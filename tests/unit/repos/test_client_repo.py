from repos.client_repo import ClientRepo


class TestClientRepo:
    def _make_repo(self, tmp_path):
        return ClientRepo(clients_file=str(tmp_path / "clients.json"))

    def test_add_and_get_client(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_client("plc1", "172.18.0.2")
        client = repo.get_client("plc1")
        assert client == {"ip": "172.18.0.2", "name": "plc1"}

    def test_get_nonexistent_client(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.get_client("nonexistent") is None

    def test_remove_client(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_client("plc1", "172.18.0.2")
        repo.remove_client("plc1")
        assert repo.get_client("plc1") is None

    def test_remove_nonexistent_client(self, tmp_path):
        repo = self._make_repo(tmp_path)
        # Should not raise
        repo.remove_client("nonexistent")

    def test_list_clients(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_client("plc1", "172.18.0.2")
        repo.add_client("plc2", "172.18.0.3")
        clients = repo.list_clients()
        assert len(clients) == 2
        assert "plc1" in clients
        assert "plc2" in clients

    def test_list_clients_empty(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.list_clients() == {}

    def test_contains(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.contains("plc1") is False
        repo.add_client("plc1", "172.18.0.2")
        assert repo.contains("plc1") is True

    def test_persistence_across_instances(self, tmp_path):
        file_path = str(tmp_path / "clients.json")
        repo1 = ClientRepo(clients_file=file_path)
        repo1.add_client("plc1", "172.18.0.2")

        repo2 = ClientRepo(clients_file=file_path)
        assert repo2.get_client("plc1") == {"ip": "172.18.0.2", "name": "plc1"}
