import os
import json
from typing import Optional, Dict

CLIENTS_FILE = os.getenv("CLIENTS_FILE", "/var/orchestrator/data/clients.json")


class FileClientRegistry:
    """Concrete adapter that owns client persistence via clients.json.

    Loads the client dict from disk on init and writes back on every mutation.
    """

    def __init__(self, clients_file: str = CLIENTS_FILE):
        self._clients_file = clients_file
        self._clients = self._load_from_file()

    def _load_from_file(self) -> dict:
        if not os.path.exists(self._clients_file):
            return {}
        with open(self._clients_file, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}

    def _write_to_file(self) -> None:
        dir_name = os.path.dirname(self._clients_file)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(self._clients_file, "w") as f:
            json.dump(self._clients, f, indent=4)

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
