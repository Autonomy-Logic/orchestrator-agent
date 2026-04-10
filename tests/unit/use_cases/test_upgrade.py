import pytest
from unittest.mock import MagicMock, patch, call

from use_cases.docker_manager.upgrade import (
    start_upgrade,
    upgrade,
    _pull_images,
    _upgrade_netmon,
    _get_orchestrator_mount_config,
    _spawn_upgrader,
    ORCHESTRATOR_STATUS_ID,
    ORCHESTRATOR_IMAGE,
    NETMON_IMAGE,
    NETMON_CONTAINER_NAME,
    SHARED_VOLUME_NAME,
    UPGRADER_CONTAINER_NAME,
)


class _NotFoundError(Exception):
    pass


def _make_runtime():
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


class TestStartUpgrade:
    def test_success(self):
        """Returns True and sets upgrading state."""
        ops = MagicMock()
        ops.set_upgrading.return_value = True

        result = start_upgrade(operations_state=ops)

        assert result is True
        ops.set_upgrading.assert_called_once_with(ORCHESTRATOR_STATUS_ID)
        ops.set_step.assert_called_once_with(ORCHESTRATOR_STATUS_ID, "starting")

    def test_already_in_progress(self):
        """Returns False when operation already in progress."""
        ops = MagicMock()
        ops.set_upgrading.return_value = False

        result = start_upgrade(operations_state=ops)

        assert result is False
        ops.set_step.assert_not_called()


class TestPullImages:
    def test_pulls_both_images(self):
        """Pulls orchestrator and netmon images."""
        runtime = _make_runtime()
        ops = MagicMock()

        _pull_images(runtime, ops)

        runtime.pull_image.assert_any_call(ORCHESTRATOR_IMAGE)
        runtime.pull_image.assert_any_call(NETMON_IMAGE)
        assert runtime.pull_image.call_count == 2
        ops.set_step.assert_called_once_with(ORCHESTRATOR_STATUS_ID, "pulling_images")

    def test_pull_failure_raises(self):
        """Image pull failure propagates."""
        runtime = _make_runtime()
        runtime.pull_image.side_effect = RuntimeError("pull failed")
        ops = MagicMock()

        with pytest.raises(RuntimeError, match="pull failed"):
            _pull_images(runtime, ops)


class TestUpgradeNetmon:
    def test_stops_removes_recreates(self):
        """Stops old netmon, removes it, creates new one."""
        runtime = _make_runtime()
        ops = MagicMock()

        old_netmon = MagicMock()
        old_netmon.attrs = {
            "Mounts": [
                {"Name": "orchestrator-shared", "Destination": "/var/orchestrator", "RW": True},
                {"Source": "/dev", "Destination": "/dev", "RW": True},
                {"Source": "/run/udev", "Destination": "/run/udev", "RW": False},
            ]
        }

        new_netmon = MagicMock()

        def get_container(name):
            if name == NETMON_CONTAINER_NAME and not old_netmon.remove.called:
                return old_netmon
            if name == NETMON_CONTAINER_NAME and old_netmon.remove.called:
                return new_netmon
            raise _NotFoundError()

        runtime.get_container.side_effect = get_container

        _upgrade_netmon(runtime, ops)

        old_netmon.stop.assert_called_once_with(timeout=10)
        old_netmon.remove.assert_called_once_with(force=True)
        runtime.create_container.assert_called_once()
        new_netmon.start.assert_called_once()
        ops.set_step.assert_called_once_with(ORCHESTRATOR_STATUS_ID, "upgrading_netmon")

    def test_netmon_not_found_creates_fresh(self):
        """If old netmon not found, creates fresh container."""
        runtime = _make_runtime()
        ops = MagicMock()

        runtime.get_container.side_effect = _NotFoundError()
        new_netmon = MagicMock()
        # After create_container, get_container will return the new one
        runtime.get_container.side_effect = [_NotFoundError(), new_netmon]

        _upgrade_netmon(runtime, ops)

        runtime.create_container.assert_called_once()


