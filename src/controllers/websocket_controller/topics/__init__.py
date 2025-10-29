from .receivers.connect import init as init_connect
from .receivers.create_new_runtime import init as init_create_new_runtime
from .receivers.run_command import init as init_run_command
from .receivers.disconnect import init as init_disconnect


def initialize_all(client):

    # Initialize all topic receivers
    init_connect(client)
    init_create_new_runtime(client)
    init_run_command(client)
    init_disconnect(client)
