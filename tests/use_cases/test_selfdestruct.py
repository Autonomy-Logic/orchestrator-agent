import pytest
from unittest.mock import MagicMock, patch, call

from use_cases.docker_manager.selfdestruct import (
    start_self_destruct,
    _delete_runtime_container_for_selfdestruct,
    _delete_all_runtime_containers,
    _cleanup_proxy_arp_veths,
    _cleanup_orchestrator_networks,
    _delete_netmon_container,
    _delete_shared_volume,
    _delete_orchestrator_container,
    self_destruct,
    ORCHESTRATOR_STATUS_ID,
    NETMON_CONTAINER_NAME,
    SHARED_VOLUME_NAME,
)


class _NotFoundError(Exception):
    pass


def _make_runtime():
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


class TestStartSelfDestruct:
    def test_success(self):
        """Returns True, sets deleting state."""
        ops = MagicMock()
        ops.set_deleting.return_value = True

        result = start_self_destruct(operations_state=ops)

        assert result is True
        ops.set_deleting.assert_called_once_with(ORCHESTRATOR_STATUS_ID)
        ops.set_step.assert_called_once_with(ORCHESTRATOR_STATUS_ID, "starting")

    def test_already_in_progress(self):
        """Returns False when self-destruct already in progress."""
        ops = MagicMock()
        ops.set_deleting.return_value = False

        result = start_self_destruct(operations_state=ops)

        assert result is False


class TestDeleteRuntimeContainerForSelfdestruct:
    @patch("use_cases.docker_manager.selfdestruct.remove_internal_network")
    @patch("use_cases.docker_manager.selfdestruct.stop_and_remove_container")
    def test_full_cleanup(self, mock_stop, mock_remove_net):
        """Stops container, removes usage buffer entry, deletes vnic configs, removes network."""
        runtime = _make_runtime()
        vnic_repo = MagicMock()
        buffer = MagicMock()

        _delete_runtime_container_for_selfdestruct("plc1", runtime, vnic_repo, buffer)

        mock_stop.assert_called_once_with("plc1", container_runtime=runtime)
        buffer.remove_device.assert_called_once_with("plc1")
        vnic_repo.delete_configs.assert_called_once_with("plc1")
        mock_remove_net.assert_called_once_with("plc1", container_runtime=runtime, disconnect_all=True)

    @patch("use_cases.docker_manager.selfdestruct.remove_internal_network")
    @patch("use_cases.docker_manager.selfdestruct.stop_and_remove_container")
    def test_usage_buffer_error_continues(self, mock_stop, mock_remove_net):
        """Usage buffer error does not stop cleanup."""
        runtime = _make_runtime()
        vnic_repo = MagicMock()
        buffer = MagicMock()
        buffer.remove_device.side_effect = RuntimeError("buffer error")

        _delete_runtime_container_for_selfdestruct("plc1", runtime, vnic_repo, buffer)

        vnic_repo.delete_configs.assert_called_once()
        mock_remove_net.assert_called_once()

    @patch("use_cases.docker_manager.selfdestruct.remove_internal_network")
    @patch("use_cases.docker_manager.selfdestruct.stop_and_remove_container")
    def test_vnic_delete_error_continues(self, mock_stop, mock_remove_net):
        """vnic_repo error does not stop cleanup."""
        runtime = _make_runtime()
        vnic_repo = MagicMock()
        vnic_repo.delete_configs.side_effect = RuntimeError("vnic error")
        buffer = MagicMock()

        _delete_runtime_container_for_selfdestruct("plc1", runtime, vnic_repo, buffer)

        mock_remove_net.assert_called_once()


class TestDeleteAllRuntimeContainers:
    @patch("use_cases.docker_manager.selfdestruct._delete_runtime_container_for_selfdestruct")
    def test_deletes_all_clients(self, mock_delete):
        """Iterates clients and deletes each."""
        runtime = _make_runtime()
        registry = MagicMock()
        registry.list_clients.return_value = {"plc1": {}, "plc2": {}}
        vnic_repo = MagicMock()
        buffer = MagicMock()

        _delete_all_runtime_containers(runtime, registry, vnic_repo, buffer)

        assert mock_delete.call_count == 2
        assert registry.remove_client.call_count == 2

    @patch("use_cases.docker_manager.selfdestruct._delete_runtime_container_for_selfdestruct")
    def test_no_clients(self, mock_delete):
        """Empty clients → early return."""
        runtime = _make_runtime()
        registry = MagicMock()
        registry.list_clients.return_value = {}
        vnic_repo = MagicMock()
        buffer = MagicMock()

        _delete_all_runtime_containers(runtime, registry, vnic_repo, buffer)

        mock_delete.assert_not_called()


