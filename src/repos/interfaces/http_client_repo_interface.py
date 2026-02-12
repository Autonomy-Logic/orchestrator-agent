from typing import Protocol


class HTTPClientRepoInterface(Protocol):
    """Abstract interface for HTTP communication with runtime containers."""

    def make_request(
        self, method: str, ip: str, port: int, api: str, content: dict
    ) -> dict: ...
