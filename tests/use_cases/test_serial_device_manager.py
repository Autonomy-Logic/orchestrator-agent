import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.serial_device_manager import SerialDeviceManager


class _NotFoundError(Exception):
    pass


def _make_manager():
    serial_repo = MagicMock()
    runtime = MagicMock()
    runtime.NotFoundError = _NotFoundError
    return SerialDeviceManager(serial_repo, runtime)


class TestHandleDeviceDiscovery:
    @pytest.mark.asyncio
    async def test_populates_cache(self):
        """Populates device_cache with discovered devices."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = []

        await mgr.handle_device_discovery({
            "devices": [
                {"by_id": "usb-FTDI_FT232R-if00", "path": "/dev/ttyUSB0", "major": 188, "minor": 0},
                {"by_id": "usb-Prolific-if00", "path": "/dev/ttyUSB1", "major": 188, "minor": 1},
            ]
        })

        assert len(mgr.device_cache) == 2
        assert "usb-FTDI_FT232R-if00" in mgr.device_cache
        assert "usb-Prolific-if00" in mgr.device_cache

    @pytest.mark.asyncio
    async def test_clears_old_cache(self):
        """Old cache entries are cleared before repopulating."""
        mgr = _make_manager()
        mgr.device_cache = {"old-device": {"path": "/dev/ttyUSB9"}}
        mgr.serial_repo.get_all_configured_ports.return_value = []

        await mgr.handle_device_discovery({"devices": []})

        assert len(mgr.device_cache) == 0

    @pytest.mark.asyncio
    async def test_skips_devices_without_by_id(self):
        """Devices without by_id are not cached."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = []

        await mgr.handle_device_discovery({
            "devices": [{"path": "/dev/ttyUSB0"}]
        })

        assert len(mgr.device_cache) == 0


class TestHandleDeviceChange:
    @pytest.mark.asyncio
    async def test_add_device_creates_node(self):
        """Adding a device creates device node in matching container."""
        mgr = _make_manager()
        mgr.serial_repo.get_by_device_id.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI_FT232R",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        exec_result = MagicMock()
        exec_result.exit_code = 0
        container.exec_run.return_value = exec_result

        await mgr.handle_device_change({
            "action": "add",
            "device": {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI_FT232R-if00",
                "major": 188,
                "minor": 0,
            },
        })

        assert "usb-FTDI_FT232R-if00" in mgr.device_cache
        mgr.serial_repo.update_status.assert_called_once_with(
            "plc1", "modbus", "connected",
            current_host_path="/dev/ttyUSB0", major=188, minor=0,
        )

    @pytest.mark.asyncio
    async def test_remove_device_updates_status(self):
        """Removing a device updates status to disconnected."""
        mgr = _make_manager()
        mgr.device_cache = {"usb-FTDI_FT232R-if00": {"path": "/dev/ttyUSB0", "by_id": "usb-FTDI_FT232R-if00"}}
        mgr.serial_repo.get_by_device_id.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {"name": "modbus", "device_id": "usb-FTDI_FT232R"},
            }
        ]

        await mgr.handle_device_change({
            "action": "remove",
            "device": {"path": "/dev/ttyUSB0", "by_id": "usb-FTDI_FT232R-if00"},
        })

        assert "usb-FTDI_FT232R-if00" not in mgr.device_cache
        mgr.serial_repo.update_status.assert_called_once_with(
            "plc1", "modbus", "disconnected"
        )

    @pytest.mark.asyncio
    async def test_invalid_event_returns_early(self):
        """Missing action or device → early return."""
        mgr = _make_manager()

        await mgr.handle_device_change({})
        await mgr.handle_device_change({"action": "add"})

        mgr.serial_repo.get_by_device_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_without_by_id_uses_path_lookup(self):
        """Remove event without by_id falls back to path-based cache lookup."""
        mgr = _make_manager()
        mgr.device_cache = {
            "usb-FTDI-if00": {"path": "/dev/ttyUSB0", "by_id": "usb-FTDI-if00"}
        }
        mgr.serial_repo.get_by_device_id.return_value = []

        await mgr.handle_device_change({
            "action": "remove",
            "device": {"path": "/dev/ttyUSB0"},
        })

        # Cache entry should be removed via path-based fallback
        assert "usb-FTDI-if00" not in mgr.device_cache

    @pytest.mark.asyncio
    async def test_add_invokes_callbacks(self):
        """Device add notifies registered callbacks."""
        mgr = _make_manager()
        callback = AsyncMock()
        mgr.device_update_callbacks = [callback]
        mgr.serial_repo.get_by_device_id.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {"name": "modbus", "device_id": "usb-FTDI", "container_path": "/dev/modbus0"},
            }
        ]
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        exec_result = MagicMock()
        exec_result.exit_code = 0
        container.exec_run.return_value = exec_result

        device = {"path": "/dev/ttyUSB0", "by_id": "usb-FTDI-if00", "major": 188, "minor": 0}
        await mgr.handle_device_change({"action": "add", "device": device})

        callback.assert_called_once_with("plc1", "modbus", "connected", device)


