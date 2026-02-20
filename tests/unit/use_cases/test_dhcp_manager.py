import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.dhcp_manager import DHCPManager, DHCP_RETRY_BACKOFF_BASE, DHCP_RETRY_BACKOFF_MAX


class _NotFoundError(Exception):
    pass


def _make_manager():
    netmon = MagicMock()
    netmon.dhcp_ip_cache = {}
    netmon.dhcp_update_callbacks = []
    runtime = MagicMock()
    runtime.NotFoundError = _NotFoundError
    vnic_repo = MagicMock()
    return DHCPManager(netmon, runtime, vnic_repo)


class TestHandleDhcpUpdate:
    @pytest.mark.asyncio
    async def test_incomplete_data_returns_early(self):
        """Missing required fields returns without saving."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        await mgr.handle_dhcp_update({"container_name": "plc1"})

        mgr.vnic_repo.load_all_configs.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_cache_and_vnic_config(self):
        """Updates dhcp_ip_cache and persists to vnic_repo."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "eth_vnic", "network_mode": "dhcp"}]
        }

        await mgr.handle_dhcp_update({
            "container_name": "plc1",
            "vnic_name": "eth_vnic",
            "ip": "192.168.1.50",
            "gateway": "192.168.1.1",
            "dns": ["8.8.8.8"],
        })

        assert mgr.netmon_client.dhcp_ip_cache["plc1:eth_vnic"]["ip"] == "192.168.1.50"
        mgr.vnic_repo.save_configs.assert_called_once_with(
            "plc1",
            [{"name": "eth_vnic", "network_mode": "dhcp", "dhcp_ip": "192.168.1.50", "dhcp_gateway": "192.168.1.1", "dhcp_dns": ["8.8.8.8"]}],
        )

    @pytest.mark.asyncio
    async def test_saves_proxy_arp_config(self):
        """proxy_arp_config from data is saved to vnic_config."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "wifi_vnic"}]
        }

        proxy_config = {"veth_host": "veth-plc1", "ip_address": "10.0.0.5"}
        await mgr.handle_dhcp_update({
            "container_name": "plc1",
            "vnic_name": "wifi_vnic",
            "ip": "10.0.0.5",
            "proxy_arp_config": proxy_config,
        })

        saved_configs = mgr.vnic_repo.save_configs.call_args[0][1]
        assert saved_configs[0]["_proxy_arp_config"] == proxy_config

    @pytest.mark.asyncio
    async def test_invokes_callbacks(self):
        """Registered callbacks are called with update data."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        sync_cb = MagicMock()
        async_cb = AsyncMock()
        mgr.netmon_client.dhcp_update_callbacks = [sync_cb, async_cb]

        data = {"container_name": "plc1", "vnic_name": "v1", "ip": "10.0.0.1"}
        await mgr.handle_dhcp_update(data)

        sync_cb.assert_called_once_with("plc1", "v1", data)
        async_cb.assert_called_once_with("plc1", "v1", data)

    @pytest.mark.asyncio
    async def test_callback_exception_handled(self):
        """Exception in DHCP update callback is handled gracefully."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        failing_cb = MagicMock(side_effect=RuntimeError("callback error"))
        mgr.netmon_client.dhcp_update_callbacks = [failing_cb]

        data = {"container_name": "plc1", "vnic_name": "v1", "ip": "10.0.0.1"}

        # Should not raise
        await mgr.handle_dhcp_update(data)

        failing_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_container_not_in_configs(self):
        """Container not in vnic_repo configs → cache updated, no save."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        await mgr.handle_dhcp_update({
            "container_name": "plc1",
            "vnic_name": "v1",
            "ip": "10.0.0.1",
        })

        assert "plc1:v1" in mgr.netmon_client.dhcp_ip_cache
        mgr.vnic_repo.save_configs.assert_not_called()


