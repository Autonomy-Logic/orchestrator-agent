from unittest.mock import MagicMock

from tools.connection_state import ConnectionStateTracker


class TestConnectionStateTracker:
    def test_initial_state(self):
        tracker = ConnectionStateTracker()
        assert tracker.has_ever_connected is False
        assert tracker.reconnect_attempt == 0

    def test_mark_connected(self):
        tracker = ConnectionStateTracker()
        tracker.mark_connected()
        assert tracker.has_ever_connected is True
        assert tracker.reconnect_attempt == 0

    def test_mark_connected_resets_attempt_counter(self):
        tracker = ConnectionStateTracker()
        tracker.increment_reconnect_attempt()
        tracker.increment_reconnect_attempt()
        assert tracker.reconnect_attempt == 2

        tracker.mark_connected()
        assert tracker.reconnect_attempt == 0

    def test_increment_reconnect_attempt(self):
        tracker = ConnectionStateTracker()
        tracker.increment_reconnect_attempt()
        assert tracker.reconnect_attempt == 1
        tracker.increment_reconnect_attempt()
        assert tracker.reconnect_attempt == 2

    def test_set_heartbeat_task(self):
        tracker = ConnectionStateTracker()
        task = MagicMock()
        tracker.set_heartbeat_task(task)
        # No public accessor for task -- tested via cancel

    def test_cancel_heartbeat_task(self):
        tracker = ConnectionStateTracker()
        task = MagicMock()
        tracker.set_heartbeat_task(task)
        tracker.cancel_heartbeat_task()
        task.cancel.assert_called_once()

    def test_cancel_heartbeat_task_when_none(self):
        tracker = ConnectionStateTracker()
        # Should not raise
        tracker.cancel_heartbeat_task()

    def test_cancel_heartbeat_task_clears_reference(self):
        tracker = ConnectionStateTracker()
        task = MagicMock()
        tracker.set_heartbeat_task(task)
        tracker.cancel_heartbeat_task()
        # Second cancel should not call cancel again
        task.cancel.reset_mock()
        tracker.cancel_heartbeat_task()
        task.cancel.assert_not_called()

    def test_set_heartbeat_task_replaces_previous(self):
        tracker = ConnectionStateTracker()
        task1 = MagicMock()
        task2 = MagicMock()
        tracker.set_heartbeat_task(task1)
        tracker.set_heartbeat_task(task2)
        tracker.cancel_heartbeat_task()
        # Only task2 should be cancelled (task1 was replaced)
        task1.cancel.assert_not_called()
        task2.cancel.assert_called_once()
