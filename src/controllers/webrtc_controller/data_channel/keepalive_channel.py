"""
Keepalive Data Channel

Manages WebRTC data channel lifecycle, connection keep-alive, and command execution.
Handles ping/pong messages to maintain session activity and run_command messages
to execute HTTP commands on runtime containers.
"""

from tools.logger import log_info, log_debug, log_error
import json
import asyncio
from typing import Optional


# Interval between keep-alive pings (seconds)
PING_INTERVAL = 30


class KeepaliveChannel:
    """
    Manages a WebRTC data channel for connection keep-alive and command execution.

    Message Protocol:
        Ping/Pong (bidirectional):
            {"type": "ping"}
            {"type": "pong"}

        Control:
            {"type": "ready"}  # Sent when channel is ready
            {"type": "close"}  # Request to close the channel

        Commands (browser -> agent):
            {"type": "run_command", "correlation_id": 12345, "device_id": "...", "method": "GET", ...}

        Command Response (agent -> browser):
            {"type": "command_response", "correlation_id": 12345, "status": "success", "http_response": {...}}
    """

    def __init__(self, data_channel, session_id: str, session_manager=None):
        """
        Initialize keepalive channel.

        Args:
            data_channel: RTCDataChannel instance
            session_id: Associated WebRTC session ID
            session_manager: WebRTCSessionManager instance (optional)
        """
        self.channel = data_channel
        self.session_id = session_id
        self.session_manager = session_manager
        self._closed = False
        self._ready = False
        self._ping_task: Optional[asyncio.Task] = None
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up data channel event handlers."""
        log_info(f"Setting up data channel handlers for session {self.session_id}")
        log_info(f"Initial channel state: {self.channel.readyState}")

        @self.channel.on("open")
        def on_open():
            log_info(f"========== Data Channel OPEN ==========")
            log_info(f"Session: {self.session_id}")
            log_info(f"Channel state: {self.channel.readyState}")
            self._ready = True
            # Notify browser that we're ready
            log_info(f"Sending 'ready' message to browser")
            self._send_message({"type": "ready"})
            # Update session state if manager available
            if self.session_manager:
                from .. import SessionState
                self.session_manager.update_session_state(self.session_id, SessionState.CONNECTED)
            # Start periodic ping task
            log_info(f"Starting ping loop")
            self._ping_task = asyncio.create_task(self._ping_loop())

        @self.channel.on("close")
        def on_close():
            log_info(f"========== Data Channel CLOSED ==========")
            log_info(f"Session: {self.session_id}")
            self._ready = False
            self.close()

        @self.channel.on("error")
        def on_error(error):
            log_error(f"========== Data Channel ERROR ==========")
            log_error(f"Session: {self.session_id}")
            log_error(f"Error: {error}")

        @self.channel.on("message")
        def on_message(message):
            asyncio.create_task(self._handle_message(message))

    async def _ping_loop(self):
        """Send periodic pings to keep connection alive."""
        try:
            while not self._closed:
                await asyncio.sleep(PING_INTERVAL)
                if not self._closed and self._ready:
                    self._send_message({"type": "ping"})
                    log_debug(f"Sent ping for session {self.session_id}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log_error(f"Error in ping loop for session {self.session_id}: {e}")

    async def _handle_message(self, raw_message):
        """
        Handle incoming data channel message.

        Args:
            raw_message: Raw message (string or bytes)
        """
        if self._closed:
            return

        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")

            message = json.loads(raw_message)
            msg_type = message.get("type")

            # Update session activity
            if self.session_manager:
                self.session_manager.touch_session(self.session_id)

            if msg_type == "ping":
                self._send_message({"type": "pong"})
                log_debug(f"Responded to ping for session {self.session_id}")
            elif msg_type == "pong":
                # Keep-alive acknowledgment received
                log_debug(f"Received pong for session {self.session_id}")
            elif msg_type == "close":
                log_info(f"Close request received for session {self.session_id}")
                self.close()
            elif msg_type == "run_command":
                await self._handle_run_command(message)
            else:
                log_debug(f"Unknown message type for session {self.session_id}: {msg_type}")

        except json.JSONDecodeError as e:
            log_error(f"Invalid JSON message in session {self.session_id}: {e}")
        except Exception as e:
            log_error(f"Error handling message in session {self.session_id}: {e}")

    async def _handle_run_command(self, message: dict):
        """
        Handle run_command message - execute HTTP command on runtime container.

        Uses the same execution logic as the WebSocket run_command handler.

        Args:
            message: Command message with device_id, method, api, etc.
        """
        from use_cases.runtime_commands import run_command
        from use_cases.docker_manager import CLIENTS

        correlation_id = message.get("correlation_id")
        device_id = message.get("device_id")
        method = message.get("method")
        api = message.get("api")

        log_info(f"WebRTC run_command for device {device_id}: {method} {api}")

        # Validate device exists
        instance = CLIENTS.get(device_id)
        if not instance:
            log_error(f"Device not found: {device_id}")
            self._send_message({
                "type": "command_response",
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Device not found: {device_id}",
            })
            return

        try:
            # Build command object for run_command.execute
            command = {
                "method": method,
                "api": api,
                "port": message.get("port", 8443),
                "headers": message.get("headers", {}),
                "data": message.get("data"),
                "params": message.get("params"),
                "files": message.get("files"),
            }

            # Execute the HTTP request
            http_response = run_command.execute(instance, command)
            log_info(f"WebRTC command completed with status {http_response.get('status_code')}")

            # Return response with correlation_id
            self._send_message({
                "type": "command_response",
                "correlation_id": correlation_id,
                "status": "success" if http_response.get("ok") else "error",
                "http_response": http_response,
            })
        except Exception as e:
            log_error(f"Error executing WebRTC command: {e}")
            self._send_message({
                "type": "command_response",
                "correlation_id": correlation_id,
                "status": "error",
                "error": str(e),
            })

    def _send_message(self, message: dict):
        """
        Send message to browser via data channel.

        Args:
            message: Message dict to send as JSON
        """
        if self._closed or not self.channel:
            return

        try:
            if self.channel.readyState == "open":
                self.channel.send(json.dumps(message))
            else:
                log_debug(f"Cannot send message, channel state: {self.channel.readyState}")
        except Exception as e:
            log_error(f"Error sending message in session {self.session_id}: {e}")

    def close(self):
        """Close the channel and cleanup resources."""
        if self._closed:
            return

        self._closed = True
        self._ready = False

        log_info(f"Closing keepalive channel for session {self.session_id}")

        # Cancel ping task
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None

        # Close the data channel
        if self.channel:
            try:
                self.channel.close()
            except Exception as e:
                log_debug(f"Error closing data channel: {e}")

        log_info(f"Keepalive channel closed for session {self.session_id}")

    @property
    def is_ready(self) -> bool:
        """Check if channel is ready."""
        return self._ready and not self._closed

    @property
    def is_closed(self) -> bool:
        """Check if channel is closed."""
        return self._closed
