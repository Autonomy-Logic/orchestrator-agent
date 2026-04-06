import pytest

from entities.dedicated_nic_config import DedicatedNicConfig


class TestDedicatedNicConfig:
    def test_create_valid(self):
        """Valid config is created successfully."""
        config = DedicatedNicConfig.create("eth0")
        assert config.host_interface == "eth0"

    def test_create_empty_raises(self):
        """Empty host_interface raises ValueError."""
        with pytest.raises(ValueError, match="host_interface is required"):
            DedicatedNicConfig.create("")

    def test_validate_empty_raises(self):
        """validate() on empty host_interface raises ValueError."""
        config = DedicatedNicConfig()
        with pytest.raises(ValueError, match="host_interface is required"):
            config.validate()

    def test_to_dict(self):
        """to_dict returns dict with host_interface."""
        config = DedicatedNicConfig.create("enp4s0")
        result = config.to_dict()
        assert result == {"host_interface": "enp4s0"}

    def test_from_dict(self):
        """from_dict creates valid config."""
        config = DedicatedNicConfig.from_dict({"host_interface": "eth1"})
        assert config.host_interface == "eth1"

    def test_from_dict_ignores_extra_keys(self):
        """from_dict ignores unknown keys."""
        config = DedicatedNicConfig.from_dict({"host_interface": "eth0", "extra": "ignored"})
        assert config.host_interface == "eth0"

    def test_from_dict_empty_raises(self):
        """from_dict with empty host_interface raises."""
        with pytest.raises(ValueError):
            DedicatedNicConfig.from_dict({})
