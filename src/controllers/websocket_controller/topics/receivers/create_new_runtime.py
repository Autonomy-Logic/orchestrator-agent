from use_cases.docker_manager.create_runtime_container import create_runtime_container
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NumberType,
    ListType,
    OptionalType,
    validate_contract,
)
from . import topic
import asyncio
from datetime import datetime

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
    "correlation_id": NumberType,
    "container_name": StringType,
    "vnic_configs": ListType(VNIC_CONFIG_TYPE),
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
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
    async def callback(message):
        correlation_id = message.get("correlation_id")

        if "action" not in message:
            message["action"] = NAME
        if "requested_at" not in message:
            message["requested_at"] = datetime.now().isoformat()

        try:
            validate_contract(MESSAGE_TYPE, message)
        except KeyError as e:
            log_error(f"Contract validation error - missing field: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Missing required field: {str(e)}",
            }
        except TypeError as e:
            log_error(f"Contract validation error - type mismatch: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Invalid field type: {str(e)}",
            }
        except Exception as e:
            log_error(f"Contract validation error: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Validation error: {str(e)}",
            }

        container_name = message.get("container_name")
        vnic_configs = message.get("vnic_configs", [])

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

        log_info(f"Creating runtime container: {container_name}")

        asyncio.create_task(create_runtime_container(container_name, vnic_configs))

        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "creating",
            "container_id": container_name,
            "message": f"Container creation started for {container_name}",
        }
