from tools.logger import *
from tools.contract_validation import (
    BASE_DEVICE,
    StringType,
    validate_contract_with_error_response,
)
from . import topic

NAME = "get_consumption_device"

MESSAGE_TYPE = {
    **BASE_DEVICE,
    "cpuPeriod": StringType,
    "memoryPeriod": StringType,
}

DUMMY_PAYLOAD = {
    "action": "get_consumption_device",
    "correlation_id": 123,
    "memory": "16384",
    "cpu": "1 vCPU",
    "cpu_usage": [
        {"registered_at": "2025-10-10T17:00:00Z", "cpu": 23.5},
        {"registered_at": "2025-10-10T17:01:00Z", "cpu": 41.2},
        {"registered_at": "2025-10-10T17:02:00Z", "cpu": 56.8},
        {"registered_at": "2025-10-10T17:03:00Z", "cpu": 37.4},
        {"registered_at": "2025-10-10T17:04:00Z", "cpu": 49.9},
    ],
    "memory_usage": [
        {"registered_at": "2025-10-10T17:00:00Z", "memory": 8234},
        {"registered_at": "2025-10-10T17:01:00Z", "memory": 8456},
        {"registered_at": "2025-10-10T17:02:00Z", "memory": 8612},
        {"registered_at": "2025-10-10T17:03:00Z", "memory": 8798},
        {"registered_at": "2025-10-10T17:04:00Z", "memory": 8920},
    ],
}


@topic(NAME)
def init(client):
    """
    Handle the 'get_consumption_device' topic to send consumption data.
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

        log_info(f"Responding: {message}")
        corr_id = message.get("correlation_id")
        response = DUMMY_PAYLOAD.copy()
        response["correlation_id"] = corr_id
        await client.emit(NAME, response)
