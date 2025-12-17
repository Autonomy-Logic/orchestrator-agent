from . import CLIENTS, get_self_container
from tools.logger import log_info, log_warning, log_error
from tools.docker_tools import CLIENT
from tools.vnic_persistence import delete_vnic_configs
from tools.devices_usage_buffer import get_devices_usage_buffer
import docker

NETMON_CONTAINER_NAME = "autonomy_netmon"
SHARED_VOLUME_NAME = "orchestrator-shared"


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
    Delete the orchestrator-shared Docker volume.
    Raises exception on failure to stop the self-destruct process.
    """
    log_info(f"Deleting shared volume: {SHARED_VOLUME_NAME}")

    try:
        volume = CLIENT.volumes.get(SHARED_VOLUME_NAME)
        volume.remove(force=True)
        log_info(f"Volume {SHARED_VOLUME_NAME} removed successfully")
    except docker.errors.NotFound:
        log_warning(f"Volume {SHARED_VOLUME_NAME} not found, may have been already deleted")
    except Exception as e:
        log_error(f"Error removing volume {SHARED_VOLUME_NAME}: {e}")
        raise


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


def self_destruct():
    """
    Self-destruct the orchestrator by removing all managed resources.

    Cleanup order:
    1. Delete all managed runtime containers (vPLCs) and their networks
    2. Delete the autonomy-netmon sidecar container
    3. Delete the orchestrator-shared volume
    4. Delete the orchestrator-agent container itself (last)

    Raises exception on any failure to allow the caller to return an error response.
    The orchestrator-agent container removal is only attempted after all other
    cleanup steps succeed.
    """
    log_info("Self-destructing orchestrator...")

    _delete_all_runtime_containers()

    _delete_netmon_container()

    _delete_shared_volume()

    _delete_orchestrator_container()
