import os
from typing import Optional, Dict

from repos.interfaces import ClientRepoInterface
from tools.json_file import read_json_file, write_json_file

CLIENTS_FILE = os.getenv("CLIENTS_FILE", "/var/orchestrator/data/clients.json")


class ClientRepo(ClientRepoInterface):
    """Concrete repo that owns client persistence via clients.json.

    Loads the client dict from disk on init and writes back on every mutation.
    """

    def __init__(self, clients_file: str = CLIENTS_FILE):
        self._clients_file = clients_file
        self._clients = read_json_file(self._clients_file)

    def _write_to_file(self) -> None:
        write_json_file(self._clients_file, self._clients, indent=4)

    def add_client(self, name: str, ip: str) -> None:
        self._clients[name] = {"ip": ip, "name": name}
        self._write_to_file()

    def remove_client(self, name: str) -> None:
        if name in self._clients:
            del self._clients[name]
            self._write_to_file()

    def get_client(self, name: str) -> Optional[dict]:
        return self._clients.get(name)

    def list_clients(self) -> Dict[str, dict]:
        return dict(self._clients)

    def contains(self, name: str) -> bool:
        return name in self._clients
