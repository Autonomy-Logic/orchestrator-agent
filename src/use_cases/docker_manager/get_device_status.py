from . import CLIENTS
from tools.operations_state import get_state
from tools.logger import log_debug, log_info, log_warning, log_error
from tools.docker_tools import CLIENT
from tools.vnic_persistence import load_vnic_configs
from tools.serial_persistence import load_serial_configs
import docker
from datetime import datetime
from typing import Dict, Any, List


def get_serial_port_status(device_id: str) -> List[Dict[str, Any]]:
    """
    Get the status of serial ports configured for a runtime container.

    Args:
        device_id: The name/ID of the container

    Returns:
        List of serial port status dicts, each containing:
        - name: User-friendly name (e.g., "modbus_rtu")
        - device_id: Stable USB device identifier
        - container_path: Path inside container (e.g., "/dev/modbus0")
        - status: "connected", "disconnected", or "error"
        - current_host_path: Current /dev/ttyUSBx path (if connected)
        - baud_rate: Configured baud rate (if set)
    """
    try:
        serial_config = load_serial_configs(device_id)
        serial_ports = serial_config.get("serial_ports", [])

        result = []
        for port in serial_ports:
            port_status = {
                "name": port.get("name"),
                "device_id": port.get("device_id"),
                "container_path": port.get("container_path"),
                "status": port.get("status", "unknown"),
            }

            # Include current host path if connected
            if port.get("current_host_path"):
                port_status["current_host_path"] = port["current_host_path"]

            # Include baud rate if configured
            if port.get("baud_rate"):
                port_status["baud_rate"] = port["baud_rate"]

            result.append(port_status)

        return result

    except Exception as e:
        log_warning(f"Error getting serial port status for {device_id}: {e}")
        return []


def get_device_info(device_id: str) -> Dict[str, Any]:
    """
    Get basic information about a runtime container (CPU, memory limits).

    Args:
        device_id: The name/ID of the container

    Returns:
        Dictionary containing:
        - cpu_count: Number of CPUs available to the container (or "N/A")
        - memory_limit: Memory limit in MB (or "N/A")
    """
    try:
        container = CLIENT.containers.get(device_id)
        container.reload()

        host_config = container.attrs.get("HostConfig", {})

        nano_cpus = host_config.get("NanoCpus", 0)
        if nano_cpus and nano_cpus > 0:
            cpu_count = f"{nano_cpus / 1e9:.1f} vCPU"
        else:
            cpu_quota = host_config.get("CpuQuota", 0)
            cpu_period = host_config.get("CpuPeriod", 100000)
            if cpu_quota and cpu_quota > 0:
                cpu_count = f"{cpu_quota / cpu_period:.1f} vCPU"
            else:
                cpu_count = "unlimited"

        memory_limit = host_config.get("Memory", 0)
        if memory_limit and memory_limit > 0:
            memory_mb = memory_limit // (1024 * 1024)
            memory_limit_str = f"{memory_mb} MB"
        else:
            memory_limit_str = "unlimited"

        return {
            "cpu_count": cpu_count,
            "memory_limit": memory_limit_str,
        }

    except docker.errors.NotFound:
        log_warning(f"Container {device_id} not found when getting device info")
        return {
            "cpu_count": "N/A",
            "memory_limit": "N/A",
        }
    except Exception as e:
        log_warning(f"Error getting device info for {device_id}: {e}")
        return {
            "cpu_count": "N/A",
            "memory_limit": "N/A",
        }


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

        # Load vNIC configs to check for DHCP-assigned IPs
        vnic_configs = load_vnic_configs(device_id)

        # Build mappings for DHCP IP lookup by docker_network_name and parent_interface
        dhcp_ips_by_network = {}
        dhcp_ips_by_parent = {}
        for vnic_config in vnic_configs:
            if vnic_config.get("dhcp_ip"):
                dhcp_info = {
                    "ip": vnic_config["dhcp_ip"],
                    "gateway": vnic_config.get("dhcp_gateway"),
                }
                # Map by docker network name (most reliable)
                if vnic_config.get("docker_network_name"):
                    dhcp_ips_by_network[vnic_config["docker_network_name"]] = dhcp_info
                # Also map by parent_interface for fallback (network name starts with macvlan_{parent})
                if vnic_config.get("parent_interface"):
                    dhcp_ips_by_parent[vnic_config["parent_interface"]] = dhcp_info

        for network_name, network_info in network_settings.items():
            # Skip internal Docker networks (used for orchestrator-runtime communication)
            # These networks are named {container_name}_internal and should not be
            # exposed to users as they are only for internal container communication
            if network_name.endswith("_internal"):
                log_debug(
                    f"Skipping internal network {network_name} from device status"
                )
                continue

            ip_address = network_info.get("IPAddress")
            gateway = network_info.get("Gateway")

            # Override with DHCP-assigned IP if available
            dhcp_info = None
            if network_name in dhcp_ips_by_network:
                dhcp_info = dhcp_ips_by_network[network_name]
            else:
                # Fallback: check if network name matches macvlan_{parent_interface}
                for parent_interface, info in dhcp_ips_by_parent.items():
                    if network_name.startswith(f"macvlan_{parent_interface}"):
                        dhcp_info = info
                        break

            if dhcp_info:
                ip_address = dhcp_info["ip"]
                if dhcp_info.get("gateway"):
                    gateway = dhcp_info["gateway"]
                log_info(f"Using DHCP IP {ip_address} for network {network_name}")

            networks[network_name] = {
                "ip_address": ip_address,
                "mac_address": network_info.get("MacAddress"),
                "gateway": gateway,
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

        # Include serial port status if configured
        serial_ports = get_serial_port_status(device_id)
        if serial_ports:
            response["serial_ports"] = serial_ports
            log_debug(f"Container {device_id} has {len(serial_ports)} serial port(s) configured")

        log_info(f"Retrieved status for container {device_id}: {container_status}")
        return response

    except Exception as e:
        log_error(f"Error retrieving status for container {device_id}: {e}")
        return {
            "status": "error",
            "device_id": device_id,
            "error": f"Failed to retrieve container status: {str(e)}",
        }
