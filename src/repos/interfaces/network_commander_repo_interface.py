from typing import Protocol, Optional, Callable, List


class NetworkCommanderRepoInterface(Protocol):
    """Abstract interface for communication with the network monitor sidecar."""

    async def send_command(self, command: dict) -> dict: ...
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
    async def move_nic_to_container(
        self, host_interface: str, container_pid: int
    ) -> dict: ...
    async def return_nic_to_host(
        self, host_interface: str, container_pid: int
    ) -> dict: ...
    async def check_nic_in_container(
        self, host_interface: str, container_pid: int
    ) -> dict: ...
    async def resync_serial_devices(self) -> None: ...
    def get_dhcp_ip(
        self, container_name: str, vnic_name: str
    ) -> Optional[str]: ...
    def register_dhcp_callback(self, callback: Callable) -> None: ...
    def get_available_devices(self) -> List[dict]: ...
    def get_device_by_id(self, device_id: str) -> Optional[dict]: ...
    def register_device_callback(self, callback: Callable) -> None: ...
