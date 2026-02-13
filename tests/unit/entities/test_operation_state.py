import pytest
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


class TestOperationStateValidation:
    def test_validate_passes_on_valid_data(self):
        state = OperationState(status="creating", operation="create")
        state.validate()  # should not raise

    def test_validate_raises_on_invalid_status(self):
        state = OperationState(status="running", operation="create")
        with pytest.raises(ValueError, match="status"):
            state.validate()

    def test_validate_raises_on_invalid_operation(self):
        state = OperationState(status="creating", operation="update")
        with pytest.raises(ValueError, match="operation"):
            state.validate()

    def test_create_raises_on_invalid_data(self):
        with pytest.raises(ValueError):
            OperationState.create(status="invalid", operation="create")

    def test_create_returns_valid_instance(self):
        state = OperationState.create(status="creating", operation="create")
        assert state.status == "creating"

    def test_from_dict_does_not_validate(self):
        data = {"status": "invalid", "operation": "bad"}
        state = OperationState.from_dict(data)
        assert state.status == "invalid"
