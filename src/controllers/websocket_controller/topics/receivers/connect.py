from tools.logger import *
from tools.ssl import get_agent_id
from . import topic
from ..emitters.heartbeat import emit_heartbeat
import asyncio

NAME = "connect"


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'connect' topic to log connection establishment.
    """
    agent_id = get_agent_id()

    @client.on(NAME)
    async def callback():
        log_info("Connection established with the server.")

        # Signal to the reconnection loop that we've been accepted.
        # Switches from rapid-retry (initial setup) to exponential backoff.
        ctx.connection_state["has_ever_connected"] = True
        ctx._reconnect_attempt = 0

        # Cancel any orphaned heartbeat task from a previous connection
        if ctx.heartbeat_task:
            ctx.heartbeat_task.cancel()

        ctx.heartbeat_task = asyncio.create_task(emit_heartbeat(
            client,
            agent_id,
            ctx.usage_buffer,
            ctx.devices_usage_buffer,
            ctx.container_runtime,
        ))
