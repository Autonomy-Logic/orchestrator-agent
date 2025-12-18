"""
Docker Event Listener

Monitors Docker container events (start, restart, die) and enforces MAC address
persistence for runtime containers. When a container restarts, Docker may assign
a new random MAC address to MACVLAN endpoints. This listener detects container
start events and re-applies the persisted MAC address to maintain network stability.
"""

import asyncio
from typing import Optional
import docker
from tools.logger import log_info, log_debug, log_warning, log_error
from tools.vnic_persistence import load_vnic_configs, save_vnic_configs
from tools.docker_tools import CLIENT


class DockerEventListener:
    """
    Listens for Docker container events and enforces MAC address persistence.
    
    When a container with persisted vNIC configurations starts or restarts,
    this listener checks if the MAC addresses match the persisted values.
    If there's a mismatch, it disconnects and reconnects the container to
    the MACVLAN network with the correct MAC address.
    """

    def __init__(self):
        self.running = False
        self.listener_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the Docker event listener."""
        if self.running:
            if self.listener_task is None or self.listener_task.done():
                log_debug("Docker event listener task is stale, restarting...")
                self.running = False
            else:
                log_debug("Docker event listener is already running")
                return

        self.running = True
        self.listener_task = asyncio.create_task(self._listen_loop())
        log_info("Docker event listener started")

    async def stop(self):
        """Stop the Docker event listener."""
        self.running = False
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        log_info("Docker event listener stopped")

    async def _listen_loop(self):
        """Main event listening loop."""
        try:
            while self.running:
                try:
                    # Run the blocking Docker events() call in a thread
                    await asyncio.to_thread(self._process_events)
                except Exception as e:
                    if self.running:
                        log_error(f"Error in Docker event listener: {e}")
                        await asyncio.sleep(5)
        finally:
            self.running = False
            self.listener_task = None
            log_debug("Docker event listener loop exited, state reset")

    def _process_events(self):
        """
        Process Docker events synchronously.
        This runs in a background thread to avoid blocking the event loop.
        """
        try:
            # Use a short timeout so we can check self.running periodically
            for event in CLIENT.events(decode=True, filters={"type": "container"}):
                if not self.running:
                    break

                status = event.get("status")
                actor = event.get("Actor", {})
                container_id = actor.get("ID", "")[:12]
                attributes = actor.get("Attributes", {})
                container_name = attributes.get("name", container_id)

                # We only care about container start events
                # "start" is emitted when a container starts (including after restart)
                if status == "start":
                    log_debug(f"Container start event detected: {container_name}")
                    self._handle_container_start(container_name)

        except docker.errors.APIError as e:
            if self.running:
                log_error(f"Docker API error in event listener: {e}")
        except Exception as e:
            if self.running:
                log_error(f"Unexpected error in Docker event processing: {e}")

    def _handle_container_start(self, container_name: str):
        """
        Handle a container start event by enforcing MAC address persistence.
        
        Args:
            container_name: Name of the container that started
        """
        try:
            # Load persisted vNIC configurations for this container
            vnic_configs = load_vnic_configs(container_name)
            if not vnic_configs:
                log_debug(f"No vNIC configs found for container {container_name}, skipping MAC enforcement")
                return

            # Get the container
            try:
                container = CLIENT.containers.get(container_name)
                container.reload()
            except docker.errors.NotFound:
                log_debug(f"Container {container_name} not found, skipping MAC enforcement")
                return

            if container.status != "running":
                log_debug(f"Container {container_name} is not running, skipping MAC enforcement")
                return

            network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            configs_updated = False

            for vnic_config in vnic_configs:
                vnic_name = vnic_config.get("name")
                persisted_mac = vnic_config.get("mac_address")
                docker_network_name = vnic_config.get("docker_network_name")
                parent_interface = vnic_config.get("parent_interface")

                if not persisted_mac:
                    log_debug(f"No persisted MAC for {container_name}:{vnic_name}, skipping")
                    continue

                # Find the actual network - prefer exact match by docker_network_name
                actual_network_name = None
                actual_mac = None

                if docker_network_name and docker_network_name in network_settings:
                    actual_network_name = docker_network_name
                    actual_mac = network_settings[docker_network_name].get("MacAddress")
                elif parent_interface:
                    # Fallback to prefix matching if docker_network_name not found
                    for net_name, net_info in network_settings.items():
                        if net_name.startswith(f"macvlan_{parent_interface}"):
                            actual_network_name = net_name
                            actual_mac = net_info.get("MacAddress")
                            # Update docker_network_name for future lookups
                            if not docker_network_name:
                                vnic_config["docker_network_name"] = net_name
                                configs_updated = True
                            break

                if not actual_network_name or not actual_mac:
                    log_debug(
                        f"Could not find MACVLAN network for {container_name}:{vnic_name}, "
                        f"skipping MAC enforcement"
                    )
                    continue

                # Check if MAC matches
                if persisted_mac.lower() == actual_mac.lower():
                    log_debug(
                        f"MAC address for {container_name}:{vnic_name} is correct: {actual_mac}"
                    )
                    continue

                # MAC mismatch detected - enforce persisted MAC
                log_warning(
                    f"MAC mismatch for {container_name}:{vnic_name}: "
                    f"persisted={persisted_mac}, actual={actual_mac}. Enforcing persisted MAC..."
                )

                try:
                    self._enforce_mac_address(
                        container, actual_network_name, vnic_config, persisted_mac
                    )
                    log_info(
                        f"Successfully enforced MAC {persisted_mac} for {container_name}:{vnic_name}"
                    )
                except Exception as e:
                    log_error(
                        f"Failed to enforce MAC for {container_name}:{vnic_name}: {e}"
                    )

            # Save updated configs if we filled in any missing docker_network_name
            if configs_updated:
                save_vnic_configs(container_name, vnic_configs)

        except Exception as e:
            log_error(f"Error handling container start for {container_name}: {e}")

    def _enforce_mac_address(
        self,
        container,
        network_name: str,
        vnic_config: dict,
        persisted_mac: str,
    ):
        """
        Enforce the persisted MAC address by disconnecting and reconnecting
        the container to the network with the correct MAC.
        
        Args:
            container: Docker container object
            network_name: Name of the Docker network
            vnic_config: vNIC configuration dict
            persisted_mac: The MAC address to enforce
        """
        network = CLIENT.networks.get(network_name)

        # Disconnect from the network
        network.disconnect(container, force=True)
        log_debug(f"Disconnected {container.name} from {network_name}")

        # Prepare connection kwargs
        connect_kwargs = {"mac_address": persisted_mac}

        # If static IP mode, include the IP address
        network_mode = vnic_config.get("network_mode", "dhcp")
        if network_mode == "static":
            ip_address = vnic_config.get("ip")
            if ip_address:
                # Remove CIDR prefix if present
                ip_address = ip_address.split("/")[0]
                connect_kwargs["ipv4_address"] = ip_address

        # Reconnect with the persisted MAC
        network.connect(container, **connect_kwargs)
        log_debug(f"Reconnected {container.name} to {network_name} with MAC {persisted_mac}")

        # Verify the MAC was applied
        container.reload()
        net_info = container.attrs.get("NetworkSettings", {}).get("Networks", {}).get(network_name, {})
        reported_mac = net_info.get("MacAddress", "")

        if reported_mac.lower() != persisted_mac.lower():
            log_warning(
                f"MAC enforcement may not have taken effect: "
                f"expected={persisted_mac}, reported={reported_mac}"
            )


# Singleton instance
docker_event_listener = DockerEventListener()
