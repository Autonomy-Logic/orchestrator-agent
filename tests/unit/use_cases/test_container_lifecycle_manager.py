import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.container_lifecycle_manager import ContainerLifecycleManager


class _NotFoundError(Exception):
    pass


class _APIError(Exception):
    pass


def _make_runtime():
    runtime = MagicMock()
    runtime.NotFoundError = _NotFoundError
    runtime.APIError = _APIError
    return runtime


def _make_manager(**overrides):
    runtime = overrides.get("container_runtime", _make_runtime())
    registry = overrides.get("client_registry", MagicMock())
    socket_repo = overrides.get("socket_repo", MagicMock())
    ops = overrides.get("operations_state", MagicMock())

    mgr = ContainerLifecycleManager(
        container_runtime=runtime,
        client_registry=registry,
        socket_repo=socket_repo,
        operations_state=ops,
    )
    return mgr


def _make_container(status="running", restart_policy="no"):
    container = MagicMock()
    container.status = status
    container.name = "test-container"
    container.attrs = {
        "HostConfig": {"RestartPolicy": {"Name": restart_policy}},
        "NetworkSettings": {
            "Networks": {
                "test-container_internal": {"IPAddress": "172.18.0.2"}
            }
        },
    }
    return container


# ── Boot Startup ─────────────────────────────────────────────────────────


class TestStartExistingContainers:
    @pytest.mark.asyncio
    async def test_starts_stopped_containers(self):
        """Stopped containers should be started at boot."""
        runtime = _make_runtime()
        container = _make_container(status="exited")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._start_existing_containers()

        container.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_leaves_running_containers_alone(self):
        """Running containers must NEVER be restarted -- PLC process disruption."""
        runtime = _make_runtime()
        container = _make_container(status="running")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._start_existing_containers()

        container.start.assert_not_called()
        container.restart.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_missing_container_gracefully(self):
        """Container in registry but deleted externally should not crash."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError("gone")

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-ghost"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        # Should not raise
        await mgr._start_existing_containers()

    @pytest.mark.asyncio
    async def test_no_containers_is_noop(self):
        """Empty registry means nothing to do."""
        registry = MagicMock()
        registry.list_clients.return_value = []

        mgr = _make_manager(client_registry=registry)
        await mgr._start_existing_containers()


# ── Restart Policy Migration ─────────────────────────────────────────────


class TestMigrateRestartPolicy:
    @pytest.mark.asyncio
    async def test_migrates_always_to_no(self):
        """Old containers with restart:always should be migrated to restart:no."""
        runtime = _make_runtime()
        container = _make_container(status="running", restart_policy="always")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-old"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._start_existing_containers()

        container.update.assert_called_once_with(restart_policy={"Name": "no"})

    @pytest.mark.asyncio
    async def test_skips_migration_if_already_no(self):
        """Containers already with restart:no should not be updated."""
        runtime = _make_runtime()
        container = _make_container(status="running", restart_policy="no")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-new"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._start_existing_containers()

        container.update.assert_not_called()


# ── Bridge Reconnection ──────────────────────────────────────────────────


class TestReconnectOrchestratorToBridge:
    @pytest.mark.asyncio
    @patch("use_cases.container_lifecycle_manager.get_self_container")
    async def test_connects_orchestrator_to_internal_network(self, mock_get_self):
        runtime = _make_runtime()
        network = MagicMock()
        runtime.get_network.return_value = network
        orchestrator = MagicMock()
        mock_get_self.return_value = orchestrator

        mgr = _make_manager(container_runtime=runtime)
        await mgr._reconnect_orchestrator_to_bridge("plc-1")

        network.connect.assert_called_once_with(orchestrator)

    @pytest.mark.asyncio
    async def test_handles_missing_network(self):
        runtime = _make_runtime()
        runtime.get_network.side_effect = _NotFoundError("no network")

        mgr = _make_manager(container_runtime=runtime)
        # Should not raise
        await mgr._reconnect_orchestrator_to_bridge("plc-1")


# ── Container Exit Handling ──────────────────────────────────────────────


class TestHandleContainerExit:
    @pytest.mark.asyncio
    async def test_restarts_crashed_container(self):
        """Crashed (exited) containers should be started."""
        runtime = _make_runtime()
        container = _make_container(status="exited")
        runtime.get_container.return_value = container

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (False, None)

        mgr = _make_manager(container_runtime=runtime, operations_state=ops)
        mgr.RESTART_DELAY = 0  # Skip delay for test speed
        await mgr._handle_container_exit("plc-1")

        container.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_during_active_operation(self):
        """Don't restart if a create/delete operation is in progress."""
        runtime = _make_runtime()
        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (True, "deleting")

        mgr = _make_manager(container_runtime=runtime, operations_state=ops)
        mgr.RESTART_DELAY = 0
        await mgr._handle_container_exit("plc-1")

        runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_if_already_running(self):
        """If container recovered on its own, don't double-start."""
        runtime = _make_runtime()
        container = _make_container(status="running")
        runtime.get_container.return_value = container

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (False, None)

        mgr = _make_manager(container_runtime=runtime, operations_state=ops)
        mgr.RESTART_DELAY = 0
        await mgr._handle_container_exit("plc-1")

        container.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_container_not_found(self):
        """Container deleted between event and restart attempt."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError("gone")

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (False, None)

        mgr = _make_manager(container_runtime=runtime, operations_state=ops)
        mgr.RESTART_DELAY = 0
        # Should not raise
        await mgr._handle_container_exit("plc-1")


# ── Health Poll ──────────────────────────────────────────────────────────


class TestHealthPoll:
    @pytest.mark.asyncio
    async def test_detects_crashed_container(self):
        """Poll loop should detect a non-running container and restart it."""
        runtime = _make_runtime()
        container = _make_container(status="exited")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (False, None)

        mgr = _make_manager(
            container_runtime=runtime,
            client_registry=registry,
            operations_state=ops,
        )
        mgr.RESTART_DELAY = 0
        mgr.HEALTH_POLL_INTERVAL = 0
        mgr.running = True
        mgr._startup_done.set()

        # Run one iteration then cancel
        async def _run_one_poll():
            # Patch sleep to cancel after first iteration
            call_count = 0

            async def _mock_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    mgr.running = False

            with patch("asyncio.sleep", side_effect=_mock_sleep):
                await mgr._health_poll_loop()

        await _run_one_poll()
        container.start.assert_called()
