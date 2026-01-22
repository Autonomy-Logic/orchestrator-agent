from .logger import log_error
import time


def matches_device_id(device_id: str, by_id: str) -> bool:
    """
    Check if a configured device_id matches a discovered by_id path.

    Uses bidirectional substring matching to handle cases where:
    - device_id is the full path: /dev/serial/by-id/usb-FTDI_...
    - device_id is just the device part: usb-FTDI_...
    - by_id is the full path from netmon

    Args:
        device_id: The configured device ID (from serial config)
        by_id: The discovered by-id path (from netmon)

    Returns:
        True if they match, False otherwise
    """
    if not device_id or not by_id:
        return False
    return device_id in by_id or by_id in device_id


def parse_period(period_str: str) -> tuple:
    """
    Parse a period string and return start and end timestamps.

    Args:
        period_str: Period string in format "start_timestamp,end_timestamp" (Unix timestamps in seconds)
                   or "duration" (e.g., "1h", "24h", "48h")

    Returns:
        tuple: (start_timestamp, end_timestamp) as integers
    """
    try:
        if "," in period_str:
            parts = period_str.split(",")
            start_time = int(parts[0])
            end_time = int(parts[1])
            return (start_time, end_time)
        else:
            end_time = int(time.time())
            if period_str.endswith("h"):
                hours = int(period_str[:-1])
                start_time = end_time - (hours * 3600)
            elif period_str.endswith("m"):
                minutes = int(period_str[:-1])
                start_time = end_time - (minutes * 60)
            elif period_str.endswith("d"):
                days = int(period_str[:-1])
                start_time = end_time - (days * 86400)
            else:
                seconds = int(period_str)
                start_time = end_time - seconds
            return (start_time, end_time)
    except Exception as e:
        log_error(f"Error parsing period '{period_str}': {e}")
        end_time = int(time.time())
        start_time = end_time - 3600
        return (start_time, end_time)
