from unittest.mock import patch, MagicMock

from tools.network_utils import (
    is_cidr_format,
    netmask_to_cidr,
    calculate_network_base,
    resolve_subnet,
    detect_interface_network,
    get_macvlan_network_key,
)


class TestIsCidrFormat:
    def test_true(self):
        assert is_cidr_format("192.168.1.0/24") is True

    def test_false(self):
        assert is_cidr_format("255.255.255.0") is False

    def test_slash_only(self):
        assert is_cidr_format("/") is True


class TestNetmaskToCidr:
    def test_24(self):
        assert netmask_to_cidr("255.255.255.0") == 24

    def test_16(self):
        assert netmask_to_cidr("255.255.0.0") == 16

    def test_8(self):
        assert netmask_to_cidr("255.0.0.0") == 8

    def test_32(self):
        assert netmask_to_cidr("255.255.255.255") == 32

    def test_20(self):
        assert netmask_to_cidr("255.255.240.0") == 20


class TestCalculateNetworkBase:
    def test_slash24(self):
        assert calculate_network_base("192.168.1.1", "255.255.255.0") == "192.168.1.0"

    def test_slash16(self):
        assert calculate_network_base("172.16.5.1", "255.255.0.0") == "172.16.0.0"

    def test_slash8(self):
        assert calculate_network_base("10.1.2.3", "255.0.0.0") == "10.0.0.0"

    def test_slash20(self):
        assert calculate_network_base("192.168.17.1", "255.255.240.0") == "192.168.16.0"


class TestResolveSubnet:
    def test_already_cidr(self):
        assert resolve_subnet("192.168.1.0/24", "192.168.1.1") == "192.168.1.0/24"

    def test_from_netmask(self):
        result = resolve_subnet("255.255.255.0", "192.168.1.1")
        assert result == "192.168.1.0/24"

    def test_from_netmask_16(self):
        result = resolve_subnet("255.255.0.0", "172.16.5.1")
        assert result == "172.16.0.0/16"


class TestGetMacvlanNetworkKey:
    def test_explicit_cidr(self):
        key = get_macvlan_network_key("eth0", "192.168.1.0/24", "192.168.1.1")
        assert key == "macvlan_eth0_192.168.1.0_24"

    def test_explicit_netmask(self):
        key = get_macvlan_network_key("eth0", "255.255.255.0", "192.168.1.1")
        assert key == "macvlan_eth0_192.168.1.0_24"

    def test_no_cache_returns_unknown(self):
        key = get_macvlan_network_key("eth0")
        assert key == "macvlan_eth0_unknown"

    def test_no_subnet_no_cache_returns_unknown(self):
        key = get_macvlan_network_key("wlan0", parent_subnet=None, parent_gateway=None)
        assert key == "macvlan_wlan0_unknown"

    @patch("tools.network_utils.detect_interface_network", return_value=(None, None))
    def test_cache_returns_none_gives_unknown(self, mock_detect):
        """interface_cache returns (None, None) -> unknown key (line 144-146)."""
        mock_cache = MagicMock()

        key = get_macvlan_network_key(
            "eth0", parent_subnet=None, parent_gateway=None,
            interface_cache=mock_cache,
        )

        assert key == "macvlan_eth0_unknown"
        mock_detect.assert_called_once_with("eth0", mock_cache)

    @patch("tools.network_utils.detect_interface_network", return_value=("192.168.1.0/24", "192.168.1.1"))
    def test_cache_returns_subnet(self, mock_detect):
        """interface_cache returns a subnet -> correct key."""
        mock_cache = MagicMock()

        key = get_macvlan_network_key(
            "eth0", parent_subnet=None, parent_gateway=None,
            interface_cache=mock_cache,
        )

        assert key == "macvlan_eth0_192.168.1.0_24"


class TestDetectInterfaceNetwork:
    def test_found_on_first_try(self):
        """Cache returns subnet on first call -> (subnet, gateway)."""
        mock_cache = MagicMock()
        mock_cache.get_interface_network.return_value = ("10.0.0.0/24", "10.0.0.1")

        with patch("tools.network_utils.time") as mock_time:
            # start_time = time.time() -> 0
            # while time.time() - start_time < 3 -> 0 - 0 = 0 < 3 -> True
            # subnet found -> return
            mock_time.time.side_effect = [0, 0]
            mock_time.sleep = MagicMock()

            subnet, gateway = detect_interface_network("eth0", mock_cache)

        assert subnet == "10.0.0.0/24"
        assert gateway == "10.0.0.1"

    def test_not_found_after_timeout(self):
        """Cache always returns (None, None) -> (None, None) after timeout."""
        mock_cache = MagicMock()
        mock_cache.get_interface_network.return_value = (None, None)

        call_count = [0]
        def fake_time():
            call_count[0] += 1
            # First call: start_time=0; then alternate between in-range and past-max
            if call_count[0] == 1:
                return 0     # start_time
            elif call_count[0] == 2:
                return 0     # while check (0 < 3 -> enter)
            elif call_count[0] == 3:
                return 0     # inner if check (0 < 3 -> sleep)
            elif call_count[0] == 4:
                return 4     # while check (4 >= 3 -> exit)
            return 10

        with patch("tools.network_utils.time") as mock_time:
            mock_time.time = fake_time
            mock_time.sleep = MagicMock()

            subnet, gateway = detect_interface_network("eth0", mock_cache)

        assert subnet is None
        assert gateway is None

    def test_found_on_retry(self):
        """Cache returns None first, then returns subnet -> (subnet, gateway)."""
        mock_cache = MagicMock()
        mock_cache.get_interface_network.side_effect = [
            (None, None),
            ("192.168.0.0/16", "192.168.0.1"),
        ]

        call_count = [0]
        def fake_time():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0     # start_time
            elif call_count[0] == 2:
                return 0     # while check -> enter loop
            elif call_count[0] == 3:
                return 0     # inner if check -> sleep
            elif call_count[0] == 4:
                return 1     # while check -> enter loop again
            return 10

        with patch("tools.network_utils.time") as mock_time:
            mock_time.time = fake_time
            mock_time.sleep = MagicMock()

            subnet, gateway = detect_interface_network("eth0", mock_cache)

        assert subnet == "192.168.0.0/16"
        assert gateway == "192.168.0.1"
