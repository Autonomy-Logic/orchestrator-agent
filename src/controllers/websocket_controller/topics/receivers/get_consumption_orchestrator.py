from tools.logger import *
from tools.contract_validation import (
    BASE_MESSAGE,
    StringType,
    validate_contract_with_error_response,
)
from tools.system_info import get_cached_system_info
from tools.usage_buffer import get_usage_buffer
from . import topic
import time
from datetime import datetime, timedelta

NAME = "get_consumption_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE, "cpuPeriod": StringType, "memoryPeriod": StringType}


def parse_period(period_str: str) -> tuple:
    """
    Parse a period string and return start and end timestamps.

    Args:
        period_str: Period string in format "start_timestamp,end_timestamp" (Unix timestamps in seconds)
                   or "duration" (e.g., "1h", "24h", "48h")

    Returns:
        tuple: (start_timestamp, end_timestamp) as integers
    """
    try:
        if "," in period_str:
            parts = period_str.split(",")
            start_time = int(parts[0])
            end_time = int(parts[1])
            return (start_time, end_time)
        else:
            end_time = int(time.time())
            if period_str.endswith("h"):
                hours = int(period_str[:-1])
                start_time = end_time - (hours * 3600)
            elif period_str.endswith("m"):
                minutes = int(period_str[:-1])
                start_time = end_time - (minutes * 60)
            elif period_str.endswith("d"):
                days = int(period_str[:-1])
                start_time = end_time - (days * 86400)
            else:
                seconds = int(period_str)
                start_time = end_time - seconds
            return (start_time, end_time)
    except Exception as e:
        log_error(f"Error parsing period '{period_str}': {e}")
        end_time = int(time.time())
        start_time = end_time - 3600
        return (start_time, end_time)


@topic(NAME)
def init(client):
    """
    Handle the 'get_consumption_orchestrator' topic to send consumption data.
    """

    @client.on(NAME)
    async def callback(message):
        correlation_id = message.get("correlation_id")

        is_valid, error_response = validate_contract_with_error_response(
            MESSAGE_TYPE, message
        )
        if not is_valid:
            error_response["action"] = NAME
            error_response["correlation_id"] = correlation_id
            return error_response

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
