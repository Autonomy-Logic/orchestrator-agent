import docker
import time
from tools.logger import log_info, log_debug, log_warning, log_error
from tools.interface_cache import get_interface_network

CLIENT = docker.from_env()


def detect_interface_network(parent_interface: str):
    """
    Detect the subnet and gateway for a parent interface using netmon discovery cache.
    Returns (subnet, gateway) tuple or (None, None) if detection fails.

    This function reads from the interface cache populated by the netmon sidecar.
    If the cache is empty, it waits briefly for the initial discovery to arrive.
    """
    max_wait_seconds = 3
    retry_interval = 0.5
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        subnet, gateway = get_interface_network(parent_interface)

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


def get_macvlan_network_key(
    parent_interface: str,
    parent_subnet: str = None,
    parent_gateway: str = None,
) -> str:
    """
    Compute the MACVLAN network key (name) for a given interface and subnet configuration.
    This is used for validation to detect duplicate vNIC configurations that would
    resolve to the same network.

    IMPORTANT: This function intentionally mirrors the subnet resolution logic in
    get_or_create_macvlan_network() to ensure validation produces the same network
    key that actual network creation would use. If you modify the logic here, you
    must also update get_or_create_macvlan_network() to maintain consistency.

    The function handles the same input combinations as get_or_create_macvlan_network():
    - Both subnet and gateway provided: uses explicit values (converts netmask to CIDR if needed)
    - Either or both missing: falls back to detect_interface_network() auto-detection

    Args:
        parent_interface: Physical network interface on host
        parent_subnet: Subnet in netmask or CIDR format (optional, auto-detected if not provided)
        parent_gateway: Gateway address (optional, auto-detected if not provided)

    Returns:
        The network key string that would be used as the Docker network name.
        Returns a key based on interface only if subnet cannot be determined.
    """
    if parent_subnet and parent_gateway:
        if is_cidr_format(parent_subnet):
            resolved_subnet = parent_subnet
        else:
            cidr_prefix = netmask_to_cidr(parent_subnet)
            network_base = calculate_network_base(parent_gateway, parent_subnet)
            resolved_subnet = f"{network_base}/{cidr_prefix}"
    else:
        resolved_subnet, _ = detect_interface_network(parent_interface)
        if not resolved_subnet:
            return f"macvlan_{parent_interface}_unknown"

    return f"macvlan_{parent_interface}_{resolved_subnet.replace('/', '_')}"


def _validate_network_exists(network) -> bool:
    """
    Validate that a Docker network object refers to an existing network.

    Docker's networks.get() can return stale objects where the name lookup
    succeeds but the underlying network (by ID) no longer exists. This causes
    failures when trying to connect containers to the network.

    Args:
        network: Docker network object to validate

    Returns:
        True if network exists and is usable, False if stale/invalid
    """
    try:
        network.reload()
        return True
    except docker.errors.NotFound:
        return False
    except Exception as e:
        log_warning(f"Unexpected error validating network {network.name}: {e}")
        return False


