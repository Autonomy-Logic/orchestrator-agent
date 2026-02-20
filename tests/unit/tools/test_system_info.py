import sys
from unittest.mock import MagicMock, patch

from tools.system_info import (
    _is_physical_interface,
    get_ip_addresses,
    get_total_memory,
    get_cpu_count,
    get_kernel_version,
    get_os_info,
    get_total_disk,
    get_static_system_info,
)


class TestIsPhysicalInterface:
    def test_eth0(self):
        assert _is_physical_interface("eth0") is True

    def test_wlan0(self):
        assert _is_physical_interface("wlan0") is True

    def test_enp0s3(self):
        assert _is_physical_interface("enp0s3") is True

    def test_docker0(self):
        assert _is_physical_interface("docker0") is False

    def test_veth_prefix(self):
        assert _is_physical_interface("veth123abc") is False

    def test_br_prefix(self):
        assert _is_physical_interface("br-abcdef") is False

    def test_loopback(self):
        assert _is_physical_interface("lo") is False

    def test_tailscale(self):
        assert _is_physical_interface("tailscale0") is False

    def test_wireguard(self):
        assert _is_physical_interface("wg0") is False

    def test_case_insensitive(self):
        assert _is_physical_interface("Docker0") is False


class TestGetIpAddresses:
    def test_returns_physical_ips(self):
        """Returns IPs from physical interfaces only."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "192.168.1.10"}]},
            "docker0": {"addresses": [{"address": "172.17.0.1"}]},
        }

        result = get_ip_addresses(cache)

        assert len(result) == 1
        assert result[0]["interface"] == "eth0"
        assert result[0]["ip_address"] == "192.168.1.10"

    def test_filters_loopback(self):
        """127.x.x.x addresses excluded."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": [{"address": "127.0.0.1"}, {"address": "10.0.0.1"}]},
        }

        result = get_ip_addresses(cache)

        assert len(result) == 1
        assert result[0]["ip_address"] == "10.0.0.1"

    def test_multiple_addresses(self):
        """Multiple IPs on same interface all returned."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {
                "addresses": [
                    {"address": "192.168.1.10"},
                    {"address": "192.168.1.11"},
                ]
            },
        }

        result = get_ip_addresses(cache)

        assert len(result) == 2

    def test_empty_cache(self):
        """Empty cache returns empty list."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {}

        result = get_ip_addresses(cache)

        assert result == []

    def test_no_addresses(self):
        """Interface with no addresses returns nothing."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": []},
        }

        result = get_ip_addresses(cache)

        assert result == []

    def test_non_dict_address_skipped(self):
        """Non-dict entries in addresses list are skipped."""
        cache = MagicMock()
        cache.get_all_interfaces.return_value = {
            "eth0": {"addresses": ["not-a-dict", {"address": "10.0.0.1"}]},
        }

        result = get_ip_addresses(cache)

        assert len(result) == 1
        assert result[0]["ip_address"] == "10.0.0.1"


class TestGetTotalMemory:
    @patch("tools.system_info.psutil")
    def test_returns_mb(self, mock_psutil):
        """Returns total memory in MB."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=4 * 1024 * 1024 * 1024  # 4 GB
        )

        assert get_total_memory() == 4096


class TestGetCpuCount:
    @patch("tools.system_info.psutil")
    def test_returns_count(self, mock_psutil):
        """Returns logical CPU count."""
        mock_psutil.cpu_count.return_value = 8

        assert get_cpu_count() == 8


class TestGetKernelVersion:
    @patch("tools.system_info.platform")
    def test_returns_release(self, mock_platform):
        mock_platform.release.return_value = "5.15.0-generic"

        assert get_kernel_version() == "5.15.0-generic"


class TestGetOsInfo:
    def test_distro_returns_name(self):
        """distro module available and returns non-empty name."""
        mock_distro = MagicMock()
        mock_distro.name.return_value = "Ubuntu 22.04 LTS"

        with patch.dict(sys.modules, {"distro": mock_distro}):
            result = get_os_info()

        assert result == "Ubuntu 22.04 LTS"

    def test_distro_import_error_fallback(self):
        """distro import fails -> fallback to platform."""
        # Remove distro from sys.modules to force ImportError
        original = sys.modules.get("distro")
        sys.modules["distro"] = None  # Causes ImportError on `import distro`
        try:
            with patch("tools.system_info.platform") as mock_platform:
                mock_platform.system.return_value = "Linux"
                mock_platform.release.return_value = "5.15.0"
                result = get_os_info()

            assert result == "Linux 5.15.0"
        finally:
            if original is not None:
                sys.modules["distro"] = original
            else:
                sys.modules.pop("distro", None)

    def test_distro_returns_empty_fallback(self):
        """distro.name() returns empty string -> fallback to platform."""
        mock_distro = MagicMock()
        mock_distro.name.return_value = ""

        with patch.dict(sys.modules, {"distro": mock_distro}):
            with patch("tools.system_info.platform") as mock_platform:
                mock_platform.system.return_value = "Linux"
                mock_platform.release.return_value = "6.1.0"
                result = get_os_info()

        assert result == "Linux 6.1.0"


class TestGetTotalDisk:
    @patch("tools.system_info._iter_disk_usage")
    def test_returns_int_gb(self, mock_iter):
        """get_total_disk returns sum of totals in GB as int."""
        usage1 = MagicMock()
        usage1.total = 100 * (1024 ** 3)  # 100 GB
        usage2 = MagicMock()
        usage2.total = 50 * (1024 ** 3)  # 50 GB
        mock_iter.return_value = [usage1, usage2]

        result = get_total_disk()
        assert result == 150
        assert isinstance(result, int)


class TestGetStaticSystemInfo:
    @patch("tools.system_info.get_total_disk")
    @patch("tools.system_info.get_kernel_version")
    @patch("tools.system_info.get_os_info")
    @patch("tools.system_info.get_cpu_count")
    @patch("tools.system_info.get_total_memory")
    def test_returns_all_fields(self, mock_mem, mock_cpu, mock_os, mock_kernel, mock_disk):
        mock_mem.return_value = 4096
        mock_cpu.return_value = 4
        mock_os.return_value = "Ubuntu 22.04"
        mock_kernel.return_value = "5.15.0"
        mock_disk.return_value = 64

        result = get_static_system_info()

        assert result == {
            "memory": 4096,
            "cpu": 4,
            "os": "Ubuntu 22.04",
            "kernel": "5.15.0",
            "disk": 64,
        }
