"""
WebRTC Signaling Module

Handles WebRTC signaling messages (offer, answer, ICE candidates) via Socket.IO.
"""

from .offer_handler import init as init_offer_handler
from .ice_handler import init as init_ice_handler
from .disconnect_handler import init as init_disconnect_handler


def initialize_signaling(client, session_manager):
    """
    Initialize all signaling handlers.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
    """
    init_offer_handler(client, session_manager)
    init_ice_handler(client, session_manager)
    init_disconnect_handler(client, session_manager)
