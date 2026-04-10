from .topics import initialize_all
from tools.ssl import get_ssl_session
from tools.logger import *
import socketio
import logging


class HeartbeatFilter(logging.Filter):
    """Filter to suppress heartbeat-related log messages from socketio/engineio."""

    def filter(self, record):
        message = record.getMessage().lower()
        if "heartbeat" in message:
            return False
        if '"heartbeat"' in message or "'heartbeat'" in message:
            return False
        return True


def _configure_socketio_logging():
    """Configure socketio and engineio loggers to filter heartbeat messages."""
    heartbeat_filter = HeartbeatFilter()

    for logger_name in ["socketio", "engineio", "socketio.client", "engineio.client"]:
        logger = logging.getLogger(logger_name)
        logger.addFilter(heartbeat_filter)


def init(client, ctx):
    """
    Initialize the Websocket controller by registering necessary topics.
    """
    log_info("Initializing Websocket Controller...")

    initialize_all(client, ctx)

    log_info("Websocket Controller initialized successfully.")


async def get_client(dns_ttl: int = 30):
    """
    Create a new Socket.IO AsyncClient with fresh HTTP session.

    This should be called for each new connection attempt to ensure
    fresh DNS resolution after network changes.

    Args:
        dns_ttl: DNS cache TTL in seconds for the underlying aiohttp session.
                Lower values help recover from network changes faster.

    Returns:
        Tuple of (AsyncClient, aiohttp.ClientSession). The caller must close
        the session when done (even if the connection fails).
    """
    _configure_socketio_logging()

    # Create fresh HTTP session with short DNS TTL
    # This helps recover from network changes by not caching stale DNS
    http_session = get_ssl_session(ttl_dns_cache=dns_ttl)

    client = socketio.AsyncClient(
        reconnection=False,
        http_session=http_session,
        logger=True,
        engineio_logger=True,
    )

    @client.event
    async def connect_error(data):
        log_error(f"Socket.IO connection error: {data}")

    return client, http_session
