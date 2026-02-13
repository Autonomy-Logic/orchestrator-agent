from unittest.mock import patch

from tools.devices_usage_buffer import DevicesUsageBuffer


class TestDevicesUsageBuffer:
    def test_add_and_remove_device(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        assert buf.has_device("plc1") is True
        buf.remove_device("plc1")
        assert buf.has_device("plc1") is False

    def test_add_device_idempotent(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        buf.add_device("plc1")  # Should not raise
        assert buf.has_device("plc1") is True

    def test_remove_nonexistent_device(self):
        buf = DevicesUsageBuffer()
        buf.remove_device("nonexistent")  # Should not raise

    def test_add_sample_to_registered_device(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 50.0, 512.0)

        samples = buf.get_samples("plc1", start_time=999, end_time=1001)
        assert len(samples) == 1
        assert samples[0]["cpu"] == 50

    def test_add_sample_to_unregistered_device(self):
        buf = DevicesUsageBuffer()
        # Should log warning but not crash
        buf.add_sample("nonexistent", 50.0, 512.0)

    def test_get_samples_unregistered(self):
        buf = DevicesUsageBuffer()
        assert buf.get_samples("nonexistent") == []

    def test_get_cpu_usage(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 75.0, 512.0)

        cpu = buf.get_cpu_usage("plc1", start_time=999, end_time=1001)
        assert len(cpu) == 1
        assert cpu[0] == {"timestamp": 1000, "cpu": 75}

    def test_get_memory_usage(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 75.0, 512.0)

        mem = buf.get_memory_usage("plc1", start_time=999, end_time=1001)
        assert len(mem) == 1
        assert mem[0] == {"timestamp": 1000, "memory": 512}

    def test_get_cpu_usage_unregistered(self):
        buf = DevicesUsageBuffer()
        assert buf.get_cpu_usage("nonexistent") == []

    def test_get_memory_usage_unregistered(self):
        buf = DevicesUsageBuffer()
        assert buf.get_memory_usage("nonexistent") == []

    def test_has_device(self):
        buf = DevicesUsageBuffer()
        assert buf.has_device("plc1") is False
        buf.add_device("plc1")
        assert buf.has_device("plc1") is True

    def test_get_device_ids(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        buf.add_device("plc2")
        ids = buf.get_device_ids()
        assert set(ids) == {"plc1", "plc2"}

    def test_get_buffer_size(self):
        buf = DevicesUsageBuffer()
        assert buf.get_buffer_size("nonexistent") == 0
        buf.add_device("plc1")
        assert buf.get_buffer_size("plc1") == 0
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 1.0, 1.0)
        assert buf.get_buffer_size("plc1") == 1

    def test_clear_device(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 1.0, 1.0)
        buf.clear_device("plc1")
        assert buf.get_buffer_size("plc1") == 0
        assert buf.has_device("plc1") is True  # Device still registered

    def test_clear_all(self):
        buf = DevicesUsageBuffer()
        buf.add_device("plc1")
        buf.add_device("plc2")
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample("plc1", 1.0, 1.0)
            buf.add_sample("plc2", 2.0, 2.0)
        buf.clear_all()
        assert buf.get_buffer_size("plc1") == 0
        assert buf.get_buffer_size("plc2") == 0
