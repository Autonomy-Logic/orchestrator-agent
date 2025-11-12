from . import HOST_NAME
from tools.logger import log_info
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
        log_info(f"Container '{HOST_NAME}' not found.")
    except Exception as e:
        log_info(f"Error removing container '{HOST_NAME}': {e}")
