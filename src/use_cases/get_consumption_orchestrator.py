from tools.system_info import get_ip_addresses
from tools.utils import parse_period


def get_consumption_orchestrator_data(
    cpu_period="1h",
    memory_period="1h",
    *,
    static_system_info,
    usage_buffer,
    network_interface_cache,
):
    cpu_start, cpu_end = parse_period(cpu_period)
    memory_start, memory_end = parse_period(memory_period)

    return {
        "ip_addresses": get_ip_addresses(network_interface_cache),
        "memory": static_system_info["memory"],
        "cpu": static_system_info["cpu"],
        "os": static_system_info["os"],
        "kernel": static_system_info["kernel"],
        "disk": static_system_info["disk"],
        "cpu_usage": usage_buffer.get_cpu_usage(cpu_start, cpu_end),
        "memory_usage": usage_buffer.get_memory_usage(memory_start, memory_end),
    }
