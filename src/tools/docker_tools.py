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
        log_debug(f"MACVLAN network {network_name} already exists, reusing it")
        return network
    except docker.errors.NotFound:

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
