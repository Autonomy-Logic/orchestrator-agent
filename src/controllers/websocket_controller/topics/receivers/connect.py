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
    log_info(f"[connect] Registering connect handler on client {id(client)}")

    @client.on(NAME)
    async def callback():
        log_info(f"[connect] Connect event fired on client {id(client)}, connected={client.connected}")
        log_info("Connection established with the server.")

        # Signal to the reconnection loop that we've been accepted.
        # Switches from rapid-retry (initial setup) to exponential backoff
        # and resets the reconnect attempt counter.
        ctx.connection_state.mark_connected()

        # Cancel any orphaned heartbeat task from a previous connection
        ctx.connection_state.cancel_heartbeat_task()

        ctx.connection_state.set_heartbeat_task(asyncio.create_task(
            emit_heartbeat(
                client,
                agent_id,
                ctx.usage_buffer,
                ctx.devices_usage_buffer,
                ctx.container_runtime,
            )
        ))
