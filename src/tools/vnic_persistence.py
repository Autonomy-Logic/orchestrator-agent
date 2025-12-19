import json
import os
from tools.logger import *

VNIC_CONFIG_FILE = "/var/orchestrator/runtime_vnics.json"


def ensure_config_dir():
    """Ensure the configuration directory exists"""
    config_dir = os.path.dirname(VNIC_CONFIG_FILE)
    os.makedirs(config_dir, exist_ok=True)


def save_vnic_configs(container_name: str, vnic_configs: list):
    """
    Save vNIC configurations for a runtime container.

    Args:
        container_name: Name of the runtime container
        vnic_configs: List of vNIC configurations
    """
    try:
        ensure_config_dir()

        existing_configs = {}
        if os.path.exists(VNIC_CONFIG_FILE):
            try:
                with open(VNIC_CONFIG_FILE, "r") as f:
                    existing_configs = json.load(f)
            except Exception as e:
                log_warning(f"Failed to read existing vNIC configs: {e}")

        existing_configs[container_name] = vnic_configs

        with open(VNIC_CONFIG_FILE, "w") as f:
            json.dump(existing_configs, f, indent=2)

        log_debug(f"Saved vNIC configurations for container {container_name}")

    except Exception as e:
        log_error(f"Failed to save vNIC configurations for {container_name}: {e}")


def load_vnic_configs(container_name: str = None):
    """
    Load vNIC configurations for a runtime container or all containers.

    Args:
        container_name: Name of the runtime container (optional)

    Returns:
        If container_name is provided, returns list of vNIC configs for that container.
        If container_name is None, returns dict of all container vNIC configs.
    """
    try:
        if not os.path.exists(VNIC_CONFIG_FILE):
            return [] if container_name else {}

        with open(VNIC_CONFIG_FILE, "r") as f:
            all_configs = json.load(f)

        if container_name:
            return all_configs.get(container_name, [])
        else:
            return all_configs

    except Exception as e:
        log_error(f"Failed to load vNIC configurations: {e}")
        return [] if container_name else {}


def delete_vnic_configs(container_name: str):
    """
    Delete vNIC configurations for a runtime container.

    Args:
        container_name: Name of the runtime container
    """
    try:
        if not os.path.exists(VNIC_CONFIG_FILE):
            return

        with open(VNIC_CONFIG_FILE, "r") as f:
            all_configs = json.load(f)

        if container_name in all_configs:
            del all_configs[container_name]

            with open(VNIC_CONFIG_FILE, "w") as f:
                json.dump(all_configs, f, indent=2)

            log_debug(f"Deleted vNIC configurations for container {container_name}")

    except Exception as e:
        log_error(f"Failed to delete vNIC configurations for {container_name}: {e}")


def get_all_mac_addresses() -> dict[str, str]:
    """
    Get all MAC addresses currently in use by existing containers.

    Returns:
        Dictionary mapping MAC address (lowercase) to container name.
    """
    macs = []
    try:
        all_configs = load_vnic_configs()
        for _, vnic_configs in all_configs.items():
            for vnic_config in vnic_configs:
                mac_address = vnic_config.get("mac_address")
                if mac_address:
                    macs.append(mac_address.lower())
    except Exception as e:
        log_error(f"Failed to get all MAC addresses: {e}")
    return macs


def check_mac_conflicts(vnic_configs: list) -> tuple[bool, str, str]:
    """
    Check if any MAC addresses in the vNIC configs conflict with existing containers.

    Args:
        vnic_configs: List of vNIC configurations to check

    Returns:
        Tuple of (has_conflict, conflicting_mac, conflicting_container).
        If no conflict, returns (False, "", "").
    """
    existing_macs = get_all_mac_addresses()

    for vnic_config in vnic_configs:
        mac_address = vnic_config.get("mac_address") or vnic_config.get("mac")
        if mac_address:
            mac_lower = mac_address.lower()
            if mac_lower in existing_macs:
                return True, mac_address

    return False, "", ""
