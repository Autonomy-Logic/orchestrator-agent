from typing import Optional, Dict


class FileClientRegistry:
    """Concrete adapter wrapping the CLIENTS dict and clients.json persistence.

    Holds a reference to the live mutable CLIENTS dict so that existing code
    that reads CLIENTS directly continues to see updates.
    """

    def __init__(self, clients_dict: dict, write_fn):
        self._clients = clients_dict
        self._write_fn = write_fn

    def add_client(self, name: str, ip: str) -> None:
        self._clients[name] = {"ip": ip, "name": name}
        self._write_fn()

    def remove_client(self, name: str) -> None:
        if name in self._clients:
            del self._clients[name]
            self._write_fn()

    def get_client(self, name: str) -> Optional[dict]:
        return self._clients.get(name)

    def list_clients(self) -> Dict[str, dict]:
        return dict(self._clients)

    def contains(self, name: str) -> bool:
        return name in self._clients
