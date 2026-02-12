from . import get_self_container, stop_and_remove_container, remove_internal_network
from tools.logger import log_info, log_warning, log_error
import json
import re
import socket

NETMON_CONTAINER_NAME = "autonomy_netmon"
SHARED_VOLUME_NAME = "orchestrator-shared"
ORCHESTRATOR_STATUS_ID = "__orchestrator__"

# Pattern to match internal networks created by orchestrator (UUID_internal)
# UUID format: 8-4-4-4-12 hex characters
INTERNAL_NETWORK_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_internal$",
    re.IGNORECASE,
)

# Pattern to match MACVLAN networks created by orchestrator
# Format: macvlan_{interface}_{subnet}_{mask}
MACVLAN_NETWORK_PATTERN = re.compile(r"^macvlan_[a-zA-Z0-9]+_\d+\.\d+\.\d+\.\d+_\d+$")



def _delete_runtime_container_for_selfdestruct(container_name, container_runtime, vnic_repo, devices_usage_buffer):
    """
    Delete a single runtime container and its associated resources.
    This is a simplified version of delete_runtime_container for use during self-destruct.
    Raises exception on failure to stop the self-destruct process.

    Args:
        container_name: Name of the runtime container to delete
        container_runtime: ContainerRuntimeRepo adapter
        vnic_repo: VNICRepo adapter
    """
    log_info(f"Deleting runtime container: {container_name}")

    # Note: Per-container Proxy ARP cleanup is skipped here.
    # Veth pairs auto-cleanup when containers are deleted (kernel behavior).
    # Proxy ARP neighbor entries are cleaned in bulk via _cleanup_proxy_arp_veths().

    stop_and_remove_container(container_name, container_runtime=container_runtime)

    try:
        devices_usage_buffer.remove_device(container_name)
    except Exception as e:
        log_warning(f"Error removing {container_name} from usage buffer: {e}")

    try:
        vnic_repo.delete_configs(container_name)
    except Exception as e:
        log_warning(f"Error deleting vNIC configurations for {container_name}: {e}")

    remove_internal_network(container_name, container_runtime=container_runtime, disconnect_all=True)


def _delete_all_runtime_containers(container_runtime, client_registry, vnic_repo, devices_usage_buffer):
    """
    Delete all managed runtime containers.
    Raises exception on failure to stop the self-destruct process.
    """
    clients = client_registry.list_clients()
    if not clients:
        log_info("No runtime containers to delete")
        return

    container_names = list(clients.keys())
    log_info(f"Deleting {len(container_names)} runtime container(s): {container_names}")

    for container_name in container_names:
        _delete_runtime_container_for_selfdestruct(container_name, container_runtime, vnic_repo, devices_usage_buffer)
        client_registry.remove_client(container_name)

    log_info("All runtime containers deleted successfully")


def _cleanup_proxy_arp_veths():
    """
    Clean up all Proxy ARP veth interfaces and neighbor entries via netmon.

    Sends a cleanup_all_proxy_arp command to netmon via a direct synchronous
    socket write. Netmon has host network access and can run ip commands.

    This is a best-effort cleanup that does NOT raise on failure.
    """
    NETMON_SOCKET_PATH = "/var/orchestrator/netmon.sock"

    log_info("Requesting Proxy ARP cleanup from netmon...")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(NETMON_SOCKET_PATH)

            command = json.dumps({"command": "cleanup_all_proxy_arp"}) + "\n"
            sock.sendall(command.encode("utf-8"))

            # Read response
            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break

        if response_data:
            response = json.loads(response_data.decode("utf-8").strip())
            if response.get("success"):
                veths_removed = response.get("veths_removed", 0)
                log_info(f"Proxy ARP cleanup via netmon complete: {veths_removed} veths removed")
            else:
                log_warning(f"Proxy ARP cleanup via netmon failed: {response.get('error')}")
        else:
            log_warning("No response from netmon for Proxy ARP cleanup")

    except Exception as e:
        log_warning(f"Error requesting Proxy ARP cleanup from netmon: {e}")


def _cleanup_orchestrator_networks(container_runtime):
    """
    Clean up all orchestrator-created networks that are no longer in use.

    This removes:
    - Internal bridge networks matching UUID_internal pattern
    - MACVLAN networks matching macvlan_{interface}_{subnet}_{mask} pattern

    Networks with connected containers are skipped to avoid disrupting other applications.
    This is a best-effort cleanup that does NOT raise on failure.
    """
    log_info("Cleaning up orchestrator-created networks...")

    try:
        all_networks = container_runtime.list_networks()
    except Exception as e:
        log_warning(f"Could not list networks for cleanup: {e}")
        return

    networks_removed = 0
    networks_skipped = 0

    for network in all_networks:
        network_name = network.name

        is_internal = INTERNAL_NETWORK_PATTERN.match(network_name)
        is_macvlan = MACVLAN_NETWORK_PATTERN.match(network_name)

        if not is_internal and not is_macvlan:
            continue

        try:
            network.reload()
            connected_containers = network.attrs.get("Containers", {})

            if connected_containers:
                log_warning(
                    f"Network {network_name} has {len(connected_containers)} connected "
                    f"container(s), skipping removal"
                )
                networks_skipped += 1
                continue

            log_info(f"Removing unused network: {network_name}")
            network.remove()
            networks_removed += 1
            log_info(f"Network {network_name} removed successfully")

        except container_runtime.NotFoundError:
            log_warning(f"Network {network_name} not found, may have been already deleted")
        except Exception as e:
            log_warning(f"Could not remove network {network_name}: {e}")
            networks_skipped += 1

    log_info(
        f"Network cleanup complete: {networks_removed} removed, {networks_skipped} skipped"
    )


