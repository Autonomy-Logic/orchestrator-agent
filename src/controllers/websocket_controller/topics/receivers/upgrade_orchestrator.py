from tools.logger import log_warning, log_error, log_info
from tools.contract_validation import BASE_MESSAGE
from . import topic, validate_message, with_response
from use_cases.docker_manager.upgrade import (
    upgrade,
    start_upgrade,
    ORCHESTRATOR_STATUS_ID,
)
import asyncio

NAME = "upgrade_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'upgrade_orchestrator' topic to upgrade the orchestrator agent
    and netmon sidecar to the latest available images.

    This command preserves all vPLC containers, networks, and configurations.
    Only the orchestrator and netmon containers are replaced.

    The response is returned IMMEDIATELY after validation passes. The actual
    upgrade runs in a background task. Use get_device_status with
    device_id="__orchestrator__" to poll for progress.

    Returns:
        On accepted: {"status": "accepted", "poll_device_id": "__orchestrator__"}
        On already in progress: {"status": "error", "error": "..."}
        On validation error: Standard validation error response
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    @with_response(NAME)
    async def callback(message):
        log_warning("Received upgrade_orchestrator command - initiating upgrade...")

        if not start_upgrade(operations_state=ctx.operations_state):
            log_error("Upgrade or other operation already in progress")
            return {
                "status": "error",
                "error": "Upgrade or other operation already in progress",
            }

        async def perform_upgrade():
            """
            Perform upgrade in a background thread after a small delay.

            Uses asyncio.to_thread to run the blocking Docker operations in a
            separate thread, keeping the event loop responsive so the orchestrator
            can still respond to status polling requests during the upgrade.
            """
            await asyncio.sleep(0.1)
            try:
                await asyncio.to_thread(
                    upgrade,
                    container_runtime=ctx.container_runtime,
                    socket_repo=ctx.socket_repo,
                    operations_state=ctx.operations_state,
                )
            except Exception as e:
                log_error(f"Upgrade failed: {e}")

        asyncio.create_task(perform_upgrade())

        log_info("Upgrade scheduled, returning accepted response")
        return {
            "status": "accepted",
            "message": "Upgrade initiated. Poll get_device_status with device_id='__orchestrator__' for progress.",
            "poll_device_id": ORCHESTRATOR_STATUS_ID,
        }
