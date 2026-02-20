"""
Debug Channel Handler

Manages a dedicated 'debug' WebRTC DataChannel for bridging the OpenPLC
debug protocol from the browser to a runtime container.

Supports persistent debug sessions: the browser can start a session,
send arbitrary debug commands, and stop the session when done.

Message Protocol:
    Browser -> Agent:
        {"type": "debug_start", "device_id": "plc1", "username": "dev", "password": "dev", "port": 8443}
        {"type": "debug_get_md5"}
        {"type": "debug_get_list", "indexes": [0, 1, 2, ...]}
        {"type": "debug_set", "index": 42, "force": true, "value": "01"}
        {"type": "debug_stop"}

    Agent -> Browser:
        {"type": "debug_ready"}
        {"type": "debug_connected"}
        {"type": "debug_md5_response", "md5": "abc123..."}
        {"type": "debug_values_response", "tick": 12345, "data": "00 01 FF ..."}
        {"type": "debug_set_response", "success": true}
        {"type": "debug_disconnected"}
        {"type": "debug_error", "error": "...message..."}
"""

from tools.logger import log_info, log_debug, log_error
from use_cases.debug_client.run_debug_command import run_debug_command
import json
import asyncio


class DebugChannelHandler:
    """
    Handles a 'debug'-labeled WebRTC DataChannel.

    Supports persistent sessions: on debug_start, authenticates and connects
    to the runtime. Subsequent commands are forwarded over the persistent
    Socket.IO connection. debug_stop disconnects cleanly.
    """

    def __init__(self, data_channel, session_id, session_manager, client_registry,
                 *, http_client_factory, debug_socket_factory):
        """
        Initialize debug channel handler.

        Args:
            data_channel: RTCDataChannel instance (label='debug')
            session_id: Associated WebRTC session ID
            session_manager: WebRTCSessionManager instance
            client_registry: ClientRepo instance for device IP lookups
            http_client_factory: Callable returning an HTTPClientRepo instance
            debug_socket_factory: Callable returning a DebugSocketRepo instance
        """
        self.channel = data_channel
        self.session_id = session_id
        self.session_manager = session_manager
        self.client_registry = client_registry
        self._http_client_factory = http_client_factory
        self._debug_socket_factory = debug_socket_factory
        self._closed = False
        self._command_lock = asyncio.Lock()

        # Persistent session state
        self._debug_socket = None
        self._connected = False

        self._setup_handlers()

    def _setup_handlers(self):
        """Set up debug data channel event handlers."""
        log_info(f"Setting up debug channel handlers for session {self.session_id}")

        @self.channel.on("open")
        def on_open():
            log_info(f"Debug channel OPEN for session {self.session_id}")
            self._send_message({"type": "debug_ready"})

        @self.channel.on("close")
        def on_close():
            log_info(f"Debug channel CLOSED for session {self.session_id}")
            self.close()

        @self.channel.on("error")
        def on_error(error):
            log_error(f"Debug channel ERROR for session {self.session_id}: {error}")

        @self.channel.on("message")
        def on_message(message):
            asyncio.create_task(self._handle_message(message))

    async def _handle_message(self, raw_message):
        """Handle incoming debug channel message."""
        if self._closed:
            return

        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")

            message = json.loads(raw_message)
            msg_type = message.get("type")

            if self.session_manager:
                self.session_manager.touch_session(self.session_id)

            if msg_type == "debug_start":
                await self._handle_start(message)
            elif msg_type == "debug_stop":
                await self._handle_stop()
            elif msg_type in ("debug_get_md5", "debug_get_list", "debug_set", "debug_info"):
                await self._handle_command(message)
            else:
                log_debug(f"Unknown debug channel message type: {msg_type}")
                self._send_message({
                    "type": "debug_error",
                    "error": f"Unknown message type: {msg_type}",
                })

        except json.JSONDecodeError as e:
            log_error(f"Invalid JSON on debug channel {self.session_id}: {e}")
            self._send_message({
                "type": "debug_error",
                "error": f"Invalid JSON: {e}",
            })
        except Exception as e:
            log_error(f"Error handling debug channel message {self.session_id}: {e}")
            self._send_message({"type": "debug_error", "error": str(e)})

    async def _handle_start(self, message):
        """
        Handle debug_start message.

        Authenticates with the runtime, creates a persistent Socket.IO
        connection, and sends debug_connected response.
        """
        # If already connected, disconnect first
        if self._connected:
            self._disconnect_debug_socket()

        device_id = message.get("device_id")
        username = message.get("username", "dev")
        password = message.get("password", "dev")
        port = message.get("port", 8443)

        log_info(f"Debug session requested for device {device_id}")

        # Look up device IP
        client = self.client_registry.get_client(device_id)
        if not client:
            self._send_message({
                "type": "debug_error",
                "error": f"Device {device_id} not found",
            })
            return

        device_ip = client["ip"]
        log_info(f"Starting persistent debug session for {device_id} at {device_ip}:{port}")

        try:
            # Step 1: Authenticate
            http_client = self._http_client_factory()
            auth_response = await asyncio.to_thread(
                http_client.make_request,
                "POST",
                device_ip,
                port,
                "api/login",
                {"json": {"username": username, "password": password}},
            )

            if not auth_response.get("ok"):
                self._send_message({
                    "type": "debug_error",
                    "error": f"Authentication failed: HTTP {auth_response.get('status_code')}",
                })
                return

            body = auth_response.get("body", {})
            token = body.get("access_token") if isinstance(body, dict) else None
            if not token:
                self._send_message({
                    "type": "debug_error",
                    "error": "No access_token in login response",
                })
                return

            log_info("Debug session: authentication successful")

            # Step 2: Connect Socket.IO
            url = f"https://{device_ip}:{port}"
            debug_socket = self._debug_socket_factory()

            await asyncio.to_thread(debug_socket.connect, url, token, 10.0)

            self._debug_socket = debug_socket
            self._connected = True

            log_info(f"Debug session: Socket.IO connected for {device_id}")
            self._send_message({"type": "debug_connected"})

        except Exception as e:
            log_error(f"Debug session start failed for {device_id}: {e}")
            self._send_message({
                "type": "debug_error",
                "error": str(e),
            })

    async def _handle_command(self, message):
        """
        Handle a debug command (get_md5, get_list, set, info).

        Forwards the command to the runtime via the persistent Socket.IO
        connection and sends the response back to the browser.
        Commands are serialized per session via _command_lock.
        """
        async with self._command_lock:
            await self._handle_command_inner(message)

    async def _handle_command_inner(self, message):
        """Inner command handler, called under _command_lock."""
        if not self._connected or not self._debug_socket:
            self._send_message({
                "type": "debug_error",
                "error": "No active debug session. Send debug_start first.",
            })
            return

        msg_type = message.get("type")

        # Map message type to command_type for run_debug_command
        command_map = {
            "debug_get_md5": "get_md5",
            "debug_get_list": "get_list",
            "debug_set": "set",
            "debug_info": "info",
        }
        command_type = command_map.get(msg_type)

        # Build params from the message
        params = {}
        if command_type == "get_list":
            params["indexes"] = message.get("indexes", [])
        elif command_type == "set":
            params["index"] = message.get("index")
            params["force"] = message.get("force", True)
            params["value"] = message.get("value", "00")

        try:
            result = await asyncio.to_thread(
                run_debug_command,
                command_type,
                params,
                self._debug_socket,
            )

            if result.get("success"):
                data = result.get("data", {})

                # Check for protocol-level errors (non-SUCCESS status)
                sname = data.get("status_name", "")
                if sname and sname != "SUCCESS":
                    self._send_message({
                        "type": "debug_error",
                        "error": sname,
                    })
                elif command_type == "get_md5":
                    self._send_message({
                        "type": "debug_md5_response",
                        "md5": data.get("md5", ""),
                    })
                elif command_type == "get_list":
                    self._send_message({
                        "type": "debug_values_response",
                        "tick": data.get("tick", 0),
                        "data": data.get("variable_data_hex", ""),
                    })
                elif command_type == "set":
                    self._send_message({
                        "type": "debug_set_response",
                        "success": True,
                    })
                elif command_type == "info":
                    self._send_message({
                        "type": "debug_info_response",
                        "variable_count": data.get("variable_count", 0),
                    })
            else:
                self._send_message({
                    "type": "debug_error",
                    "error": result.get("error", "Unknown error"),
                })

        except Exception as e:
            log_error(f"Debug command {msg_type} failed: {e}")
            self._send_message({
                "type": "debug_error",
                "error": str(e),
            })

    async def _handle_stop(self):
        """
        Handle debug_stop message.

        Disconnects the Socket.IO connection and clears session state.
        """
        log_info(f"Debug session stop requested for {self.session_id}")
        self._disconnect_debug_socket()
        self._send_message({"type": "debug_disconnected"})

    def _disconnect_debug_socket(self):
        """Disconnect the debug socket and clear session state."""
        if self._debug_socket:
            try:
                self._debug_socket.disconnect()
            except Exception as e:
                log_debug(f"Error disconnecting debug socket: {e}")
            self._debug_socket = None
        self._connected = False

    def _send_message(self, message):
        """Send a JSON message on the debug channel."""
        if self._closed or not self.channel:
            return

        try:
            if self.channel.readyState == "open":
                self.channel.send(json.dumps(message))
            else:
                log_debug(f"Cannot send debug message, channel state: {self.channel.readyState}")
        except Exception as e:
            log_error(f"Error sending debug message in session {self.session_id}: {e}")

    def close(self):
        """Close the debug channel handler and cleanup."""
        if self._closed:
            return

        self._closed = True
        log_info(f"Closing debug channel handler for session {self.session_id}")

        # Disconnect any active debug session
        self._disconnect_debug_socket()

        if self.channel:
            try:
                self.channel.close()
            except Exception as e:
                log_debug(f"Error closing debug channel: {e}")

        log_info(f"Debug channel handler closed for session {self.session_id}")

    @property
    def is_closed(self):
        """Check if handler is closed."""
        return self._closed
