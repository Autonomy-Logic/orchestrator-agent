from tools.logger import *
from tools.contract_validation import (
    BASE_MESSAGE,
    StringType,
)
from tools.system_info import get_cached_system_info
from tools.usage_buffer import get_usage_buffer
from tools.utils import parse_period
from . import topic, validate_message

NAME = "get_consumption_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE, "cpuPeriod": StringType, "memoryPeriod": StringType}


@topic(NAME)
def init(client):
    """
    Handle the 'get_consumption_orchestrator' topic to send consumption data.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        log_debug(f"Received get_consumption_orchestrator request: {message}")

        corr_id = message.get("correlation_id")
        cpu_period = message.get("cpuPeriod", "1h")
        memory_period = message.get("memoryPeriod", "1h")

        system_info = get_cached_system_info()
        usage_buffer = get_usage_buffer()

        cpu_start, cpu_end = parse_period(cpu_period)
        memory_start, memory_end = parse_period(memory_period)

        cpu_usage_data = usage_buffer.get_cpu_usage(cpu_start, cpu_end)
        memory_usage_data = usage_buffer.get_memory_usage(memory_start, memory_end)

        response = {
            "action": NAME,
            "correlation_id": corr_id,
            "ip_addresses": system_info["ip_addresses"],
            "memory": system_info["memory"],
            "cpu": system_info["cpu"],
            "os": system_info["os"],
            "kernel": system_info["kernel"],
            "disk": system_info["disk"],
            "cpu_usage": cpu_usage_data,
            "memory_usage": memory_usage_data,
        }

        log_debug(
            f"Returning get_consumption_orchestrator response with {len(cpu_usage_data)} CPU samples and {len(memory_usage_data)} memory samples"
        )
        return response
