from use_cases.docker_manager.create_runtime_container import create_runtime_container
from tools.logger import *
from tools.contract_validation import (
    StringType,
    ListType,
    OptionalType,
    validate_contract,
)
from . import topic

NAME = "create_new_runtime"

VNIC_CONFIG_TYPE = {
    "name": StringType,
    "parent_interface": StringType,
    "parent_subnet": OptionalType(StringType),
    "parent_gateway": OptionalType(StringType),
    "network_mode": StringType,
    "ip_address": OptionalType(StringType),
    "subnet": OptionalType(StringType),
    "gateway": OptionalType(StringType),
    "dns": OptionalType(ListType(StringType)),
    "mac_address": OptionalType(StringType),
}

MESSAGE_TYPE = {
    "container_name": StringType,
    "vnic_configs": ListType(VNIC_CONFIG_TYPE),
}


@topic(NAME)
def init(client):
    """
    Handle the 'create_new_runtime' topic to create a new runtime environment.
    Creates a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.
    """

    @client.on(NAME)
    async def callback(message):
        try:
            validate_contract(MESSAGE_TYPE, message)
        except Exception as e:
            log_error(f"Contract validation error: {e}")
            return

        container_name = message.get("container_name")
        vnic_configs = message.get("vnic_configs", [])

        log_info(f"Creating runtime container: {container_name}")
        await create_runtime_container(container_name, vnic_configs)
