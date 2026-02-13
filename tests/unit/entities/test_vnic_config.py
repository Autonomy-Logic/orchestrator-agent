import pytest
from entities.vnic_config import VnicConfig


class TestVnicConfigDefaults:
    def test_default_values(self):
        config = VnicConfig()
        assert config.name == ""
        assert config.parent_interface == ""
        assert config.network_mode == "dhcp"
        assert config.ip is None
        assert config.subnet is None
        assert config.gateway is None
        assert config.dns is None
        assert config.mac is None
        assert config.mac_address is None
        assert config.docker_network_name is None
        assert config._interface_type is None
        assert config._is_wifi is None


class TestVnicConfigToDict:
    def test_excludes_none_internal_fields(self):
        config = VnicConfig()
        d = config.to_dict()
        assert "_interface_type" not in d
        assert "_is_wifi" not in d
        assert "_network_method" not in d
        assert "_proxy_arp_config" not in d

    def test_includes_set_internal_fields(self):
        config = VnicConfig(_is_wifi=True, _interface_type="wifi")
        d = config.to_dict()
        assert d["_is_wifi"] is True
        assert d["_interface_type"] == "wifi"

    def test_includes_all_user_fields(self):
        config = VnicConfig()
        d = config.to_dict()
        assert "name" in d
        assert "ip" in d
        assert "subnet" in d
        assert "gateway" in d
        assert "network_mode" in d

    def test_full_config_to_dict(self):
        config = VnicConfig(
            name="eth0_vnic",
            parent_interface="eth0",
            network_mode="static",
            ip="192.168.1.100",
            subnet="192.168.1.0/24",
            gateway="192.168.1.1",
            dns=["8.8.8.8"],
            mac="aa:bb:cc:dd:ee:ff",
        )
        d = config.to_dict()
        assert d["name"] == "eth0_vnic"
        assert d["ip"] == "192.168.1.100"
        assert d["dns"] == ["8.8.8.8"]


class TestVnicConfigInternalFields:
    def test_internal_fields_contains_expected_fields(self):
        assert VnicConfig._INTERNAL_FIELDS == frozenset({
            "_interface_type", "_is_wifi", "_network_method", "_proxy_arp_config"
        })


class TestVnicConfigFromDict:
    def test_ignores_unknown_keys(self):
        data = {"name": "test", "unknown_key": "ignored", "another": 42}
        config = VnicConfig.from_dict(data)
        assert config.name == "test"
        assert not hasattr(config, "unknown_key")

    def test_roundtrip(self):
        original = VnicConfig(
            name="eth0_vnic",
            parent_interface="eth0",
            network_mode="static",
            ip="192.168.1.100",
            subnet="192.168.1.0/24",
            gateway="192.168.1.1",
            dns=["8.8.8.8", "8.8.4.4"],
            mac="aa:bb:cc:dd:ee:ff",
            mac_address="aa:bb:cc:dd:ee:ff",
            docker_network_name="macvlan_eth0",
        )
        rebuilt = VnicConfig.from_dict(original.to_dict())
        assert rebuilt == original

    def test_roundtrip_with_internal_fields(self):
        original = VnicConfig(_is_wifi=True, _interface_type="wifi")
        d = original.to_dict()
        rebuilt = VnicConfig.from_dict(d)
        assert rebuilt._is_wifi is True
        assert rebuilt._interface_type == "wifi"


class TestVnicConfigValidation:
    def test_validate_passes_on_valid_data(self):
        config = VnicConfig(network_mode="dhcp")
        config.validate()  # should not raise

    def test_validate_passes_on_static(self):
        config = VnicConfig(network_mode="static")
        config.validate()  # should not raise

    def test_validate_raises_on_invalid_network_mode(self):
        config = VnicConfig(network_mode="manual")
        with pytest.raises(ValueError, match="network_mode"):
            config.validate()

    def test_create_raises_on_invalid_data(self):
        with pytest.raises(ValueError):
            VnicConfig.create(network_mode="invalid")

    def test_create_returns_valid_instance(self):
        config = VnicConfig.create(name="eth0_vnic", network_mode="dhcp")
        assert config.name == "eth0_vnic"

    def test_from_dict_does_not_validate(self):
        data = {"network_mode": "invalid"}
        config = VnicConfig.from_dict(data)
        assert config.network_mode == "invalid"
