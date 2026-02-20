"""
Validate the OpenPLC debug protocol against a runtime container.

Orchestrates the full validation flow: authenticate, connect, send
each debug command, log all raw responses, and disconnect.
"""

from tools.debug_protocol import (
    build_get_md5,
    build_get_info,
    build_get_list,
    parse_response,
)
from tools.logger import log_info, log_error, log_warning


def validate_debug_session(
    device_ip,
    username,
    password,
    *,
    http_client,
    debug_socket,
    port=8443,
    on_step=None,
):
    """Run a full debug protocol validation against a runtime container.

    Args:
        device_ip: IP address of the runtime container.
        username: Runtime login username.
        password: Runtime login password.
        http_client: HTTPClientRepoInterface - for REST authentication.
        debug_socket: DebugSocketRepoInterface - for Socket.IO debug session.
        port: Runtime HTTPS port (default 8443).
        on_step: Optional callable(step_dict) invoked after each debug step completes.

    Returns:
        Dict with "status" ("success" or "error") and "steps" list containing
        the raw request/response for each command sent.
    """
    steps = []
    url = f"https://{device_ip}:{port}"

    # --- Step 1: Authenticate ---
    log_info(f"Authenticating with runtime at {device_ip}:{port}")
    try:
        auth_response = http_client.make_request(
            "POST",
            device_ip,
            port,
            "api/login",
            {"json": {"username": username, "password": password}},
        )
    except Exception as e:
        log_error(f"Authentication request failed: {e}")
        return {"status": "error", "error": f"Authentication request failed: {e}", "steps": steps}

    if not auth_response.get("ok"):
        log_error(
            f"Authentication failed: HTTP {auth_response.get('status_code')} - {auth_response.get('body')}"
        )
        return {
            "status": "error",
            "error": f"Authentication failed: HTTP {auth_response.get('status_code')}",
            "steps": steps,
        }

    body = auth_response.get("body", {})
    token = body.get("access_token") if isinstance(body, dict) else None
    if not token:
        log_error(f"No access_token in login response: {body}")
        return {"status": "error", "error": "No access_token in login response", "steps": steps}

    log_info("Authentication successful, JWT obtained")

    # --- Step 2: Connect Socket.IO ---
    try:
        log_info(f"Connecting Socket.IO to {url}/api/debug")
        connected = debug_socket.connect(url, token, timeout=10.0)
        log_info(f"Socket.IO connected: {connected}")
    except Exception as e:
        log_error(f"Socket.IO connection failed: {e}")
        return {"status": "error", "error": f"Socket.IO connection failed: {e}", "steps": steps}

    try:
        # --- Step 3: DEBUG_GET_MD5 ---
        step = _send_and_log(debug_socket, "DEBUG_GET_MD5", build_get_md5())
        steps.append(step)
        if on_step:
            on_step(step)

        # --- Step 4: DEBUG_INFO ---
        step = _send_and_log(debug_socket, "DEBUG_INFO", build_get_info())
        steps.append(step)
        if on_step:
            on_step(step)

        variable_count = 0
        if step.get("parsed"):
            variable_count = step["parsed"].get("variable_count", 0)

        # --- Step 5: DEBUG_GET_LIST (if variables exist) ---
        if variable_count > 0:
            num_to_fetch = min(variable_count, 10)
            indexes = list(range(num_to_fetch))
            step = _send_and_log(debug_socket, "DEBUG_GET_LIST", build_get_list(indexes))
            steps.append(step)
            if on_step:
                on_step(step)
        else:
            log_info("No debug variables reported, skipping DEBUG_GET_LIST")

    finally:
        # --- Step 6: Disconnect ---
        debug_socket.disconnect()

    log_info("Debug protocol validation complete")
    return {"status": "success", "steps": steps}


def _send_and_log(debug_socket, command_name, hex_command):
    """Send a debug command, log the raw exchange, and return a step dict."""
    log_info(f"[{command_name}] Sending: {hex_command}")

    step = {
        "command": command_name,
        "raw_request": hex_command,
        "raw_response": None,
        "parsed": None,
        "error": None,
    }

    try:
        response = debug_socket.send_command(hex_command, timeout=5.0)
    except Exception as e:
        log_error(f"[{command_name}] Error: {e}")
        step["error"] = str(e)
        return step

    success = response.get("success", False)
    raw_data = response.get("data", "")
    error_msg = response.get("error", "")

    if success:
        log_info(f"[{command_name}] Raw response: {raw_data}")
        step["raw_response"] = raw_data
        try:
            step["parsed"] = parse_response(raw_data)
        except Exception as e:
            log_error(f"[{command_name}] Failed to parse response: {e}")
            step["error"] = f"Parse error: {e}"
    else:
        log_warning(f"[{command_name}] Runtime error: {error_msg}")
        step["raw_response"] = raw_data
        step["error"] = error_msg

    return step
