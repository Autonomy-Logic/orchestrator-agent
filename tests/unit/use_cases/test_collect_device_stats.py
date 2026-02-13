import pytest
from unittest.mock import MagicMock

from use_cases.collect_device_stats import collect_device_stats, collect_all_device_stats


class TestCollectDeviceStats:
    def test_running_container(self):
        """Happy path: CPU delta math returns (cpu_percent, memory_mb)."""
        runtime = MagicMock()
        container = MagicMock()
        container.status = "running"
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 5000},
                "system_cpu_usage": 20000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 3000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 100 * 1024 * 1024},
        }
        runtime.get_container.return_value = container

        cpu, mem = collect_device_stats("plc1", container_runtime=runtime)

        # cpu_delta=2000, system_delta=10000, online_cpus=4 → (2000/10000)*4*100 = 80.0
        assert cpu == pytest.approx(80.0)
        assert mem == pytest.approx(100.0)

    def test_not_running(self):
        """Non-running container returns (None, None)."""
        runtime = MagicMock()
        container = MagicMock()
        container.status = "exited"
        runtime.get_container.return_value = container

        cpu, mem = collect_device_stats("plc1", container_runtime=runtime)
        assert cpu is None
        assert mem is None

    def test_exception_returns_none(self):
        """Exception from container_runtime returns (None, None)."""
        runtime = MagicMock()
        runtime.get_container.side_effect = RuntimeError("boom")

        cpu, mem = collect_device_stats("plc1", container_runtime=runtime)
        assert cpu is None
        assert mem is None

    def test_zero_system_delta(self):
        """system_delta=0 → cpu_percent=0.0."""
        runtime = MagicMock()
        container = MagicMock()
        container.status = "running"
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 5000},
                "system_cpu_usage": 10000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 5000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 50 * 1024 * 1024},
        }
        runtime.get_container.return_value = container

        cpu, mem = collect_device_stats("plc1", container_runtime=runtime)
        assert cpu == 0.0
        assert mem == pytest.approx(50.0)

    def test_online_cpus_none_fallback(self):
        """online_cpus=None falls back to len(percpu_usage)."""
        runtime = MagicMock()
        container = MagicMock()
        container.status = "running"
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 5000, "percpu_usage": [1, 2, 3, 4]},
                "system_cpu_usage": 20000,
                "online_cpus": None,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 3000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 100 * 1024 * 1024},
        }
        runtime.get_container.return_value = container

        cpu, mem = collect_device_stats("plc1", container_runtime=runtime)
        # percpu_usage has 4 entries → num_cpus=4
        # (2000/10000) * 4 * 100 = 80.0
        assert cpu == pytest.approx(80.0)


class TestCollectAllDeviceStats:
    def test_adds_valid_samples(self):
        """Valid stats are added as samples to the buffer."""
        runtime = MagicMock()
        buffer = MagicMock()
        buffer.get_device_ids.return_value = ["plc1", "plc2"]

        container1 = MagicMock()
        container1.status = "running"
        container1.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 5000},
                "system_cpu_usage": 20000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 4000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 50 * 1024 * 1024},
        }

        container2 = MagicMock()
        container2.status = "running"
        container2.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 8000},
                "system_cpu_usage": 20000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 6000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 100 * 1024 * 1024},
        }

        runtime.get_container.side_effect = [container1, container2]

        collect_all_device_stats(buffer, container_runtime=runtime)

        assert buffer.add_sample.call_count == 2

    def test_skips_none_values(self):
        """Devices returning (None, None) are not added to buffer."""
        runtime = MagicMock()
        buffer = MagicMock()
        buffer.get_device_ids.return_value = ["plc1", "plc2"]

        container1 = MagicMock()
        container1.status = "exited"  # Not running → (None, None)

        container2 = MagicMock()
        container2.status = "running"
        container2.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 5000},
                "system_cpu_usage": 20000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 4000},
                "system_cpu_usage": 10000,
            },
            "memory_stats": {"usage": 50 * 1024 * 1024},
        }

        runtime.get_container.side_effect = [container1, container2]

        collect_all_device_stats(buffer, container_runtime=runtime)

        assert buffer.add_sample.call_count == 1
