from tools.logger import *
from tools.contract_validation import *
from . import topic
from use_cases.docker_manager.selfdestruct import self_destruct

NAME = "delete_orchestrator"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "action": StringType,
    "requested_at": DateType,
}


@topic(NAME)
def init(client):
    """
    Handle the 'delete_orchestrator' topic to delete the orchestrator.
    """

    @client.on(NAME)
    async def callback(message):

        try:
            validate_contract(MESSAGE_TYPE, message)
        except Exception as e:
            log_error(f"Contract validation error: {e}")
            return

        log_warning("Deleting orchestrator...")

        response = {
            "correlation_id": message.get("correlation_id"),
            "status": "command_received",
        }

        try:
            await client.emit("delete_orchestrator_response", response)
            await self_destruct()
        except Exception as e:
            log_error(f"Error occurred: {e}")
