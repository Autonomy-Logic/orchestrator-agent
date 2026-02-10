from use_cases.docker_manager.delete_runtime_container import start_deletion
from tools.logger import *
from tools.contract_validation import BASE_DEVICE
from . import topic, validate_message

NAME = "delete_device"

MESSAGE_TYPE = {**BASE_DEVICE}


@topic(NAME)
def init(client):
    """
    Handle the 'delete_device' topic to delete a runtime container.
    Deletes the container and all associated resources including networks and configurations.

    Returns a quick response with correlation_id before starting the container deletion.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        device_id = message.get("device_id")

        if not device_id or not isinstance(device_id, str) or not device_id.strip():
            log_error("Device ID is empty or invalid")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": "Device ID must be a non-empty string",
            }

        result, started = await start_deletion(device_id)
        result["action"] = NAME
        result["correlation_id"] = correlation_id
        return result
