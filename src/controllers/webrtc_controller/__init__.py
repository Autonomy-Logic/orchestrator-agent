"""
WebRTC Controller

Manages WebRTC peer connections for real-time communication with runtime containers.
Signaling is handled via the existing Socket.IO connection to the cloud.
"""

from tools.logger import log_info

from .session_manager import (
    WebRTCSessionManager,
    get_session_manager,
)


def init(client, session_manager: WebRTCSessionManager = None):
    """
    Initialize the WebRTC controller by registering signaling handlers.

    Args:
        client: Socket.IO client for signaling
        session_manager: Optional WebRTCSessionManager instance for dependency injection.
                        If not provided, uses the global singleton.
    """
    from .signaling import initialize_signaling

    if session_manager is None:
        session_manager = get_session_manager()

    log_info("Initializing WebRTC Controller...")
    initialize_signaling(client, session_manager)
    log_info("WebRTC Controller initialized successfully.")


async def start(session_manager: WebRTCSessionManager = None):
    """
    Start the WebRTC controller background tasks.

    Args:
        session_manager: Optional WebRTCSessionManager instance.
                        If not provided, uses the global singleton.
    """
    if session_manager is None:
        session_manager = get_session_manager()
    await session_manager.start()


async def stop(session_manager: WebRTCSessionManager = None):
    """
    Stop the WebRTC controller.

    Args:
        session_manager: Optional WebRTCSessionManager instance.
                        If not provided, uses the global singleton.
    """
    if session_manager is None:
        session_manager = get_session_manager()
    await session_manager.stop()
