from tools.logger import *
from tools.contract_validation import *
from . import topic

NAME = "delete_device"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "action": StringType,
    "requested_at": DateType,
}

DUMMY_PAYLOAD = {"action": "delete_device", "success": True}


@topic(NAME)
def init(client):
    """
    Handle the 'delete_device' topic to send delete device.
    """

    @client.on(NAME)
    async def callback(message):
        try:
            validate_contract(MESSAGE_TYPE, message)
        except Exception as e:
            log_error(f"Contract validation error: {e}")
            return

        log_info(f"Responding: {message}")
        corr_id = message.get("correlation_id")
        response = DUMMY_PAYLOAD.copy()
        response["correlation_id"] = corr_id
        await client.emit(NAME, response)
