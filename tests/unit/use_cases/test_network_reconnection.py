import pytest
from unittest.mock import MagicMock, AsyncMock

from use_cases.network_reconnection import NetworkReconnectionManager


class _NotFoundError(Exception):
    pass


def _make_manager():
    netmon = MagicMock()
    netmon.cleanup_proxy_arp_bridge = AsyncMock()
    netmon.setup_proxy_arp_bridge = AsyncMock()
    netmon.request_wifi_dhcp = AsyncMock(return_value={"success": True})
    runtime = MagicMock()
    runtime.NotFoundError = _NotFoundError
    vnic_repo = MagicMock()
    interface_cache = MagicMock()
    return NetworkReconnectionManager(netmon, runtime, vnic_repo, interface_cache)


class TestReconnectContainers:
    @pytest.mark.asyncio
    async def test_no_vnic_configs(self):
        """Empty configs → early return."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        await mgr.reconnect_containers("eth0", {"ipv4_addresses": [{"subnet": "192.168.1.0/24"}], "gateway": "192.168.1.1"})

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_ipv4_addresses(self):
        """No IPv4 addresses → early return."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth0"}]
        }

        await mgr.reconnect_containers("eth0", {"ipv4_addresses": []})

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_subnet(self):
        """Missing subnet → early return."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth0"}]
        }

        await mgr.reconnect_containers("eth0", {"ipv4_addresses": [{}], "gateway": "192.168.1.1"})

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_matching_interface(self):
        """vNICs on different interfaces are skipped."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth1"}]
        }

        await mgr.reconnect_containers("eth0", {
            "ipv4_addresses": [{"subnet": "192.168.1.0/24"}],
            "gateway": "192.168.1.1",
        })

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_container_not_found(self):
        """NotFoundError handled gracefully."""
        mgr = _make_manager()
        mgr.interface_cache.get_interface_type.return_value = "ethernet"
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth0"}]
        }
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        # Should not raise
        await mgr.reconnect_containers("eth0", {
            "ipv4_addresses": [{"subnet": "192.168.1.0/24"}],
            "gateway": "192.168.1.1",
        })

    @pytest.mark.asyncio
    async def test_generic_exception_in_reconnect(self):
        """Generic exception during reconnect for specific container is handled."""
        mgr = _make_manager()
        mgr.interface_cache.get_interface_type.return_value = "ethernet"
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth0"}]
        }
        mgr.container_runtime.get_container.side_effect = RuntimeError("Docker error")

        # Should not raise
        await mgr.reconnect_containers("eth0", {
            "ipv4_addresses": [{"subnet": "192.168.1.0/24"}],
            "gateway": "192.168.1.1",
        })

    @pytest.mark.asyncio
    async def test_outer_exception_in_reconnect_containers(self):
        """Outer exception wrapping reconnect_containers is handled (lines 88-89)."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.side_effect = RuntimeError("db error")

        # Should not raise
        await mgr.reconnect_containers("eth0", {
            "ipv4_addresses": [{"subnet": "192.168.1.0/24"}],
            "gateway": "192.168.1.1",
        })

    @pytest.mark.asyncio
    async def test_dispatches_macvlan_for_ethernet(self):
        """Ethernet interface dispatches to _reconnect_macvlan_vnic."""
        mgr = _make_manager()
        mgr.interface_cache.get_interface_type.return_value = "ethernet"
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        mgr.container_runtime.get_container.return_value = container

        new_network = MagicMock()
        new_network.name = "macvlan_eth0_new"
        mgr.container_runtime.get_or_create_macvlan_network.return_value = new_network

        await mgr.reconnect_containers("eth0", {
            "ipv4_addresses": [{"subnet": "10.0.0.0/24"}],
            "gateway": "10.0.0.1",
        })

        mgr.container_runtime.get_or_create_macvlan_network.assert_called_once()
        new_network.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_wifi_for_wifi(self):
        """WiFi interface dispatches to _reconnect_wifi_vnic."""
        mgr = _make_manager()
        mgr.interface_cache.get_interface_type.return_value = "wifi"
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "wifi_v1",
                "parent_interface": "wlan0",
                "network_mode": "dhcp",
                "_proxy_arp_config": {},
            }]
        }
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}
        mgr.container_runtime.get_container.return_value = container

        await mgr.reconnect_containers("wlan0", {
            "ipv4_addresses": [{"subnet": "10.0.0.0/24"}],
            "gateway": "10.0.0.1",
        })

        mgr.netmon_client.request_wifi_dhcp.assert_called_once()


class TestReconnectMacvlanVnic:
    @pytest.mark.asyncio
    async def test_already_on_correct_subnet(self):
        """Same subnet → no reconnection."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {"macvlan_eth0_old": {"IPAddress": "192.168.1.100"}}
            }
        }

        network = MagicMock()
        network.attrs = {"IPAM": {"Config": [{"Subnet": "192.168.1.0/24"}]}}
        mgr.container_runtime.get_network.return_value = network

        await mgr._reconnect_macvlan_vnic(
            container, "plc1",
            {"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"},
            "eth0", "192.168.1.0/24", "192.168.1.1",
        )

        mgr.container_runtime.get_or_create_macvlan_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnects_old_and_connects_new(self):
        """Different subnet → disconnect old, connect new."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {"macvlan_eth0_old": {"IPAddress": "192.168.1.100"}}
            }
        }

        old_network = MagicMock()
        old_network.attrs = {"IPAM": {"Config": [{"Subnet": "192.168.1.0/24"}]}}

        new_network = MagicMock()
        new_network.name = "macvlan_eth0_new"

        mgr.container_runtime.get_network.return_value = old_network
        mgr.container_runtime.get_or_create_macvlan_network.return_value = new_network

        await mgr._reconnect_macvlan_vnic(
            container, "plc1",
            {"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp", "mac_address": "02:00:00:00:00:01"},
            "eth0", "10.0.0.0/24", "10.0.0.1",
        )

        old_network.disconnect.assert_called_once_with(container, force=True)
        new_network.connect.assert_called_once_with(container, mac_address="02:00:00:00:00:01")

    @pytest.mark.asyncio
    async def test_disconnect_old_network_exception(self):
        """Exception disconnecting from old network is handled gracefully."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {"macvlan_eth0_old": {"IPAddress": "192.168.1.100"}}
            }
        }

        old_network = MagicMock()
        old_network.attrs = {"IPAM": {"Config": [{"Subnet": "192.168.1.0/24"}]}}
        old_network.disconnect.side_effect = RuntimeError("disconnect failed")

        new_network = MagicMock()
        new_network.name = "macvlan_eth0_new"

        mgr.container_runtime.get_network.return_value = old_network
        mgr.container_runtime.get_or_create_macvlan_network.return_value = new_network

        # Should not raise
        await mgr._reconnect_macvlan_vnic(
            container, "plc1",
            {"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"},
            "eth0", "10.0.0.0/24", "10.0.0.1",
        )

        new_network.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_static_ip_passed_to_connect(self):
        """Static mode passes ipv4_address to connect."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"NetworkSettings": {"Networks": {}}}

        new_network = MagicMock()
        mgr.container_runtime.get_or_create_macvlan_network.return_value = new_network

        await mgr._reconnect_macvlan_vnic(
            container, "plc1",
            {"name": "v1", "parent_interface": "eth0", "network_mode": "static", "ip": "10.0.0.50/24"},
            "eth0", "10.0.0.0/24", "10.0.0.1",
        )

        new_network.connect.assert_called_once_with(container, ipv4_address="10.0.0.50")


class TestReconnectWifiVnic:
    @pytest.mark.asyncio
    async def test_cleans_up_old_proxy_arp(self):
        """Old proxy ARP config is cleaned up via netmon."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {
                "ip_address": "192.168.1.50",
                "veth_host": "veth-plc1",
            },
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.cleanup_proxy_arp_bridge.assert_called_once_with(
            "plc1", "192.168.1.50", "wlan0", "veth-plc1"
        )

    @pytest.mark.asyncio
    async def test_dhcp_mode_requests_wifi_dhcp(self):
        """DHCP mode calls request_wifi_dhcp."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {},
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.request_wifi_dhcp.assert_called_once_with(
            "plc1", "wifi_v1", "wlan0", 1234
        )

    @pytest.mark.asyncio
    async def test_static_mode_calls_setup(self):
        """Static mode calls setup_proxy_arp_bridge and saves config."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        mgr.vnic_repo.load_configs.return_value = [
            {"name": "wifi_v1", "parent_interface": "wlan0", "network_mode": "static", "ip": "10.0.0.50"}
        ]

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "static",
            "ip": "10.0.0.50",
            "subnet": "255.255.255.0",
            "_proxy_arp_config": {},
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.setup_proxy_arp_bridge.assert_called_once_with(
            "plc1", 1234, "wlan0", "10.0.0.50", "10.0.0.1", "255.255.255.0"
        )
        mgr.vnic_repo.save_configs.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_old_proxy_arp_exception(self):
        """Exception cleaning up old Proxy ARP config is handled."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}
        mgr.netmon_client.cleanup_proxy_arp_bridge.side_effect = RuntimeError("cleanup error")

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {
                "ip_address": "192.168.1.50",
                "veth_host": "veth-plc1",
            },
        }

        # Should not raise, continues to DHCP request
        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.request_wifi_dhcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_static_wifi_no_ip_logs_error(self):
        """Static WiFi with no IP configured logs error."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "static",
            "_proxy_arp_config": {},
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.setup_proxy_arp_bridge.assert_not_called()

    @pytest.mark.asyncio
    async def test_static_wifi_setup_exception(self):
        """Exception during static WiFi setup is handled (lines 221-222)."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}
        mgr.netmon_client.setup_proxy_arp_bridge.side_effect = RuntimeError("netmon error")

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "static",
            "ip": "10.0.0.50",
            "subnet": "255.255.255.0",
            "_proxy_arp_config": {},
        }

        # Should not raise
        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

    @pytest.mark.asyncio
    async def test_dhcp_wifi_not_success(self):
        """WiFi DHCP request returns not success (line 232)."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}
        mgr.netmon_client.request_wifi_dhcp.return_value = {"success": False, "error": "timeout"}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {},
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

    @pytest.mark.asyncio
    async def test_dhcp_wifi_request_exception(self):
        """Exception during WiFi DHCP request is handled."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}
        mgr.netmon_client.request_wifi_dhcp.side_effect = RuntimeError("network error")

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {},
        }

        # Should not raise
        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

    @pytest.mark.asyncio
    async def test_invalid_pid_returns_early(self):
        """Container with PID 0 → early return."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 0}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {},
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "10.0.0.1"
        )

        mgr.netmon_client.request_wifi_dhcp.assert_not_called()
        mgr.netmon_client.setup_proxy_arp_bridge.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_network_skips_reconnect(self):
        """Same interface, gateway, and subnet → skip reconnect."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {
                "ip_address": "192.168.1.50",
                "gateway": "192.168.1.1",
                "parent_interface": "wlan0",
                "veth_host": "veth-plc1",
            },
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "192.168.1.0/24", "192.168.1.1"
        )

        # Should return early — no cleanup, no DHCP request
        mgr.netmon_client.cleanup_proxy_arp_bridge.assert_not_called()
        mgr.netmon_client.request_wifi_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_subnet_proceeds(self):
        """Same interface and gateway but different subnet → reconnects."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {
                "ip_address": "192.168.1.50",
                "gateway": "192.168.1.1",
                "parent_interface": "wlan0",
                "veth_host": "veth-plc1",
            },
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "10.0.0.0/24", "192.168.1.1"
        )

        # Different subnet — should proceed with reconnect
        mgr.netmon_client.request_wifi_dhcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_malformed_ip_proceeds(self):
        """Malformed IP in old config → proceed with reconnect (ValueError caught)."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 1234}}

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
            "_proxy_arp_config": {
                "ip_address": "not-an-ip",
                "gateway": "192.168.1.1",
                "parent_interface": "wlan0",
                "veth_host": "veth-plc1",
            },
        }

        await mgr._reconnect_wifi_vnic(
            container, "plc1", vnic_config, "wlan0", "192.168.1.0/24", "192.168.1.1"
        )

        # Malformed IP → proceed with reconnect
        mgr.netmon_client.request_wifi_dhcp.assert_called_once()


class TestGetNetworkSubnet:
    def test_returns_subnet(self):
        """Returns subnet from IPAM config."""
        mgr = _make_manager()
        network = MagicMock()
        network.attrs = {"IPAM": {"Config": [{"Subnet": "10.0.0.0/24"}]}}
        mgr.container_runtime.get_network.return_value = network

        assert mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime) == "10.0.0.0/24"

    def test_empty_config_returns_none(self):
        """No IPAM config returns None."""
        mgr = _make_manager()
        network = MagicMock()
        network.attrs = {"IPAM": {"Config": []}}
        mgr.container_runtime.get_network.return_value = network

        assert mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime) is None

    def test_exception_returns_none(self):
        """Exception returns None."""
        mgr = _make_manager()
        mgr.container_runtime.get_network.side_effect = RuntimeError("boom")

        assert mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime) is None
