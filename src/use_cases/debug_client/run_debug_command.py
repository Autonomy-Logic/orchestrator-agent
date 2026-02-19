"""
Dispatch a single debug protocol command on an existing connection.

Stateless use case that takes an already-connected DebugSocketRepo and
sends one debug command, returning the parsed response.
"""

from tools.debug_protocol import (
    build_get_md5,
    build_get_info,
    build_get_list,
    build_set_variable,
    parse_response,
)
from tools.logger import log_error, log_debug


def run_debug_command(command_type, params, debug_socket, debug_protocol=None):
    """Dispatch a single debug command on an existing connection.

    Args:
        command_type: "get_md5" | "get_list" | "set" | "info"
        params: dict with command-specific fields:
            - get_list: {"indexes": [0, 1, 2, ...]}
            - set: {"index": 42, "force": True, "value": "01"} (value is hex)
            - get_md5, info: no params needed
        debug_socket: Connected DebugSocketRepo instance.
        debug_protocol: Unused, kept for API compatibility.

    Returns:
        {"success": True, "data": {...parsed response...}} or
        {"success": False, "error": "...message..."}
    """
    try:
        if command_type == "get_md5":
            hex_cmd = build_get_md5()
        elif command_type == "info":
            hex_cmd = build_get_info()
        elif command_type == "get_list":
            indexes = params.get("indexes", [])
            if not indexes:
                return {"success": False, "error": "indexes must not be empty"}
            hex_cmd = build_get_list(indexes)
        elif command_type == "set":
            index = params.get("index")
            if index is None or not isinstance(index, int) or not (0 <= index <= 65535):
                return {"success": False, "error": f"Invalid index: must be an integer 0–65535, got {index!r}"}
            force = params.get("force", True)
            value_hex = params.get("value", "00")
            try:
                value_bytes = bytes.fromhex(value_hex.replace(" ", ""))
            except (ValueError, AttributeError) as e:
                return {"success": False, "error": f"Invalid value hex string: {value_hex!r} ({e})"}
            hex_cmd = build_set_variable(index, force, value_bytes)
        else:
            return {"success": False, "error": f"Unknown command type: {command_type}"}

        log_debug(f"[run_debug_command] Sending {command_type}: {hex_cmd}")

        response = debug_socket.send_command(hex_cmd, timeout=5.0)

        if not response.get("success", False):
            error_msg = response.get("error", "Unknown runtime error")
            log_error(f"[run_debug_command] Runtime error for {command_type}: {error_msg}")
            return {"success": False, "error": error_msg}

        raw_data = response.get("data", "")
        parsed = parse_response(raw_data)

        log_debug(f"[run_debug_command] {command_type} response parsed: {parsed}")

        return {"success": True, "data": parsed, "raw": raw_data}

    except TimeoutError as e:
        log_error(f"[run_debug_command] Timeout for {command_type}: {e}")
        return {"success": False, "error": f"Timeout: {e}"}
    except Exception as e:
        log_error(f"[run_debug_command] Error for {command_type}: {e}")
        return {"success": False, "error": str(e)}
