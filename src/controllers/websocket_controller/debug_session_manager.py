"""
Debug Session Manager for HTTP fallback.

Manages persistent DebugSocketRepo connections keyed by device_id,
enabling debug commands to flow through the run_command WebSocket topic
when the WebRTC DataChannel is unavailable.

This is the HTTP-path analog of DebugChannelHandler. The browser wraps
debug messages in run_command with api="debug", and this manager routes
them to the appropriate persistent Socket.IO session with the runtime.

Session lifecycle:
    1. debug_start  → authenticate + connect Socket.IO → debug_connected
    2. debug_get_md5 / debug_get_list / debug_set / debug_info → forward command
    3. debug_stop   → disconnect Socket.IO → debug_disconnected
    4. 5-min inactivity → automatic cleanup
"""

import asyncio
import threading
from datetime import datetime, timezone

from tools.logger import log_info, log_debug, log_error
from use_cases.debug_client.run_debug_command import run_debug_command


class DebugSessionManager:
    """Manages persistent debug sessions for the HTTP (run_command) path."""

    def __init__(self, *, http_client_factory, debug_socket_factory, client_registry):
        self._http_client_factory = http_client_factory
        self._debug_socket_factory = debug_socket_factory
        self._client_registry = client_registry

        # {device_id: {"debug_socket": DebugSocketRepo, "connected": bool, "last_activity": datetime}}
        self._sessions = {}
        self._lock = threading.Lock()
        self._cleanup_task = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self):
        """Start the background cleanup loop."""
        self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())
        log_info("DebugSessionManager started")

    async def stop(self):
        """Cancel cleanup and disconnect all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        with self._lock:
            for device_id in list(self._sessions):
                self._disconnect_session(device_id)
        log_info("DebugSessionManager stopped")

    def handle_debug_message(self, device_id, debug_message):
        """Route a debug message to the appropriate handler.

        Called via asyncio.to_thread from the run_command receiver.

        Args:
            device_id: The runtime container name.
            debug_message: Dict with "type" and command-specific fields.

        Returns:
            Dict response to send back to the browser.
        """
        msg_type = debug_message.get("type", "")

        try:
            if msg_type == "debug_start":
                return self._handle_start(device_id, debug_message)
            elif msg_type == "debug_stop":
                return self._handle_stop(device_id)
            elif msg_type == "debug_command":
                return self._handle_raw_command(device_id, debug_message)
            elif msg_type in ("debug_get_md5", "debug_get_list", "debug_set", "debug_info"):
                return self._handle_command(device_id, debug_message)
            else:
                return {"type": "debug_error", "error": f"Unknown debug message type: {msg_type}"}
        except Exception as e:
            log_error(f"DebugSessionManager error for {device_id}: {e}")
            return {"type": "debug_error", "error": str(e)}

    def forward_raw_command(self, device_id, hex_command):
        """Forward a raw hex Modbus PDU to the runtime and return the raw hex response.

        Used by DebugChannelHandler for binary WebRTC debug commands.

        Args:
            device_id: The runtime container name.
            hex_command: Space-separated hex string (e.g. "44 00 03 00 00 00 01 00 02").

        Returns:
            {"success": True, "data": "44 7E ..."} or
            {"success": False, "error": "..."}
        """
        with self._lock:
            session = self._sessions.get(device_id)
            if not session or not session["connected"]:
                return {"success": False, "error": "No active debug session"}
            session["last_activity"] = datetime.now(timezone.utc)
            debug_socket = session["debug_socket"]
            command_lock = session["command_lock"]

        with command_lock:
            return debug_socket.send_command(hex_command, timeout=5.0)

    # ------------------------------------------------------------------
    # Handlers (run in worker thread via to_thread)
    # ------------------------------------------------------------------

    def _handle_start(self, device_id, message):
        """Authenticate with runtime and establish persistent Socket.IO connection."""
        # Disconnect existing session for this device if any
        with self._lock:
            if device_id in self._sessions:
                self._disconnect_session(device_id)

        username = message.get("username", "dev")
        password = message.get("password", "dev")
        port = message.get("port", 8443)

        log_info(f"HTTP debug session requested for device {device_id}")

        # Look up device IP
        client = self._client_registry.get_client(device_id)
        if not client:
            return {"type": "debug_error", "error": f"Device {device_id} not found"}

        device_ip = client["ip"]
        log_info(f"Starting HTTP debug session for {device_id} at {device_ip}:{port}")

        # Step 1: Authenticate
        http_client = self._http_client_factory()
        auth_response = http_client.make_request(
            "POST",
            device_ip,
            port,
            "api/login",
            {"json": {"username": username, "password": password}},
        )

        if not auth_response.get("ok"):
            return {
                "type": "debug_error",
                "error": f"Authentication failed: HTTP {auth_response.get('status_code')}",
            }

        body = auth_response.get("body", {})
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            return {"type": "debug_error", "error": "No access_token in login response"}

        log_info("HTTP debug session: authentication successful")

        # Step 2: Connect Socket.IO
        url = f"https://{device_ip}:{port}"
        debug_socket = self._debug_socket_factory()
        debug_socket.connect(url, token, 10.0)

        with self._lock:
            self._sessions[device_id] = {
                "debug_socket": debug_socket,
                "connected": True,
                "last_activity": datetime.now(timezone.utc),
                "command_lock": threading.Lock(),
            }

        log_info(f"HTTP debug session: Socket.IO connected for {device_id}")
        return {"type": "debug_connected"}

    def _handle_command(self, device_id, message):
        """Forward a debug command to the runtime via the persistent session."""
        with self._lock:
            session = self._sessions.get(device_id)
            if not session or not session["connected"]:
                return {"type": "debug_error", "error": "No active debug session. Send debug_start first."}
            session["last_activity"] = datetime.now(timezone.utc)
            debug_socket = session["debug_socket"]
            command_lock = session["command_lock"]

        with command_lock:
            return self._execute_command(debug_socket, message)

    def _execute_command(self, debug_socket, message):
        """Execute a debug command under the per-device lock."""
        msg_type = message.get("type")

        command_map = {
            "debug_get_md5": "get_md5",
            "debug_get_list": "get_list",
            "debug_set": "set",
            "debug_info": "info",
        }
        command_type = command_map.get(msg_type)

        params = {}
        if command_type == "get_list":
            params["indexes"] = message.get("indexes", [])
        elif command_type == "set":
            params["index"] = message.get("index")
            params["force"] = message.get("force", True)
            params["value"] = message.get("value", "00")

        result = run_debug_command(command_type, params, debug_socket)

        if result.get("success"):
            data = result.get("data", {})

            # Check for protocol-level errors
            sname = data.get("status_name", "")
            if sname and sname != "SUCCESS":
                return {"type": "debug_error", "error": sname}
            elif command_type == "get_md5":
                return {"type": "debug_md5_response", "md5": data.get("md5", "")}
            elif command_type == "get_list":
                return {
                    "type": "debug_values_response",
                    "tick": data.get("tick", 0),
                    "data": data.get("variable_data_hex", ""),
                }
            elif command_type == "set":
                return {"type": "debug_set_response", "success": True}
            elif command_type == "info":
                return {"type": "debug_info_response", "variable_count": data.get("variable_count", 0)}
        else:
            return {"type": "debug_error", "error": result.get("error", "Unknown error")}

    def _handle_raw_command(self, device_id, message):
        """Forward a raw hex Modbus PDU command via the HTTP/run_command path."""
        hex_command = message.get("command", "")
        if not hex_command:
            return {"type": "debug_error", "error": "Missing 'command' field"}

        result = self.forward_raw_command(device_id, hex_command)

        if result.get("success"):
            return {"type": "debug_command_response", "data": result.get("data", "")}
        else:
            return {"type": "debug_error", "error": result.get("error", "Unknown error")}

    def _handle_stop(self, device_id):
        """Disconnect the Socket.IO session for a device."""
        log_info(f"HTTP debug session stop requested for {device_id}")
        with self._lock:
            self._disconnect_session(device_id)
        return {"type": "debug_disconnected"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _disconnect_session(self, device_id):
        """Disconnect and remove a session. Caller must hold self._lock."""
        session = self._sessions.pop(device_id, None)
        if session and session.get("debug_socket"):
            try:
                session["debug_socket"].disconnect()
            except Exception as e:
                log_debug(f"Error disconnecting HTTP debug session for {device_id}: {e}")

    async def _cleanup_loop(self):
        """Periodically disconnect sessions idle for more than 5 minutes."""
        try:
            while True:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                stale = []

                with self._lock:
                    for device_id, session in self._sessions.items():
                        elapsed = (now - session["last_activity"]).total_seconds()
                        if elapsed > 300:  # 5 minutes
                            stale.append(device_id)

                    for device_id in stale:
                        log_info(f"Cleaning up stale HTTP debug session for {device_id}")
                        self._disconnect_session(device_id)

        except asyncio.CancelledError:
            pass
