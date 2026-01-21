from use_cases.docker_manager.create_runtime_container import create_runtime_container
from tools.operations_state import (
    set_creating,
    is_operation_in_progress,
    clear_state,
)
from tools.logger import *
from tools.contract_validation import (
    StringType,
    ListType,
    OptionalType,
    BASE_MESSAGE,
    SERIAL_CONFIG_TYPE,
)
from tools.docker_tools import get_existing_mac_addresses_on_interface
from . import topic, validate_message
import asyncio

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

        in_progress, operation_type = is_operation_in_progress(container_name)
        if in_progress:
            log_warning(
                f"Container {container_name} already has a {operation_type} operation in progress"
            )
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Container {container_name} already has a {operation_type} operation in progress",
            }

        if not set_creating(container_name):
            log_error(
                f"Failed to set creating state for {container_name} (race condition)"
            )
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Failed to start creation for {container_name}",
            }

        # Check for MAC address conflicts before proceeding with container creation
        for vnic_config in vnic_configs:
            mac_address = vnic_config.get("mac")
            if mac_address:
                parent_interface = vnic_config.get("parent_interface")
                vnic_name = vnic_config.get("name", "unnamed")

                existing_macs = get_existing_mac_addresses_on_interface(
                    parent_interface
                )
                mac_lower = mac_address.lower()

                if mac_lower in existing_macs:
                    conflicting_container = existing_macs[mac_lower]
                    log_error(
                        f"MAC address {mac_address} for vNIC {vnic_name} already exists "
                        f"on container {conflicting_container} (interface: {parent_interface})"
                    )
                    clear_state(container_name)
                    return {
                        "action": NAME,
                        "correlation_id": correlation_id,
                        "status": "error",
                        "error": (
                            f"MAC address {mac_address} is already in use."
                        ),
                    }

        log_info(f"Creating runtime container: {container_name}")
        if serial_configs:
            log_info(f"Container {container_name} will have {len(serial_configs)} serial port(s) configured")

        asyncio.create_task(
            create_runtime_container(container_name, vnic_configs, serial_configs)
        )

        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "creating",
            "container_id": container_name,
            "message": f"Container creation started for {container_name}",
            "serial_configs_count": len(serial_configs) if serial_configs else 0,
        }
