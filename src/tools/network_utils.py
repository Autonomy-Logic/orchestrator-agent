"""
Pure network utility functions with no Docker or infrastructure dependencies.

These functions were extracted from docker_tools.py to separate pure computation
from Docker-dependent operations.
"""

import time
from tools.logger import log_info, log_debug, log_warning


def is_cidr_format(subnet: str) -> bool:
    """
    Lightweight check to distinguish CIDR strings (e.g., '192.168.1.0/24')
    from plain netmasks (e.g., '255.255.255.0'). This intentionally does
    not fully validate the CIDR format; invalid strings will fail later
    where they're actually parsed (e.g., in Docker or ipaddress module).
    """
    return "/" in subnet


def netmask_to_cidr(netmask: str) -> int:
    """
    Convert a netmask (e.g., 255.255.255.0) to CIDR prefix length (e.g., 24).
    """
    return sum(bin(int(octet)).count("1") for octet in netmask.split("."))


def calculate_network_base(gateway: str, netmask: str) -> str:
    """
    Calculate the network base address by applying the netmask to the gateway IP.
    Works for all subnet sizes (not just /24).

    Args:
        gateway: Gateway IP address (e.g., "192.168.1.1")
        netmask: Netmask in dotted decimal format (e.g., "255.255.255.0")

    Returns:
        Network base address (e.g., "192.168.1.0")
    """
    gateway_octets = [int(o) for o in gateway.split(".")]
    mask_octets = [int(o) for o in netmask.split(".")]
    network_octets = [str(gateway_octets[i] & mask_octets[i]) for i in range(4)]
    return ".".join(network_octets)


def resolve_subnet(parent_subnet, parent_gateway):
    """
    Resolve a subnet string to CIDR format.

    If the subnet is already CIDR, return as-is.
    If it's a netmask, convert using gateway to compute network base.

    Args:
        parent_subnet: Subnet in netmask or CIDR format
        parent_gateway: Gateway address (needed for netmask conversion)

    Returns:
        Subnet in CIDR format (e.g., "192.168.1.0/24")
    """
    if is_cidr_format(parent_subnet):
        return parent_subnet
    cidr_prefix = netmask_to_cidr(parent_subnet)
    network_base = calculate_network_base(parent_gateway, parent_subnet)
    return f"{network_base}/{cidr_prefix}"


def detect_interface_network(parent_interface: str, interface_cache):
    """
    Detect the subnet and gateway for a parent interface using netmon discovery cache.
    Returns (subnet, gateway) tuple or (None, None) if detection fails.

    This function reads from the interface cache populated by the netmon sidecar.
    If the cache is empty, it waits briefly for the initial discovery to arrive.

    Args:
        parent_interface: Physical network interface on host
        interface_cache: NetworkInterfaceCacheRepo instance (or any object with
                         get_interface_network method)
    """
    max_wait_seconds = 3
    retry_interval = 0.5
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        subnet, gateway = interface_cache.get_interface_network(parent_interface)

        if subnet:
            log_info(
                f"Detected network for interface {parent_interface}: "
                f"subnet={subnet}, gateway={gateway}"
            )
            return subnet, gateway

        if time.time() - start_time < max_wait_seconds:
            log_debug(
                f"Interface {parent_interface} not yet in cache, "
                f"waiting for netmon discovery..."
            )
            time.sleep(retry_interval)

    log_warning(
        f"Interface {parent_interface} not found in netmon discovery cache after "
        f"{max_wait_seconds}s. The interface may not exist or netmon may not be running."
    )
    return None, None


def get_macvlan_network_key(
    parent_interface: str,
    parent_subnet: str = None,
    parent_gateway: str = None,
    interface_cache=None,
) -> str:
    """
    Compute the MACVLAN network key (name) for a given interface and subnet configuration.
    This is used for validation to detect duplicate vNIC configurations that would
    resolve to the same network.

    IMPORTANT: This function intentionally mirrors the subnet resolution logic in
    ContainerRuntimeRepo.get_or_create_macvlan_network() to ensure validation produces
    the same network key that actual network creation would use. If you modify the logic
    here, you must also update get_or_create_macvlan_network() to maintain consistency.

    The function handles the same input combinations as get_or_create_macvlan_network():
    - Both subnet and gateway provided: uses explicit values (converts netmask to CIDR if needed)
    - Either or both missing: falls back to detect_interface_network() auto-detection

    Args:
        parent_interface: Physical network interface on host
        parent_subnet: Subnet in netmask or CIDR format (optional, auto-detected if not provided)
        parent_gateway: Gateway address (optional, auto-detected if not provided)
        interface_cache: NetworkInterfaceCacheRepo instance for auto-detection fallback

    Returns:
        The network key string that would be used as the Docker network name.
        Returns a key based on interface only if subnet cannot be determined.
    """
    if parent_subnet and parent_gateway:
        resolved_subnet = resolve_subnet(parent_subnet, parent_gateway)
    else:
        if interface_cache is None:
            return f"macvlan_{parent_interface}_unknown"
        resolved_subnet, _ = detect_interface_network(parent_interface, interface_cache)
        if not resolved_subnet:
            return f"macvlan_{parent_interface}_unknown"

    return f"macvlan_{parent_interface}_{resolved_subnet.replace('/', '_')}"
