"""
Thread-safe connection state tracker for WebSocket reconnection logic.

Tracks whether the orchestrator has ever connected to the backend (to
distinguish initial setup from reconnection), the reconnection attempt
counter, and the active heartbeat task reference.

Follows the same pattern as OperationsStateTracker and DevicesUsageBuffer:
mutable infrastructure state with threading.Lock in src/tools/.
"""

import threading


class ConnectionStateTracker:
    """Track WebSocket connection state for reconnection logic.

    Thread-safe since the heartbeat emitter runs in asyncio.to_thread
    and the connect/disconnect event handlers run on the event loop.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._has_ever_connected = False
        self._reconnect_attempt = 0
        self._heartbeat_task = None

    @property
    def has_ever_connected(self):
        """True once the first successful connection has been established."""
        with self._lock:
            return self._has_ever_connected

    @property
    def reconnect_attempt(self):
        """Current reconnection attempt counter (0-indexed)."""
        with self._lock:
            return self._reconnect_attempt

    def mark_connected(self):
        """Called when a successful connection is established.

        Sets has_ever_connected (switches from initial-setup rapid retry
        to exponential backoff) and resets the reconnect attempt counter.
        """
        with self._lock:
            self._has_ever_connected = True
            self._reconnect_attempt = 0

    def increment_reconnect_attempt(self):
        """Increment the reconnection attempt counter."""
        with self._lock:
            self._reconnect_attempt += 1

    def set_heartbeat_task(self, task):
        """Store the active heartbeat asyncio task."""
        with self._lock:
            self._heartbeat_task = task

    def cancel_heartbeat_task(self):
        """Cancel the active heartbeat task if one exists."""
        with self._lock:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                self._heartbeat_task = None
