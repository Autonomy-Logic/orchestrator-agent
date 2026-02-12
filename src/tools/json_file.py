"""Thread-safe JSON file read/write helper for config persistence."""

import json
import os
import threading

from tools.logger import log_error


def read_json_file(file_path: str) -> dict:
    """Read a JSON file, returning empty dict if missing or invalid."""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log_error(f"Failed to parse {file_path}: {e}")
        return {}
    except Exception as e:
        log_error(f"Failed to read {file_path}: {e}")
        return {}


def write_json_file(file_path: str, data: dict, indent: int = 2) -> None:
    """Write data as JSON, creating parent directories if needed."""
    config_dir = os.path.dirname(file_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=indent)


class JsonConfigStore:
    """Thread-safe JSON file store for container-keyed configs."""

    def __init__(self, config_file):
        self._config_file = config_file
        self._lock = threading.Lock()

    def read_all(self):
        with self._lock:
            return read_json_file(self._config_file)

    def modify(self, fn):
        """Read all, call fn(data) to mutate, write back."""
        with self._lock:
            data = read_json_file(self._config_file)
            fn(data)
            write_json_file(self._config_file, data)
