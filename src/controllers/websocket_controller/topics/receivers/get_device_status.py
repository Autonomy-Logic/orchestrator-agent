from use_cases.docker_manager import CLIENT, CLIENTS
from use_cases.docker_manager.operations_state import get_state
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
    validate_contract_with_error_response,
)
from . import topic
from datetime import datetime
import docker

NAME = "get_device_status"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "device_id": StringType,
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
}


@topic(NAME)
def init(client):
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
    async def callback(message):
        correlation_id = message.get("correlation_id")

        if "action" not in message:
            message["action"] = NAME
        if "requested_at" not in message:
            message["requested_at"] = datetime.now().isoformat()

        is_valid, error_response = validate_contract_with_error_response(
            MESSAGE_TYPE, message, NAME, correlation_id
        )
        if not is_valid:
            return error_response

        device_id = message.get("device_id")

        if not device_id or not isinstance(device_id, str) or not device_id.strip():
            log_error("Device ID is empty or invalid")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": "Device ID must be a non-empty string",
            }

        log_debug(f"Retrieving status for container: {device_id}")

        try:
            op_state = get_state(device_id)
            if op_state:
                log_debug(
                    f"Container {device_id} has tracked operation state: {op_state['status']}"
                )

                response = {
                    "action": NAME,
                    "correlation_id": correlation_id,
                    "status": op_state["status"],
                    "device_id": device_id,
                    "operation": op_state["operation"],
                    "started_at": op_state["started_at"],
                    "updated_at": op_state["updated_at"],
                }

                if op_state["step"]:
                    response["step"] = op_state["step"]

                if op_state["error"]:
                    response["error"] = op_state["error"]
                    response["message"] = f"Operation failed: {op_state['error']}"
                elif op_state["status"] == "creating":
                    response["message"] = f"Container {device_id} is being created"
                elif op_state["status"] == "deleting":
                    response["message"] = f"Container {device_id} is being deleted"

                log_info(
                    f"Returning tracked operation status for {device_id}: {op_state['status']}"
                )
                return response

            try:
                container = CLIENT.containers.get(device_id)
            except docker.errors.NotFound:
                log_info(f"Container {device_id} not found")
                return {
                    "action": NAME,
                    "correlation_id": correlation_id,
                    "status": "not_found",
                    "device_id": device_id,
                    "message": f"Container {device_id} does not exist",
                }

            container.reload()

            container_state = container.attrs.get("State", {})
            container_status = container_state.get("Status", "unknown")
            is_running = container_state.get("Running", False)

            uptime_seconds = None
            if is_running and container_state.get("StartedAt"):
                try:
                    started_at_str = container_state.get("StartedAt")
                    if started_at_str:
                        started_at_str = started_at_str.split(".")[0]
                        started_at = datetime.fromisoformat(started_at_str)
                        uptime_seconds = (
                            datetime.utcnow() - started_at
                        ).total_seconds()
                except Exception as e:
                    log_warning(f"Could not calculate uptime for {device_id}: {e}")

            network_settings = container.attrs.get("NetworkSettings", {}).get(
                "Networks", {}
            )
            networks = {}

            for network_name, network_info in network_settings.items():
                networks[network_name] = {
                    "ip_address": network_info.get("IPAddress"),
                    "mac_address": network_info.get("MacAddress"),
                    "gateway": network_info.get("Gateway"),
                }

            internal_ip = None
            if device_id in CLIENTS:
                internal_ip = CLIENTS[device_id].get("ip")

            restart_count = container_state.get("RestartCount", 0)

            exit_code = None
            if not is_running:
                exit_code = container_state.get("ExitCode")

            response = {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "device_id": device_id,
                "container_status": container_status,
                "is_running": is_running,
                "networks": networks,
                "restart_count": restart_count,
            }

            if internal_ip:
                response["internal_ip"] = internal_ip

            if uptime_seconds is not None:
                response["uptime_seconds"] = int(uptime_seconds)

            if exit_code is not None:
                response["exit_code"] = exit_code

            health = container_state.get("Health")
            if health:
                response["health_status"] = health.get("Status")

            log_info(f"Retrieved status for container {device_id}: {container_status}")
            return response

        except Exception as e:
            log_error(f"Error retrieving status for container {device_id}: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "device_id": device_id,
                "error": f"Failed to retrieve container status: {str(e)}",
            }
