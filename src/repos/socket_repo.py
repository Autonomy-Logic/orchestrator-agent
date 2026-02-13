import socket


class SocketRepo:
    """Concrete implementation wrapping the socket module."""

    def resolve_dns(self, host: str, port: int, timeout: float) -> list:
        """Resolve hostname to address info list. Raises socket.gaierror on failure."""
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            return socket.getaddrinfo(
                host, port,
                socket.AF_UNSPEC, socket.SOCK_STREAM,
                0, socket.AI_ADDRCONFIG
            )
        finally:
            socket.setdefaulttimeout(old_timeout)

    def get_hostname(self) -> str:
        """Return the local machine hostname."""
        return socket.gethostname()
