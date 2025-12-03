from tools.logger import *
from tools.contract_validation import BASE_DEVICE
from . import topic, validate_message

NAME = "stop_device"

MESSAGE_TYPE = {**BASE_DEVICE}

DUMMY_PAYLOAD = {"action": "stop_device", "success": True}


@topic(NAME)
def init(client):
    """
    Handle the 'stop_device' topic to send stop device.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        log_info(f"Responding: {message}")
        corr_id = message.get("correlation_id")
        response = DUMMY_PAYLOAD.copy()
        response["correlation_id"] = corr_id
        await client.emit(NAME, response)
