from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class VnicConfig:
    """Represents a virtual NIC configuration for a runtime container."""

    VALID_NETWORK_MODES = frozenset({"dhcp", "static"})

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

    # Internal metadata (not persisted when None)
    _interface_type: Optional[str] = field(default=None, repr=False)
    _is_wifi: Optional[bool] = field(default=None, repr=False)
    _network_method: Optional[str] = field(default=None, repr=False)
    _proxy_arp_config: Optional[dict] = field(default=None, repr=False)

    _INTERNAL_FIELDS = frozenset({
        "_interface_type", "_is_wifi", "_network_method", "_proxy_arp_config"
    })

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if self.network_mode not in self.VALID_NETWORK_MODES:
            raise ValueError(f"network_mode must be one of {self.VALID_NETWORK_MODES}, got '{self.network_mode}'")

    @classmethod
    def create(cls, **kwargs) -> "VnicConfig":
        """Construct and validate a new VnicConfig."""
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict, excluding None internal fields."""
        result = {}
        for k, v in asdict(self).items():
            if k in self._INTERNAL_FIELDS and v is None:
                continue
            result[k] = v
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "VnicConfig":
        """Create from a raw dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})
