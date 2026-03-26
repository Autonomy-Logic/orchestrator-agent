from typing import Any, Dict, Optional, Protocol


class DedicatedNicRepoInterface(Protocol):
    """
    Abstract interface for dedicated NIC configuration persistence.

    The concrete repo returns DedicatedNicConfig entities from load methods,
    eliminating from_dict conversion at every call site. The interface uses
    Any to avoid coupling repos/interfaces/ to entities/.
    """

    def save_config(self, container_name: str, config: Any) -> None: ...
    def load_config(self, container_name: str) -> Optional[Any]: ...
    def load_all_configs(self) -> Dict[str, Any]: ...
    def delete_config(self, container_name: str) -> None: ...
    def get_container_for_nic(self, interface_name: str) -> Optional[str]: ...
