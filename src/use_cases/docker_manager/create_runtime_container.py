from . import CLIENTS, add_client, get_self_container
from tools.operations_state import set_step, set_error, clear_state
from tools.logger import *
from tools.vnic_persistence import save_vnic_configs
from tools.serial_persistence import save_serial_configs
from tools.docker_tools import (
    CLIENT,
    get_or_create_macvlan_network,
    create_internal_network,
    get_macvlan_network_key,
)
from tools.devices_usage_buffer import get_devices_usage_buffer
from tools.network_event_listener import network_event_listener
import docker
import asyncio
import random


def _generate_mac_address() -> str:
    """
    Generate a locally-administered unicast MAC address.
    
    Locally-administered addresses have bit 1 (second-least-significant) of the
    first octet set to 1, and bit 0 (least-significant) set to 0 for unicast.
    This ensures the MAC won't conflict with globally-assigned manufacturer MACs.
    
    The first octet will be one of: 0x02, 0x06, 0x0A, 0x0E, 0x12, etc.
    (any even number with bit 1 set)
    """
    # Generate random value, shift left by 2 to preserve bits 0-1, then set bit 1
    # This produces values like 0x02, 0x06, 0x0A, 0x0E, 0x12, etc.
    first_octet = 0x02 | (random.randint(0, 63) << 2)
    
    # Generate remaining 5 octets randomly
    octets = [first_octet] + [random.randint(0, 255) for _ in range(5)]
    
    return ":".join(f"{octet:02x}" for octet in octets)


