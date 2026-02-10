from tools.system_info import get_ip_addresses
from tools.utils import parse_period
from bootstrap import get_context


def get_consumption_orchestrator_data(cpu_period="1h", memory_period="1h"):
    ctx = get_context()
    system_info = ctx.static_system_info
    usage_buffer = ctx.usage_buffer

    cpu_start, cpu_end = parse_period(cpu_period)
    memory_start, memory_end = parse_period(memory_period)

    return {
        "ip_addresses": get_ip_addresses(ctx.network_interface_cache),
        "memory": system_info["memory"],
        "cpu": system_info["cpu"],
        "os": system_info["os"],
        "kernel": system_info["kernel"],
        "disk": system_info["disk"],
        "cpu_usage": usage_buffer.get_cpu_usage(cpu_start, cpu_end),
        "memory_usage": usage_buffer.get_memory_usage(memory_start, memory_end),
    }
