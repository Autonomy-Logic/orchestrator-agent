from typing import Dict, Optional

from entities import DedicatedNicConfig
from repos.interfaces import DedicatedNicRepoInterface
from tools.json_file import JsonConfigStore
from tools.logger import log_debug, log_error

DEDICATED_NIC_CONFIG_FILE = "/var/orchestrator/dedicated_nics.json"


class DedicatedNicRepo(DedicatedNicRepoInterface):
    """File-backed persistence for dedicated NIC configurations."""

    def __init__(self):
        self._store = JsonConfigStore(DEDICATED_NIC_CONFIG_FILE)

    def save_config(self, container_name: str, config: DedicatedNicConfig) -> None:
        try:
            self._store.modify(lambda data: data.__setitem__(container_name, config.to_dict()))
            log_debug(
                f"Saved dedicated NIC config for container {container_name}"
            )
        except Exception as e:
            log_error(
                f"Failed to save dedicated NIC config for {container_name}: {e}"
            )

    def load_config(self, container_name: str) -> Optional[DedicatedNicConfig]:
        try:
            all_configs = self._store.read_all()
            raw = all_configs.get(container_name)
            if raw is None:
                return None
            return DedicatedNicConfig.from_dict(raw)
        except Exception as e:
            log_error(f"Failed to load dedicated NIC config for {container_name}: {e}")
            return None

    def load_all_configs(self) -> Dict[str, DedicatedNicConfig]:
        try:
            raw_configs = self._store.read_all()
            return {
                name: DedicatedNicConfig.from_dict(raw)
                for name, raw in raw_configs.items()
            }
        except Exception as e:
            log_error(f"Failed to load dedicated NIC configurations: {e}")
            return {}

    def delete_config(self, container_name: str) -> None:
        try:
            def _delete(data):
                if container_name in data:
                    del data[container_name]
            self._store.modify(_delete)
            log_debug(
                f"Deleted dedicated NIC config for container {container_name}"
            )
        except Exception as e:
            log_error(
                f"Failed to delete dedicated NIC config for {container_name}: {e}"
            )

    def get_container_for_nic(self, interface_name: str) -> Optional[str]:
        """Return the container name that has this interface dedicated, or None."""
        try:
            all_configs = self._store.read_all()
            for container_name, config in all_configs.items():
                if config.get("host_interface") == interface_name:
                    return container_name
            return None
        except Exception as e:
            log_error(f"Failed to look up NIC {interface_name}: {e}")
            return None
