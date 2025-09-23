import docker

CLIENT = docker.from_env()

## TODO: remove this hardcoding when creating installer
HOST_NAME = "orchestrator-agent-devcontainer"

CLIENTS = {}

def addClient(clientName: str, ip: str):
    # TODO: Define structure of CLIENTS better
    CLIENTS[clientName] = {
        "ip": ip,
        "name": clientName
    }