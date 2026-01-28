"""
WebRTC Controller

Manages WebRTC peer connections for real-time communication with runtime containers.
Signaling is handled via the existing Socket.IO connection to the cloud.
"""

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from tools.logger import log_info, log_debug, log_error, log_warning
from typing import Dict, Optional, Callable
from enum import Enum
from datetime import datetime, timedelta
import asyncio


class SessionState(Enum):
    """WebRTC session states."""
    CREATED = "created"           # Session created, waiting for offer
    CONNECTING = "connecting"     # Offer received, establishing connection
    CONNECTED = "connected"       # Data channel open, ready for communication
    DISCONNECTED = "disconnected" # Connection lost
    CLOSED = "closed"             # Session closed


# Session timeout in seconds (close inactive sessions)
SESSION_TIMEOUT_SECONDS = 300  # 5 minutes
# How often to check for stale sessions
CLEANUP_INTERVAL_SECONDS = 60  # 1 minute


class WebRTCSessionManager:
    """
    Manages WebRTC peer connection sessions.

    Each session represents a WebRTC connection to a specific runtime container.
    Sessions are identified by a unique session_id provided by the signaling server.
    """

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._on_session_closed: Optional[Callable] = None

    async def start(self):
        """Start the session manager background tasks."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            log_info("WebRTC session cleanup task started")

    async def stop(self):
        """Stop the session manager and close all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        await self.close_all_sessions()
        log_info("WebRTC session manager stopped")

    async def _cleanup_loop(self):
        """Background task to clean up stale sessions."""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                await self._cleanup_stale_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Error in session cleanup loop: {e}")

    async def _cleanup_stale_sessions(self):
        """Close sessions that have been inactive for too long."""
        now = datetime.now()
        timeout = timedelta(seconds=SESSION_TIMEOUT_SECONDS)
        stale_sessions = []

        for session_id, session in self._sessions.items():
            last_activity = session.get("last_activity", session["created_at"])
            if now - last_activity > timeout:
                stale_sessions.append(session_id)

        for session_id in stale_sessions:
            log_warning(f"Closing stale WebRTC session {session_id} (inactive > {SESSION_TIMEOUT_SECONDS}s)")
            await self.close_session(session_id, reason="timeout")

    async def create_session(self, session_id: str, device_id: str) -> RTCPeerConnection:
        """
        Create a new WebRTC session for a device.

        Args:
            session_id: Unique identifier for this session
            device_id: Target runtime container identifier

        Returns:
            RTCPeerConnection instance for this session
        """
        async with self._lock:
            if session_id in self._sessions:
                log_warning(f"Session {session_id} already exists, closing existing")
                await self._close_session_unlocked(session_id, reason="replaced")

            pc = RTCPeerConnection()
            now = datetime.now()

            self._sessions[session_id] = {
                "pc": pc,
                "device_id": device_id,
                "data_channel": None,
                "keepalive_channel": None,
                "state": SessionState.CREATED,
                "created_at": now,
                "last_activity": now,
                "ice_connection_state": "new",
                "connection_state": "new",
            }

            log_info(f"Created WebRTC session {session_id} for device {device_id}")
            return pc

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_peer_connection(self, session_id: str) -> Optional[RTCPeerConnection]:
        """Get peer connection for a session."""
        session = self._sessions.get(session_id)
        return session["pc"] if session else None

    def update_session_state(self, session_id: str, state: SessionState) -> bool:
        """Update the state of a session."""
        session = self._sessions.get(session_id)
        if session:
            old_state = session["state"]
            session["state"] = state
            session["last_activity"] = datetime.now()
            log_debug(f"Session {session_id} state: {old_state.value} -> {state.value}")
            return True
        return False

    def update_connection_state(self, session_id: str, connection_state: str, ice_state: str = None) -> bool:
        """Update the connection states of a session."""
        session = self._sessions.get(session_id)
        if session:
            session["connection_state"] = connection_state
            if ice_state:
                session["ice_connection_state"] = ice_state
            session["last_activity"] = datetime.now()

            # Update session state based on connection state
            if connection_state == "connected":
                session["state"] = SessionState.CONNECTED
            elif connection_state == "failed" or connection_state == "disconnected":
                session["state"] = SessionState.DISCONNECTED
            elif connection_state == "connecting":
                session["state"] = SessionState.CONNECTING
            return True
        return False

    def touch_session(self, session_id: str) -> bool:
        """Update last activity timestamp for a session."""
        session = self._sessions.get(session_id)
        if session:
            session["last_activity"] = datetime.now()
            return True
        return False

    async def _close_session_unlocked(self, session_id: str, reason: str = "requested") -> bool:
        """Close a session without acquiring lock (internal use)."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        session["state"] = SessionState.CLOSED
        pc = session["pc"]

        # Close keepalive channel if exists
        keepalive_channel = session.get("keepalive_channel")
        if keepalive_channel:
            try:
                keepalive_channel.close()
            except Exception as e:
                log_debug(f"Error closing keepalive channel: {e}")

        # Close peer connection
        try:
            await pc.close()
            log_info(f"Closed WebRTC session {session_id} (reason: {reason})")
        except Exception as e:
            log_error(f"Error closing peer connection for session {session_id}: {e}")

        # Notify callback if registered
        if self._on_session_closed:
            try:
                self._on_session_closed(session_id, reason)
            except Exception as e:
                log_error(f"Error in session closed callback: {e}")

        return True

    async def close_session(self, session_id: str, reason: str = "requested") -> bool:
        """
        Close and cleanup a WebRTC session.

        Args:
            session_id: Session to close
            reason: Reason for closing (for logging)

        Returns:
            True if session was closed, False if not found
        """
        async with self._lock:
            result = await self._close_session_unlocked(session_id, reason)
            if not result:
                log_warning(f"Session {session_id} not found for closing")
            return result

    async def close_all_sessions(self):
        """Close all active sessions."""
        async with self._lock:
            session_ids = list(self._sessions.keys())
            for session_id in session_ids:
                await self._close_session_unlocked(session_id, reason="shutdown")
        log_info("All WebRTC sessions closed")

    def list_sessions(self) -> Dict[str, dict]:
        """List all active sessions with their info."""
        return {
            sid: {
                "device_id": session["device_id"],
                "state": session["state"].value,
                "connection_state": session["connection_state"],
                "created_at": session["created_at"].isoformat(),
            }
            for sid, session in self._sessions.items()
        }

    def get_session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    def set_data_channel(self, session_id: str, channel) -> bool:
        """Associate a data channel with a session."""
        session = self._sessions.get(session_id)
        if session:
            session["data_channel"] = channel
            session["last_activity"] = datetime.now()
            return True
        return False

    def set_keepalive_channel(self, session_id: str, keepalive_channel) -> bool:
        """Associate a keepalive channel with a session."""
        session = self._sessions.get(session_id)
        if session:
            session["keepalive_channel"] = keepalive_channel
            session["last_activity"] = datetime.now()
            return True
        return False

    def get_keepalive_channel(self, session_id: str):
        """Get the keepalive channel for a session."""
        session = self._sessions.get(session_id)
        return session.get("keepalive_channel") if session else None

    def on_session_closed(self, callback: Callable):
        """Register a callback for when sessions are closed."""
        self._on_session_closed = callback


# Global session manager instance
session_manager = WebRTCSessionManager()


def init(client):
    """
    Initialize the WebRTC controller by registering signaling handlers.

    Args:
        client: Socket.IO client for signaling
    """
    from .signaling import initialize_signaling

    log_info("Initializing WebRTC Controller...")
    initialize_signaling(client, session_manager)
    log_info("WebRTC Controller initialized successfully.")


async def start():
    """Start the WebRTC controller background tasks."""
    await session_manager.start()


async def stop():
    """Stop the WebRTC controller."""
    await session_manager.stop()
