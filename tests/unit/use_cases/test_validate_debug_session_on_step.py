"""Tests for the on_step callback in validate_debug_session."""

from unittest.mock import MagicMock, call

import pytest

from use_cases.debug_client.validate_session import validate_debug_session


def _make_deps():
    """Create mocked dependencies for validate_debug_session."""
    http_client = MagicMock()
    debug_socket = MagicMock()
    return http_client, debug_socket


def _auth_ok(http_client, token="jwt-token-123"):
    """Configure http_client to return a successful login response."""
    http_client.make_request.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {"access_token": token},
    }


def _debug_response(hex_data):
    """Build a successful debug_response dict."""
    return {"success": True, "data": hex_data}


# ---------------------------------------------------------------------------
# on_step callback
# ---------------------------------------------------------------------------


class TestOnStepCallback:
    def test_on_step_called_for_each_command(self):
        """With variables present, on_step is called 3 times (MD5, INFO, GET_LIST)."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            _debug_response("45 7E 61 62 63 64"),       # MD5
            _debug_response("41 00 05"),                  # INFO with 5 variables
            _debug_response("44 7E 00 02 00 00 00 42"),  # GET_LIST
        ]

        on_step = MagicMock()
        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket, on_step=on_step,
        )

        assert on_step.call_count == 3

    def test_on_step_called_twice_when_no_variables(self):
        """With 0 variables, on_step is called 2 times (MD5, INFO only)."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            _debug_response("45 7E 61 62 63 64"),  # MD5
            _debug_response("41 00 00"),             # INFO with 0 variables
        ]

        on_step = MagicMock()
        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket, on_step=on_step,
        )

        assert on_step.call_count == 2

    def test_on_step_receives_step_dict(self):
        """The dict passed to on_step has command, raw_request, raw_response, parsed keys."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            _debug_response("45 7E 61 62 63 64"),  # MD5
            _debug_response("41 00 00"),             # INFO with 0 variables
        ]

        on_step = MagicMock()
        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket, on_step=on_step,
        )

        step = on_step.call_args_list[0][0][0]
        assert "command" in step
        assert "raw_request" in step
        assert "raw_response" in step
        assert "parsed" in step
        assert step["command"] == "DEBUG_GET_MD5"

    def test_on_step_not_called_on_auth_failure(self):
        """When authentication fails, on_step is never called."""
        http_client, debug_socket = _make_deps()
        http_client.make_request.return_value = {
            "ok": False,
            "status_code": 401,
            "body": "Unauthorized",
        }

        on_step = MagicMock()
        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket, on_step=on_step,
        )

        on_step.assert_not_called()

    def test_on_step_none_is_safe(self):
        """Default on_step=None doesn't break anything (backward compat)."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            _debug_response("45 7E 61 62 63 64"),
            _debug_response("41 00 05"),
            _debug_response("44 7E 00 02 00 00 00 42"),
        ]

        # Should not raise — on_step defaults to None
        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "success"
        assert len(result["steps"]) == 3

    def test_on_step_called_even_when_command_errors(self):
        """When send_command raises, on_step is still called with error in step."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = TimeoutError("no response")

        on_step = MagicMock()
        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket, on_step=on_step,
        )

        # MD5 command errors, on_step still called with the error step
        assert on_step.call_count >= 1
        step = on_step.call_args_list[0][0][0]
        assert step["error"] == "no response"
        assert step["raw_response"] is None
