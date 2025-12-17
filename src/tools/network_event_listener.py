import asyncio
import json
import os
from typing import Dict, Optional, Callable
import docker
from tools.logger import *
from tools.vnic_persistence import load_vnic_configs, save_vnic_configs
from tools.interface_cache import INTERFACE_CACHE
from tools.docker_tools import CLIENT, get_or_create_macvlan_network

SOCKET_PATH = "/var/orchestrator/netmon.sock"
DEBOUNCE_SECONDS = 3


class NetworkEventListener:
    def __init__(self):
        self.socket_path = SOCKET_PATH
        self.running = False
        self.listener_task = None
        self.pending_changes = {}
        self.last_event_time = {}
        self.writer: Optional[asyncio.StreamWriter] = None
        self.dhcp_ip_cache: Dict[str, Dict[str, str]] = {}
        self.dhcp_update_callbacks: list[Callable] = []

    async def start(self):
        """Start the network event listener"""
        if self.running:
            if self.listener_task is None or self.listener_task.done():
                log_debug("Network event listener task is stale, restarting...")
                self.running = False
            else:
                log_debug("Network event listener is already running")
                return

        self.running = True
        self.listener_task = asyncio.create_task(self._listen_loop())
        log_info("Network event listener started")

    async def stop(self):
        """Stop the network event listener"""
        self.running = False
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        log_info("Network event listener stopped")

    async def _listen_loop(self):
        """Main event listening loop"""
        try:
            while self.running:
                try:
                    if not os.path.exists(self.socket_path):
                        log_debug(
                            f"Network monitor socket not found at {self.socket_path}, "
                            f"waiting for network monitor daemon..."
                        )
                        await asyncio.sleep(5)
                        continue

                    log_info(f"Connecting to network monitor at {self.socket_path}")
                    reader, writer = await asyncio.open_unix_connection(
                        self.socket_path
                    )

                    self.writer = writer
                    log_info("Connected to network monitor, listening for events...")

                    # Resync DHCP for existing containers on startup/reconnect
                    await self._resync_dhcp_for_existing_containers()

                    while self.running:
                        try:
                            line = await asyncio.wait_for(
                                reader.readline(), timeout=1.0
                            )
                            if not line:
                                log_warning("Network monitor connection closed")
                                break

                            event_data = json.loads(line.decode("utf-8"))
                            await self._handle_event(event_data)

                        except asyncio.TimeoutError:
                            continue
                        except json.JSONDecodeError as e:
                            log_error(f"Failed to parse network event: {e}")
                        except Exception as e:
                            log_error(f"Error reading network event: {e}")
                            break

                    self.writer = None
                    writer.close()
                    await writer.wait_closed()

                except FileNotFoundError:
                    log_debug(
                        f"Network monitor socket not found, waiting for daemon to start..."
                    )
                    await asyncio.sleep(5)
                except Exception as e:
                    log_error(f"Error in network event listener: {e}")
                    await asyncio.sleep(5)
        finally:
            self.running = False
            self.listener_task = None
            log_debug("Network event listener loop exited, state reset")

    async def _handle_event(self, event_data: dict):
        """Handle a network event from the monitor"""
        try:
            event_type = event_data.get("type")

            if event_type == "network_discovery":
                log_info("Received network discovery event")
                interfaces = event_data.get("data", {}).get("interfaces", [])
                log_info(f"Discovered {len(interfaces)} network interfaces")

                for iface in interfaces:
                    interface_name = iface.get("interface")
                    ipv4_addresses = iface.get("ipv4_addresses", [])
                    gateway = iface.get("gateway")

                    if not interface_name:
                        continue

                    if ipv4_addresses:
                        subnet = ipv4_addresses[0].get("subnet")

                        INTERFACE_CACHE[interface_name] = {
                            "subnet": subnet,
                            "gateway": gateway,
                            "addresses": ipv4_addresses,
                        }

                        log_debug(
                            f"Cached interface {interface_name}: "
                            f"subnet={subnet}, gateway={gateway}, "
                            f"{len(ipv4_addresses)} IPv4 address(es)"
                        )
                    else:
                        log_debug(
                            f"Interface {interface_name} has no IPv4 addresses, skipping cache"
                        )
                        if interface_name in INTERFACE_CACHE:
                            del INTERFACE_CACHE[interface_name]
                            log_debug(
                                f"Removed {interface_name} from cache (no addresses)"
                            )

            elif event_type == "dhcp_update":
                log_info("Received DHCP update event")
                await self._handle_dhcp_update(event_data.get("data", {}))

            elif event_type == "network_change":
                log_info("Received network change event")
                iface_data = event_data.get("data", {})
                interface = iface_data.get("interface")
                ipv4_addresses = iface_data.get("ipv4_addresses", [])
                gateway = iface_data.get("gateway")

                if not interface:
                    return

                if ipv4_addresses:
                    log_info(
                        f"Network change detected on {interface}: "
                        f"{len(ipv4_addresses)} IPv4 address(es), gateway: {gateway}"
                    )

                    subnet = ipv4_addresses[0].get("subnet")
                    INTERFACE_CACHE[interface] = {
                        "subnet": subnet,
                        "gateway": gateway,
                        "addresses": ipv4_addresses,
                    }
                    log_debug(
                        f"Updated cache for interface {interface}: subnet={subnet}, gateway={gateway}"
                    )

                    self.pending_changes[interface] = iface_data
                    self.last_event_time[interface] = asyncio.get_event_loop().time()

                    asyncio.create_task(self._process_pending_changes(interface))
                else:
                    log_debug(
                        f"Interface {interface} has no IPv4 addresses after change, skipping cache update"
                    )
                    if interface in INTERFACE_CACHE:
                        del INTERFACE_CACHE[interface]
                        log_debug(f"Removed {interface} from cache (no addresses)")

        except Exception as e:
            log_error(f"Error handling network event: {e}")

    async def _process_pending_changes(self, interface: str):
        """Process pending network changes after debounce period"""
        await asyncio.sleep(DEBOUNCE_SECONDS)

        current_time = asyncio.get_event_loop().time()
        if (
            interface in self.last_event_time
            and current_time - self.last_event_time[interface] < DEBOUNCE_SECONDS
        ):
            return

        if interface not in self.pending_changes:
            return

        iface_data = self.pending_changes.pop(interface)
        log_info(f"Processing network change for interface {interface}")

        await self._reconnect_containers(interface, iface_data)

    async def _handle_dhcp_update(self, data: dict):
        """Handle DHCP IP update from netmon"""
        container_name = data.get("container_name")
        vnic_name = data.get("vnic_name")
        ip = data.get("ip")
        mac_address = data.get("mac_address")

        if not all([container_name, vnic_name, ip]):
            log_warning("Incomplete DHCP update data received")
            return

        key = f"{container_name}:{vnic_name}"
        log_info(f"DHCP update for {key}: IP={ip}")

        self.dhcp_ip_cache[key] = {
            "ip": ip,
            "mask": data.get("mask"),
            "prefix": data.get("prefix"),
            "gateway": data.get("gateway"),
            "dns": data.get("dns"),
            "mac_address": mac_address,
        }

        all_vnic_configs = load_vnic_configs()
        if container_name in all_vnic_configs:
            vnic_configs = all_vnic_configs[container_name]
            for vnic_config in vnic_configs:
                if vnic_config.get("name") == vnic_name:
                    vnic_config["dhcp_ip"] = ip
                    vnic_config["dhcp_gateway"] = data.get("gateway")
                    vnic_config["dhcp_dns"] = data.get("dns")
                    break
            save_vnic_configs(container_name, vnic_configs)
            log_debug(f"Updated vNIC config with DHCP IP for {key}")

        for callback in self.dhcp_update_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(container_name, vnic_name, data)
                else:
                    callback(container_name, vnic_name, data)
            except Exception as e:
                log_error(f"Error in DHCP update callback: {e}")

    async def send_command(self, command: dict) -> dict:
        """Send a command to netmon and wait for response"""
        if not self.writer:
            log_error("Not connected to network monitor")
            return {"success": False, "error": "Not connected to network monitor"}

        try:
            command_json = json.dumps(command) + "\n"
            self.writer.write(command_json.encode("utf-8"))
            await self.writer.drain()
            log_debug(f"Sent command to netmon: {command.get('command')}")
            return {"success": True, "message": "Command sent"}
        except Exception as e:
            log_error(f"Failed to send command to netmon: {e}")
            return {"success": False, "error": str(e)}

    async def start_dhcp(
        self, container_name: str, vnic_name: str, mac_address: str, container_pid: int
    ) -> dict:
        """Request netmon to start DHCP client for a container's vNIC"""
        command = {
            "command": "start_dhcp",
            "container_name": container_name,
            "vnic_name": vnic_name,
            "mac_address": mac_address,
            "container_pid": container_pid,
        }
        return await self.send_command(command)

    async def stop_dhcp(self, container_name: str, vnic_name: str) -> dict:
        """Request netmon to stop DHCP client for a container's vNIC"""
        command = {
            "command": "stop_dhcp",
            "container_name": container_name,
            "vnic_name": vnic_name,
        }
        return await self.send_command(command)

    def get_dhcp_ip(self, container_name: str, vnic_name: str) -> Optional[str]:
        """Get the DHCP-assigned IP for a container's vNIC"""
        key = f"{container_name}:{vnic_name}"
        cached = self.dhcp_ip_cache.get(key)
        if cached:
            return cached.get("ip")
        return None

    def register_dhcp_callback(self, callback: Callable):
        """Register a callback to be called when DHCP IP updates are received"""
        self.dhcp_update_callbacks.append(callback)

    def _get_network_subnet(self, network_name: str) -> str | None:
        """Get the subnet of a Docker network from its IPAM config."""
        try:
            network = CLIENT.networks.get(network_name)
            ipam_config = network.attrs.get("IPAM", {}).get("Config", [])
            if ipam_config:
                return ipam_config[0].get("Subnet")
        except Exception as e:
            log_debug(f"Could not get subnet for network {network_name}: {e}")
        return None

    async def _resync_dhcp_for_existing_containers(self):
        """
        Resync DHCP for existing containers on startup or reconnect.
        
        This handles the case where the host reboots and containers resume,
        but DHCP clients need to be restarted to obtain/renew IP addresses.
        """
        try:
            all_vnic_configs = load_vnic_configs()
            if not all_vnic_configs:
                log_debug("No vNIC configurations found, skipping DHCP resync")
                return

            log_info("Resyncing DHCP for existing containers...")
            
            for container_name, vnic_configs in all_vnic_configs.items():
                for vnic_config in vnic_configs:
                    network_mode = vnic_config.get("network_mode", "dhcp")
                    if network_mode != "dhcp":
                        continue
                    
                    vnic_name = vnic_config.get("name")
                    parent_interface = vnic_config.get("parent_interface")
                    
                    try:
                        # Get fresh container info from Docker
                        container = CLIENT.containers.get(container_name)
                        container.reload()
                        
                        # Skip if container is not running
                        if container.status != "running":
                            log_debug(f"Container {container_name} is not running, skipping DHCP resync")
                            continue
                        
                        # Get fresh PID from Docker
                        container_pid = container.attrs.get("State", {}).get("Pid", 0)
                        if container_pid <= 0:
                            log_warning(f"Container {container_name} has invalid PID, skipping DHCP resync")
                            continue
                        
                        # Get actual MAC address from Docker for the macvlan network
                        network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                        actual_mac = None
                        docker_network_name = None
                        
                        for net_name, net_info in network_settings.items():
                            if net_name.startswith(f"macvlan_{parent_interface}"):
                                actual_mac = net_info.get("MacAddress")
                                docker_network_name = net_name
                                break
                        
                        if not actual_mac:
                            log_warning(f"Could not find MAC address for {container_name}:{vnic_name}, skipping DHCP resync")
                            continue
                        
                        # Get persisted MAC address (authoritative for stability)
                        persisted_mac = vnic_config.get("mac_address")
                        
                        # Check for MAC mismatch and enforce persisted MAC if needed
                        if persisted_mac and persisted_mac.lower() != actual_mac.lower():
                            log_warning(
                                f"MAC mismatch for {container_name}:{vnic_name}: "
                                f"persisted={persisted_mac}, actual={actual_mac}. "
                                f"Enforcing persisted MAC by reconnecting..."
                            )
                            # Disconnect and reconnect with persisted MAC to enforce stability
                            try:
                                network = CLIENT.networks.get(docker_network_name)
                                network.disconnect(container, force=True)
                                
                                connect_kwargs = {"mac_address": persisted_mac}
                                network_mode = vnic_config.get("network_mode", "dhcp")
                                if network_mode == "static":
                                    ip_address = vnic_config.get("ip")
                                    if ip_address:
                                        connect_kwargs["ipv4_address"] = ip_address.split("/")[0]
                                
                                network.connect(container, **connect_kwargs)
                                log_info(f"Reconnected {container_name}:{vnic_name} with persisted MAC {persisted_mac}")
                                
                                # Refresh container info after reconnect
                                container.reload()
                                container_pid = container.attrs.get("State", {}).get("Pid", 0)
                                mac_address = persisted_mac
                            except Exception as e:
                                log_error(f"Failed to enforce MAC for {container_name}:{vnic_name}: {e}")
                                # Fall back to actual MAC if enforcement fails
                                mac_address = actual_mac
                        else:
                            mac_address = actual_mac
                            # Only fill MAC if missing, never overwrite existing
                            if not persisted_mac:
                                vnic_config["mac_address"] = actual_mac
                                log_info(f"Stored MAC address {actual_mac} for {container_name}:{vnic_name}")
                        
                        # Update docker_network_name if missing
                        if docker_network_name and not vnic_config.get("docker_network_name"):
                            vnic_config["docker_network_name"] = docker_network_name
                        
                        log_info(f"Starting DHCP for {container_name}:{vnic_name} (MAC: {mac_address}, PID: {container_pid})")
                        
                        # Request DHCP from netmon
                        result = await self.start_dhcp(container_name, vnic_name, mac_address, container_pid)
                        if result.get("success"):
                            log_info(f"DHCP resync initiated for {container_name}:{vnic_name}")
                        else:
                            log_warning(f"DHCP resync failed for {container_name}:{vnic_name}: {result.get('error')}")
                        
                    except docker.errors.NotFound:
                        log_debug(f"Container {container_name} not found, skipping DHCP resync")
                    except Exception as e:
                        log_error(f"Error resyncing DHCP for {container_name}:{vnic_name}: {e}")
            
            # Save updated vnic configs with fresh MAC addresses
            for container_name, vnic_configs in all_vnic_configs.items():
                save_vnic_configs(container_name, vnic_configs)
            
            log_info("DHCP resync completed")
            
        except Exception as e:
            log_error(f"Error during DHCP resync: {e}")

    async def _reconnect_containers(self, interface: str, iface_data: dict):
        """Reconnect runtime containers to new MACVLAN network after interface change"""

        try:
            all_vnic_configs = load_vnic_configs()

            if not all_vnic_configs:
                log_debug("No runtime containers with vNIC configurations found")
                return

            ipv4_addresses = iface_data.get("ipv4_addresses", [])
            if not ipv4_addresses:
                log_warning(f"No IPv4 addresses found for interface {interface}")
                return

            new_subnet = ipv4_addresses[0].get("subnet")
            new_gateway = iface_data.get("gateway")

            if not new_subnet:
                log_warning(f"No subnet found for interface {interface}")
                return

            log_info(
                f"Processing network change for interface {interface}, "
                f"new subnet: {new_subnet}"
            )

            for container_name, vnic_configs in all_vnic_configs.items():
                for vnic_config in vnic_configs:
                    parent_interface = vnic_config.get("parent_interface")

                    if parent_interface == interface:
                        log_info(
                            f"Checking container {container_name} vNIC "
                            f"{vnic_config.get('name')} for network reconnection"
                        )

                        try:
                            container = CLIENT.containers.get(container_name)
                            container.reload()

                            container_networks = container.attrs.get(
                                "NetworkSettings", {}
                            ).get("Networks", {})

                            already_on_correct_subnet = False
                            for net_name in list(container_networks.keys()):
                                if net_name.startswith(f"macvlan_{interface}"):
                                    current_subnet = self._get_network_subnet(net_name)
                                    if not current_subnet:
                                        continue

                                    if current_subnet == new_subnet:
                                        log_info(
                                            f"Container {container_name} already connected to "
                                            f"macvlan network {net_name} with subnet {current_subnet}, "
                                            f"no reconnection needed"
                                        )
                                        already_on_correct_subnet = True
                                        break

                            if already_on_correct_subnet:
                                continue

                            log_info(
                                f"Subnet changed for container {container_name}, "
                                f"reconnecting to new network"
                            )

                            for net_name in list(container_networks.keys()):
                                if net_name.startswith(f"macvlan_{interface}"):
                                    try:
                                        old_network = CLIENT.networks.get(net_name)
                                        old_network.disconnect(container, force=True)
                                        log_info(
                                            f"Disconnected {container_name} from old network {net_name}"
                                        )
                                    except Exception as e:
                                        log_debug(
                                            f"Could not disconnect from old network {net_name}: {e}"
                                        )

                            new_network = get_or_create_macvlan_network(
                                interface, new_subnet, new_gateway
                            )

                            network_mode = vnic_config.get("network_mode", "dhcp")
                            connect_kwargs = {}

                            if network_mode == "static":
                                ip_address = vnic_config.get("ip")
                                if ip_address:
                                    ip_address = ip_address.split("/")[0]
                                    connect_kwargs["ipv4_address"] = ip_address
                                    log_debug(
                                        f"Configured static IP {ip_address} for reconnection"
                                    )

                            mac_address = vnic_config.get("mac_address")
                            if mac_address:
                                connect_kwargs["mac_address"] = mac_address
                            else:
                                log_warning(
                                    f"No MAC address found for {container_name}:{vnic_config.get('name')}. "
                                    f"Docker will generate a new MAC, which may break MAC stability."
                                )

                            new_network.connect(container, **connect_kwargs)
                            log_info(
                                f"Reconnected {container_name} to new network {new_network.name}"
                            )

                        except docker.errors.NotFound:
                            log_warning(
                                f"Container {container_name} not found, may have been deleted. "
                                f"Consider cleaning up vNIC configs."
                            )
                        except Exception as e:
                            log_error(
                                f"Failed to reconnect container {container_name}: {e}"
                            )

        except Exception as e:
            log_error(f"Error reconnecting containers for interface {interface}: {e}")


network_event_listener = NetworkEventListener()
