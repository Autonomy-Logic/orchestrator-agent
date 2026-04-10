import os

NETMON_CONTAINER_NAME = "autonomy_netmon"


def get_orchestrator_version(*, container_runtime):
    """
    Collect version information for the orchestrator agent and netmon sidecar.

    Reads the orchestrator version from the AGENT_VERSION environment variable
    (baked in at Docker build time). Reads the netmon version by inspecting the
    netmon container's environment via the Docker API.

    Args:
        container_runtime: ContainerRuntimeRepo adapter

    Returns:
        dict with orchestrator_version, netmon_version, and orchestrator_image_id.
    """
    orchestrator_version = os.getenv("AGENT_VERSION", "unknown")

    netmon_version = "unknown"
    try:
        netmon = container_runtime.get_container(NETMON_CONTAINER_NAME)
        env_list = netmon.attrs.get("Config", {}).get("Env", [])
        for env_entry in env_list:
            if env_entry.startswith("AGENT_VERSION="):
                netmon_version = env_entry.split("=", 1)[1]
                break
    except Exception:
        pass

    orchestrator_image_id = "unknown"
    try:
        hostname = os.getenv("HOSTNAME", "")
        if hostname:
            self_container = container_runtime.get_container(hostname)
            orchestrator_image_id = self_container.image.id
    except Exception:
        pass

    return {
        "orchestrator_version": orchestrator_version,
        "netmon_version": netmon_version,
        "orchestrator_image_id": orchestrator_image_id,
    }
