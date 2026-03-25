import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from use_cases.dedicated_nic_manager import DedicatedNICManager


class _NotFoundError(Exception):
    pass


def _make_manager():
    netmon_client = MagicMock()
    netmon_client.move_nic_to_container = AsyncMock()
    netmon_client.check_nic_in_container = AsyncMock()

    container_runtime = MagicMock()
    container_runtime.NotFoundError = _NotFoundError

    dedicated_nic_repo = MagicMock()

    return DedicatedNICManager(netmon_client, container_runtime, dedicated_nic_repo)


class TestMoveNicToRunningContainer:
    @pytest.mark.asyncio
    async def test_returns_false_when_pid_is_zero(self):
        """Container with pid=0 returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 0}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container

        result = await mgr._move_nic_to_running_container("c1", "eth0")

        assert result is False
        mgr.netmon_client.move_nic_to_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_running(self):
        """Container with status != running returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 100}}
        container.status = "exited"
        mgr.container_runtime.get_container.return_value = container

        result = await mgr._move_nic_to_running_container("c1", "eth0")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_present_true_nic_already_in_container(self):
        """When check_present=True and NIC is already present, returns True without moving."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 100}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.check_nic_in_container.return_value = {"present": True}

        result = await mgr._move_nic_to_running_container("c1", "eth0", check_present=True)

        assert result is True
        mgr.netmon_client.check_nic_in_container.assert_awaited_once_with("eth0", 100)
        mgr.netmon_client.move_nic_to_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_present_true_nic_not_present_moves(self):
        """When check_present=True and NIC is not present, moves it."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 100}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.check_nic_in_container.return_value = {"present": False}
        mgr.netmon_client.move_nic_to_container.return_value = {"success": True}

        result = await mgr._move_nic_to_running_container("c1", "eth0", check_present=True)

        assert result is True
        mgr.netmon_client.move_nic_to_container.assert_awaited_once_with("eth0", 100)

    @pytest.mark.asyncio
    async def test_move_succeeds(self):
        """Default check_present=False, move succeeds returns True."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 100}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.move_nic_to_container.return_value = {"success": True}

        result = await mgr._move_nic_to_running_container("c1", "eth0")

        assert result is True
        mgr.netmon_client.check_nic_in_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_move_fails(self):
        """Move returns success=False, returns False."""
        mgr = _make_manager()
        container = MagicMock()
        container.attrs = {"State": {"Pid": 100}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.move_nic_to_container.return_value = {"success": False}

        result = await mgr._move_nic_to_running_container("c1", "eth0")

        assert result is False


class TestResyncNicsForExistingContainers:
    @pytest.mark.asyncio
    async def test_empty_configs_returns_early(self):
        """No configs means nothing happens."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_all_configs.return_value = {}

        await mgr.resync_nics_for_existing_containers()

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_configs_returns_early(self):
        """None configs means nothing happens."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_all_configs.return_value = None

        await mgr.resync_nics_for_existing_containers()

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_running_container_moves_nic(self):
        """Running container gets its NIC moved."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_all_configs.return_value = {
            "runtime1": {"host_interface": "enp3s0"},
        }
        container = MagicMock()
        container.attrs = {"State": {"Pid": 42}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.check_nic_in_container.return_value = {"present": False}
        mgr.netmon_client.move_nic_to_container.return_value = {"success": True}

        await mgr.resync_nics_for_existing_containers()

        mgr.netmon_client.move_nic_to_container.assert_awaited_once_with("enp3s0", 42)
        mgr.dedicated_nic_repo.delete_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found_error_cleans_orphan(self):
        """Container not found removes its config."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_all_configs.return_value = {
            "orphan": {"host_interface": "enp3s0"},
        }
        mgr.container_runtime.get_container.side_effect = _NotFoundError("gone")

        await mgr.resync_nics_for_existing_containers()

        mgr.dedicated_nic_repo.delete_config.assert_called_once_with("orphan")

    @pytest.mark.asyncio
    async def test_generic_exception_continues(self):
        """Generic exception is swallowed and processing continues."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_all_configs.return_value = {
            "bad": {"host_interface": "enp3s0"},
            "good": {"host_interface": "enp4s0"},
        }

        call_count = 0

        async def _side_effect(name, iface, *, check_present=False):
            nonlocal call_count
            call_count += 1
            if name == "bad":
                raise RuntimeError("something broke")
            return True

        with patch.object(mgr, "_move_nic_to_running_container", side_effect=_side_effect):
            await mgr.resync_nics_for_existing_containers()

        assert call_count == 2
        mgr.dedicated_nic_repo.delete_config.assert_not_called()