class TestMatchDeviceToConfigs:
    def test_matches_by_device_id(self):
        """Matches using serial_repo.get_by_device_id."""
        mgr = _make_manager()
        mgr.serial_repo.get_by_device_id.return_value = [
            {"container_name": "plc1", "serial_config": {"name": "modbus"}}
        ]

        result = mgr._match_device_to_configs({"by_id": "usb-FTDI-if00"})

        assert len(result) == 1
        assert result[0]["container_name"] == "plc1"

    def test_no_by_id_falls_back_to_path(self):
        """No by_id falls back to path-based matching."""
        mgr = _make_manager()
        mgr.serial_repo.load_configs.return_value = {
            "plc1": {
                "serial_ports": [
                    {"name": "modbus", "device_id": "ttyUSB0"}
                ]
            }
        }

        result = mgr._match_device_to_configs({"path": "/dev/ttyUSB0"})

        assert len(result) == 1
        assert result[0]["container_name"] == "plc1"

    def test_no_path_no_by_id_returns_empty(self):
        """No path and no by_id returns empty."""
        mgr = _make_manager()

        result = mgr._match_device_to_configs({})

        assert result == []


class TestGetAvailableDevices:
    def test_returns_cache_values(self):
        """Returns list of all cached devices."""
        mgr = _make_manager()
        mgr.device_cache = {
            "usb-FTDI": {"path": "/dev/ttyUSB0", "by_id": "usb-FTDI"},
            "usb-Prolific": {"path": "/dev/ttyUSB1", "by_id": "usb-Prolific"},
        }

        result = mgr.get_available_devices()

        assert len(result) == 2

    def test_empty_cache(self):
        """Empty cache returns empty list."""
        mgr = _make_manager()

        assert mgr.get_available_devices() == []


class TestGetDeviceById:
    def test_finds_matching_device(self):
        """Finds device matching the device_id."""
        mgr = _make_manager()
        mgr.device_cache = {
            "usb-FTDI_FT232R_ABC-if00-port0": {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI_FT232R_ABC-if00-port0",
            }
        }

        result = mgr.get_device_by_id("usb-FTDI_FT232R_ABC")

        assert result is not None
        assert result["path"] == "/dev/ttyUSB0"

    def test_no_match_returns_none(self):
        """No matching device returns None."""
        mgr = _make_manager()
        mgr.device_cache = {}

        assert mgr.get_device_by_id("nonexistent") is None


class TestRegisterDeviceCallback:
    def test_registers_callback(self):
        """Callback added to list."""
        mgr = _make_manager()
        cb = MagicMock()

        mgr.register_device_callback(cb)

        assert cb in mgr.device_update_callbacks


