from tools.logger import *
from tools.contract_validation import (
    BASE_DEVICE,
    validate_contract_with_error_response,
)
from . import topic

NAME = "restart_device"

MESSAGE_TYPE = {**BASE_DEVICE}

DUMMY_PAYLOAD = {"action": "restart_device", "success": True}


@topic(NAME)
def init(client):
    """
    Handle the 'restart_device' topic to send restart device.
    """

    @client.on(NAME)
    async def callback(message):
        correlation_id = message.get("correlation_id")

        is_valid, error_response = validate_contract_with_error_response(
            MESSAGE_TYPE, message, NAME, correlation_id
        )
        if not is_valid:
            return error_response

        log_info(f"Responding: {message}")
        corr_id = message.get("correlation_id")
        response = DUMMY_PAYLOAD.copy()
        response["correlation_id"] = corr_id
        await client.emit(NAME, response)
