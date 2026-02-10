from . import get_self_container
from tools.logger import *
from tools.network_utils import get_macvlan_network_key
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


def _validate_vnic_configs(vnic_configs: list, *, interface_cache) -> tuple[bool, str]:
    """
    Validate vNIC configurations to detect duplicate networks.

    For Ethernet (MACVLAN): Docker only allows one endpoint per (container, network) pair.
    When multiple vNICs resolve to the same MACVLAN network, the second network.connect()
    call will fail with "endpoint already exists" error.

    For WiFi (Proxy ARP Bridge): Each vNIC gets its own veth pair and IP, so multiple
    WiFi vNICs on the same interface are theoretically possible but may cause routing
    conflicts. We still validate to warn about potential issues.

    Args:
        vnic_configs: List of vNIC configurations
        interface_cache: NetworkInterfaceCacheRepo instance

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    seen_macvlan_networks = {}
    seen_wifi_interfaces = {}

    for idx, vnic_config in enumerate(vnic_configs):
        vnic_name = vnic_config.get("name") or f"unnamed_vnic_{idx}"
        parent_interface = vnic_config.get("parent_interface")
        parent_subnet = vnic_config.get("subnet")
        parent_gateway = vnic_config.get("gateway")

        # Determine network type based on interface type
        interface_type = interface_cache.get_interface_type(parent_interface)

        if interface_type == "wifi":
            # WiFi uses Proxy ARP Bridge - check for duplicate interfaces
            # (multiple vNICs on same WiFi interface may cause routing issues)
            if parent_interface in seen_wifi_interfaces:
                conflicting_vnic = seen_wifi_interfaces[parent_interface]
                log_warning(
                    f"vNICs '{conflicting_vnic}' and '{vnic_name}' both use WiFi interface "
                    f"'{parent_interface}'. This may cause routing conflicts."
                )
            seen_wifi_interfaces[parent_interface] = vnic_name
        else:
            # Ethernet uses MACVLAN - strict validation for network conflicts
            network_key = get_macvlan_network_key(
                parent_interface, parent_subnet, parent_gateway,
                interface_cache=interface_cache,
            )

            if network_key in seen_macvlan_networks:
                conflicting_vnic = seen_macvlan_networks[network_key]
                error_msg = (
                    f"Invalid vNIC configuration: vNICs '{conflicting_vnic}' and '{vnic_name}' "
                    f"would connect to the same MACVLAN network ({network_key}). "
                    f"Docker only allows one endpoint per container per network. "
                    f"To use multiple IPs on the same physical network, consider using "
                    f"different subnets or a single vNIC with additional IP configuration."
                )
                return False, error_msg

            seen_macvlan_networks[network_key] = vnic_name

    return True, ""


def _validate_mac_addresses(vnic_configs: list, *, container_runtime) -> tuple[bool, str]:
    """
    Validate that user-specified MAC addresses are not already in use on the interface.

    Only checks vNIC configs that have an explicit 'mac' field set (user-provided MACs).
    Auto-generated MACs are checked elsewhere during container creation.

    Args:
        vnic_configs: List of vNIC configurations
        container_runtime: ContainerRuntimeRepo instance

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    for vnic_config in vnic_configs:
        mac_address = vnic_config.get("mac")
        if mac_address:
            parent_interface = vnic_config.get("parent_interface")
            vnic_name = vnic_config.get("name", "unnamed")

            existing_macs = container_runtime.get_existing_mac_addresses_on_interface(
                parent_interface
            )
            mac_lower = mac_address.lower()

            if mac_lower in existing_macs:
                conflicting_container = existing_macs[mac_lower]
                log_error(
                    f"MAC address {mac_address} for vNIC {vnic_name} already exists "
                    f"on container {conflicting_container} (interface: {parent_interface})"
                )
                return False, f"MAC address {mac_address} is already in use."

    return True, ""


