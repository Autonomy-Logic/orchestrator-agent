from tools.logger import log_info, log_debug
from tools.contract_validation import BASE_MESSAGE
from use_cases.get_serial_devices import get_serial_devices_data
from . import topic, validate_message

NAME = "get_serial_devices"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client):
    """
    Handle the 'get_serial_devices' topic to list available serial devices on the host.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        log_info("Retrieving list of available serial devices")

        result = get_serial_devices_data()

        log_debug(f"Found {result['count']} serial device(s)")
        return {
            "action": NAME,
            "correlation_id": message.get("correlation_id"),
            "status": "success",
            **result,
        }
