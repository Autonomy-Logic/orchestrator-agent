"""Tests for use_cases.debug_client.run_debug_command."""

from unittest.mock import MagicMock

from use_cases.debug_client.run_debug_command import run_debug_command


def _make_socket():
    """Create a mocked DebugSocketRepo."""
    return MagicMock()


def _debug_response(hex_data):
    """Build a successful debug_response dict."""
    return {"success": True, "data": hex_data}


# ---------------------------------------------------------------------------
# get_md5
# ---------------------------------------------------------------------------


class TestGetMd5:
    def test_sends_md5_command(self):
        socket = _make_socket()
        socket.send_command.return_value = _debug_response("45 7E 61 62 63 64")

        result = run_debug_command("get_md5", {}, socket)

        assert result["success"] is True
        assert result["data"]["md5"] == "abcd"
        socket.send_command.assert_called_once()
        hex_cmd = socket.send_command.call_args[0][0]
        assert hex_cmd == "45 DE AD 00 00"

    def test_md5_runtime_error(self):
        socket = _make_socket()
        socket.send_command.return_value = {"success": False, "error": "PLC not running"}

        result = run_debug_command("get_md5", {}, socket)

        assert result["success"] is False
        assert "PLC not running" in result["error"]


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


class TestInfo:
    def test_sends_info_command(self):
        socket = _make_socket()
        socket.send_command.return_value = _debug_response("41 00 0A")

        result = run_debug_command("info", {}, socket)

        assert result["success"] is True
        assert result["data"]["variable_count"] == 10
        hex_cmd = socket.send_command.call_args[0][0]
        assert hex_cmd == "41"


# ---------------------------------------------------------------------------
# get_list
# ---------------------------------------------------------------------------


class TestGetList:
    def test_sends_get_list_command(self):
        socket = _make_socket()
        socket.send_command.return_value = _debug_response(
            "44 7E 00 02 00 00 00 42 00 03 01 02 03"
        )

        result = run_debug_command("get_list", {"indexes": [0, 1, 2]}, socket)

        assert result["success"] is True
        assert result["data"]["tick"] == 66
        assert "variable_data_hex" in result["data"]

    def test_get_list_empty_indexes_returns_error(self):
        socket = _make_socket()

        result = run_debug_command("get_list", {"indexes": []}, socket)

        assert result["success"] is False
        assert "empty" in result["error"]
        socket.send_command.assert_not_called()

    def test_get_list_missing_indexes_returns_error(self):
        socket = _make_socket()

        result = run_debug_command("get_list", {}, socket)

        assert result["success"] is False
        socket.send_command.assert_not_called()


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


class TestSet:
    def test_sends_set_command_force_true(self):
        socket = _make_socket()
        socket.send_command.return_value = _debug_response("42 7E")

        result = run_debug_command(
            "set",
            {"index": 5, "force": True, "value": "01"},
            socket,
        )

        assert result["success"] is True
        hex_cmd = socket.send_command.call_args[0][0]
        data = bytes.fromhex(hex_cmd.replace(" ", ""))
        assert data[0] == 0x42  # FC_DEBUG_SET
        # index = 5 (big-endian 16-bit)
        assert data[1] == 0x00
        assert data[2] == 0x05
        # force = 1
        assert data[3] == 0x01

    def test_set_invalid_index_none(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": None, "value": "01"}, socket)
        assert result["success"] is False
        assert "Invalid index" in result["error"]
        socket.send_command.assert_not_called()

    def test_set_invalid_index_negative(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": -1, "value": "01"}, socket)
        assert result["success"] is False
        assert "Invalid index" in result["error"]

    def test_set_invalid_index_too_large(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": 70000, "value": "01"}, socket)
        assert result["success"] is False
        assert "Invalid index" in result["error"]

    def test_set_invalid_index_string(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": "abc", "value": "01"}, socket)
        assert result["success"] is False
        assert "Invalid index" in result["error"]

    def test_set_invalid_value_hex(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": 5, "value": "ZZ"}, socket)
        assert result["success"] is False
        assert "Invalid value" in result["error"]

    def test_set_value_not_string(self):
        socket = _make_socket()
        result = run_debug_command("set", {"index": 5, "value": 123}, socket)
        assert result["success"] is False
        assert "Invalid value" in result["error"]

    def test_sends_set_command_force_false(self):
        socket = _make_socket()
        socket.send_command.return_value = _debug_response("42 7E")

        result = run_debug_command(
            "set",
            {"index": 3, "force": False, "value": "00"},
            socket,
        )

        assert result["success"] is True
        hex_cmd = socket.send_command.call_args[0][0]
        data = bytes.fromhex(hex_cmd.replace(" ", ""))
        assert data[3] == 0x00  # force = 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_unknown_command_type(self):
        socket = _make_socket()

        result = run_debug_command("unknown_command", {}, socket)

        assert result["success"] is False
        assert "Unknown command type" in result["error"]
        socket.send_command.assert_not_called()

    def test_timeout_error(self):
        socket = _make_socket()
        socket.send_command.side_effect = TimeoutError("no response in 5s")

        result = run_debug_command("get_md5", {}, socket)

        assert result["success"] is False
        assert "Timeout" in result["error"]

    def test_generic_exception(self):
        socket = _make_socket()
        socket.send_command.side_effect = RuntimeError("socket closed")

        result = run_debug_command("get_md5", {}, socket)

        assert result["success"] is False
        assert "socket closed" in result["error"]
