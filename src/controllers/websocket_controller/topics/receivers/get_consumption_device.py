from tools.logger import *
from tools.contract_validation import (
    BASE_DEVICE,
    StringType,
)
from tools.devices_usage_buffer import get_devices_usage_buffer
from tools.utils import parse_period
from use_cases.docker_manager import CLIENTS
from use_cases.docker_manager.get_device_status import get_device_info
from . import topic, validate_message

NAME = "get_consumption_device"

MESSAGE_TYPE = {
    **BASE_DEVICE,
    "cpuPeriod": StringType,
    "memoryPeriod": StringType,
}


@topic(NAME)
def init(client):
    """
    Handle the 'get_consumption_device' topic to send consumption data.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        log_debug(f"Received get_consumption_device request: {message}")

        corr_id = message.get("correlation_id")
        device_id = message.get("device_id")
        cpu_period = message.get("cpuPeriod", "1h")
        memory_period = message.get("memoryPeriod", "1h")

        if device_id not in CLIENTS:
            log_warning(f"Device {device_id} not found in CLIENTS registry")
            return {
                "action": NAME,
                "correlation_id": corr_id,
                "status": "error",
                "error": f"Device {device_id} not found",
            }

        devices_buffer = get_devices_usage_buffer()

        cpu_start, cpu_end = parse_period(cpu_period)
        memory_start, memory_end = parse_period(memory_period)

        cpu_usage_data = devices_buffer.get_cpu_usage(device_id, cpu_start, cpu_end)
        memory_usage_data = devices_buffer.get_memory_usage(
            device_id, memory_start, memory_end
        )

        device_info = get_device_info(device_id)

        response = {
            "action": NAME,
            "correlation_id": corr_id,
            "device_id": device_id,
            "memory": device_info.get("memory_limit", "N/A"),
            "cpu": device_info.get("cpu_count", "N/A"),
            "cpu_usage": cpu_usage_data,
            "memory_usage": memory_usage_data,
        }

        log_debug(
            f"Returning get_consumption_device response for {device_id} with "
            f"{len(cpu_usage_data)} CPU samples and {len(memory_usage_data)} memory samples"
        )
        return response
