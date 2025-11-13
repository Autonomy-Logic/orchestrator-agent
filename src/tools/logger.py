import logging
from datetime import datetime
import inspect
from colorlog import ColoredFormatter
import os

__all__ = ["log_error", "log_info", "log_warning", "log_debug", "set_log_level"]

LOGGER = logging.getLogger("orchestrator_agent")

## Allow all messages to be passed to handlers
LOGGER.setLevel(logging.DEBUG)
LOGGER.propagate = False

log_format = ColoredFormatter(
    "%(log_color)s%(asctime)s | %(levelname)s | %(message)s%(reset)s"
)
level = logging.INFO

## Configure logging stream
stream_handler = logging.StreamHandler()
stream_handler.setLevel(level)
stream_handler.setFormatter(log_format)
stream_handler.set_name("stream_handler")
LOGGER.addHandler(stream_handler)

## Create log directories if they don't exist
os.makedirs("/var/orchestrator/logs", exist_ok=True)
os.makedirs("/var/orchestrator/debug", exist_ok=True)

## Configure debug logging file
debugger_handler = logging.FileHandler(
    f"/var/orchestrator/debug/orchestrator-debug-{datetime.now().strftime('%Y-%m-%d')}.log",
    mode="w",
)
debugger_handler.setLevel(logging.DEBUG)
debugger_handler.setFormatter(log_format)
debugger_handler.set_name("debugger_handler")
LOGGER.addHandler(debugger_handler)

## Configure regular logging file
regular_handler = logging.FileHandler(
    f"/var/orchestrator/logs/orchestrator-logs-{datetime.now().strftime('%Y-%m-%d')}.log",
    mode="w",
)
regular_handler.setLevel(level)
regular_handler.setFormatter(log_format)
regular_handler.set_name("regular_handler")
LOGGER.addHandler(regular_handler)


def log_critical(message: str) -> None:
    """Log a critical error message."""
    LOGGER.critical(
        f"{inspect.stack()[1].function} | {message}",
        stack_info=True,
        stacklevel=3,
    )


def log_error(message: str) -> None:
    """Log an error message."""
    LOGGER.error(
        f"{inspect.stack()[1].function} | {message}",
        stack_info=True,
        stacklevel=3,
    )


def log_info(message: str) -> None:
    """Log an informational message."""
    LOGGER.info(f"{inspect.stack()[1].function} | {message}")


def log_warning(message: str) -> None:
    """Log a warning message."""
    LOGGER.warning(f"{inspect.stack()[1].function} | {message}")


def log_debug(message: str) -> None:
    """Log a debug message."""
    LOGGER.debug(f"{inspect.stack()[1].function} | {message}")


def set_log_level(level: int) -> None:
    """Set the logging level."""
    for handler in LOGGER.handlers:
        if handler.name != "debugger_handler":
            handler.setLevel(level)
