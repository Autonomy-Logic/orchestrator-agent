from typing import Optional
from tools.serial_persistence import (
    save_serial_configs,
    load_serial_configs,
    delete_serial_configs,
    update_serial_status,
    get_serial_port_by_device_id,
    get_all_configured_serial_ports,
)


class FileSerialRepository:
    """Concrete adapter wrapping tools/serial_persistence.py file operations."""

    def save_configs(self, container_name: str, serial_configs: list) -> None:
        save_serial_configs(container_name, serial_configs)

    def load_configs(self, container_name: Optional[str] = None) -> dict:
        return load_serial_configs(container_name)

    def delete_configs(self, container_name: str) -> None:
        delete_serial_configs(container_name)

    def update_status(
        self, container_name: str, port_name: str, status: str, **kwargs
    ) -> None:
        update_serial_status(container_name, port_name, status, **kwargs)

    def get_by_device_id(self, device_id: str) -> list:
        return get_serial_port_by_device_id(device_id)

    def get_all_configured_ports(self) -> list:
        return get_all_configured_serial_ports()
