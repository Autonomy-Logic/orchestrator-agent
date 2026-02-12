import asyncio
import os
from typing import Dict, List, Optional, Callable
from tools.logger import log_info, log_debug, log_warning, log_error
from tools.utils import matches_device_id
class SerialDeviceManager:
    """
    Manages serial device matching and provisioning for runtime containers.

    Handles device discovery/change events from netmon, creates device nodes
    inside containers, and tracks currently available serial devices.
    """

    def __init__(self, serial_repo, container_runtime):
        self.serial_repo = serial_repo
        self.container_runtime = container_runtime
        # Serial device cache: by_id -> device_info
        self.device_cache: Dict[str, Dict] = {}
        # Callbacks for serial device status changes
        self.device_update_callbacks: List[Callable] = []

    async def handle_device_discovery(self, data: dict):
        """
        Handle device discovery event from netmon.

        Called on initial connection to netmon. Populates the device cache
        with all currently available serial devices, then triggers resync.
        """
        devices = data.get("devices", [])
        log_info(f"Discovered {len(devices)} serial devices")

        self.device_cache.clear()
        for device in devices:
            by_id = device.get("by_id")
            if by_id:
                self.device_cache[by_id] = device
                log_debug(
                    f"Cached device: {device.get('path')} -> {by_id} "
                    f"(major={device.get('major')}, minor={device.get('minor')})"
                )

        await self._resync_serial_devices()

    async def handle_device_change(self, data: dict):
        """
        Handle device add/remove event from netmon.

        Called when a USB serial device is plugged in or unplugged.
        """

        action = data.get("action")
        device = data.get("device", {})

        if not action or not device:
            log_warning("Invalid device change event: missing action or device")
            return

        device_path = device.get("path")
        by_id = device.get("by_id")

        log_info(f"Device {action}: {device_path} (by_id: {by_id})")

        if action == "add":
            if by_id:
                self.device_cache[by_id] = device

            matches = self._match_device_to_configs(device)

            for match in matches:
                container_name = match["container_name"]
                serial_config = match["serial_config"]
                port_name = serial_config.get("name")
                container_path = serial_config.get("container_path")

                log_info(
                    f"Creating device node for {container_name}:{port_name} "
                    f"({device_path} -> {container_path})"
                )

                success = await self._create_device_node(
                    container_name,
                    device_path,
                    container_path,
                    device.get("major"),
                    device.get("minor"),
                )

                if success:
                    self.serial_repo.update_status(
                        container_name,
                        port_name,
                        "connected",
                        current_host_path=device_path,
                        major=device.get("major"),
                        minor=device.get("minor"),
                    )
                    log_info(f"Device node created successfully for {container_name}:{port_name}")

                    await self._notify_device_callbacks(
                        container_name, port_name, "connected", device
                    )
                else:
                    log_error(f"Failed to create device node for {container_name}:{port_name}")

        elif action == "remove":
            if not by_id:
                for cached_by_id, cached_device in list(self.device_cache.items()):
                    if cached_device.get("path") == device_path:
                        by_id = cached_by_id
                        device = cached_device
                        break

            if by_id and by_id in self.device_cache:
                del self.device_cache[by_id]

            matches = self._match_device_to_configs(device)

            for match in matches:
                container_name = match["container_name"]
                serial_config = match["serial_config"]
                port_name = serial_config.get("name")

                log_info(f"Device disconnected for {container_name}:{port_name}")

                self.serial_repo.update_status(container_name, port_name, "disconnected")

                await self._notify_device_callbacks(
                    container_name, port_name, "disconnected", device
                )

    def _match_device_to_configs(self, device: dict) -> List[dict]:
        """
        Find all containers that have a serial port configured for this device.

        Matches by device_id (the stable /dev/serial/by-id/ identifier).
        """

        by_id = device.get("by_id")
        if not by_id:
            device_path = device.get("path")
            if not device_path:
                return []

            device_basename = os.path.basename(device_path)

            log_debug(f"No by_id for device {device_path}, falling back to path-based matching")
            matches = []
            all_configs = self.serial_repo.load_configs()

            for container_name, container_config in all_configs.items():
                for port_config in container_config.get("serial_ports", []):
                    config_device_id = port_config.get("device_id", "")
                    if device_basename in config_device_id:
                        matches.append({
                            "container_name": container_name,
                            "serial_config": port_config.copy(),
                        })

            return matches

        return self.serial_repo.get_by_device_id(by_id)

    async def _create_device_node(
        self,
        container_name: str,
        host_device_path: str,
        container_path: str,
        major: Optional[int] = None,
        minor: Optional[int] = None,
    ) -> bool:
        """
        Create a device node inside a running container.

        Uses Docker SDK exec_run to create the device node without restarting
        the container.
        """

        try:
            if major is None or minor is None:
                try:
                    stat_info = os.stat(host_device_path)
                    major = os.major(stat_info.st_rdev)
                    minor = os.minor(stat_info.st_rdev)
                except (OSError, FileNotFoundError) as e:
                    log_error(f"Cannot stat host device {host_device_path}: {e}")
                    return False

            try:
                container = self.container_runtime.get_container(container_name)
                if container.status != "running":
                    log_warning(f"Container {container_name} is not running, cannot create device node")
                    return False
            except self.container_runtime.NotFoundError:
                log_error(f"Container {container_name} not found")
                return False

            rm_result = await asyncio.to_thread(
                container.exec_run,
                ["rm", "-f", container_path],
                user="root",
            )
            if rm_result.exit_code != 0:
                log_debug(f"rm -f {container_path} returned {rm_result.exit_code} (may not exist)")

            mknod_result = await asyncio.to_thread(
                container.exec_run,
                ["mknod", container_path, "c", str(major), str(minor)],
                user="root",
            )

            if mknod_result.exit_code != 0:
                stderr = mknod_result.output.decode("utf-8", errors="replace")
                log_error(f"mknod failed for {container_name}:{container_path}: {stderr}")
                return False

            chmod_result = await asyncio.to_thread(
                container.exec_run,
                ["chmod", "666", container_path],
                user="root",
            )

            if chmod_result.exit_code != 0:
                stderr = chmod_result.output.decode("utf-8", errors="replace")
                log_warning(f"chmod failed for {container_name}:{container_path}: {stderr}")

            log_debug(
                f"Created device node {container_path} in {container_name} "
                f"(major={major}, minor={minor})"
            )
            return True

        except Exception as e:
            log_error(f"Error creating device node in {container_name}: {e}")
            return False

    async def _remove_device_node(self, container_name: str, container_path: str) -> bool:
        """Remove a device node from inside a container."""

        try:
            try:
                container = self.container_runtime.get_container(container_name)
                if container.status != "running":
                    log_debug(f"Container {container_name} is not running, skipping device node removal")
                    return True
            except self.container_runtime.NotFoundError:
                log_debug(f"Container {container_name} not found, skipping device node removal")
                return True

            result = await asyncio.to_thread(
                container.exec_run,
                ["rm", "-f", container_path],
                user="root",
            )

            if result.exit_code != 0:
                stderr = result.output.decode("utf-8", errors="replace")
                log_warning(f"Failed to remove device node {container_path} from {container_name}: {stderr}")
                return False

            log_debug(f"Removed device node {container_path} from {container_name}")
            return True

        except Exception as e:
            log_error(f"Error removing device node from {container_name}: {e}")
            return False

    async def resync_serial_devices(self):
        """
        Public method to resync serial device nodes for all configured containers.

        Called after container creation or device hot-plug to ensure all containers
        have their configured serial devices available.
        """
        await self._resync_serial_devices()

    async def _resync_serial_devices(self):
        """
        Internal implementation of serial device resync.

        Called after device_discovery to ensure all containers have their
        configured serial devices available (if the devices are currently connected).
        """

        try:
            all_configured = self.serial_repo.get_all_configured_ports()
            if not all_configured:
                log_debug("No serial port configurations found, skipping resync")
                return

            log_info(f"Resyncing serial devices for {len(all_configured)} configured port(s)...")

            stale_containers = set()

            for config_entry in all_configured:
                container_name = config_entry["container_name"]
                serial_config = config_entry["serial_config"]
                port_name = serial_config.get("name")
                device_id = serial_config.get("device_id")
                container_path = serial_config.get("container_path")

                if not device_id or not container_path:
                    log_warning(f"Incomplete serial config for {container_name}:{port_name}, skipping")
                    continue

                try:
                    container = self.container_runtime.get_container(container_name)
                    if container.status != "running":
                        log_debug(f"Container {container_name} is not running, skipping serial resync")
                        continue
                except self.container_runtime.NotFoundError:
                    log_debug(f"Container {container_name} no longer exists, marking for cleanup")
                    stale_containers.add(container_name)
                    continue

                matching_device = None
                for by_id, device in self.device_cache.items():
                    if matches_device_id(device_id, by_id):
                        matching_device = device
                        break

                if not matching_device:
                    log_debug(
                        f"Device {device_id} not currently connected for {container_name}:{port_name}"
                    )
                    self.serial_repo.update_status(container_name, port_name, "disconnected")
                    continue

                device_path = matching_device.get("path")
                major = matching_device.get("major")
                minor = matching_device.get("minor")

                log_info(
                    f"Resyncing device for {container_name}:{port_name}: "
                    f"{device_path} -> {container_path}"
                )

                success = await self._create_device_node(
                    container_name,
                    device_path,
                    container_path,
                    major,
                    minor,
                )

                if success:
                    self.serial_repo.update_status(
                        container_name,
                        port_name,
                        "connected",
                        current_host_path=device_path,
                        major=major,
                        minor=minor,
                    )
                    log_info(f"Serial device resynced for {container_name}:{port_name}")
                else:
                    self.serial_repo.update_status(container_name, port_name, "error")
                    log_error(f"Failed to resync serial device for {container_name}:{port_name}")

            for stale_container in stale_containers:
                log_info(f"Cleaning up stale serial config for deleted container {stale_container}")
                self.serial_repo.delete_configs(stale_container)

            log_info("Serial device resync completed")

        except Exception as e:
            log_error(f"Error during serial device resync: {e}")

    async def _notify_device_callbacks(
        self,
        container_name: str,
        port_name: str,
        status: str,
        device: dict,
    ):
        """Notify registered callbacks about device status changes."""
        for callback in self.device_update_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(container_name, port_name, status, device)
                else:
                    callback(container_name, port_name, status, device)
            except Exception as e:
                log_error(f"Error in device update callback: {e}")

    def register_device_callback(self, callback: Callable):
        """Register a callback to be called when device status changes."""
        self.device_update_callbacks.append(callback)

    def get_available_devices(self) -> List[dict]:
        """Get list of currently available serial devices."""
        return list(self.device_cache.values())

    def get_device_by_id(self, device_id: str) -> Optional[dict]:
        """Get device info by its stable device_id."""
        for by_id, device in self.device_cache.items():
            if matches_device_id(device_id, by_id):
                return device
        return None
