"""
WebRTC Session Manager

Manages WebRTC peer connection sessions for real-time communication
with runtime containers.
"""

from aiortc import RTCPeerConnection
from tools.logger import log_info, log_debug, log_error, log_warning
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
import asyncio

from .types import (
    SessionState,
    SESSION_TIMEOUT_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    ICE_SERVERS,
)


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
        stale_sessions = []

        # Take a snapshot of stale sessions while holding the lock to avoid
        # concurrent modification of self._sessions during iteration
        async with self._lock:
            now = datetime.now()
            timeout = timedelta(seconds=SESSION_TIMEOUT_SECONDS)

            for session_id, session in self._sessions.items():
                last_activity = session.get("last_activity", session["created_at"])
                if now - last_activity > timeout:
                    stale_sessions.append(session_id)

        # Close the identified stale sessions outside the lock
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
        # Check for existing session and remove it under the lock,
        # but close the peer connection outside to avoid blocking other operations.
        existing_session = None
        async with self._lock:
            if session_id in self._sessions:
                log_warning(f"Session {session_id} already exists, closing existing")
                existing_session = self._sessions.pop(session_id, None)

        # Close existing session's peer connection outside the lock
        if existing_session:
            existing_session["state"] = SessionState.CLOSED
            channel_handler = existing_session.get("channel_handler")
            if channel_handler:
                try:
                    channel_handler.close()
                except Exception as e:
                    log_debug(f"Error closing channel handler: {e}")
            try:
                await existing_session["pc"].close()
                log_info(f"Closed replaced session {session_id}")
            except Exception as e:
                log_error(f"Error closing replaced session {session_id}: {e}")

        async with self._lock:
            pc = RTCPeerConnection(configuration=ICE_SERVERS)
            now = datetime.now()

            self._sessions[session_id] = {
                "pc": pc,
                "device_id": device_id,
                "data_channel": None,
                "channel_handler": None,
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

        # Close channel handler if exists
        channel_handler = session.get("channel_handler")
        if channel_handler:
            try:
                channel_handler.close()
            except Exception as e:
                log_debug(f"Error closing channel handler: {e}")

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
        # Snapshot session IDs under lock, then close each outside to avoid
        # holding the lock across awaited pc.close() calls.
        async with self._lock:
            session_ids = list(self._sessions.keys())

        for session_id in session_ids:
            await self.close_session(session_id, reason="shutdown")
        log_info("All WebRTC sessions closed")

    def list_sessions(self) -> Dict[str, dict]:
        """List all active sessions with their info."""
        return {
            sid: {
                "device_id": session["device_id"],
                "state": session["state"].value,
                "connection_state": session["connection_state"],
                "created_at": session["created_at"].isoformat(),
                "last_activity": session.get("last_activity", session["created_at"]).isoformat(),
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

    def set_channel_handler(self, session_id: str, channel_handler) -> bool:
        """Associate a data channel handler with a session."""
        session = self._sessions.get(session_id)
        if session:
            session["channel_handler"] = channel_handler
            session["last_activity"] = datetime.now()
            return True
        return False

    def get_channel_handler(self, session_id: str):
        """Get the data channel handler for a session."""
        session = self._sessions.get(session_id)
        return session.get("channel_handler") if session else None

    def on_session_closed(self, callback: Callable):
        """Register a callback for when sessions are closed."""
        self._on_session_closed = callback
