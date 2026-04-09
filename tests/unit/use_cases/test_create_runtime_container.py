import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.docker_manager.create_runtime_container import (
    _generate_mac_address,
    _validate_vnic_configs,
    _validate_mac_addresses,
    _create_runtime_container_sync,
    create_runtime_container,
    start_creation,
)


class TestGenerateMacAddress:
    def test_format(self):
        """MAC has 6 colon-separated hex octets."""
        mac = _generate_mac_address()
        parts = mac.split(":")
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 2
            int(part, 16)  # should not raise

    def test_locally_administered(self):
        """First octet bit 1 set (locally administered)."""
        mac = _generate_mac_address()
        first_octet = int(mac.split(":")[0], 16)
        assert first_octet & 0x02 != 0

    def test_unicast(self):
        """First octet bit 0 clear (unicast)."""
        mac = _generate_mac_address()
        first_octet = int(mac.split(":")[0], 16)
        assert first_octet & 0x01 == 0

    def test_uniqueness(self):
        """100 generated MACs are all unique."""
        macs = {_generate_mac_address() for _ in range(100)}
        assert len(macs) == 100


class TestValidateVnicConfigs:
    def test_single_vnic_valid(self):
        """One ethernet vNIC is valid."""
        cache = MagicMock()
        cache.get_interface_type.return_value = "ethernet"

        with patch(
            "use_cases.docker_manager.create_runtime_container.get_macvlan_network_key"
        ) as mock_key:
            mock_key.return_value = "macvlan_eth0_192_168_1_0_24"
            valid, error = _validate_vnic_configs(
                [{"name": "vnic1", "parent_interface": "eth0", "subnet": "255.255.255.0", "gateway": "192.168.1.1"}],
                interface_cache=cache,
            )

        assert valid is True
        assert error == ""

    def test_duplicate_macvlan_network(self):
        """Two vNICs resolving to the same MACVLAN network → invalid."""
        cache = MagicMock()
        cache.get_interface_type.return_value = "ethernet"

        with patch(
            "use_cases.docker_manager.create_runtime_container.get_macvlan_network_key"
        ) as mock_key:
            mock_key.return_value = "macvlan_eth0_192_168_1_0_24"
            valid, error = _validate_vnic_configs(
                [
                    {"name": "vnic1", "parent_interface": "eth0", "subnet": "255.255.255.0", "gateway": "192.168.1.1"},
                    {"name": "vnic2", "parent_interface": "eth0", "subnet": "255.255.255.0", "gateway": "192.168.1.1"},
                ],
                interface_cache=cache,
            )

        assert valid is False
        assert "same MACVLAN network" in error

    def test_wifi_same_interface_warns_but_passes(self):
        """Two WiFi vNICs on same interface → valid (just warns)."""
        cache = MagicMock()
        cache.get_interface_type.return_value = "wifi"

        valid, error = _validate_vnic_configs(
            [
                {"name": "wifi1", "parent_interface": "wlan0"},
                {"name": "wifi2", "parent_interface": "wlan0"},
            ],
            interface_cache=cache,
        )

        assert valid is True
        assert error == ""

    def test_mixed_wifi_ethernet(self):
        """Mixed interface types → valid when no duplicates."""
        cache = MagicMock()
        cache.get_interface_type.side_effect = ["wifi", "ethernet"]

        with patch(
            "use_cases.docker_manager.create_runtime_container.get_macvlan_network_key"
        ) as mock_key:
            mock_key.return_value = "macvlan_eth0_192_168_1_0_24"
            valid, error = _validate_vnic_configs(
                [
                    {"name": "wifi1", "parent_interface": "wlan0"},
                    {"name": "eth1", "parent_interface": "eth0", "subnet": "255.255.255.0", "gateway": "192.168.1.1"},
                ],
                interface_cache=cache,
            )

        assert valid is True
        assert error == ""


