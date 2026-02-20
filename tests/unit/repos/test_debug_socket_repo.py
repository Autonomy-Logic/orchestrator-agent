"""Tests for repos.debug_socket_repo — Socket.IO debug client."""

import threading
from unittest.mock import MagicMock, patch, call

import pytest

from repos.debug_socket_repo import DebugSocketRepo, NAMESPACE


class TestDebugSocketRepoInit:
    def test_initial_state(self):
        repo = DebugSocketRepo()
        assert repo._sio is None
        assert repo._response is None
        assert repo._connected_status is None


class TestConnect:
    @patch("repos.debug_socket_repo.socketio.Client")
    def test_successful_connection(self, mock_client_cls):
        """connect() creates a Client, connects, and waits for 'connected' event."""
        mock_sio = MagicMock()
        mock_client_cls.return_value = mock_sio

        repo = DebugSocketRepo()

        # Simulate the runtime emitting 'connected' event shortly after connect()
        def fake_connect(url, namespaces, auth):
            # The 'on' decorator registered a handler; find it and call it
            repo._connected_status = {"status": "ok"}
            repo._connected_event.set()

        mock_sio.connect.side_effect = fake_connect

        result = repo.connect("https://172.18.0.2:8443", "jwt-token", timeout=2.0)

        mock_client_cls.assert_called_once_with(
            ssl_verify=False, logger=False, engineio_logger=False
        )
        mock_sio.connect.assert_called_once_with(
            "https://172.18.0.2:8443",
            namespaces=[NAMESPACE],
            auth={"token": "jwt-token"},
        )
        assert result == {"status": "ok"}

    @patch("repos.debug_socket_repo.socketio.Client")
    def test_timeout_raises(self, mock_client_cls):
        """connect() raises TimeoutError if 'connected' event never arrives."""
        mock_sio = MagicMock()
        mock_client_cls.return_value = mock_sio
        mock_sio.connected = False

        repo = DebugSocketRepo()

        with pytest.raises(TimeoutError, match="connected"):
            repo.connect("https://172.18.0.2:8443", "jwt-token", timeout=0.1)

        # Should have cleaned up after timeout
        assert repo._sio is None

    @patch("repos.debug_socket_repo.socketio.Client")
    def test_connect_exception_propagates(self, mock_client_cls):
        """connect() propagates Socket.IO connection exceptions."""
        mock_sio = MagicMock()
        mock_client_cls.return_value = mock_sio
        mock_sio.connect.side_effect = ConnectionError("refused")

        repo = DebugSocketRepo()

        with pytest.raises(ConnectionError, match="refused"):
            repo.connect("https://172.18.0.2:8443", "jwt-token", timeout=1.0)


class TestSendCommand:
    def _make_connected_repo(self):
        """Create a repo with a mocked connected Socket.IO client."""
        repo = DebugSocketRepo()
        repo._sio = MagicMock()
        repo._sio.connected = True
        return repo

    def test_successful_send_and_receive(self):
        """send_command() emits the command and returns the response."""
        repo = self._make_connected_repo()
        expected_response = {"success": True, "data": "41 00 05"}

        # Simulate response arriving shortly after emit
        def fake_emit(event, data, namespace):
            repo._response = expected_response
            repo._response_event.set()

        repo._sio.emit.side_effect = fake_emit

        result = repo.send_command("41", timeout=2.0)

        repo._sio.emit.assert_called_once_with(
            "debug_command", {"command": "41"}, namespace=NAMESPACE
        )
        assert result == expected_response

    def test_timeout_raises(self):
        """send_command() raises TimeoutError if no response arrives."""
        repo = self._make_connected_repo()

        with pytest.raises(TimeoutError, match="No debug_response"):
            repo.send_command("41", timeout=0.1)

    def test_not_connected_raises(self):
        """send_command() raises RuntimeError if not connected."""
        repo = DebugSocketRepo()

        with pytest.raises(RuntimeError, match="Not connected"):
            repo.send_command("41")

    def test_disconnected_client_raises(self):
        """send_command() raises RuntimeError if client exists but is disconnected."""
        repo = DebugSocketRepo()
        repo._sio = MagicMock()
        repo._sio.connected = False

        with pytest.raises(RuntimeError, match="Not connected"):
            repo.send_command("41")

    def test_clears_previous_response(self):
        """send_command() clears state from previous call before emitting."""
        repo = self._make_connected_repo()
        repo._response = {"stale": True}
        repo._response_event.set()

        new_response = {"success": True, "data": "45 7E"}

        def fake_emit(event, data, namespace):
            # After clearing, set the new response
            repo._response = new_response
            repo._response_event.set()

        repo._sio.emit.side_effect = fake_emit

        result = repo.send_command("45 DE AD 00 00", timeout=2.0)
        assert result == new_response


class TestDisconnect:
    def test_disconnect_connected_client(self):
        """disconnect() calls sio.disconnect() and clears state."""
        repo = DebugSocketRepo()
        mock_sio = MagicMock()
        mock_sio.connected = True
        repo._sio = mock_sio

        repo.disconnect()

        mock_sio.disconnect.assert_called_once()

    def test_disconnect_when_not_connected(self):
        """disconnect() is safe when _sio is None."""
        repo = DebugSocketRepo()
        repo._sio = None

        repo.disconnect()  # Should not raise

    def test_disconnect_clears_sio(self):
        """disconnect() sets _sio to None."""
        repo = DebugSocketRepo()
        repo._sio = MagicMock()
        repo._sio.connected = True

        repo.disconnect()
        assert repo._sio is None

    def test_disconnect_exception_swallowed(self):
        """disconnect() swallows exceptions from sio.disconnect()."""
        repo = DebugSocketRepo()
        repo._sio = MagicMock()
        repo._sio.connected = True
        repo._sio.disconnect.side_effect = Exception("socket error")

        repo.disconnect()  # Should not raise
        assert repo._sio is None

    def test_disconnect_already_disconnected_client(self):
        """disconnect() does not call sio.disconnect() if already disconnected."""
        repo = DebugSocketRepo()
        mock_sio = MagicMock()
        mock_sio.connected = False
        repo._sio = mock_sio

        repo.disconnect()

        mock_sio.disconnect.assert_not_called()
        assert repo._sio is None


class TestEventHandlerRegistration:
    @patch("repos.debug_socket_repo.socketio.Client")
    def test_registers_four_event_handlers(self, mock_client_cls):
        """connect() registers handlers for connected, debug_response, connect_error, disconnect."""
        mock_sio = MagicMock()
        mock_client_cls.return_value = mock_sio

        repo = DebugSocketRepo()

        # Make connect succeed immediately
        def fake_connect(url, namespaces, auth):
            repo._connected_status = {"status": "ok"}
            repo._connected_event.set()

        mock_sio.connect.side_effect = fake_connect

        repo.connect("https://1.2.3.4:8443", "token", timeout=1.0)

        # Check that .on() was called for each event
        on_calls = mock_sio.on.call_args_list
        events_registered = [c[0][0] for c in on_calls]
        assert "connected" in events_registered
        assert "debug_response" in events_registered
        assert "connect_error" in events_registered
        assert "disconnect" in events_registered

        # All in the correct namespace
        for c in on_calls:
            assert c[1].get("namespace") == NAMESPACE or c[0][1] == NAMESPACE
