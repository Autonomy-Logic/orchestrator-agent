"""
Serial port configuration persistence for vPLC containers.

This module manages serial port configurations that allow vPLC containers to access
host serial ports (USB-to-serial adapters and native serial ports) without requiring
container restarts when devices are hot-plugged.

The persistence layer tracks:
- User-defined serial port configurations (device_id, container_path, etc.)
- Runtime state (connection status, current host path, major/minor numbers)

File location: /var/orchestrator/data/serial_configs.json

Schema:
{
  "container_name": {
    "serial_ports": [
      {
        "name": "modbus_rtu",
        "device_id": "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0",
        "container_path": "/dev/modbus0",
        "baud_rate": 9600,
        "status": "connected",
        "current_host_path": "/dev/ttyUSB0",
        "major": 188,
        "minor": 0
      }
    ]
  }
}
"""

import json
import os
import threading
from tools.logger import log_debug, log_error, log_warning, log_info

SERIAL_CONFIG_FILE = "/var/orchestrator/data/serial_configs.json"

# Lock for thread-safe file operations
_file_lock = threading.Lock()


def _ensure_config_dir():
    """Ensure the configuration directory exists."""
    config_dir = os.path.dirname(SERIAL_CONFIG_FILE)
    os.makedirs(config_dir, exist_ok=True)


