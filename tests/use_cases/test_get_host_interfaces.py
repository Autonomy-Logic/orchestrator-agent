from unittest.mock import MagicMock

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

    def test_interface_no_ipv4_skipped(self):
        """Interface with no IPv4 addresses and include_virtual=False is skipped."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": []},
        }

        result = get_host_interfaces_data(
            include_virtual=False, detailed=False, interface_cache=cache
        )

        assert result["status"] == "success"
        assert len(result["interfaces"]) == 0

    def test_exception_returns_error(self):
        """Exception in get_host_interfaces_data returns error dict."""
        cache = MagicMock()
        cache.get_all_interfaces.side_effect = RuntimeError("cache broken")

        result = get_host_interfaces_data(interface_cache=cache)

        assert result["status"] == "error"
        assert "Failed to retrieve" in result["error"]
