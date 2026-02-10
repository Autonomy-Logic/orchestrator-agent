import pytest
from unittest.mock import MagicMock

from use_cases.docker_manager.get_device_status import (
    get_serial_port_status,
    get_device_info,
    get_device_status_data,
)


class _NotFoundError(Exception):
    pass


def _make_runtime():
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


class TestGetSerialPortStatus:
    def test_returns_port_list(self):
        """Formats ports with name, device_id, container_path, status."""
        serial_repo = MagicMock()
        serial_repo.load_configs.return_value = {
            "serial_ports": [
                {
                    "name": "modbus_rtu",
                    "device_id": "usb-FTDI_FT232R",
                    "container_path": "/dev/modbus0",
                    "status": "connected",
                }
            ]
        }

        result = get_serial_port_status("plc1", serial_repo=serial_repo)

        assert len(result) == 1
        assert result[0]["name"] == "modbus_rtu"
        assert result[0]["device_id"] == "usb-FTDI_FT232R"
        assert result[0]["container_path"] == "/dev/modbus0"
        assert result[0]["status"] == "connected"

    def test_includes_host_path_when_connected(self):
        """current_host_path included only when set."""
        serial_repo = MagicMock()
        serial_repo.load_configs.return_value = {
            "serial_ports": [
                {
                    "name": "modbus",
                    "device_id": "usb-FTDI",
                    "container_path": "/dev/modbus0",
                    "status": "connected",
                    "current_host_path": "/dev/ttyUSB0",
                }
            ]
        }

        result = get_serial_port_status("plc1", serial_repo=serial_repo)
        assert result[0]["current_host_path"] == "/dev/ttyUSB0"

    def test_empty_serial_ports(self):
        """No serial ports returns empty list."""
        serial_repo = MagicMock()
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = get_serial_port_status("plc1", serial_repo=serial_repo)
        assert result == []


