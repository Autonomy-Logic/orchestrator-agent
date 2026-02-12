import asyncio

from use_cases.runtime_commands.run_command import execute_for_device
from . import topic, validate_message, with_response
from tools.logger import *
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
    BASE_DEVICE,
)

NAME = "run_command"

MESSAGE_TYPE = {
    **BASE_DEVICE,
    "method": StringType,
    "api": StringType,
    "port": OptionalType(NumberType),
    # headers, data, params, files are optional and not type-validated
    # They are passed through directly to the HTTP request
}


@topic(NAME)
def init(client, ctx):
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
    @with_response(NAME)
    async def callback(message):
        device_id = message.get("device_id")

        log_info(f"Received run_command for device {device_id}: {message.get('method')} {message.get('api')}")

        result = await asyncio.to_thread(
            execute_for_device, device_id, message,
            client_registry=ctx.client_registry,
            http_client=ctx.http_client,
        )

        if result.get("http_response"):
            log_info(f"Command completed with status {result['http_response'].get('status_code')}")

        return result
