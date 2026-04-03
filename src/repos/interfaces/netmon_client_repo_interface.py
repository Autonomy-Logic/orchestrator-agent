from typing import Protocol, Optional, Callable, Dict, List


class NetmonClientRepoInterface(Protocol):
    """
    Low-level interface for Unix socket communication with the netmon sidecar.

    Covers DHCP and Proxy ARP operations. For dedicated NIC operations
    (move/return/check), use NetworkCommanderRepoInterface which aggregates
    netmon commands with device management capabilities.
    """

    async def send_command(self, command: dict) -> dict: ...
    async def send_command_and_wait(self, command: dict) -> dict: ...
    async def start_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        mac_address: str,
        container_pid: int,
    ) -> dict: ...
    async def stop_dhcp(self, container_name: str, vnic_name: str) -> dict: ...
    async def request_wifi_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        parent_interface: str,
        container_pid: int,
    ) -> dict: ...
    async def setup_proxy_arp_bridge(
        self,
        container_name: str,
        container_pid: int,
        parent_interface: str,
        ip_address: str,
        gateway: str,
        subnet_mask: str = "255.255.255.0",
    ) -> dict: ...
    async def cleanup_proxy_arp_bridge(
        self,
        container_name: str,
        ip_address: Optional[str] = None,
        parent_interface: Optional[str] = None,
        veth_host: Optional[str] = None,
    ) -> dict: ...
    async def cleanup_all_proxy_arp(self) -> dict: ...
    def get_dhcp_ip(
        self, container_name: str, vnic_name: str
    ) -> Optional[str]: ...
    def register_dhcp_callback(self, callback: Callable) -> None: ...
