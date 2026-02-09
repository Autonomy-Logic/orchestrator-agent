from typing import Optional, Tuple, Dict
from tools.interface_cache import (
    INTERFACE_CACHE,
    get_interface_type,
    get_interface_network,
)


class DictNetworkInterfaceCache:
    """Concrete adapter wrapping the in-memory INTERFACE_CACHE dict.

    Holds a reference to the live mutable INTERFACE_CACHE so that existing
    code that writes to it directly (network_event_listener) continues to work.
    """

    def __init__(self, cache_dict: Dict[str, dict] = None):
        self._cache = cache_dict if cache_dict is not None else INTERFACE_CACHE

    def get_interface_type(self, interface_name: str) -> str:
        return get_interface_type(interface_name)

    def get_interface_network(
        self, parent_interface: str
    ) -> Tuple[Optional[str], Optional[str]]:
        return get_interface_network(parent_interface)

    def get_all_interfaces(self) -> Dict[str, dict]:
        return dict(self._cache)

    def set_interface(self, name: str, data: dict) -> None:
        self._cache[name] = data

    def remove_interface(self, name: str) -> None:
        if name in self._cache:
            del self._cache[name]
