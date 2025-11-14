"""
System metrics collection module for the orchestrator agent.
Provides functions to collect CPU, memory, disk usage, and uptime metrics.
"""

import psutil
import time
from typing import Dict, List

_start_time = time.time()


def get_cpu_usage() -> float:
    """
    Get the current system CPU utilization as a percentage (0-100).

    Returns:
        float: CPU utilization percentage (0-100)
    """
    return psutil.cpu_percent(interval=1)


def get_memory_usage() -> int:
    """
    Get the current system memory usage in megabytes (MB).

    Returns:
        int: Memory usage in MB
    """
    memory = psutil.virtual_memory()
    return int(memory.used / (1024 * 1024))


def get_disk_usage() -> List[Dict[str, any]]:
    """
    Get disk usage information for all mounted disks.

    Returns:
        List[Dict]: List of dictionaries containing disk information:
            - mountpoint: str - The mount point of the disk
            - total: int - Total disk space in MB
            - used: int - Used disk space in MB
            - free: int - Free disk space in MB
            - percent: float - Percentage of disk used
    """
    disk_info = []

    partitions = psutil.disk_partitions()

    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_info.append(
                {
                    "mountpoint": partition.mountpoint,
                    "total": int(usage.total / (1024 * 1024)),  # Convert to MB
                    "used": int(usage.used / (1024 * 1024)),  # Convert to MB
                    "free": int(usage.free / (1024 * 1024)),  # Convert to MB
                    "percent": usage.percent,
                }
            )
        except PermissionError:
            continue

    return disk_info


def get_uptime() -> int:
    """
    Get the uptime of the orchestrator agent in seconds.
    This represents the time since the agent started, not system uptime.

    Returns:
        int: Uptime in seconds
    """
    return int(time.time() - _start_time)


def get_status() -> str:
    """
    Get the current status of the orchestrator agent.

    Returns:
        str: Status string ("active" or "stopped")
    """
    return "active"


def get_all_metrics() -> Dict:
    """
    Get all system metrics in a single dictionary.

    Returns:
        Dict: Dictionary containing all system metrics:
            - cpu_usage: float - CPU utilization percentage (0-100)
            - memory_usage: int - Memory usage in MB
            - disk_usage: List[Dict] - List of disk usage information
            - uptime: int - Agent uptime in seconds
            - status: str - Agent status ("active" or "stopped")
    """
    return {
        "cpu_usage": get_cpu_usage(),
        "memory_usage": get_memory_usage(),
        "disk_usage": get_disk_usage(),
        "uptime": get_uptime(),
        "status": get_status(),
    }
