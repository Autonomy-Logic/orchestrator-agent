from tools.logger import log_info, log_debug
from tools.contract_validation import BASE_MESSAGE
from use_cases.get_serial_devices import get_serial_devices_data
from . import topic, validate_message, with_response

NAME = "get_serial_devices"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_serial_devices' topic to list available serial devices on the host.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        log_info("Retrieving list of available serial devices")

        result = get_serial_devices_data(
            network_event_listener=ctx.network_event_listener,
        )

        log_debug(f"Found {result['count']} serial device(s)")
        return {
            "status": "success",
            **result,
        }
