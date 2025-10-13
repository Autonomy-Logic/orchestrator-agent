from use_cases.runtime_commands import run_command
from use_cases.docker_manager import CLIENTS
from tools.logger import *

NAME = "run_command"


def callback(instance_id, command):
    log_info(f"Executing command: {command}")
    instance = CLIENTS.get(instance_id)
    if not instance:
        log_error(f"Instance not found: {instance_id}")
        return {"error": "Instance not found"}
    if not command.get("method") or not command.get("api"):
        log_error("Invalid command format")
        return {"error": "Invalid command format"}
    return run_command.execute(instance, command)