class TestGetOrchestratorMountConfig:
    def test_extracts_mtls_and_volume(self):
        """Extracts mTLS host path and shared volume name from mounts."""
        container = MagicMock()
        container.attrs = {
            "Mounts": [
                {"Source": "/home/user/.mtls", "Destination": "/root/.mtls", "RW": False},
                {"Name": "orchestrator-shared", "Destination": "/var/orchestrator", "RW": True},
                {"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True},
            ]
        }

        config = _get_orchestrator_mount_config(container)

        assert config["mtls_host_path"] == "/home/user/.mtls"
        assert config["shared_volume"] == "orchestrator-shared"

    def test_missing_mtls(self):
        """Returns None for mtls if not found in mounts."""
        container = MagicMock()
        container.attrs = {
            "Mounts": [
                {"Name": "orchestrator-shared", "Destination": "/var/orchestrator", "RW": True},
            ]
        }

        config = _get_orchestrator_mount_config(container)

        assert config["mtls_host_path"] is None

    def test_no_mounts(self):
        """Returns defaults when no mounts exist."""
        container = MagicMock()
        container.attrs = {"Mounts": []}

        config = _get_orchestrator_mount_config(container)

        assert config["mtls_host_path"] is None
        assert config["shared_volume"] == SHARED_VOLUME_NAME


class TestSpawnUpgrader:
    @patch("use_cases.docker_manager.upgrade.get_self_container")
    def test_creates_upgrader_container(self, mock_get_self):
        """Creates upgrader with correct env vars and volumes."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()

        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        self_container.attrs = {
            "Mounts": [
                {"Source": "/root/.mtls", "Destination": "/root/.mtls", "RW": False},
                {"Name": "orchestrator-shared", "Destination": "/var/orchestrator", "RW": True},
            ]
        }
        mock_get_self.return_value = self_container

        # No leftover upgrader
        runtime.get_container.side_effect = _NotFoundError()

        upgrader = MagicMock()
        runtime.create_container.return_value = upgrader

        _spawn_upgrader(runtime, socket_repo, ops)

        runtime.create_container.assert_called_once()
        create_kwargs = runtime.create_container.call_args
        assert create_kwargs.kwargs["image"] == ORCHESTRATOR_IMAGE
        assert create_kwargs.kwargs["name"] == UPGRADER_CONTAINER_NAME
        assert create_kwargs.kwargs["command"] == ["python", "src/tools/upgrade_self.py"]
        env = create_kwargs.kwargs["environment"]
        assert env["UPGRADE_MODE"] == "true"
        assert env["TARGET_CONTAINER"] == "orchestrator_agent"
        assert env["MTLS_HOST_PATH"] == "/root/.mtls"
        upgrader.start.assert_called_once()

    @patch("use_cases.docker_manager.upgrade.get_self_container")
    def test_removes_leftover_upgrader(self, mock_get_self):
        """Removes leftover upgrader container from previous failed attempt."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()

        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        self_container.attrs = {
            "Mounts": [
                {"Source": "/root/.mtls", "Destination": "/root/.mtls", "RW": False},
                {"Name": "orchestrator-shared", "Destination": "/var/orchestrator", "RW": True},
            ]
        }
        mock_get_self.return_value = self_container

        old_upgrader = MagicMock()
        runtime.get_container.return_value = old_upgrader

        upgrader = MagicMock()
        runtime.create_container.return_value = upgrader

        _spawn_upgrader(runtime, socket_repo, ops)

        old_upgrader.remove.assert_called_once_with(force=True)

    @patch("use_cases.docker_manager.upgrade.get_self_container")
    def test_no_self_container_raises(self, mock_get_self):
        """Raises RuntimeError if self container not detected."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()
        mock_get_self.return_value = None

        with pytest.raises(RuntimeError, match="Could not detect"):
            _spawn_upgrader(runtime, socket_repo, ops)

    @patch("use_cases.docker_manager.upgrade.get_self_container")
    def test_no_mtls_path_raises(self, mock_get_self):
        """Raises RuntimeError if mTLS host path not found."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()

        self_container = MagicMock()
        self_container.name = "orchestrator_agent"
        self_container.attrs = {"Mounts": []}
        mock_get_self.return_value = self_container

        # No leftover upgrader
        runtime.get_container.side_effect = _NotFoundError()

        with pytest.raises(RuntimeError, match="mTLS host path"):
            _spawn_upgrader(runtime, socket_repo, ops)


class TestUpgrade:
    @patch("use_cases.docker_manager.upgrade._spawn_upgrader")
    @patch("use_cases.docker_manager.upgrade._upgrade_netmon")
    @patch("use_cases.docker_manager.upgrade._pull_images")
    def test_full_sequence(self, mock_pull, mock_netmon, mock_spawner):
        """All steps called in order with state tracking."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()

        upgrade(
            container_runtime=runtime,
            socket_repo=socket_repo,
            operations_state=ops,
        )

        mock_pull.assert_called_once_with(runtime, ops)
        mock_netmon.assert_called_once_with(runtime, ops)
        mock_spawner.assert_called_once_with(runtime, socket_repo, ops)
        ops.set_step.assert_called_with(ORCHESTRATOR_STATUS_ID, "upgrader_spawned")

    @patch("use_cases.docker_manager.upgrade._pull_images")
    def test_pull_failure_sets_error(self, mock_pull):
        """Pull failure sets error state and raises."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()
        mock_pull.side_effect = RuntimeError("pull failed")

        with pytest.raises(RuntimeError):
            upgrade(
                container_runtime=runtime,
                socket_repo=socket_repo,
                operations_state=ops,
            )

        ops.set_error.assert_called_once_with(
            ORCHESTRATOR_STATUS_ID, "pull failed", "upgrade"
        )

    @patch("use_cases.docker_manager.upgrade._upgrade_netmon")
    @patch("use_cases.docker_manager.upgrade._pull_images")
    def test_netmon_failure_sets_error(self, mock_pull, mock_netmon):
        """Netmon upgrade failure sets error state and raises."""
        runtime = _make_runtime()
        ops = MagicMock()
        socket_repo = MagicMock()
        mock_netmon.side_effect = RuntimeError("netmon error")

        with pytest.raises(RuntimeError):
            upgrade(
                container_runtime=runtime,
                socket_repo=socket_repo,
                operations_state=ops,
            )

        ops.set_error.assert_called_once_with(
            ORCHESTRATOR_STATUS_ID, "netmon error", "upgrade"
        )
