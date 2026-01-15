"""
Terminal Data Channel

Handles terminal I/O over WebRTC data channel.
Bridges data channel messages to PTY sessions on runtime containers.
"""

from tools.logger import log_info, log_debug, log_error, log_warning
import json
import asyncio


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
        self._message_queue = asyncio.Queue()
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
            # Queue message for async processing
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: asyncio.create_task(self._handle_message(message))
                )
            except RuntimeError:
                # If no event loop, handle synchronously (shouldn't happen in production)
                log_warning(f"No event loop for message handling in session {self.session_id}")

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
        if self.pty_bridge:
            try:
                await self.pty_bridge.write(data)
            except Exception as e:
                log_error(f"Error writing to PTY: {e}")
                self._send_error(f"PTY write error: {e}")
        else:
            log_debug(f"Terminal input received but no PTY attached: {repr(data[:50])}")
            # Echo back for testing when no PTY is attached
            self._send_message({
                "type": "output",
                "data": f"[No PTY attached] Received: {repr(data)}\r\n"
            })

    async def _handle_resize(self, cols: int, rows: int):
        """
        Handle terminal resize request.

        Args:
            cols: New column count
            rows: New row count
        """
        log_debug(f"Terminal resize for session {self.session_id}: {cols}x{rows}")
        if self.pty_bridge:
            try:
                await self.pty_bridge.resize(cols, rows)
            except Exception as e:
                log_error(f"Error resizing PTY: {e}")

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

    def set_pty_bridge(self, pty_bridge):
        """
        Associate a PTY bridge with this channel.

        Args:
            pty_bridge: PTY bridge instance
        """
        self.pty_bridge = pty_bridge
        log_debug(f"PTY bridge attached to session {self.session_id}")

    def close(self):
        """Close the terminal channel and cleanup resources."""
        if self._closed:
            return

        self._closed = True
        self._ready = False

        # Close PTY bridge if attached
        if self.pty_bridge:
            try:
                self.pty_bridge.close()
            except Exception as e:
                log_debug(f"Error closing PTY bridge: {e}")
            self.pty_bridge = None

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
