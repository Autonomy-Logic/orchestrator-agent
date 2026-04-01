from dataclasses import dataclass, asdict


@dataclass
class DedicatedNicConfig:
    """Represents a dedicated physical NIC moved into a container's network namespace."""

    host_interface: str = ""

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if not self.host_interface:
            raise ValueError("host_interface is required")

    @classmethod
    def create(cls, host_interface: str) -> "DedicatedNicConfig":
        """Construct and validate a new DedicatedNicConfig."""
        instance = cls(host_interface=host_interface)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DedicatedNicConfig":
        """Create from a raw dict, ignoring unknown keys. Validates after construction."""
        return cls.create(host_interface=data.get("host_interface", ""))
