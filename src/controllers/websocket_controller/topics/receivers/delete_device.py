from use_cases.docker_manager.delete_runtime_container import start_deletion
from tools.logger import *
from tools.contract_validation import BASE_DEVICE
from . import topic, validate_message, with_response

NAME = "delete_device"

MESSAGE_TYPE = {**BASE_DEVICE}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'delete_device' topic to delete a runtime container.
    Deletes the container and all associated resources including networks and configurations.

    Returns a quick response with correlation_id before starting the container deletion.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        device_id = message.get("device_id")

        result, started = await start_deletion(device_id, ctx=ctx)
        return result
