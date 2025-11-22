from use_cases.runtime_commands import run_command
from use_cases.docker_manager import CLIENTS
from . import topic
from tools.logger import *

NAME = "run_command"


@topic(NAME)
def init(client):
    """
    Handle the 'run_command' topic to execute HTTP commands on runtime instances.
    
    This topic forwards HTTP requests from the api-service to runtime containers
    (e.g., openplc-runtime) and returns the full HTTP response back through the websocket.
    
    Expected command format:
    {
        "method": "GET|POST|PUT|DELETE",
        "api": "/api/endpoint",
        "port": 8443 (optional, defaults to 8443),
        "headers": {} (optional),
        "data": {} (optional),
        "params": {} (optional),
        "files": {} (optional)
    }
    
    Returns:
    {
        "status_code": 200,
        "headers": {},
        "body": {},
        "ok": true,
        "content_type": "application/json"
    }
    """

    @client.on(NAME)
    async def callback(instance_id, command):
        log_info(f"Received run_command for instance {instance_id}: {command.get('method')} {command.get('api')}")
        
        # Validate instance exists
        instance = CLIENTS.get(instance_id)
        if not instance:
            log_error(f"Instance not found: {instance_id}")
            return {
                "status_code": 404,
                "headers": {},
                "body": {"error": f"Instance not found: {instance_id}"},
                "ok": False,
                "content_type": "application/json"
            }
        
        # Validate required command fields
        if not command.get("method"):
            log_error("Missing required field: method")
            return {
                "status_code": 400,
                "headers": {},
                "body": {"error": "Missing required field: method"},
                "ok": False,
                "content_type": "application/json"
            }
        
        if not command.get("api"):
            log_error("Missing required field: api")
            return {
                "status_code": 400,
                "headers": {},
                "body": {"error": "Missing required field: api"},
                "ok": False,
                "content_type": "application/json"
            }
        
        # Execute the command and return the response
        response = run_command.execute(instance, command)
        log_info(f"Command completed with status {response.get('status_code')}")
        return response
