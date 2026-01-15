"""
WebRTC Controller

Manages WebRTC peer connections for remote terminal access to runtime containers.
Signaling is handled via the existing Socket.IO connection to the cloud.
"""

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from tools.logger import log_info, log_debug, log_error, log_warning
from typing import Dict, Optional
import asyncio


class WebRTCSessionManager:
    """
    Manages WebRTC peer connection sessions.

    Each session represents a terminal connection to a specific runtime container.
    Sessions are identified by a unique session_id provided by the signaling server.
    """

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

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
                await self.close_session(session_id)

            pc = RTCPeerConnection()

            self._sessions[session_id] = {
                "pc": pc,
                "device_id": device_id,
                "data_channel": None,
                "pty_session": None,
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

    async def close_session(self, session_id: str) -> bool:
        """
        Close and cleanup a WebRTC session.

        Args:
            session_id: Session to close

        Returns:
            True if session was closed, False if not found
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if not session:
                log_warning(f"Session {session_id} not found for closing")
                return False

            pc = session["pc"]
            try:
                await pc.close()
                log_info(f"Closed WebRTC session {session_id}")
            except Exception as e:
                log_error(f"Error closing session {session_id}: {e}")

            return True

    async def close_all_sessions(self):
        """Close all active sessions."""
        session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id)
        log_info("All WebRTC sessions closed")

    def list_sessions(self) -> Dict[str, str]:
        """List all active sessions with their device IDs."""
        return {
            sid: session["device_id"]
            for sid, session in self._sessions.items()
        }

    def set_data_channel(self, session_id: str, channel) -> bool:
        """Associate a data channel with a session."""
        session = self._sessions.get(session_id)
        if session:
            session["data_channel"] = channel
            return True
        return False

    def set_pty_session(self, session_id: str, pty_session) -> bool:
        """Associate a PTY session with a WebRTC session."""
        session = self._sessions.get(session_id)
        if session:
            session["pty_session"] = pty_session
            return True
        return False


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
