from tools.logger import *
from tools.contract_validation import BASE_MESSAGE
from . import topic, validate_message
from use_cases.docker_manager.selfdestruct import self_destruct

NAME = "delete_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client):
    """
    Handle the 'delete_orchestrator' topic to delete the orchestrator.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        log_warning("Deleting orchestrator...")

        response = {
            "correlation_id": message.get("correlation_id"),
            "status": "command_received",
        }

        try:
            await client.emit("delete_orchestrator_response", response)
            self_destruct()
        except Exception as e:
            log_error(f"Error occurred: {e}")
