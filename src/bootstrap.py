"""
Composition root: creates and wires all adapters at startup.

This module provides a centralized AppContext that holds all adapter instances,
enabling dependency injection throughout the application. Use get_context() to
access the singleton context.
"""

from adapters import (
    DockerContainerRuntime,
    FileVnicRepository,
    FileSerialRepository,
    FileClientRegistry,
    RequestsHttpClient,
    DictNetworkInterfaceCache,
)


class AppContext:
    """Holds all instantiated adapters for dependency injection."""

    def __init__(self):
        self.container_runtime = DockerContainerRuntime()
        self.vnic_repo = FileVnicRepository()
        self.serial_repo = FileSerialRepository()
        self.http_client = RequestsHttpClient()
        self.network_interface_cache = DictNetworkInterfaceCache()

        # FileClientRegistry needs references to the live CLIENTS dict
        # Import here to avoid circular imports at module level
        from use_cases.docker_manager import CLIENTS, write_clients_to_file

        self.client_registry = FileClientRegistry(CLIENTS, write_clients_to_file)


_context = None


def get_context() -> AppContext:
    """Return the singleton AppContext, creating it on first access."""
    global _context
    if _context is None:
        _context = AppContext()
    return _context
