import time
from unittest.mock import patch, MagicMock

from tools.system_metrics import (
    get_cpu_usage,
    get_memory_usage,
    get_memory_total,
    get_disk_total,
    get_uptime,
    get_status,
    get_all_metrics,
    _iter_disk_usage,
    _SKIP_FSTYPES,
)


class TestGetCpuUsage:
    @patch("tools.system_metrics.psutil")
    def test_returns_percentage(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 25.5

        assert get_cpu_usage() == 25.5
        mock_psutil.cpu_percent.assert_called_with(interval=None)


class TestGetMemoryUsage:
    @patch("tools.system_metrics.psutil")
    def test_returns_gb(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            used=2 * 1024 * 1024 * 1024  # 2 GB
        )

        assert get_memory_usage() == 2.0


class TestGetMemoryTotal:
    def test_returns_cached_value(self):
        """Returns the module-level cached total."""
        result = get_memory_total()
        assert isinstance(result, float)
        assert result > 0


class TestGetDiskTotal:
    def test_returns_cached_value(self):
        """Returns the module-level cached total."""
        result = get_disk_total()
        assert isinstance(result, float)
        assert result >= 0


class TestGetUptime:
    def test_returns_positive_int(self):
        """Uptime is a positive integer."""
        result = get_uptime()
        assert isinstance(result, int)
        assert result >= 0

    def test_increases_over_time(self):
        """Uptime increases between calls."""
        t1 = get_uptime()
        time.sleep(0.01)
        t2 = get_uptime()
        assert t2 >= t1


class TestGetStatus:
    def test_returns_active(self):
        assert get_status() == "active"


class TestGetAllMetrics:
    @patch("tools.system_metrics.get_cpu_usage", return_value=10.0)
    @patch("tools.system_metrics.get_memory_usage", return_value=2.0)
    @patch("tools.system_metrics.get_memory_total", return_value=8.0)
    @patch("tools.system_metrics.get_disk_usage", return_value=20.0)
    @patch("tools.system_metrics.get_disk_total", return_value=100.0)
    @patch("tools.system_metrics.get_uptime", return_value=3600)
    @patch("tools.system_metrics.get_status", return_value="active")
    def test_returns_all_fields(self, *_mocks):
        result = get_all_metrics()

        assert result == {
            "cpu_usage": 10.0,
            "memory_usage": 2.0,
            "memory_total": 8.0,
            "disk_usage": 20.0,
            "disk_total": 100.0,
            "uptime": 3600,
            "status": "active",
        }

    def test_returns_correct_keys(self):
        """Real call returns all expected keys."""
        result = get_all_metrics()

        expected_keys = {
            "cpu_usage", "memory_usage", "memory_total",
            "disk_usage", "disk_total", "uptime", "status",
        }
        assert set(result.keys()) == expected_keys


class TestIterDiskUsage:
    @patch("tools.system_metrics.psutil")
    def test_skips_tmpfs_partition(self, mock_psutil):
        """Line 26: partitions with fstype in _SKIP_FSTYPES are skipped."""
        tmpfs_partition = MagicMock()
        tmpfs_partition.fstype = "tmpfs"
        tmpfs_partition.device = "/dev/sda1"
        tmpfs_partition.mountpoint = "/tmp"

        real_partition = MagicMock()
        real_partition.fstype = "ext4"
        real_partition.device = "/dev/sdb1"
        real_partition.mountpoint = "/"

        mock_usage = MagicMock(total=100, used=50)
        mock_psutil.disk_partitions.return_value = [tmpfs_partition, real_partition]
        mock_psutil.disk_usage.return_value = mock_usage

        results = list(_iter_disk_usage())

        assert len(results) == 1
        assert results[0] == mock_usage
        # disk_usage should only be called for the real partition
        mock_psutil.disk_usage.assert_called_once_with("/")

    @patch("tools.system_metrics.psutil")
    def test_skips_permission_error(self, mock_psutil):
        """Lines 32-33: PermissionError from disk_usage is caught and skipped."""
        partition = MagicMock()
        partition.fstype = "ext4"
        partition.device = "/dev/sda1"
        partition.mountpoint = "/restricted"

        mock_psutil.disk_partitions.return_value = [partition]
        mock_psutil.disk_usage.side_effect = PermissionError("denied")

        results = list(_iter_disk_usage())

        assert len(results) == 0

    @patch("tools.system_metrics.psutil")
    def test_skips_os_error(self, mock_psutil):
        """Lines 32-33: OSError from disk_usage is caught and skipped."""
        partition = MagicMock()
        partition.fstype = "ext4"
        partition.device = "/dev/sda1"
        partition.mountpoint = "/bad"

        mock_psutil.disk_partitions.return_value = [partition]
        mock_psutil.disk_usage.side_effect = OSError("no such device")

        results = list(_iter_disk_usage())

        assert len(results) == 0


class TestSkipFstypes:
    def test_contains_common_virtual_fstypes(self):
        """Verify common virtual fstypes are in the skip list."""
        assert "tmpfs" in _SKIP_FSTYPES
        assert "overlay" in _SKIP_FSTYPES
        assert "proc" in _SKIP_FSTYPES
        assert "sysfs" in _SKIP_FSTYPES
