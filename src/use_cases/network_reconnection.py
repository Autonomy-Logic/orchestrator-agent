from typing import Optional
from tools.logger import log_info, log_debug, log_warning, log_error
class NetworkReconnectionManager:
    """
    Handles container reconnection after host network changes.

    For Ethernet (MACVLAN): Reconnects container to new MACVLAN network.
    For WiFi (Proxy ARP): Updates Proxy ARP bridge configuration with new IP/gateway.
    """

    def __init__(self, netmon_client, container_runtime, vnic_repo, interface_cache):
        self.netmon_client = netmon_client
        self.container_runtime = container_runtime
        self.vnic_repo = vnic_repo
        self.interface_cache = interface_cache

    async def reconnect_containers(self, interface: str, iface_data: dict):
        """
        Reconnect runtime containers after interface network change.

        For Ethernet (MACVLAN): Reconnect container to new MACVLAN network
        For WiFi (Proxy ARP): Update Proxy ARP bridge configuration with new IP/gateway
        """

        try:
            all_vnic_configs = self.vnic_repo.load_all_configs()

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

            interface_type = self.interface_cache.get_interface_type(interface)
            is_wifi = interface_type == "wifi"

            log_info(
                f"Processing network change for interface {interface} (type: {interface_type}), "
                f"new subnet: {new_subnet}"
            )

            for container_name, vnic_configs in all_vnic_configs.items():
                for vnic_config in vnic_configs:
                    parent_interface = vnic_config.get("parent_interface")

                    if parent_interface == interface:
                        vnic_name = vnic_config.get("name")
                        log_info(
                            f"Checking container {container_name} vNIC "
                            f"{vnic_name} for network reconnection"
                        )

                        try:
                            container = self.container_runtime.get_container(container_name)
                            container.reload()

                            if is_wifi:
                                await self._reconnect_wifi_vnic(
                                    container, container_name, vnic_config,
                                    interface, new_subnet, new_gateway,
                                )
                            else:
                                await self._reconnect_macvlan_vnic(
                                    container, container_name, vnic_config,
                                    interface, new_subnet, new_gateway,
                                )

                        except self.container_runtime.NotFoundError:
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

    async def _reconnect_macvlan_vnic(
        self,
        container,
        container_name: str,
        vnic_config: dict,
        interface: str,
        new_subnet: str,
        new_gateway: str,
    ):
        """Reconnect a MACVLAN vNIC to new network after subnet change."""
        vnic_name = vnic_config.get("name")
        container_networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

        # Check if already on correct subnet
        for net_name in list(container_networks.keys()):
            if net_name.startswith(f"macvlan_{interface}"):
                current_subnet = self._get_network_subnet(net_name, self.container_runtime)
                if current_subnet == new_subnet:
                    log_info(
                        f"Container {container_name} already connected to "
                        f"network {net_name} with subnet {current_subnet}, "
                        f"no reconnection needed"
                    )
                    return

        log_info(
            f"Subnet changed for container {container_name}, "
            f"reconnecting to new MACVLAN network"
        )

        # Disconnect from old macvlan networks
        for net_name in list(container_networks.keys()):
            if net_name.startswith(f"macvlan_{interface}"):
                try:
                    old_network = self.container_runtime.get_network(net_name)
                    old_network.disconnect(container, force=True)
                    log_info(f"Disconnected {container_name} from old network {net_name}")
                except Exception as e:
                    log_debug(f"Could not disconnect from old network {net_name}: {e}")

        # Create or get new MACVLAN network
        new_network = self.container_runtime.get_or_create_macvlan_network(
            interface, new_subnet, new_gateway,
            interface_cache=self.interface_cache,
        )

        network_mode = vnic_config.get("network_mode", "dhcp")
        connect_kwargs = {}

        if network_mode == "static":
            ip_address = vnic_config.get("ip")
            if ip_address:
                ip_address = ip_address.split("/")[0]
                connect_kwargs["ipv4_address"] = ip_address
                log_debug(f"Configured static IP {ip_address} for reconnection")

        mac_address = vnic_config.get("mac_address")
        if mac_address:
            connect_kwargs["mac_address"] = mac_address
        else:
            log_warning(
                f"No MAC address found for {container_name}:{vnic_name}. "
                f"Docker will generate a new MAC, which may break MAC stability."
            )

        new_network.connect(container, **connect_kwargs)
        log_info(f"Reconnected {container_name} to new network {new_network.name}")

    async def _reconnect_wifi_vnic(
        self,
        container,
        container_name: str,
        vnic_config: dict,
        interface: str,
        new_subnet: str,
        new_gateway: str,
    ):
        """
        Reconnect a WiFi vNIC using Proxy ARP Bridge after network change.

        For static IP: Send cleanup + setup commands to netmon
        For DHCP: Send cleanup to netmon, then request new DHCP
                  (bridge setup happens automatically in netmon when IP arrives)
        """

        vnic_name = vnic_config.get("name")
        network_mode = vnic_config.get("network_mode", "dhcp")
        proxy_arp_config = vnic_config.get("_proxy_arp_config", {})

        container_pid = container.attrs.get("State", {}).get("Pid", 0)
        if container_pid <= 0:
            log_warning(f"Container {container_name} has invalid PID, cannot reconfigure WiFi vNIC")
            return

        # Clean up old Proxy ARP configuration via netmon
        old_ip = proxy_arp_config.get("ip_address")
        old_veth_host = proxy_arp_config.get("veth_host")
        if old_ip and old_veth_host:
            log_info(f"Cleaning up old Proxy ARP config for {container_name}:{vnic_name}")
            try:
                await self.netmon_client.cleanup_proxy_arp_bridge(
                    container_name, old_ip, interface, old_veth_host
                )
            except Exception as e:
                log_warning(f"Error cleaning up old Proxy ARP config: {e}")

        if network_mode == "static":
            ip_address = vnic_config.get("ip")
            if ip_address:
                ip_address = ip_address.split("/")[0]
                log_info(f"Reconfiguring static Proxy ARP for {container_name}:{vnic_name}")
                try:
                    await self.netmon_client.setup_proxy_arp_bridge(
                        container_name, container_pid, interface,
                        ip_address, new_gateway, vnic_config.get("subnet", "255.255.255.0")
                    )
                    vnic_config["_proxy_arp_config"] = {
                        "veth_host": f"veth-{container_name[:8]}",
                        "veth_container": "eth1",
                        "ip_address": ip_address,
                        "gateway": new_gateway,
                        "parent_interface": interface,
                    }
                    all_configs = self.vnic_repo.load_configs(container_name)
                    for idx, cfg in enumerate(all_configs):
                        if cfg.get("name") == vnic_name and cfg.get("parent_interface") == interface:
                            all_configs[idx] = vnic_config
                            break
                    self.vnic_repo.save_configs(container_name, all_configs)
                    log_info(f"WiFi vNIC {vnic_name} reconfigured with gateway {new_gateway}")
                except Exception as e:
                    log_error(f"Failed to reconfigure static Proxy ARP: {e}")
            else:
                log_error(f"Static IP mode but no IP configured for {container_name}:{vnic_name}")
        else:
            log_info(f"Requesting new DHCP for WiFi vNIC {container_name}:{vnic_name}")
            try:
                result = await self.netmon_client.request_wifi_dhcp(
                    container_name, vnic_name, interface, container_pid
                )
                if not result.get("success"):
                    log_warning(f"WiFi DHCP request failed: {result.get('error')}")
            except Exception as e:
                log_warning(f"Failed to request WiFi DHCP: {e}")

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