def _make_wait_for_with_events(mgr, events):
    """Create a patched wait_for that injects events into the queue, then stops."""
    original_wait_for = asyncio.wait_for
    call_count = 0

    async def _patched_wait_for(coro, **kwargs):
        nonlocal call_count
        if call_count < len(events):
            mgr._event_queue.put_nowait(events[call_count])
        call_count += 1
        if call_count > len(events):
            mgr._running = False
            raise asyncio.TimeoutError
        return await original_wait_for(coro, **kwargs)

    return _patched_wait_for


async def _run_event_listener(mgr, events):
    """Run start_docker_event_listener with injected events."""
    with patch("use_cases.dedicated_nic_manager.asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor.return_value = asyncio.Future()
        mock_loop.return_value.run_in_executor.return_value.set_result(None)
        patched_wait = _make_wait_for_with_events(mgr, events)
        with patch("use_cases.dedicated_nic_manager.asyncio.wait_for", side_effect=patched_wait):
            await mgr.start_docker_event_listener()


class TestStartDockerEventListener:
    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_event_with_matching_config_moves_nic(self, mock_sleep):
        """Docker start event with matching config triggers NIC move."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_config.return_value = {"host_interface": "enp3s0"}

        container = MagicMock()
        container.attrs = {"State": {"Pid": 55}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.move_nic_to_container.return_value = {"success": True}

        event = {"Actor": {"Attributes": {"name": "runtime1"}}}
        await _run_event_listener(mgr, [event])

        mgr.netmon_client.move_nic_to_container.assert_awaited_once_with("enp3s0", 55)

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_event_without_container_name_skipped(self, mock_sleep):
        """Event without container name is skipped."""
        mgr = _make_manager()

        event_no_name = {"Actor": {"Attributes": {}}}
        await _run_event_listener(mgr, [event_no_name])

        mgr.dedicated_nic_repo.load_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_event_with_no_config_skipped(self, mock_sleep):
        """Event for container with no dedicated NIC config is skipped."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_config.return_value = None

        event = {"Actor": {"Attributes": {"name": "runtime1"}}}
        await _run_event_listener(mgr, [event])

        mgr.container_runtime.get_container.assert_not_called()

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_exception_event_breaks_loop(self, mock_sleep):
        """An exception pushed to the queue breaks the event loop."""
        mgr = _make_manager()
        await _run_event_listener(mgr, [RuntimeError("docker error")])

        assert mgr._running is False

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_exception_during_move_continues(self, mock_sleep):
        """Exception during NIC move is swallowed and loop continues."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_config.return_value = {"host_interface": "enp3s0"}
        mgr.container_runtime.get_container.side_effect = RuntimeError("boom")

        event = {"Actor": {"Attributes": {"name": "runtime1"}}}
        await _run_event_listener(mgr, [event])

        mgr.dedicated_nic_repo.load_config.assert_called_once_with("runtime1")


class TestPollDockerEvents:
    """Tests for the _poll_docker_events inner function that runs in a thread."""

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_poll_pushes_events_to_queue(self, mock_sleep):
        """Docker events are pushed to the queue by the polling thread."""
        mgr = _make_manager()
        mgr.dedicated_nic_repo.load_config.return_value = {"host_interface": "enp3s0"}

        container = MagicMock()
        container.attrs = {"State": {"Pid": 55}}
        container.status = "running"
        mgr.container_runtime.get_container.return_value = container
        mgr.netmon_client.move_nic_to_container.return_value = {"success": True}

        event = {"Actor": {"Attributes": {"name": "runtime1"}}}
        mgr.container_runtime.docker_events.return_value = [event]

        # Use real run_in_executor so _poll_docker_events actually runs
        async def _run():
            # After the event is processed, stop
            original_wait_for = asyncio.wait_for
            call_count = 0

            async def _patched_wait_for(coro, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    mgr._running = False
                    raise asyncio.TimeoutError
                return await original_wait_for(coro, **kwargs)

            with patch("use_cases.dedicated_nic_manager.asyncio.wait_for", side_effect=_patched_wait_for):
                await mgr.start_docker_event_listener()

        await _run()

        mgr.container_runtime.docker_events.assert_called_once_with(
            filters={"event": ["start"]}, decode=True,
        )
        mgr.netmon_client.move_nic_to_container.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_poll_exception_pushed_to_queue(self, mock_sleep):
        """Exception in docker_events pushes error to queue, breaking the loop."""
        mgr = _make_manager()
        mgr.container_runtime.docker_events.side_effect = RuntimeError("Docker API error")

        await mgr.start_docker_event_listener()

        assert mgr._running is False

    @pytest.mark.asyncio
    @patch("use_cases.dedicated_nic_manager.asyncio.sleep", new_callable=AsyncMock)
    async def test_poll_stops_when_not_running(self, mock_sleep):
        """Polling thread stops when _running is set to False."""
        mgr = _make_manager()

        def _fake_events(**kwargs):
            # Yield one event, then the loop should check _running
            mgr._running = False
            return iter([{"Actor": {"Attributes": {"name": "rt1"}}}])

        mgr.container_runtime.docker_events.side_effect = _fake_events
        mgr.dedicated_nic_repo.load_config.return_value = None

        await mgr.start_docker_event_listener()

        assert mgr._events_generator is None


class TestStart:
    @pytest.mark.asyncio
    async def test_resyncs_and_creates_listener_task(self):
        """start() calls resync and creates the event listener task."""
        mgr = _make_manager()

        with patch.object(mgr, "start_docker_event_listener", new_callable=AsyncMock) as mock_listener:
            mock_listener.return_value = None

            with patch("use_cases.dedicated_nic_manager.asyncio.create_task") as mock_create_task:
                mock_task = MagicMock()
                mock_create_task.return_value = mock_task

                with patch.object(mgr, "resync_nics_for_existing_containers", new_callable=AsyncMock) as mock_resync:
                    await mgr.start()

                    mock_resync.assert_awaited_once()
                    mock_create_task.assert_called_once()
                    assert mgr._event_listener_task is mock_task


class TestStop:
    @pytest.mark.asyncio
    async def test_cancels_running_task(self):
        """stop() cancels a running event listener task."""
        mgr = _make_manager()
        mgr._running = True

        # Create a real task that blocks forever so it's not done
        async def _block_forever():
            await asyncio.Future()  # never completes

        task = asyncio.create_task(_block_forever())
        mgr._event_listener_task = task

        await mgr.stop()

        assert mgr._running is False
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_closes_events_generator(self):
        """stop() closes the events generator if present."""
        mgr = _make_manager()
        mgr._running = True
        mock_generator = MagicMock()
        mgr._events_generator = mock_generator
        mgr._event_listener_task = None

        await mgr.stop()

        mock_generator.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_swallows_generator_close_exception(self):
        """stop() swallows exceptions from generator.close()."""
        mgr = _make_manager()
        mgr._running = True
        mock_generator = MagicMock()
        mock_generator.close.side_effect = RuntimeError("close failed")
        mgr._events_generator = mock_generator
        mgr._event_listener_task = None

        await mgr.stop()

        assert mgr._running is False

    @pytest.mark.asyncio
    async def test_no_task_no_op(self):
        """stop() with no task is a no-op."""
        mgr = _make_manager()
        mgr._running = True
        mgr._event_listener_task = None

        await mgr.stop()

        assert mgr._running is False

    @pytest.mark.asyncio
    async def test_already_done_task_not_cancelled(self):
        """stop() does not cancel a task that is already done."""
        mgr = _make_manager()
        mgr._running = True
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mgr._event_listener_task = mock_task

        await mgr.stop()

        mock_task.cancel.assert_not_called()
