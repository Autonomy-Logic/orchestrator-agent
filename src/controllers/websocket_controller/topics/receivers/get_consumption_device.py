from tools.logger import *
from tools.contract_validation import BASE_DEVICE, StringType
from use_cases.get_consumption_device import get_consumption_device_data
from . import topic, validate_message, with_response

NAME = "get_consumption_device"

MESSAGE_TYPE = {
    **BASE_DEVICE,
    "cpuPeriod": StringType,
    "memoryPeriod": StringType,
}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_consumption_device' topic to send consumption data.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    @with_response(NAME)
    async def callback(message):
        log_debug(f"Received get_consumption_device request: {message}")

        device_id = message.get("device_id")
        result = get_consumption_device_data(
            device_id,
            message.get("cpuPeriod", "1h"),
            message.get("memoryPeriod", "1h"),
            client_registry=ctx.client_registry,
            devices_usage_buffer=ctx.devices_usage_buffer,
            container_runtime=ctx.container_runtime,
        )

        log_debug(
            f"Returning get_consumption_device response for {device_id}"
        )
        return result
