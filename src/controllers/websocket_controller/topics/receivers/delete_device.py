from use_cases.docker_manager.delete_runtime_container import delete_runtime_container
from use_cases.docker_manager.operations_state import (
    set_deleting,
    is_operation_in_progress,
)
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
)
from . import topic, validate_message
import asyncio

NAME = "delete_device"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "device_id": StringType,
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
}


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

        in_progress, operation_type = is_operation_in_progress(device_id)
        if in_progress:
            log_warning(
                f"Container {device_id} already has a {operation_type} operation in progress"
            )
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Container {device_id} already has a {operation_type} operation in progress",
            }

        if not set_deleting(device_id):
            log_error(f"Failed to set deleting state for {device_id} (race condition)")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Failed to start deletion for {device_id}",
            }

        log_info(f"Deleting runtime container: {device_id}")

        asyncio.create_task(delete_runtime_container(device_id))

        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "deleting",
            "device_id": device_id,
            "message": f"Container deletion started for {device_id}",
        }
