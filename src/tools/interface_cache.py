from typing import Optional, Tuple, Dict
from tools.logger import log_debug

INTERFACE_CACHE: Dict[str, dict] = {}


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
