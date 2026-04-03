from . import stop_and_remove_container, remove_internal_network
from tools.logger import *
import asyncio


def _delete_runtime_container_sync(
    container_name: str,
    *,
    container_runtime,
    client_registry,
    vnic_repo,
    serial_repo,
    operations_state,
    devices_usage_buffer,
    socket_repo,
):
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
        container_runtime: Optional ContainerRuntimeRepo adapter (defaults to singleton)
        client_registry: Optional ClientRepo adapter (defaults to singleton)
        vnic_repo: Optional VNICRepo adapter (defaults to singleton)
        serial_repo: Optional SerialRepo adapter (defaults to singleton)
        operations_state: Optional OperationsStateTracker (defaults to singleton)
    """
    log_debug(f'Attempting to delete runtime container "{container_name}"')

    if not client_registry.contains(container_name):
        log_warning(f"Container {container_name} not found in client registry")

    try:
        operations_state.set_step(container_name, "stopping_container")
        stop_and_remove_container(container_name, container_runtime=container_runtime)

        try:
            client_registry.remove_client(container_name)
            log_debug(f"Removed {container_name} from client registry")
        except Exception as e:
            log_warning(f"Error removing {container_name} from client registry: {e}")

        try:
            devices_usage_buffer.remove_device(container_name)
            log_debug(f"Removed {container_name} from usage data collection")
        except Exception as e:
            log_warning(f"Error removing {container_name} from usage buffer: {e}")

        try:
            vnic_repo.delete_configs(container_name)
            log_debug(f"Deleted vNIC configurations for {container_name}")
        except Exception as e:
            log_warning(f"Error deleting vNIC configurations for {container_name}: {e}")

        try:
            serial_repo.delete_configs(container_name)
            log_debug(f"Deleted serial configurations for {container_name}")
        except Exception as e:
            log_warning(f"Error deleting serial configurations for {container_name}: {e}")

        operations_state.set_step(container_name, "removing_networks")
        remove_internal_network(container_name, container_runtime=container_runtime, socket_repo=socket_repo)

        log_info(
            f"Runtime container {container_name} and associated resources deleted successfully"
        )

        operations_state.clear_state(container_name)

    except Exception as e:
        log_error(f"Failed to delete runtime container {container_name}. Error: {e}")
        import traceback

        log_error(f"Traceback: {traceback.format_exc()}")
        operations_state.set_error(container_name, str(e), "delete")
        raise


async def delete_runtime_container(
    container_name: str,
    *,
    container_runtime,
    client_registry,
    vnic_repo,
    serial_repo,
    network_commander,
    operations_state,
    devices_usage_buffer,
    socket_repo,
    dedicated_nic_repo,
):
    """
    Delete a runtime container and all associated resources.

    Dedicated NIC return and Proxy ARP cleanup are done first via netmon (async),
    then blocking Docker operations are offloaded to a background thread.

    Args:
        container_name: Name of the runtime container to delete
        container_runtime: ContainerRuntimeRepo adapter
        client_registry: ClientRepo adapter
        vnic_repo: VNICRepo adapter
        serial_repo: SerialRepo adapter
        network_commander: NetworkCommanderRepo adapter
        operations_state: OperationsStateTracker
        devices_usage_buffer: DevicesUsageBuffer
        socket_repo: SocketRepo adapter
        dedicated_nic_repo: DedicatedNicRepo adapter
    """
    # Return dedicated NIC to host namespace (must happen before container stop)
    try:
        nic_config = dedicated_nic_repo.load_config(container_name)
        if nic_config:
            host_interface = nic_config.host_interface
            log_info(f"Returning dedicated NIC {host_interface} to host for {container_name}")
            try:
                pid = container_runtime.get_running_pid(container_name)
                if pid:
                    await network_commander.return_nic_to_host(host_interface, pid)
                    log_info(f"Dedicated NIC {host_interface} returned to host")
                else:
                    log_warning(
                        f"Container {container_name} not running, "
                        f"NIC {host_interface} may already be on host"
                    )
            except Exception as e:
                log_warning(f"Error returning dedicated NIC {host_interface}: {e}")
            dedicated_nic_repo.delete_config(container_name)
    except Exception as e:
        log_warning(f"Error during dedicated NIC cleanup for {container_name}: {e}")

    # Clean up Proxy ARP bridges via netmon before deleting container
    # This must be done before container removal to ensure routes are properly cleaned
    try:
        all_vnic_configs = vnic_repo.load_all_configs()
        vnic_configs = all_vnic_configs.get(container_name, [])
        for vnic_config in vnic_configs:
            proxy_arp_config = vnic_config.get("_proxy_arp_config")
            if proxy_arp_config:
                ip_address = proxy_arp_config.get("ip_address")
                parent_interface = proxy_arp_config.get("parent_interface")
                veth_host = proxy_arp_config.get("veth_host")
                if ip_address and parent_interface and veth_host:
                    log_info(f"Cleaning up Proxy ARP bridge for vNIC {vnic_config.get('name')}")
                    try:
                        await network_commander.cleanup_proxy_arp_bridge(
                            container_name, ip_address, parent_interface, veth_host
                        )
                    except Exception as e:
                        log_warning(f"Error cleaning up Proxy ARP bridge: {e}")
    except Exception as e:
        log_warning(f"Error loading vNIC configs for Proxy ARP cleanup: {e}")

    await asyncio.to_thread(
        _delete_runtime_container_sync, container_name,
        container_runtime=container_runtime,
        client_registry=client_registry,
        vnic_repo=vnic_repo,
        serial_repo=serial_repo,
        operations_state=operations_state,
        devices_usage_buffer=devices_usage_buffer,
        socket_repo=socket_repo,
    )


async def start_deletion(container_name, *, ctx):
    """
    Validate preconditions and begin container deletion as a background task.

    Returns:
        Tuple of (status_dict, started: bool). If started=True, deletion is running
        as a background task. If started=False, status_dict contains the error.
    """
    from tools.operations_state import begin_operation
    operations_state = ctx.operations_state

    error, ok = begin_operation(container_name, operations_state.set_deleting, operations_state=operations_state)
    if not ok:
        return error, False

    log_info(f"Deleting runtime container: {container_name}")

    asyncio.create_task(delete_runtime_container(
        container_name,
        container_runtime=ctx.container_runtime,
        client_registry=ctx.client_registry,
        vnic_repo=ctx.vnic_repo,
        serial_repo=ctx.serial_repo,
        network_commander=ctx.network_event_listener,
        operations_state=ctx.operations_state,
        devices_usage_buffer=ctx.devices_usage_buffer,
        socket_repo=ctx.socket_repo,
        dedicated_nic_repo=ctx.dedicated_nic_repo,
    ))

    return {
        "status": "deleting",
        "device_id": container_name,
        "message": f"Container deletion started for {container_name}",
    }, True
