"""
DNS and reconnection utilities for network resilience.

Provides functions for DNS health checks, exponential backoff calculation,
and DNS error detection to handle network transitions gracefully.
"""
import socket
import random
from time import sleep
from tools.logger import log_debug, log_warning, log_info

# DNS health check configuration
DNS_HEALTH_CHECK_TIMEOUT = 5.0  # DNS health check timeout in seconds
DNS_HEALTH_CHECK_RETRIES = 3  # Number of DNS health check retries

# Reconnection configuration
RECONNECT_DELAY_BASE = 1.0  # Initial delay in seconds
RECONNECT_DELAY_MAX = 30.0  # Maximum delay in seconds
RECONNECT_JITTER = 0.3  # Jitter factor (30%)


def parse_server_address(server_url: str) -> tuple[str, int]:
    """
    Parse server URL into host and port.

    Args:
        server_url: Server URL in host:port format

    Returns:
        Tuple of (host, port)
    """
    parts = server_url.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 443
    return host, port


def wait_for_dns(host: str, port: int, max_retries: int = DNS_HEALTH_CHECK_RETRIES) -> bool:
    """
    Wait until DNS resolution succeeds for the given host.

    This helps avoid rapid reconnection attempts when the network is still
    transitioning (e.g., after WiFi change).

    Args:
        host: Hostname to resolve
        port: Port number (for getaddrinfo)
        max_retries: Maximum number of DNS resolution attempts

    Returns:
        True if DNS resolution succeeded, False if all retries failed
    """
    for attempt in range(max_retries):
        try:
            # Force fresh DNS lookup by not using any caching hints
            socket.setdefaulttimeout(DNS_HEALTH_CHECK_TIMEOUT)
            result = socket.getaddrinfo(
                host, port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
                socket.AI_ADDRCONFIG  # Only return addresses reachable from this host
            )
            if result:
                log_debug(f"DNS health check passed for {host}:{port}")
                return True
        except socket.gaierror as e:
            log_warning(f"DNS health check failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                sleep(2)  # Wait before retry
        except Exception as e:
            log_warning(f"DNS health check error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                sleep(2)

    return False


def calculate_backoff(attempt: int) -> float:
    """
    Calculate reconnection delay with exponential backoff and jitter.

    Args:
        attempt: Current reconnection attempt number (0-indexed)

    Returns:
        Delay in seconds before next reconnection attempt
    """
    # Exponential backoff: base * 2^attempt, capped at max
    delay = min(RECONNECT_DELAY_BASE * (2 ** attempt), RECONNECT_DELAY_MAX)

    # Add jitter (±30%) to prevent thundering herd
    jitter = delay * RECONNECT_JITTER * (2 * random.random() - 1)
    delay = max(RECONNECT_DELAY_BASE, delay + jitter)

    return delay


def is_dns_error(error: Exception) -> bool:
    """
    Check if the error is related to DNS resolution failure.

    Args:
        error: The exception to check

    Returns:
        True if this appears to be a DNS-related error
    """
    error_str = str(error).lower()
    dns_error_indicators = [
        "name resolution",
        "getaddrinfo",
        "nodename nor servname",
        "name or service not known",
        "temporary failure",
        "dns",
    ]
    return any(indicator in error_str for indicator in dns_error_indicators)


def perform_dns_health_check(server_url: str, reconnect_attempt: int) -> bool:
    """
    Perform DNS health check before reconnection attempt.

    Args:
        server_url: Server URL in host:port format
        reconnect_attempt: Current reconnection attempt number

    Returns:
        True if DNS check passed or not needed, False if DNS failed
    """
    if reconnect_attempt == 0:
        return True

    host, port = parse_server_address(server_url)
    log_info(f"Performing DNS health check for {host}...")

    if wait_for_dns(host, port):
        return True

    log_warning(
        f"DNS resolution failed after {DNS_HEALTH_CHECK_RETRIES} attempts. "
        f"Network may still be transitioning."
    )
    return False
