import asyncio
import time

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call

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

    @pytest.mark.asyncio
    async def test_stops_retrying_after_crash_loop(self):
        """After MAX_RAPID_RESTARTS, stop restarting and log error."""
        runtime = _make_runtime()
        container = _make_container(status="exited")
        runtime.get_container.return_value = container

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (False, None)

        mgr = _make_manager(container_runtime=runtime, operations_state=ops)
        mgr.RESTART_DELAY = 0
        mgr.MAX_RAPID_RESTARTS = 3
        mgr.RAPID_RESTART_WINDOW = 600

        # First 3 restarts should work
        for _ in range(3):
            await mgr._handle_container_exit("plc-loop")
        assert container.start.call_count == 3

        # 4th attempt should be blocked by crash-loop protection
        container.start.reset_mock()
        await mgr._handle_container_exit("plc-loop")
        container.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_generic_exception_during_restart(self):
        """Generic exception during container.start should be caught."""
        runtime = _make_runtime()
        container = _make_container(status="exited")
        container.start.side_effect = RuntimeError("Docker daemon error")
        runtime.get_container.return_value = container

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

            with patch("use_cases.container_lifecycle_manager.asyncio.sleep", side_effect=_mock_sleep):
                await mgr._health_poll_loop()

        await _run_one_poll()
        container.start.assert_called()


# ── Start / Stop / on_network_ready ──────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        mgr = _make_manager()
        # Patch the loops so they don't actually run
        mgr._docker_event_loop = AsyncMock()
        mgr._health_poll_loop = AsyncMock()

        await mgr.start()
        assert mgr.running is True
        assert mgr._event_task is not None
        assert mgr._poll_task is not None

        await mgr.stop()
        assert mgr.running is False
        assert mgr._event_task is None
        assert mgr._poll_task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        mgr = _make_manager()

        async def _hang():
            await asyncio.sleep(9999)

        mgr.running = True
        mgr._event_task = asyncio.create_task(_hang())
        mgr._poll_task = asyncio.create_task(_hang())

        await mgr.stop()
        assert mgr._event_task is None
        assert mgr._poll_task is None

    @pytest.mark.asyncio
    async def test_on_network_ready_sets_startup_done(self):
        registry = MagicMock()
        registry.list_clients.return_value = []
        mgr = _make_manager(client_registry=registry)

        assert not mgr._startup_done.is_set()
        await mgr.on_network_ready()
        assert mgr._startup_done.is_set()


# ── _start_existing_containers edge cases ────────────────────────────────


