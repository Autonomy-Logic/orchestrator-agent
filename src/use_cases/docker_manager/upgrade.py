import os

from . import get_self_container
from tools.logger import log_info, log_warning, log_error

ORCHESTRATOR_IMAGE = "ghcr.io/autonomy-logic/orchestrator-agent:latest"
NETMON_IMAGE = "ghcr.io/autonomy-logic/autonomy-netmon:latest"
NETMON_CONTAINER_NAME = "autonomy_netmon"
SHARED_VOLUME_NAME = "orchestrator-shared"
ORCHESTRATOR_STATUS_ID = "__orchestrator__"
UPGRADER_CONTAINER_NAME = "orchestrator_upgrader"


def start_upgrade(*, operations_state) -> bool:
    """
    Initialize the upgrade operation by setting the tracking state.

    Returns:
        True if upgrade was started successfully
        False if an operation is already in progress
    """
    if not operations_state.set_upgrading(ORCHESTRATOR_STATUS_ID):
        log_warning("Upgrade or other operation already in progress")
        return False

    operations_state.set_step(ORCHESTRATOR_STATUS_ID, "starting")
    return True


def _pull_images(container_runtime, operations_state):
    """Pull the latest images for both orchestrator and netmon."""
    operations_state.set_step(ORCHESTRATOR_STATUS_ID, "pulling_images")

    log_info(f"Pulling image: {ORCHESTRATOR_IMAGE}")
    container_runtime.pull_image(ORCHESTRATOR_IMAGE)
    log_info(f"Successfully pulled: {ORCHESTRATOR_IMAGE}")

    log_info(f"Pulling image: {NETMON_IMAGE}")
    container_runtime.pull_image(NETMON_IMAGE)
    log_info(f"Successfully pulled: {NETMON_IMAGE}")


def _upgrade_netmon(container_runtime, operations_state):
    """
    Upgrade the netmon sidecar container.

    Stops and removes the old netmon container, then creates a new one
    with the same configuration using the newly pulled image.
    """
    operations_state.set_step(ORCHESTRATOR_STATUS_ID, "upgrading_netmon")

    # Capture existing config before stopping
    netmon_mounts = []
    try:
        old_netmon = container_runtime.get_container(NETMON_CONTAINER_NAME)
        netmon_mounts = old_netmon.attrs.get("Mounts", [])
        log_info(f"Stopping netmon container: {NETMON_CONTAINER_NAME}")
        old_netmon.stop(timeout=10)
        old_netmon.remove(force=True)
        log_info(f"Removed old netmon container")
    except container_runtime.NotFoundError:
        log_warning(f"Netmon container {NETMON_CONTAINER_NAME} not found, creating fresh")

    # Reconstruct volume binds from old mounts
    # Default config matches install.sh:
    #   -v orchestrator-shared:/var/orchestrator
    #   -v /dev:/dev
    #   -v /run/udev:/run/udev:ro
    volumes = {
        SHARED_VOLUME_NAME: {"bind": "/var/orchestrator", "mode": "rw"},
        "/dev": {"bind": "/dev", "mode": "rw"},
        "/run/udev": {"bind": "/run/udev", "mode": "ro"},
    }

    # If we captured mounts from the old container, use those instead
    if netmon_mounts:
        volumes = {}
        for mount in netmon_mounts:
            source = mount.get("Name") or mount.get("Source", "")
            destination = mount.get("Destination", "")
            rw = mount.get("RW", True)
            mode = "rw" if rw else "ro"
            if source and destination:
                volumes[source] = {"bind": destination, "mode": mode}

    log_info(f"Creating new netmon container with image: {NETMON_IMAGE}")
    container_runtime.create_container(
        image=NETMON_IMAGE,
        name=NETMON_CONTAINER_NAME,
        detach=True,
        network_mode="host",
        pid_mode="host",
        privileged=True,
        restart_policy={"Name": "unless-stopped"},
        volumes=volumes,
    )

    # Start is implicit with create_container when detach=True in docker-py,
    # but the repo uses containers.create not containers.run.
    # Let's get the container and start it.
    new_netmon = container_runtime.get_container(NETMON_CONTAINER_NAME)
    new_netmon.start()
    log_info(f"New netmon container started successfully")


