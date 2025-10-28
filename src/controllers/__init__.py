from .websocket_controller import (
    init as init_websocket_controller,
    get_client as get_websocket_client,
)
from tools.logger import *


async def main_websocket_task(server_url):
    """
    Main function to connect the WebSocket client to the server.
    """
    client = await get_websocket_client()
    init_websocket_controller(client)
    await client.connect(
        f"https://{server_url}",
    )
    log_info(f"Connected to WebSocket server at {server_url}")
    await client.wait()


async def main_webrtc_task(*args, **kwargs):
    raise NotImplementedError("WebRTC task is not implemented yet.")
