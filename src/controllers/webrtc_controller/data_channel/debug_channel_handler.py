"""
Debug Channel Handler

Manages a dedicated 'debug' WebRTC DataChannel for forwarding raw Modbus PDU
binary frames between the browser and the runtime container.

The debug channel carries ONLY binary data (Modbus PDU). Session lifecycle
(debug_start/debug_stop) is handled via run_command on the main data channel,
which routes to the DebugSessionManager.

The DebugChannelHandler looks up the active debug socket from the
DebugSessionManager (keyed by device_id) and forwards binary frames.
"""

from tools.logger import log_info, log_debug, log_error
from tools.debug_protocol import bytes_to_hex, hex_to_bytes
import asyncio


class DebugChannelHandler:
    """
    Handles a 'debug'-labeled WebRTC DataChannel.

    Only processes binary messages (Modbus PDU). Converts to hex for
    Socket.IO transport, and converts hex responses back to binary.

    Session management (connect/disconnect) happens via run_command
    on the main data channel, not here.
    """

    def __init__(self, data_channel, session_id, session_manager, device_id,
                 *, debug_session_manager):
        """
        Initialize debug channel handler.

        Args:
            data_channel: RTCDataChannel instance (label='debug')
            session_id: Associated WebRTC session ID
            session_manager: WebRTCSessionManager instance
            device_id: The runtime device ID (for looking up debug sessions)
            debug_session_manager: DebugSessionManager for socket lookups
        """
        self.channel = data_channel
        self.session_id = session_id
        self.session_manager = session_manager
        self.device_id = device_id
        self._debug_session_manager = debug_session_manager
        self._closed = False
        self._command_lock = asyncio.Lock()

        self._setup_handlers()

    def _setup_handlers(self):
        """Set up debug data channel event handlers."""
        log_info(f"Setting up debug channel handlers for session {self.session_id}")

        @self.channel.on("open")
        def on_open():
            log_info(f"Debug channel OPEN for session {self.session_id}")

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
        """Handle incoming debug channel message (binary only)."""
        if self._closed:
            return

        if self.session_manager:
            self.session_manager.touch_session(self.session_id)

        if not isinstance(raw_message, (bytes, bytearray)):
            log_debug(f"Ignoring non-binary message on debug channel {self.session_id}")
            return

        await self._handle_binary_command(bytes(raw_message))

    async def _handle_binary_command(self, pdu_bytes):
        """
        Forward a binary Modbus PDU to the runtime and send the raw response back.

        The PDU is converted to a hex string for the Socket.IO debug_command
        event, and the hex response is converted back to bytes for the browser.
        """
        async with self._command_lock:
            try:
                hex_cmd = bytes_to_hex(pdu_bytes)
                log_debug(f"[Debug] Forwarding binary PDU: {hex_cmd}")

                result = await asyncio.to_thread(
                    self._debug_session_manager.forward_raw_command,
                    self.device_id,
                    hex_cmd,
                )

                if not result.get("success", False):
                    error_msg = result.get("error", "Unknown runtime error")
                    log_error(f"[Debug] Runtime error: {error_msg}")
                    return

                response_hex = result.get("data", "")
                if response_hex:
                    response_bytes = hex_to_bytes(response_hex)
                    self._send_binary(response_bytes)

            except Exception as e:
                log_error(f"[Debug] Binary command error: {e}")

    def _send_binary(self, data):
        """Send raw binary bytes on the debug channel."""
        if self._closed or not self.channel:
            return

        try:
            if self.channel.readyState == "open":
                self.channel.send(data)
            else:
                log_debug(f"Cannot send debug binary, channel state: {self.channel.readyState}")
        except Exception as e:
            log_error(f"Error sending debug binary in session {self.session_id}: {e}")

    def close(self):
        """Close the debug channel handler and cleanup."""
        if self._closed:
            return

        self._closed = True
        log_info(f"Closing debug channel handler for session {self.session_id}")

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