def _delete_netmon_container(container_runtime):
    """
    Delete the autonomy-netmon sidecar container.
    Raises exception on failure to stop the self-destruct process.
    """
    log_info(f"Deleting netmon container: {NETMON_CONTAINER_NAME}")

    try:
        container = container_runtime.get_container(NETMON_CONTAINER_NAME)
        log_info(f"Stopping container {NETMON_CONTAINER_NAME}")
        container.stop(timeout=10)
        log_info(f"Removing container {NETMON_CONTAINER_NAME}")
        container.remove(force=True)
        log_info(f"Container {NETMON_CONTAINER_NAME} removed successfully")
    except container_runtime.NotFoundError:
        log_warning(f"Container {NETMON_CONTAINER_NAME} not found, may have been already deleted")
    except Exception as e:
        log_error(f"Error stopping/removing container {NETMON_CONTAINER_NAME}: {e}")
        raise


def _delete_shared_volume(container_runtime):
    """
    Attempt to delete the orchestrator-shared Docker volume.

    Note: This will likely fail because the orchestrator-agent container itself
    mounts this volume. The volume will be orphaned after the orchestrator
    container is removed and can be cleaned up with 'docker volume prune'.
    This is a best-effort cleanup step that does NOT raise on failure.
    """
    log_info(f"Attempting to delete shared volume: {SHARED_VOLUME_NAME}")

    try:
        volume = container_runtime.get_volume(SHARED_VOLUME_NAME)
        volume.remove(force=True)
        log_info(f"Volume {SHARED_VOLUME_NAME} removed successfully")
    except container_runtime.NotFoundError:
        log_warning(f"Volume {SHARED_VOLUME_NAME} not found, may have been already deleted")
    except Exception as e:
        log_warning(
            f"Could not remove volume {SHARED_VOLUME_NAME}: {e}. "
            "This is expected since the orchestrator container mounts this volume. "
            "The volume will be orphaned after self-destruct completes and can be "
            "cleaned up with 'docker volume prune'."
        )


def _delete_orchestrator_container(container_runtime):
    """
    Delete the orchestrator-agent container itself.
    This should be called last as it will terminate the process.

    Args:
        container_runtime: ContainerRuntimeRepo adapter
    """
    log_info("Deleting orchestrator-agent container (self)...")

    self_container = get_self_container(container_runtime=container_runtime)
    if not self_container:
        log_error("Could not detect orchestrator-agent container")
        raise RuntimeError("Could not detect orchestrator-agent container for self-destruct")

    container_name = self_container.name
    log_info(f"Removing orchestrator-agent container: {container_name}")

    try:
        self_container.remove(force=True)
        log_info(f"Container '{container_name}' removed successfully.")
    except container_runtime.NotFoundError:
        log_error(f"Container '{container_name}' not found.")
        raise
    except Exception as e:
        log_error(f"Error removing container '{container_name}': {e}")
        raise


def start_self_destruct(*, operations_state) -> bool:
    """
    Initialize the self-destruct operation by setting the tracking state.

    Returns:
        True if self-destruct was started successfully
        False if a self-destruct operation is already in progress
    """
    if not operations_state.set_deleting(ORCHESTRATOR_STATUS_ID):
        log_warning("Self-destruct operation already in progress")
        return False

    operations_state.set_step(ORCHESTRATOR_STATUS_ID, "starting")
    return True


def self_destruct(*, container_runtime, client_registry, vnic_repo, operations_state, devices_usage_buffer):
    """
    Self-destruct the orchestrator by removing all managed resources.

    Cleanup order:
    1. Delete all managed runtime containers (vPLCs) and their networks
    2. Clean up orphaned networks (internal and MACVLAN)
    3. Delete the autonomy-netmon sidecar container
    4. Delete the orchestrator-shared volume (best-effort)
    5. Delete the orchestrator-agent container itself (last)

    Updates operations_state with progress steps:
    - "starting" -> "deleting_runtimes" -> "cleaning_networks" -> "deleting_netmon"
      -> "deleting_volume" -> "removing_self"

    On failure, sets error state and raises exception.
    The orchestrator-agent container removal is only attempted after all other
    cleanup steps succeed.

    Args:
        container_runtime: Optional ContainerRuntimeRepo adapter (defaults to singleton)
        client_registry: Optional ClientRepo adapter (defaults to singleton)
        vnic_repo: Optional VNICRepo adapter (defaults to singleton)
        operations_state: Optional OperationsStateTracker (defaults to singleton)
    """
    log_info("Self-destructing orchestrator...")

    try:
        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "deleting_runtimes")
        _delete_all_runtime_containers(container_runtime, client_registry, vnic_repo, devices_usage_buffer)

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "cleaning_networks")
        _cleanup_orchestrator_networks(container_runtime)

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "cleaning_proxy_arp")
        _cleanup_proxy_arp_veths()

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "deleting_netmon")
        _delete_netmon_container(container_runtime)

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "deleting_volume")
        _delete_shared_volume(container_runtime)

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "removing_self")
        _delete_orchestrator_container(container_runtime)

    except Exception as e:
        log_error(f"Self-destruct failed: {e}")
        operations_state.set_error(ORCHESTRATOR_STATUS_ID, str(e), "self_destruct")
        raise
