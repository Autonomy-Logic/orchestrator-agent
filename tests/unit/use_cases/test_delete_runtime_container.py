import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.docker_manager.delete_runtime_container import (
    _delete_runtime_container_sync,
    delete_runtime_container,
    start_deletion,
)


class _NotFoundError(Exception):
    pass


def _make_runtime():
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


def _make_deps():
    runtime = _make_runtime()
    registry = MagicMock()
    vnic_repo = MagicMock()
    serial_repo = MagicMock()
    ops = MagicMock()
    buffer = MagicMock()
    socket_repo = MagicMock()
    return runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo


def _call_sync(name, runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo):
    return _delete_runtime_container_sync(
        name,
        container_runtime=runtime,
        client_registry=registry,
        vnic_repo=vnic_repo,
        serial_repo=serial_repo,
        operations_state=ops,
        devices_usage_buffer=buffer,
        socket_repo=socket_repo,
    )


class TestDeleteRuntimeContainerSync:
    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_sync_deletion_success(self, mock_remove_net, mock_stop):
        """Full cleanup sequence verified via mock calls."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        registry.contains.return_value = True

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        mock_stop.assert_called_once_with("plc1", container_runtime=runtime)
        registry.remove_client.assert_called_once_with("plc1")
        buffer.remove_device.assert_called_once_with("plc1")
        vnic_repo.delete_configs.assert_called_once_with("plc1")
        serial_repo.delete_configs.assert_called_once_with("plc1")
        mock_remove_net.assert_called_once_with("plc1", container_runtime=runtime, socket_repo=socket_repo)

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_sync_deletion_sets_steps(self, mock_remove_net, mock_stop):
        """set_step called with 'stopping_container' and 'removing_networks'."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        ops.set_step.assert_any_call("plc1", "stopping_container")
        ops.set_step.assert_any_call("plc1", "removing_networks")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_sync_deletion_clears_state_on_success(self, mock_remove_net, mock_stop):
        """clear_state called on successful completion."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    def test_sync_deletion_sets_error_on_failure(self, mock_stop):
        """Exception → set_error called, re-raises."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        mock_stop.side_effect = RuntimeError("Docker daemon error")

        with pytest.raises(RuntimeError, match="Docker daemon error"):
            _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        ops.set_error.assert_called_once_with("plc1", "Docker daemon error", "delete")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_sync_deletion_continues_after_registry_error(self, mock_remove_net, mock_stop):
        """Registry error doesn't stop deletion."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        registry.remove_client.side_effect = RuntimeError("registry error")

        # Should NOT raise
        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        # Deletion continues — vnic_repo and serial_repo still called
        vnic_repo.delete_configs.assert_called_once()
        serial_repo.delete_configs.assert_called_once()
        mock_remove_net.assert_called_once()
        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_client_registry_not_contains_warns(self, mock_remove_net, mock_stop):
        """client_registry.contains returns False logs warning but continues."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        registry.contains.return_value = False

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        # Deletion still proceeds
        mock_stop.assert_called_once()
        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_usage_buffer_error_continues(self, mock_remove_net, mock_stop):
        """devices_usage_buffer.remove_device error does not stop deletion."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        buffer.remove_device.side_effect = RuntimeError("buffer error")

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        vnic_repo.delete_configs.assert_called_once()
        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_vnic_repo_delete_error_continues(self, mock_remove_net, mock_stop):
        """vnic_repo.delete_configs error does not stop deletion."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        vnic_repo.delete_configs.side_effect = RuntimeError("vnic error")

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        serial_repo.delete_configs.assert_called_once()
        ops.clear_state.assert_called_once_with("plc1")

    @patch("use_cases.docker_manager.delete_runtime_container.stop_and_remove_container")
    @patch("use_cases.docker_manager.delete_runtime_container.remove_internal_network")
    def test_serial_repo_delete_error_continues(self, mock_remove_net, mock_stop):
        """serial_repo.delete_configs error does not stop deletion."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        serial_repo.delete_configs.side_effect = RuntimeError("serial error")

        _call_sync("plc1", runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo)

        mock_remove_net.assert_called_once()
        ops.clear_state.assert_called_once_with("plc1")


class TestDeleteRuntimeContainerAsync:
    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_dedicated_nic_returned_when_running(self, mock_asyncio, mock_sync):
        """Dedicated NIC returned to host when container is running."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        nic_repo = MagicMock()
        nic_repo.load_config.return_value = {"host_interface": "enp3s0"}

        container = MagicMock()
        container.attrs = {"State": {"Pid": 42}}
        container.status = "running"
        runtime.get_container.return_value = container

        mock_asyncio.to_thread = AsyncMock()
        vnic_repo.load_all_configs.return_value = {}

        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
            dedicated_nic_repo=nic_repo,
        )

        commander.return_nic_to_host.assert_called_once_with("enp3s0", 42)
        nic_repo.delete_config.assert_called_once_with("plc1")

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_dedicated_nic_not_running(self, mock_asyncio, mock_sync):
        """Dedicated NIC: container not running → logs warning, config still deleted."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        nic_repo = MagicMock()
        nic_repo.load_config.return_value = {"host_interface": "enp3s0"}

        container = MagicMock()
        container.attrs = {"State": {"Pid": 0}}
        container.status = "exited"
        runtime.get_container.return_value = container

        mock_asyncio.to_thread = AsyncMock()
        vnic_repo.load_all_configs.return_value = {}

        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
            dedicated_nic_repo=nic_repo,
        )

        commander.return_nic_to_host.assert_not_called()
        nic_repo.delete_config.assert_called_once_with("plc1")

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_dedicated_nic_no_config(self, mock_asyncio, mock_sync):
        """No dedicated NIC config → no return attempted."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        nic_repo = MagicMock()
        nic_repo.load_config.return_value = None

        mock_asyncio.to_thread = AsyncMock()
        vnic_repo.load_all_configs.return_value = {}

        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
            dedicated_nic_repo=nic_repo,
        )

        commander.return_nic_to_host.assert_not_called()
        nic_repo.delete_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_dedicated_nic_outer_exception(self, mock_asyncio, mock_sync):
        """Exception from load_config itself → outer catch, deletion continues."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        nic_repo = MagicMock()
        nic_repo.load_config.side_effect = RuntimeError("disk error")

        mock_asyncio.to_thread = AsyncMock()
        vnic_repo.load_all_configs.return_value = {}

        # Should not raise
        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
            dedicated_nic_repo=nic_repo,
        )

        # Deletion thread still called
        mock_asyncio.to_thread.assert_called_once()

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_dedicated_nic_return_exception(self, mock_asyncio, mock_sync):
        """Exception during NIC return → logged, config still deleted."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        commander.return_nic_to_host.side_effect = RuntimeError("netmon error")
        nic_repo = MagicMock()
        nic_repo.load_config.return_value = {"host_interface": "enp3s0"}

        container = MagicMock()
        container.attrs = {"State": {"Pid": 42}}
        container.status = "running"
        runtime.get_container.return_value = container

        mock_asyncio.to_thread = AsyncMock()
        vnic_repo.load_all_configs.return_value = {}

        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
            dedicated_nic_repo=nic_repo,
        )

        nic_repo.delete_config.assert_called_once_with("plc1")

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_proxy_arp_cleanup_before_thread(self, mock_asyncio, mock_sync):
        """Proxy ARP cleanup called before deletion thread."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        vnic_repo.load_all_configs.return_value = {
            "plc1": [
                {
                    "name": "wifi_v1",
                    "_proxy_arp_config": {
                        "ip_address": "10.0.0.5",
                        "parent_interface": "wlan0",
                        "veth_host": "veth-plc1",
                    },
                }
            ]
        }

        # mock asyncio.to_thread to just call the function
        mock_asyncio.to_thread = AsyncMock()

        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
        )

        commander.cleanup_proxy_arp_bridge.assert_called_once_with(
            "plc1", "10.0.0.5", "wlan0", "veth-plc1"
        )

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_proxy_arp_cleanup_exception_handled(self, mock_asyncio, mock_sync):
        """Exception during Proxy ARP cleanup is handled gracefully."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        vnic_repo.load_all_configs.side_effect = RuntimeError("load error")

        mock_asyncio.to_thread = AsyncMock()

        # Should not raise
        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    @patch("use_cases.docker_manager.delete_runtime_container._delete_runtime_container_sync")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_proxy_arp_inner_exception_handled(self, mock_asyncio, mock_sync):
        """Exception during individual Proxy ARP bridge cleanup is handled."""
        runtime, registry, vnic_repo, serial_repo, ops, buffer, socket_repo = _make_deps()
        commander = AsyncMock()
        commander.cleanup_proxy_arp_bridge.side_effect = RuntimeError("cleanup failed")
        vnic_repo.load_all_configs.return_value = {
            "plc1": [
                {
                    "name": "wifi_v1",
                    "_proxy_arp_config": {
                        "ip_address": "10.0.0.5",
                        "parent_interface": "wlan0",
                        "veth_host": "veth-plc1",
                    },
                }
            ]
        }

        mock_asyncio.to_thread = AsyncMock()

        # Should not raise
        await delete_runtime_container(
            "plc1",
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            serial_repo=serial_repo,
            network_commander=commander,
            operations_state=ops,
            devices_usage_buffer=buffer,
            socket_repo=MagicMock(),
        )


class TestStartDeletion:
    @pytest.mark.asyncio
    @patch("tools.operations_state.begin_operation")
    @patch("use_cases.docker_manager.delete_runtime_container.delete_runtime_container")
    @patch("use_cases.docker_manager.delete_runtime_container.asyncio")
    async def test_start_deletion_success(self, mock_asyncio, mock_delete, mock_begin):
        """Returns (status_dict, True) on success."""
        mock_begin.return_value = (None, True)
        ctx = MagicMock()

        result, started = await start_deletion("plc1", ctx=ctx)

        assert started is True
        assert result["status"] == "deleting"
        assert result["device_id"] == "plc1"

    @pytest.mark.asyncio
    @patch("tools.operations_state.begin_operation")
    async def test_start_deletion_already_in_progress(self, mock_begin):
        """Returns (error, False) when operation already in progress."""
        error = {"status": "error", "error": "already in progress"}
        mock_begin.return_value = (error, False)
        ctx = MagicMock()

        result, started = await start_deletion("plc1", ctx=ctx)

        assert started is False
        assert result["status"] == "error"