def get_or_create_macvlan_network(
    parent_interface: str,
    parent_subnet: str = None,
    parent_gateway: str = None,
):
    """
    Get existing MACVLAN network for a parent interface or create a new one.
    If parent_subnet and parent_gateway are not provided, attempts to auto-detect them.
    parent_subnet can be in either:
    - Netmask format (e.g., 255.255.255.0) - will be converted to CIDR using gateway
    - CIDR format (e.g., 192.168.1.0/24) - used directly
    Returns the network object.
    """
    if parent_subnet and parent_gateway:
        if is_cidr_format(parent_subnet):
            log_debug(f"Subnet already in CIDR format: {parent_subnet}")
        else:
            cidr_prefix = netmask_to_cidr(parent_subnet)
            network_base = calculate_network_base(parent_gateway, parent_subnet)
            parent_subnet = f"{network_base}/{cidr_prefix}"
            log_debug(f"Converted netmask to CIDR notation: {parent_subnet}")
    else:
        parent_subnet, parent_gateway = detect_interface_network(parent_interface)

        if not parent_subnet:
            raise ValueError(
                f"Could not detect subnet for interface {parent_interface}. "
                f"The interface may not exist or netmon may not be running."
            )

    network_name = f"macvlan_{parent_interface}_{parent_subnet.replace('/', '_')}"

    try:
        network = CLIENT.networks.get(network_name)

        # Validate the network actually exists (not a stale reference)
        if _validate_network_exists(network):
            log_debug(f"MACVLAN network {network_name} already exists, reusing it")
            return network
        else:
            # Network lookup succeeded but it's stale - try to remove it
            log_warning(
                f"MACVLAN network {network_name} exists but is stale (underlying network not found). "
                f"Removing stale reference and recreating..."
            )
            try:
                network.remove()
            except Exception as remove_err:
                log_debug(f"Could not remove stale network {network_name}: {remove_err}")
            # Fall through to create a new network

    except docker.errors.NotFound:
        pass  # Network doesn't exist, will create below

    log_info(
        f"Creating new MACVLAN network {network_name} for parent interface {parent_interface} "
        f"with subnet {parent_subnet} and gateway {parent_gateway}"
    )
    try:
        ipam_pool_config = {"subnet": parent_subnet}
        if parent_gateway:
            ipam_pool_config["gateway"] = parent_gateway

        ipam_pool = docker.types.IPAMPool(**ipam_pool_config)
        ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])
        network = CLIENT.networks.create(
            name=network_name,
            driver="macvlan",
            options={"parent": parent_interface},
            ipam=ipam_config,
        )
        log_info(f"MACVLAN network {network_name} created successfully")
        return network
    except docker.errors.APIError as e:
        if "overlaps" in str(e).lower():
            log_warning(
                f"Network overlap detected for subnet {parent_subnet}. "
                f"Searching for existing MACVLAN network to reuse..."
            )

            try:
                all_networks = CLIENT.networks.list()
                for net in all_networks:
                    if net.attrs.get("Driver") == "macvlan":
                        net_options = net.attrs.get("Options", {})
                        net_parent = net_options.get("parent")

                        ipam = net.attrs.get("IPAM", {})
                        if ipam and ipam.get("Config"):
                            for config in ipam["Config"]:
                                net_subnet = config.get("Subnet")
                                if (
                                    net_subnet == parent_subnet
                                    and net_parent == parent_interface
                                ):
                                    log_info(
                                        f"Found existing MACVLAN network {net.name} with matching "
                                        f"subnet {parent_subnet} and parent {parent_interface}. Reusing it."
                                    )
                                    return net

                log_error(
                    f"Network overlap error but could not find existing MACVLAN network "
                    f"for subnet {parent_subnet} and parent {parent_interface}"
                )
                raise
            except Exception as search_error:
                log_error(f"Error searching for existing networks: {search_error}")
                raise
        else:
            log_error(f"Failed to create MACVLAN network {network_name}: {e}")
            raise


def get_existing_mac_addresses_on_interface(parent_interface: str) -> dict[str, str]:
    """
    Get all MAC addresses currently in use by containers on MACVLAN networks
    attached to a specific parent interface.

    Args:
        parent_interface: Physical network interface on host (e.g., "eth0", "ens33")

    Returns:
        Dictionary mapping MAC address (lowercase) to container name
    """
    mac_to_container: dict[str, str] = {}

    try:
        # Find all MACVLAN networks attached to this parent interface
        macvlan_networks = []
        all_networks = CLIENT.networks.list()
        for net in all_networks:
            if net.attrs.get("Driver") == "macvlan":
                net_options = net.attrs.get("Options", {})
                net_parent = net_options.get("parent")
                if net_parent == parent_interface:
                    macvlan_networks.append(net.name)

        if not macvlan_networks:
            log_debug(
                f"No MACVLAN networks found for parent interface {parent_interface}"
            )
            return mac_to_container

        # Get all containers and check their network connections
        all_containers = CLIENT.containers.list(all=True)
        for container in all_containers:
            network_settings = container.attrs.get("NetworkSettings", {}).get(
                "Networks", {}
            )
            for net_name, net_info in network_settings.items():
                if net_name in macvlan_networks:
                    mac_address = net_info.get("MacAddress", "")
                    if mac_address:
                        mac_to_container[mac_address.lower()] = container.name
                        log_debug(
                            f"Found MAC {mac_address} on container {container.name} "
                            f"(network: {net_name})"
                        )

    except Exception as e:
        log_error(
            f"Error getting existing MAC addresses for interface {parent_interface}: {e}"
        )

    return mac_to_container


def create_internal_network(container_name: str):
    """
    Create an internal bridge network for orchestrator-runtime communication.
    Returns the network object.
    """
    network_name = f"{container_name}_internal"

    try:
        network = CLIENT.networks.get(network_name)
        log_debug(f"Internal network {network_name} already exists")
        return network
    except docker.errors.NotFound:
        log_info(f"Creating internal network {network_name}")
        try:
            network = CLIENT.networks.create(
                name=network_name, driver="bridge", internal=True
            )
            log_info(f"Internal network {network_name} created successfully")
            return network
        except Exception as e:
            log_error(f"Failed to create internal network {network_name}: {e}")
            raise
