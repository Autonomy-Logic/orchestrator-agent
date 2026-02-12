from use_cases.docker_manager.get_device_status import get_device_status_data
from tools.contract_validation import BASE_DEVICE
from . import topic, validate_message, with_response

NAME = "get_device_status"

MESSAGE_TYPE = {**BASE_DEVICE}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_device_status' topic to retrieve the current status of a runtime container.

    This topic provides feedback for container creation/deletion operations and enables
    periodic health checks from the backend.

    Returns container status information including:
    - Container state (running, stopped, created, etc.)
    - Network information (IP addresses for internal and MACVLAN networks)
    - Container health and uptime
    - For non-existent containers, returns appropriate error response
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        device_id = message.get("device_id")

        return get_device_status_data(
            device_id,
            container_runtime=ctx.container_runtime,
            client_registry=ctx.client_registry,
            vnic_repo=ctx.vnic_repo,
            serial_repo=ctx.serial_repo,
            operations_state=ctx.operations_state,
        )
