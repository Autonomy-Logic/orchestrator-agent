from . import CLIENT, CLIENTS, HOST_NAME, add_client
from tools.logger import *
from .vnic_persistence import save_vnic_configs
from use_cases.network_monitor.interface_cache import get_interface_network
import docker
import asyncio
import time


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


def get_or_create_macvlan_network(
    parent_interface: str, parent_subnet: str = None, parent_gateway: str = None
):
    """
    Get existing MACVLAN network for a parent interface or create a new one.
    If parent_subnet and parent_gateway are not provided, attempts to auto-detect them.
    Returns the network object.
    """
    network_name = f"macvlan_{parent_interface}"

    if parent_subnet:
        network_name = f"macvlan_{parent_interface}_{parent_subnet.replace('/', '_')}"

    try:
        network = CLIENT.networks.get(network_name)
        log_debug(f"MACVLAN network {network_name} already exists, reusing it")
        return network
    except docker.errors.NotFound:
        if not parent_subnet:
            log_info(
                f"No subnet provided for {parent_interface}, attempting auto-detection"
            )
            parent_subnet, detected_gateway = detect_interface_network(parent_interface)
            if not parent_subnet:
                raise ValueError(
                    f"Could not detect subnet for interface {parent_interface}. "
                    f"Please provide parent_subnet and parent_gateway in the configuration."
                )
            if not parent_gateway:
                parent_gateway = detected_gateway

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


async def create_runtime_container(container_name: str, vnic_configs: list):
    """
    Create a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.

    Args:
        container_name: Name for the runtime container
        vnic_configs: List of virtual NIC configurations, each containing:
            - name: Virtual NIC name
            - parent_interface: Physical network interface on host
            - network_mode: "dhcp" or "manual"
            - ip_address: IP address (optional, for manual mode)
            - subnet: Subnet mask (optional, for manual mode)
            - gateway: Gateway address (optional, for manual mode)
            - dns: List of DNS servers (optional, for manual mode)
            - mac_address: MAC address (optional, auto-generated if not provided)
    """

    log_debug(f'Attempting to create runtime container "{container_name}"')

    if container_name in CLIENTS:
        log_error(f"Container name {container_name} is already in use.")
        return

    try:
        image_name = "ghcr.io/autonomy-logic/openplc-runtime:latest"

        log_info(f"Pulling image {image_name}")
        try:
            CLIENT.images.pull(image_name)
            log_info(f"Image {image_name} pulled successfully")
        except Exception as e:
            log_warning(f"Failed to pull image, will try to use local image: {e}")

        internal_network = create_internal_network(container_name)

        macvlan_networks = []
        endpoint_configs = {}

        dns_servers = []

        for vnic_config in vnic_configs:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")
            parent_subnet = vnic_config.get("parent_subnet")
            parent_gateway = vnic_config.get("parent_gateway")
            network_mode = vnic_config.get("network_mode", "dhcp")

            log_debug(
                f"Processing vNIC {vnic_name} for parent interface {parent_interface}"
            )

            macvlan_network = get_or_create_macvlan_network(
                parent_interface, parent_subnet, parent_gateway
            )
            macvlan_networks.append((macvlan_network, vnic_config))

            vnic_dns = vnic_config.get("dns")
            if vnic_dns and isinstance(vnic_dns, list):
                dns_servers.extend(vnic_dns)

            endpoint_config = {}

            if network_mode == "manual":
                ip_address = vnic_config.get("ip_address")
                subnet = vnic_config.get("subnet")
                gateway = vnic_config.get("gateway")

                if ip_address and subnet:
                    ipv4_address = f"{ip_address}/{subnet.split('/')[-1] if '/' in subnet else '24'}"

                    ipam_config = {"IPv4Address": ipv4_address}

                    if gateway:
                        ipam_config["Gateway"] = gateway

                    endpoint_config["IPAMConfig"] = ipam_config
                    log_debug(
                        f"Configured manual IP {ipv4_address} for vNIC {vnic_name}"
                    )

            mac_address = vnic_config.get("mac_address")
            if mac_address:
                endpoint_config["MacAddress"] = mac_address
                log_debug(f"Configured MAC address {mac_address} for vNIC {vnic_name}")

            endpoint_configs[macvlan_network.name] = endpoint_config

        networking_config = {internal_network.name: {}}
        networking_config.update(endpoint_configs)

        log_info(f"Creating container {container_name}")

        create_kwargs = {
            "image": image_name,
            "name": container_name,
            "detach": True,
            "restart_policy": {"Name": "always"},
            "networking_config": {"EndpointsConfig": networking_config},
        }

        if dns_servers:
            unique_dns = list(dict.fromkeys(dns_servers))
            create_kwargs["dns"] = unique_dns
            log_debug(f"Configuring DNS servers: {unique_dns}")

        container = CLIENT.containers.create(**create_kwargs)

        container.start()
        log_info(f"Container {container_name} created and started successfully")

        try:
            main_container = CLIENT.containers.get(HOST_NAME)
            internal_network.connect(main_container)
            log_debug(
                f"Connected {HOST_NAME} to internal network {internal_network.name}"
            )
        except Exception as e:
            log_error(
                f"Could not connect main container {HOST_NAME} to internal network: {e}"
            )

        container.reload()
        network_settings = container.attrs["NetworkSettings"]["Networks"]

        if internal_network.name in network_settings:
            ip_addr = network_settings[internal_network.name]["IPAddress"]
            add_client(container_name, ip_addr)
            log_info(f"Container {container_name} has internal IP {ip_addr}")
        else:
            log_warning(
                f"Could not retrieve internal IP for container {container_name}"
            )

        for vnic_config in vnic_configs:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")
            network_name = f"macvlan_{parent_interface}"

            if network_name in network_settings:
                vnic_ip = network_settings[network_name]["IPAddress"]
                vnic_mac = network_settings[network_name]["MacAddress"]
                log_info(
                    f"vNIC {vnic_name} on {parent_interface}: IP={vnic_ip}, MAC={vnic_mac}"
                )

        save_vnic_configs(container_name, vnic_configs)

        log_info(
            f"Runtime container {container_name} created successfully with {len(vnic_configs)} virtual NICs"
        )

    except Exception as e:
        log_error(f"Failed to create runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
