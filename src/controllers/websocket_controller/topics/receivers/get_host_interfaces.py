import psutil
import socket
from use_cases.network_monitor.interface_cache import INTERFACE_CACHE
from tools.logger import *
from tools.contract_validation import (
    NumberType,
    BooleanType,
    OptionalType,
    StringType,
    validate_contract,
)
from . import topic
from datetime import datetime

NAME = "get_host_interfaces"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "include_virtual": OptionalType(BooleanType),
    "detailed": OptionalType(BooleanType),
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
}

VIRTUAL_INTERFACE_PREFIXES = [
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    "tailscale",
    "zt",
    "cni",
    "flannel",
    "kube-ipvs",
    "wg",
    "cilium",
    "macvtap",
]


def should_include_interface(interface_name: str, include_virtual: bool) -> bool:
    """
    Determine if an interface should be included based on filtering rules.
    
    Args:
        interface_name: Name of the network interface
        include_virtual: Whether to include virtual/container interfaces
    
    Returns:
        True if the interface should be included, False otherwise
    """
    if include_virtual:
        return True
    
    interface_lower = interface_name.lower()
    for prefix in VIRTUAL_INTERFACE_PREFIXES:
        if interface_lower.startswith(prefix):
            return False
    
    return True


def get_interface_info(interface_name: str, addresses: list, detailed: bool) -> dict:
    """
    Build interface information dictionary from psutil data.
    
    Args:
        interface_name: Name of the network interface
        addresses: List of address objects from psutil.net_if_addrs()
        detailed: Whether to include detailed information (subnet, gateway)
    
    Returns:
        Dictionary with interface information
    """
    ipv4_addresses = []
    mac_address = None
    
    for addr in addresses:
        if addr.family == socket.AF_INET:
            if not addr.address.startswith("127."):
                ipv4_addresses.append(addr.address)
        elif hasattr(socket, "AF_PACKET") and addr.family == socket.AF_PACKET:
            mac_address = addr.address
        elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
            mac_address = addr.address
    
    interface_info = {
        "name": interface_name,
        "ip_address": ipv4_addresses[0] if ipv4_addresses else None,
        "ipv4_addresses": ipv4_addresses,
        "mac_address": mac_address,
    }
    
    if detailed and interface_name in INTERFACE_CACHE:
        cached_data = INTERFACE_CACHE[interface_name]
        interface_info["subnet"] = cached_data.get("subnet")
        interface_info["gateway"] = cached_data.get("gateway")
    elif detailed:
        interface_info["subnet"] = None
        interface_info["gateway"] = None
    
    return interface_info


@topic(NAME)
def init(client):
    """
    Handle the 'get_host_interfaces' topic to retrieve network interfaces on the host.
    
    This topic allows the backend to query available network interfaces so it can
    properly assemble create_new_runtime requests with the correct parent_interface.
    
    Returns information about network interfaces including:
    - Interface name
    - IPv4 address(es)
    - MAC address
    - Subnet and gateway (when available from network monitor cache)
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

        include_virtual = message.get("include_virtual", False)
        detailed = message.get("detailed", True)

        log_debug(
            f"Retrieving host network interfaces (include_virtual={include_virtual}, detailed={detailed})"
        )

        try:
            net_if_addrs = psutil.net_if_addrs()
            interfaces = []

            for interface_name, addresses in net_if_addrs.items():
                if not should_include_interface(interface_name, include_virtual):
                    log_debug(f"Filtering out virtual interface: {interface_name}")
                    continue

                interface_info = get_interface_info(
                    interface_name, addresses, detailed
                )

                if interface_info["ipv4_addresses"] or include_virtual:
                    interfaces.append(interface_info)
                    log_debug(
                        f"Added interface {interface_name}: "
                        f"IP={interface_info['ip_address']}, "
                        f"MAC={interface_info['mac_address']}"
                    )

            interfaces.sort(key=lambda x: x["name"])

            log_info(f"Retrieved {len(interfaces)} network interface(s)")

            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "interfaces": interfaces,
            }

        except Exception as e:
            log_error(f"Error retrieving network interfaces: {e}")
            import traceback

            log_error(f"Traceback: {traceback.format_exc()}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Failed to retrieve network interfaces: {str(e)}",
            }
