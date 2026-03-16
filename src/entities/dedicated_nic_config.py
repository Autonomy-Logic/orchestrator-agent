from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class DedicatedNicConfig:
    """Represents a dedicated physical NIC moved into a container's network namespace."""

    host_interface: str = ""
    container_interface: str = ""
    purpose: str = "dedicated"
    moved_at: Optional[str] = None

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if not self.host_interface:
            raise ValueError("host_interface is required")
        if not self.container_interface:
            raise ValueError("container_interface is required")

    @classmethod
    def create(cls, **kwargs) -> "DedicatedNicConfig":
        """Construct and validate a new DedicatedNicConfig."""
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DedicatedNicConfig":
        """Create from a raw dict, ignoring unknown keys. Validates after construction."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        instance = cls(**{k: v for k, v in data.items() if k in known})
        instance.validate()
        return instance