class TestCleanupProxyArpVeths:
    @patch("use_cases.docker_manager.selfdestruct.socket")
    def test_successful_cleanup(self, mock_socket_mod):
        """Successful cleanup via netmon socket."""
        import json
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        response = json.dumps({"success": True, "veths_removed": 3}) + "\n"
        mock_sock.recv.return_value = response.encode("utf-8")

        _cleanup_proxy_arp_veths()

        mock_sock.connect.assert_called_once()
        mock_sock.sendall.assert_called_once()

    @patch("use_cases.docker_manager.selfdestruct.socket")
    def test_failed_cleanup(self, mock_socket_mod):
        """Failed cleanup response is handled."""
        import json
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        response = json.dumps({"success": False, "error": "no veths"}) + "\n"
        mock_sock.recv.return_value = response.encode("utf-8")

        _cleanup_proxy_arp_veths()

    @patch("use_cases.docker_manager.selfdestruct.socket")
    def test_no_response(self, mock_socket_mod):
        """No response from netmon is handled."""
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        mock_sock.recv.return_value = b""

        _cleanup_proxy_arp_veths()

    @patch("use_cases.docker_manager.selfdestruct.socket")
    def test_socket_exception(self, mock_socket_mod):
        """Socket exception is handled gracefully."""
        mock_socket_mod.socket.side_effect = RuntimeError("socket error")
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        # Should not raise
        _cleanup_proxy_arp_veths()


class TestCleanupOrchestratorNetworks:
    def test_removes_matching_networks(self):
        """Regex matching removes internal and macvlan networks."""
        runtime = _make_runtime()
        internal_net = MagicMock()
        internal_net.name = "abcdef01-2345-6789-abcd-ef0123456789_internal"
        internal_net.attrs = {"Containers": {}}

        macvlan_net = MagicMock()
        macvlan_net.name = "macvlan_eth0_192.168.1.0_24"
        macvlan_net.attrs = {"Containers": {}}

        other_net = MagicMock()
        other_net.name = "bridge"

        runtime.list_networks.return_value = [internal_net, macvlan_net, other_net]

        _cleanup_orchestrator_networks(runtime)

        internal_net.remove.assert_called_once()
        macvlan_net.remove.assert_called_once()
        other_net.remove.assert_not_called()

    def test_skips_connected_networks(self):
        """Networks with containers are skipped."""
        runtime = _make_runtime()
        net = MagicMock()
        net.name = "abcdef01-2345-6789-abcd-ef0123456789_internal"
        net.attrs = {"Containers": {"container1": {}}}
        runtime.list_networks.return_value = [net]

        _cleanup_orchestrator_networks(runtime)

        net.remove.assert_not_called()

    def test_list_networks_exception(self):
        """list_networks exception handled gracefully."""
        runtime = _make_runtime()
        runtime.list_networks.side_effect = RuntimeError("list error")

        # Should not raise
        _cleanup_orchestrator_networks(runtime)

    def test_network_not_found_during_removal(self):
        """NotFoundError during network removal is handled."""
        runtime = _make_runtime()
        net = MagicMock()
        net.name = "abcdef01-2345-6789-abcd-ef0123456789_internal"
        net.attrs = {"Containers": {}}
        net.remove.side_effect = _NotFoundError
        runtime.list_networks.return_value = [net]

        # Should not raise
        _cleanup_orchestrator_networks(runtime)

    def test_generic_exception_during_removal(self):
        """Generic exception during network removal is handled."""
        runtime = _make_runtime()
        net = MagicMock()
        net.name = "abcdef01-2345-6789-abcd-ef0123456789_internal"
        net.attrs = {"Containers": {}}
        net.remove.side_effect = RuntimeError("remove error")
        runtime.list_networks.return_value = [net]

        # Should not raise
        _cleanup_orchestrator_networks(runtime)


