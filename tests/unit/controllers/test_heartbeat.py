import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from controllers.websocket_controller.topics.emitters.heartbeat import (
    emit_heartbeat,
    MAX_CONSECUTIVE_FAILURES,
)


def _make_client(connected=True):
    client = MagicMock()
    client.connected = connected
    client.emit = AsyncMock()
    return client


def _mock_metrics():
    return {
        "cpu_usage": 10.0,
        "memory_usage": 0.5,
        "memory_total": 4.0,
        "disk_usage": 20.0,
        "disk_total": 100.0,
        "uptime": 3600,
        "status": "running",
    }


class TestEmitHeartbeat:
    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.collect_all_device_stats")
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.get_all_metrics", return_value=_mock_metrics())
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.sleep", new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.to_thread", new_callable=AsyncMock)
    async def test_heartbeat_includes_agent_version(self, mock_to_thread, mock_sleep, mock_metrics, mock_stats):
        """Heartbeat payload includes agent_version from env var."""
        client = _make_client()
        connected_values = [True, True, False]
        type(client).connected = property(lambda self: connected_values.pop(0) if connected_values else False)

        with patch.dict("os.environ", {"AGENT_VERSION": "v1.2.3"}):
            await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        assert client.emit.call_count == 1
        heartbeat_data = client.emit.call_args[0][1]
        assert heartbeat_data["agent_version"] == "v1.2.3"

    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.collect_all_device_stats")
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.get_all_metrics", return_value=_mock_metrics())
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.sleep", new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.to_thread", new_callable=AsyncMock)
    async def test_emits_heartbeat_successfully(self, mock_to_thread, mock_sleep, mock_metrics, mock_stats):
        """Heartbeat emits and resets failure counter on success."""
        client = _make_client()
        # connected is checked twice per iteration (while + if), plus once for final while
        # 2 iterations = 2*(while+if) + 1 final while = 5 checks
        connected_values = [True, True, True, True, False]
        type(client).connected = property(lambda self: connected_values.pop(0) if connected_values else False)

        await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        assert client.emit.call_count == 2

    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.collect_all_device_stats")
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.get_all_metrics", return_value=_mock_metrics())
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.sleep", new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.to_thread", new_callable=AsyncMock)
    async def test_tolerates_transient_failures(self, mock_to_thread, mock_sleep, mock_metrics, mock_stats):
        """1-2 emit failures should not kill the heartbeat task."""
        client = _make_client()
        # 3 iterations: while+if per iter + final while = 3*2 + 1 = 7 checks
        connected_values = [True, True, True, True, True, True, False]
        type(client).connected = property(lambda self: connected_values.pop(0) if connected_values else False)

        # Fail once, succeed, succeed -- should NOT break after the failure
        client.emit.side_effect = [
            Exception("transient"),
            None,
            None,
        ]

        await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        assert client.emit.call_count == 3

    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.collect_all_device_stats")
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.get_all_metrics", return_value=_mock_metrics())
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.sleep", new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.to_thread", new_callable=AsyncMock)
    async def test_stops_after_max_consecutive_failures(self, mock_to_thread, mock_sleep, mock_metrics, mock_stats):
        """After MAX_CONSECUTIVE_FAILURES, heartbeat task should stop."""
        client = _make_client()
        client.emit.side_effect = Exception("persistent failure")

        await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        assert client.emit.call_count == MAX_CONSECUTIVE_FAILURES

    @pytest.mark.asyncio
    async def test_exits_immediately_if_not_connected(self):
        """If client is not connected, heartbeat should not emit."""
        client = _make_client(connected=False)

        await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        client.emit.assert_not_called()

    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.emitters.heartbeat.asyncio.sleep", new_callable=AsyncMock)
    async def test_exits_when_disconnected_during_sleep(self, mock_sleep):
        """If client disconnects during sleep, heartbeat should exit."""
        client = _make_client()
        # Connected on loop entry, disconnected after sleep
        call_count = 0

        def _connected():
            nonlocal call_count
            call_count += 1
            # First check (while condition): True
            # Second check (after sleep): False
            return call_count <= 1

        type(client).connected = property(lambda self: _connected())

        await emit_heartbeat(client, "agent-1", MagicMock(), MagicMock(), MagicMock())

        client.emit.assert_not_called()


def _make_mock_client_with_handler_capture():
    """Create a mock client that captures handlers registered via @client.on(name).

    Returns (client, handlers_dict) where handlers_dict maps event names
    to the async callback functions registered by topic init().
    """
    handlers = {}
    client = MagicMock()

    def _on_decorator(name):
        def decorator(fn):
            handlers[name] = fn
            return fn
        return decorator

    client.on = _on_decorator
    return client, handlers


