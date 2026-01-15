"""
Create PTY Session

Creates an interactive PTY session on a runtime container using Docker exec.
"""

import docker
from tools.docker_tools import CLIENT
from tools.logger import log_info, log_debug, log_error, log_warning
from use_cases.docker_manager import CLIENTS
from typing import Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Thread pool for blocking Docker operations
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pty_")

# Default shell to use
DEFAULT_SHELL = "/bin/bash"
FALLBACK_SHELL = "/bin/sh"


def _create_exec_sync(
    container_name: str,
    cols: int = 80,
    rows: int = 24,
    shell: str = DEFAULT_SHELL,
) -> Tuple[Optional[str], Optional[object], Optional[str]]:
    """
    Synchronous function to create Docker exec instance.

    Args:
        container_name: Name of the container
        cols: Terminal column count
        rows: Terminal row count
        shell: Shell to execute

    Returns:
        Tuple of (exec_id, socket, error_message)
    """
    try:
        # Get container
        container = CLIENT.containers.get(container_name)

        if container.status != "running":
            return None, None, f"Container {container_name} is not running (status: {container.status})"

        # Check if shell exists in container
        try:
            exit_code, _ = container.exec_run(f"which {shell}", demux=True)
            if exit_code != 0:
                log_warning(f"Shell {shell} not found in container, trying {FALLBACK_SHELL}")
                shell = FALLBACK_SHELL
        except Exception:
            shell = FALLBACK_SHELL

        # Create exec instance with PTY
        exec_instance = CLIENT.api.exec_create(
            container.id,
            shell,
            stdin=True,
            tty=True,
            environment={
                "TERM": "xterm-256color",
                "COLUMNS": str(cols),
                "LINES": str(rows),
            },
        )

        exec_id = exec_instance["Id"]
        log_debug(f"Created exec instance {exec_id} for container {container_name}")

        # Start exec and get socket
        socket = CLIENT.api.exec_start(
            exec_id,
            tty=True,
            socket=True,
            demux=False,
        )

        log_info(f"PTY session started for container {container_name} (exec_id: {exec_id[:12]})")
        return exec_id, socket, None

    except docker.errors.NotFound:
        return None, None, f"Container {container_name} not found"
    except docker.errors.APIError as e:
        return None, None, f"Docker API error: {e}"
    except Exception as e:
        return None, None, f"Error creating PTY session: {e}"


async def create_pty_session(
    container_name: str,
    cols: int = 80,
    rows: int = 24,
) -> Tuple[Optional[str], Optional[object], Optional[str]]:
    """
    Create an interactive PTY session on a runtime container.

    This is an async wrapper that offloads blocking Docker operations
    to a thread pool to avoid blocking the event loop.

    Args:
        container_name: Name of the target container
        cols: Initial terminal column count
        rows: Initial terminal row count

    Returns:
        Tuple of (exec_id, socket, error_message)
        - exec_id: Docker exec instance ID
        - socket: Socket for reading/writing to PTY
        - error_message: Error description if failed, None if successful
    """
    # Verify container exists in our registry
    if container_name not in CLIENTS:
        log_warning(f"Container {container_name} not in CLIENTS registry")
        return None, None, f"Container {container_name} not managed by orchestrator"

    loop = asyncio.get_event_loop()

    exec_id, socket, error = await loop.run_in_executor(
        _executor,
        _create_exec_sync,
        container_name,
        cols,
        rows,
    )

    return exec_id, socket, error


def _resize_exec_sync(exec_id: str, cols: int, rows: int) -> Optional[str]:
    """
    Synchronous function to resize exec TTY.

    Args:
        exec_id: Docker exec instance ID
        cols: New column count
        rows: New row count

    Returns:
        Error message if failed, None if successful
    """
    try:
        CLIENT.api.exec_resize(exec_id, height=rows, width=cols)
        log_debug(f"Resized exec {exec_id[:12]} to {cols}x{rows}")
        return None
    except docker.errors.APIError as e:
        return f"Failed to resize PTY: {e}"
    except Exception as e:
        return f"Error resizing PTY: {e}"


async def resize_pty_session(exec_id: str, cols: int, rows: int) -> Optional[str]:
    """
    Resize a PTY session.

    Args:
        exec_id: Docker exec instance ID
        cols: New column count
        rows: New row count

    Returns:
        Error message if failed, None if successful
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _resize_exec_sync,
        exec_id,
        cols,
        rows,
    )


def _close_exec_sync(exec_id: str) -> None:
    """
    Attempt to clean up exec instance.
    Note: Docker doesn't provide a direct way to terminate exec,
    but we can inspect it to check if it's still running.
    """
    try:
        exec_info = CLIENT.api.exec_inspect(exec_id)
        if exec_info.get("Running", False):
            log_debug(f"Exec {exec_id[:12]} is still running, will terminate when socket closes")
        else:
            log_debug(f"Exec {exec_id[:12]} has already exited")
    except Exception as e:
        log_debug(f"Error inspecting exec {exec_id[:12]}: {e}")


def close_pty_session(exec_id: str) -> None:
    """
    Close/cleanup a PTY session.

    Note: The exec session will terminate when the socket is closed
    and the shell process exits. This function is mainly for cleanup.

    Args:
        exec_id: Docker exec instance ID
    """
    _close_exec_sync(exec_id)
    log_info(f"PTY session {exec_id[:12]} closed")
