"""
System metrics collection module for the orchestrator agent.
Provides functions to collect CPU, memory, disk usage, and uptime metrics.
"""

import psutil
import time
from typing import Dict, List

_start_time = time.time()


def _calculate_memory_total() -> float:
    """Calculate total system memory at module load time."""
    memory = psutil.virtual_memory()
    return round(memory.total / (1024 * 1024 * 1024), 1)


def _calculate_disk_total() -> float:
    """Calculate total disk space at module load time."""
    total_space = 0
    partitions = psutil.disk_partitions()

    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            total_space += usage.total
        except PermissionError:
            continue

    return round(total_space / (1024 * 1024 * 1024), 1)


_memory_total = _calculate_memory_total()
_disk_total = _calculate_disk_total()


def get_cpu_usage() -> float:
    """
    Get the current system CPU utilization as a percentage (0-100).

    Returns:
        float: CPU utilization percentage (0-100)
    """
    return psutil.cpu_percent(interval=1)


def get_memory_usage() -> float:
    """
    Get the current system memory usage in gigabytes (GB).

    Returns:
        float: Memory usage in GB (rounded to 1 decimal place)
    """
    memory = psutil.virtual_memory()
    return round(memory.used / (1024 * 1024 * 1024), 1)


def get_memory_total() -> float:
    """
    Get the total system memory in gigabytes (GB).
    This value is cached at module load time for efficiency.

    Returns:
        float: Total memory in GB (rounded to 1 decimal place)
    """
    return _memory_total


def get_disk_usage() -> float:
    """
    Get total disk usage across all mounted disks in gigabytes (GB).

    Returns:
        float: Total disk usage in GB (rounded to 1 decimal place)
    """
    total_used = 0
    partitions = psutil.disk_partitions()

    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            total_used += usage.used
        except PermissionError:
            continue

    return round(total_used / (1024 * 1024 * 1024), 1)


def get_disk_total() -> float:
    """
    Get total disk space across all mounted disks in gigabytes (GB).
    This value is cached at module load time for efficiency.

    Returns:
        float: Total disk space in GB (rounded to 1 decimal place)
    """
    return _disk_total


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
            - memory_usage: float - Memory usage in GB
            - memory_total: float - Total memory in GB
            - disk_usage: float - Total disk usage in GB
            - disk_total: float - Total disk space in GB
            - uptime: int - Agent uptime in seconds
            - status: str - Agent status ("active" or "stopped")
    """
    return {
        "cpu_usage": get_cpu_usage(),
        "memory_usage": get_memory_usage(),
        "memory_total": get_memory_total(),
        "disk_usage": get_disk_usage(),
        "disk_total": get_disk_total(),
        "uptime": get_uptime(),
        "status": get_status(),
    }
