"""Tests for use_cases.debug_client.validate_session."""

from unittest.mock import MagicMock, call, patch

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
# Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_auth_request_sent_correctly(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.return_value = _debug_response("45 7E 61")

        validate_debug_session(
            "172.18.0.2", "openplc", "secret",
            http_client=http_client, debug_socket=debug_socket,
        )

        http_client.make_request.assert_called_once_with(
            "POST", "172.18.0.2", 8443, "api/login",
            {"json": {"username": "openplc", "password": "secret"}},
        )

    def test_auth_failure_returns_error(self):
        http_client, debug_socket = _make_deps()
        http_client.make_request.return_value = {
            "ok": False,
            "status_code": 401,
            "body": "Wrong username or password",
        }

        result = validate_debug_session(
            "172.18.0.2", "admin", "wrong",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "error"
        assert "401" in result["error"]
        debug_socket.connect.assert_not_called()

    def test_auth_exception_returns_error(self):
        http_client, debug_socket = _make_deps()
        http_client.make_request.side_effect = ConnectionError("refused")

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "error"
        assert "refused" in result["error"]

    def test_no_access_token_returns_error(self):
        http_client, debug_socket = _make_deps()
        http_client.make_request.return_value = {
            "ok": True,
            "status_code": 200,
            "body": {"msg": "no token field"},
        }

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "error"
        assert "access_token" in result["error"]

    def test_body_not_dict_returns_error(self):
        http_client, debug_socket = _make_deps()
        http_client.make_request.return_value = {
            "ok": True,
            "status_code": 200,
            "body": "unexpected string body",
        }

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "error"
        assert "access_token" in result["error"]


# ---------------------------------------------------------------------------
# Socket.IO connection
# ---------------------------------------------------------------------------


class TestSocketConnection:
    def test_connect_called_with_url_and_token(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client, token="my-jwt")
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.return_value = _debug_response("45 7E 61")

        validate_debug_session(
            "10.0.0.1", "user", "pass",
            http_client=http_client, debug_socket=debug_socket, port=9999,
        )

        debug_socket.connect.assert_called_once_with(
            "https://10.0.0.1:9999", "my-jwt", timeout=10.0,
        )

    def test_connect_failure_returns_error(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.side_effect = TimeoutError("timed out")

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "error"
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Debug commands
# ---------------------------------------------------------------------------


class TestDebugCommands:
    def _run_session(self, variable_count=5, send_responses=None):
        """Run a complete validation session with configurable responses."""
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}

        if send_responses is None:
            # Default: MD5 ok, INFO with N variables, GET_LIST ok
            info_count_hi = (variable_count >> 8) & 0xFF
            info_count_lo = variable_count & 0xFF
            send_responses = [
                _debug_response("45 7E 61 62 63 64"),
                _debug_response(f"41 {info_count_hi:02X} {info_count_lo:02X}"),
            ]
            if variable_count > 0:
                send_responses.append(
                    _debug_response("44 7E 00 02 00 00 00 42 00 03 01 02 03")
                )

        debug_socket.send_command.side_effect = send_responses

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )
        return result, debug_socket

    def test_sends_md5_first(self):
        result, debug_socket = self._run_session()
        first_call = debug_socket.send_command.call_args_list[0]
        assert first_call[0][0] == "45 DE AD 00 00"

    def test_sends_info_second(self):
        result, debug_socket = self._run_session()
        second_call = debug_socket.send_command.call_args_list[1]
        assert second_call[0][0] == "41"

    def test_sends_get_list_when_variables_exist(self):
        result, debug_socket = self._run_session(variable_count=5)
        assert debug_socket.send_command.call_count == 3
        third_call = debug_socket.send_command.call_args_list[2]
        hex_cmd = third_call[0][0]
        assert hex_cmd.startswith("44")

    def test_skips_get_list_when_no_variables(self):
        result, debug_socket = self._run_session(variable_count=0)
        assert debug_socket.send_command.call_count == 2

    def test_caps_get_list_at_10_variables(self):
        result, debug_socket = self._run_session(variable_count=100)
        third_call = debug_socket.send_command.call_args_list[2]
        hex_cmd = third_call[0][0]
        data = bytes.fromhex(hex_cmd.replace(" ", ""))
        count = (data[1] << 8) | data[2]
        assert count == 10

    def test_success_result_structure(self):
        result, _ = self._run_session(variable_count=5)
        assert result["status"] == "success"
        assert len(result["steps"]) == 3
        assert result["steps"][0]["command"] == "DEBUG_GET_MD5"
        assert result["steps"][1]["command"] == "DEBUG_INFO"
        assert result["steps"][2]["command"] == "DEBUG_GET_LIST"

    def test_raw_request_preserved_in_steps(self):
        result, _ = self._run_session()
        assert result["steps"][0]["raw_request"] == "45 DE AD 00 00"
        assert result["steps"][1]["raw_request"] == "41"

    def test_raw_response_preserved_in_steps(self):
        result, _ = self._run_session()
        assert result["steps"][0]["raw_response"] == "45 7E 61 62 63 64"

    def test_parsed_md5_in_steps(self):
        result, _ = self._run_session()
        parsed = result["steps"][0]["parsed"]
        assert parsed["md5"] == "abcd"

    def test_parsed_variable_count_in_steps(self):
        result, _ = self._run_session(variable_count=5)
        parsed = result["steps"][1]["parsed"]
        assert parsed["variable_count"] == 5


# ---------------------------------------------------------------------------
# Error handling during commands
# ---------------------------------------------------------------------------


class TestCommandErrors:
    def test_send_command_exception_captured(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = TimeoutError("no response")

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "success"
        assert result["steps"][0]["error"] == "no response"
        assert result["steps"][0]["raw_response"] is None

    @patch("use_cases.debug_client.validate_session.parse_response")
    def test_parse_response_exception_captured(self, mock_parse):
        mock_parse.side_effect = RuntimeError("unexpected parse failure")
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            _debug_response("45 7E 61"),
            _debug_response("41 00 00"),
        ]

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["status"] == "success"
        assert "Parse error" in result["steps"][0]["error"]

    def test_runtime_error_response_captured(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = [
            {"success": False, "error": "PLC not running", "data": ""},
            _debug_response("41 00 00"),
        ]

        result = validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        assert result["steps"][0]["error"] == "PLC not running"


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_called_on_success(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.return_value = _debug_response("45 7E 61")

        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        debug_socket.disconnect.assert_called_once()

    def test_disconnect_called_on_command_exception(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.side_effect = Exception("fatal error")

        validate_debug_session(
            "172.18.0.2", "openplc", "openplc",
            http_client=http_client, debug_socket=debug_socket,
        )

        debug_socket.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Custom port
# ---------------------------------------------------------------------------


class TestCustomPort:
    def test_custom_port_in_auth(self):
        http_client, debug_socket = _make_deps()
        _auth_ok(http_client)
        debug_socket.connect.return_value = {"status": "ok"}
        debug_socket.send_command.return_value = _debug_response("45 7E 61")

        validate_debug_session(
            "10.0.0.1", "user", "pass",
            http_client=http_client, debug_socket=debug_socket, port=9999,
        )

        http_client.make_request.assert_called_once_with(
            "POST", "10.0.0.1", 9999, "api/login",
            {"json": {"username": "user", "password": "pass"}},
        )
