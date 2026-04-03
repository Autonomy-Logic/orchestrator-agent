import asyncio
import json
import os
from typing import Optional, Callable, List
from tools.logger import log_info, log_debug, log_warning, log_error

SOCKET_PATH = "/var/orchestrator/netmon.sock"
DEBOUNCE_SECONDS = 3


class NetworkEventListener:
    """
    Thin coordinator that listens for netmon events and dispatches to sub-managers.

    Owns the socket connection lifecycle and event routing. All domain logic
    is delegated to:
    - NetmonClientRepo: netmon socket communication and command sending
    - DHCPManager: DHCP resync, retry, and IP cache management
    - NetworkReconnectionManager: container reconnection on network changes
    - SerialDeviceManager: serial device matching and provisioning
    """

    def __init__(self, interface_cache=None, netmon_client=None,
                 dhcp_manager=None, reconnection_manager=None,
                 serial_device_manager=None, dedicated_nic_manager=None):
        self.socket_path = SOCKET_PATH
        self.running = False
        self.listener_task = None
        self.pending_changes = {}
        self.last_event_time = {}
        self.interface_cache = interface_cache

        # Sub-managers (injected by composition root)
        self.netmon_client = netmon_client
        self.dhcp_manager = dhcp_manager
        self.reconnection_manager = reconnection_manager
        self.serial_device_manager = serial_device_manager
        self.dedicated_nic_manager = dedicated_nic_manager

    # ========== Lifecycle ==========

    async def start(self):
        """Start the network event listener."""
        if self.running:
            if self.listener_task is None or self.listener_task.done():
                log_debug("Network event listener task is stale, restarting...")
                self.running = False
            else:
                log_debug("Network event listener is already running")
                return

        self.running = True
        self.dhcp_manager.running = True
        self.listener_task = asyncio.create_task(self._listen_loop())
        log_info("Network event listener started")

    async def stop(self):
        """Stop the network event listener."""
        self.running = False
        self.dhcp_manager.running = False
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        await self.dhcp_manager.stop()
        if self.dedicated_nic_manager:
            await self.dedicated_nic_manager.stop()
        log_info("Network event listener stopped")

    async def _listen_loop(self):
        """Main event listening loop."""
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

                    self.netmon_client.writer = writer
                    log_info("Connected to network monitor, listening for events...")

                    # Resync DHCP for existing containers on startup/reconnect
                    await self.dhcp_manager.resync_dhcp_for_existing_containers()

                    # Resync dedicated NICs and start Docker event listener
                    if self.dedicated_nic_manager:
                        await self.dedicated_nic_manager.start()

                    # Start background retry task for failed DHCP resyncs
                    if self.dhcp_manager.pending_dhcp_resyncs and not self.dhcp_manager.dhcp_retry_task:
                        self.dhcp_manager.dhcp_retry_task = asyncio.create_task(
                            self.dhcp_manager.dhcp_retry_loop()
                        )
                        log_info(
                            f"Started DHCP retry task for "
                            f"{len(self.dhcp_manager.pending_dhcp_resyncs)} pending resyncs"
                        )

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

                    self.netmon_client.writer = None
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

    # ========== Event Routing ==========

    async def _handle_event(self, event_data: dict):
        """Handle a network event from the monitor by dispatching to sub-managers."""
        try:
            event_type = event_data.get("type")

            # Route command responses (no "type" field) to netmon client
            if event_type is None:
                self.netmon_client.deliver_response(event_data)
                return

            if event_type == "network_discovery":
                log_info("Received network discovery event")
                interfaces = event_data.get("data", {}).get("interfaces", [])
                log_info(f"Discovered {len(interfaces)} network interfaces")

                for iface in interfaces:
                    interface_name = iface.get("interface")
                    ipv4_addresses = iface.get("ipv4_addresses", [])
                    gateway = iface.get("gateway")
                    iface_type = iface.get("type", "ethernet")

                    if not interface_name:
                        continue

                    subnet = ipv4_addresses[0].get("subnet") if ipv4_addresses else None

                    self.interface_cache.set_interface(interface_name, {
                        "subnet": subnet,
                        "gateway": gateway,
                        "type": iface_type,
                        "addresses": ipv4_addresses,
                    })

                    log_debug(
                        f"Cached interface {interface_name}: "
                        f"subnet={subnet}, gateway={gateway}, type={iface_type}, "
                        f"{len(ipv4_addresses)} IPv4 address(es)"
                    )

            elif event_type == "dhcp_update":
                log_info("Received DHCP update event")
                await self.dhcp_manager.handle_dhcp_update(event_data.get("data", {}))

            elif event_type == "network_change":
                log_info("Received network change event")
                iface_data = event_data.get("data", {})
                interface = iface_data.get("interface")
                ipv4_addresses = iface_data.get("ipv4_addresses", [])
                gateway = iface_data.get("gateway")
                all_interfaces = self.interface_cache.get_all_interfaces()
                existing_type = all_interfaces.get(interface, {}).get("type", "ethernet")
                iface_type = iface_data.get("type", existing_type)

                if not interface:
                    return

                if ipv4_addresses:
                    log_info(
                        f"Network change detected on {interface}: "
                        f"{len(ipv4_addresses)} IPv4 address(es), gateway: {gateway}"
                    )

                    subnet = ipv4_addresses[0].get("subnet")
                    self.interface_cache.set_interface(interface, {
                        "subnet": subnet,
                        "gateway": gateway,
                        "type": iface_type,
                        "addresses": ipv4_addresses,
                    })
                    log_debug(
                        f"Updated cache for interface {interface}: subnet={subnet}, gateway={gateway}, type={iface_type}"
                    )

                    self.pending_changes[interface] = iface_data
                    self.last_event_time[interface] = asyncio.get_event_loop().time()

                    asyncio.create_task(self._process_pending_changes(interface))
                else:
                    status = iface_data.get("status")
                    if status in ("removed", "down"):
                        # Interface was physically removed or went down
                        self.interface_cache.remove_interface(interface)
                        log_debug(f"Removed {interface} from cache (status: {status})")
                    else:
                        # Interface still exists but lost IPv4 — keep in cache
                        # so Ethernet ports without IP remain visible for dedicated NIC use
                        self.interface_cache.set_interface(interface, {
                            "subnet": None,
                            "gateway": None,
                            "type": iface_type,
                            "addresses": [],
                        })
                        log_debug(
                            f"Updated cache for {interface}: no IPv4 (kept for dedicated NIC eligibility)"
                        )

            elif event_type == "device_discovery":
                log_info("Received device discovery event")
                await self.serial_device_manager.handle_device_discovery(event_data.get("data", {}))

            elif event_type == "device_change":
                log_info("Received device change event")
                await self.serial_device_manager.handle_device_change(event_data.get("data", {}))

        except Exception as e:
            log_error(f"Error handling network event: {e}")

    async def _process_pending_changes(self, interface: str):
        """Process pending network changes after debounce period."""
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

        await self.reconnection_manager.reconnect_containers(interface, iface_data)

    # ========== Delegated Public API ==========
    # These methods delegate to sub-managers, preserving backward compatibility
    # for all existing callers that use `network_event_listener.<method>()`.

    async def send_command(self, command: dict) -> dict:
        return await self.netmon_client.send_command(command)

    async def send_command_and_wait(self, command: dict) -> dict:
        return await self.netmon_client.send_command_and_wait(command)

    async def start_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        mac_address: str,
        container_pid: int,
    ) -> dict:
        return await self.netmon_client.start_dhcp(
            container_name, vnic_name, mac_address, container_pid
        )

    async def stop_dhcp(self, container_name: str, vnic_name: str) -> dict:
        return await self.netmon_client.stop_dhcp(container_name, vnic_name)

    async def request_wifi_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        parent_interface: str,
        container_pid: int,
    ) -> dict:
        return await self.netmon_client.request_wifi_dhcp(
            container_name, vnic_name, parent_interface, container_pid
        )

    async def setup_proxy_arp_bridge(
        self,
        container_name: str,
        container_pid: int,
        parent_interface: str,
        ip_address: str,
        gateway: str,
        subnet_mask: str = "255.255.255.0",
    ) -> dict:
        return await self.netmon_client.setup_proxy_arp_bridge(
            container_name, container_pid, parent_interface,
            ip_address, gateway, subnet_mask,
        )

    async def cleanup_proxy_arp_bridge(
        self,
        container_name: str,
        ip_address: str = None,
        parent_interface: str = None,
        veth_host: str = None,
    ) -> dict:
        return await self.netmon_client.cleanup_proxy_arp_bridge(
            container_name, ip_address, parent_interface, veth_host
        )

    async def cleanup_all_proxy_arp(self) -> dict:
        return await self.netmon_client.cleanup_all_proxy_arp()

    async def move_nic_to_container(self, host_interface: str, container_pid: int) -> dict:
        return await self.netmon_client.move_nic_to_container(host_interface, container_pid)

    async def return_nic_to_host(self, host_interface: str, container_pid: int) -> dict:
        return await self.netmon_client.return_nic_to_host(host_interface, container_pid)

    async def check_nic_in_container(self, host_interface: str, container_pid: int) -> dict:
        return await self.netmon_client.check_nic_in_container(host_interface, container_pid)

    def get_dhcp_ip(self, container_name: str, vnic_name: str) -> Optional[str]:
        return self.netmon_client.get_dhcp_ip(container_name, vnic_name)

    def register_dhcp_callback(self, callback: Callable):
        self.netmon_client.register_dhcp_callback(callback)

    async def resync_serial_devices(self):
        await self.serial_device_manager.resync_serial_devices()

    def get_available_devices(self) -> List[dict]:
        return self.serial_device_manager.get_available_devices()

    def get_device_by_id(self, device_id: str) -> Optional[dict]:
        return self.serial_device_manager.get_device_by_id(device_id)

    def register_device_callback(self, callback: Callable):
        self.serial_device_manager.register_device_callback(callback)


