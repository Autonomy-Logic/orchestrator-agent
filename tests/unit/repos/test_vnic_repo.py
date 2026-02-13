from repos.vnic_repo import VNICRepo


class TestVNICRepo:
    def _make_repo(self, tmp_path):
        repo = VNICRepo()
        from tools.json_file import JsonConfigStore
        repo._store = JsonConfigStore(str(tmp_path / "vnics.json"))
        return repo

    def test_save_and_load_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        configs = [
            {"name": "vnic1", "parent_interface": "eth0", "network_mode": "dhcp"},
            {"name": "vnic2", "parent_interface": "eth0", "network_mode": "static"},
        ]
        repo.save_configs("plc1", configs)
        loaded = repo.load_configs("plc1")
        assert loaded == configs

    def test_load_all_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "vnic1"}])
        repo.save_configs("plc2", [{"name": "vnic2"}])
        all_configs = repo.load_all_configs()
        assert "plc1" in all_configs
        assert "plc2" in all_configs

    def test_delete_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "vnic1"}])
        repo.delete_configs("plc1")
        loaded = repo.load_configs("plc1")
        assert loaded == []

    def test_load_nonexistent_returns_empty(self, tmp_path):
        repo = self._make_repo(tmp_path)
        loaded = repo.load_configs("nonexistent")
        assert loaded == []

    def test_load_all_empty(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.load_all_configs() == {}

    def test_delete_nonexistent(self, tmp_path):
        repo = self._make_repo(tmp_path)
        # Should not raise
        repo.delete_configs("nonexistent")
