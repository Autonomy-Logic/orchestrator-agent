"""
System information collection module for the orchestrator agent.
Collects static system information at boot time (memory, CPU, OS, kernel, disk)
and dynamic IP addresses from the interface cache.
"""

import psutil
import platform
from typing import List, Dict
from tools.system_metrics import _iter_disk_usage

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


def get_ip_addresses(interface_cache) -> List[Dict[str, str]]:
    """
    Get all IP addresses from physical HOST network interfaces.
    Uses the interface cache populated by the netmon sidecar to access host
    network information from within the container.
    Filters out virtual interfaces (Docker bridges, VPNs, etc.).

    Args:
        interface_cache: NetworkInterfaceCacheRepo instance

    Returns:
        List[Dict[str, str]]: List of {"interface": name, "ip_address": ip} dicts
    """
    ip_addresses = []

    # Take a snapshot for thread safety (cache may be updated by netmon events)
    cache_snapshot = interface_cache.get_all_interfaces()

    for interface_name, cache_data in cache_snapshot.items():
        if not _is_physical_interface(interface_name):
            continue

        addresses_list = cache_data.get("addresses", [])
        for addr_obj in addresses_list:
            if isinstance(addr_obj, dict):
                address = addr_obj.get("address")
                if address and not address.startswith("127."):
                    ip_addresses.append({
                        "interface": interface_name,
                        "ip_address": address,
                    })

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
    return int(sum(u.total for u in _iter_disk_usage()) / (1024 ** 3))


def get_static_system_info() -> Dict:
    """
    Get static system information (everything except IP addresses).
    This should be called once at boot time and cached.

    Returns:
        Dict: Dictionary containing static system information:
            - memory: int - Total RAM in MB
            - cpu: int - Number of CPUs
            - os: str - Operating system
            - kernel: str - Kernel version
            - disk: int - Total disk space in GB
    """
    return {
        "memory": get_total_memory(),
        "cpu": get_cpu_count(),
        "os": get_os_info(),
        "kernel": get_kernel_version(),
        "disk": get_total_disk(),
    }
