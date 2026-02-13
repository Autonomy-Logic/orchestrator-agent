import pytest
from entities.network_interface import NetworkInterface


class TestNetworkInterface:
    def test_defaults(self):
        iface = NetworkInterface()
        assert iface.subnet is None
        assert iface.gateway is None
        assert iface.type == "ethernet"
        assert iface.addresses == []

    def test_to_dict(self):
        iface = NetworkInterface(
            subnet="192.168.1.0/24",
            gateway="192.168.1.1",
            type="wifi",
            addresses=[{"address": "192.168.1.100", "prefixlen": 24}],
        )
        d = iface.to_dict()
        assert d["subnet"] == "192.168.1.0/24"
        assert d["gateway"] == "192.168.1.1"
        assert d["type"] == "wifi"
        assert len(d["addresses"]) == 1

    def test_from_dict(self):
        data = {
            "subnet": "10.0.0.0/8",
            "gateway": "10.0.0.1",
            "type": "wifi",
            "addresses": [{"address": "10.0.0.50"}],
        }
        iface = NetworkInterface.from_dict(data)
        assert iface.subnet == "10.0.0.0/8"
        assert iface.gateway == "10.0.0.1"
        assert iface.type == "wifi"
        assert iface.addresses == [{"address": "10.0.0.50"}]

    def test_from_dict_defaults(self):
        iface = NetworkInterface.from_dict({})
        assert iface.subnet is None
        assert iface.type == "ethernet"
        assert iface.addresses == []

    def test_roundtrip(self):
        original = NetworkInterface(
            subnet="192.168.1.0/24",
            gateway="192.168.1.1",
            type="ethernet",
            addresses=[{"address": "192.168.1.50", "prefixlen": 24}],
        )
        rebuilt = NetworkInterface.from_dict(original.to_dict())
        assert rebuilt == original


class TestNetworkInterfaceValidation:
    def test_validate_passes_on_ethernet(self):
        iface = NetworkInterface(type="ethernet")
        iface.validate()  # should not raise

    def test_validate_passes_on_wifi(self):
        iface = NetworkInterface(type="wifi")
        iface.validate()  # should not raise

    def test_validate_raises_on_invalid_type(self):
        iface = NetworkInterface(type="bluetooth")
        with pytest.raises(ValueError, match="type"):
            iface.validate()

    def test_create_raises_on_invalid_data(self):
        with pytest.raises(ValueError):
            NetworkInterface.create(type="invalid")

    def test_create_returns_valid_instance(self):
        iface = NetworkInterface.create(type="wifi", subnet="10.0.0.0/8")
        assert iface.type == "wifi"
        assert iface.subnet == "10.0.0.0/8"

    def test_from_dict_does_not_validate(self):
        data = {"type": "invalid_type"}
        iface = NetworkInterface.from_dict(data)
        assert iface.type == "invalid_type"
