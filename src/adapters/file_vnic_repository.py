from typing import Optional, Union
from tools.vnic_persistence import (
    save_vnic_configs,
    load_vnic_configs,
    delete_vnic_configs,
)


class FileVnicRepository:
    """Concrete adapter wrapping tools/vnic_persistence.py file operations."""

    def save_configs(self, container_name: str, vnic_configs: list) -> None:
        save_vnic_configs(container_name, vnic_configs)

    def load_configs(self, container_name: Optional[str] = None) -> Union[dict, list]:
        return load_vnic_configs(container_name)

    def delete_configs(self, container_name: str) -> None:
        delete_vnic_configs(container_name)
