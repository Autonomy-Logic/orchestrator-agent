from tools.logger import *
import asyncio
from datetime import datetime


async def emit_heartbeat(client):
    """
    Emit a heartbeat message at regular intervals.
    """
    while True:
        await asyncio.sleep(5)  # Heartbeat interval in seconds

        heartbeat_data = {
            "cpu_usage": 0.5,  # Example CPU usage
            "memory_usage": 256,  # Example memory usage in MB
            "disk_usage": 1024,  # Example disk usage in MB
            "timestamp": datetime.now().isoformat(),  # Current timestamp
        }

        try:
            await client.emit("heartbeat", heartbeat_data)
            log_info("Heartbeat emitted: " + str(heartbeat_data))
        except Exception as e:
            log_error(f"Failed to emit heartbeat: {e}")
            break
