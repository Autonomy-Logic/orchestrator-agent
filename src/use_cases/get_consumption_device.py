from tools.utils import parse_period
from use_cases.docker_manager.get_device_status import get_device_info


def get_consumption_device_data(
    device_id,
    cpu_period="1h",
    memory_period="1h",
    *,
    client_registry,
    devices_usage_buffer,
    container_runtime,
):
    if not client_registry.contains(device_id):
        return {"status": "error", "error": f"Device {device_id} not found"}

    cpu_start, cpu_end = parse_period(cpu_period)
    memory_start, memory_end = parse_period(memory_period)

    device_info = get_device_info(device_id, container_runtime=container_runtime)

    return {
        "device_id": device_id,
        "memory": device_info.get("memory_limit", "N/A"),
        "cpu": device_info.get("cpu_count", "N/A"),
        "cpu_usage": devices_usage_buffer.get_cpu_usage(device_id, cpu_start, cpu_end),
        "memory_usage": devices_usage_buffer.get_memory_usage(device_id, memory_start, memory_end),
    }
