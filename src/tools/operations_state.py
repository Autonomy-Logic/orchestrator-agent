"""
Thread-safe operations state tracker for container create/delete operations.

This module tracks the state of ongoing container operations (creating, deleting)
to provide accurate status information via get_device_status topic.
"""

import threading
from datetime import datetime
from typing import Dict, Optional, Tuple


def begin_operation(container_name, set_fn, *, operations_state):
    """Check no operation is in progress and set the new state.
    Returns (error_dict, False) on failure, (None, True) on success."""
    in_progress, operation_type = operations_state.is_operation_in_progress(container_name)
    if in_progress:
        return {
            "status": "error",
            "error": f"Container {container_name} already has a {operation_type} operation in progress",
        }, False
    if not set_fn(container_name):
        return {
            "status": "error",
            "error": f"Failed to start operation for {container_name}",
        }, False
    return None, True


class OperationsStateTracker:
    """
    Thread-safe tracker for container operations state.

    Tracks operations like 'creating' and 'deleting' with optional step information,
    errors, and timestamps. Uses threading.Lock for thread safety since operations
    run in background threads via asyncio.to_thread().
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._operations: Dict[str, Dict] = {}

    def set_creating(self, container_name: str) -> bool:
        """
        Mark a container as being created.

        Returns:
            True if state was set successfully
            False if container already has an active operation in progress
        """
        with self._lock:
            if container_name in self._operations:
                # Only block if there's an active operation in progress
                # Allow overwriting error/terminal states with new operation
                current_status = self._operations[container_name].get("status")
                if current_status in ["creating", "deleting"]:
                    return False

            now = datetime.now().isoformat()
            self._operations[container_name] = {
                "status": "creating",
                "operation": "create",
                "step": None,
                "error": None,
                "started_at": now,
                "updated_at": now,
            }
            return True

    def set_deleting(self, container_name: str) -> bool:
        """
        Mark a container as being deleted.

        Returns:
            True if state was set successfully
            False if container already has an active operation in progress
        """
        with self._lock:
            if container_name in self._operations:
                # Only block if there's an active operation in progress
                # Allow overwriting error/terminal states with new operation
                current_status = self._operations[container_name].get("status")
                if current_status in ["creating", "deleting"]:
                    return False

            now = datetime.now().isoformat()
            self._operations[container_name] = {
                "status": "deleting",
                "operation": "delete",
                "step": None,
                "error": None,
                "started_at": now,
                "updated_at": now,
            }
            return True

    def set_step(self, container_name: str, step: str):
        """
        Update the current step of an ongoing operation.

        Args:
            container_name: Name of the container
            step: Description of the current step (e.g., "pulling_image", "creating_container")
        """
        with self._lock:
            if container_name in self._operations:
                self._operations[container_name]["step"] = step
                self._operations[container_name][
                    "updated_at"
                ] = datetime.now().isoformat()

    def set_error(self, container_name: str, error: str, operation: str = None):
        """
        Mark an operation as failed with an error message.

        Args:
            container_name: Name of the container
            error: Error message
            operation: Operation type ('create' or 'delete'), optional
        """
        with self._lock:
            now = datetime.now().isoformat()

            if container_name in self._operations:
                self._operations[container_name]["status"] = "error"
                self._operations[container_name]["error"] = error
                self._operations[container_name]["updated_at"] = now
            else:
                self._operations[container_name] = {
                    "status": "error",
                    "operation": operation or "unknown",
                    "step": None,
                    "error": error,
                    "started_at": now,
                    "updated_at": now,
                }

    def clear_state(self, container_name: str):
        """
        Clear the operation state for a container (called on successful completion).

        Args:
            container_name: Name of the container
        """
        with self._lock:
            if container_name in self._operations:
                del self._operations[container_name]

    def get_state(self, container_name: str) -> Optional[Dict]:
        """
        Get the current operation state for a container.

        Returns:
            Dict with operation state or None if no operation is tracked
        """
        with self._lock:
            if container_name in self._operations:
                return self._operations[container_name].copy()
            return None

    def is_operation_in_progress(
        self, container_name: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an operation is in progress for a container.

        Returns:
            Tuple of (is_in_progress, operation_type)
        """
        with self._lock:
            if container_name in self._operations:
                op = self._operations[container_name]
                if op["status"] in ["creating", "deleting"]:
                    return True, op["operation"]
            return False, None


