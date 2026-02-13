import pytest
from entities.container_client import ContainerClient


class TestContainerClient:
    def test_to_dict(self):
        client = ContainerClient(name="plc1", ip="172.18.0.2")
        d = client.to_dict()
        assert d == {"name": "plc1", "ip": "172.18.0.2"}

    def test_from_dict(self):
        data = {"name": "plc1", "ip": "172.18.0.2"}
        client = ContainerClient.from_dict(data)
        assert client.name == "plc1"
        assert client.ip == "172.18.0.2"

    def test_from_dict_missing_keys(self):
        client = ContainerClient.from_dict({})
        assert client.name == ""
        assert client.ip == ""

    def test_from_dict_partial(self):
        client = ContainerClient.from_dict({"name": "plc1"})
        assert client.name == "plc1"
        assert client.ip == ""

    def test_roundtrip(self):
        original = ContainerClient(name="plc1", ip="172.18.0.2")
        rebuilt = ContainerClient.from_dict(original.to_dict())
        assert rebuilt == original


class TestContainerClientValidation:
    def test_validate_passes_on_valid_data(self):
        client = ContainerClient(name="plc1", ip="172.18.0.2")
        client.validate()  # should not raise

    def test_validate_raises_on_empty_name(self):
        client = ContainerClient(name="", ip="172.18.0.2")
        with pytest.raises(ValueError, match="name"):
            client.validate()

    def test_validate_raises_on_whitespace_name(self):
        client = ContainerClient(name="   ", ip="172.18.0.2")
        with pytest.raises(ValueError, match="name"):
            client.validate()

    def test_validate_raises_on_empty_ip(self):
        client = ContainerClient(name="plc1", ip="")
        with pytest.raises(ValueError, match="ip"):
            client.validate()

    def test_create_raises_on_invalid_data(self):
        with pytest.raises(ValueError):
            ContainerClient.create(name="", ip="172.18.0.2")

    def test_create_returns_valid_instance(self):
        client = ContainerClient.create(name="plc1", ip="172.18.0.2")
        assert client.name == "plc1"
        assert client.ip == "172.18.0.2"

    def test_from_dict_does_not_validate(self):
        # from_dict accepts invalid data without raising
        client = ContainerClient.from_dict({"name": "", "ip": ""})
        assert client.name == ""
        assert client.ip == ""
