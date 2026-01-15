"""
Terminal Data Channel

Handles terminal I/O over WebRTC data channel.
Bridges data channel messages to PTY sessions on runtime containers.
"""

from tools.logger import log_info, log_debug, log_error
import json


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
    """

    def __init__(self, data_channel, session_id: str):
        """
        Initialize terminal channel.

        Args:
            data_channel: RTCDataChannel instance
            session_id: Associated WebRTC session ID
        """
        self.channel = data_channel
        self.session_id = session_id
        self.pty_session = None
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up data channel event handlers."""

        @self.channel.on("open")
        def on_open():
            log_info(f"Terminal data channel opened for session {self.session_id}")

        @self.channel.on("close")
        def on_close():
            log_info(f"Terminal data channel closed for session {self.session_id}")
            self._cleanup()

        @self.channel.on("message")
        async def on_message(message):
            await self._handle_message(message)

    async def _handle_message(self, raw_message):
        """
        Handle incoming data channel message.

        Args:
            raw_message: Raw message (string or bytes)
        """
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")

            message = json.loads(raw_message)
            msg_type = message.get("type")

            if msg_type == "input":
                await self._handle_input(message.get("data", ""))
            elif msg_type == "resize":
                await self._handle_resize(message.get("cols", 80), message.get("rows", 24))
            elif msg_type == "ping":
                self._send_message({"type": "pong"})
            elif msg_type == "close":
                self._cleanup()
            else:
                log_debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            log_error(f"Invalid JSON message: {e}")
        except Exception as e:
            log_error(f"Error handling message: {e}")

    async def _handle_input(self, data: str):
        """
        Handle terminal input from browser.

        Args:
            data: Input data to write to PTY
        """
        # Implementation will be added in Phase 3
        log_debug(f"Terminal input received: {repr(data[:50])}")

    async def _handle_resize(self, cols: int, rows: int):
        """
        Handle terminal resize request.

        Args:
            cols: New column count
            rows: New row count
        """
        # Implementation will be added in Phase 3
        log_debug(f"Terminal resize: {cols}x{rows}")

    def _send_message(self, message: dict):
        """
        Send message to browser via data channel.

        Args:
            message: Message dict to send as JSON
        """
        try:
            self.channel.send(json.dumps(message))
        except Exception as e:
            log_error(f"Error sending message: {e}")

    def send_output(self, data: str):
        """
        Send terminal output to browser.

        Args:
            data: Output data from PTY
        """
        self._send_message({"type": "output", "data": data})

    def _cleanup(self):
        """Clean up resources."""
        if self.pty_session:
            # PTY cleanup will be added in Phase 3
            pass
        log_debug(f"Terminal channel cleanup for session {self.session_id}")

    def set_pty_session(self, pty_session):
        """
        Associate a PTY session with this channel.

        Args:
            pty_session: PTY session instance
        """
        self.pty_session = pty_session
