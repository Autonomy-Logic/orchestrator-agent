"""
PTY Bridge

Bridges a WebRTC data channel to a Docker exec PTY socket.
Handles bidirectional I/O between browser terminal and container shell.
"""

import asyncio
import socket
from typing import Optional, Callable
from tools.logger import log_info, log_debug, log_error, log_warning
from use_cases.terminal_pty.create_pty_session import (
    create_pty_session,
    resize_pty_session,
    close_pty_session,
)


class PTYBridge:
    """
    Bridges terminal I/O between a WebRTC data channel and a Docker exec PTY.

    The bridge handles:
    - Reading output from PTY and sending to data channel
    - Receiving input from data channel and writing to PTY
    - Terminal resize events
    - Cleanup on disconnect
    """

    def __init__(
        self,
        container_name: str,
        output_callback: Callable[[bytes], None],
        cols: int = 80,
        rows: int = 24,
    ):
        """
        Initialize PTY bridge.

        Args:
            container_name: Target container name
            output_callback: Function to call with PTY output data
            cols: Initial terminal columns
            rows: Initial terminal rows
        """
        self.container_name = container_name
        self.output_callback = output_callback
        self.cols = cols
        self.rows = rows

        self._exec_id: Optional[str] = None
        self._socket: Optional[socket.SocketIO] = None
        self._read_task: Optional[asyncio.Task] = None
        self._closed = False
        self._connected = False

    async def connect(self) -> Optional[str]:
        """
        Connect to the container PTY.

        Returns:
            Error message if connection failed, None if successful
        """
        if self._connected:
            return "Already connected"

        log_info(f"Connecting PTY bridge to container {self.container_name}")

        exec_id, sock, error = await create_pty_session(
            self.container_name,
            self.cols,
            self.rows,
        )

        if error:
            log_error(f"Failed to create PTY session: {error}")
            return error

        self._exec_id = exec_id
        self._socket = sock
        self._connected = True

        # Start reading from PTY
        self._read_task = asyncio.create_task(self._read_loop())

        log_info(f"PTY bridge connected to {self.container_name}")
        return None

    async def _read_loop(self):
        """
        Continuously read from PTY socket and send to output callback.
        """
        log_debug(f"Starting PTY read loop for {self.container_name}")

        try:
            # Get the underlying socket file descriptor
            sock = self._socket._sock

            # Set socket to non-blocking
            sock.setblocking(False)

            loop = asyncio.get_event_loop()

            while not self._closed and self._connected:
                try:
                    # Read data from socket asynchronously
                    data = await loop.run_in_executor(
                        None,
                        self._blocking_read,
                        sock,
                    )

                    if data:
                        # Send output to callback
                        try:
                            self.output_callback(data)
                        except Exception as e:
                            log_error(f"Error in output callback: {e}")
                    elif data == b"":
                        # Socket closed
                        log_debug(f"PTY socket closed for {self.container_name}")
                        break

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    if not self._closed:
                        log_error(f"Error reading from PTY: {e}")
                    break

        except Exception as e:
            log_error(f"PTY read loop error: {e}")
        finally:
            log_debug(f"PTY read loop ended for {self.container_name}")
            if not self._closed:
                self.close()

    def _blocking_read(self, sock, chunk_size: int = 4096) -> bytes:
        """
        Blocking read from socket.

        Args:
            sock: Socket to read from
            chunk_size: Maximum bytes to read

        Returns:
            Data read from socket, or empty bytes on EOF
        """
        try:
            sock.setblocking(True)
            data = sock.recv(chunk_size)
            return data
        except socket.error as e:
            # Connection reset or closed
            if e.errno in (104, 54, 10054):  # ECONNRESET
                return b""
            raise
        except Exception:
            return b""

    async def write(self, data: str) -> Optional[str]:
        """
        Write input data to PTY.

        Args:
            data: String data to write to PTY

        Returns:
            Error message if write failed, None if successful
        """
        if not self._connected or self._closed:
            return "PTY not connected"

        if not self._socket:
            return "PTY socket not available"

        try:
            # Convert string to bytes
            data_bytes = data.encode("utf-8")

            # Get underlying socket and write
            sock = self._socket._sock
            loop = asyncio.get_event_loop()

            await loop.run_in_executor(
                None,
                self._blocking_write,
                sock,
                data_bytes,
            )

            return None

        except Exception as e:
            log_error(f"Error writing to PTY: {e}")
            return f"Write error: {e}"

    def _blocking_write(self, sock, data: bytes) -> None:
        """
        Blocking write to socket.

        Args:
            sock: Socket to write to
            data: Bytes to write
        """
        sock.setblocking(True)
        sock.sendall(data)

    async def resize(self, cols: int, rows: int) -> Optional[str]:
        """
        Resize the PTY terminal.

        Args:
            cols: New column count
            rows: New row count

        Returns:
            Error message if resize failed, None if successful
        """
        if not self._connected or not self._exec_id:
            return "PTY not connected"

        self.cols = cols
        self.rows = rows

        error = await resize_pty_session(self._exec_id, cols, rows)
        if error:
            log_warning(f"Failed to resize PTY: {error}")
        return error

    def close(self):
        """
        Close the PTY bridge and cleanup resources.
        """
        if self._closed:
            return

        self._closed = True
        self._connected = False

        log_info(f"Closing PTY bridge for {self.container_name}")

        # Cancel read task
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                # Don't await here to avoid blocking
                pass
            except Exception:
                pass

        # Close socket
        if self._socket:
            try:
                self._socket.close()
            except Exception as e:
                log_debug(f"Error closing PTY socket: {e}")
            self._socket = None

        # Cleanup exec
        if self._exec_id:
            try:
                close_pty_session(self._exec_id)
            except Exception as e:
                log_debug(f"Error closing PTY session: {e}")
            self._exec_id = None

        log_info(f"PTY bridge closed for {self.container_name}")

    @property
    def is_connected(self) -> bool:
        """Check if bridge is connected."""
        return self._connected and not self._closed

    @property
    def is_closed(self) -> bool:
        """Check if bridge is closed."""
        return self._closed