def _create_runtime_container_sync(
    container_name: str,
    vnic_configs: list,
    serial_configs: list = None,
    runtime_version: str = None,
    *,
    container_runtime,
    vnic_repo,
    serial_repo,
    client_registry,
    interface_cache,
    operations_state,
    devices_usage_buffer,
):
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
        runtime_version: Version tag for the runtime image (optional, defaults to "latest")
        container_runtime: Optional ContainerRuntimeRepo adapter (defaults to singleton)
        vnic_repo: Optional VNICRepo adapter (defaults to singleton)
        serial_repo: Optional SerialRepo adapter (defaults to singleton)
        client_registry: Optional ClientRepo adapter (defaults to singleton)
        interface_cache: Optional InterfaceCacheRepo adapter (defaults to singleton)
        operations_state: Optional OperationsStateTracker (defaults to singleton)
    """
    if serial_configs is None:
        serial_configs = []

    log_debug(f'Attempting to create runtime container "{container_name}"')

    if client_registry.contains(container_name):
        log_error(f"Container name {container_name} is already in use.")
        operations_state.set_error(container_name, "Container name is already in use", "create")
        return None

    operations_state.set_step(container_name, "validating_config")
    is_valid, error_msg = _validate_vnic_configs(vnic_configs, interface_cache=interface_cache)
    if not is_valid:
        log_error(f"vNIC configuration validation failed: {error_msg}")
        operations_state.set_error(container_name, error_msg, "create")
        return None

    is_valid, error_msg = _validate_mac_addresses(vnic_configs, container_runtime=container_runtime)
    if not is_valid:
        log_error(f"MAC address validation failed: {error_msg}")
        operations_state.set_error(container_name, error_msg, "create")
        return None

    try:
        version_tag = runtime_version if runtime_version else "latest"
        image_name = f"ghcr.io/autonomy-logic/openplc-runtime:{version_tag}"

        operations_state.set_step(container_name, "pulling_image")
        log_info(f"Pulling image {image_name}")
        try:
            container_runtime.pull_image(image_name)
            log_info(f"Image {image_name} pulled successfully")
        except container_runtime.NotFoundError:
            # Image doesn't exist in registry, check if available locally
            try:
                container_runtime.get_image(image_name)
                log_warning(f"Image {image_name} not found in registry, using local image")
            except container_runtime.ImageNotFound:
                error_msg = f"Runtime version '{version_tag}' not found. The image {image_name} does not exist in the registry or locally."
                log_error(error_msg)
                operations_state.set_error(container_name, error_msg, "create")
                return None
        except Exception as e:
            log_warning(f"Failed to pull image, will try to use local image: {e}")

        operations_state.set_step(container_name, "creating_networks")
        internal_network = container_runtime.create_internal_network(container_name)

        # List of (network, vnic_config) tuples for MACVLAN (Ethernet) only
        # WiFi vNICs use Proxy ARP Bridge which is set up after container starts
        macvlan_networks = []
        wifi_vnics = []  # WiFi vNICs to configure with Proxy ARP after container starts
        dns_servers = []

        for vnic_config in vnic_configs:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")
            parent_subnet = vnic_config.get("subnet")
            parent_gateway = vnic_config.get("gateway")

            # Detect interface type and choose appropriate network method
            interface_type = interface_cache.get_interface_type(parent_interface)
            is_wifi = interface_type == "wifi"

            # Store for later use
            vnic_config["_interface_type"] = interface_type
            vnic_config["_is_wifi"] = is_wifi

            log_debug(
                f"Processing vNIC {vnic_name} for {interface_type} interface {parent_interface}"
            )

            if is_wifi:
                # WiFi interface - use Proxy ARP Bridge (configured after container starts)
                log_info(f"Using Proxy ARP Bridge for WiFi interface {parent_interface}")
                vnic_config["_network_method"] = "proxy_arp"
                wifi_vnics.append(vnic_config)
            else:
                # Ethernet interface - use MACVLAN (unique MAC per container)
                log_info(f"Using MACVLAN for Ethernet interface {parent_interface}")
                network = container_runtime.get_or_create_macvlan_network(
                    parent_interface, parent_subnet, parent_gateway,
                    interface_cache=interface_cache,
                )
                vnic_config["_network_method"] = "macvlan"
                macvlan_networks.append((network, vnic_config))

            vnic_dns = vnic_config.get("dns")
            if vnic_dns and isinstance(vnic_dns, list):
                dns_servers.extend(vnic_dns)

        operations_state.set_step(container_name, "creating_container")
        log_info(f"Creating container {container_name}")

        api_version = container_runtime.get_api_version()

        # Docker API <1.44 rejects container creation when networking_config
        # contains multiple network endpoints. Use network.connect() after
        # creation as a fallback for older API versions.
        use_networking_config = tuple(api_version.split(".")) >= ("1", "44")
        if not use_networking_config:
            log_info(
                f"Docker API {api_version} < 1.44: will connect MACVLAN networks after creation"
            )

        networking_config = {}
        macvlan_endpoint_configs = []
        for network, vnic_config in macvlan_networks:
            vnic_name = vnic_config.get("name")
            network_mode = vnic_config.get("network_mode", "dhcp")

            endpoint_kwargs = {}

            if network_mode == "static":
                ip_address = vnic_config.get("ip")
                if ip_address:
                    ip_address = ip_address.split("/")[0]
                    endpoint_kwargs["ipv4_address"] = ip_address
                    log_debug(f"Configured manual IP {ip_address} for vNIC {vnic_name}")

            # MACVLAN: generate/use unique MAC address per container
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

            if use_networking_config:
                networking_config[network.name] = container_runtime.create_endpoint_config(
                    version=api_version, **endpoint_kwargs
                )
            else:
                macvlan_endpoint_configs.append((network, vnic_config, endpoint_kwargs))
            log_debug(
                f"Prepared EndpointConfig for MACVLAN network {network.name}"
            )

        if use_networking_config:
            networking_config[internal_network.name] = container_runtime.create_endpoint_config(
                version=api_version
            )

        create_kwargs = {
            "image": image_name,
            "name": container_name,
            "detach": True,
            "restart_policy": {"Name": "always"},
            "network": internal_network.name,
            # Real-time scheduling capabilities for PLC deterministic execution
            # SYS_NICE: Required for sched_setscheduler(SCHED_FIFO) in the PLC core
            # MKNOD: Required for dynamic serial port passthrough (creating device nodes at runtime)
            "cap_add": ["SYS_NICE", "MKNOD"],
            # ulimits for real-time scheduling:
            # - rtprio: Maximum real-time priority (99 is highest)
            # - memlock: Unlimited memory locking for future mlockall() support
            "ulimits": [
                container_runtime.create_ulimit(name="rtprio", soft=99, hard=99),
                container_runtime.create_ulimit(name="memlock", soft=-1, hard=-1),
            ],
            # Device cgroup rules for serial port passthrough
            # These grant permission to access device classes without requiring container restart
            # when devices are hot-plugged. Device nodes are created dynamically via mknod.
            # - c 188:* rmw: USB-to-serial adapters (/dev/ttyUSB*)
            # - c 166:* rmw: ACM modems (/dev/ttyACM*)
            # - c 4:* rmw: Native serial ports (/dev/ttyS*) - major 4 includes tty devices
            "device_cgroup_rules": [
                "c 188:* rmw",  # USB-to-serial (ttyUSB*)
                "c 166:* rmw",  # ACM modems (ttyACM*)
                "c 4:* rmw",    # Native serial ports (ttyS*) and tty devices
            ],
        }

        if dns_servers:
            unique_dns = list(dict.fromkeys(dns_servers))
            create_kwargs["dns"] = unique_dns
            log_debug(f"Configuring DNS servers: {unique_dns}")

        if use_networking_config:
            create_kwargs["networking_config"] = networking_config

        container = container_runtime.create_container(**create_kwargs)

        # For older Docker API (<1.44), connect MACVLAN networks after creation.
        # If this fails, remove the container to avoid leaving it in a partial
        # state with only the internal network.
        if not use_networking_config and macvlan_endpoint_configs:
            try:
                for network, vnic_config, endpoint_kwargs in macvlan_endpoint_configs:
                    network.connect(container, **endpoint_kwargs)
                    log_debug(f"Connected container to MACVLAN network {network.name}")
            except container_runtime.APIError as e:
                log_error(f"Failed to connect MACVLAN network, removing container: {e}")
                container.remove(force=True)
                raise

        container.start()
        log_info(f"Container {container_name} created and started successfully")

        try:
            main_container = get_self_container(container_runtime=container_runtime)
            if main_container:
                try:
                    internal_network.connect(main_container)
                    log_debug(
                        f"Connected {main_container.name} to internal network {internal_network.name}"
                    )
                except container_runtime.APIError as e:
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
        container_pid = container.attrs.get("State", {}).get("Pid", 0)

        if internal_network.name in network_settings:
            ip_addr = network_settings[internal_network.name]["IPAddress"]
            client_registry.add_client(container_name, ip_addr)
            log_info(f"Container {container_name} has internal IP {ip_addr}")
        else:
            log_warning(
                f"Could not retrieve internal IP for container {container_name}"
            )

        # Log MACVLAN network details
        for network, vnic_config in macvlan_networks:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")

            if network.name in network_settings:
                vnic_ip = network_settings[network.name]["IPAddress"]
                vnic_mac = network_settings[network.name]["MacAddress"]
                # Store MAC address and network name in vnic_config for DHCP IP mapping
                vnic_config["mac_address"] = vnic_mac
                vnic_config["docker_network_name"] = network.name
                log_info(
                    f"vNIC {vnic_name} on {parent_interface} (MACVLAN): IP={vnic_ip}, MAC={vnic_mac}"
                )

        # Collect WiFi vNICs info for Proxy ARP setup (done in async wrapper via netmon)
        # Both static and DHCP WiFi vNICs are handled asynchronously since
        # proxy ARP operations must go through netmon (which has host network access)
        wifi_vnics_to_configure = []
        for vnic_config in wifi_vnics:
            vnic_name = vnic_config.get("name")
            parent_interface = vnic_config.get("parent_interface")
            wifi_vnics_to_configure.append({
                "vnic_name": vnic_name,
                "parent_interface": parent_interface,
                "container_pid": container_pid,
                "vnic_config": vnic_config,
            })

        vnic_repo.save_configs(container_name, vnic_configs)

        if serial_configs:
            serial_repo.save_configs(container_name, serial_configs)
            log_info(
                f"Saved {len(serial_configs)} serial port configuration(s) for container {container_name}"
            )

        log_info(
            f"Runtime container {container_name} created successfully with {len(vnic_configs)} virtual NICs"
        )

        devices_usage_buffer.add_device(container_name)
        log_debug(f"Registered device {container_name} for usage data collection")

        log_debug(f"Container {container_name} has PID {container_pid}")

        # Collect MACVLAN vNICs that need DHCP
        dhcp_vnics = []
        for network, vnic_config in macvlan_networks:
            network_mode = vnic_config.get("network_mode", "dhcp")
            if network_mode == "dhcp":
                vnic_name = vnic_config.get("name")
                mac_address = network_settings.get(network.name, {}).get(
                    "MacAddress"
                )
                if container_pid > 0:
                    dhcp_vnics.append((vnic_name, mac_address, container_pid))
                    log_debug(
                        f"Will request DHCP for vNIC {vnic_name} (MAC: {mac_address}, PID: {container_pid})"
                    )

        operations_state.clear_state(container_name)

        # Return both MACVLAN DHCP info and WiFi vNICs needing configuration
        return {
            "dhcp_vnics": dhcp_vnics,
            "wifi_vnics_to_configure": wifi_vnics_to_configure,
            "vnic_configs": vnic_configs,  # For saving after WiFi setup
        }

    except Exception as e:
        log_error(f"Failed to create runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        operations_state.set_error(container_name, str(e), "create")
        return None


async def create_runtime_container(
    container_name: str,
    vnic_configs: list,
    serial_configs: list = None,
    runtime_version: str = None,
    *,
    container_runtime,
    vnic_repo,
    serial_repo,
    client_registry,
    interface_cache,
    network_commander,
    operations_state,
    devices_usage_buffer,
):
    """
    Create a runtime container with MACVLAN or Proxy ARP Bridge networking for
    physical network bridging and an internal network for orchestrator communication.

    Network method selection:
    - Ethernet interfaces: MACVLAN (unique MAC per container)
    - WiFi interfaces: Proxy ARP Bridge (traffic routes through host's WiFi MAC)

    This async wrapper offloads all blocking Docker operations to a background thread
    to prevent blocking the asyncio event loop and causing websocket disconnections.

    Args:
        container_name: Name for the runtime container
        vnic_configs: List of virtual NIC configurations
        serial_configs: List of serial port configurations (optional)
        runtime_version: Version tag for the runtime image (optional, defaults to "latest")
        container_runtime: Optional ContainerRuntimeRepo adapter (defaults to singleton)
        vnic_repo: Optional VNICRepo adapter (defaults to singleton)
        serial_repo: Optional SerialRepo adapter (defaults to singleton)
        client_registry: Optional ClientRepo adapter (defaults to singleton)
        interface_cache: Optional InterfaceCacheRepo adapter (defaults to singleton)
        network_commander: Optional NetworkCommanderRepo adapter (defaults to singleton)
        operations_state: Optional OperationsStateTracker (defaults to singleton)
    """
    result = await asyncio.to_thread(
        _create_runtime_container_sync, container_name, vnic_configs, serial_configs, runtime_version,
        container_runtime=container_runtime,
        vnic_repo=vnic_repo,
        serial_repo=serial_repo,
        client_registry=client_registry,
        interface_cache=interface_cache,
        operations_state=operations_state,
        devices_usage_buffer=devices_usage_buffer,
    )

    if result is None:
        # Container creation failed
        return

    dhcp_vnics = result.get("dhcp_vnics", [])
    wifi_vnics_to_configure = result.get("wifi_vnics_to_configure", [])
    updated_vnic_configs = result.get("vnic_configs", vnic_configs)

    # Start DHCP for MACVLAN vNICs (Ethernet)
    if dhcp_vnics:
        operations_state.set_step(container_name, "starting_dhcp")
        for vnic_name, mac_address, container_pid in dhcp_vnics:
            try:
                await network_commander.start_dhcp(
                    container_name, vnic_name, mac_address, container_pid
                )
                log_info(f"Requested DHCP for MACVLAN vNIC {vnic_name} (MAC: {mac_address})")
            except Exception as e:
                log_warning(f"Failed to request DHCP for vNIC {vnic_name}: {e}")

    # Configure WiFi vNICs with Proxy ARP Bridge via netmon
    # All proxy ARP operations go through netmon (which has host network + PID access)
    if wifi_vnics_to_configure:
        operations_state.set_step(container_name, "configuring_wifi_vnics")
        for wifi_info in wifi_vnics_to_configure:
            vnic_name = wifi_info["vnic_name"]
            parent_interface = wifi_info["parent_interface"]
            container_pid = wifi_info["container_pid"]
            vnic_config = wifi_info["vnic_config"]
            network_mode = vnic_config.get("network_mode", "dhcp")

            try:
                if network_mode == "static":
                    # Static IP - send setup command to netmon
                    ip_address = vnic_config.get("ip")
                    gateway = vnic_config.get("gateway")
                    subnet = vnic_config.get("subnet", "255.255.255.0")

                    if ip_address and gateway:
                        ip_address = ip_address.split("/")[0]
                        log_info(f"Setting up Proxy ARP Bridge for WiFi vNIC {vnic_name} (static IP) via netmon")
                        await network_commander.setup_proxy_arp_bridge(
                            container_name, container_pid, parent_interface,
                            ip_address, gateway, subnet,
                        )
                        # Build proxy_arp_config locally (send_command is fire-and-forget,
                        # so the response from netmon is not received here).
                        # The naming convention is deterministic: veth-{name[:8]}
                        vnic_config["_proxy_arp_config"] = {
                            "veth_host": f"veth-{container_name[:8]}",
                            "veth_container": "eth1",
                            "ip_address": ip_address,
                            "gateway": gateway,
                            "parent_interface": parent_interface,
                        }
                        log_info(f"vNIC {vnic_name} on {parent_interface} (Proxy ARP/Static): IP={ip_address}")
                    else:
                        log_error(f"Static IP mode requires ip and gateway for WiFi vNIC {vnic_name}")
                else:
                    # DHCP mode - just request DHCP, netmon handles bridge setup
                    # when the lease arrives via its lease monitor
                    log_info(f"Requesting DHCP for WiFi vNIC {vnic_name} via Proxy ARP")
                    result = await network_commander.request_wifi_dhcp(
                        container_name, vnic_name, parent_interface, container_pid
                    )
                    if not result.get("success"):
                        log_warning(f"WiFi DHCP request failed for {vnic_name}: {result.get('error')}")
                    # Proxy ARP config will be saved via _handle_dhcp_update when IP arrives
            except Exception as e:
                log_warning(f"Failed to configure WiFi vNIC {vnic_name}: {e}")

        # Save updated vnic_configs (static WiFi vNICs have proxy_arp_config now)
        vnic_repo.save_configs(container_name, updated_vnic_configs)

    # Trigger serial device sync for the newly created container
    # This creates device nodes for any serial devices that are already connected
    if serial_configs:
        try:
            await network_commander.resync_serial_devices()
            log_info(f"Triggered serial device resync for container {container_name}")
        except Exception as e:
            log_warning(f"Failed to resync serial devices for {container_name}: {e}")


async def start_creation(container_name, vnic_configs, serial_configs=None, runtime_version=None, *, ctx):
    """
    Validate preconditions and begin container creation as a background task.

    Returns:
        Tuple of (status_dict, started: bool). If started=True, creation is running
        as a background task. If started=False, status_dict contains the error.
    """
    from tools.operations_state import begin_operation
    operations_state = ctx.operations_state

    error, ok = begin_operation(container_name, operations_state.set_creating, operations_state=operations_state)
    if not ok:
        return error, False

    log_info(f"Creating runtime container: {container_name}")
    if serial_configs:
        log_info(f"Container {container_name} will have {len(serial_configs)} serial port(s) configured")

    asyncio.create_task(
        create_runtime_container(
            container_name, vnic_configs, serial_configs, runtime_version,
            container_runtime=ctx.container_runtime,
            vnic_repo=ctx.vnic_repo,
            serial_repo=ctx.serial_repo,
            client_registry=ctx.client_registry,
            interface_cache=ctx.network_interface_cache,
            network_commander=ctx.network_event_listener,
            operations_state=ctx.operations_state,
            devices_usage_buffer=ctx.devices_usage_buffer,
        )
    )

    return {
        "status": "creating",
        "container_id": container_name,
        "message": f"Container creation started for {container_name}",
    }, True
