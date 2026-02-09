"""
WebRTC Controller Types

Shared types and constants for the WebRTC controller module.
This module has no internal dependencies to avoid circular imports.
"""

from enum import Enum
from aiortc import RTCConfiguration, RTCIceServer


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

# STUN servers for NAT traversal (same as openplc-web)
ICE_SERVERS = RTCConfiguration([
    RTCIceServer(urls=['stun:stun.l.google.com:19302']),
    RTCIceServer(urls=['stun:stun1.l.google.com:19302']),
])
