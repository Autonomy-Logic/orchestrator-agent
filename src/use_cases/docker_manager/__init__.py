import docker
import os
import json
from tools.logger import log_error

CLIENT = docker.from_env()

HOST_NAME = os.getenv("HOST_NAME", "orchestrator-agent-devcontainer")
CLIENTS_FILE = os.getenv("CLIENTS_FILE", "/var/orchestrator/data/clients.json")


def load_clients_from_file():
    if not os.path.exists(CLIENTS_FILE):
        return {}
    with open(CLIENTS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


CLIENTS = load_clients_from_file()


def ensure_clients_file_exists():
    if not os.path.exists(CLIENTS_FILE):
        dir_name = os.path.dirname(CLIENTS_FILE)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(CLIENTS_FILE, "w") as f:
            f.write("{}")
    return True


def write_clients_to_file():
    if not ensure_clients_file_exists():
        return
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
