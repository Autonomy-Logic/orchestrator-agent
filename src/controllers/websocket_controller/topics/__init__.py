from .receivers.connect import init as init_connect
from .receivers.create_new_runtime import init as init_create_new_runtime
from .receivers.delete_device import init as init_delete_device
from .receivers.delete_orchestrator import init as init_delete_orchestrator
from .receivers.disconnect import init as init_disconnect
from .receivers.get_consumption_device import init as init_get_consumption_device
from .receivers.get_consumption_orchestrator import (
    init as init_get_consumption_orchestrator,
)
from .receivers.get_device_status import init as init_get_device_status
from .receivers.get_host_interfaces import init as init_get_host_interfaces
from .receivers.get_serial_devices import init as init_get_serial_devices
from .receivers.restart_device import init as init_restart_device
from .receivers.run_command import init as init_run_command
from .receivers.start_device import init as init_start_device
from .receivers.stop_device import init as init_stop_device


def initialize_all(client):

    # Initialize all topic receivers
    init_connect(client)
    init_create_new_runtime(client)
    init_run_command(client)
    init_disconnect(client)
    init_delete_device(client)
    init_delete_orchestrator(client)
    init_get_consumption_device(client)
    init_get_consumption_orchestrator(client)
    init_get_device_status(client)
    init_get_host_interfaces(client)
    init_get_serial_devices(client)
    init_restart_device(client)
    init_start_device(client)
    init_stop_device(client)
