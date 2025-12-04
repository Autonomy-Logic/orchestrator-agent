"""
Circular buffer for storing CPU and memory usage data.
Stores up to 48 hours of data at 5-second intervals.

This module provides:
- BaseUsageBuffer: Base class with common circular buffer logic
- UsageBuffer: Singleton buffer for orchestrator agent metrics (inherits from BaseUsageBuffer)
"""

import time
from typing import List, Dict, Optional
from collections import deque


class BaseUsageBuffer:
    """
    Base class for circular buffer storing CPU and memory usage data.

    Stores data points with timestamp, CPU usage, and memory usage.
    Automatically removes old data when the buffer is full (48 hours at 5-second intervals).
    Data is stored in RAM and lost on reboot.

    This class can be subclassed or used directly for storing usage metrics.
    """

    MAX_SAMPLES = 48 * 3600 // 5

    def __init__(self):
        """Initialize the circular buffer."""
        self._buffer = deque(maxlen=self.MAX_SAMPLES)

    def add_sample(self, cpu_usage: float, memory_usage: float) -> None:
        """
        Add a new sample to the buffer.

        Args:
            cpu_usage: CPU usage percentage (0-100)
            memory_usage: Memory usage in MB
        """
        timestamp = int(time.time())
        cpu = int(cpu_usage)
        memory = int(memory_usage)

        self._buffer.append((timestamp, cpu, memory))

    def get_samples(
        self, start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict]:
        """
        Get samples within a time range.

        Args:
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp', 'cpu', and 'memory' keys
        """
        if end_time is None:
            end_time = int(time.time())

        if start_time is None:
            return [
                {"timestamp": ts, "cpu": cpu, "memory": mem}
                for ts, cpu, mem in self._buffer
                if ts <= end_time
            ]

        return [
            {"timestamp": ts, "cpu": cpu, "memory": mem}
            for ts, cpu, mem in self._buffer
            if start_time <= ts <= end_time
        ]

    def get_cpu_usage(
        self, start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict]:
        """
        Get CPU usage samples within a time range.

        Args:
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp' and 'cpu' keys
        """
        samples = self.get_samples(start_time, end_time)
        return [{"timestamp": s["timestamp"], "cpu": s["cpu"]} for s in samples]

    def get_memory_usage(
        self, start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict]:
        """
        Get memory usage samples within a time range.

        Args:
            start_time: Start timestamp (Unix timestamp in seconds). If None, returns all samples.
            end_time: End timestamp (Unix timestamp in seconds). If None, uses current time.

        Returns:
            List of dictionaries with 'timestamp' and 'memory' keys
        """
        samples = self.get_samples(start_time, end_time)
        return [{"timestamp": s["timestamp"], "memory": s["memory"]} for s in samples]

    def get_buffer_size(self) -> int:
        """
        Get the current number of samples in the buffer.

        Returns:
            int: Number of samples
        """
        return len(self._buffer)

    def clear(self) -> None:
        """Clear all samples from the buffer."""
        self._buffer.clear()


class UsageBuffer(BaseUsageBuffer):
    """
    Circular buffer for storing orchestrator agent CPU and memory usage data.

    Inherits all functionality from BaseUsageBuffer.
    This class exists for backwards compatibility and semantic clarity.
    """

    pass


_usage_buffer = UsageBuffer()


def get_usage_buffer() -> UsageBuffer:
    """
    Get the global usage buffer instance for the orchestrator agent.

    Returns:
        UsageBuffer: The global usage buffer
    """
    return _usage_buffer
