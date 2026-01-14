"""
System information collection module for the orchestrator agent.
Collects static system information at boot time (IP addresses, OS, kernel, CPU count, etc.).
"""

import psutil
import platform
import socket
from typing import List, Dict, Tuple

# Virtual interface prefixes to filter out (Docker bridges, VPNs, etc.)
VIRTUAL_INTERFACE_PREFIXES = [
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    "tailscale",
    "zt",
    "cni",
    "flannel",
    "kube-ipvs",
    "wg",
    "cilium",
    "macvtap",
]


def _is_physical_interface(interface_name: str) -> bool:
    """
    Check if an interface is a physical (non-virtual) interface.

    Args:
        interface_name: Name of the network interface

    Returns:
        bool: True if the interface is physical, False if virtual
    """
    interface_lower = interface_name.lower()
    for prefix in VIRTUAL_INTERFACE_PREFIXES:
        if interface_lower.startswith(prefix):
            return False
    return True


def get_ip_addresses() -> List[Tuple[str, str]]:
    """
    Get all IP addresses from physical network interfaces.
    Filters out virtual interfaces (Docker bridges, VPNs, etc.).

    Returns:
        List[Tuple[str, str]]: List of (interface_name, ip_address) tuples
    """
    ip_addresses = []

    net_if_addrs = psutil.net_if_addrs()

    for interface_name, addresses in net_if_addrs.items():
        if not _is_physical_interface(interface_name):
            continue

        for address in addresses:
            if address.family == socket.AF_INET:
                if not address.address.startswith("127."):
                    ip_addresses.append((interface_name, address.address))

    return ip_addresses


def get_total_memory() -> int:
    """
    Get total RAM memory installed in MB.

    Returns:
        int: Total memory in MB
    """
    memory = psutil.virtual_memory()
    return int(memory.total / (1024 * 1024))


def get_cpu_count() -> int:
    """
    Get the number of CPUs installed.

    Returns:
        int: Number of CPUs
    """
    return psutil.cpu_count(logical=True)


def get_os_info() -> str:
    """
    Get operating system information.

    Returns:
        str: OS information (e.g., "Ubuntu Core 24")
    """
    try:
        import distro

        os_name = distro.name(pretty=True)
        if os_name:
            return os_name
    except ImportError:
        pass

    system = platform.system()
    release = platform.release()
    return f"{system} {release}"


def get_kernel_version() -> str:
    """
    Get Linux kernel version.

    Returns:
        str: Kernel version
    """
    return platform.release()


def get_total_disk() -> int:
    """
    Get total disk space installed in GB.

    Returns:
        int: Total disk space in GB
    """
    total_space = 0
    seen_devices = set()

    SKIP_FSTYPES = {
        "tmpfs",
        "devtmpfs",
        "overlay",
        "squashfs",
        "ramfs",
        "proc",
        "sysfs",
        "cgroup",
        "cgroup2",
        "debugfs",
        "tracefs",
        "pstore",
        "autofs",
        "devpts",
        "mqueue",
        "hugetlbfs",
        "fusectl",
        "none",
    }

    partitions = psutil.disk_partitions(all=False)

    for partition in partitions:
        if partition.fstype.lower() in SKIP_FSTYPES:
            continue

        if not partition.device or partition.device in seen_devices:
            continue

        seen_devices.add(partition.device)

        try:
            usage = psutil.disk_usage(partition.mountpoint)
            total_space += usage.total
        except (PermissionError, OSError):
            continue

    return int(total_space / (1024 * 1024 * 1024))


def get_system_info() -> Dict:
    """
    Get all static system information.
    This should be called once at boot time and cached.

    Returns:
        Dict: Dictionary containing all system information:
            - ip_addresses: List[Dict] - List of {interface, ip_address} for each physical interface
            - memory: int - Total RAM in MB
            - cpu: int - Number of CPUs
            - os: str - Operating system
            - kernel: str - Kernel version
            - disk: int - Total disk space in GB
    """
    # Convert list of tuples to list of dicts for JSON serialization
    ip_address_tuples = get_ip_addresses()
    ip_addresses = [
        {"interface": iface, "ip_address": ip} for iface, ip in ip_address_tuples
    ]

    return {
        "ip_addresses": ip_addresses,
        "memory": get_total_memory(),
        "cpu": get_cpu_count(),
        "os": get_os_info(),
        "kernel": get_kernel_version(),
        "disk": get_total_disk(),
    }


_system_info = get_system_info()


def get_cached_system_info() -> Dict:
    """
    Get cached system information.

    Returns:
        Dict: Cached system information
    """
    return _system_info.copy()
