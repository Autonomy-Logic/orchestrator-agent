"""
Usage buffer manager for storing CPU and memory usage data for multiple devices.
Each device has its own circular buffer storing up to 48 hours of data at 5-second intervals.

This module provides:
- DevicesUsageBuffer: Manager class that maintains a buffer per device
"""

from typing import List, Dict, Optional
from threading import Lock
from tools.usage_buffer import BaseUsageBuffer
from tools.logger import log_debug, log_info, log_warning


class DevicesUsageBuffer:
    """
    Manager class for storing usage data for multiple devices (containers).

    Maintains a dictionary of BaseUsageBuffer instances, one per device.
    Thread-safe for concurrent access from multiple coroutines.
    """

    def __init__(self):
        """Initialize the devices usage buffer manager."""
        self._buffers: Dict[str, BaseUsageBuffer] = {}
        self._lock = Lock()

    def add_device(self, device_id: str) -> None:
        """
        Register a new device and create its usage buffer.

        Args:
            device_id: Unique identifier for the device (container name)
        """
        with self._lock:
            if device_id not in self._buffers:
                self._buffers[device_id] = BaseUsageBuffer()
                log_info(f"Created usage buffer for device {device_id}")
            else:
                log_debug(f"Usage buffer for device {device_id} already exists")

    def remove_device(self, device_id: str) -> None:
        """
        Remove a device and its usage buffer.

        Args:
            device_id: Unique identifier for the device (container name)
        """
        with self._lock:
            if device_id in self._buffers:
                del self._buffers[device_id]
                log_info(f"Removed usage buffer for device {device_id}")
            else:
                log_debug(f"Usage buffer for device {device_id} not found")

    def has_device(self, device_id: str) -> bool:
        """
        Check if a device is registered.

        Args:
            device_id: Unique identifier for the device (container name)

        Returns:
            bool: True if the device is registered, False otherwise
        """
        with self._lock:
            return device_id in self._buffers

    def get_device_ids(self) -> List[str]:
        """
        Get a list of all registered device IDs.

        Returns:
            List[str]: List of device IDs
        """
        with self._lock:
            return list(self._buffers.keys())

    def add_sample(self, device_id: str, cpu_usage: float, memory_usage: float) -> None:
        """
        Add a usage sample for a specific device.

        Args:
            device_id: Unique identifier for the device (container name)
            cpu_usage: CPU usage percentage (0-100)
            memory_usage: Memory usage in MB
        """
        with self._lock:
            if device_id in self._buffers:
                self._buffers[device_id].add_sample(cpu_usage, memory_usage)
            else:
                log_warning(
                    f"Cannot add sample for device {device_id}: device not registered"
                )

    def get_samples(
        self,
        device_id: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get samples for a specific device within a time range.

        Args:
            device_id: Unique identifier for the device (container name)
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp', 'cpu', and 'memory' keys.
            Returns empty list if device is not registered.
        """
        with self._lock:
            if device_id in self._buffers:
                return self._buffers[device_id].get_samples(start_time, end_time)
            else:
                log_warning(
                    f"Cannot get samples for device {device_id}: device not registered"
                )
                return []

    def get_cpu_usage(
        self,
        device_id: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get CPU usage samples for a specific device within a time range.

        Args:
            device_id: Unique identifier for the device (container name)
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp' and 'cpu' keys.
            Returns empty list if device is not registered.
        """
        with self._lock:
            if device_id in self._buffers:
                return self._buffers[device_id].get_cpu_usage(start_time, end_time)
            else:
                log_warning(
                    f"Cannot get CPU usage for device {device_id}: device not registered"
                )
                return []

    def get_memory_usage(
        self,
        device_id: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get memory usage samples for a specific device within a time range.

        Args:
            device_id: Unique identifier for the device (container name)
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp' and 'memory' keys.
            Returns empty list if device is not registered.
        """
        with self._lock:
            if device_id in self._buffers:
                return self._buffers[device_id].get_memory_usage(start_time, end_time)
            else:
                log_warning(
                    f"Cannot get memory usage for device {device_id}: device not registered"
                )
                return []

    def get_buffer_size(self, device_id: str) -> int:
        """
        Get the current number of samples in a device's buffer.

        Args:
            device_id: Unique identifier for the device (container name)

        Returns:
            int: Number of samples, or 0 if device is not registered
        """
        with self._lock:
            if device_id in self._buffers:
                return self._buffers[device_id].get_buffer_size()
            else:
                return 0

    def clear_device(self, device_id: str) -> None:
        """
        Clear all samples from a device's buffer.

        Args:
            device_id: Unique identifier for the device (container name)
        """
        with self._lock:
            if device_id in self._buffers:
                self._buffers[device_id].clear()
                log_debug(f"Cleared usage buffer for device {device_id}")

    def clear_all(self) -> None:
        """Clear all samples from all device buffers."""
        with self._lock:
            for buffer in self._buffers.values():
                buffer.clear()
            log_debug("Cleared all device usage buffers")


_devices_usage_buffer = DevicesUsageBuffer()


def get_devices_usage_buffer() -> DevicesUsageBuffer:
    """
    Get the global devices usage buffer instance.

    Returns:
        DevicesUsageBuffer: The global devices usage buffer manager
    """
    return _devices_usage_buffer
