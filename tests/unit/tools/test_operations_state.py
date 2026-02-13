from tools.operations_state import OperationsStateTracker, begin_operation


class TestOperationsStateTracker:
    def test_set_creating(self):
        tracker = OperationsStateTracker()
        assert tracker.set_creating("plc1") is True
        state = tracker.get_state("plc1")
        assert state["status"] == "creating"
        assert state["operation"] == "create"
        assert state["step"] is None
        assert state["error"] is None
        assert state["started_at"] is not None

    def test_set_deleting(self):
        tracker = OperationsStateTracker()
        assert tracker.set_deleting("plc1") is True
        state = tracker.get_state("plc1")
        assert state["status"] == "deleting"
        assert state["operation"] == "delete"

    def test_set_creating_blocked_by_active_creating(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        assert tracker.set_creating("plc1") is False

    def test_set_creating_blocked_by_active_deleting(self):
        tracker = OperationsStateTracker()
        tracker.set_deleting("plc1")
        assert tracker.set_creating("plc1") is False

    def test_set_deleting_blocked_by_active_creating(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        assert tracker.set_deleting("plc1") is False

    def test_set_creating_allowed_after_error(self):
        tracker = OperationsStateTracker()
        tracker.set_error("plc1", "something failed", "create")
        assert tracker.set_creating("plc1") is True
        state = tracker.get_state("plc1")
        assert state["status"] == "creating"

    def test_set_step_updates_state(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        tracker.set_step("plc1", "pulling_image")
        state = tracker.get_state("plc1")
        assert state["step"] == "pulling_image"

    def test_set_step_nonexistent_container(self):
        tracker = OperationsStateTracker()
        # Should not raise
        tracker.set_step("nonexistent", "some_step")

    def test_set_error(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        tracker.set_error("plc1", "Image pull failed")
        state = tracker.get_state("plc1")
        assert state["status"] == "error"
        assert state["error"] == "Image pull failed"

    def test_set_error_creates_new_entry(self):
        tracker = OperationsStateTracker()
        tracker.set_error("plc1", "Unknown failure", "create")
        state = tracker.get_state("plc1")
        assert state["status"] == "error"
        assert state["operation"] == "create"
        assert state["error"] == "Unknown failure"

    def test_set_error_default_operation(self):
        tracker = OperationsStateTracker()
        tracker.set_error("plc1", "failure")
        state = tracker.get_state("plc1")
        assert state["operation"] == "unknown"

    def test_clear_state(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        tracker.clear_state("plc1")
        assert tracker.get_state("plc1") is None

    def test_clear_state_nonexistent(self):
        tracker = OperationsStateTracker()
        # Should not raise
        tracker.clear_state("nonexistent")

    def test_get_state_returns_copy(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        state = tracker.get_state("plc1")
        state["status"] = "modified"
        # Internal state should not be affected
        assert tracker.get_state("plc1")["status"] == "creating"

    def test_get_state_nonexistent(self):
        tracker = OperationsStateTracker()
        assert tracker.get_state("nonexistent") is None

    def test_is_operation_in_progress(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        in_progress, op_type = tracker.is_operation_in_progress("plc1")
        assert in_progress is True
        assert op_type == "create"

    def test_is_operation_not_in_progress_when_error(self):
        tracker = OperationsStateTracker()
        tracker.set_error("plc1", "failed", "create")
        in_progress, op_type = tracker.is_operation_in_progress("plc1")
        assert in_progress is False
        assert op_type is None

    def test_is_operation_not_in_progress_when_cleared(self):
        tracker = OperationsStateTracker()
        in_progress, op_type = tracker.is_operation_in_progress("nonexistent")
        assert in_progress is False
        assert op_type is None


class TestBeginOperation:
    def test_success(self):
        tracker = OperationsStateTracker()
        error, ok = begin_operation("plc1", tracker.set_creating, operations_state=tracker)
        assert ok is True
        assert error is None
        assert tracker.get_state("plc1")["status"] == "creating"

    def test_already_in_progress(self):
        tracker = OperationsStateTracker()
        tracker.set_creating("plc1")
        error, ok = begin_operation("plc1", tracker.set_deleting, operations_state=tracker)
        assert ok is False
        assert error["status"] == "error"
        assert "already has a create operation in progress" in error["error"]

    def test_set_fn_fails(self):
        tracker = OperationsStateTracker()

        def always_fails(name):
            return False

        error, ok = begin_operation("plc1", always_fails, operations_state=tracker)
        assert ok is False
        assert error["status"] == "error"
        assert "Failed to start operation" in error["error"]
