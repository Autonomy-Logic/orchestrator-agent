from repos.interfaces import VNICRepoInterface
from tools.json_file import JsonConfigStore
from tools.logger import log_debug, log_error, log_warning

VNIC_CONFIG_FILE = "/var/orchestrator/runtime_vnics.json"


class VNICRepo(VNICRepoInterface):
    """File-backed persistence for vNIC configurations."""

    def __init__(self):
        self._store = JsonConfigStore(VNIC_CONFIG_FILE)

    def save_configs(self, container_name: str, vnic_configs: list) -> None:
        try:
            self._store.modify(lambda data: data.__setitem__(container_name, vnic_configs))
            log_debug(
                f"Saved vNIC configurations for container {container_name}"
            )
        except Exception as e:
            log_error(
                f"Failed to save vNIC configurations for {container_name}: {e}"
            )

    def load_all_configs(self) -> dict:
        try:
            return self._store.read_all()
        except Exception as e:
            log_error(f"Failed to load vNIC configurations: {e}")
            return {}

    def load_configs(self, container_name: str) -> list:
        try:
            all_configs = self._store.read_all()
            return all_configs.get(container_name, [])
        except Exception as e:
            log_error(f"Failed to load vNIC configurations: {e}")
            return []

    def delete_configs(self, container_name: str) -> None:
        try:
            def _delete(data):
                if container_name in data:
                    del data[container_name]
            self._store.modify(_delete)
            log_debug(
                f"Deleted vNIC configurations for container {container_name}"
            )
        except Exception as e:
            log_error(
                f"Failed to delete vNIC configurations for {container_name}: {e}"
            )