class TestCreateDeviceNode:
    @pytest.mark.asyncio
    @patch("use_cases.serial_device_manager.os")
    async def test_stat_host_device_when_major_minor_none(self, mock_os):
        """When major/minor are None, stat the host device to get them."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        exec_result = MagicMock()
        exec_result.exit_code = 0
        container.exec_run.return_value = exec_result

        stat_result = MagicMock()
        stat_result.st_rdev = 48128  # Example rdev
        mock_os.stat.return_value = stat_result
        mock_os.major.return_value = 188
        mock_os.minor.return_value = 0

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", None, None)

        assert result is True
        mock_os.stat.assert_called_once_with("/dev/ttyUSB0")

    @pytest.mark.asyncio
    @patch("use_cases.serial_device_manager.os")
    async def test_stat_host_device_fails(self, mock_os):
        """OSError from os.stat returns False."""
        mgr = _make_manager()
        mock_os.stat.side_effect = OSError("no device")

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", None, None)

        assert result is False

    @pytest.mark.asyncio
    async def test_container_not_found(self):
        """Container not found returns False."""
        mgr = _make_manager()
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is False

    @pytest.mark.asyncio
    async def test_container_not_running(self):
        """Container not running returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is False

    @pytest.mark.asyncio
    async def test_rm_nonzero_exit_continues(self):
        """rm exit_code != 0 logs debug but continues."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        rm_result = MagicMock()
        rm_result.exit_code = 1

        mknod_result = MagicMock()
        mknod_result.exit_code = 0

        chmod_result = MagicMock()
        chmod_result.exit_code = 0

        container.exec_run.side_effect = [rm_result, mknod_result, chmod_result]

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is True

    @pytest.mark.asyncio
    async def test_mknod_failure(self):
        """mknod exit_code != 0 returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        rm_result = MagicMock()
        rm_result.exit_code = 0

        mknod_result = MagicMock()
        mknod_result.exit_code = 1
        mknod_result.output = b"mknod: operation not permitted"

        container.exec_run.side_effect = [rm_result, mknod_result]

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is False

    @pytest.mark.asyncio
    async def test_chmod_failure_still_returns_true(self):
        """chmod exit_code != 0 logs warning but returns True."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        rm_result = MagicMock()
        rm_result.exit_code = 0

        mknod_result = MagicMock()
        mknod_result.exit_code = 0

        chmod_result = MagicMock()
        chmod_result.exit_code = 1
        chmod_result.output = b"chmod: failed"

        container.exec_run.side_effect = [rm_result, mknod_result, chmod_result]

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is True

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic exception in _create_device_node returns False."""
        mgr = _make_manager()
        mgr.container_runtime.get_container.side_effect = RuntimeError("unexpected")

        result = await mgr._create_device_node("plc1", "/dev/ttyUSB0", "/dev/modbus0", 188, 0)

        assert result is False


class TestRemoveDeviceNode:
    @pytest.mark.asyncio
    async def test_successful_removal(self):
        """Successful device node removal returns True."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        result = MagicMock()
        result.exit_code = 0
        container.exec_run.return_value = result

        ret = await mgr._remove_device_node("plc1", "/dev/modbus0")

        assert ret is True

    @pytest.mark.asyncio
    async def test_container_not_running(self):
        """Non-running container returns True (skips removal)."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        ret = await mgr._remove_device_node("plc1", "/dev/modbus0")

        assert ret is True

    @pytest.mark.asyncio
    async def test_container_not_found(self):
        """Container not found returns True (skips removal)."""
        mgr = _make_manager()
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        ret = await mgr._remove_device_node("plc1", "/dev/modbus0")

        assert ret is True

    @pytest.mark.asyncio
    async def test_rm_failure(self):
        """rm failure returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        result = MagicMock()
        result.exit_code = 1
        result.output = b"rm: cannot remove"
        container.exec_run.return_value = result

        ret = await mgr._remove_device_node("plc1", "/dev/modbus0")

        assert ret is False

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic exception returns False."""
        mgr = _make_manager()
        mgr.container_runtime.get_container.side_effect = RuntimeError("unexpected")

        ret = await mgr._remove_device_node("plc1", "/dev/modbus0")

        assert ret is False


