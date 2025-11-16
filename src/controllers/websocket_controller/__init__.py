from .topics import initialize_all
from tools.ssl import get_ssl_session
from tools.logger import *
import socketio


def init(client):
    """
    Initialize the Websocket controller by registering necessary topics.
    """
    log_info("Initializing Websocket Controller...")

    initialize_all(client)

    log_info("Websocket Controller initialized successfully.")


async def get_client():
    return socketio.AsyncClient(
        reconnection=True,
        reconnection_attempts=0,
        reconnection_delay=1,
        reconnection_delay_max=5,
        http_session=get_ssl_session(),
    )
