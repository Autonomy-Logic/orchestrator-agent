from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class NetworkInterface:
    """Represents a host network interface from the netmon discovery cache."""

    subnet: Optional[str] = None
    gateway: Optional[str] = None
    type: str = "ethernet"
    addresses: List[dict] = field(default_factory=list)

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
