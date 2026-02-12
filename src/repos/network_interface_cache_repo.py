from typing import Optional, Tuple, Dict
from tools.logger import log_debug

from repos.interfaces import NetworkInterfaceCacheRepoInterface


class NetworkInterfaceCacheRepo(NetworkInterfaceCacheRepoInterface):
    """Concrete repo owning the in-memory network interface cache.

    All mutations and reads go through this repo instance. The cache is
    populated by NetworkEventListener via set_interface/remove_interface
    and read by use cases via get_interface_type/get_interface_network.
    """

    def __init__(self, cache_dict: Dict[str, dict] = None):
        self._cache = cache_dict if cache_dict is not None else {}

    def get_interface_type(self, interface_name: str) -> str:
        """
        Get the type of an interface from the cache.

        Returns:
            "wifi" for wireless interfaces, "ethernet" for wired interfaces.
            Defaults to "ethernet" if interface not found or type not specified.
        """
        if interface_name not in self._cache:
            log_debug(
                f"Interface {interface_name} not found in cache, "
                f"defaulting to ethernet type"
            )
            return "ethernet"

        iface_type = self._cache[interface_name].get("type", "ethernet")
        log_debug(f"Interface {interface_name} type from cache: {iface_type}")
        return iface_type

    def get_interface_network(
        self, parent_interface: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Get network information for an interface from the cache.

        Returns:
            Tuple of (subnet, gateway) or (None, None) if interface not found
        """
        if parent_interface not in self._cache:
            log_debug(f"Interface {parent_interface} not found in netmon discovery cache")
            return None, None

        iface_data = self._cache[parent_interface]
        subnet = iface_data.get("subnet")
        gateway = iface_data.get("gateway")

        log_debug(
            f"Retrieved network info for {parent_interface} from cache: "
            f"subnet={subnet}, gateway={gateway}"
        )

        return subnet, gateway

    def get_all_interfaces(self) -> Dict[str, dict]:
        return dict(self._cache)

    def set_interface(self, name: str, data: dict) -> None:
        self._cache[name] = data

    def remove_interface(self, name: str) -> None:
        if name in self._cache:
            del self._cache[name]
