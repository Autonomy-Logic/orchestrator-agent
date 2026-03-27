"""
WebRTC Controller

Manages WebRTC peer connections for real-time communication with runtime containers.
Signaling is handled via the existing Socket.IO connection to the cloud.
"""

from tools.logger import log_info

from .signaling import initialize_signaling
from .session_manager import WebRTCSessionManager


def init(client, session_manager: WebRTCSessionManager, client_registry, http_client,
         *, http_client_factory=None, debug_socket_factory=None,
         debug_session_manager=None):
    """
    Initialize the WebRTC controller by registering signaling handlers.

    Args:
        client: Socket.IO client for signaling
        session_manager: WebRTCSessionManager instance
        client_registry: ClientRepo instance for device lookups
        http_client: HTTPClientRepo instance for command execution
        http_client_factory: Callable returning a new HTTPClientRepo (for debug sessions)
        debug_socket_factory: Callable returning a new DebugSocketRepo (for debug sessions)
        debug_session_manager: DebugSessionManager for debug session lifecycle
    """
    log_info("Initializing WebRTC Controller...")
    initialize_signaling(
        client, session_manager, client_registry, http_client,
        http_client_factory=http_client_factory,
        debug_socket_factory=debug_socket_factory,
        debug_session_manager=debug_session_manager,
    )
    log_info("WebRTC Controller initialized successfully.")


async def start(session_manager: WebRTCSessionManager):
    """
    Start the WebRTC controller background tasks.

    Args:
        session_manager: WebRTCSessionManager instance
    """
    await session_manager.start()


async def stop(session_manager: WebRTCSessionManager):
    """
    Stop the WebRTC controller.

    Args:
        session_manager: WebRTCSessionManager instance
    """
    await session_manager.stop()