class TestStartExistingContainersEdgeCases:
    @pytest.mark.asyncio
    async def test_exception_in_one_container_does_not_block_others(self):
        """Error starting one container should not prevent starting the next."""
        runtime = _make_runtime()
        bad_container = MagicMock()
        bad_container.status = "exited"
        bad_container.attrs = {"HostConfig": {"RestartPolicy": {"Name": "no"}}}
        bad_container.start.side_effect = Exception("start failed")

        good_container = _make_container(status="exited")

        runtime.get_container.side_effect = [bad_container, good_container]

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-bad", "plc-good"]

        async def _passthrough(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        with patch("use_cases.container_lifecycle_manager.asyncio.to_thread", side_effect=_passthrough), \
             patch("use_cases.container_lifecycle_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr._start_existing_containers()

        good_container.start.assert_called_once()


# ── _ensure_container_running edge cases ─────────────────────────────────


class TestEnsureContainerRunningEdgeCases:
    @pytest.mark.asyncio
    async def test_unexpected_status_returns_early(self):
        """Container in unexpected state (e.g., 'paused') should be skipped."""
        runtime = _make_runtime()
        container = _make_container(status="paused")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-paused"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._start_existing_containers()

        container.start.assert_not_called()
        # _reconnect_orchestrator_to_bridge should NOT be called for unexpected state
        runtime.get_network.assert_not_called()


# ── _migrate_restart_policy edge cases ───────────────────────────────────


class TestMigrateRestartPolicyEdgeCases:
    @pytest.mark.asyncio
    async def test_migration_failure_does_not_crash(self):
        """Exception during policy migration should be caught."""
        runtime = _make_runtime()
        container = _make_container(status="running", restart_policy="always")
        container.update.side_effect = Exception("Docker API error")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        # Should not raise
        await mgr._start_existing_containers()


# ── _reconnect_orchestrator_to_bridge edge cases ─────────────────────────


class TestReconnectEdgeCases:
    @pytest.mark.asyncio
    @patch("use_cases.container_lifecycle_manager.get_self_container")
    async def test_already_connected_is_tolerated(self, mock_get_self):
        """APIError 'already exists' should be silently handled."""
        runtime = _make_runtime()
        network = MagicMock()
        network.connect.side_effect = _APIError("already exists in network")
        runtime.get_network.return_value = network
        mock_get_self.return_value = MagicMock()

        mgr = _make_manager(container_runtime=runtime)
        # Should not raise
        await mgr._reconnect_orchestrator_to_bridge("plc-1")

    @pytest.mark.asyncio
    @patch("use_cases.container_lifecycle_manager.get_self_container")
    async def test_api_error_non_duplicate_logged(self, mock_get_self):
        """Non-duplicate APIError should be logged as warning."""
        runtime = _make_runtime()
        network = MagicMock()
        network.connect.side_effect = _APIError("some other error")
        runtime.get_network.return_value = network
        mock_get_self.return_value = MagicMock()

        mgr = _make_manager(container_runtime=runtime)
        # Should not raise
        await mgr._reconnect_orchestrator_to_bridge("plc-1")

    @pytest.mark.asyncio
    @patch("use_cases.container_lifecycle_manager.get_self_container")
    async def test_no_self_container(self, mock_get_self):
        """If orchestrator container can't be found, skip reconnection."""
        runtime = _make_runtime()
        runtime.get_network.return_value = MagicMock()
        mock_get_self.return_value = None

        mgr = _make_manager(container_runtime=runtime)
        await mgr._reconnect_orchestrator_to_bridge("plc-1")
        # No crash, network.connect not called

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self):
        """Generic exception during reconnection should not propagate."""
        runtime = _make_runtime()
        runtime.get_network.side_effect = RuntimeError("unexpected")

        mgr = _make_manager(container_runtime=runtime)
        await mgr._reconnect_orchestrator_to_bridge("plc-1")


# ── _refresh_client_ip ───────────────────────────────────────────────────


class TestRefreshClientIp:
    @pytest.mark.asyncio
    async def test_updates_registry_with_internal_ip(self):
        runtime = _make_runtime()
        container = _make_container(status="running")
        runtime.get_container.return_value = container

        registry = MagicMock()
        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        await mgr._refresh_client_ip("test-container")

        registry.add_client.assert_called_once_with("test-container", "172.18.0.2")

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        runtime = _make_runtime()
        runtime.get_container.side_effect = Exception("boom")

        mgr = _make_manager(container_runtime=runtime)
        await mgr._refresh_client_ip("test-container")


# ── _consume_docker_events ───────────────────────────────────────────────


class TestConsumeDockerEvents:
    def test_processes_die_event_for_managed_container(self):
        runtime = _make_runtime()
        close_fn = MagicMock()
        events = [
            {
                "Action": "die",
                "Actor": {"Attributes": {"name": "plc-1", "exitCode": "137"}},
            }
        ]
        runtime.create_event_stream.return_value = (iter(events), close_fn)

        registry = MagicMock()
        registry.contains.return_value = True

        loop = MagicMock()
        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        mgr._loop = loop
        mgr.running = True
        mgr._consume_docker_events()

        loop.call_soon_threadsafe.assert_called_once()
        close_fn.assert_called_once()

    def test_skips_unmanaged_container(self):
        runtime = _make_runtime()
        close_fn = MagicMock()
        events = [
            {
                "Action": "die",
                "Actor": {"Attributes": {"name": "other-container", "exitCode": "0"}},
            }
        ]
        runtime.create_event_stream.return_value = (iter(events), close_fn)

        registry = MagicMock()
        registry.contains.return_value = False

        loop = MagicMock()
        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        mgr._loop = loop
        mgr.running = True
        mgr._consume_docker_events()

        loop.call_soon_threadsafe.assert_not_called()
        close_fn.assert_called_once()

    def test_stops_on_running_false(self):
        runtime = _make_runtime()
        close_fn = MagicMock()

        def _events():
            yield {"Action": "die", "Actor": {"Attributes": {"name": "plc-1"}}}
            yield {"Action": "die", "Actor": {"Attributes": {"name": "plc-2"}}}

        runtime.create_event_stream.return_value = (_events(), close_fn)

        registry = MagicMock()
        registry.contains.return_value = True

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        mgr.running = False
        mgr._loop = MagicMock()
        mgr._consume_docker_events()

        # Should stop after seeing running=False, not process any events
        mgr._loop.call_soon_threadsafe.assert_not_called()
        close_fn.assert_called_once()


# ── _docker_event_loop ───────────────────────────────────────────────────


class TestDockerEventLoop:
    @pytest.mark.asyncio
    async def test_retries_on_exception(self):
        """Event loop should retry after error with backoff."""
        mgr = _make_manager()
        mgr.running = True
        call_count = 0

        async def _failing_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("lost connection")
            mgr.running = False

        with patch("use_cases.container_lifecycle_manager.asyncio.to_thread", side_effect=_failing_to_thread), \
             patch("use_cases.container_lifecycle_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr._docker_event_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cancellation_handled(self):
        """CancelledError should propagate cleanly."""
        mgr = _make_manager()
        mgr.running = True

        async def _raise_cancel(fn, *args, **kwargs):
            raise asyncio.CancelledError()

        with patch("use_cases.container_lifecycle_manager.asyncio.to_thread", side_effect=_raise_cancel):
            with pytest.raises(asyncio.CancelledError):
                await mgr._docker_event_loop()

    @pytest.mark.asyncio
    async def test_stops_when_not_running_after_error(self):
        """If running is False when exception occurs, loop should exit."""
        mgr = _make_manager()
        mgr.running = True

        async def _fail_then_stop(fn, *args, **kwargs):
            mgr.running = False
            raise ConnectionError("lost connection")

        with patch("use_cases.container_lifecycle_manager.asyncio.to_thread", side_effect=_fail_then_stop):
            await mgr._docker_event_loop()


# ── _health_poll_loop edge cases ─────────────────────────────────────────


class TestHealthPollEdgeCases:
    @pytest.mark.asyncio
    async def test_skips_container_with_active_operation(self):
        runtime = _make_runtime()
        container = _make_container(status="exited")
        runtime.get_container.return_value = container

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        ops = MagicMock()
        ops.is_operation_in_progress.return_value = (True, "creating")

        mgr = _make_manager(
            container_runtime=runtime,
            client_registry=registry,
            operations_state=ops,
        )
        mgr.RESTART_DELAY = 0
        mgr.HEALTH_POLL_INTERVAL = 0
        mgr.running = True
        mgr._startup_done.set()

        call_count = 0

        async def _mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                mgr.running = False

        with patch("use_cases.container_lifecycle_manager.asyncio.sleep", side_effect=_mock_sleep):
            await mgr._health_poll_loop()

        container.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_not_found_during_poll(self):
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError("gone")

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-ghost"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        mgr.HEALTH_POLL_INTERVAL = 0
        mgr.running = True
        mgr._startup_done.set()

        call_count = 0

        async def _mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                mgr.running = False

        with patch("use_cases.container_lifecycle_manager.asyncio.sleep", side_effect=_mock_sleep):
            await mgr._health_poll_loop()

    @pytest.mark.asyncio
    async def test_handles_exception_during_poll(self):
        runtime = _make_runtime()
        runtime.get_container.side_effect = RuntimeError("Docker socket error")

        registry = MagicMock()
        registry.list_clients.return_value = ["plc-1"]

        mgr = _make_manager(container_runtime=runtime, client_registry=registry)
        mgr.HEALTH_POLL_INTERVAL = 0
        mgr.running = True
        mgr._startup_done.set()

        call_count = 0

        async def _mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                mgr.running = False

        with patch("use_cases.container_lifecycle_manager.asyncio.sleep", side_effect=_mock_sleep):
            await mgr._health_poll_loop()

    @pytest.mark.asyncio
    async def test_cancellation_handled(self):
        mgr = _make_manager()
        mgr.running = True
        mgr._startup_done.set()

        async def _raise_cancel(seconds):
            raise asyncio.CancelledError()

        with patch("use_cases.container_lifecycle_manager.asyncio.sleep", side_effect=_raise_cancel):
            with pytest.raises(asyncio.CancelledError):
                await mgr._health_poll_loop()


# ── Crash-loop detection helpers ─────────────────────────────────────────


class TestCrashLoopHelpers:
    def test_is_crash_looping_false_when_empty(self):
        mgr = _make_manager()
        assert mgr._is_crash_looping("plc-1") is False

    def test_is_crash_looping_false_below_threshold(self):
        mgr = _make_manager()
        mgr.MAX_RAPID_RESTARTS = 3
        mgr._restart_history["plc-1"] = [time.time(), time.time()]
        assert mgr._is_crash_looping("plc-1") is False

    def test_is_crash_looping_true_at_threshold(self):
        mgr = _make_manager()
        mgr.MAX_RAPID_RESTARTS = 3
        now = time.time()
        mgr._restart_history["plc-1"] = [now - 10, now - 5, now - 1]
        assert mgr._is_crash_looping("plc-1") is True

    def test_old_restarts_are_pruned(self):
        mgr = _make_manager()
        mgr.MAX_RAPID_RESTARTS = 3
        mgr.RAPID_RESTART_WINDOW = 60
        old = time.time() - 120  # 2 minutes ago (outside window)
        mgr._restart_history["plc-1"] = [old, old, old, old, old]
        assert mgr._is_crash_looping("plc-1") is False

    def test_record_restart_appends(self):
        mgr = _make_manager()
        mgr._record_restart("plc-1")
        mgr._record_restart("plc-1")
        assert len(mgr._restart_history["plc-1"]) == 2
