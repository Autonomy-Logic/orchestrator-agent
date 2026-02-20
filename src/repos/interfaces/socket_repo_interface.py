from typing import Protocol


class SocketRepoInterface(Protocol):
    """Abstract interface for socket operations (DNS resolution, hostname)."""

    def resolve_dns(self, host: str, port: int, timeout: float) -> list:
        """Resolve hostname to address info list. Raises socket.gaierror on failure."""
        ...

    def get_hostname(self) -> str:
        """Return the local machine hostname."""
        ...
