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
import asyncio

from bootstrap import get_context
from tools.logger import *
from tools.dns_utils import (
    calculate_backoff,
    INITIAL_SETUP_RETRY_DELAY,
)


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
    ctx = get_context()

    # Start long-lived services (once per process, not per connection attempt)
    await ctx.network_event_listener.start()
    log_info("Network event listener started")
    await ctx.lifecycle_manager.start()

    session_manager = WebRTCSessionManager()
    await start_webrtc_controller(session_manager)
    log_info("WebRTC controller started")
    await ctx.debug_session_manager.start()

    try:
        while True:
            client = None
            http_session = None
            try:
                # Create fresh client with new HTTP session for DNS refresh
                client, http_session = await get_websocket_client(dns_ttl=dns_ttl)

                # Initialize WebSocket controller (existing topics)
                init_websocket_controller(client, ctx)

                # Initialize WebRTC controller (signaling topics)
                init_webrtc_controller(
                    client, session_manager, ctx.client_registry, ctx.http_client,
                    http_client_factory=ctx.http_client_factory,
                    debug_socket_factory=ctx.debug_socket_factory,
                )

                log_info(f"[main] Calling client.connect(), client id={id(client)}, handlers={list(client.handlers.get('/', {}).keys()) if hasattr(client, 'handlers') else 'N/A'}")
                await client.connect(
                    f"https://{server_url}",
                )
                log_info(f"Connected to WebSocket server at {server_url}, connected={client.connected}")
                await client.wait()

            except Exception as e:
                log_error(f"Connection error: {e}")
            finally:
                # Always close the HTTP session to prevent leaks.
                # We hold our own reference since client.http may not be set
                # if the connection failed before socketio stored it.
                if http_session is not None and not http_session.closed:
                    try:
                        await http_session.close()
                    except Exception:
                        pass

            # Calculate retry delay
            if not ctx.connection_state.has_ever_connected:
                delay = INITIAL_SETUP_RETRY_DELAY
                log_warning(
                    f"Waiting for backend to accept connection... "
                    f"retrying in {delay:.0f}s"
                )
            else:
                delay = calculate_backoff(ctx.connection_state.reconnect_attempt)
                log_warning(f"Reconnecting in {delay:.1f}s...")
                ctx.connection_state.increment_reconnect_attempt()

            await asyncio.sleep(delay)

    finally:
        log_info("Cleaning up controllers...")
        await ctx.lifecycle_manager.stop()
        await ctx.debug_session_manager.stop()
        await stop_webrtc_controller(session_manager)
        log_info("Controllers stopped")


def run_websocket_with_reconnection(server_url: str, run_task):
    """
    Run the WebSocket connection task.

    The retry logic is inside main_websocket_task (async), keeping everything
    in a single event loop. This function is the sync entry point.

    Args:
        server_url: The server URL to connect to (host:port format)
        run_task: Function to run the async task (e.g., asyncio.run)
    """
    try:
        run_task(main_websocket_task(server_url))
    except KeyboardInterrupt:
        log_warning("Keyboard interrupt received. Exiting.")
    except Exception as e:
        log_error(f"Fatal error: {e}")


async def main_webrtc_task(*args, **kwargs):
    """
    Placeholder for standalone WebRTC task.
    Currently WebRTC is integrated into main_websocket_task.
    """
    raise NotImplementedError(
        "WebRTC is integrated into main_websocket_task. "
        "Use main_websocket_task instead."
    )


