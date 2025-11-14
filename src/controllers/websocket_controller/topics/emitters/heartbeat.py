from tools.logger import *
from tools.system_metrics import get_all_metrics
import asyncio
from datetime import datetime


async def emit_heartbeat(client):
    """
    Emit a heartbeat message at regular intervals.
    """
    while True:
        await asyncio.sleep(5)  # Heartbeat interval in seconds

        metrics = get_all_metrics()

        heartbeat_data = {
            "cpu_usage": metrics["cpu_usage"],
            "memory_usage": metrics["memory_usage"],
            "disk_usage": metrics["disk_usage"],
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