def _validate_vnic_configs(vnic_configs: list) -> tuple[bool, str]:
    """
    Validate vNIC configurations to detect duplicate networks.

    Docker only allows one endpoint per (container, network) pair. When multiple vNICs
    resolve to the same MACVLAN network (same parent interface and subnet), the second
    network.connect() call will fail with "endpoint already exists" error.

    This function detects such conflicts early and returns a clear error message.

    Args:
        vnic_configs: List of vNIC configurations

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    seen_networks = {}

    for idx, vnic_config in enumerate(vnic_configs):
        vnic_name = vnic_config.get("name") or f"unnamed_vnic_{idx}"
        parent_interface = vnic_config.get("parent_interface")
        parent_subnet = vnic_config.get("subnet")
        parent_gateway = vnic_config.get("gateway")

        network_key = get_macvlan_network_key(
            parent_interface, parent_subnet, parent_gateway
        )

        if network_key in seen_networks:
            conflicting_vnic = seen_networks[network_key]
            error_msg = (
                f"Invalid vNIC configuration: vNICs '{conflicting_vnic}' and '{vnic_name}' "
                f"would connect to the same MACVLAN network ({network_key}). "
                f"Docker only allows one endpoint per container per network. "
                f"To use multiple IPs on the same physical network, consider using "
                f"different subnets or a single vNIC with additional IP configuration."
            )
            return False, error_msg

        seen_networks[network_key] = vnic_name

    return True, ""


def _create_runtime_container_sync(container_name: str, vnic_configs: list, serial_configs: list = None):
    """
    Synchronous implementation of runtime container creation.
    This function contains all blocking Docker operations and runs in a background thread.

    Args:
        container_name: Name for the runtime container
        vnic_configs: List of virtual NIC configurations, each containing:
            - name: Virtual NIC name
            - parent_interface: Physical network interface on host
            - network_mode: "dhcp" or "static"
            - ip: IP address (optional, for static mode)
            - subnet: Subnet mask (optional, for static mode)
            - gateway: Gateway address (optional, for static mode)
            - dns: List of DNS servers (optional)
            - mac_address: MAC address (optional, auto-generated if not provided)
        serial_configs: List of serial port configurations (optional), each containing:
            - name: User-friendly name for the serial port (e.g., "modbus_rtu")
            - device_id: Stable USB device identifier from /dev/serial/by-id/
            - container_path: Path inside container (e.g., "/dev/modbus0")
            - baud_rate: Baud rate for documentation purposes (optional)
    """
    if serial_configs is None:
        serial_configs = []

    log_debug(f'Attempting to create runtime container "{container_name}"')

    if container_name in CLIENTS:
        log_error(f"Container name {container_name} is already in use.")
        set_error(container_name, "Container name is already in use", "create")
        return None

    set_step(container_name, "validating_config")
    is_valid, error_msg = _validate_vnic_configs(vnic_configs)
    if not is_valid:
        log_error(f"vNIC configuration validation failed: {error_msg}")
        set_error(container_name, error_msg, "create")
        return None

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
        internal_network = create_internal_network(container_name)

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

            macvlan_network = get_or_create_macvlan_network(
                parent_interface, parent_subnet, parent_gateway
            )
            macvlan_networks.append((macvlan_network, vnic_config))

            vnic_dns = vnic_config.get("dns")
            if vnic_dns and isinstance(vnic_dns, list):
                dns_servers.extend(vnic_dns)

        set_step(container_name, "creating_container")
        log_info(f"Creating container {container_name}")

        networking_config = {}
        api_version = CLIENT.api.api_version

        for macvlan_network, vnic_config in macvlan_networks:
            vnic_name = vnic_config.get("name")
            network_mode = vnic_config.get("network_mode", "dhcp")

            endpoint_kwargs = {}

            if network_mode == "static":
                ip_address = vnic_config.get("ip")
                if ip_address:
                    ip_address = ip_address.split("/")[0]
                    endpoint_kwargs["ipv4_address"] = ip_address
                    log_debug(f"Configured manual IP {ip_address} for vNIC {vnic_name}")

            mac_address = vnic_config.get("mac")
            if not mac_address:
                mac_address = _generate_mac_address()
                vnic_config["mac_address"] = mac_address
                log_info(f"Generated MAC address {mac_address} for vNIC {vnic_name}")
            else:
                log_debug(
                    f"Using user-provided MAC address {mac_address} for vNIC {vnic_name}"
                )
            endpoint_kwargs["mac_address"] = mac_address

            networking_config[macvlan_network.name] = docker.types.EndpointConfig(
                version=api_version, **endpoint_kwargs
            )
            log_debug(
                f"Prepared EndpointConfig for MACVLAN network {macvlan_network.name}"
            )

        ## Needed to avoid docker SDK setting 'None' networking_config
        networking_config[internal_network.name] = docker.types.EndpointConfig(
            version=api_version
        )

        create_kwargs = {
            "image": image_name,
            "name": container_name,
            "detach": True,
            "restart_policy": {"Name": "always"},
            "network": internal_network.name,
            "networking_config": networking_config,
            # Real-time scheduling capabilities for PLC deterministic execution
            # SYS_NICE: Required for sched_setscheduler(SCHED_FIFO) in the PLC core
            # MKNOD: Required for dynamic serial port passthrough (creating device nodes at runtime)
            "cap_add": ["SYS_NICE", "MKNOD"],
            # ulimits for real-time scheduling:
            # - rtprio: Maximum real-time priority (99 is highest)
            # - memlock: Unlimited memory locking for future mlockall() support
            "ulimits": [
                docker.types.Ulimit(name="rtprio", soft=99, hard=99),
                docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
            ],
            # Device cgroup rules for serial port passthrough
            # These grant permission to access device classes without requiring container restart
            # when devices are hot-plugged. Device nodes are created dynamically via mknod.
            # - c 188:* rmw: USB-to-serial adapters (/dev/ttyUSB*)
            # - c 166:* rmw: ACM modems (/dev/ttyACM*)
            # - c 4:64-255 rmw: Native serial ports (/dev/ttyS*)
            "device_cgroup_rules": [
                "c 188:* rmw",  # USB-to-serial (ttyUSB*)
                "c 166:* rmw",  # ACM modems (ttyACM*)
                "c 4:64-255 rmw",  # Native serial ports (ttyS0-ttyS191)
            ],
        }

        if dns_servers:
            unique_dns = list(dict.fromkeys(dns_servers))
            create_kwargs["dns"] = unique_dns
            log_debug(f"Configuring DNS servers: {unique_dns}")

        container = CLIENT.containers.create(**create_kwargs)

        container.start()
        log_info(f"Container {container_name} created and started successfully")

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
                # Store MAC address and network name in vnic_config for DHCP IP mapping
                vnic_config["mac_address"] = vnic_mac
                vnic_config["docker_network_name"] = macvlan_network.name
                log_info(
                    f"vNIC {vnic_name} on {parent_interface}: IP={vnic_ip}, MAC={vnic_mac}"
                )

        save_vnic_configs(container_name, vnic_configs)

        if serial_configs:
            save_serial_configs(container_name, serial_configs)
            log_info(
                f"Saved {len(serial_configs)} serial port configuration(s) for container {container_name}"
            )

        log_info(
            f"Runtime container {container_name} created successfully with {len(vnic_configs)} virtual NICs"
        )

        devices_buffer = get_devices_usage_buffer()
        devices_buffer.add_device(container_name)
        log_debug(f"Registered device {container_name} for usage data collection")

        container_pid = container.attrs.get("State", {}).get("Pid", 0)
        log_debug(f"Container {container_name} has PID {container_pid}")

        dhcp_vnics = []
        for macvlan_network, vnic_config in macvlan_networks:
            network_mode = vnic_config.get("network_mode", "dhcp")
            if network_mode == "dhcp":
                vnic_name = vnic_config.get("name")
                mac_address = network_settings.get(macvlan_network.name, {}).get(
                    "MacAddress"
                )
                if mac_address and container_pid > 0:
                    dhcp_vnics.append((vnic_name, mac_address, container_pid))
                    log_debug(
                        f"Will request DHCP for vNIC {vnic_name} (MAC: {mac_address}, PID: {container_pid})"
                    )

        clear_state(container_name)

        return dhcp_vnics

    except Exception as e:
        log_error(f"Failed to create runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        set_error(container_name, str(e), "create")
        return None


async def create_runtime_container(container_name: str, vnic_configs: list, serial_configs: list = None):
    """
    Create a runtime container with MACVLAN networking for physical network bridging
    and an internal network for orchestrator communication.

    This async wrapper offloads all blocking Docker operations to a background thread
    to prevent blocking the asyncio event loop and causing websocket disconnections.

    Args:
        container_name: Name for the runtime container
        vnic_configs: List of virtual NIC configurations
        serial_configs: List of serial port configurations (optional)
    """
    dhcp_vnics = await asyncio.to_thread(
        _create_runtime_container_sync, container_name, vnic_configs, serial_configs
    )

    if dhcp_vnics:
        set_step(container_name, "starting_dhcp")
        for vnic_name, mac_address, container_pid in dhcp_vnics:
            try:
                await network_event_listener.start_dhcp(
                    container_name, vnic_name, mac_address, container_pid
                )
                log_info(f"Requested DHCP for vNIC {vnic_name}")
            except Exception as e:
                log_warning(f"Failed to request DHCP for vNIC {vnic_name}: {e}")
