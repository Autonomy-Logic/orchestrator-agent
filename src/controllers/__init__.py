from .websocket_controller import (
    init as init_websocket_controller,
    get_client as get_websocket_client,
)
from .webrtc_controller import (
    init as init_webrtc_controller,
    start as start_webrtc_controller,
    stop as stop_webrtc_controller,
    WebRTCSessionManager,
)
from bootstrap import get_context
from tools.logger import *
from tools.dns_utils import (
    perform_dns_health_check,
    calculate_backoff,
    is_dns_error,
)
from time import sleep


async def main_websocket_task(server_url: str, dns_ttl: int = 30):
    """
    Main function to connect the WebSocket client to the server.
    Initializes both WebSocket and WebRTC controllers.

    Creates a fresh Socket.IO client and HTTP session for each connection
    attempt. This ensures DNS is re-resolved after network changes.

    Args:
        server_url: The server URL to connect to (host:port format)
        dns_ttl: DNS cache TTL in seconds. Lower values help with network
                changes but increase DNS queries.
    """
    client = None
    try:
        # Initialize composition root (creates all adapters)
        ctx = get_context()

        # Create fresh client with new HTTP session for DNS refresh
        client = await get_websocket_client(dns_ttl=dns_ttl)

        # Initialize WebSocket controller (existing topics)
        init_websocket_controller(client, ctx)

        # Initialize WebRTC controller (signaling topics)
        session_manager = WebRTCSessionManager()
        init_webrtc_controller(
            client, session_manager, ctx.client_registry, ctx.http_client,
            http_client_factory=ctx.http_client_factory,
            debug_socket_factory=ctx.debug_socket_factory,
            debug_session_manager=ctx.debug_session_manager,
        )

        # Start network event listener
        await ctx.network_event_listener.start()
        log_info("Network event listener started")

        # Start WebRTC session manager background tasks
        await start_webrtc_controller(session_manager)
        log_info("WebRTC controller started")

        # Start debug session manager (HTTP fallback for debug commands)
        await ctx.debug_session_manager.start()

        await client.connect(
            f"https://{server_url}",
        )
        log_info(f"Connected to WebSocket server at {server_url}")
        await client.wait()
    finally:
        # Cleanup controllers on disconnect
        log_info("Cleaning up controllers...")
        await ctx.debug_session_manager.stop()
        await stop_webrtc_controller(session_manager)
        log_info("Controllers stopped")

        # Cleanup: close HTTP session to release resources
        if client is not None:
            try:
                if client.http and not client.http.closed:
                    await client.http.close()
                    log_debug("Closed HTTP session")
            except Exception as e:
                log_debug(f"Error closing HTTP session: {e}")


def run_websocket_with_reconnection(server_url: str, run_task):
    """
    Run WebSocket connection with automatic reconnection and DNS health checks.

    Manages the reconnection loop with exponential backoff and DNS health checks
    to handle network transitions gracefully.

    Args:
        server_url: The server URL to connect to (host:port format)
        run_task: Function to run the async task (e.g., asyncio.run)
    """
    reconnect_attempt = 0
    ctx = get_context()

    while True:
        try:
            # DNS health check before attempting connection
            if not perform_dns_health_check(server_url, reconnect_attempt, socket_repo=ctx.socket_repo):
                delay = calculate_backoff(reconnect_attempt)
                log_warning(f"Waiting {delay:.1f}s before next attempt...")
                sleep(delay)
                reconnect_attempt += 1
                continue

            log_info(f"Attempting to connect to server at {server_url}...")
            run_task(main_websocket_task(server_url))

            # Connection closed normally, reset attempt counter
            reconnect_attempt = 0

        except KeyboardInterrupt:
            log_warning("Keyboard interrupt received. Closing connection and exiting.")
            break
        except Exception as e:
            log_error(f"Error on websocket interface: {e}")

            # DNS errors get longer delays to allow network to stabilize
            if is_dns_error(e):
                delay = calculate_backoff(reconnect_attempt + 2)
                log_warning(
                    f"DNS-related error detected. Waiting {delay:.1f}s to allow network to stabilize..."
                )
            else:
                delay = calculate_backoff(reconnect_attempt)
                log_warning(f"Reconnecting in {delay:.1f}s (attempt {reconnect_attempt + 1})...")

            sleep(delay)
            reconnect_attempt += 1


async def main_webrtc_task(*args, **kwargs):
    """
    Placeholder for standalone WebRTC task.
    Currently WebRTC is integrated into main_websocket_task.
    """
    raise NotImplementedError(
        "WebRTC is integrated into main_websocket_task. "
        "Use main_websocket_task instead."
    )