class TestValidateMacAddresses:
    def test_no_mac_specified(self):
        """No user MACs → valid."""
        runtime = MagicMock()

        valid, error = _validate_mac_addresses(
            [{"name": "vnic1", "parent_interface": "eth0"}],
            container_runtime=runtime,
        )

        assert valid is True
        assert error == ""
        runtime.get_existing_mac_addresses_on_interface.assert_not_called()

    def test_mac_not_in_use(self):
        """User MAC available → valid."""
        runtime = MagicMock()
        runtime.get_existing_mac_addresses_on_interface.return_value = {}

        valid, error = _validate_mac_addresses(
            [{"name": "vnic1", "parent_interface": "eth0", "mac": "02:00:00:00:00:01"}],
            container_runtime=runtime,
        )

        assert valid is True
        assert error == ""

    def test_mac_already_in_use(self):
        """User MAC conflicts → invalid."""
        runtime = MagicMock()
        runtime.get_existing_mac_addresses_on_interface.return_value = {
            "02:00:00:00:00:01": "plc2"
        }

        valid, error = _validate_mac_addresses(
            [{"name": "vnic1", "parent_interface": "eth0", "mac": "02:00:00:00:00:01"}],
            container_runtime=runtime,
        )

        assert valid is False
        assert "already in use" in error


