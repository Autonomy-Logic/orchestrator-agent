from use_cases.network_monitor.get_host_interfaces import get_host_interfaces_data
from tools.contract_validation import (
    BASE_MESSAGE,
    BooleanType,
    OptionalType,
)
from . import topic, validate_message, with_response

NAME = "get_host_interfaces"

MESSAGE_TYPE = {
    **BASE_MESSAGE,
    "include_virtual": OptionalType(BooleanType),
    "detailed": OptionalType(BooleanType),
}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_host_interfaces' topic to retrieve network interfaces on the host.

    This topic queries the INTERFACE_CACHE which is populated by the netmon sidecar
    with HOST network interface information. This allows the backend to properly
    assemble create_new_runtime requests with the correct parent_interface.

    Returns information about network interfaces including:
    - Interface name
    - IPv4 address(es)
    - MAC address (when available)
    - Subnet and gateway (when detailed=true)
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        include_virtual = message.get("include_virtual", False)
        detailed = message.get("detailed", True)

        return get_host_interfaces_data(
            include_virtual, detailed,
            interface_cache=ctx.network_interface_cache,
        )
