from unittest.mock import MagicMock, patch

from use_cases.get_consumption_orchestrator import get_consumption_orchestrator_data


class TestGetConsumptionOrchestratorData:
    @patch("use_cases.get_consumption_orchestrator.get_ip_addresses")
    @patch("use_cases.get_consumption_orchestrator.parse_period")
    def test_returns_system_info(self, mock_parse, mock_ips):
        """Returns aggregated dict with ip_addresses, memory, cpu, os, kernel, disk, usage."""
        mock_parse.return_value = (1000, 2000)
        mock_ips.return_value = [{"interface": "eth0", "ip_address": "192.168.1.10"}]

        static_info = {
            "memory": 4096,
            "cpu": 4,
            "os": "Ubuntu 22.04",
            "kernel": "5.15.0",
            "disk": 64,
        }

        usage_buffer = MagicMock()
        usage_buffer.get_cpu_usage.return_value = [{"ts": 1500, "value": 10.0}]
        usage_buffer.get_memory_usage.return_value = [{"ts": 1500, "value": 2048.0}]

        interface_cache = MagicMock()

        result = get_consumption_orchestrator_data(
            static_system_info=static_info,
            usage_buffer=usage_buffer,
            network_interface_cache=interface_cache,
        )

        assert result["ip_addresses"] == [{"interface": "eth0", "ip_address": "192.168.1.10"}]
        assert result["memory"] == 4096
        assert result["cpu"] == 4
        assert result["os"] == "Ubuntu 22.04"
        assert result["kernel"] == "5.15.0"
        assert result["disk"] == 64
        assert result["cpu_usage"] == [{"ts": 1500, "value": 10.0}]
        assert result["memory_usage"] == [{"ts": 1500, "value": 2048.0}]
        mock_ips.assert_called_once_with(interface_cache)
