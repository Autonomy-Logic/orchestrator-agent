from entities.operation_state import OperationState


class TestOperationState:
    def test_to_dict(self):
        state = OperationState(
            status="creating",
            operation="create",
            step="pulling_image",
            error=None,
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:01",
        )
        d = state.to_dict()
        assert d["status"] == "creating"
        assert d["operation"] == "create"
        assert d["step"] == "pulling_image"
        assert d["error"] is None
        assert d["started_at"] == "2024-01-01T00:00:00"

    def test_from_dict_ignores_unknown(self):
        data = {
            "status": "error",
            "operation": "delete",
            "unknown_field": "should_be_ignored",
        }
        state = OperationState.from_dict(data)
        assert state.status == "error"
        assert state.operation == "delete"
        assert not hasattr(state, "unknown_field")

    def test_defaults(self):
        state = OperationState(status="creating", operation="create")
        assert state.step is None
        assert state.error is None
        assert state.started_at is None
        assert state.updated_at is None

    def test_roundtrip(self):
        original = OperationState(
            status="deleting",
            operation="delete",
            step="stopping_container",
            error=None,
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:05",
        )
        rebuilt = OperationState.from_dict(original.to_dict())
        assert rebuilt == original
