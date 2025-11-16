from tools.logger import *
from tools.system_metrics import get_all_metrics
from tools.ssl import get_agent_id
import asyncio
from datetime import datetime


async def emit_heartbeat(client):
    """
    Emit a heartbeat message at regular intervals.
    """
    agent_id = get_agent_id()

    while True:
        await asyncio.sleep(5)

        metrics = get_all_metrics()

        heartbeat_data = {
            "agent_id": agent_id,
            "cpu_usage": metrics["cpu_usage"],
            "memory_usage": metrics["memory_usage"],
            "memory_total": metrics["memory_total"],
            "disk_usage": metrics["disk_usage"],
            "disk_total": metrics["disk_total"],
            "uptime": metrics["uptime"],
            "status": metrics["status"],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            await client.emit("heartbeat", heartbeat_data)
            log_info("Heartbeat emitted: " + str(heartbeat_data))
        except Exception as e:
            log_error(f"Failed to emit heartbeat: {e}")
            break
