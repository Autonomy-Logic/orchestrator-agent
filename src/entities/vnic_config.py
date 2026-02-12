from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class VnicConfig:
    """Represents a virtual NIC configuration for a runtime container."""

    # User-provided fields (from cloud message)
    name: str = ""
    parent_interface: str = ""
    network_mode: str = "dhcp"
    ip: Optional[str] = None
    subnet: Optional[str] = None
    gateway: Optional[str] = None
    dns: Optional[List[str]] = None
    mac: Optional[str] = None

    # Runtime fields (populated during container creation)
    mac_address: Optional[str] = None
    docker_network_name: Optional[str] = None
    dhcp_ip: Optional[str] = None
    dhcp_gateway: Optional[str] = None
    dhcp_dns: Optional[str] = None

    # Internal metadata (prefixed with underscore)
    _interface_type: Optional[str] = field(default=None, repr=False)
    _is_wifi: Optional[bool] = field(default=None, repr=False)
    _network_method: Optional[str] = field(default=None, repr=False)
    _proxy_arp_config: Optional[dict] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict, excluding None internal fields."""
        result = {}
        for k, v in asdict(self).items():
            if k.startswith("_") and v is None:
                continue
            result[k] = v
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "VnicConfig":
        """Create from a raw dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})
