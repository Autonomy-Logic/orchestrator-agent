from tools.logger import log_warning, log_error, log_info
from tools.contract_validation import BASE_MESSAGE
from . import topic, validate_message
from use_cases.docker_manager.selfdestruct import self_destruct
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

    The response is returned BEFORE the self-destruct begins. If any cleanup step
    fails, the self-destruct stops and an error is logged (but the response has
    already been sent).

    Returns:
        On success: {"correlation_id": ..., "status": "success"}
        On validation error: Standard validation error response
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        log_warning("Received delete_orchestrator command - initiating self-destruct...")

        async def perform_self_destruct():
            """
            Perform self-destruct in a separate task after returning the response.
            This ensures the API call gets a response before the container is removed.
            """
            await asyncio.sleep(0.5)
            try:
                self_destruct()
            except Exception as e:
                log_error(f"Self-destruct failed: {e}")

        asyncio.create_task(perform_self_destruct())

        log_info("Self-destruct scheduled, returning success response")
        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "success",
        }
