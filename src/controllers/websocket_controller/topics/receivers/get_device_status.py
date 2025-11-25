from use_cases.docker_manager.get_device_status import get_device_status_data
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
)
from . import topic, validate_message

NAME = "get_device_status"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "device_id": StringType,
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
}


@topic(NAME)
def init(client):
    """
    Handle the 'get_device_status' topic to retrieve the current status of a runtime container.

    This topic provides feedback for container creation/deletion operations and enables
    periodic health checks from the backend.

    Returns container status information including:
    - Container state (running, stopped, created, etc.)
    - Network information (IP addresses for internal and MACVLAN networks)
    - Container health and uptime
    - For non-existent containers, returns appropriate error response
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        device_id = message.get("device_id")

        result = get_device_status_data(device_id)

        return {
            "action": NAME,
            "correlation_id": correlation_id,
            **result,
        }
