from typing import Optional

from repos.interfaces import SerialRepoInterface
from tools.json_file import JsonConfigStore
from tools.logger import log_debug, log_error, log_warning
from tools.utils import matches_device_id

SERIAL_CONFIG_FILE = "/var/orchestrator/data/serial_configs.json"


class SerialRepo(SerialRepoInterface):
    """File-backed persistence for serial port configurations."""

    def __init__(self):
        self._store = JsonConfigStore(SERIAL_CONFIG_FILE)

    def save_configs(self, container_name: str, serial_configs: list) -> None:
        try:
            initialized_configs = []
            for config in serial_configs:
                initialized_configs.append({
                    "name": config.get("name"),
                    "device_id": config.get("device_id"),
                    "container_path": config.get("container_path"),
                    "status": "disconnected",
                    "current_host_path": None,
                    "major": None,
                    "minor": None,
                })

            self._store.modify(
                lambda data: data.__setitem__(container_name, {"serial_ports": initialized_configs})
            )
            log_debug(
                f"Saved {len(serial_configs)} serial configuration(s) for container {container_name}"
            )
        except Exception as e:
            log_error(
                f"Failed to save serial configurations for {container_name}: {e}"
            )

    def load_configs(self, container_name: Optional[str] = None) -> dict:
        try:
            all_configs = self._store.read_all()

            if container_name:
                return all_configs.get(container_name, {"serial_ports": []})
            else:
                return all_configs
        except Exception as e:
            log_error(f"Failed to load serial configurations: {e}")
            return {"serial_ports": []} if container_name else {}

    def delete_configs(self, container_name: str) -> None:
        try:
            def _delete(data):
                if container_name in data:
                    del data[container_name]
                    log_debug(
                        f"Deleted serial configurations for container {container_name}"
                    )
                else:
                    log_debug(
                        f"No serial configurations found for container {container_name}"
                    )
            self._store.modify(_delete)
        except Exception as e:
            log_error(
                f"Failed to delete serial configurations for {container_name}: {e}"
            )

    def update_status(
        self, container_name: str, port_name: str, status: str, **kwargs
    ) -> None:
        try:
            def _update(data):
                if container_name not in data:
                    log_warning(
                        f"Cannot update serial status: container {container_name} not found"
                    )
                    return

                container_config = data[container_name]
                serial_ports = container_config.get("serial_ports", [])

                for port_config in serial_ports:
                    if port_config.get("name") == port_name:
                        port_config["status"] = status

                        if "current_host_path" in kwargs:
                            port_config["current_host_path"] = kwargs[
                                "current_host_path"
                            ]
                        if "major" in kwargs:
                            port_config["major"] = kwargs["major"]
                        if "minor" in kwargs:
                            port_config["minor"] = kwargs["minor"]

                        if status == "disconnected":
                            port_config["current_host_path"] = None
                            port_config["major"] = None
                            port_config["minor"] = None

                        log_debug(
                            f"Updated serial port '{port_name}' status to '{status}' for container {container_name}"
                        )
                        return

                log_warning(
                    f"Serial port '{port_name}' not found in container {container_name}"
                )

            self._store.modify(_update)
        except Exception as e:
            log_error(
                f"Failed to update serial status for {container_name}/{port_name}: {e}"
            )

    def get_by_device_id(self, device_id: str) -> list:
        try:
            all_configs = self._store.read_all()
            matches = []

            for container_name, container_config in all_configs.items():
                for port_config in container_config.get("serial_ports", []):
                    config_device_id = port_config.get("device_id", "")
                    if matches_device_id(config_device_id, device_id):
                        matches.append(
                            {
                                "container_name": container_name,
                                "serial_config": port_config.copy(),
                            }
                        )

            return matches
        except Exception as e:
            log_error(
                f"Failed to find serial port by device_id '{device_id}': {e}"
            )
            return []

    def get_all_configured_ports(self) -> list:
        try:
            all_configs = self._store.read_all()
            all_ports = []

            for container_name, container_config in all_configs.items():
                for port_config in container_config.get("serial_ports", []):
                    all_ports.append(
                        {
                            "container_name": container_name,
                            "serial_config": port_config.copy(),
                        }
                    )

            return all_ports
        except Exception as e:
            log_error(f"Failed to get all configured serial ports: {e}")
            return []
