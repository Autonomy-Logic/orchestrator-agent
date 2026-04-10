from tools.logger import log_error
from tools.system_metrics import get_all_metrics
from use_cases.collect_device_stats import collect_all_device_stats
import asyncio
import os
from datetime import datetime

# Stop the heartbeat task after this many consecutive emit failures.
# Tolerates transient errors (1-2 glitches) but stops if the connection
# is genuinely dead to avoid infinite error log spam.
MAX_CONSECUTIVE_FAILURES = 3


async def emit_heartbeat(client, agent_id, usage_buffer, devices_usage_buffer, container_runtime):
    """
    Emit a heartbeat message at regular intervals.
    Also logs CPU and memory usage to the circular buffer for both
    the orchestrator agent and all managed devices.

    Tolerates transient emit failures and only stops after
    MAX_CONSECUTIVE_FAILURES in a row or when the client disconnects.
    """
    consecutive_failures = 0

    while True:
        await asyncio.sleep(5)

        if not client.connected:
            break

        metrics = get_all_metrics()

        memory_mb = metrics["memory_usage"] * 1024
        usage_buffer.add_sample(metrics["cpu_usage"], memory_mb)

        await asyncio.to_thread(
            collect_all_device_stats, devices_usage_buffer, container_runtime=container_runtime
        )

        heartbeat_data = {
            "agent_id": agent_id,
            "agent_version": os.getenv("AGENT_VERSION", "unknown"),
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
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            log_error(
                f"Failed to emit heartbeat "
                f"({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}"
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log_error("Heartbeat failed too many times, stopping")
                break
