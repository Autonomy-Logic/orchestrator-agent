from . import CLIENTS, get_self_container
from tools.logger import log_info, log_warning, log_error
from tools.docker_tools import CLIENT
from tools.vnic_persistence import delete_vnic_configs
from tools.devices_usage_buffer import get_devices_usage_buffer
from tools.operations_state import set_deleting, set_step, set_error
import docker

NETMON_CONTAINER_NAME = "autonomy_netmon"
SHARED_VOLUME_NAME = "orchestrator-shared"
ORCHESTRATOR_STATUS_ID = "__orchestrator__"


def _delete_runtime_container_for_selfdestruct(container_name: str):
    """
    Delete a single runtime container and its associated resources.
    This is a simplified version of delete_runtime_container for use during self-destruct.
    Raises exception on failure to stop the self-destruct process.

    Args:
        container_name: Name of the runtime container to delete
    """
    log_info(f"Deleting runtime container: {container_name}")

    try:
        container = CLIENT.containers.get(container_name)
        log_info(f"Stopping container {container_name}")
        container.stop(timeout=10)
        log_info(f"Removing container {container_name}")
        container.remove(force=True)
        log_info(f"Container {container_name} removed successfully")
    except docker.errors.NotFound:
        log_warning(f"Container {container_name} not found, may have been already deleted")
    except Exception as e:
        log_error(f"Error stopping/removing container {container_name}: {e}")
        raise

    try:
        devices_buffer = get_devices_usage_buffer()
        devices_buffer.remove_device(container_name)
    except Exception as e:
        log_warning(f"Error removing {container_name} from usage buffer: {e}")

    try:
        delete_vnic_configs(container_name)
    except Exception as e:
        log_warning(f"Error deleting vNIC configurations for {container_name}: {e}")

    internal_network_name = f"{container_name}_internal"
    try:
        internal_network = CLIENT.networks.get(internal_network_name)
        internal_network.reload()
        connected_containers = internal_network.attrs.get("Containers", {})

        if connected_containers:
            for container_id in list(connected_containers.keys()):
                try:
                    internal_network.disconnect(container_id, force=True)
                except Exception as e:
                    log_warning(f"Error disconnecting container from {internal_network_name}: {e}")

        log_info(f"Removing internal network {internal_network_name}")
        internal_network.remove()
        log_info(f"Internal network {internal_network_name} removed successfully")
    except docker.errors.NotFound:
        log_warning(f"Internal network {internal_network_name} not found")
    except Exception as e:
        log_warning(f"Error removing internal network {internal_network_name}: {e}")


def _delete_all_runtime_containers():
    """
    Delete all managed runtime containers.
    Raises exception on failure to stop the self-destruct process.
    """
    if not CLIENTS:
        log_info("No runtime containers to delete")
        return

    container_names = list(CLIENTS.keys())
    log_info(f"Deleting {len(container_names)} runtime container(s): {container_names}")

    for container_name in container_names:
        _delete_runtime_container_for_selfdestruct(container_name)

        if container_name in CLIENTS:
            del CLIENTS[container_name]

    log_info("All runtime containers deleted successfully")


def _delete_netmon_container():
    """
    Delete the autonomy-netmon sidecar container.
    Raises exception on failure to stop the self-destruct process.
    """
    log_info(f"Deleting netmon container: {NETMON_CONTAINER_NAME}")

    try:
        container = CLIENT.containers.get(NETMON_CONTAINER_NAME)
        log_info(f"Stopping container {NETMON_CONTAINER_NAME}")
        container.stop(timeout=10)
        log_info(f"Removing container {NETMON_CONTAINER_NAME}")
        container.remove(force=True)
        log_info(f"Container {NETMON_CONTAINER_NAME} removed successfully")
    except docker.errors.NotFound:
        log_warning(f"Container {NETMON_CONTAINER_NAME} not found, may have been already deleted")
    except Exception as e:
        log_error(f"Error stopping/removing container {NETMON_CONTAINER_NAME}: {e}")
        raise


def _delete_shared_volume():
    """
    Attempt to delete the orchestrator-shared Docker volume.

    Note: This will likely fail because the orchestrator-agent container itself
    mounts this volume. The volume will be orphaned after the orchestrator
    container is removed and can be cleaned up with 'docker volume prune'.
    This is a best-effort cleanup step that does NOT raise on failure.
    """
    log_info(f"Attempting to delete shared volume: {SHARED_VOLUME_NAME}")

    try:
        volume = CLIENT.volumes.get(SHARED_VOLUME_NAME)
        volume.remove(force=True)
        log_info(f"Volume {SHARED_VOLUME_NAME} removed successfully")
    except docker.errors.NotFound:
        log_warning(f"Volume {SHARED_VOLUME_NAME} not found, may have been already deleted")
    except Exception as e:
        log_warning(
            f"Could not remove volume {SHARED_VOLUME_NAME}: {e}. "
            "This is expected since the orchestrator container mounts this volume. "
            "The volume will be orphaned after self-destruct completes and can be "
            "cleaned up with 'docker volume prune'."
        )


def _delete_orchestrator_container():
    """
    Delete the orchestrator-agent container itself.
    This should be called last as it will terminate the process.
    """
    log_info("Deleting orchestrator-agent container (self)...")

    self_container = get_self_container()
    if not self_container:
        log_error("Could not detect orchestrator-agent container")
        raise RuntimeError("Could not detect orchestrator-agent container for self-destruct")

    container_name = self_container.name
    log_info(f"Removing orchestrator-agent container: {container_name}")

    try:
        self_container.remove(force=True)
        log_info(f"Container '{container_name}' removed successfully.")
    except docker.errors.NotFound:
        log_error(f"Container '{container_name}' not found.")
        raise
    except Exception as e:
        log_error(f"Error removing container '{container_name}': {e}")
        raise


def start_self_destruct() -> bool:
    """
    Initialize the self-destruct operation by setting the tracking state.

    Returns:
        True if self-destruct was started successfully
        False if a self-destruct operation is already in progress
    """
    if not set_deleting(ORCHESTRATOR_STATUS_ID):
        log_warning("Self-destruct operation already in progress")
        return False

    set_step(ORCHESTRATOR_STATUS_ID, "starting")
    return True


def self_destruct():
    """
    Self-destruct the orchestrator by removing all managed resources.

    Cleanup order:
    1. Delete all managed runtime containers (vPLCs) and their networks
    2. Delete the autonomy-netmon sidecar container
    3. Delete the orchestrator-shared volume
    4. Delete the orchestrator-agent container itself (last)

    Updates operations_state with progress steps:
    - "starting" -> "deleting_runtimes" -> "deleting_netmon" -> "deleting_volume" -> "removing_self"

    On failure, sets error state and raises exception.
    The orchestrator-agent container removal is only attempted after all other
    cleanup steps succeed.
    """
    log_info("Self-destructing orchestrator...")

    try:
        set_step(ORCHESTRATOR_STATUS_ID, "deleting_runtimes")
        _delete_all_runtime_containers()

        set_step(ORCHESTRATOR_STATUS_ID, "deleting_netmon")
        _delete_netmon_container()

        set_step(ORCHESTRATOR_STATUS_ID, "deleting_volume")
        _delete_shared_volume()

        set_step(ORCHESTRATOR_STATUS_ID, "removing_self")
        _delete_orchestrator_container()

    except Exception as e:
        log_error(f"Self-destruct failed: {e}")
        set_error(ORCHESTRATOR_STATUS_ID, str(e), "self_destruct")
        raise
