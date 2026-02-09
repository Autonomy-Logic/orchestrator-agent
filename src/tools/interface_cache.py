from typing import Optional, Tuple, Dict
from tools.logger import log_debug

INTERFACE_CACHE: Dict[str, dict] = {}
"""
Interface cache structure:
{
    "eth0": {
        "subnet": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "type": "ethernet",
        "addresses": [...]
    },
    "wlan0": {
        "subnet": "10.0.0.0/24",
        "gateway": "10.0.0.1",
        "type": "wifi",
        "addresses": [...]
    }
}
"""


def get_interface_type(interface_name: str) -> str:
    """
    Get the type of an interface from the netmon discovery cache.

    The interface type is detected by netmon based on sysfs attributes
    (wireless directory, phy80211 link) and reported in discovery events.

    Args:
        interface_name: Name of the network interface (e.g., "eth0", "wlan0")

    Returns:
        "wifi" for wireless interfaces, "ethernet" for wired interfaces.
        Defaults to "ethernet" if interface not found or type not specified.
    """
    if interface_name not in INTERFACE_CACHE:
        log_debug(
            f"Interface {interface_name} not found in cache, "
            f"defaulting to ethernet type"
        )
        return "ethernet"

    iface_type = INTERFACE_CACHE[interface_name].get("type", "ethernet")
    log_debug(f"Interface {interface_name} type from cache: {iface_type}")
    return iface_type


def get_interface_network(parent_interface: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Get network information for an interface from the netmon discovery cache.

    Returns:
        Tuple of (subnet, gateway) or (None, None) if interface not found in cache
    """
    if parent_interface not in INTERFACE_CACHE:
        log_debug(f"Interface {parent_interface} not found in netmon discovery cache")
        return None, None

    iface_data = INTERFACE_CACHE[parent_interface]
    subnet = iface_data.get("subnet")
    gateway = iface_data.get("gateway")

    log_debug(
        f"Retrieved network info for {parent_interface} from cache: "
        f"subnet={subnet}, gateway={gateway}"
    )

    return subnet, gateway
