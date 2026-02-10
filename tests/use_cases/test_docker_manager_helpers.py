import pytest
from unittest.mock import MagicMock, patch

from use_cases.docker_manager import stop_and_remove_container, remove_internal_network, get_self_container


class _NotFoundError(Exception):
    """Fake NotFoundError for mocking container_runtime."""
    pass


def _make_runtime():
    """Create a MagicMock container_runtime with a real NotFoundError exception class."""
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


class TestGetSelfContainer:
    @patch("use_cases.docker_manager.os")
    def test_found_via_hostname_env(self, mock_os):
        """HOSTNAME env var finds the container."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: "abc123" if key == "HOSTNAME" else None
        container = MagicMock()
        container.name = "orchestrator_agent"
        mock_runtime.get_container.return_value = container

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container
        mock_runtime.get_container.assert_called_once_with("abc123")

    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_hostname_env_not_found_falls_through(self, mock_os, mock_socket):
        """HOSTNAME env container not found falls through to socket.gethostname."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: "abc123" if key == "HOSTNAME" else None
        mock_socket.gethostname.return_value = "host123"
        container = MagicMock()
        container.name = "orchestrator_agent"
        # First call (HOSTNAME) raises NotFoundError, second (socket) succeeds
        mock_runtime.get_container.side_effect = [_NotFoundError, container]

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container

    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_found_via_socket_gethostname(self, mock_os, mock_socket):
        """socket.gethostname() finds the container when HOSTNAME env fails."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.return_value = "host123"
        container = MagicMock()
        container.name = "orchestrator_agent"
        mock_runtime.get_container.return_value = container

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container

    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_socket_gethostname_not_found(self, mock_os, mock_socket):
        """socket.gethostname container not found falls through to HOST_NAME."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.return_value = "host123"
        # NotFoundError from socket hostname lookup
        mock_runtime.get_container.side_effect = _NotFoundError
        mock_runtime.list_containers.return_value = []

        result = get_self_container(container_runtime=mock_runtime)

        # Falls through all methods → None
        assert result is None

    @patch("use_cases.docker_manager.HOST_NAME", "custom_host")
    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_found_via_host_name_env(self, mock_os, mock_socket):
        """HOST_NAME env var finds the container when other methods fail."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.side_effect = Exception("no hostname")
        container = MagicMock()
        container.name = "orchestrator_agent"
        # HOSTNAME is None (skip), socket.gethostname raises (skip), HOST_NAME works
        mock_runtime.get_container.return_value = container

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container
        mock_runtime.get_container.assert_called_with("custom_host")

    @patch("use_cases.docker_manager.HOST_NAME", "custom_host")
    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_host_name_not_found_falls_through(self, mock_os, mock_socket):
        """HOST_NAME container not found falls through to label search."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.side_effect = Exception("no hostname")
        mock_runtime.get_container.side_effect = _NotFoundError
        container = MagicMock()
        container.name = "orchestrator_agent"
        mock_runtime.list_containers.return_value = [container]

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container

    @patch("use_cases.docker_manager.HOST_NAME", "")
    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_found_via_label_search(self, mock_os, mock_socket):
        """Label search finds the container when all other methods fail."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.side_effect = Exception("no hostname")
        container = MagicMock()
        container.name = "orchestrator_agent"
        mock_runtime.list_containers.return_value = [container]

        result = get_self_container(container_runtime=mock_runtime)

        assert result is container
        mock_runtime.list_containers.assert_called_once_with(
            filters={"label": "edge.autonomy.role=orchestrator-agent"}
        )

    @patch("use_cases.docker_manager.HOST_NAME", "")
    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_label_search_exception(self, mock_os, mock_socket):
        """Exception during label search returns None."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.side_effect = Exception("no hostname")
        mock_runtime.list_containers.side_effect = RuntimeError("docker error")

        result = get_self_container(container_runtime=mock_runtime)

        assert result is None

    @patch("use_cases.docker_manager.HOST_NAME", "")
    @patch("use_cases.docker_manager.socket")
    @patch("use_cases.docker_manager.os")
    def test_all_methods_fail_returns_none(self, mock_os, mock_socket):
        """When all detection methods fail, returns None."""
        mock_runtime = _make_runtime()
        mock_os.getenv.side_effect = lambda key, *args: None
        mock_socket.gethostname.side_effect = Exception("no hostname")
        mock_runtime.list_containers.return_value = []

        result = get_self_container(container_runtime=mock_runtime)

        assert result is None


