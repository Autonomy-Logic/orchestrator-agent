from unittest.mock import MagicMock

from entities import DedicatedNicConfig
from use_cases.network_monitor.get_host_interfaces import (
    should_include_interface,
    build_interface_info_from_cache,
    get_host_interfaces_data,
)


class TestShouldIncludeInterface:
    def test_include_virtual_true(self):
        """include_virtual=True always returns True."""
        assert should_include_interface("docker0", True) is True
        assert should_include_interface("veth123", True) is True
        assert should_include_interface("eth0", True) is True

    def test_filters_docker(self):
        """Docker interface filtered when include_virtual=False."""
        assert should_include_interface("docker0", False) is False

    def test_filters_veth(self):
        """Veth interface filtered when include_virtual=False."""
        assert should_include_interface("veth123abc", False) is False

    def test_allows_eth0(self):
        """Physical ethernet interface passes."""
        assert should_include_interface("eth0", False) is True

    def test_allows_wlan0(self):
        """WiFi interface passes."""
        assert should_include_interface("wlan0", False) is True


class TestBuildInterfaceInfoFromCache:
    def test_basic_info(self):
        """Extracts name, ip, ipv4_addresses."""
        cache_data = {
            "addresses": [{"address": "192.168.1.10"}, {"address": "10.0.0.1"}]
        }

        result = build_interface_info_from_cache("eth0", cache_data, detailed=False)

        assert result["name"] == "eth0"
        assert result["ip_address"] == "192.168.1.10"
        assert result["ipv4_addresses"] == ["192.168.1.10", "10.0.0.1"]
        assert result["mac_address"] is None

    def test_detailed_includes_subnet_gateway(self):
        """detailed=True adds subnet and gateway."""
        cache_data = {
            "addresses": [{"address": "192.168.1.10"}],
            "subnet": "255.255.255.0",
            "gateway": "192.168.1.1",
        }

        result = build_interface_info_from_cache("eth0", cache_data, detailed=True)

        assert result["subnet"] == "255.255.255.0"
        assert result["gateway"] == "192.168.1.1"

    def test_detailed_false_omits_subnet(self):
        """detailed=False omits subnet and gateway."""
        cache_data = {
            "addresses": [{"address": "192.168.1.10"}],
            "subnet": "255.255.255.0",
            "gateway": "192.168.1.1",
        }

        result = build_interface_info_from_cache("eth0", cache_data, detailed=False)

        assert "subnet" not in result
        assert "gateway" not in result

    def test_filters_loopback(self):
        """127.x.x.x addresses excluded."""
        cache_data = {
            "addresses": [{"address": "127.0.0.1"}, {"address": "192.168.1.10"}]
        }

        result = build_interface_info_from_cache("lo", cache_data, detailed=False)

        assert result["ipv4_addresses"] == ["192.168.1.10"]
        assert result["ip_address"] == "192.168.1.10"