class TestResyncSerialDevices:
    @pytest.mark.asyncio
    async def test_no_configured_ports(self):
        """No configured ports → early return."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = []

        await mgr.resync_serial_devices()

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_device_node_for_connected_device(self):
        """Connected device gets device node created."""
        mgr = _make_manager()
        mgr.device_cache = {
            "usb-FTDI_FT232R-if00": {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI_FT232R-if00",
                "major": 188,
                "minor": 0,
            }
        }
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI_FT232R-if00",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        exec_result = MagicMock()
        exec_result.exit_code = 0
        container.exec_run.return_value = exec_result

        await mgr.resync_serial_devices()

        mgr.serial_repo.update_status.assert_called_once_with(
            "plc1", "modbus", "connected",
            current_host_path="/dev/ttyUSB0", major=188, minor=0,
        )

    @pytest.mark.asyncio
    async def test_disconnected_device_marked(self):
        """Device not in cache marked as disconnected."""
        mgr = _make_manager()
        mgr.device_cache = {}
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI_FT232R",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        await mgr.resync_serial_devices()

        mgr.serial_repo.update_status.assert_called_once_with(
            "plc1", "modbus", "disconnected"
        )

    @pytest.mark.asyncio
    async def test_stale_container_cleaned_up(self):
        """Container not found → serial configs deleted."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "deleted_plc",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        await mgr.resync_serial_devices()

        mgr.serial_repo.delete_configs.assert_called_once_with("deleted_plc")

    @pytest.mark.asyncio
    async def test_skips_non_running_container(self):
        """Non-running container skipped during resync."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        container = MagicMock()
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        await mgr.resync_serial_devices()

        mgr.serial_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_incomplete_serial_config_skipped(self):
        """Incomplete serial config (missing device_id or container_path) is skipped."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                },
            }
        ]

        await mgr.resync_serial_devices()

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_resync_create_device_fails_updates_error(self):
        """Failed device creation during resync updates status to error."""
        mgr = _make_manager()
        mgr.device_cache = {
            "usb-FTDI-if00": {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI-if00",
                "major": 188,
                "minor": 0,
            }
        }
        mgr.serial_repo.get_all_configured_ports.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI-if00",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        container = MagicMock()
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        # mknod fails
        rm_result = MagicMock()
        rm_result.exit_code = 0
        mknod_result = MagicMock()
        mknod_result.exit_code = 1
        mknod_result.output = b"mknod: failed"
        container.exec_run.side_effect = [rm_result, mknod_result]

        await mgr.resync_serial_devices()

        mgr.serial_repo.update_status.assert_called_once_with("plc1", "modbus", "error")

    @pytest.mark.asyncio
    async def test_resync_exception_logged(self):
        """Exception in _resync_serial_devices logs error."""
        mgr = _make_manager()
        mgr.serial_repo.get_all_configured_ports.side_effect = RuntimeError("db error")

        # Should not raise
        await mgr.resync_serial_devices()


class TestNotifyDeviceCallbacks:
    @pytest.mark.asyncio
    async def test_callback_exception_handled(self):
        """Exception in device callback is handled gracefully."""
        mgr = _make_manager()
        failing_cb = MagicMock(side_effect=RuntimeError("callback error"))
        mgr.device_update_callbacks = [failing_cb]

        # Should not raise
        await mgr._notify_device_callbacks("plc1", "modbus", "connected", {})

        failing_cb.assert_called_once()


class TestHandleDeviceChangeFailedCreate:
    @pytest.mark.asyncio
    async def test_add_device_create_fails_logs_error(self):
        """Failed device node creation logs error (line 103)."""
        mgr = _make_manager()
        mgr.serial_repo.get_by_device_id.return_value = [
            {
                "container_name": "plc1",
                "serial_config": {
                    "name": "modbus",
                    "device_id": "usb-FTDI",
                    "container_path": "/dev/modbus0",
                },
            }
        ]
        # Container not found → _create_device_node returns False
        mgr.container_runtime.get_container.side_effect = _NotFoundError

        await mgr.handle_device_change({
            "action": "add",
            "device": {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI-if00",
                "major": 188,
                "minor": 0,
            },
        })

        # update_status should NOT be called since creation failed
        mgr.serial_repo.update_status.assert_not_called()