class TestStopAndRemoveContainer:
    def test_stops_and_removes(self):
        mock_runtime = _make_runtime()
        mock_container = MagicMock()
        mock_runtime.get_container.return_value = mock_container

        stop_and_remove_container("plc1", container_runtime=mock_runtime)

        mock_runtime.get_container.assert_called_once_with("plc1")
        mock_container.stop.assert_called_once_with(timeout=10)
        mock_container.remove.assert_called_once_with(force=True)

    def test_not_found(self):
        mock_runtime = _make_runtime()
        mock_runtime.get_container.side_effect = _NotFoundError

        # Should not raise
        stop_and_remove_container("plc1", container_runtime=mock_runtime)

    def test_other_error_raises(self):
        mock_runtime = _make_runtime()
        mock_container = MagicMock()
        mock_runtime.get_container.return_value = mock_container
        mock_container.stop.side_effect = RuntimeError("Docker daemon error")

        with pytest.raises(RuntimeError, match="Docker daemon error"):
            stop_and_remove_container("plc1", container_runtime=mock_runtime)


class TestRemoveInternalNetwork:
    def test_removes_network(self):
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_network.attrs = {"Containers": {}}
        mock_runtime.get_network.return_value = mock_network

        remove_internal_network("plc1", container_runtime=mock_runtime)

        mock_runtime.get_network.assert_called_once_with("plc1_internal")
        mock_network.reload.assert_called_once()
        mock_network.remove.assert_called_once()

    def test_not_found(self):
        mock_runtime = _make_runtime()
        mock_runtime.get_network.side_effect = _NotFoundError

        # Should not raise
        remove_internal_network("plc1", container_runtime=mock_runtime)

    def test_disconnect_all(self):
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_network.attrs = {"Containers": {"cid1": {}, "cid2": {}}}
        mock_runtime.get_network.return_value = mock_network

        remove_internal_network("plc1", container_runtime=mock_runtime, disconnect_all=True)

        assert mock_network.disconnect.call_count == 2
        mock_network.remove.assert_called_once()

    @patch("use_cases.docker_manager.get_self_container")
    def test_disconnects_orchestrator_only(self, mock_get_self):
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_main = MagicMock()
        mock_main.id = "orch-id"
        mock_get_self.return_value = mock_main
        mock_network.attrs = {"Containers": {"orch-id": {}, "other-id": {}}}
        mock_runtime.get_network.return_value = mock_network

        remove_internal_network("plc1", container_runtime=mock_runtime, disconnect_all=False)

        mock_network.disconnect.assert_called_once_with(mock_main, force=True)
        mock_network.remove.assert_called_once()

    def test_disconnect_all_exception_logged(self):
        """Exception during disconnect_all is logged and continues."""
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_network.attrs = {"Containers": {"cid1": {}}}
        mock_network.disconnect.side_effect = RuntimeError("disconnect failed")
        mock_runtime.get_network.return_value = mock_network

        # Should not raise
        remove_internal_network("plc1", container_runtime=mock_runtime, disconnect_all=True)

        mock_network.disconnect.assert_called_once()
        mock_network.remove.assert_called_once()

    @patch("use_cases.docker_manager.get_self_container")
    def test_disconnect_orchestrator_exception_logged(self, mock_get_self):
        """Exception disconnecting orchestrator is logged and continues."""
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_main = MagicMock()
        mock_main.id = "orch-id"
        mock_get_self.return_value = mock_main
        mock_network.attrs = {"Containers": {"orch-id": {}}}
        mock_network.disconnect.side_effect = RuntimeError("disconnect failed")
        mock_runtime.get_network.return_value = mock_network

        # Should not raise
        remove_internal_network("plc1", container_runtime=mock_runtime, disconnect_all=False)

        mock_network.remove.assert_called_once()

    def test_generic_exception_logged(self):
        """Generic exception during remove_internal_network is logged."""
        mock_runtime = _make_runtime()
        mock_network = MagicMock()
        mock_network.attrs = {"Containers": {}}
        mock_network.remove.side_effect = RuntimeError("remove failed")
        mock_runtime.get_network.return_value = mock_network

        # Should not raise
        remove_internal_network("plc1", container_runtime=mock_runtime)
