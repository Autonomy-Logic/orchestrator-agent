from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class NetworkInterface:
    """Represents a host network interface from the netmon discovery cache."""

    VALID_TYPES = frozenset({"ethernet", "wifi"})

    subnet: Optional[str] = None
    gateway: Optional[str] = None
    type: str = "ethernet"
    addresses: List[dict] = field(default_factory=list)

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if self.type not in self.VALID_TYPES:
            raise ValueError(f"type must be one of {self.VALID_TYPES}, got '{self.type}'")

    @classmethod
    def create(cls, **kwargs) -> "NetworkInterface":
        """Construct and validate a new NetworkInterface."""
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkInterface":
        """Create from a raw dict."""
        return cls(
            subnet=data.get("subnet"),
            gateway=data.get("gateway"),
            type=data.get("type", "ethernet"),
            addresses=data.get("addresses", []),
        )
