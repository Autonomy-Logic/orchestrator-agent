from . import HOST_NAME
from tools.logger import log_info, log_error
import docker


def self_destruct():
    """
    Self-destruct the orchestrator by shutting it down.
    """
    log_info("Self-destructing orchestrator...")

    client = docker.from_env()
    try:
        container = client.containers.get(HOST_NAME)
        container.remove(force=True)
        log_info(f"Container '{HOST_NAME}' removed successfully.")
    except docker.errors.NotFound:
        log_error(f"Container '{HOST_NAME}' not found.")
    except Exception as e:
        log_error(f"Error removing container '{HOST_NAME}': {e}")
