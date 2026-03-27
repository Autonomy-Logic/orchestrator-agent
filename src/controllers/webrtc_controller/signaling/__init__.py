"""
WebRTC Signaling Module

Handles WebRTC signaling messages (offer, answer, ICE candidates) via Socket.IO.
"""

from .offer_handler import init as init_offer_handler
from .ice_handler import init as init_ice_handler
from .disconnect_handler import init as init_disconnect_handler


def initialize_signaling(client, session_manager, client_registry, http_client,
                         *, http_client_factory=None, debug_socket_factory=None,
                         debug_session_manager=None):
    """
    Initialize all signaling handlers.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
        client_registry: ClientRepo instance for device lookups
        http_client: HTTPClientRepo instance for command execution
        http_client_factory: Callable returning a new HTTPClientRepo (for debug sessions)
        debug_socket_factory: Callable returning a new DebugSocketRepo (for debug sessions)
        debug_session_manager: DebugSessionManager for debug session lifecycle
    """
    init_offer_handler(
        client, session_manager, client_registry, http_client,
        http_client_factory=http_client_factory,
        debug_socket_factory=debug_socket_factory,
        debug_session_manager=debug_session_manager,
    )
    init_ice_handler(client, session_manager)
    init_disconnect_handler(client, session_manager)
