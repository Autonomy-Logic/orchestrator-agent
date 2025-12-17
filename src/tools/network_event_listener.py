import asyncio
import json
import os
import random
import time
from typing import Dict, Optional, Callable
import docker
from tools.logger import *
from tools.vnic_persistence import load_vnic_configs, save_vnic_configs
from tools.interface_cache import INTERFACE_CACHE
from tools.docker_tools import CLIENT, get_or_create_macvlan_network

SOCKET_PATH = "/var/orchestrator/netmon.sock"
DEBOUNCE_SECONDS = 3

# DHCP retry configuration
DHCP_RETRY_BACKOFF_BASE = 1.0  # Initial retry delay in seconds
DHCP_RETRY_BACKOFF_MAX = 300.0  # Max retry delay (5 minutes)
DHCP_RETRY_JITTER = 0.3  # Jitter factor (30%)


class NetworkEventListener:
    def __init__(self):
        self.socket_path = SOCKET_PATH
        self.running = False
        self.listener_task = None
        self.dhcp_retry_task = None
        self.pending_changes = {}
        self.last_event_time = {}
        self.writer: Optional[asyncio.StreamWriter] = None
        self.dhcp_ip_cache: Dict[str, Dict[str, str]] = {}
        self.dhcp_update_callbacks: list[Callable] = []
        # Track pending DHCP resyncs: key -> {next_retry_at, retry_count, mac_enforced}
        self.pending_dhcp_resyncs: Dict[str, Dict] = {}

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
        if self.dhcp_retry_task:
            self.dhcp_retry_task.cancel()
            try:
                await self.dhcp_retry_task
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
                    
                    # Start background retry task for failed DHCP resyncs
                    if self.pending_dhcp_resyncs and not self.dhcp_retry_task:
                        self.dhcp_retry_task = asyncio.create_task(self._dhcp_retry_loop())
                        log_info(f"Started DHCP retry task for {len(self.pending_dhcp_resyncs)} pending resyncs")

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
                                
                                # Wait for Docker to report the endpoint with correct MAC
                                # This is necessary because network.connect() returns before
                                # the interface is fully created in the container's netns
                                max_wait_seconds = 5
                                poll_interval = 0.2
                                waited = 0
                                mac_verified = False
                                
                                while waited < max_wait_seconds:
                                    await asyncio.sleep(poll_interval)
                                    waited += poll_interval
                                    container.reload()
                                    
                                    net_info = container.attrs.get("NetworkSettings", {}).get("Networks", {}).get(docker_network_name, {})
                                    reported_mac = net_info.get("MacAddress", "")
                                    
                                    if reported_mac and reported_mac.lower() == persisted_mac.lower():
                                        log_info(f"MAC enforcement verified for {container_name}:{vnic_name} after {waited:.1f}s")
                                        mac_verified = True
                                        break
                                    
                                    log_debug(f"Waiting for MAC enforcement... reported={reported_mac}, expected={persisted_mac}")
                                
                                if not mac_verified:
                                    log_warning(f"MAC enforcement may not have taken effect for {container_name}:{vnic_name} after {max_wait_seconds}s")
                                
                                # Refresh container info after waiting
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
                        key = f"{container_name}:{vnic_name}"
                        result = await self.start_dhcp(container_name, vnic_name, mac_address, container_pid)
                        if result.get("success"):
                            log_info(f"DHCP resync initiated for {key}")
                            # Remove from pending if it was there
                            self.pending_dhcp_resyncs.pop(key, None)
                        else:
                            log_warning(f"DHCP resync failed for {key}: {result.get('error')}")
                            # Clear stale DHCP IP since resync failed - status should reflect reality
                            if vnic_config.get("dhcp_ip"):
                                log_info(f"Clearing stale DHCP IP {vnic_config['dhcp_ip']} for {key}")
                                vnic_config.pop("dhcp_ip", None)
                                vnic_config.pop("dhcp_gateway", None)
                            # Add to pending for background retry
                            self.pending_dhcp_resyncs[key] = {
                                "container_name": container_name,
                                "vnic_name": vnic_name,
                                "parent_interface": parent_interface,
                                "next_retry_at": time.time() + DHCP_RETRY_BACKOFF_BASE,
                                "retry_count": 0,
                                "mac_enforced": bool(persisted_mac and persisted_mac.lower() != actual_mac.lower()),
                            }
                            log_info(f"Added {key} to pending DHCP resyncs for background retry")
                        
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

    async def _dhcp_retry_loop(self):
        """
        Background task that retries failed DHCP resyncs with exponential backoff.
        
        Runs until all pending resyncs succeed or containers are no longer applicable.
        """
        log_info("DHCP retry loop started")
        
        try:
            while self.running and self.pending_dhcp_resyncs:
                now = time.time()
                
                # Find the next key to retry
                next_key = None
                next_time = float('inf')
                
                for key, state in list(self.pending_dhcp_resyncs.items()):
                    if state["next_retry_at"] < next_time:
                        next_time = state["next_retry_at"]
                        next_key = key
                
                if next_key is None:
                    break
                
                # Wait until next retry time
                wait_time = max(0, next_time - now)
                if wait_time > 0:
                    log_debug(f"DHCP retry: waiting {wait_time:.1f}s until next retry for {next_key}")
                    await asyncio.sleep(wait_time)
                
                if not self.running or next_key not in self.pending_dhcp_resyncs:
                    continue
                
                state = self.pending_dhcp_resyncs[next_key]
                container_name = state["container_name"]
                vnic_name = state["vnic_name"]
                parent_interface = state["parent_interface"]
                retry_count = state["retry_count"]
                
                log_info(f"DHCP retry attempt {retry_count + 1} for {next_key}")
                
                try:
                    # Re-fetch fresh container state
                    container = CLIENT.containers.get(container_name)
                    container.reload()
                    
                    # Check if container is still running
                    if container.status != "running":
                        log_info(f"Container {container_name} is not running, removing from pending DHCP resyncs")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                        continue
                    
                    # Re-load vnic config to check if still DHCP mode
                    all_vnic_configs = load_vnic_configs()
                    vnic_configs = all_vnic_configs.get(container_name, [])
                    vnic_config = None
                    for vc in vnic_configs:
                        if vc.get("name") == vnic_name:
                            vnic_config = vc
                            break
                    
                    if not vnic_config:
                        log_info(f"vNIC config for {next_key} not found, removing from pending DHCP resyncs")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                        continue
                    
                    if vnic_config.get("network_mode", "dhcp") != "dhcp":
                        log_info(f"vNIC {next_key} is no longer DHCP mode, removing from pending DHCP resyncs")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                        continue
                    
                    # Get fresh PID
                    container_pid = container.attrs.get("State", {}).get("Pid", 0)
                    if container_pid <= 0:
                        log_warning(f"Container {container_name} has invalid PID, will retry later")
                        self._schedule_next_retry(next_key, state)
                        continue
                    
                    # Get fresh MAC from Docker
                    network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                    actual_mac = None
                    docker_network_name = None
                    
                    for net_name, net_info in network_settings.items():
                        if net_name.startswith(f"macvlan_{parent_interface}"):
                            actual_mac = net_info.get("MacAddress")
                            docker_network_name = net_name
                            break
                    
                    if not actual_mac:
                        log_warning(f"Could not find MAC for {next_key}, will retry later")
                        self._schedule_next_retry(next_key, state)
                        continue
                    
                    # Use persisted MAC if available, otherwise use actual
                    persisted_mac = vnic_config.get("mac_address")
                    mac_address = persisted_mac if persisted_mac else actual_mac
                    
                    # Request DHCP from netmon
                    result = await self.start_dhcp(container_name, vnic_name, mac_address, container_pid)
                    
                    if result.get("success"):
                        log_info(f"DHCP retry succeeded for {next_key} after {retry_count + 1} attempts")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                    else:
                        log_warning(f"DHCP retry failed for {next_key}: {result.get('error')}")
                        self._schedule_next_retry(next_key, state)
                    
                except docker.errors.NotFound:
                    log_info(f"Container {container_name} not found, removing from pending DHCP resyncs")
                    self.pending_dhcp_resyncs.pop(next_key, None)
                except Exception as e:
                    log_error(f"Error during DHCP retry for {next_key}: {e}")
                    self._schedule_next_retry(next_key, state)
            
            log_info("DHCP retry loop completed - no more pending resyncs")
            
        except asyncio.CancelledError:
            log_info("DHCP retry loop cancelled")
            raise
        except Exception as e:
            log_error(f"Error in DHCP retry loop: {e}")
        finally:
            self.dhcp_retry_task = None

    def _schedule_next_retry(self, key: str, state: dict):
        """Schedule the next retry with exponential backoff and jitter."""
        retry_count = state["retry_count"] + 1
        
        # Exponential backoff: base * 2^retry_count, capped at max
        delay = min(
            DHCP_RETRY_BACKOFF_BASE * (2 ** retry_count),
            DHCP_RETRY_BACKOFF_MAX
        )
        
        # Add jitter (±30%)
        jitter = delay * DHCP_RETRY_JITTER * (2 * random.random() - 1)
        delay = max(DHCP_RETRY_BACKOFF_BASE, delay + jitter)
        
        state["retry_count"] = retry_count
        state["next_retry_at"] = time.time() + delay
        
        log_debug(f"Scheduled next DHCP retry for {key} in {delay:.1f}s (attempt {retry_count + 1})")

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
