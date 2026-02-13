import time
from unittest.mock import patch

from tools.usage_buffer import BaseUsageBuffer, UsageBuffer


class TestBaseUsageBuffer:
    def test_add_and_get_samples(self):
        buf = BaseUsageBuffer()
        now = int(time.time())
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = now
            buf.add_sample(50.5, 1024.7)

        samples = buf.get_samples(start_time=now - 1, end_time=now + 1)
        assert len(samples) == 1
        assert samples[0]["cpu"] == 50
        assert samples[0]["memory"] == 1024
        assert samples[0]["timestamp"] == now

    def test_values_truncated_to_int(self):
        buf = BaseUsageBuffer()
        now = int(time.time())
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = now
            buf.add_sample(99.9, 2048.8)

        samples = buf.get_samples(start_time=now - 1, end_time=now + 1)
        assert samples[0]["cpu"] == 99
        assert samples[0]["memory"] == 2048

    def test_max_samples_evicts_oldest(self):
        buf = BaseUsageBuffer()
        # Override maxlen to a small number for testing
        from collections import deque
        buf._buffer = deque(maxlen=3)

        base_time = 1000000
        with patch("tools.usage_buffer.time") as mock_time:
            for i in range(5):
                mock_time.time.return_value = base_time + i
                buf.add_sample(float(i), float(i * 10))

        assert buf.get_buffer_size() == 3
        samples = buf.get_samples(start_time=0, end_time=base_time + 10)
        # Only the last 3 samples should remain
        assert samples[0]["cpu"] == 2
        assert samples[1]["cpu"] == 3
        assert samples[2]["cpu"] == 4

    def test_get_samples_with_time_range(self):
        buf = BaseUsageBuffer()
        with patch("tools.usage_buffer.time") as mock_time:
            for i in range(5):
                mock_time.time.return_value = 1000 + i
                buf.add_sample(float(i), float(i))

        samples = buf.get_samples(start_time=1002, end_time=1003)
        assert len(samples) == 2
        assert samples[0]["cpu"] == 2
        assert samples[1]["cpu"] == 3

    def test_get_samples_no_start_time(self):
        buf = BaseUsageBuffer()
        with patch("tools.usage_buffer.time") as mock_time:
            for i in range(3):
                mock_time.time.return_value = 1000 + i
                buf.add_sample(float(i), float(i))
            mock_time.time.return_value = 1005

        samples = buf.get_samples()
        assert len(samples) == 3

    def test_get_cpu_usage(self):
        buf = BaseUsageBuffer()
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample(75.0, 512.0)

        cpu_samples = buf.get_cpu_usage(start_time=999, end_time=1001)
        assert len(cpu_samples) == 1
        assert cpu_samples[0] == {"timestamp": 1000, "cpu": 75}
        assert "memory" not in cpu_samples[0]

    def test_get_memory_usage(self):
        buf = BaseUsageBuffer()
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample(75.0, 512.0)

        mem_samples = buf.get_memory_usage(start_time=999, end_time=1001)
        assert len(mem_samples) == 1
        assert mem_samples[0] == {"timestamp": 1000, "memory": 512}
        assert "cpu" not in mem_samples[0]

    def test_buffer_size(self):
        buf = BaseUsageBuffer()
        assert buf.get_buffer_size() == 0
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample(1.0, 1.0)
        assert buf.get_buffer_size() == 1

    def test_clear(self):
        buf = BaseUsageBuffer()
        with patch("tools.usage_buffer.time") as mock_time:
            mock_time.time.return_value = 1000
            buf.add_sample(1.0, 1.0)
        buf.clear()
        assert buf.get_buffer_size() == 0


class TestUsageBuffer:
    def test_inherits_base(self):
        buf = UsageBuffer()
        assert isinstance(buf, BaseUsageBuffer)
