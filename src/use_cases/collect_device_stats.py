from tools.logger import log_debug


def collect_device_stats(device_id, *, container_runtime):
    """
    Collect CPU and memory usage stats for a Docker container.

    Args:
        device_id: The container name/ID
        container_runtime: ContainerRuntimeRepo instance

    Returns:
        tuple: (cpu_percent, memory_mb) or (None, None) if stats cannot be collected
    """
    try:
        container = container_runtime.get_container(device_id)
        if container.status != "running":
            return None, None

        stats = container.stats(stream=False)

        # CPU delta calculation
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


def collect_all_device_stats(devices_buffer, *, container_runtime):
    """
    Collect stats for all registered devices and add samples to the buffer.

    Args:
        devices_buffer: The DevicesUsageBuffer instance
        container_runtime: ContainerRuntimeRepo instance
    """
    device_ids = devices_buffer.get_device_ids()

    for device_id in device_ids:
        cpu_percent, memory_mb = collect_device_stats(device_id, container_runtime=container_runtime)
        if cpu_percent is not None and memory_mb is not None:
            devices_buffer.add_sample(device_id, cpu_percent, memory_mb)
