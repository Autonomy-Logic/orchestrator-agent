from use_cases.network_monitor.interface_cache import INTERFACE_CACHE
from tools.logger import *
from tools.contract_validation import (
    NumberType,
    BooleanType,
    OptionalType,
    StringType,
    validate_contract_with_error_response,
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

    # Filter out virtual/container interfaces
    interface_lower = interface_name.lower()
    for prefix in VIRTUAL_INTERFACE_PREFIXES:
        if interface_lower.startswith(prefix):
            return False

    return True


def build_interface_info_from_cache(
    interface_name: str, cache_data: dict, detailed: bool
) -> dict:
    """
    Build interface information dictionary from INTERFACE_CACHE data.

    The INTERFACE_CACHE is populated by the netmon sidecar with HOST network interface information.

    Args:
        interface_name: Name of the network interface
        cache_data: Data from INTERFACE_CACHE for this interface
        detailed: Whether to include detailed information (subnet, gateway)

    Returns:
        Dictionary with interface information
    """
    addresses_list = cache_data.get("addresses", [])

    ipv4_addresses = []

    for addr_obj in addresses_list:
        if isinstance(addr_obj, dict):
            address = addr_obj.get("address")
            if address and not address.startswith("127."):
                ipv4_addresses.append(address)

    interface_info = {
        "name": interface_name,
        "ip_address": ipv4_addresses[0] if ipv4_addresses else None,
        "ipv4_addresses": ipv4_addresses,
        "mac_address": None,
    }

    if detailed:
        interface_info["subnet"] = cache_data.get("subnet")
        interface_info["gateway"] = cache_data.get("gateway")

    return interface_info


@topic(NAME)
def init(client):
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

        include_virtual = message.get("include_virtual", False)
        detailed = message.get("detailed", True)

        log_debug(
            f"Retrieving host network interfaces from INTERFACE_CACHE "
            f"(include_virtual={include_virtual}, detailed={detailed})"
        )

        try:
            if not INTERFACE_CACHE:
                log_warning(
                    "INTERFACE_CACHE is empty - netmon sidecar may not be running or "
                    "has not yet discovered network interfaces"
                )
                return {
                    "action": NAME,
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": "Network interface cache is empty. The netmon sidecar may not be running or has not yet discovered interfaces.",
                }

            log_debug(f"INTERFACE_CACHE has {len(INTERFACE_CACHE)} interface(s)")

            interfaces = []

            cache_snapshot = dict(INTERFACE_CACHE)

            for interface_name, cache_data in cache_snapshot.items():
                if not should_include_interface(interface_name, include_virtual):
                    log_debug(f"Filtering out virtual interface: {interface_name}")
                    continue

                # Build interface information from cache data
                interface_info = build_interface_info_from_cache(
                    interface_name, cache_data, detailed
                )

                if interface_info["ipv4_addresses"] or include_virtual:
                    interfaces.append(interface_info)
                    log_debug(
                        f"Added interface {interface_name}: "
                        f"IP={interface_info['ip_address']}, "
                        f"subnet={interface_info.get('subnet')}, "
                        f"gateway={interface_info.get('gateway')}"
                    )
                else:
                    log_debug(
                        f"Skipping interface {interface_name} (no IPv4 addresses)"
                    )

            interfaces.sort(key=lambda x: x["name"])

            log_info(
                f"Retrieved {len(interfaces)} network interface(s) from host "
                f"(total in cache: {len(INTERFACE_CACHE)})"
            )

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
