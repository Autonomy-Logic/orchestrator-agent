from use_cases.docker_manager.create_runtime_container import start_creation
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NonEmptyStringType,
    ListType,
    OptionalType,
    BASE_MESSAGE,
    SERIAL_CONFIG_TYPE,
)
from . import topic, validate_message, with_response

NAME = "create_new_runtime"

VNIC_CONFIG_TYPE = {
    "name": StringType,
    "parent_interface": StringType,
    "network_mode": StringType,
    "ip": OptionalType(StringType),
    "subnet": OptionalType(StringType),
    "gateway": OptionalType(StringType),
    "dns": OptionalType(ListType(StringType)),
    "mac": OptionalType(StringType),
}

MESSAGE_TYPE = {
    **BASE_MESSAGE,
    "container_name": NonEmptyStringType,
    "vnic_configs": ListType(VNIC_CONFIG_TYPE),
    "serial_configs": OptionalType(ListType(SERIAL_CONFIG_TYPE)),
    "runtime_version": OptionalType(StringType),
}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'create_new_runtime' topic to create a new runtime environment.
    Creates a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.

    Returns a quick response with correlation_id before starting the container creation.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        container_name = message.get("container_name")
        vnic_configs = message.get("vnic_configs", [])
        serial_configs = message.get("serial_configs", [])
        runtime_version = message.get("runtime_version")

        result, started = await start_creation(
            container_name, vnic_configs, serial_configs, runtime_version, ctx=ctx
        )
        if started and serial_configs:
            result["serial_configs_count"] = len(serial_configs)
        return result
