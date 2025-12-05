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


def init(client):
    """
    Initialize the Websocket controller by registering necessary topics.
    """
    log_info("Initializing Websocket Controller...")

    initialize_all(client)

    log_info("Websocket Controller initialized successfully.")


async def get_client():
    _configure_socketio_logging()

    client = socketio.AsyncClient(
        reconnection=True,
        reconnection_attempts=0,
        reconnection_delay=1,
        reconnection_delay_max=5,
        http_session=get_ssl_session(),
        logger=True,
        engineio_logger=True,
    )

    @client.event
    async def connect_error(data):
        log_error(f"Socket.IO connection error: {data}")

    return client
