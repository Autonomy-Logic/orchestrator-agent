import asyncio
import json
import socket
import os
from tools.logger import *
from use_cases.docker_manager.vnic_persistence import load_vnic_configs
from use_cases.docker_manager.create_runtime_container import (
    get_or_create_macvlan_network,
    CLIENT,
)

SOCKET_PATH = "/var/orchestrator/netmon.sock"
DEBOUNCE_SECONDS = 3


class NetworkEventListener:
    def __init__(self):
        self.socket_path = SOCKET_PATH
        self.running = False
        self.listener_task = None
        self.pending_changes = {}
        self.last_event_time = {}

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

                    log_info("Connected to network monitor, listening for events...")

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
                    log_debug(
                        f"Interface {iface['interface']}: "
                        f"{len(iface['ipv4_addresses'])} IPv4 address(es), "
                        f"gateway: {iface.get('gateway', 'none')}"
                    )

            elif event_type == "network_change":
                log_info("Received network change event")
                iface_data = event_data.get("data", {})
                interface = iface_data.get("interface")
                ipv4_addresses = iface_data.get("ipv4_addresses", [])
                gateway = iface_data.get("gateway")

                if interface and ipv4_addresses:
                    log_info(
                        f"Network change detected on {interface}: "
                        f"{len(ipv4_addresses)} IPv4 address(es), gateway: {gateway}"
                    )

                    self.pending_changes[interface] = iface_data
                    self.last_event_time[interface] = asyncio.get_event_loop().time()

                    asyncio.create_task(self._process_pending_changes(interface))

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
                f"Reconnecting containers using interface {interface} "
                f"to new subnet {new_subnet}"
            )

            for container_name, vnic_configs in all_vnic_configs.items():
                for vnic_config in vnic_configs:
                    parent_interface = vnic_config.get("parent_interface")

                    if parent_interface == interface:
                        log_info(
                            f"Reconnecting container {container_name} vNIC "
                            f"{vnic_config.get('name')} to new network"
                        )

                        try:
                            container = CLIENT.containers.get(container_name)

                            old_network_name = f"macvlan_{interface}"
                            try:
                                old_network = CLIENT.networks.get(old_network_name)
                                old_network.disconnect(container, force=True)
                                log_info(
                                    f"Disconnected {container_name} from old network {old_network_name}"
                                )
                            except Exception as e:
                                log_debug(
                                    f"Could not disconnect from old network {old_network_name}: {e}"
                                )

                            new_network = get_or_create_macvlan_network(
                                interface, new_subnet, new_gateway
                            )

                            network_mode = vnic_config.get("network_mode", "dhcp")
                            endpoint_config = {}

                            if network_mode == "manual":
                                ip_address = vnic_config.get("ip_address")
                                subnet = vnic_config.get("subnet")

                                if ip_address and subnet:
                                    ipv4_address = f"{ip_address}/{subnet.split('/')[-1] if '/' in subnet else '24'}"
                                    endpoint_config = {
                                        "IPAMConfig": {"IPv4Address": ipv4_address}
                                    }

                            mac_address = vnic_config.get("mac_address")
                            if mac_address:
                                endpoint_config["MacAddress"] = mac_address

                            new_network.connect(container, **endpoint_config)
                            log_info(
                                f"Reconnected {container_name} to new network {new_network.name}"
                            )

                        except Exception as e:
                            log_error(
                                f"Failed to reconnect container {container_name}: {e}"
                            )

        except Exception as e:
            log_error(f"Error reconnecting containers for interface {interface}: {e}")


network_event_listener = NetworkEventListener()
