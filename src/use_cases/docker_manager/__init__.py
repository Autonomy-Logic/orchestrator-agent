import os
from tools.logger import log_debug, log_info, log_error, log_warning

HOST_NAME = os.getenv("HOST_NAME", "orchestrator_agent")


def get_self_container(*, container_runtime, socket_repo):
    """
    Detect the orchestrator-agent's own container from inside the container.

    Tries multiple methods in order:
    1. HOSTNAME environment variable (Docker sets this to container ID by default)
    2. socket_repo.get_hostname() (usually returns container ID)
    3. HOST_NAME environment variable (explicit override)
    4. Search by label edge.autonomy.role=orchestrator-agent

    Args:
        container_runtime: ContainerRuntimeRepo adapter
        socket_repo: SocketRepo adapter for hostname resolution

    Returns the container object or None if not found.
    """
    container_id = os.getenv("HOSTNAME")
    if container_id:
        try:
            container = container_runtime.get_container(container_id)
            log_debug(f"Found self container via HOSTNAME env: {container.name}")
            return container
        except container_runtime.NotFoundError:
            log_debug(f"HOSTNAME env {container_id} not found as container")

    try:
        hostname = socket_repo.get_hostname()
        container = container_runtime.get_container(hostname)
        log_debug(f"Found self container via socket_repo.get_hostname(): {container.name}")
        return container
    except container_runtime.NotFoundError:
        log_debug(f"socket_repo.get_hostname() {hostname} not found as container")
    except Exception as e:
        log_debug(f"Error getting hostname: {e}")

    if HOST_NAME:
        try:
            container = container_runtime.get_container(HOST_NAME)
            log_debug(f"Found self container via HOST_NAME env: {container.name}")
            return container
        except container_runtime.NotFoundError:
            log_debug(f"HOST_NAME env {HOST_NAME} not found as container")

    try:
        containers = container_runtime.list_containers(
            filters={"label": "edge.autonomy.role=orchestrator-agent"}
        )
        if containers:
            container = containers[0]
            log_debug(f"Found self container via label: {container.name}")
            return container
    except Exception as e:
        log_debug(f"Error searching by label: {e}")

    log_warning("Could not detect self container using any method")
    return None


def stop_and_remove_container(container_name, *, container_runtime):
    """Stop and force-remove a container. Logs warning if not found, re-raises other errors."""
    try:
        container = container_runtime.get_container(container_name)
        log_info(f"Stopping container {container_name}")
        container.stop(timeout=10)
        log_info(f"Removing container {container_name}")
        container.remove(force=True)
        log_info(f"Container {container_name} removed successfully")
    except container_runtime.NotFoundError:
        log_warning(f"Container {container_name} not found, may have been already deleted")
    except Exception as e:
        log_error(f"Error stopping/removing container {container_name}: {e}")
        raise


def remove_internal_network(container_name, *, container_runtime, socket_repo, disconnect_all=False):
    """Remove a container's internal network.
    If disconnect_all=True, disconnects all containers. Otherwise only disconnects orchestrator."""
    internal_network_name = f"{container_name}_internal"
    try:
        network = container_runtime.get_network(internal_network_name)
        network.reload()
        connected = network.attrs.get("Containers", {})
        if connected:
            if disconnect_all:
                for cid in list(connected.keys()):
                    try:
                        network.disconnect(cid, force=True)
                    except Exception as e:
                        log_warning(f"Error disconnecting container from {internal_network_name}: {e}")
            else:
                try:
                    main = get_self_container(container_runtime=container_runtime, socket_repo=socket_repo)
                    if main and main.id in connected:
                        network.disconnect(main, force=True)
                except Exception as e:
                    log_warning(f"Error disconnecting orchestrator from internal network: {e}")
        log_info(f"Removing internal network {internal_network_name}")
        network.remove()
        log_info(f"Internal network {internal_network_name} removed successfully")
    except container_runtime.NotFoundError:
        log_warning(f"Internal network {internal_network_name} not found")
    except Exception as e:
        log_warning(f"Error removing internal network {internal_network_name}: {e}")
