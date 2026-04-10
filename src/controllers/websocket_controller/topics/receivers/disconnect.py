from tools.logger import *
from . import topic

NAME = "disconnect"


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'disconnect' topic to log connection ending.
    """

    @client.on(NAME)
    async def callback():
        log_info("Connection ended by the server.")

        # Cancel the heartbeat task to prevent orphaned emit attempts
        if ctx.heartbeat_task:
            ctx.heartbeat_task.cancel()
            ctx.heartbeat_task = None
