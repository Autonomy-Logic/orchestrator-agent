import asyncio
import json
from typing import Dict, List, Optional, Callable
from tools.logger import log_info, log_debug, log_error, log_warning

# Timeout for waiting for a response from netmon after sending a command.
# Some commands (move_nic_to_container, setup_proxy_arp_bridge) run subprocess
# commands that may take several seconds.
COMMAND_RESPONSE_TIMEOUT = 15


class NetmonClientRepo:
    """
    Handles Unix socket communication with the netmon sidecar.

    Owns the StreamWriter and provides command methods for DHCP, Proxy ARP,
    and other netmon operations.

    Command-response protocol:
    - Commands are sent as JSON lines on the shared Unix socket.
    - Netmon sends back a JSON line response for each command.
    - The event listener routes responses (messages without a "type" field)
      to this repo via deliver_response(), while events are handled normally.
    - A lock serializes commands so each response is matched to its command.
    """

    def __init__(self):
        self.writer: Optional[asyncio.StreamWriter] = None
        self.dhcp_ip_cache: Dict[str, Dict[str, str]] = {}
        self.dhcp_update_callbacks: List[Callable] = []
        self._response_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._command_lock: asyncio.Lock = asyncio.Lock()

    def deliver_response(self, response: dict) -> None:
        """Deliver a command response from the event listener.

        Called by NetworkEventListener when it receives a message that is
        a command response (no "type" field) rather than an event.
        """
        try:
            self._response_queue.put_nowait(response)
        except asyncio.QueueFull:
            log_warning("Command response queue full, discarding response")

    async def send_command(self, command: dict) -> dict:
        """Send a fire-and-forget command to netmon (no response expected)."""
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

    async def send_command_and_wait(self, command: dict) -> dict:
        """Send a command to netmon and wait for the response.

        Used for commands that require confirmation (e.g., dedicated NIC operations).
        Responses are delivered via deliver_response() from the event listener.
        """
        if not self.writer:
            log_error("Not connected to network monitor")
            return {"success": False, "error": "Not connected to network monitor"}

        async with self._command_lock:
            # Drain any stale response left from a previous timed-out command
            while not self._response_queue.empty():
                try:
                    self._response_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            try:
                command_json = json.dumps(command) + "\n"
                self.writer.write(command_json.encode("utf-8"))
                await self.writer.drain()
                log_debug(f"Sent command to netmon: {command.get('command')}")
            except Exception as e:
                log_error(f"Failed to send command to netmon: {e}")
                return {"success": False, "error": str(e)}

            try:
                response = await asyncio.wait_for(
                    self._response_queue.get(),
                    timeout=COMMAND_RESPONSE_TIMEOUT,
                )
                log_debug(f"Received response from netmon: {response}")
                return response
            except asyncio.TimeoutError:
                log_warning(
                    f"Timeout waiting for netmon response to '{command.get('command')}' "
                    f"after {COMMAND_RESPONSE_TIMEOUT}s"
                )
                return {"success": False, "error": "Timeout waiting for netmon response"}

    async def start_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        mac_address: str,
        container_pid: int,
    ) -> dict:
        """Request netmon to start DHCP client for a container's MACVLAN vNIC."""
        command = {
            "command": "start_dhcp",
            "container_name": container_name,
            "vnic_name": vnic_name,
            "mac_address": mac_address,
            "container_pid": container_pid,
        }
        return await self.send_command(command)

    async def stop_dhcp(self, container_name: str, vnic_name: str) -> dict:
        """Request netmon to stop DHCP client for a container's vNIC."""
        command = {
            "command": "stop_dhcp",
            "container_name": container_name,
            "vnic_name": vnic_name,
        }
        return await self.send_command(command)

    async def request_wifi_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        parent_interface: str,
        container_pid: int,
    ) -> dict:
        """
        Request DHCP for a WiFi vNIC using Proxy ARP method.

        Unlike MACVLAN DHCP (which runs inside the container's network namespace),
        Proxy ARP DHCP runs on the host's WiFi interface with a unique client-id
        (DHCP option 61) to differentiate multiple containers sharing the same
        WiFi interface.
        """
        client_id = f"{container_name}:{vnic_name}"

        command = {
            "command": "request_wifi_dhcp",
            "container_name": container_name,
            "vnic_name": vnic_name,
            "parent_interface": parent_interface,
            "container_pid": container_pid,
            "client_id": client_id,
        }

        log_info(f"Requesting WiFi DHCP for {client_id} on {parent_interface}")
        return await self.send_command(command)

    async def setup_proxy_arp_bridge(
        self,
        container_name: str,
        container_pid: int,
        parent_interface: str,
        ip_address: str,
        gateway: str,
        subnet_mask: str = "255.255.255.0",
    ) -> dict:
        """
        Request netmon to set up a Proxy ARP bridge for a container.

        Netmon has host network access and can run ip/nsenter commands.
        """
        command = {
            "command": "setup_proxy_arp_bridge",
            "container_name": container_name,
            "container_pid": container_pid,
            "parent_interface": parent_interface,
            "ip_address": ip_address,
            "gateway": gateway,
            "subnet_mask": subnet_mask,
        }
        log_info(f"Requesting Proxy ARP bridge setup for {container_name} via netmon")
        return await self.send_command(command)

    async def cleanup_proxy_arp_bridge(
        self,
        container_name: str,
        ip_address: str = None,
        parent_interface: str = None,
        veth_host: str = None,
    ) -> dict:
        """Request netmon to clean up a Proxy ARP bridge for a container."""
        command = {
            "command": "cleanup_proxy_arp_bridge",
            "container_name": container_name,
            "ip_address": ip_address,
            "parent_interface": parent_interface,
            "veth_host": veth_host,
        }
        log_info(f"Requesting Proxy ARP bridge cleanup for {container_name} via netmon")
        return await self.send_command(command)

    async def cleanup_all_proxy_arp(self) -> dict:
        """
        Request netmon to clean up all Proxy ARP veth interfaces and entries.
        Used during selfdestruct for bulk cleanup.
        """
        command = {"command": "cleanup_all_proxy_arp"}
        log_info("Requesting cleanup of all Proxy ARP interfaces via netmon")
        return await self.send_command(command)

    async def move_nic_to_container(self, host_interface: str, container_pid: int) -> dict:
        """Request netmon to move a physical NIC into a container's network namespace."""
        command = {
            "command": "move_nic_to_container",
            "host_interface": host_interface,
            "container_pid": container_pid,
        }
        log_info(f"Requesting NIC move: {host_interface} -> container PID {container_pid}")
        return await self.send_command_and_wait(command)

    async def return_nic_to_host(self, host_interface: str, container_pid: int) -> dict:
        """Request netmon to return a physical NIC from a container back to the host."""
        command = {
            "command": "return_nic_to_host",
            "host_interface": host_interface,
            "container_pid": container_pid,
        }
        log_info(f"Requesting NIC return: {host_interface} <- container PID {container_pid}")
        return await self.send_command_and_wait(command)

    async def check_nic_in_container(self, host_interface: str, container_pid: int) -> dict:
        """Check whether a NIC is present inside a container's network namespace."""
        command = {
            "command": "check_nic_in_container",
            "host_interface": host_interface,
            "container_pid": container_pid,
        }
        return await self.send_command_and_wait(command)

    def get_dhcp_ip(self, container_name: str, vnic_name: str) -> Optional[str]:
        """Get the DHCP-assigned IP for a container's vNIC."""
        key = f"{container_name}:{vnic_name}"
        cached = self.dhcp_ip_cache.get(key)
        if cached:
            return cached.get("ip")
        return None

    def register_dhcp_callback(self, callback: Callable):
        """Register a callback to be called when DHCP IP updates are received."""
        self.dhcp_update_callbacks.append(callback)
