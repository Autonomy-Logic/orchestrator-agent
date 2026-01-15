"""
Terminal Data Channel

Handles terminal I/O over WebRTC data channel.
Bridges data channel messages to PTY sessions on runtime containers.
"""

from tools.logger import log_info, log_debug, log_error, log_warning
import json
import asyncio
from typing import Optional


class TerminalChannel:
    """
    Manages terminal I/O over a WebRTC data channel.

    Message Protocol:
        Input (browser -> agent):
            {"type": "input", "data": "command\\n"}

        Output (agent -> browser):
            {"type": "output", "data": "output text"}

        Resize (browser -> agent):
            {"type": "resize", "cols": 120, "rows": 40}

        Control:
            {"type": "ping"}
            {"type": "pong"}
            {"type": "close"}
            {"type": "ready"}  # Sent when channel is ready for terminal I/O
            {"type": "pty_connected"}  # Sent when PTY is connected
            {"type": "pty_disconnected"}  # Sent when PTY is disconnected
    """

    def __init__(self, data_channel, session_id: str, session_manager=None):
        """
        Initialize terminal channel.

        Args:
            data_channel: RTCDataChannel instance
            session_id: Associated WebRTC session ID
            session_manager: WebRTCSessionManager instance (optional)
        """
        self.channel = data_channel
        self.session_id = session_id
        self.session_manager = session_manager
        self.pty_bridge = None
        self._closed = False
        self._ready = False
        self._device_id: Optional[str] = None
        self._cols = 80
        self._rows = 24
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up data channel event handlers."""

        @self.channel.on("open")
        def on_open():
            log_info(f"Terminal data channel opened for session {self.session_id}")
            self._ready = True
            # Notify browser that we're ready
            self._send_message({"type": "ready"})
            # Update session state if manager available
            if self.session_manager:
                from .. import SessionState
                self.session_manager.update_session_state(self.session_id, SessionState.CONNECTED)
                # Get device_id from session
                session = self.session_manager.get_session(self.session_id)
                if session:
                    self._device_id = session.get("device_id")
                    # Auto-connect to PTY
                    asyncio.create_task(self._auto_connect_pty())

        @self.channel.on("close")
        def on_close():
            log_info(f"Terminal data channel closed for session {self.session_id}")
            self._ready = False
            self.close()  # Cleanup resources

        @self.channel.on("error")
        def on_error(error):
            log_error(f"Terminal data channel error for session {self.session_id}: {error}")

        @self.channel.on("message")
        def on_message(message):
            # Handle message in async context
            asyncio.create_task(self._handle_message(message))

    async def _auto_connect_pty(self):
        """Automatically connect to PTY when channel opens."""
        if not self._device_id:
            log_warning(f"No device_id for session {self.session_id}, cannot auto-connect PTY")
            return

        error = await self.connect_pty(self._device_id, self._cols, self._rows)
        if error:
            self._send_message({
                "type": "error",
                "message": f"Failed to connect PTY: {error}"
            })

    async def connect_pty(self, container_name: str, cols: int = 80, rows: int = 24) -> Optional[str]:
        """
        Connect to a container PTY.

        Args:
            container_name: Target container name
            cols: Terminal columns
            rows: Terminal rows

        Returns:
            Error message if failed, None if successful
        """
        if self.pty_bridge and self.pty_bridge.is_connected:
            return "PTY already connected"

        self._cols = cols
        self._rows = rows

        try:
            # Import here to avoid circular imports
            from use_cases.terminal_pty import PTYBridge

            # Create PTY bridge with output callback
            self.pty_bridge = PTYBridge(
                container_name=container_name,
                output_callback=self.send_output_bytes,
                cols=cols,
                rows=rows,
            )

            # Connect to container
            error = await self.pty_bridge.connect()
            if error:
                self.pty_bridge = None
                return error

            log_info(f"PTY connected for session {self.session_id} to container {container_name}")
            self._send_message({"type": "pty_connected", "container": container_name})
            return None

        except Exception as e:
            log_error(f"Error connecting PTY for session {self.session_id}: {e}")
            self.pty_bridge = None
            return str(e)

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

            if msg_type == "input":
                await self._handle_input(message.get("data", ""))
            elif msg_type == "resize":
                await self._handle_resize(
                    message.get("cols", 80),
                    message.get("rows", 24)
                )
            elif msg_type == "ping":
                self._send_message({"type": "pong"})
            elif msg_type == "close":
                log_info(f"Close request received for session {self.session_id}")
                self.close()
            elif msg_type == "connect_pty":
                # Manual PTY connection request
                container = message.get("container")
                cols = message.get("cols", 80)
                rows = message.get("rows", 24)
                if container:
                    error = await self.connect_pty(container, cols, rows)
                    if error:
                        self._send_error(f"PTY connection failed: {error}")
                else:
                    self._send_error("Container name required for connect_pty")
            else:
                log_debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            log_error(f"Invalid JSON message in session {self.session_id}: {e}")
            self._send_error(f"Invalid JSON: {e}")
        except Exception as e:
            log_error(f"Error handling message in session {self.session_id}: {e}")
            self._send_error(f"Error: {e}")

    async def _handle_input(self, data: str):
        """
        Handle terminal input from browser.

        Args:
            data: Input data to write to PTY
        """
        if self.pty_bridge and self.pty_bridge.is_connected:
            error = await self.pty_bridge.write(data)
            if error:
                log_error(f"Error writing to PTY: {error}")
                self._send_error(f"PTY write error: {error}")
        else:
            log_debug(f"Terminal input received but no PTY connected: {repr(data[:50] if len(data) > 50 else data)}")
            # Echo back for testing when no PTY is attached
            self._send_message({
                "type": "output",
                "data": f"[No PTY connected] Input received: {len(data)} bytes\r\n"
            })

    async def _handle_resize(self, cols: int, rows: int):
        """
        Handle terminal resize request.

        Args:
            cols: New column count
            rows: New row count
        """
        self._cols = cols
        self._rows = rows
        log_debug(f"Terminal resize for session {self.session_id}: {cols}x{rows}")

        if self.pty_bridge and self.pty_bridge.is_connected:
            error = await self.pty_bridge.resize(cols, rows)
            if error:
                log_warning(f"PTY resize warning: {error}")

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

    def _send_error(self, error_message: str):
        """Send error message to browser."""
        self._send_message({
            "type": "error",
            "message": error_message
        })

    def send_output(self, data: str):
        """
        Send terminal output to browser.

        Args:
            data: Output data from PTY
        """
        self._send_message({"type": "output", "data": data})

    def send_output_bytes(self, data: bytes):
        """
        Send terminal output bytes to browser.

        Args:
            data: Output data from PTY as bytes
        """
        try:
            text = data.decode("utf-8", errors="replace")
            self.send_output(text)
        except Exception as e:
            log_error(f"Error decoding output bytes: {e}")

    def close(self):
        """Close the terminal channel and cleanup resources."""
        if self._closed:
            return

        self._closed = True
        self._ready = False

        log_info(f"Closing terminal channel for session {self.session_id}")

        # Close PTY bridge if attached
        if self.pty_bridge:
            try:
                self.pty_bridge.close()
            except Exception as e:
                log_debug(f"Error closing PTY bridge: {e}")
            self.pty_bridge = None

        # Notify browser
        try:
            self._send_message({"type": "pty_disconnected"})
        except Exception:
            pass

        # Close the data channel
        if self.channel:
            try:
                self.channel.close()
            except Exception as e:
                log_debug(f"Error closing data channel: {e}")

        log_info(f"Terminal channel closed for session {self.session_id}")

    @property
    def is_ready(self) -> bool:
        """Check if channel is ready for I/O."""
        return self._ready and not self._closed

    @property
    def is_closed(self) -> bool:
        """Check if channel is closed."""
        return self._closed

    @property
    def is_pty_connected(self) -> bool:
        """Check if PTY is connected."""
        return self.pty_bridge is not None and self.pty_bridge.is_connected
