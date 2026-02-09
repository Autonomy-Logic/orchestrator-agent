from . import get_self_container
from tools.operations_state import set_step, set_error, clear_state
from tools.logger import *
from tools.devices_usage_buffer import get_devices_usage_buffer
from tools.network_event_listener import network_event_listener
from bootstrap import get_context
import asyncio


def _delete_runtime_container_sync(
    container_name: str,
    *,
    container_runtime=None,
    client_registry=None,
    vnic_repo=None,
    serial_repo=None,
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
    """
    if any(dep is None for dep in [container_runtime, client_registry, vnic_repo, serial_repo]):

        ctx = get_context()
        if container_runtime is None:
            container_runtime = ctx.container_runtime
        if client_registry is None:
            client_registry = ctx.client_registry
        if vnic_repo is None:
            vnic_repo = ctx.vnic_repo
        if serial_repo is None:
            serial_repo = ctx.serial_repo

    log_debug(f'Attempting to delete runtime container "{container_name}"')

    if not client_registry.contains(container_name):
        log_warning(f"Container {container_name} not found in client registry")

    try:
        set_step(container_name, "stopping_container")
        try:
            container = container_runtime.get_container(container_name)
            log_info(f"Stopping container {container_name}")
            container.stop(timeout=10)

            set_step(container_name, "removing_container")
            log_info(f"Removing container {container_name}")
            container.remove(force=True)
            log_info(f"Container {container_name} removed successfully")
        except container_runtime.NotFoundError:
            log_warning(
                f"Container {container_name} not found, may have been already deleted"
            )
        except Exception as e:
            log_error(f"Error stopping/removing container {container_name}: {e}")
            raise

        try:
            client_registry.remove_client(container_name)
            log_debug(f"Removed {container_name} from client registry")
        except Exception as e:
            log_warning(f"Error removing {container_name} from client registry: {e}")

        try:
            devices_buffer = get_devices_usage_buffer()
            devices_buffer.remove_device(container_name)
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

        set_step(container_name, "removing_networks")
        internal_network_name = f"{container_name}_internal"
        try:
            internal_network = container_runtime.get_network(internal_network_name)

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

        except container_runtime.NotFoundError:
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


async def delete_runtime_container(
    container_name: str,
    *,
    container_runtime=None,
    client_registry=None,
    vnic_repo=None,
    serial_repo=None,
    network_commander=None,
):
    """
    Delete a runtime container and all associated resources.

    Proxy ARP cleanup is done first via netmon (async), then blocking Docker
    operations are offloaded to a background thread.

    Args:
        container_name: Name of the runtime container to delete
        container_runtime: Optional ContainerRuntimeRepo adapter (defaults to singleton)
        client_registry: Optional ClientRepo adapter (defaults to singleton)
        vnic_repo: Optional VNICRepo adapter (defaults to singleton)
        serial_repo: Optional SerialRepo adapter (defaults to singleton)
        network_commander: Optional NetworkCommanderRepo adapter (defaults to singleton)
    """
    if vnic_repo is None:

        vnic_repo = get_context().vnic_repo
    if network_commander is None:
        network_commander = network_event_listener

    # Clean up Proxy ARP bridges via netmon before deleting container
    # This must be done before container removal to ensure routes are properly cleaned
    try:
        all_vnic_configs = vnic_repo.load_configs()
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
    )
