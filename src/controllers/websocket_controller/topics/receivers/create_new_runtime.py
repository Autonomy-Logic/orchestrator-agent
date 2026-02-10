from use_cases.docker_manager.create_runtime_container import start_creation
from tools.logger import *
from tools.contract_validation import (
    StringType,
    ListType,
    OptionalType,
    BASE_MESSAGE,
    SERIAL_CONFIG_TYPE,
)
from . import topic, validate_message

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
    "container_name": StringType,
    "vnic_configs": ListType(VNIC_CONFIG_TYPE),
    "serial_configs": OptionalType(ListType(SERIAL_CONFIG_TYPE)),
    "runtime_version": OptionalType(StringType),
}


@topic(NAME)
def init(client):
    """
    Handle the 'create_new_runtime' topic to create a new runtime environment.
    Creates a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.

    Returns a quick response with correlation_id before starting the container creation.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        container_name = message.get("container_name")
        vnic_configs = message.get("vnic_configs", [])
        serial_configs = message.get("serial_configs", [])
        runtime_version = message.get("runtime_version")

        if (
            not container_name
            or not isinstance(container_name, str)
            or not container_name.strip()
        ):
            log_error("Container name is empty or invalid")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": "Container name must be a non-empty string",
            }

        if (
            not vnic_configs
            or not isinstance(vnic_configs, list)
            or len(vnic_configs) == 0
        ):
            log_error("vnic_configs is empty or invalid")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": "At least one vNIC configuration is required",
            }

        result, started = await start_creation(
            container_name, vnic_configs, serial_configs, runtime_version
        )
        result["action"] = NAME
        result["correlation_id"] = correlation_id
        if started and serial_configs:
            result["serial_configs_count"] = len(serial_configs)
        return result
