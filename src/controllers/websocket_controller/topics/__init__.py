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
from .receivers.run_command import init as init_run_command


def initialize_all(client, ctx):

    # Initialize all topic receivers
    init_connect(client, ctx)
    init_create_new_runtime(client, ctx)
    init_run_command(client, ctx)
    init_disconnect(client)
    init_delete_device(client, ctx)
    init_delete_orchestrator(client, ctx)
    init_get_consumption_device(client, ctx)
    init_get_consumption_orchestrator(client, ctx)
    init_get_device_status(client, ctx)
    init_get_host_interfaces(client, ctx)
    init_get_serial_devices(client, ctx)
