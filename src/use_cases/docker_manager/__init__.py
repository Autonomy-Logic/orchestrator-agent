import docker
import os
import json
import socket
from tools.logger import log_debug, log_info, log_warning
from tools.docker_tools import CLIENT
from tools.devices_usage_buffer import get_devices_usage_buffer

HOST_NAME = os.getenv("HOST_NAME", "orchestrator-agent-devcontainer")
CLIENTS_FILE = os.getenv("CLIENTS_FILE", "/var/orchestrator/data/clients.json")


def get_self_container():
    """
    Detect the orchestrator-agent's own container from inside the container.

    Tries multiple methods in order:
    1. HOSTNAME environment variable (Docker sets this to container ID by default)
    2. socket.gethostname() (usually returns container ID)
    3. HOST_NAME environment variable (explicit override)
    4. Search by label edge.autonomy.role=orchestrator-agent

    Returns the container object or None if not found.
    """
    container_id = os.getenv("HOSTNAME")
    if container_id:
        try:
            container = CLIENT.containers.get(container_id)
            log_debug(f"Found self container via HOSTNAME env: {container.name}")
            return container
        except docker.errors.NotFound:
            log_debug(f"HOSTNAME env {container_id} not found as container")

    try:
        hostname = socket.gethostname()
        container = CLIENT.containers.get(hostname)
        log_debug(f"Found self container via socket.gethostname(): {container.name}")
        return container
    except docker.errors.NotFound:
        log_debug(f"socket.gethostname() {hostname} not found as container")
    except Exception as e:
        log_debug(f"Error getting hostname: {e}")

    if HOST_NAME:
        try:
            container = CLIENT.containers.get(HOST_NAME)
            log_debug(f"Found self container via HOST_NAME env: {container.name}")
            return container
        except docker.errors.NotFound:
            log_debug(f"HOST_NAME env {HOST_NAME} not found as container")

    try:
        containers = CLIENT.containers.list(
            filters={"label": "edge.autonomy.role=orchestrator-agent"}
        )
        if containers:
            container = containers[0]
            log_debug(f"Found self container via label: {container.name}")
            return container
    except Exception as e:
        log_debug(f"Error searching by label: {e}")

    log_warning("Could not detect self container using any method")
    return None


def load_clients_from_file():
    if not os.path.exists(CLIENTS_FILE):
        return {}
    with open(CLIENTS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


CLIENTS = load_clients_from_file()


def _register_existing_clients_with_usage_buffer():
    """
    Register all existing clients with the devices usage buffer.
    This is called at module load time to ensure existing containers
    have their usage data collected from startup.
    """
    if not CLIENTS:
        return

    devices_buffer = get_devices_usage_buffer()
    for client_name in CLIENTS:
        devices_buffer.add_device(client_name)
        log_info(f"Registered existing client {client_name} for usage data collection")


_register_existing_clients_with_usage_buffer()


def ensure_clients_file_exists():
    if not os.path.exists(CLIENTS_FILE):
        dir_name = os.path.dirname(CLIENTS_FILE)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(CLIENTS_FILE, "w") as f:
            f.write("{}")


def write_clients_to_file():
    ensure_clients_file_exists()
    with open(CLIENTS_FILE, "w") as f:
        json.dump(CLIENTS, f, indent=4)


def add_client(clientName: str, ip: str):
    # TODO: Define structure of CLIENTS better
    CLIENTS[clientName] = {"ip": ip, "name": clientName}
    write_clients_to_file()


def remove_client(clientName: str):
    if clientName in CLIENTS:
        del CLIENTS[clientName]
        write_clients_to_file()
