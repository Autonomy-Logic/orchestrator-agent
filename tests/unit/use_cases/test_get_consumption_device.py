from unittest.mock import MagicMock, patch

from use_cases.get_consumption_device import get_consumption_device_data


class TestGetConsumptionDeviceData:
    def test_device_not_found(self):
        """client_registry.contains=False returns error dict."""
        registry = MagicMock()
        registry.contains.return_value = False
        buffer = MagicMock()
        runtime = MagicMock()

        result = get_consumption_device_data(
            "plc1",
            client_registry=registry,
            devices_usage_buffer=buffer,
            container_runtime=runtime,
        )

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @patch("use_cases.get_consumption_device.get_device_info")
    @patch("use_cases.get_consumption_device.parse_period")
    def test_success(self, mock_parse, mock_info):
        """Returns dict with device_id, memory, cpu, cpu_usage, memory_usage."""
        mock_parse.return_value = (1000, 2000)
        mock_info.return_value = {"memory_limit": "512 MB", "cpu_count": "1.0 vCPU"}

        registry = MagicMock()
        registry.contains.return_value = True
        buffer = MagicMock()
        buffer.get_cpu_usage.return_value = [{"timestamp": 1500, "value": 25.0}]
        buffer.get_memory_usage.return_value = [{"timestamp": 1500, "value": 200.0}]
        runtime = MagicMock()

        result = get_consumption_device_data(
            "plc1",
            client_registry=registry,
            devices_usage_buffer=buffer,
            container_runtime=runtime,
        )

        assert result["device_id"] == "plc1"
        assert result["memory"] == "512 MB"
        assert result["cpu"] == "1.0 vCPU"
        assert result["cpu_usage"] == [{"timestamp": 1500, "value": 25.0}]
        assert result["memory_usage"] == [{"timestamp": 1500, "value": 200.0}]
