from use_cases.runtime_commands import run_command
from use_cases.docker_manager import CLIENTS
from . import topic, validate_message
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
)

NAME = "run_command"

MESSAGE_TYPE = {
    "correlation_id": NumberType,
    "device_id": StringType,
    "method": StringType,
    "api": StringType,
    "action": OptionalType(StringType),
    "requested_at": OptionalType(StringType),
    "port": OptionalType(NumberType),
    # headers, data, params, files are optional and not type-validated
    # They are passed through directly to the HTTP request
}


@topic(NAME)
def init(client):
    """
    Handle the 'run_command' topic to execute HTTP commands on runtime instances.

    This topic forwards HTTP requests from the api-service to runtime containers
    (e.g., openplc-runtime) and returns the full HTTP response back through the websocket.

    Acts as a transparent bridge - the openplc-editor and openplc-runtime communicate
    as if directly connected on the same network.

    Expected message format:
    {
        "correlation_id": 12345,
        "device_id": "runtime-container-name",
        "method": "GET|POST|PUT|DELETE",
        "api": "/api/endpoint",
        "action": "run_command" (optional),
        "requested_at": "2024-01-01T12:00:00" (optional),
        "port": 8443 (optional, defaults to 8443),
        "headers": {} (optional),
        "data": {} (optional),
        "params": {} (optional),
        "files": {} (optional)
    }

    Returns:
    {
        "action": "run_command",
        "correlation_id": 12345,
        "status": "success|error",
        "http_response": {
            "status_code": 200,
            "headers": {},
            "body": {},
            "ok": true,
            "content_type": "application/json"
        }
    }
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        correlation_id = message.get("correlation_id")
        device_id = message.get("device_id")
        method = message.get("method")
        api = message.get("api")

        log_info(f"Received run_command for device {device_id}: {method} {api}")

        # Validate device exists
        instance = CLIENTS.get(device_id)
        if not instance:
            log_error(f"Device not found: {device_id}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Device not found: {device_id}",
            }

        # Build command object for run_command.execute
        command = {
            "method": method,
            "api": api,
            "port": message.get("port", 8443),
            "headers": message.get("headers", {}),
            "data": message.get("data"),
            "params": message.get("params"),
            "files": message.get("files"),
        }

        # Execute the HTTP request
        http_response = run_command.execute(instance, command)
        log_info(f"Command completed with status {http_response.get('status_code')}")

        # Return response with correlation_id
        return {
            "action": NAME,
            "correlation_id": correlation_id,
            "status": "success" if http_response.get("ok") else "error",
            "http_response": http_response,
        }
