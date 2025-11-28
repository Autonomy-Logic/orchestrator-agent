from . import CLIENT, CLIENTS, remove_client, get_self_container
from tools.operations_state import set_step, set_error, clear_state
from tools.logger import *
from tools.vnic_persistence import delete_vnic_configs
import docker
import asyncio


def _delete_runtime_container_sync(container_name: str):
    """
    Synchronous implementation of runtime container deletion.
    This function contains all blocking Docker operations and runs in a background thread.

    Cleanup steps:
    1. Stop and remove the container
    2. Remove from client registry
    3. Delete vNIC configurations
    4. Remove internal network (if not used by other containers)
    5. Disconnect orchestrator from internal network (if connected)

    Note: MACVLAN networks are NOT removed as they may be shared by other containers.

    Args:
        container_name: Name of the runtime container to delete
    """

    log_debug(f'Attempting to delete runtime container "{container_name}"')

    if container_name not in CLIENTS:
        log_warning(f"Container {container_name} not found in client registry")

    try:
        set_step(container_name, "stopping_container")
        try:
            container = CLIENT.containers.get(container_name)
            log_info(f"Stopping container {container_name}")
            container.stop(timeout=10)

            set_step(container_name, "removing_container")
            log_info(f"Removing container {container_name}")
            container.remove(force=True)
            log_info(f"Container {container_name} removed successfully")
        except docker.errors.NotFound:
            log_warning(
                f"Container {container_name} not found, may have been already deleted"
            )
        except Exception as e:
            log_error(f"Error stopping/removing container {container_name}: {e}")
            raise

        try:
            remove_client(container_name)
            log_debug(f"Removed {container_name} from client registry")
        except Exception as e:
            log_warning(f"Error removing {container_name} from client registry: {e}")

        try:
            delete_vnic_configs(container_name)
            log_debug(f"Deleted vNIC configurations for {container_name}")
        except Exception as e:
            log_warning(f"Error deleting vNIC configurations for {container_name}: {e}")

        set_step(container_name, "removing_networks")
        internal_network_name = f"{container_name}_internal"
        try:
            internal_network = CLIENT.networks.get(internal_network_name)

            internal_network.reload()
            connected_containers = internal_network.attrs.get("Containers", {})

            if connected_containers:
                log_debug(
                    f"Internal network {internal_network_name} still has {len(connected_containers)} "
                    f"connected container(s), disconnecting them before removal"
                )

                try:
                    main_container = get_self_container()
                    if main_container and main_container.id in connected_containers:
                        internal_network.disconnect(main_container, force=True)
                        log_debug(
                            f"Disconnected orchestrator-agent from internal network {internal_network_name}"
                        )
                except Exception as e:
                    log_warning(
                        f"Error disconnecting orchestrator-agent from internal network: {e}"
                    )

            log_info(f"Removing internal network {internal_network_name}")
            internal_network.remove()
            log_info(f"Internal network {internal_network_name} removed successfully")

        except docker.errors.NotFound:
            log_debug(
                f"Internal network {internal_network_name} not found, may have been already deleted"
            )
        except Exception as e:
            log_warning(f"Error removing internal network {internal_network_name}: {e}")

        log_info(
            f"Runtime container {container_name} and associated resources deleted successfully"
        )

        clear_state(container_name)

    except Exception as e:
        log_error(f"Failed to delete runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        set_error(container_name, str(e), "delete")
        raise


async def delete_runtime_container(container_name: str):
    """
    Delete a runtime container and all associated resources.

    This async wrapper offloads all blocking Docker operations to a background thread
    to prevent blocking the asyncio event loop and causing websocket disconnections.

    Args:
        container_name: Name of the runtime container to delete
    """
    await asyncio.to_thread(_delete_runtime_container_sync, container_name)