class TestConnectHandler:
    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.receivers.connect.emit_heartbeat",
           new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.receivers.connect.get_agent_id",
           return_value="test-agent")
    async def test_marks_connected_and_starts_heartbeat(self, mock_agent_id, mock_heartbeat):
        """Connect handler should call mark_connected() and start heartbeat."""
        from controllers.websocket_controller.topics.receivers.connect import init
        from tools.connection_state import ConnectionStateTracker

        client, handlers = _make_mock_client_with_handler_capture()
        ctx = MagicMock()
        ctx.connection_state = ConnectionStateTracker()
        ctx.usage_buffer = MagicMock()
        ctx.devices_usage_buffer = MagicMock()
        ctx.container_runtime = MagicMock()

        init(client, ctx)
        assert "connect" in handlers

        await handlers["connect"]()

        assert ctx.connection_state.has_ever_connected is True
        assert ctx.connection_state.reconnect_attempt == 0

    @pytest.mark.asyncio
    @patch("controllers.websocket_controller.topics.receivers.connect.emit_heartbeat",
           new_callable=AsyncMock)
    @patch("controllers.websocket_controller.topics.receivers.connect.get_agent_id",
           return_value="test-agent")
    async def test_cancels_orphaned_heartbeat(self, mock_agent_id, mock_heartbeat):
        """Connect handler should cancel previous heartbeat task."""
        from controllers.websocket_controller.topics.receivers.connect import init
        from tools.connection_state import ConnectionStateTracker

        client, handlers = _make_mock_client_with_handler_capture()
        ctx = MagicMock()
        ctx.connection_state = ConnectionStateTracker()
        ctx.usage_buffer = MagicMock()
        ctx.devices_usage_buffer = MagicMock()
        ctx.container_runtime = MagicMock()

        old_task = MagicMock()
        ctx.connection_state.set_heartbeat_task(old_task)

        init(client, ctx)
        await handlers["connect"]()

        old_task.cancel.assert_called_once()


class TestDisconnectHandler:
    @pytest.mark.asyncio
    async def test_cancels_heartbeat_task(self):
        """Disconnect handler should cancel heartbeat task."""
        from controllers.websocket_controller.topics.receivers.disconnect import init
        from tools.connection_state import ConnectionStateTracker

        client, handlers = _make_mock_client_with_handler_capture()
        ctx = MagicMock()
        ctx.connection_state = ConnectionStateTracker()

        task = MagicMock()
        ctx.connection_state.set_heartbeat_task(task)

        init(client, ctx)
        assert "disconnect" in handlers

        await handlers["disconnect"]()

        task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_crash_when_no_heartbeat_task(self):
        """Disconnect handler should not crash if no heartbeat task."""
        from controllers.websocket_controller.topics.receivers.disconnect import init
        from tools.connection_state import ConnectionStateTracker

        client, handlers = _make_mock_client_with_handler_capture()
        ctx = MagicMock()
        ctx.connection_state = ConnectionStateTracker()

        init(client, ctx)
        # Should not raise
        await handlers["disconnect"]()


class TestReconnectionBranching:
    def test_initial_setup_uses_fixed_delay(self):
        """Before first connection, should use INITIAL_SETUP_RETRY_DELAY."""
        from tools.connection_state import ConnectionStateTracker
        from tools.dns_utils import INITIAL_SETUP_RETRY_DELAY, calculate_backoff

        state = ConnectionStateTracker()

        if not state.has_ever_connected:
            delay = INITIAL_SETUP_RETRY_DELAY
        else:
            delay = calculate_backoff(state.reconnect_attempt)

        assert delay == INITIAL_SETUP_RETRY_DELAY

    def test_after_connection_uses_backoff(self):
        """After first connection, should use exponential backoff."""
        from tools.connection_state import ConnectionStateTracker
        from tools.dns_utils import INITIAL_SETUP_RETRY_DELAY, calculate_backoff

        state = ConnectionStateTracker()
        state.mark_connected()

        if not state.has_ever_connected:
            delay = INITIAL_SETUP_RETRY_DELAY
        else:
            delay = calculate_backoff(state.reconnect_attempt)

        assert delay != INITIAL_SETUP_RETRY_DELAY
        assert delay >= 0.7  # RECONNECT_DELAY_BASE with negative jitter

    def test_attempt_counter_not_incremented_during_initial_setup(self):
        """reconnect_attempt should not grow during initial setup."""
        from tools.connection_state import ConnectionStateTracker

        state = ConnectionStateTracker()

        # Simulate 10 iterations of the initial-setup branch
        for _ in range(10):
            if not state.has_ever_connected:
                pass  # No increment in initial setup branch
            else:
                state.increment_reconnect_attempt()

        assert state.reconnect_attempt == 0
