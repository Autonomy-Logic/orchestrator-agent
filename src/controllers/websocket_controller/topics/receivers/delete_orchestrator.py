from tools.logger import log_warning, log_error, log_info
from tools.contract_validation import BASE_MESSAGE
from . import topic, validate_message
from use_cases.docker_manager.selfdestruct import (
    self_destruct,
    start_self_destruct,
    ORCHESTRATOR_STATUS_ID,
)
import asyncio

NAME = "delete_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client):
    """
    Handle the 'delete_orchestrator' topic to delete the orchestrator.

    This command performs a complete uninstall of the orchestrator-agent and all
    managed resources:
    1. Deletes all managed runtime containers (vPLCs) and their networks
    2. Deletes the autonomy-netmon sidecar container
    3. Deletes the orchestrator-shared volume
    4. Deletes the orchestrator-agent container itself (last)

    The response is returned IMMEDIATELY after validation passes. The actual
    cleanup runs in a background task. Use get_device_status with
    device_id="__orchestrator__" to poll for progress.

    Returns:
        On accepted: {"correlation_id": ..., "status": "accepted", "poll_device_id": "__orchestrator__"}
        On already in progress: {"correlation_id": ..., "status": "error", "error": "..."}
        On validation error: Standard validation error response
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        log_warning(
            "Received delete_orchestrator command - initiating self-destruct..."
        )

        if not start_self_destruct():
            log_error("Self-destruct operation already in progress")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": "Self-destruct operation already in progress",
            }

        async def perform_self_destruct():
            """
            Perform self-destruct in a background thread after a small delay.

            Uses asyncio.to_thread to run the blocking Docker operations in a
            separate thread, keeping the event loop responsive so the orchestrator
            can still respond to status polling requests during cleanup.
            """
            await asyncio.sleep(0.1)
            try:
                await asyncio.to_thread(self_destruct)
            except Exception as e:
                log_error(f"Self-destruct failed: {e}")

        asyncio.create_task(perform_self_destruct())

        log_info("Self-destruct scheduled, returning accepted response")
        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "accepted",
            "message": "Self-destruct initiated. Poll get_device_status with device_id='__orchestrator__' for progress.",
            "poll_device_id": ORCHESTRATOR_STATUS_ID,
        }
