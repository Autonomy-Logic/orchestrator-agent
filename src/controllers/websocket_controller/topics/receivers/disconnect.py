from tools.logger import *
from . import topic

NAME = "disconnect"


@topic(NAME)
def init(client):
    """
    Handle the 'disconnect' topic to log connection ending.
    """

    @client.on(NAME)
    async def callback():
        log_info("Connection ended by the server.")

        # Cancel the heartbeat task to prevent orphaned emit attempts
        if hasattr(client, "_heartbeat_task") and client._heartbeat_task:
            client._heartbeat_task.cancel()
            client._heartbeat_task = None
