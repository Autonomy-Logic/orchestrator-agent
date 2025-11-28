from . import CLIENT, CLIENTS
from tools.operations_state import get_state
from tools.logger import log_debug, log_info, log_warning, log_error
import docker
from datetime import datetime
from typing import Dict, Any


def get_device_status_data(device_id: str) -> Dict[str, Any]:
    """
    Get the current status of a runtime container.

    This function contains the core business logic for retrieving container status,
    separated from the transport layer (WebSocket topic handling).

    Args:
        device_id: The name/ID of the container to check

    Returns:
        Dictionary containing status information:
        - For tracked operations: status, operation, step, error, timestamps
        - For existing containers: container_status, is_running, networks, health
        - For non-existent containers: status="not_found"
        - For errors: status="error" with error message
    """
    if not device_id or not isinstance(device_id, str) or not device_id.strip():
        log_error("Device ID is empty or invalid")
        return {
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
                    uptime_seconds = (datetime.utcnow() - started_at).total_seconds()
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
            "status": "error",
            "device_id": device_id,
            "error": f"Failed to retrieve container status: {str(e)}",
        }
