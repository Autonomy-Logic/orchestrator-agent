"""
OpenPLC debug protocol utilities.

Pure functions for building and parsing debug protocol messages.
The protocol uses Modbus-inspired function codes transported as
hex-encoded strings over Socket.IO events.

Reference: docs/features/openplc-debug-protocol/openplc-debug-protocol.md
"""

import struct

# --- Function codes ---
FC_DEBUG_INFO = 0x41
FC_DEBUG_SET = 0x42
FC_DEBUG_GET = 0x43
FC_DEBUG_GET_LIST = 0x44
FC_DEBUG_GET_MD5 = 0x45

# --- Response status codes ---
STATUS_SUCCESS = 0x7E
STATUS_OUT_OF_BOUNDS = 0x81
STATUS_OUT_OF_MEMORY = 0x82

_STATUS_NAMES = {
    STATUS_SUCCESS: "SUCCESS",
    STATUS_OUT_OF_BOUNDS: "ERROR_OUT_OF_BOUNDS",
    STATUS_OUT_OF_MEMORY: "ERROR_OUT_OF_MEMORY",
}

_FC_NAMES = {
    FC_DEBUG_INFO: "DEBUG_INFO",
    FC_DEBUG_SET: "DEBUG_SET",
    FC_DEBUG_GET: "DEBUG_GET",
    FC_DEBUG_GET_LIST: "DEBUG_GET_LIST",
    FC_DEBUG_GET_MD5: "DEBUG_GET_MD5",
}


# --- Conversion helpers ---


def bytes_to_hex(data: bytes) -> str:
    """Convert bytes to space-separated uppercase hex string.

    >>> bytes_to_hex(b'\\x45\\xDE\\xAD')
    '45 DE AD'
    """
    return " ".join(f"{b:02X}" for b in data)


def hex_to_bytes(hex_string: str) -> bytes:
    """Convert space-separated hex string to bytes.

    >>> hex_to_bytes('45 DE AD 00 00')
    b'\\x45\\xde\\xad\\x00\\x00'
    """
    return bytes.fromhex(hex_string.replace(" ", ""))


def status_name(code: int) -> str:
    """Human-readable status name."""
    return _STATUS_NAMES.get(code, f"UNKNOWN(0x{code:02X})")


def fc_name(code: int) -> str:
    """Human-readable function code name."""
    return _FC_NAMES.get(code, f"UNKNOWN(0x{code:02X})")


# --- Command builders (return hex strings) ---


def build_get_md5() -> str:
    """Build DEBUG_GET_MD5 command.

    Sends 0xDEAD as endianness check value.
    """
    return bytes_to_hex(struct.pack(">BHH", FC_DEBUG_GET_MD5, 0xDEAD, 0x0000))


def build_get_info() -> str:
    """Build DEBUG_INFO command to get the number of debug variables."""
    return bytes_to_hex(struct.pack(">B", FC_DEBUG_INFO))


def build_get_list(indexes: list) -> str:
    """Build DEBUG_GET_LIST command with 16-bit big-endian indexes.

    Args:
        indexes: List of variable indexes (0-based, max 256).
    """
    if not indexes:
        raise ValueError("indexes must not be empty")
    if len(indexes) > 256:
        raise ValueError("indexes must not exceed 256 entries")
    data = struct.pack(">BH", FC_DEBUG_GET_LIST, len(indexes))
    for idx in indexes:
        data += struct.pack(">H", idx)
    return bytes_to_hex(data)


def build_set_variable(index: int, force: bool, value: bytes) -> str:
    """Build DEBUG_SET command to force or release a variable.

    Args:
        index: Variable index (16-bit).
        force: True to force, False to release.
        value: Raw value bytes (little-endian, as expected by runtime).
    """
    data = struct.pack(">BHbH", FC_DEBUG_SET, index, 1 if force else 0, len(value))
    data += value
    return bytes_to_hex(data)


# --- Response parsers ---


def parse_response(hex_string: str) -> dict:
    """Parse a debug response hex string into a structured dict.

    Returns a dict with at minimum:
        - function_code: int
        - function_name: str
        - raw: str (the original hex string)

    Additional fields depend on the function code.
    """
    raw = hex_string
    try:
        data = hex_to_bytes(hex_string)
    except (ValueError, TypeError) as e:
        return {"function_code": None, "error": f"malformed hex: {e}", "raw": raw}

    if len(data) < 1:
        return {"function_code": None, "error": "empty response", "raw": raw}

    fc = data[0]
    result = {
        "function_code": fc,
        "function_name": fc_name(fc),
        "raw": raw,
    }

    if fc == FC_DEBUG_INFO:
        result.update(_parse_info(data))
    elif fc == FC_DEBUG_SET:
        result.update(_parse_set(data))
    elif fc == FC_DEBUG_GET_MD5:
        result.update(_parse_get_md5(data))
    elif fc in (FC_DEBUG_GET, FC_DEBUG_GET_LIST):
        result.update(_parse_get_list(data))
    else:
        result["error"] = f"unknown function code 0x{fc:02X}"

    return result


def _parse_info(data: bytes) -> dict:
    """Parse DEBUG_INFO response: [0x41] [count_hi] [count_lo]."""
    if len(data) < 3:
        return {"error": "response too short for DEBUG_INFO"}
    count = struct.unpack(">H", data[1:3])[0]
    return {"variable_count": count}


def _parse_set(data: bytes) -> dict:
    """Parse DEBUG_SET response: [0x42] [status]."""
    if len(data) < 2:
        return {"error": "response too short for DEBUG_SET"}
    status = data[1]
    return {"status": status, "status_name": status_name(status)}


def _parse_get_md5(data: bytes) -> dict:
    """Parse DEBUG_GET_MD5 response: [0x45] [status] [md5_ascii...]."""
    if len(data) < 2:
        return {"error": "response too short for DEBUG_GET_MD5"}
    status = data[1]
    result = {"status": status, "status_name": status_name(status)}
    if len(data) > 2:
        md5_bytes = data[2:]
        md5_str = md5_bytes.split(b"\x00")[0].decode("ascii", errors="replace")
        result["md5"] = md5_str
    return result


def _parse_get_list(data: bytes) -> dict:
    """Parse DEBUG_GET / DEBUG_GET_LIST response.

    Format: [fc] [status] [last_idx_hi] [last_idx_lo]
            [tick_3] [tick_2] [tick_1] [tick_0]
            [data_len_hi] [data_len_lo]
            [variable data...]
    """
    if len(data) < 2:
        return {"error": "response too short"}
    status = data[1]
    result = {"status": status, "status_name": status_name(status)}

    if status != STATUS_SUCCESS:
        return result

    if len(data) < 10:
        return {**result, "error": "response too short for successful GET_LIST"}

    last_index = struct.unpack(">H", data[2:4])[0]
    tick = struct.unpack(">I", data[4:8])[0]
    data_size = struct.unpack(">H", data[8:10])[0]

    if len(data) < 10 + data_size:
        return {**result, "error": f"response truncated: expected {10 + data_size} bytes, got {len(data)}"}

    var_data = data[10:10 + data_size]

    result["last_index"] = last_index
    result["tick"] = tick
    result["data_size"] = data_size
    result["variable_data_hex"] = bytes_to_hex(var_data) if var_data else ""

    return result