class TestGetDeviceInfo:
    def test_nano_cpus(self):
        """NanoCpus set → formatted as vCPU string."""
        runtime = _make_runtime()
        container = MagicMock()
        container.attrs = {
            "HostConfig": {"NanoCpus": 2_000_000_000, "Memory": 536870912}
        }
        runtime.get_container.return_value = container

        result = get_device_info("plc1", container_runtime=runtime)

        assert result["cpu_count"] == "2.0 vCPU"
        assert result["memory_limit"] == "512 MB"

    def test_cpu_quota_period(self):
        """CpuQuota/CpuPeriod → formatted as vCPU string."""
        runtime = _make_runtime()
        container = MagicMock()
        container.attrs = {
            "HostConfig": {
                "NanoCpus": 0,
                "CpuQuota": 150000,
                "CpuPeriod": 100000,
                "Memory": 0,
            }
        }
        runtime.get_container.return_value = container

        result = get_device_info("plc1", container_runtime=runtime)

        assert result["cpu_count"] == "1.5 vCPU"
        assert result["memory_limit"] == "unlimited"

    def test_unlimited_resources(self):
        """No resource limits → 'unlimited'."""
        runtime = _make_runtime()
        container = MagicMock()
        container.attrs = {
            "HostConfig": {"NanoCpus": 0, "CpuQuota": 0, "CpuPeriod": 100000, "Memory": 0}
        }
        runtime.get_container.return_value = container

        result = get_device_info("plc1", container_runtime=runtime)

        assert result["cpu_count"] == "unlimited"
        assert result["memory_limit"] == "unlimited"

    def test_container_not_found(self):
        """NotFoundError → N/A values."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError

        result = get_device_info("plc1", container_runtime=runtime)

        assert result["cpu_count"] == "N/A"
        assert result["memory_limit"] == "N/A"


class TestGetDeviceStatusData:
    def _make_deps(self):
        runtime = _make_runtime()
        registry = MagicMock()
        vnic_repo = MagicMock()
        serial_repo = MagicMock()
        ops = MagicMock()
        return runtime, registry, vnic_repo, serial_repo, ops

    def _call(self, device_id, runtime, registry, vnic_repo, serial_repo, ops):
        return get_device_status_data(
            device_id,
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            operations_state=ops,
        )

    def test_empty_device_id(self):
        """Empty device_id returns error."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()

        result = self._call("", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "error"
        assert "non-empty" in result["error"]

    def test_operation_in_progress_creating(self):
        """Creating operation state returns status with message."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = {
            "status": "creating",
            "operation": "create",
            "step": "pulling_image",
            "error": None,
            "started_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:01",
        }

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "creating"
        assert result["step"] == "pulling_image"
        assert "being created" in result["message"]

    def test_operation_with_error(self):
        """Error state includes error and message."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = {
            "status": "error",
            "operation": "create",
            "step": "creating_container",
            "error": "Image not found",
            "started_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:01",
        }

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "error"
        assert result["error"] == "Image not found"
        assert "Operation failed" in result["message"]

    def test_container_not_found(self):
        """NotFoundError → status='not_found'."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None
        runtime.get_container.side_effect = _NotFoundError

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "not_found"
        assert result["device_id"] == "plc1"

    def test_running_container(self):
        """Running container returns status, is_running, networks, restart_count."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {
                "Status": "running",
                "Running": True,
                "StartedAt": "2024-01-01T00:00:00",
                "RestartCount": 2,
            },
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_192_168_1_0_24": {
                        "IPAddress": "192.168.1.100",
                        "MacAddress": "02:42:ac:11:00:02",
                        "Gateway": "192.168.1.1",
                    }
                }
            },
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = {"ip": "172.18.0.2"}
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "success"
        assert result["is_running"] is True
        assert result["restart_count"] == 2
        assert "macvlan_eth0_192_168_1_0_24" in result["networks"]
        assert result["internal_ip"] == "172.18.0.2"

    def test_skips_internal_networks(self):
        """Networks ending '_internal' excluded."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {
                        "IPAddress": "172.18.0.2",
                        "MacAddress": "02:42:ac:12:00:02",
                        "Gateway": "",
                    },
                    "macvlan_eth0": {
                        "IPAddress": "192.168.1.100",
                        "MacAddress": "02:42:ac:11:00:02",
                        "Gateway": "192.168.1.1",
                    },
                }
            },
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert "plc1_internal" not in result["networks"]
        assert "macvlan_eth0" in result["networks"]

    def test_dhcp_ip_override(self):
        """DHCP IP from vnic_config replaces Docker IP."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_192_168_1_0_24": {
                        "IPAddress": "0.0.0.0",
                        "MacAddress": "02:42:ac:11:00:02",
                        "Gateway": "",
                    }
                }
            },
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = [
            {
                "docker_network_name": "macvlan_eth0_192_168_1_0_24",
                "dhcp_ip": "192.168.1.50",
                "dhcp_gateway": "192.168.1.1",
            }
        ]
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        net = result["networks"]["macvlan_eth0_192_168_1_0_24"]
        assert net["ip_address"] == "192.168.1.50"
        assert net["gateway"] == "192.168.1.1"

    def test_wifi_vnic_included(self):
        """WiFi vNICs appear in networks."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {"Networks": {}},
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = [
            {
                "_is_wifi": True,
                "name": "wifi_vnic",
                "parent_interface": "wlan0",
                "network_mode": "static",
                "_proxy_arp_config": {
                    "ip_address": "192.168.1.200",
                    "gateway": "192.168.1.1",
                },
            }
        ]
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert "wifi_wlan0_wifi_vnic" in result["networks"]
        net = result["networks"]["wifi_wlan0_wifi_vnic"]
        assert net["ip_address"] == "192.168.1.200"
        assert net["gateway"] == "192.168.1.1"

    def test_serial_port_exception_returns_empty(self):
        """Exception in get_serial_port_status returns empty list."""
        serial_repo = MagicMock()
        serial_repo.load_configs.side_effect = RuntimeError("db error")

        result = get_serial_port_status("plc1", serial_repo=serial_repo)
        assert result == []

    def test_device_info_generic_exception(self):
        """Generic exception in get_device_info returns N/A values."""
        runtime = _make_runtime()
        container = MagicMock()
        container.attrs = {"HostConfig": {}}
        runtime.get_container.return_value = container
        container.reload.side_effect = RuntimeError("reload failed")

        result = get_device_info("plc1", container_runtime=runtime)

        assert result["cpu_count"] == "N/A"
        assert result["memory_limit"] == "N/A"

    def test_operation_deleting(self):
        """Deleting operation state returns message with 'being deleted'."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = {
            "status": "deleting",
            "operation": "delete",
            "step": "stopping_container",
            "error": None,
            "started_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:01",
        }

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "deleting"
        assert "being deleted" in result["message"]

    def test_uptime_calculation_exception(self):
        """Exception in uptime calculation logs warning."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {
                "Status": "running",
                "Running": True,
                "StartedAt": "invalid-date-format",
                "RestartCount": 0,
            },
            "NetworkSettings": {"Networks": {}},
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "success"
        assert "uptime_seconds" not in result

    def test_dhcp_ip_fallback_by_parent_interface(self):
        """DHCP IP fallback by parent_interface matching when docker_network_name is not set."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_10_0_0_0_24": {
                        "IPAddress": "0.0.0.0",
                        "MacAddress": "02:42:ac:11:00:02",
                        "Gateway": "",
                    }
                }
            },
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = [
            {
                "parent_interface": "eth0",
                "dhcp_ip": "10.0.0.50",
                "dhcp_gateway": "10.0.0.1",
            }
        ]
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        net = result["networks"]["macvlan_eth0_10_0_0_0_24"]
        assert net["ip_address"] == "10.0.0.50"
        assert net["gateway"] == "10.0.0.1"

    def test_dhcp_ip_override_with_gateway(self):
        """DHCP IP override includes gateway when present."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {
                        "IPAddress": "0.0.0.0",
                        "MacAddress": "02:42:ac:11:00:02",
                        "Gateway": "",
                    }
                }
            },
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = [
            {
                "docker_network_name": "macvlan_eth0_net",
                "dhcp_ip": "192.168.1.50",
                "dhcp_gateway": "192.168.1.1",
            }
        ]
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        net = result["networks"]["macvlan_eth0_net"]
        assert net["ip_address"] == "192.168.1.50"
        assert net["gateway"] == "192.168.1.1"

    def test_health_status_included(self):
        """Health status from container state is included."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {
                "Status": "running",
                "Running": True,
                "RestartCount": 0,
                "Health": {"Status": "healthy"},
            },
            "NetworkSettings": {"Networks": {}},
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["health_status"] == "healthy"

    def test_serial_ports_included(self):
        """Serial ports included in response when configured."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running", "Running": True, "RestartCount": 0},
            "NetworkSettings": {"Networks": {}},
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {
            "serial_ports": [
                {
                    "name": "modbus",
                    "device_id": "usb-FTDI",
                    "container_path": "/dev/modbus0",
                    "status": "connected",
                }
            ]
        }

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert "serial_ports" in result
        assert len(result["serial_ports"]) == 1

    def test_generic_exception_returns_error(self):
        """Generic exception returns status='error'."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.side_effect = RuntimeError("unexpected error")

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "error"
        assert "Failed to retrieve" in result["error"]

    def test_stopped_container_exit_code(self):
        """Not running → includes exit_code."""
        runtime, registry, vnic_repo, serial_repo, ops = self._make_deps()
        ops.get_state.return_value = None

        container = MagicMock()
        container.attrs = {
            "State": {
                "Status": "exited",
                "Running": False,
                "ExitCode": 137,
                "RestartCount": 0,
            },
            "NetworkSettings": {"Networks": {}},
        }
        runtime.get_container.return_value = container
        vnic_repo.load_configs.return_value = []
        registry.get_client.return_value = None
        serial_repo.load_configs.return_value = {"serial_ports": []}

        result = self._call("plc1", runtime, registry, vnic_repo, serial_repo, ops)

        assert result["status"] == "success"
        assert result["is_running"] is False
        assert result["exit_code"] == 137
