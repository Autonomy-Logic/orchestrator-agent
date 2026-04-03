"""
Composition root: creates and wires all repos at startup.

This module provides a centralized AppContext that holds all repo instances,
enabling dependency injection throughout the application. Use get_context() to
access the singleton context.
"""

from repos import (
    ContainerRuntimeRepo,
    VNICRepo,
    SerialRepo,
    ClientRepo,
    HTTPClientRepo,
    NetworkInterfaceCacheRepo,
    NetmonClientRepo,
    SocketRepo,
    DedicatedNicRepo,
)
from repos.debug_socket_repo import DebugSocketRepo
from controllers.websocket_controller.debug_session_manager import DebugSessionManager
from tools.operations_state import OperationsStateTracker
from tools.devices_usage_buffer import DevicesUsageBuffer
from tools.network_event_listener import NetworkEventListener
from tools.system_info import get_static_system_info
from tools.usage_buffer import UsageBuffer
from tools.logger import log_info
from use_cases.dhcp_manager import DHCPManager
from use_cases.network_reconnection import NetworkReconnectionManager
from use_cases.serial_device_manager import SerialDeviceManager
from use_cases.dedicated_nic_manager import DedicatedNICManager


class AppContext:
    """Holds all instantiated repos for dependency injection."""

    def __init__(self):
        self.container_runtime = ContainerRuntimeRepo()
        self.vnic_repo = VNICRepo()
        self.serial_repo = SerialRepo()
        self.client_registry = ClientRepo()
        self.http_client = HTTPClientRepo()
        self.network_interface_cache = NetworkInterfaceCacheRepo()
        self.operations_state = OperationsStateTracker()
        self.usage_buffer = UsageBuffer()
        self.devices_usage_buffer = DevicesUsageBuffer()
        self.socket_repo = SocketRepo()
        self.netmon_client = NetmonClientRepo()
        self.dhcp_manager = DHCPManager(self.netmon_client, self.container_runtime, self.vnic_repo)
        self.reconnection_manager = NetworkReconnectionManager(
            self.netmon_client, self.container_runtime, self.vnic_repo, self.network_interface_cache
        )
        self.dedicated_nic_repo = DedicatedNicRepo()
        self.serial_device_manager = SerialDeviceManager(self.serial_repo, self.container_runtime)
        self.dedicated_nic_manager = DedicatedNICManager(
            self.netmon_client, self.container_runtime, self.dedicated_nic_repo
        )
        self.network_event_listener = NetworkEventListener(
            interface_cache=self.network_interface_cache,
            netmon_client=self.netmon_client,
            dhcp_manager=self.dhcp_manager,
            reconnection_manager=self.reconnection_manager,
            serial_device_manager=self.serial_device_manager,
            dedicated_nic_manager=self.dedicated_nic_manager,
        )

        # Factory callables for creating fresh repo instances per debug session
        self.http_client_factory = HTTPClientRepo
        self.debug_socket_factory = DebugSocketRepo

        self.debug_session_manager = DebugSessionManager(
            http_client_factory=self.http_client_factory,
            debug_socket_factory=self.debug_socket_factory,
            client_registry=self.client_registry,
        )

        self.static_system_info = get_static_system_info()

        # Register existing clients for usage data collection at bootstrap time
        clients = self.client_registry.list_clients()
        if clients:
            for client_name in clients:
                self.devices_usage_buffer.add_device(client_name)
                log_info(f"Registered existing client {client_name} for usage data collection")


_context = None


def get_context() -> AppContext:
    """Return the singleton AppContext, creating it on first access."""
    global _context
    if _context is None:
        _context = AppContext()
    return _context
