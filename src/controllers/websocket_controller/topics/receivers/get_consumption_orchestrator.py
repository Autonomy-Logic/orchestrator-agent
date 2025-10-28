from tools.logger import *
from . import topic

NAME = "get_consumption_orchestrator"

DUMMY_PAYLOAD = {
    "action": "get_consumption_device",
    "correlation_id": "1ce0-0339-f942",
    "network": "120.2.345.3",
    "memory": "16384",
    "cpu": "8 vCPU",
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
    Handle the 'get_consumption_orchestrator' topic to send consumption data.
    """

    @client.on(NAME)
    async def callback(message):
        log_info(f"Responding: {message}")
        corr_id = message.get("correlation_id")
        response = DUMMY_PAYLOAD.copy()
        response["correlation_id"] = corr_id
        await client.emit(NAME, response)
