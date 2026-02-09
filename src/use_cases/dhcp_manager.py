import asyncio
import random
import time
from typing import Dict, Optional
from tools.logger import log_info, log_debug, log_warning, log_error
from bootstrap import get_context

# DHCP retry configuration
DHCP_RETRY_BACKOFF_BASE = 1.0  # Initial retry delay in seconds
DHCP_RETRY_BACKOFF_MAX = 300.0  # Max retry delay (5 minutes)
DHCP_RETRY_JITTER = 0.3  # Jitter factor (30%)


class DHCPManager:
    """
    Manages DHCP resync and retry logic for container vNICs.

    Handles DHCP update events from netmon, resyncs DHCP for existing
    containers on startup/reconnect, and retries failed DHCP requests
    with exponential backoff.
    """

    def __init__(self, netmon_client):
        self.netmon_client = netmon_client
        self.running = False
        self.dhcp_retry_task = None
        # Track pending DHCP resyncs: key -> {next_retry_at, retry_count, ...}
        self.pending_dhcp_resyncs: Dict[str, Dict] = {}

    async def stop(self):
        """Stop the DHCP retry task."""
        self.running = False
        if self.dhcp_retry_task:
            self.dhcp_retry_task.cancel()
            try:
                await self.dhcp_retry_task
            except asyncio.CancelledError:
                pass

    async def handle_dhcp_update(self, data: dict):
        """Handle DHCP IP update from netmon."""

        vnic_repo = get_context().vnic_repo

        container_name = data.get("container_name")
        vnic_name = data.get("vnic_name")
        ip = data.get("ip")
        mac_address = data.get("mac_address")

        if not all([container_name, vnic_name, ip]):
            log_warning("Incomplete DHCP update data received")
            return

        key = f"{container_name}:{vnic_name}"
        log_info(f"DHCP update for {key}: IP={ip}")

        self.netmon_client.dhcp_ip_cache[key] = {
            "ip": ip,
            "mask": data.get("mask"),
            "prefix": data.get("prefix"),
            "gateway": data.get("gateway"),
            "dns": data.get("dns"),
            "mac_address": mac_address,
        }

        all_vnic_configs = vnic_repo.load_configs()
        if container_name in all_vnic_configs:
            vnic_configs = all_vnic_configs[container_name]
            for vnic_config in vnic_configs:
                if vnic_config.get("name") == vnic_name:
                    vnic_config["dhcp_ip"] = ip
                    vnic_config["dhcp_gateway"] = data.get("gateway")
                    vnic_config["dhcp_dns"] = data.get("dns")
                    proxy_arp_config = data.get("proxy_arp_config")
                    if proxy_arp_config:
                        vnic_config["_proxy_arp_config"] = proxy_arp_config
                        log_info(f"Saved Proxy ARP config for {key}: {proxy_arp_config}")
                    break
            vnic_repo.save_configs(container_name, vnic_configs)
            log_debug(f"Updated vNIC config with DHCP IP for {key}")

        for callback in self.netmon_client.dhcp_update_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(container_name, vnic_name, data)
                else:
                    callback(container_name, vnic_name, data)
            except Exception as e:
                log_error(f"Error in DHCP update callback: {e}")

    def _get_network_subnet(self, network_name: str, container_runtime) -> Optional[str]:
        """Get the subnet of a Docker network from its IPAM config."""
        try:
            network = container_runtime.get_network(network_name)
            ipam_config = network.attrs.get("IPAM", {}).get("Config", [])
            if ipam_config:
                return ipam_config[0].get("Subnet")
        except Exception as e:
            log_debug(f"Could not get subnet for network {network_name}: {e}")
        return None

    async def resync_dhcp_for_existing_containers(self):
        """
        Resync DHCP for existing containers on startup or reconnect.

        This handles the case where the host reboots and containers resume,
        but DHCP clients need to be restarted to obtain/renew IP addresses.
        """

        ctx = get_context()
        container_runtime = ctx.container_runtime
        vnic_repo = ctx.vnic_repo

        try:
            all_vnic_configs = vnic_repo.load_configs()
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
                        container = container_runtime.get_container(container_name)
                        container.reload()

                        if container.status != "running":
                            log_debug(f"Container {container_name} is not running, skipping DHCP resync")
                            continue

                        container_pid = container.attrs.get("State", {}).get("Pid", 0)
                        if container_pid <= 0:
                            log_warning(f"Container {container_name} has invalid PID, skipping DHCP resync")
                            continue

                        # Check if this is a Proxy ARP vNIC (WiFi)
                        proxy_arp_config = vnic_config.get("_proxy_arp_config")
                        if proxy_arp_config or vnic_config.get("_network_method") == "proxy_arp":
                            log_info(f"Resyncing Proxy ARP DHCP for WiFi vNIC {container_name}:{vnic_name}")
                            key = f"{container_name}:{vnic_name}"
                            result = await self.netmon_client.request_wifi_dhcp(
                                container_name, vnic_name, parent_interface, container_pid
                            )
                            if result.get("success"):
                                log_info(f"Proxy ARP DHCP resync initiated for {key}")
                                self.pending_dhcp_resyncs.pop(key, None)
                            else:
                                log_warning(f"Proxy ARP DHCP resync failed for {key}: {result.get('error')}")
                                if vnic_config.get("dhcp_ip"):
                                    vnic_config.pop("dhcp_ip", None)
                                    vnic_config.pop("dhcp_gateway", None)
                                self.pending_dhcp_resyncs[key] = {
                                    "container_name": container_name,
                                    "vnic_name": vnic_name,
                                    "parent_interface": parent_interface,
                                    "is_proxy_arp": True,
                                    "next_retry_at": time.time() + DHCP_RETRY_BACKOFF_BASE,
                                    "retry_count": 0,
                                }
                            continue

                        # Get actual MAC address from Docker for the MACVLAN network
                        network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                        actual_mac = None
                        docker_network_name = None

                        for net_name, net_info in network_settings.items():
                            if net_name.startswith(f"macvlan_{parent_interface}"):
                                actual_mac = net_info.get("MacAddress")
                                docker_network_name = net_name
                                break

                        if not actual_mac:
                            log_warning(f"Could not find MACVLAN network for {container_name}:{vnic_name}, skipping DHCP resync")
                            continue

                        # MACVLAN: Get persisted MAC address (authoritative for stability)
                        persisted_mac = vnic_config.get("mac_address")

                        # Check for MAC mismatch and enforce persisted MAC if needed
                        if persisted_mac and persisted_mac.lower() != actual_mac.lower():
                            log_warning(
                                f"MAC mismatch for {container_name}:{vnic_name}: "
                                f"persisted={persisted_mac}, actual={actual_mac}. "
                                f"Enforcing persisted MAC by reconnecting..."
                            )
                            try:
                                network = container_runtime.get_network(docker_network_name)
                                network.disconnect(container, force=True)

                                connect_kwargs = {"mac_address": persisted_mac}
                                network_mode = vnic_config.get("network_mode", "dhcp")
                                if network_mode == "static":
                                    ip_address = vnic_config.get("ip")
                                    if ip_address:
                                        connect_kwargs["ipv4_address"] = ip_address.split("/")[0]

                                network.connect(container, **connect_kwargs)
                                log_info(f"Reconnected {container_name}:{vnic_name} with persisted MAC {persisted_mac}")

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
                                    container.reload()
                                    net_info = container.attrs.get("NetworkSettings", {}).get("Networks", {}).get(docker_network_name, {})
                                    fallback_mac = net_info.get("MacAddress", "")
                                    if fallback_mac:
                                        log_warning(f"Using actual MAC {fallback_mac} instead of persisted {persisted_mac} for {container_name}:{vnic_name}")
                                        mac_address = fallback_mac
                                        vnic_config["mac_address"] = fallback_mac
                                    else:
                                        mac_address = persisted_mac
                                else:
                                    mac_address = persisted_mac

                                container.reload()
                                container_pid = container.attrs.get("State", {}).get("Pid", 0)
                            except Exception as e:
                                log_error(f"Failed to enforce MAC for {container_name}:{vnic_name}: {e}")
                                mac_address = actual_mac
                        else:
                            mac_address = actual_mac
                            if not persisted_mac:
                                vnic_config["mac_address"] = actual_mac
                                log_info(f"Stored MAC address {actual_mac} for {container_name}:{vnic_name}")

                        # Update docker_network_name if missing
                        if docker_network_name and not vnic_config.get("docker_network_name"):
                            vnic_config["docker_network_name"] = docker_network_name

                        log_info(f"Starting DHCP for {container_name}:{vnic_name} (MAC: {mac_address}, PID: {container_pid})")

                        key = f"{container_name}:{vnic_name}"
                        result = await self.netmon_client.start_dhcp(container_name, vnic_name, mac_address, container_pid)
                        if result.get("success"):
                            log_info(f"DHCP resync initiated for {key}")
                            self.pending_dhcp_resyncs.pop(key, None)
                        else:
                            log_warning(f"DHCP resync failed for {key}: {result.get('error')}")
                            if vnic_config.get("dhcp_ip"):
                                log_info(f"Clearing stale DHCP IP {vnic_config['dhcp_ip']} for {key}")
                                vnic_config.pop("dhcp_ip", None)
                                vnic_config.pop("dhcp_gateway", None)
                            self.pending_dhcp_resyncs[key] = {
                                "container_name": container_name,
                                "vnic_name": vnic_name,
                                "parent_interface": parent_interface,
                                "next_retry_at": time.time() + DHCP_RETRY_BACKOFF_BASE,
                                "retry_count": 0,
                            }
                            log_info(f"Added {key} to pending DHCP resyncs for background retry")

                    except container_runtime.NotFoundError:
                        log_debug(f"Container {container_name} not found, skipping DHCP resync")
                    except Exception as e:
                        log_error(f"Error resyncing DHCP for {container_name}:{vnic_name}: {e}")

            # Save updated vnic configs with fresh MAC addresses
            for container_name, vnic_configs in all_vnic_configs.items():
                vnic_repo.save_configs(container_name, vnic_configs)

            log_info("DHCP resync completed")

        except Exception as e:
            log_error(f"Error during DHCP resync: {e}")

    async def dhcp_retry_loop(self):
        """
        Background task that retries failed DHCP resyncs with exponential backoff.

        Runs until all pending resyncs succeed or containers are no longer applicable.
        """

        ctx = get_context()
        container_runtime = ctx.container_runtime
        vnic_repo = ctx.vnic_repo

        log_info("DHCP retry loop started")

        try:
            while self.running and self.pending_dhcp_resyncs:
                now = time.time()

                next_key = None
                next_time = float('inf')

                for key, state in list(self.pending_dhcp_resyncs.items()):
                    if state["next_retry_at"] < next_time:
                        next_time = state["next_retry_at"]
                        next_key = key

                if next_key is None:
                    break

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
                    container = container_runtime.get_container(container_name)
                    container.reload()

                    if container.status != "running":
                        log_info(f"Container {container_name} is not running, removing from pending DHCP resyncs")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                        continue

                    all_vnic_configs = vnic_repo.load_configs()
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

                    container_pid = container.attrs.get("State", {}).get("Pid", 0)
                    if container_pid <= 0:
                        log_warning(f"Container {container_name} has invalid PID, will retry later")
                        self._schedule_next_retry(next_key, state)
                        continue

                    # Check if this is a Proxy ARP retry (WiFi)
                    is_proxy_arp = state.get("is_proxy_arp", False)
                    if is_proxy_arp:
                        result = await self.netmon_client.request_wifi_dhcp(
                            container_name, vnic_name, parent_interface, container_pid
                        )
                        if result.get("success"):
                            log_info(f"Proxy ARP DHCP retry succeeded for {next_key} after {retry_count + 1} attempts")
                            self.pending_dhcp_resyncs.pop(next_key, None)
                        else:
                            log_warning(f"Proxy ARP DHCP retry failed for {next_key}: {result.get('error')}")
                            self._schedule_next_retry(next_key, state)
                        continue

                    # Get fresh MAC from Docker for MACVLAN network
                    network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                    actual_mac = None

                    for net_name, net_info in network_settings.items():
                        if net_name.startswith(f"macvlan_{parent_interface}"):
                            actual_mac = net_info.get("MacAddress")
                            break

                    if not actual_mac:
                        log_warning(f"Could not find MACVLAN network for {next_key}, will retry later")
                        self._schedule_next_retry(next_key, state)
                        continue

                    persisted_mac = vnic_config.get("mac_address")
                    mac_address = persisted_mac if persisted_mac else actual_mac

                    result = await self.netmon_client.start_dhcp(container_name, vnic_name, mac_address, container_pid)

                    if result.get("success"):
                        log_info(f"DHCP retry succeeded for {next_key} after {retry_count + 1} attempts")
                        self.pending_dhcp_resyncs.pop(next_key, None)
                    else:
                        log_warning(f"DHCP retry failed for {next_key}: {result.get('error')}")
                        self._schedule_next_retry(next_key, state)

                except container_runtime.NotFoundError:
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

        delay = min(
            DHCP_RETRY_BACKOFF_BASE * (2 ** retry_count),
            DHCP_RETRY_BACKOFF_MAX
        )

        jitter = delay * DHCP_RETRY_JITTER * (2 * random.random() - 1)
        delay = max(DHCP_RETRY_BACKOFF_BASE, delay + jitter)

        state["retry_count"] = retry_count
        state["next_retry_at"] = time.time() + delay

        log_debug(f"Scheduled next DHCP retry for {key} in {delay:.1f}s (attempt {retry_count + 1})")
