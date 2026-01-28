from .websocket_controller import (
    init as init_websocket_controller,
    get_client as get_websocket_client,
)
from .webrtc_controller import (
    init as init_webrtc_controller,
    start as start_webrtc_controller,
    stop as stop_webrtc_controller,
    session_manager as webrtc_session_manager,
)
from tools.logger import log_info, log_warning, log_error
from tools.network_event_listener import network_event_listener


async def main_websocket_task(server_url):
    """
    Main function to connect the WebSocket client to the server.
    Initializes both WebSocket and WebRTC controllers.
    """
    client = await get_websocket_client()

    # Initialize WebSocket controller (existing topics)
    init_websocket_controller(client)

    # Initialize WebRTC controller (signaling topics)
    init_webrtc_controller(client)

    # Start network event listener
    await network_event_listener.start()
    log_info("Network event listener started")

    # Start WebRTC session manager background tasks
    await start_webrtc_controller()
    log_info("WebRTC controller started")

    try:
        await client.connect(
            f"https://{server_url}",
        )
        log_info(f"Connected to WebSocket server at {server_url}")
        await client.wait()
    finally:
        # Cleanup on disconnect
        log_info("Cleaning up controllers...")
        await stop_webrtc_controller()
        log_info("WebRTC controller stopped")


async def main_webrtc_task(*args, **kwargs):
    """
    Placeholder for standalone WebRTC task.
    Currently WebRTC is integrated into main_websocket_task.
    """
    raise NotImplementedError(
        "WebRTC is integrated into main_websocket_task. "
        "Use main_websocket_task instead."
    )


def get_webrtc_session_manager():
    """Get the WebRTC session manager instance."""
    return webrtc_session_manager
