from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class SerialConfig:
    """Represents a serial port configuration for a runtime container."""

    VALID_STATUSES = frozenset({"connected", "disconnected"})

    # User-provided fields (from cloud message)
    name: str = ""
    device_id: str = ""
    container_path: str = ""
    baud_rate: Optional[int] = None

    # Runtime state (populated by device event listener)
    status: str = "disconnected"
    current_host_path: Optional[str] = None
    major: Optional[int] = None
    minor: Optional[int] = None

    def validate(self) -> None:
        """Raise ValueError if business invariants are violated."""
        if self.status not in self.VALID_STATUSES:
            raise ValueError(f"status must be one of {self.VALID_STATUSES}, got '{self.status}'")

    @classmethod
    def create(cls, **kwargs) -> "SerialConfig":
        """Construct and validate a new SerialConfig."""
        instance = cls(**kwargs)
        instance.validate()
        return instance

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SerialConfig":
        """Create from a raw dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})