class TestGetHostInterfacesData:
    def test_empty_cache_returns_error(self):
        """Empty cache returns error."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {}

        result = get_host_interfaces_data(interface_cache=cache)

        assert result["status"] == "error"
        assert "empty" in result["error"]

    def test_success(self):
        """Returns sorted interfaces list."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth1": {"addresses": [{"address": "10.0.0.1"}]},
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
        }

        result = get_host_interfaces_data(detailed=False, interface_cache=cache)

        assert result["status"] == "success"
        assert len(result["interfaces"]) == 2
        # Sorted by name
        assert result["interfaces"][0]["name"] == "eth0"
        assert result["interfaces"][1]["name"] == "eth1"

    def test_filters_virtual_interfaces(self):
        """Virtual interfaces excluded by default."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            "docker0": {"addresses": [{"address": "172.17.0.1"}]},
            "veth123": {"addresses": [{"address": "172.18.0.1"}]},
        }

        result = get_host_interfaces_data(detailed=False, interface_cache=cache)

        assert result["status"] == "success"
        names = [i["name"] for i in result["interfaces"]]
        assert "eth0" in names
        assert "docker0" not in names
        assert "veth123" not in names

    def test_includes_virtual_when_flag(self):
        """include_virtual=True includes all interfaces."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            "docker0": {"addresses": [{"address": "172.17.0.1"}]},
        }

        result = get_host_interfaces_data(
            include_virtual=True, detailed=False, interface_cache=cache
        )

        assert result["status"] == "success"
        names = [i["name"] for i in result["interfaces"]]
        assert "eth0" in names
        assert "docker0" in names

    def test_interface_no_ipv4_still_included(self):
        """Physical interface without IPv4 is still included (visible in UI)."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "wlan0": {"addresses": [], "type": "wifi"},
        }

        result = get_host_interfaces_data(
            include_virtual=False, detailed=False, interface_cache=cache
        )

        assert result["status"] == "success"
        assert len(result["interfaces"]) == 1
        assert result["interfaces"][0]["name"] == "wlan0"
        assert result["interfaces"][0]["ipv4_addresses"] == []

    def test_ethernet_no_ipv4_included_as_dedicated_only(self):
        """Ethernet interface without IPv4 is included with dedicated_only=True."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            "enp4s0": {"addresses": [], "type": "ethernet"},
        }

        result = get_host_interfaces_data(
            include_virtual=False, detailed=False, interface_cache=cache
        )

        assert result["status"] == "success"
        names = [i["name"] for i in result["interfaces"]]
        assert "enp4s0" in names
        assert "eth0" in names

        enp4s0 = next(i for i in result["interfaces"] if i["name"] == "enp4s0")
        assert enp4s0["dedicated_only"] is True
        assert enp4s0["ip_address"] is None

        eth0 = next(i for i in result["interfaces"] if i["name"] == "eth0")
        assert "dedicated_only" not in eth0

    def test_exception_returns_error(self):
        """Exception in get_host_interfaces_data returns error dict."""
        cache = MagicMock()
        cache.get_all_interfaces.side_effect = RuntimeError("cache broken")

        result = get_host_interfaces_data(interface_cache=cache)

        assert result["status"] == "error"
        assert "Failed to retrieve" in result["error"]

    def test_dedicated_nic_moved_to_container_still_listed(self):
        """A dedicated NIC moved to a container namespace (no longer in cache) still appears."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            # enp4s0 is NOT in cache — it was moved to a container
        }
        nic_repo = MagicMock()
        nic_repo.load_all_configs.return_value = {
            "my_container": DedicatedNicConfig.create("enp4s0"),
        }

        result = get_host_interfaces_data(
            detailed=False, interface_cache=cache, dedicated_nic_repo=nic_repo,
        )

        assert result["status"] == "success"
        names = [i["name"] for i in result["interfaces"]]
        assert "enp4s0" in names
        assert "eth0" in names

        enp4s0 = next(i for i in result["interfaces"] if i["name"] == "enp4s0")
        assert enp4s0["dedicated_to"] == "my_container"
        assert enp4s0["ip_address"] is None
        assert enp4s0["ipv4_addresses"] == []

    def test_dedicated_nic_in_cache_gets_dedicated_to_field(self):
        """A dedicated NIC still in cache (not yet moved) gets the dedicated_to field."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            "enp4s0": {"addresses": [{"address": "10.0.0.5"}]},
        }
        nic_repo = MagicMock()
        nic_repo.load_all_configs.return_value = {
            "my_container": DedicatedNicConfig.create("enp4s0"),
        }

        result = get_host_interfaces_data(
            detailed=False, interface_cache=cache, dedicated_nic_repo=nic_repo,
        )

        assert result["status"] == "success"
        enp4s0 = next(i for i in result["interfaces"] if i["name"] == "enp4s0")
        assert enp4s0["dedicated_to"] == "my_container"
        assert enp4s0["ip_address"] == "10.0.0.5"

    def test_dedicated_nic_repo_exception_handled(self):
        """Exception loading dedicated NIC configs is handled gracefully."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
        }
        nic_repo = MagicMock()
        nic_repo.load_all_configs.side_effect = RuntimeError("disk error")

        result = get_host_interfaces_data(
            detailed=False, interface_cache=cache, dedicated_nic_repo=nic_repo,
        )

        assert result["status"] == "success"
        assert len(result["interfaces"]) == 1
        assert result["interfaces"][0]["name"] == "eth0"

    def test_dedicated_nic_not_duplicated_if_in_cache(self):
        """A dedicated NIC that is still in cache should not appear twice."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "enp4s0": {"addresses": [{"address": "10.0.0.5"}]},
        }
        nic_repo = MagicMock()
        nic_repo.load_all_configs.return_value = {
            "my_container": DedicatedNicConfig.create("enp4s0"),
        }

        result = get_host_interfaces_data(
            detailed=False, interface_cache=cache, dedicated_nic_repo=nic_repo,
        )

        assert result["status"] == "success"
        enp4s0_entries = [i for i in result["interfaces"] if i["name"] == "enp4s0"]
        assert len(enp4s0_entries) == 1