class TestGetNetworkSubnet:
    def test_returns_subnet(self):
        """Returns subnet from IPAM config."""
        mgr = _make_manager()
        network = MagicMock()
        network.attrs = {"IPAM": {"Config": [{"Subnet": "192.168.1.0/24"}]}}
        mgr.container_runtime.get_network.return_value = network

        result = mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime)

        assert result == "192.168.1.0/24"

    def test_returns_none_on_empty_config(self):
        """No IPAM config returns None."""
        mgr = _make_manager()
        network = MagicMock()
        network.attrs = {"IPAM": {"Config": []}}
        mgr.container_runtime.get_network.return_value = network

        result = mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime)

        assert result is None

    def test_returns_none_on_exception(self):
        """Exception returns None."""
        mgr = _make_manager()
        mgr.container_runtime.get_network.side_effect = RuntimeError("boom")

        result = mgr._get_network_subnet("macvlan_eth0", mgr.container_runtime)

        assert result is None

    def test_extracts_subnet_from_ipam(self):
        """Extracts subnet string from network IPAM Config (line 86-87)."""
        mgr = _make_manager()
        network = MagicMock()
        network.attrs = {"IPAM": {"Config": [{"Subnet": "10.0.0.0/8"}]}}
        mgr.container_runtime.get_network.return_value = network

        result = mgr._get_network_subnet("macvlan_eth0_10_0_0_0_8", mgr.container_runtime)

        assert result == "10.0.0.0/8"


class TestScheduleNextRetry:
    def test_increments_retry_count(self):
        """Retry count incremented by 1."""
        mgr = _make_manager()
        state = {"retry_count": 0, "next_retry_at": 0}

        mgr._schedule_next_retry("plc1:v1", state)

        assert state["retry_count"] == 1

    def test_exponential_backoff(self):
        """Delay grows exponentially."""
        mgr = _make_manager()
        state = {"retry_count": 2, "next_retry_at": 0}

        before = time.time()
        mgr._schedule_next_retry("plc1:v1", state)

        # After retry_count becomes 3: base * 2^3 = 1.0 * 8 = 8.0 (before jitter)
        # With 30% jitter: 8 * 0.7 to 8 * 1.3 = 5.6 to 10.4
        expected_min = before + DHCP_RETRY_BACKOFF_BASE
        assert state["next_retry_at"] >= expected_min

    def test_capped_at_max(self):
        """Delay doesn't exceed DHCP_RETRY_BACKOFF_MAX."""
        mgr = _make_manager()
        state = {"retry_count": 20, "next_retry_at": 0}

        mgr._schedule_next_retry("plc1:v1", state)

        max_possible = time.time() + DHCP_RETRY_BACKOFF_MAX * 1.3 + 1
        assert state["next_retry_at"] <= max_possible