class TestCreateRuntimeContainerSync:
    def _make_deps(self):
        runtime = MagicMock()
        runtime.NotFoundError = type("NotFoundError", (Exception,), {})
        runtime.ImageNotFound = type("ImageNotFound", (Exception,), {})
        runtime.APIError = type("APIError", (Exception,), {})
        vnic_repo = MagicMock()
        serial_repo = MagicMock()
        registry = MagicMock()
        cache = MagicMock()
        ops = MagicMock()
        buffer = MagicMock()
        socket_repo = MagicMock()
        return runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_name_already_registered(self, mock_vnic_val, mock_mac_val):
        """client_registry.contains=True → None, sets error."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = True

        result = _create_runtime_container_sync(
            "plc1", [],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        ops.set_error.assert_called_once()
        mock_vnic_val.assert_not_called()

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_vnic_validation_fails(self, mock_vnic_val, mock_mac_val):
        """Invalid vNICs → None, sets error."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (False, "duplicate network")

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        ops.set_error.assert_called_once()

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_mac_validation_fails(self, mock_vnic_val, mock_mac_val):
        """MAC validation fails → None, sets error."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (False, "MAC already in use")

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        ops.set_error.assert_called_once()

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_full_creation_with_ethernet_api144(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Full container creation with ethernet vNIC and API >= 1.44."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_192_168_1_0_24"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_192_168_1_0_24": {
                        "IPAddress": "192.168.1.100",
                        "MacAddress": "02:00:00:00:00:01",
                    },
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container

        main_container = MagicMock()
        main_container.name = "orchestrator_agent"
        mock_get_self.return_value = main_container

        vnic_configs = [
            {
                "name": "v1",
                "parent_interface": "eth0",
                "network_mode": "dhcp",
                "subnet": "255.255.255.0",
                "gateway": "192.168.1.1",
                "dns": ["8.8.8.8"],
            }
        ]

        result = _create_runtime_container_sync(
            "plc1", vnic_configs,
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        assert len(result["dhcp_vnics"]) == 1
        registry.add_client.assert_called_once_with("plc1", "172.18.0.2")
        vnic_repo.save_configs.assert_called_once()
        buffer.add_device.assert_called_once_with("plc1")
        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_image_not_found_uses_local(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Image pull NotFoundError + local image exists → fallback."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"
        runtime.pull_image.side_effect = runtime.NotFoundError("not found")
        runtime.get_image.return_value = MagicMock()

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {
                        "IPAddress": "0.0.0.0",
                        "MacAddress": "02:00:00:00:00:01",
                    },
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_image_not_found_no_local_returns_none(self, mock_vnic_val, mock_mac_val):
        """Image pull NotFoundError + no local image → error."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        runtime.pull_image.side_effect = runtime.NotFoundError("not found")
        runtime.get_image.side_effect = runtime.ImageNotFound("not found locally")

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        ops.set_error.assert_called_once()

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_image_pull_generic_failure_continues(self, mock_vnic_val, mock_mac_val):
        """Generic image pull failure logs warning and continues."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"
        runtime.pull_image.side_effect = RuntimeError("network timeout")

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container

        with patch("use_cases.docker_manager.create_runtime_container.get_self_container", return_value=None):
            result = _create_runtime_container_sync(
                "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
                container_runtime=runtime,
                vnic_repo=vnic_repo,
                serial_repo=serial_repo,
                client_registry=registry,
                interface_cache=cache,
                operations_state=ops,
                devices_usage_buffer=buffer,
                socket_repo=socket_repo,
            )

        assert result is not None

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_api_below_144_connects_after_creation(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """API < 1.44 connects MACVLAN after creation."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.43"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        macvlan_net.connect.assert_called_once()

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_api_below_144_macvlan_connect_fails(self, mock_vnic_val, mock_mac_val):
        """API < 1.44 MACVLAN connect failure removes container and re-raises."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        macvlan_net.connect.side_effect = runtime.APIError("endpoint already exists")
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.43"

        container = MagicMock()
        runtime.create_container.return_value = container

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        container.remove.assert_called_once_with(force=True)

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_self_container_already_connected(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Self container 'already exists' APIError is handled gracefully."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        internal_net.connect.side_effect = runtime.APIError("already exists in network")
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container

        main_container = MagicMock()
        main_container.name = "orchestrator_agent"
        mock_get_self.return_value = main_container

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_wifi_vnic_collected(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """WiFi vNIC is collected for post-creation configuration."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "wifi"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "wifi_v1", "parent_interface": "wlan0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        assert len(result["wifi_vnics_to_configure"]) == 1
        assert result["wifi_vnics_to_configure"][0]["vnic_name"] == "wifi_v1"

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_serial_configs_saved(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Serial configs are saved when provided."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        serial_configs = [{"name": "modbus", "device_id": "usb-FTDI", "container_path": "/dev/modbus0"}]

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            serial_configs=serial_configs,
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        serial_repo.save_configs.assert_called_once_with("plc1", serial_configs)

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_user_provided_mac_address(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """User-provided MAC address is used instead of auto-generated."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:AA:BB:CC:DD:EE"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp", "mac": "02:AA:BB:CC:DD:EE"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        # create_endpoint_config should have been called with the user MAC
        endpoint_call = runtime.create_endpoint_config.call_args_list
        # First call for macvlan network should include mac_address
        found_mac = False
        for call in endpoint_call:
            if "mac_address" in call[1]:
                assert call[1]["mac_address"] == "02:AA:BB:CC:DD:EE"
                found_mac = True
        assert found_mac

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_self_container_api_error_other(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """APIError not 'already exists' logs warning."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        internal_net.connect.side_effect = runtime.APIError("network is full")
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container

        main_container = MagicMock()
        main_container.name = "orchestrator_agent"
        mock_get_self.return_value = main_container

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        # Still succeeds despite internal network connection warning
        assert result is not None

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_generic_exception_connecting_internal(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Generic exception connecting to internal network is handled."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.side_effect = RuntimeError("detection error")

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_internal_network_not_in_settings(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Internal network not in network settings logs warning."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        # Internal network NOT present in NetworkSettings
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        # add_client should NOT be called since internal network not found
        registry.add_client.assert_not_called()

    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_exception_during_creation_sets_error(self, mock_vnic_val, mock_mac_val):
        """Exception during container creation sets error state."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        runtime.create_internal_network.side_effect = RuntimeError("Docker error")

        result = _create_runtime_container_sync(
            "plc1", [{"name": "v1", "parent_interface": "eth0"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is None
        ops.set_error.assert_called_once()

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_static_ip_with_macvlan(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Static IP mode with MACVLAN passes IP to endpoint config."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "10.0.0.50", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        result = _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "static", "ip": "10.0.0.50/24"}],
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        assert result is not None
        # verify static mode does NOT add dhcp_vnics
        assert len(result["dhcp_vnics"]) == 0

    @patch("use_cases.docker_manager.create_runtime_container.get_self_container")
    @patch("use_cases.docker_manager.create_runtime_container._validate_mac_addresses")
    @patch("use_cases.docker_manager.create_runtime_container._validate_vnic_configs")
    def test_runtime_version_tag(self, mock_vnic_val, mock_mac_val, mock_get_self):
        """Custom runtime_version tag is used in image name."""
        runtime, vnic_repo, serial_repo, registry, cache, ops, buffer, socket_repo = self._make_deps()
        registry.contains.return_value = False
        mock_vnic_val.return_value = (True, "")
        mock_mac_val.return_value = (True, "")
        cache.get_interface_type.return_value = "ethernet"

        internal_net = MagicMock()
        internal_net.name = "plc1_internal"
        runtime.create_internal_network.return_value = internal_net

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_net"
        runtime.get_or_create_macvlan_network.return_value = macvlan_net

        runtime.get_api_version.return_value = "1.44"
        runtime.create_endpoint_config.return_value = {}

        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "plc1_internal": {"IPAddress": "172.18.0.2"},
                    "macvlan_eth0_net": {"IPAddress": "0.0.0.0", "MacAddress": "02:00:00:00:00:01"},
                }
            },
            "State": {"Pid": 1234},
        }
        runtime.create_container.return_value = container
        mock_get_self.return_value = None

        _create_runtime_container_sync(
            "plc1",
            [{"name": "v1", "parent_interface": "eth0", "network_mode": "dhcp"}],
            runtime_version="v2.0",
            container_runtime=runtime,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            client_registry=registry,
            interface_cache=cache,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=socket_repo,
        )

        create_call = runtime.create_container.call_args
        assert "v2.0" in create_call[1]["image"]


class TestCreateRuntimeContainerAsync:
    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_result_none_returns_early(self, mock_asyncio):
        """Result None from sync function returns early."""
        mock_asyncio.to_thread = AsyncMock(return_value=None)

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=MagicMock(),
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=MagicMock(),
            operations_state=MagicMock(),
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_dhcp_for_macvlan_vnics(self, mock_asyncio):
        """DHCP started for MACVLAN vNICs."""
        commander = AsyncMock()
        ops = MagicMock()

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [("v1", "02:00:00:00:00:01", 1234)],
            "wifi_vnics_to_configure": [],
            "vnic_configs": [],
        })

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=MagicMock(),
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.start_dhcp.assert_called_once_with("plc1", "v1", "02:00:00:00:00:01", 1234)

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_wifi_static_ip_configuration(self, mock_asyncio):
        """WiFi static IP configured via proxy ARP bridge."""
        commander = AsyncMock()
        ops = MagicMock()
        vnic_repo = MagicMock()

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "static",
            "ip": "10.0.0.50/24",
            "gateway": "10.0.0.1",
            "subnet": "255.255.255.0",
        }

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [{
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "container_pid": 1234,
                "vnic_config": vnic_config,
            }],
            "vnic_configs": [vnic_config],
        })

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=vnic_repo,
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.setup_proxy_arp_bridge.assert_called_once()
        vnic_repo.save_configs.assert_called_once()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_wifi_static_no_ip_logs_error(self, mock_asyncio):
        """WiFi static mode without ip and gateway logs error."""
        commander = AsyncMock()
        ops = MagicMock()
        vnic_repo = MagicMock()

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "static",
        }

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [{
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "container_pid": 1234,
                "vnic_config": vnic_config,
            }],
            "vnic_configs": [vnic_config],
        })

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=vnic_repo,
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.setup_proxy_arp_bridge.assert_not_called()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_wifi_dhcp_configuration(self, mock_asyncio):
        """WiFi DHCP configuration via request_wifi_dhcp."""
        commander = AsyncMock()
        commander.request_wifi_dhcp.return_value = {"success": True}
        ops = MagicMock()
        vnic_repo = MagicMock()

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
        }

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [{
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "container_pid": 1234,
                "vnic_config": vnic_config,
            }],
            "vnic_configs": [vnic_config],
        })

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=vnic_repo,
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.request_wifi_dhcp.assert_called_once()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_wifi_dhcp_not_success(self, mock_asyncio):
        """WiFi DHCP request returns not success logs warning."""
        commander = AsyncMock()
        commander.request_wifi_dhcp.return_value = {"success": False, "error": "timeout"}
        ops = MagicMock()
        vnic_repo = MagicMock()

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
        }

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [{
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "container_pid": 1234,
                "vnic_config": vnic_config,
            }],
            "vnic_configs": [vnic_config],
        })

        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=vnic_repo,
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.request_wifi_dhcp.assert_called_once()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_wifi_exception_handled(self, mock_asyncio):
        """Exception during WiFi vNIC configuration is handled."""
        commander = AsyncMock()
        commander.request_wifi_dhcp.side_effect = RuntimeError("netmon error")
        ops = MagicMock()
        vnic_repo = MagicMock()

        vnic_config = {
            "name": "wifi_v1",
            "parent_interface": "wlan0",
            "network_mode": "dhcp",
        }

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [{
                "vnic_name": "wifi_v1",
                "parent_interface": "wlan0",
                "container_pid": 1234,
                "vnic_config": vnic_config,
            }],
            "vnic_configs": [vnic_config],
        })

        # Should not raise
        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=vnic_repo,
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_serial_device_resync(self, mock_asyncio):
        """Serial device resync triggered after creation."""
        commander = AsyncMock()
        ops = MagicMock()

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [],
            "vnic_configs": [],
        })

        await create_runtime_container(
            "plc1", [],
            serial_configs=[{"name": "modbus"}],
            container_runtime=MagicMock(),
            vnic_repo=MagicMock(),
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

        commander.resync_serial_devices.assert_called_once()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_serial_resync_exception_handled(self, mock_asyncio):
        """Exception during serial resync is handled gracefully."""
        commander = AsyncMock()
        commander.resync_serial_devices.side_effect = RuntimeError("resync error")
        ops = MagicMock()

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [],
            "wifi_vnics_to_configure": [],
            "vnic_configs": [],
        })

        # Should not raise
        await create_runtime_container(
            "plc1", [],
            serial_configs=[{"name": "modbus"}],
            container_runtime=MagicMock(),
            vnic_repo=MagicMock(),
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_dhcp_exception_handled(self, mock_asyncio):
        """Exception during DHCP start is handled gracefully."""
        commander = AsyncMock()
        commander.start_dhcp.side_effect = RuntimeError("dhcp error")
        ops = MagicMock()

        mock_asyncio.to_thread = AsyncMock(return_value={
            "dhcp_vnics": [("v1", "02:00:00:00:00:01", 1234)],
            "wifi_vnics_to_configure": [],
            "vnic_configs": [],
        })

        # Should not raise
        await create_runtime_container(
            "plc1", [],
            container_runtime=MagicMock(),
            vnic_repo=MagicMock(),
            serial_repo=MagicMock(),
            client_registry=MagicMock(),
            interface_cache=MagicMock(),
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=MagicMock(),
            socket_repo=MagicMock(),
        )


class TestStartCreation:
    @pytest.mark.asyncio
    @patch("tools.operations_state.begin_operation")
    @patch("use_cases.docker_manager.create_runtime_container.create_runtime_container")
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_start_creation_success(self, mock_asyncio, mock_create, mock_begin):
        """Returns (status_dict, True) on success."""
        mock_begin.return_value = (None, True)
        ctx = MagicMock()

        result, started = await start_creation("plc1", [], ctx=ctx)

        assert started is True
        assert result["status"] == "creating"
        assert result["container_id"] == "plc1"

    @pytest.mark.asyncio
    @patch("tools.operations_state.begin_operation")
    async def test_start_creation_already_in_progress(self, mock_begin):
        """Returns (error, False) when operation already in progress."""
        error = {"status": "error", "error": "already in progress"}
        mock_begin.return_value = (error, False)
        ctx = MagicMock()

        result, started = await start_creation("plc1", [], ctx=ctx)

        assert started is False
        assert result["status"] == "error"

    @pytest.mark.asyncio
    @patch("tools.operations_state.begin_operation")
    @patch("use_cases.docker_manager.create_runtime_container.create_runtime_container")
    @patch("use_cases.docker_manager.create_runtime_container.asyncio")
    async def test_start_creation_with_serial_configs(self, mock_asyncio, mock_create, mock_begin):
        """Serial configs are logged when provided."""
        mock_begin.return_value = (None, True)
        ctx = MagicMock()
        serial_configs = [{"name": "modbus", "device_id": "usb-FTDI"}]

        result, started = await start_creation("plc1", [], serial_configs=serial_configs, ctx=ctx)

        assert started is True
        assert result["status"] == "creating"