class TestDeleteNetmonContainer:
    def test_stops_and_removes(self):
        """Stops and removes autonomy_netmon."""
        runtime = _make_runtime()
        container = MagicMock()
        runtime.get_container.return_value = container

        _delete_netmon_container(runtime)

        runtime.get_container.assert_called_once_with(NETMON_CONTAINER_NAME)
        container.stop.assert_called_once_with(timeout=10)
        container.remove.assert_called_once_with(force=True)

    def test_not_found(self):
        """NotFoundError handled gracefully."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError

        # Should not raise
        _delete_netmon_container(runtime)

    def test_generic_exception_raises(self):
        """Generic exception is re-raised."""
        runtime = _make_runtime()
        container = MagicMock()
        container.stop.side_effect = RuntimeError("stop error")
        runtime.get_container.return_value = container

        with pytest.raises(RuntimeError, match="stop error"):
            _delete_netmon_container(runtime)


class TestDeleteSharedVolume:
    def test_removes_volume(self):
        """Removes volume."""
        runtime = _make_runtime()
        volume = MagicMock()
        runtime.get_volume.return_value = volume

        _delete_shared_volume(runtime)

        runtime.get_volume.assert_called_once_with(SHARED_VOLUME_NAME)
        volume.remove.assert_called_once_with(force=True)

    def test_not_found(self):
        """NotFoundError handled gracefully."""
        runtime = _make_runtime()
        runtime.get_volume.side_effect = _NotFoundError

        # Should not raise
        _delete_shared_volume(runtime)

    def test_generic_exception_handled(self):
        """Generic exception handled gracefully (best-effort)."""
        runtime = _make_runtime()
        volume = MagicMock()
        volume.remove.side_effect = RuntimeError("volume in use")
        runtime.get_volume.return_value = volume

        # Should not raise
        _delete_shared_volume(runtime)


class TestDeleteOrchestratorContainer:
    @patch("use_cases.docker_manager.selfdestruct.get_self_container")
    def test_removes_self(self, mock_get_self):
        """get_self_container → remove."""
        runtime = _make_runtime()
        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        mock_get_self.return_value = self_container

        _delete_orchestrator_container(runtime)

        self_container.remove.assert_called_once_with(force=True)

    @patch("use_cases.docker_manager.selfdestruct.get_self_container")
    def test_not_found_raises(self, mock_get_self):
        """get_self_container=None → raises RuntimeError."""
        runtime = _make_runtime()
        mock_get_self.return_value = None

        with pytest.raises(RuntimeError, match="Could not detect"):
            _delete_orchestrator_container(runtime)

    @patch("use_cases.docker_manager.selfdestruct.get_self_container")
    def test_remove_not_found_raises(self, mock_get_self):
        """NotFoundError during remove is re-raised."""
        runtime = _make_runtime()
        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        self_container.remove.side_effect = _NotFoundError
        mock_get_self.return_value = self_container

        with pytest.raises(_NotFoundError):
            _delete_orchestrator_container(runtime)

    @patch("use_cases.docker_manager.selfdestruct.get_self_container")
    def test_remove_generic_exception_raises(self, mock_get_self):
        """Generic exception during remove is re-raised."""
        runtime = _make_runtime()
        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        self_container.remove.side_effect = RuntimeError("remove error")
        mock_get_self.return_value = self_container

        with pytest.raises(RuntimeError, match="remove error"):
            _delete_orchestrator_container(runtime)


class TestSelfDestruct:
    @patch("use_cases.docker_manager.selfdestruct._delete_orchestrator_container")
    @patch("use_cases.docker_manager.selfdestruct._delete_shared_volume")
    @patch("use_cases.docker_manager.selfdestruct._delete_netmon_container")
    @patch("use_cases.docker_manager.selfdestruct._cleanup_proxy_arp_veths")
    @patch("use_cases.docker_manager.selfdestruct._cleanup_orchestrator_networks")
    @patch("use_cases.docker_manager.selfdestruct._delete_all_runtime_containers")
    def test_full_sequence(
        self,
        mock_delete_all,
        mock_cleanup_nets,
        mock_cleanup_veths,
        mock_delete_netmon,
        mock_delete_vol,
        mock_delete_orch,
    ):
        """All steps called in order with state tracking."""
        runtime = _make_runtime()
        registry = MagicMock()
        vnic_repo = MagicMock()
        ops = MagicMock()
        buffer = MagicMock()

        self_destruct(
            container_runtime=runtime,
            client_registry=registry,
            vnic_repo=vnic_repo,
            operations_state=ops,
            devices_usage_buffer=buffer,
        )

        mock_delete_all.assert_called_once_with(runtime, registry, vnic_repo, buffer)
        mock_cleanup_nets.assert_called_once_with(runtime)
        mock_cleanup_veths.assert_called_once()
        mock_delete_netmon.assert_called_once_with(runtime)
        mock_delete_vol.assert_called_once_with(runtime)
        mock_delete_orch.assert_called_once_with(runtime)

        # Verify steps were set
        ops.set_step.assert_any_call(ORCHESTRATOR_STATUS_ID, "deleting_runtimes")
        ops.set_step.assert_any_call(ORCHESTRATOR_STATUS_ID, "cleaning_networks")
        ops.set_step.assert_any_call(ORCHESTRATOR_STATUS_ID, "removing_self")

    @patch("use_cases.docker_manager.selfdestruct._delete_all_runtime_containers")
    def test_error_sets_state(self, mock_delete_all):
        """Exception → operations_state.set_error."""
        runtime = _make_runtime()
        registry = MagicMock()
        vnic_repo = MagicMock()
        ops = MagicMock()
        buffer = MagicMock()
        mock_delete_all.side_effect = RuntimeError("Docker error")

        with pytest.raises(RuntimeError):
            self_destruct(
                container_runtime=runtime,
                client_registry=registry,
                vnic_repo=vnic_repo,
                operations_state=ops,
                devices_usage_buffer=buffer,
            )

        ops.set_error.assert_called_once_with(
            ORCHESTRATOR_STATUS_ID, "Docker error", "self_destruct"
        )