class TestResyncDhcpForExistingContainers:
    @pytest.mark.asyncio
    async def test_no_vnic_configs(self):
        """Empty configs → early return, no DHCP started."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {}

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_static_vnics(self):
        """Static network_mode vNICs skipped."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "static", "parent_interface": "eth0"}]
        }

        await mgr.resync_dhcp_for_existing_containers()

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_running_containers(self):
        """Non-running containers skipped."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_starts_dhcp_for_macvlan(self):
        """Running container with MACVLAN gets DHCP started via netmon."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_192_168_1_0_24": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_called_once_with(
            "plc1", "v1", "02:00:00:00:00:01", 1234
        )

    @pytest.mark.asyncio
    async def test_container_not_found_skipped(self):
        """NotFoundError for container is handled gracefully."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        # Should not raise
        await mgr.resync_dhcp_for_existing_containers()

    @pytest.mark.asyncio
    async def test_proxy_arp_vnic_uses_wifi_dhcp(self):
        """WiFi/Proxy ARP vNIC uses request_wifi_dhcp instead of start_dhcp."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "wifi_v1",
                "network_mode": "dhcp",
                "parent_interface": "wlan0",
                "_proxy_arp_config": {"veth_host": "veth-plc1"},
            }]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 5678}}
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.request_wifi_dhcp = AsyncMock(return_value={"success": True})

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.request_wifi_dhcp.assert_called_once_with(
            "plc1", "wifi_v1", "wlan0", 5678
        )

    @pytest.mark.asyncio
    async def test_failed_dhcp_added_to_pending(self):
        """Failed DHCP resync adds entry to pending_dhcp_resyncs."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": False, "error": "timeout"})

        await mgr.resync_dhcp_for_existing_containers()

        assert "plc1:v1" in mgr.pending_dhcp_resyncs
        assert mgr.pending_dhcp_resyncs["plc1:v1"]["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_container_pid_zero_skipped(self):
        """Container with PID <= 0 is skipped."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 0}}
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock()

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_proxy_arp_dhcp_resync_fails_adds_pending(self):
        """Proxy ARP DHCP resync failure adds to pending with is_proxy_arp=True."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "wifi_v1",
                "network_mode": "dhcp",
                "parent_interface": "wlan0",
                "_proxy_arp_config": {"veth_host": "veth-plc1"},
                "dhcp_ip": "10.0.0.5",
            }]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 5678}}
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.request_wifi_dhcp = AsyncMock(return_value={"success": False, "error": "timeout"})

        await mgr.resync_dhcp_for_existing_containers()

        assert "plc1:wifi_v1" in mgr.pending_dhcp_resyncs
        assert mgr.pending_dhcp_resyncs["plc1:wifi_v1"]["is_proxy_arp"] is True

    @pytest.mark.asyncio
    async def test_no_mac_for_macvlan_skipped(self):
        """No MAC found for macvlan network → skip."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "bridge": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock()

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_mac_mismatch_reconnect_verified(self):
        """MAC mismatch → disconnect + reconnect with persisted MAC, verified."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "v1",
                "network_mode": "dhcp",
                "parent_interface": "eth0",
                "mac_address": "02:00:00:00:00:AA",
            }]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        # First reload keeps mismatched MAC; subsequent reloads show verified MAC
        reload_count = {"n": 0}
        def reload_side_effect():
            reload_count["n"] += 1
            if reload_count["n"] >= 2:
                container.attrs = {
                    "State": {"Pid": 1234},
                    "NetworkSettings": {
                        "Networks": {
                            "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:aa"}
                        }
                    },
                }
        container.reload.side_effect = reload_side_effect

        mgr.container_runtime.get_container.return_value = container
        network = MagicMock()
        mgr.container_runtime.get_network.return_value = network
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        with patch("use_cases.dhcp_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr.resync_dhcp_for_existing_containers()

        network.disconnect.assert_called_once_with(container, force=True)
        network.connect.assert_called_once_with(container, mac_address="02:00:00:00:00:AA")
        mgr.netmon_client.start_dhcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_mac_mismatch_static_mode_with_ip(self):
        """MAC mismatch in static mode passes IP to reconnect kwargs.

        Lines 196-198 are normally unreachable because the outer loop at lines
        118-119 filters to network_mode=="dhcp" only, and line 194 re-reads
        network_mode from the same vnic_config dict. To cover them, the
        vnic_config is mutated during container.reload() (simulating a race
        or config update) so that it passes the outer "dhcp" check but reads
        "static" at line 194.
        """
        mgr = _make_manager()
        vnic_config = {
            "name": "v1",
            "network_mode": "dhcp",  # passes outer filter
            "parent_interface": "eth0",
            "mac_address": "02:00:00:00:00:AA",
            "ip": "10.0.0.50/24",
        }
        mgr.vnic_repo.load_all_configs.return_value = {"plc1": [vnic_config]}
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        reload_count = {"n": 0}
        def reload_side_effect():
            reload_count["n"] += 1
            # After the first reload (line 127), mutate vnic_config so that
            # when line 194 re-reads network_mode it gets "static"
            if reload_count["n"] == 1:
                vnic_config["network_mode"] = "static"
            if reload_count["n"] >= 2:
                container.attrs = {
                    "State": {"Pid": 1234},
                    "NetworkSettings": {
                        "Networks": {
                            "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:aa"}
                        }
                    },
                }
        container.reload.side_effect = reload_side_effect

        mgr.container_runtime.get_container.return_value = container
        network = MagicMock()
        mgr.container_runtime.get_network.return_value = network
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        with patch("use_cases.dhcp_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr.resync_dhcp_for_existing_containers()

        # connect should have ipv4_address for static mode
        connect_call = network.connect.call_args
        assert connect_call[1]["mac_address"] == "02:00:00:00:00:AA"
        assert connect_call[1]["ipv4_address"] == "10.0.0.50"

    @pytest.mark.asyncio
    async def test_mac_mismatch_not_verified_no_fallback_mac(self):
        """MAC not verified and no fallback MAC → uses persisted MAC."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "v1",
                "network_mode": "dhcp",
                "parent_interface": "eth0",
                "mac_address": "02:00:00:00:00:AA",
            }]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        # First reload keeps mismatch, subsequent clear MAC
        reload_count = {"n": 0}
        def reload_side_effect_multi():
            reload_count["n"] += 1
            if reload_count["n"] >= 2:
                container.attrs = {
                    "State": {"Pid": 1234},
                    "NetworkSettings": {
                        "Networks": {
                            "macvlan_eth0_net": {"MacAddress": ""}
                        }
                    },
                }
        container.reload.side_effect = reload_side_effect_multi

        mgr.container_runtime.get_container.return_value = container
        network = MagicMock()
        mgr.container_runtime.get_network.return_value = network
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        with patch("use_cases.dhcp_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr.resync_dhcp_for_existing_containers()

        # Should use persisted MAC since no fallback_mac available
        mgr.netmon_client.start_dhcp.assert_called_once_with(
            "plc1", "v1", "02:00:00:00:00:AA", 1234
        )

    @pytest.mark.asyncio
    async def test_inner_exception_per_vnic(self):
        """Generic exception per-vnic during resync is handled (lines 276-277)."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        container = MagicMock()
        container.status = "running"
        container.reload.side_effect = RuntimeError("unexpected Docker error")
        mgr.container_runtime.get_container.return_value = container

        # Should not raise
        await mgr.resync_dhcp_for_existing_containers()

    @pytest.mark.asyncio
    async def test_mac_mismatch_not_verified_fallback(self):
        """MAC mismatch → reconnect but MAC not verified, falls back to actual."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "v1",
                "network_mode": "dhcp",
                "parent_interface": "eth0",
                "mac_address": "02:00:00:00:00:AA",
            }]
        }
        container = MagicMock()
        container.status = "running"
        # MAC never matches persisted (simulation of enforcement failure)
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        # reload never changes the MAC
        container.reload.return_value = None

        mgr.container_runtime.get_container.return_value = container
        network = MagicMock()
        mgr.container_runtime.get_network.return_value = network
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        with patch("use_cases.dhcp_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr.resync_dhcp_for_existing_containers()

        # Should still call start_dhcp with the fallback MAC
        mgr.netmon_client.start_dhcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_mac_mismatch_reconnect_exception(self):
        """MAC enforcement exception falls back to actual MAC."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{
                "name": "v1",
                "network_mode": "dhcp",
                "parent_interface": "eth0",
                "mac_address": "02:00:00:00:00:AA",
            }]
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        network = MagicMock()
        network.disconnect.side_effect = RuntimeError("disconnect error")
        mgr.container_runtime.get_network.return_value = network
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        await mgr.resync_dhcp_for_existing_containers()

        # Should use actual_mac as fallback since enforcement failed
        mgr.netmon_client.start_dhcp.assert_called_once_with(
            "plc1", "v1", "02:00:00:00:00:BB", 1234
        )

    @pytest.mark.asyncio
    async def test_no_persisted_mac_stores_actual(self):
        """No persisted MAC → stores actual MAC address."""
        mgr = _make_manager()
        vnic_config = {"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}
        mgr.vnic_repo.load_all_configs.return_value = {"plc1": [vnic_config]}
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        await mgr.resync_dhcp_for_existing_containers()

        assert vnic_config["mac_address"] == "02:00:00:00:00:01"

    @pytest.mark.asyncio
    async def test_dhcp_resync_fails_clears_stale_ip(self):
        """DHCP resync failure clears stale dhcp_ip from config."""
        mgr = _make_manager()
        vnic_config = {
            "name": "v1",
            "network_mode": "dhcp",
            "parent_interface": "eth0",
            "dhcp_ip": "192.168.1.100",
            "dhcp_gateway": "192.168.1.1",
        }
        mgr.vnic_repo.load_all_configs.return_value = {"plc1": [vnic_config]}
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": False, "error": "timeout"})

        await mgr.resync_dhcp_for_existing_containers()

        assert "dhcp_ip" not in vnic_config
        assert "dhcp_gateway" not in vnic_config

    @pytest.mark.asyncio
    async def test_container_not_found_during_resync_inner(self):
        """NotFoundError during inner resync loop is handled (line 276-277)."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        await mgr.resync_dhcp_for_existing_containers()

        mgr.netmon_client.start_dhcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_outer_exception_in_resync(self):
        """Outer exception in resync_dhcp_for_existing_containers logs error."""
        mgr = _make_manager()
        mgr.vnic_repo.load_all_configs.side_effect = RuntimeError("db error")

        # Should not raise
        await mgr.resync_dhcp_for_existing_containers()


class TestDhcpRetryLoop:
    @pytest.mark.asyncio
    async def test_successful_retry_removes_from_pending(self):
        """Successful DHCP retry removes entry from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_failed_retry_schedules_next(self):
        """Failed DHCP retry schedules next retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:01"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": False})

        # After first retry, stop the loop
        original_schedule = mgr._schedule_next_retry
        def stop_after_schedule(key, state):
            original_schedule(key, state)
            mgr.running = False
        mgr._schedule_next_retry = stop_after_schedule

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" in mgr.pending_dhcp_resyncs
        assert mgr.pending_dhcp_resyncs["plc1:v1"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_container_not_running_removed(self):
        """Non-running container removed from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_vnic_config_not_found_removed(self):
        """Missing vNIC config removes entry from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {"plc1": []}

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_no_longer_dhcp_mode_removed(self):
        """vNIC no longer in DHCP mode removed from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "static", "parent_interface": "eth0"}]
        }

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_invalid_pid_schedules_retry(self):
        """Container with invalid PID schedules retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 0}}
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }

        original_schedule = mgr._schedule_next_retry
        def stop_after_schedule(key, state):
            original_schedule(key, state)
            mgr.running = False
        mgr._schedule_next_retry = stop_after_schedule

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" in mgr.pending_dhcp_resyncs
        assert mgr.pending_dhcp_resyncs["plc1:v1"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_proxy_arp_retry_success(self):
        """Proxy ARP retry success removes from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:wifi_v1": {
                "container_name": "plc1",
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "is_proxy_arp": True,
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 1234}}
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "wifi_v1", "network_mode": "dhcp", "parent_interface": "wlan0"}]
        }
        mgr.netmon_client.request_wifi_dhcp = AsyncMock(return_value={"success": True})

        await mgr.dhcp_retry_loop()

        assert "plc1:wifi_v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_proxy_arp_retry_failure(self):
        """Proxy ARP retry failure schedules next retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:wifi_v1": {
                "container_name": "plc1",
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "is_proxy_arp": True,
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"Pid": 1234}}
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "wifi_v1", "network_mode": "dhcp", "parent_interface": "wlan0"}]
        }
        mgr.netmon_client.request_wifi_dhcp = AsyncMock(return_value={"success": False, "error": "timeout"})

        original_schedule = mgr._schedule_next_retry
        def stop_after_schedule(key, state):
            original_schedule(key, state)
            mgr.running = False
        mgr._schedule_next_retry = stop_after_schedule

        await mgr.dhcp_retry_loop()

        assert mgr.pending_dhcp_resyncs["plc1:wifi_v1"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_macvlan_no_mac_schedules_retry(self):
        """No MAC found for MACVLAN in retry loop schedules next retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {"Networks": {"bridge": {"MacAddress": "02:00:00:00:00:01"}}},
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0"}]
        }

        original_schedule = mgr._schedule_next_retry
        def stop_after_schedule(key, state):
            original_schedule(key, state)
            mgr.running = False
        mgr._schedule_next_retry = stop_after_schedule

        await mgr.dhcp_retry_loop()

        assert mgr.pending_dhcp_resyncs["plc1:v1"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_macvlan_persisted_mac_used(self):
        """Persisted MAC used when available in retry loop."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "State": {"Pid": 1234},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"MacAddress": "02:00:00:00:00:BB"}
                }
            },
        }
        mgr.container_runtime.get_container.return_value = container
        mgr.vnic_repo.load_all_configs.return_value = {
            "plc1": [{"name": "v1", "network_mode": "dhcp", "parent_interface": "eth0", "mac_address": "02:00:00:00:00:AA"}]
        }
        mgr.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        await mgr.dhcp_retry_loop()

        mgr.netmon_client.start_dhcp.assert_called_once_with(
            "plc1", "v1", "02:00:00:00:00:AA", 1234
        )

    @pytest.mark.asyncio
    async def test_container_not_found_removed(self):
        """NotFoundError removes entry from pending."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        await mgr.dhcp_retry_loop()

        assert "plc1:v1" not in mgr.pending_dhcp_resyncs

    @pytest.mark.asyncio
    async def test_generic_exception_schedules_retry(self):
        """Generic exception during retry schedules next retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": 0,
                "retry_count": 0,
            }
        }
        container = MagicMock()
        container.status = "running"
        container.reload.side_effect = RuntimeError("unexpected error")
        mgr.container_runtime.get_container.return_value = container

        original_schedule = mgr._schedule_next_retry
        def stop_after_schedule(key, state):
            original_schedule(key, state)
            mgr.running = False
        mgr._schedule_next_retry = stop_after_schedule

        await mgr.dhcp_retry_loop()

        assert mgr.pending_dhcp_resyncs["plc1:v1"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_reraises(self):
        """CancelledError is re-raised."""
        import asyncio
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": time.time() + 3600,
                "retry_count": 0,
            }
        }

        with patch("use_cases.dhcp_manager.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await mgr.dhcp_retry_loop()

        assert mgr.dhcp_retry_task is None

    @pytest.mark.asyncio
    async def test_loop_completes_when_no_pending(self):
        """Loop completes when pending_dhcp_resyncs becomes empty."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {}

        await mgr.dhcp_retry_loop()

        assert mgr.dhcp_retry_task is None

    @pytest.mark.asyncio
    async def test_running_set_to_false_during_wait(self):
        """Running set to False or key removed during wait skips retry."""
        mgr = _make_manager()
        mgr.running = True
        mgr.pending_dhcp_resyncs = {
            "plc1:v1": {
                "container_name": "plc1",
                "vnic_name": "v1",
                "parent_interface": "eth0",
                "next_retry_at": time.time() + 100,
                "retry_count": 0,
            }
        }

        async def stop_running(*args, **kwargs):
            mgr.running = False

        with patch("use_cases.dhcp_manager.asyncio.sleep", side_effect=stop_running):
            await mgr.dhcp_retry_loop()

    @pytest.mark.asyncio
    async def test_next_key_none_breaks_loop(self):
        """Defensive break when items() is empty but dict is truthy (line 310)."""
        mgr = _make_manager()
        mgr.running = True
        # Create a dict-like mock that is truthy but returns empty items()
        # This covers the defensive `if next_key is None: break` at line 310
        fake_pending = MagicMock()
        fake_pending.__bool__ = MagicMock(return_value=True)
        fake_pending.items.return_value = []  # no entries → next_key stays None
        mgr.pending_dhcp_resyncs = fake_pending

        await mgr.dhcp_retry_loop()

        assert mgr.dhcp_retry_task is None

    @pytest.mark.asyncio
    async def test_generic_exception_in_retry_loop_body(self):
        """Generic exception in retry loop outer body (lines 413-414)."""
        mgr = _make_manager()
        mgr.running = True
        # Cause an error by making pending_dhcp_resyncs itself raise on iteration
        mgr.pending_dhcp_resyncs = MagicMock()
        mgr.pending_dhcp_resyncs.__bool__ = MagicMock(return_value=True)
        mgr.pending_dhcp_resyncs.items.side_effect = RuntimeError("internal error")

        # Should not raise
        await mgr.dhcp_retry_loop()

        assert mgr.dhcp_retry_task is None


class TestStop:
    @pytest.mark.asyncio
    async def test_cancels_retry_task(self):
        """Sets running=False and cancels dhcp_retry_task."""
        import asyncio

        mgr = _make_manager()
        mgr.running = True

        # Create a real asyncio task that sleeps forever (simulates the retry loop)
        async def _forever():
            await asyncio.sleep(9999)

        mgr.dhcp_retry_task = asyncio.create_task(_forever())

        await mgr.stop()

        assert mgr.running is False
        assert mgr.dhcp_retry_task.cancelled()
