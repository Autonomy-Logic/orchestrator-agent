from dataclasses import dataclass, asdict


@dataclass
class ContainerClient:
    """Represents a registered runtime container in the client registry."""

    name: str
    ip: str

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ContainerClient":
        """Create from a raw dict."""
        return cls(name=data.get("name", ""), ip=data.get("ip", ""))