def _read_config_file() -> dict:
    """
    Read the serial config file with thread safety.

    Returns:
        dict: All serial configurations, or empty dict if file doesn't exist.
    """
    if not os.path.exists(SERIAL_CONFIG_FILE):
        return {}

    try:
        with open(SERIAL_CONFIG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log_error(f"Failed to parse serial config file: {e}")
        return {}
    except Exception as e:
        log_error(f"Failed to read serial config file: {e}")
        return {}


def _write_config_file(configs: dict):
    """
    Write to the serial config file with thread safety.

    Args:
        configs: Complete configuration dict to write.
    """
    _ensure_config_dir()

    with open(SERIAL_CONFIG_FILE, "w") as f:
        json.dump(configs, f, indent=2)


def save_serial_configs(container_name: str, serial_configs: list):
    """
    Save serial port configurations for a runtime container.

    This initializes the configuration with user-provided settings.
    Runtime state (status, host_path, major/minor) is set to defaults
    and will be updated by the DeviceEventListener when devices are detected.

    Args:
        container_name: Name of the runtime container
        serial_configs: List of serial port configurations, each containing:
            - name: User-friendly name for the serial port
            - device_id: Stable USB device identifier (from /dev/serial/by-id/)
            - container_path: Path inside container (e.g., "/dev/modbus0")
            - baud_rate: Baud rate (optional, for documentation)
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()

            # Initialize each serial config with runtime state defaults
            initialized_configs = []
            for config in serial_configs:
                initialized_config = {
                    "name": config.get("name"),
                    "device_id": config.get("device_id"),
                    "container_path": config.get("container_path"),
                    "baud_rate": config.get("baud_rate"),
                    # Runtime state - will be populated by DeviceEventListener
                    "status": "disconnected",
                    "current_host_path": None,
                    "major": None,
                    "minor": None,
                }
                initialized_configs.append(initialized_config)

            all_configs[container_name] = {
                "serial_ports": initialized_configs
            }

            _write_config_file(all_configs)

            log_debug(f"Saved {len(serial_configs)} serial configuration(s) for container {container_name}")

        except Exception as e:
            log_error(f"Failed to save serial configurations for {container_name}: {e}")


def load_serial_configs(container_name: str = None) -> dict:
    """
    Load serial port configurations for a runtime container or all containers.

    Args:
        container_name: Name of the runtime container (optional)

    Returns:
        If container_name is provided, returns dict with 'serial_ports' list for that container.
        If container_name is None, returns dict of all container serial configs.
        Returns empty dict/list structure if not found.
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()

            if container_name:
                return all_configs.get(container_name, {"serial_ports": []})
            else:
                return all_configs

        except Exception as e:
            log_error(f"Failed to load serial configurations: {e}")
            return {"serial_ports": []} if container_name else {}


def delete_serial_configs(container_name: str):
    """
    Delete serial port configurations for a runtime container.

    Called when a container is deleted to clean up associated configs.

    Args:
        container_name: Name of the runtime container
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()

            if container_name in all_configs:
                del all_configs[container_name]
                _write_config_file(all_configs)
                log_debug(f"Deleted serial configurations for container {container_name}")
            else:
                log_debug(f"No serial configurations found for container {container_name}")

        except Exception as e:
            log_error(f"Failed to delete serial configurations for {container_name}: {e}")


def update_serial_status(container_name: str, port_name: str, status: str, **kwargs):
    """
    Update the runtime status of a specific serial port.

    Called by DeviceEventListener when device state changes (plug/unplug events).

    Args:
        container_name: Name of the runtime container
        port_name: Name of the serial port (matches 'name' field in config)
        status: New status - "connected", "disconnected", or "error"
        **kwargs: Additional fields to update:
            - current_host_path: Current /dev/ttyUSBx path on host
            - major: Device major number
            - minor: Device minor number
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()

            if container_name not in all_configs:
                log_warning(f"Cannot update serial status: container {container_name} not found")
                return

            container_config = all_configs[container_name]
            serial_ports = container_config.get("serial_ports", [])

            port_found = False
            for port_config in serial_ports:
                if port_config.get("name") == port_name:
                    port_config["status"] = status

                    # Update optional runtime state fields
                    if "current_host_path" in kwargs:
                        port_config["current_host_path"] = kwargs["current_host_path"]
                    if "major" in kwargs:
                        port_config["major"] = kwargs["major"]
                    if "minor" in kwargs:
                        port_config["minor"] = kwargs["minor"]

                    # Clear runtime state on disconnect
                    if status == "disconnected":
                        port_config["current_host_path"] = None
                        port_config["major"] = None
                        port_config["minor"] = None

                    port_found = True
                    break

            if not port_found:
                log_warning(f"Serial port '{port_name}' not found in container {container_name}")
                return

            _write_config_file(all_configs)
            log_debug(f"Updated serial port '{port_name}' status to '{status}' for container {container_name}")

        except Exception as e:
            log_error(f"Failed to update serial status for {container_name}/{port_name}: {e}")


def get_serial_port_by_device_id(device_id: str) -> list:
    """
    Find all containers that have a serial port configured for a given device_id.

    Used by DeviceEventListener to match incoming device events to container configs.

    Args:
        device_id: The stable device identifier (e.g., "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0")

    Returns:
        List of dicts, each containing:
            - container_name: Name of the container
            - serial_config: The matching serial port configuration
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()
            matches = []

            for container_name, container_config in all_configs.items():
                for port_config in container_config.get("serial_ports", []):
                    config_device_id = port_config.get("device_id", "")
                    # Match if the device_id contains or equals the configured ID
                    # This handles both full paths and partial IDs
                    if config_device_id and (config_device_id in device_id or device_id in config_device_id):
                        matches.append({
                            "container_name": container_name,
                            "serial_config": port_config.copy()
                        })

            return matches

        except Exception as e:
            log_error(f"Failed to find serial port by device_id '{device_id}': {e}")
            return []


def get_all_configured_serial_ports() -> list:
    """
    Get all configured serial ports across all containers.

    Used for initial device sync on startup to recreate device nodes.

    Returns:
        List of dicts, each containing:
            - container_name: Name of the container
            - serial_config: The serial port configuration
    """
    with _file_lock:
        try:
            all_configs = _read_config_file()
            all_ports = []

            for container_name, container_config in all_configs.items():
                for port_config in container_config.get("serial_ports", []):
                    all_ports.append({
                        "container_name": container_name,
                        "serial_config": port_config.copy()
                    })

            return all_ports

        except Exception as e:
            log_error(f"Failed to get all configured serial ports: {e}")
            return []
