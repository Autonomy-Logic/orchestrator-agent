from tools.logger import *
from tools.system_metrics import get_all_metrics
from tools.ssl import get_agent_id
from tools.usage_buffer import get_usage_buffer
from tools.devices_usage_buffer import get_devices_usage_buffer
from tools.docker_tools import CLIENT
import asyncio
from datetime import datetime


def _collect_device_stats(device_id: str) -> tuple:
    """
    Collect CPU and memory usage stats for a Docker container.

    Args:
        device_id: The container name/ID

    Returns:
        tuple: (cpu_percent, memory_mb) or (None, None) if stats cannot be collected
    """
    try:
        container = CLIENT.containers.get(device_id)
        if container.status != "running":
            return None, None

        stats = container.stats(stream=False)

        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )

        cpu_percent = 0.0
        if system_delta > 0 and cpu_delta > 0:
            num_cpus = stats["cpu_stats"].get("online_cpus", 1)
            if num_cpus is None:
                num_cpus = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0

        memory_usage = stats["memory_stats"].get("usage", 0)
        memory_mb = memory_usage / (1024 * 1024)

        return cpu_percent, memory_mb

    except Exception as e:
        log_debug(f"Could not collect stats for device {device_id}: {e}")
        return None, None


def _collect_all_device_stats(devices_buffer):
    """
    Collect stats for all registered devices and add samples to the buffer.

    Args:
        devices_buffer: The DevicesUsageBuffer instance
    """
    device_ids = devices_buffer.get_device_ids()

    for device_id in device_ids:
        cpu_percent, memory_mb = _collect_device_stats(device_id)
        if cpu_percent is not None and memory_mb is not None:
            devices_buffer.add_sample(device_id, cpu_percent, memory_mb)


async def emit_heartbeat(client):
    """
    Emit a heartbeat message at regular intervals.
    Also logs CPU and memory usage to the circular buffer for both
    the orchestrator agent and all managed devices.
    """
    agent_id = get_agent_id()
    usage_buffer = get_usage_buffer()
    devices_buffer = get_devices_usage_buffer()

    while True:
        await asyncio.sleep(5)

        metrics = get_all_metrics()

        memory_mb = metrics["memory_usage"] * 1024
        usage_buffer.add_sample(metrics["cpu_usage"], memory_mb)

        await asyncio.to_thread(_collect_all_device_stats, devices_buffer)

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
