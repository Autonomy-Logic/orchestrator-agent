from tools.logger import *
from . import topic
from ..emitters.heartbeat import emit_heartbeat
import asyncio

NAME = "connect"


@topic(NAME)
def init(client):
    """
    Handle the 'connect' topic to log connection establishment.
    """

    @client.on(NAME)
    async def callback():
        log_info("Connection established with the server.")
        asyncio.create_task(emit_heartbeat(client))
