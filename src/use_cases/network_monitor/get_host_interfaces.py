from tools.logger import log_debug, log_info, log_warning, log_error
from typing import Dict, Any, List

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


def get_host_interfaces_data(
    include_virtual: bool = False, detailed: bool = True,
    *, interface_cache, dedicated_nic_repo=None,
) -> Dict[str, Any]:
    """
    Get network interfaces on the host from the interface cache.

    This function contains the core business logic for retrieving host network interfaces,
    separated from the transport layer (WebSocket topic handling).

    The interface cache is populated by the netmon sidecar with HOST network interface
    information, allowing the orchestrator-agent (running in a container) to see the
    host's physical network interfaces.

    Args:
        include_virtual: Whether to include virtual/container interfaces (default: False)
        detailed: Whether to include detailed information like subnet and gateway (default: True)
        interface_cache: Optional InterfaceCacheRepo adapter (defaults to singleton)

    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - interfaces: List of interface information (on success)
        - error: Error message (on error)
    """
    log_debug(
        f"Retrieving host network interfaces from interface cache "
        f"(include_virtual={include_virtual}, detailed={detailed})"
    )

    try:
        all_interfaces = interface_cache.get_all_interfaces()
        if not all_interfaces:
            log_warning(
                "INTERFACE_CACHE is empty - netmon sidecar may not be running or "
                "has not yet discovered network interfaces"
            )
            return {
                "status": "error",
                "error": "Network interface cache is empty. The netmon sidecar may not be running or has not yet discovered interfaces.",
            }

        log_debug(f"Interface cache has {len(all_interfaces)} interface(s)")

        interfaces: List[dict] = []

        # Build lookup of which NICs are dedicated to containers
        dedicated_nics = {}
        if dedicated_nic_repo:
            try:
                all_nic_configs = dedicated_nic_repo.load_all_configs()
                for container_name, nic_config in all_nic_configs.items():
                    host_iface = nic_config.get("host_interface")
                    if host_iface:
                        dedicated_nics[host_iface] = container_name
            except Exception as e:
                log_warning(f"Could not load dedicated NIC configs: {e}")

        cache_snapshot = all_interfaces

        for interface_name, cache_data in cache_snapshot.items():
            if not should_include_interface(interface_name, include_virtual):
                log_debug(f"Filtering out virtual interface: {interface_name}")
                continue

            interface_info = build_interface_info_from_cache(
                interface_name, cache_data, detailed
            )

            # Add dedicated_to field if this NIC is assigned to a container
            if interface_name in dedicated_nics:
                interface_info["dedicated_to"] = dedicated_nics[interface_name]

            if interface_info["ipv4_addresses"] or include_virtual:
                interfaces.append(interface_info)
                log_debug(
                    f"Added interface {interface_name}: "
                    f"IP={interface_info['ip_address']}, "
                    f"subnet={interface_info.get('subnet')}, "
                    f"gateway={interface_info.get('gateway')}"
                )
            else:
                log_debug(f"Skipping interface {interface_name} (no IPv4 addresses)")

        interfaces.sort(key=lambda x: x["name"])

        log_info(
            f"Retrieved {len(interfaces)} network interface(s) from host "
            f"(total in cache: {len(all_interfaces)})"
        )

        return {
            "status": "success",
            "interfaces": interfaces,
        }

    except Exception as e:
        log_error(f"Error retrieving network interfaces: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "error": f"Failed to retrieve network interfaces: {str(e)}",
        }
