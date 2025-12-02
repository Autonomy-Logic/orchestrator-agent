from . import CLIENTS, add_client, get_self_container
from tools.operations_state import set_step, set_error, clear_state
from tools.logger import *
from tools.vnic_persistence import save_vnic_configs
from tools.network_tools import ContainerNetworkManager
from tools.docker_tools import CLIENT
import docker
import asyncio

network_manager = ContainerNetworkManager(CLIENT)


def _create_runtime_container_sync(container_name: str, vnic_configs: list):
    """
    Synchronous implementation of runtime container creation.
    This function contains all blocking Docker operations and runs in a background thread.

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
        set_error(container_name, "Container name is already in use", "create")
        return

    try:
        image_name = "ghcr.io/autonomy-logic/openplc-runtime:latest"

        set_step(container_name, "pulling_image")
        log_info(f"Pulling image {image_name}")
        try:
            CLIENT.images.pull(image_name)
            log_info(f"Image {image_name} pulled successfully")
        except Exception as e:
            log_warning(f"Failed to pull image, will try to use local image: {e}")

        set_step(container_name, "creating_networks")
        internal_network = network_manager.create_internal_network(container_name)

        macvlan_networks = []
        dns_servers = []

        for vnic_config in vnic_configs:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")
            parent_subnet = vnic_config.get("subnet")
            parent_gateway = vnic_config.get("gateway")

            log_debug(
                f"Processing vNIC {vnic_name} for parent interface {parent_interface}"
            )

            macvlan_network = network_manager.get_or_create_macvlan_network(
                parent_interface, parent_subnet, parent_gateway
            )
            macvlan_networks.append((macvlan_network, vnic_config))

            vnic_dns = vnic_config.get("dns")
            if vnic_dns and isinstance(vnic_dns, list):
                dns_servers.extend(vnic_dns)

        set_step(container_name, "creating_container")
        log_info(f"Creating container {container_name}")

        create_kwargs = {
            "image": image_name,
            "name": container_name,
            "detach": True,
            "restart_policy": {"Name": "always"},
            "network": internal_network.name,
        }

        if dns_servers:
            unique_dns = list(dict.fromkeys(dns_servers))
            create_kwargs["dns"] = unique_dns
            log_debug(f"Configuring DNS servers: {unique_dns}")

        container = CLIENT.containers.create(**create_kwargs)

        container.start()
        log_info(f"Container {container_name} created and started successfully")

        set_step(container_name, "connecting_networks")
        for macvlan_network, vnic_config in macvlan_networks:
            vnic_name = vnic_config.get("name")
            network_mode = vnic_config.get("network_mode", "dhcp")

            connect_kwargs = {}

            if network_mode == "static":
                ip_address = vnic_config.get("ip")
                if ip_address:
                    # Docker's network.connect() expects ipv4_address without CIDR prefix
                    # (e.g., '192.168.1.10' not '192.168.1.10/24'). Normalize defensively
                    # in case the user mistakenly provides a CIDR notation.
                    ip_address = ip_address.split("/")[0]
                    connect_kwargs["ipv4_address"] = ip_address
                    log_debug(f"Configured manual IP {ip_address} for vNIC {vnic_name}")

            mac_address = vnic_config.get("mac_address")
            if mac_address:
                connect_kwargs["mac_address"] = mac_address
                log_debug(f"Configured MAC address {mac_address} for vNIC {vnic_name}")

            try:
                macvlan_network.connect(container, **connect_kwargs)
                log_info(
                    f"Connected container {container_name} to MACVLAN network {macvlan_network.name}"
                )
            except docker.errors.APIError as e:
                log_error(
                    f"Failed to connect container {container_name} to MACVLAN network {macvlan_network.name}: {e}"
                )
                raise

        try:
            main_container = get_self_container()
            if main_container:
                try:
                    internal_network.connect(main_container)
                    log_debug(
                        f"Connected {main_container.name} to internal network {internal_network.name}"
                    )
                except docker.errors.APIError as e:
                    if (
                        "already exists" in str(e).lower()
                        or "already attached" in str(e).lower()
                    ):
                        log_debug(
                            f"Container {main_container.name} already connected to {internal_network.name}"
                        )
                    else:
                        log_warning(
                            f"Could not connect {main_container.name} to internal network: {e}"
                        )
            else:
                log_warning(
                    "Could not detect orchestrator-agent container, skipping internal network connection"
                )
        except Exception as e:
            log_warning(f"Error connecting orchestrator-agent to internal network: {e}")

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

        for macvlan_network, vnic_config in macvlan_networks:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")

            if macvlan_network.name in network_settings:
                vnic_ip = network_settings[macvlan_network.name]["IPAddress"]
                vnic_mac = network_settings[macvlan_network.name]["MacAddress"]
                log_info(
                    f"vNIC {vnic_name} on {parent_interface}: IP={vnic_ip}, MAC={vnic_mac}"
                )

        save_vnic_configs(container_name, vnic_configs)

        log_info(
            f"Runtime container {container_name} created successfully with {len(vnic_configs)} virtual NICs"
        )

        clear_state(container_name)

    except Exception as e:
        log_error(f"Failed to create runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        set_error(container_name, str(e), "create")


async def create_runtime_container(container_name: str, vnic_configs: list):
    """
    Create a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.

    This async wrapper offloads all blocking Docker operations to a background thread
    to prevent blocking the asyncio event loop and causing websocket disconnections.

    Args:
        container_name: Name for the runtime container
        vnic_configs: List of virtual NIC configurations
    """
    await asyncio.to_thread(
        _create_runtime_container_sync, container_name, vnic_configs
    )
