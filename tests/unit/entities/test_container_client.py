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