def _get_orchestrator_mount_config(self_container):
    """
    Extract the host-side mount configuration from the running orchestrator container.

    Returns a dict with the host paths needed to recreate the container:
        - mtls_host_path: Host path for mTLS certificates
        - shared_volume: Docker volume name for shared data
    """
    mounts = self_container.attrs.get("Mounts", [])

    mtls_host_path = None
    shared_volume = SHARED_VOLUME_NAME

    for mount in mounts:
        destination = mount.get("Destination", "")
        if destination == "/root/.mtls":
            mtls_host_path = mount.get("Source", "")
        elif destination == "/var/orchestrator":
            # Could be a named volume or a bind mount
            shared_volume = mount.get("Name") or mount.get("Source", SHARED_VOLUME_NAME)

    return {
        "mtls_host_path": mtls_host_path,
        "shared_volume": shared_volume,
    }


def _spawn_upgrader(container_runtime, socket_repo, operations_state):
    """
    Spawn a one-shot upgrader container that will replace the orchestrator.

    The upgrader runs from the NEW orchestrator image and performs:
    1. Wait for old orchestrator to finish responding
    2. Stop and remove old orchestrator container
    3. Create new orchestrator container with same config
    4. Exit and auto-remove itself

    The upgrader needs Docker socket access to manage containers.
    """
    operations_state.set_step(ORCHESTRATOR_STATUS_ID, "spawning_upgrader")

    self_container = get_self_container(
        container_runtime=container_runtime, socket_repo=socket_repo
    )
    if not self_container:
        raise RuntimeError("Could not detect orchestrator container for upgrade")

    container_name = self_container.name
    mount_config = _get_orchestrator_mount_config(self_container)

    if not mount_config["mtls_host_path"]:
        raise RuntimeError(
            "Could not detect mTLS host path from container mounts. "
            "Cannot proceed with upgrade."
        )

    log_info(
        f"Spawning upgrader container to replace '{container_name}' "
        f"(mtls: {mount_config['mtls_host_path']}, "
        f"volume: {mount_config['shared_volume']})"
    )

    # Remove any leftover upgrader container from a previous failed attempt
    try:
        old_upgrader = container_runtime.get_container(UPGRADER_CONTAINER_NAME)
        old_upgrader.remove(force=True)
        log_warning("Removed leftover upgrader container from previous attempt")
    except container_runtime.NotFoundError:
        pass

    env_vars = {
        "UPGRADE_MODE": "true",
        "TARGET_CONTAINER": container_name,
        "NEW_IMAGE": ORCHESTRATOR_IMAGE,
        "MTLS_HOST_PATH": mount_config["mtls_host_path"],
        "SHARED_VOLUME": mount_config["shared_volume"],
    }

    upgrader = container_runtime.create_container(
        image=ORCHESTRATOR_IMAGE,
        name=UPGRADER_CONTAINER_NAME,
        detach=True,
        auto_remove=True,
        command=["python", "src/tools/upgrade_self.py"],
        environment=env_vars,
        volumes={
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
        },
    )
    upgrader.start()

    log_info(f"Upgrader container '{UPGRADER_CONTAINER_NAME}' started")


def upgrade(*, container_runtime, socket_repo, operations_state):
    """
    Upgrade the orchestrator agent and netmon sidecar to the latest images.

    This operation preserves all vPLC containers, networks, configurations,
    and settings. Only the orchestrator and netmon containers are replaced.

    Sequence:
    1. Pull latest images for both orchestrator and netmon
    2. Upgrade netmon (stop, remove, recreate with new image)
    3. Spawn upgrader container to replace the orchestrator itself

    Updates operations_state with progress steps.
    On failure, sets error state and raises exception.
    """
    log_info("Starting orchestrator upgrade...")

    try:
        _pull_images(container_runtime, operations_state)
        _upgrade_netmon(container_runtime, operations_state)
        _spawn_upgrader(container_runtime, socket_repo, operations_state)

        operations_state.set_step(ORCHESTRATOR_STATUS_ID, "upgrader_spawned")
        log_info(
            "Upgrade handoff complete. Upgrader container will replace "
            "the orchestrator shortly."
        )

    except Exception as e:
        log_error(f"Upgrade failed: {e}")
        operations_state.set_error(ORCHESTRATOR_STATUS_ID, str(e), "upgrade")
        raise
