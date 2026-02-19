"""
Socket.IO debug client for connecting to OpenPLC-Runtime containers.

Manages a single debug connection using the synchronous socketio.Client.
Uses threading events to bridge the event-driven Socket.IO callbacks
into a synchronous request-response pattern.
"""

import threading

import socketio

from repos.interfaces import DebugSocketRepoInterface
from tools.logger import log_info, log_debug, log_error, log_warning

NAMESPACE = "/api/debug"


class DebugSocketRepo(DebugSocketRepoInterface):
    """Socket.IO client adapter for one debug session with a runtime container."""

    def __init__(self):
        self._sio = None
        self._connected_event = threading.Event()
        self._connected_status = None
        self._response_event = threading.Event()
        self._response = None
        self._command_lock = threading.Lock()

    def connect(self, url: str, token: str, timeout: float = 5.0) -> dict:
        """Connect to the runtime's /api/debug Socket.IO namespace.

        Args:
            url: Full HTTPS URL of the runtime (e.g. "https://172.18.0.2:8443").
            token: JWT access token obtained from /api/login.
            timeout: Seconds to wait for the 'connected' confirmation event.

        Returns:
            The connection confirmation dict (e.g. {"status": "ok"}).

        Raises:
            TimeoutError: If the runtime does not confirm within timeout.
            Exception: On Socket.IO connection failure.
        """
        self._connected_event.clear()
        self._connected_status = None

        self._sio = socketio.Client(ssl_verify=False, logger=False, engineio_logger=False)

        @self._sio.on("connected", namespace=NAMESPACE)
        def _on_connected(data):
            log_debug(f"Received 'connected' event: {data}")
            self._connected_status = data
            self._connected_event.set()

        @self._sio.on("debug_response", namespace=NAMESPACE)
        def _on_debug_response(data):
            log_debug(f"Received 'debug_response' event: {data}")
            self._response = data
            self._response_event.set()

        @self._sio.on("connect_error", namespace=NAMESPACE)
        def _on_connect_error(data):
            log_error(f"Socket.IO connect_error on {NAMESPACE}: {data}")

        @self._sio.on("disconnect", namespace=NAMESPACE)
        def _on_disconnect():
            log_info(f"Socket.IO disconnected from {NAMESPACE}")

        log_info(f"Connecting to {url}{NAMESPACE}")
        try:
            self._sio.connect(
                url,
                namespaces=[NAMESPACE],
                auth={"token": token},
            )
        except Exception:
            self._safe_disconnect()
            raise

        if not self._connected_event.wait(timeout):
            self._safe_disconnect()
            raise TimeoutError(
                f"Runtime did not send 'connected' confirmation within {timeout}s"
            )

        log_info(f"Debug session connected: {self._connected_status}")
        return self._connected_status

    def send_command(self, hex_command: str, timeout: float = 5.0) -> dict:
        """Send a debug command and wait for the response.

        Args:
            hex_command: Space-separated hex string (e.g. "45 DE AD 00 00").
            timeout: Seconds to wait for the debug_response event.

        Returns:
            Raw response dict from the runtime, e.g.:
            {"success": True, "data": "45 7E ..."} or
            {"success": False, "error": "message"}

        Raises:
            TimeoutError: If no response within timeout.
            RuntimeError: If not connected.
        """
        if self._sio is None or not self._sio.connected:
            raise RuntimeError("Not connected to runtime debug namespace")

        with self._command_lock:
            self._response_event.clear()
            self._response = None

            log_debug(f"Sending debug_command: {hex_command}")
            self._sio.emit("debug_command", {"command": hex_command}, namespace=NAMESPACE)

            if not self._response_event.wait(timeout):
                raise TimeoutError(
                    f"No debug_response received within {timeout}s for command: {hex_command}"
                )

            return self._response

    def disconnect(self) -> None:
        """Disconnect from the runtime debug namespace."""
        self._safe_disconnect()
        log_info("Debug session disconnected")

    def _safe_disconnect(self) -> None:
        """Disconnect without raising on errors."""
        if self._sio is not None:
            try:
                if self._sio.connected:
                    self._sio.disconnect()
            except Exception as e:
                log_warning(f"Error during debug socket disconnect: {e}")
            self._sio = None
