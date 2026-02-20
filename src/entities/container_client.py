from dataclasses import dataclass, asdict


@dataclass
class ContainerClient:
    """Represents a registered runtime container in the client registry."""

    name: str
    ip: str

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.ip, str) or not self.ip.strip():
            raise ValueError("ip must be a non-empty string")

    @classmethod
    def create(cls, name: str, ip: str) -> "ContainerClient":
        """Construct and validate a new ContainerClient."""
        instance = cls(name=name, ip=ip)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ContainerClient":
        """Create from a raw dict."""
        return cls(name=data.get("name", ""), ip=data.get("ip", ""))
