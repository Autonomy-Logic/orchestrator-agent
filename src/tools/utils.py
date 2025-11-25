from .logger import log_error
import time


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
