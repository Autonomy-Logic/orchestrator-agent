from repos.serial_repo import SerialRepo


class TestSerialRepo:
    def _make_repo(self, tmp_path):
        repo = SerialRepo()
        from tools.json_file import JsonConfigStore
        repo._store = JsonConfigStore(str(tmp_path / "serials.json"))
        return repo

    def test_save_and_load_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        configs = [
            {"name": "modbus0", "device_id": "usb-FTDI-0", "container_path": "/dev/modbus0"},
        ]
        repo.save_configs("plc1", configs)
        loaded = repo.load_configs("plc1")
        assert loaded["serial_ports"][0]["name"] == "modbus0"
        assert loaded["serial_ports"][0]["status"] == "disconnected"
        assert loaded["serial_ports"][0]["current_host_path"] is None

    def test_load_all_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "s1", "device_id": "d1", "container_path": "/dev/s1"}])
        repo.save_configs("plc2", [{"name": "s2", "device_id": "d2", "container_path": "/dev/s2"}])
        all_configs = repo.load_configs()
        assert "plc1" in all_configs
        assert "plc2" in all_configs

    def test_delete_configs(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "s1", "device_id": "d1", "container_path": "/dev/s1"}])
        repo.delete_configs("plc1")
        loaded = repo.load_configs("plc1")
        assert loaded == {"serial_ports": []}

    def test_load_nonexistent_returns_default(self, tmp_path):
        repo = self._make_repo(tmp_path)
        loaded = repo.load_configs("nonexistent")
        assert loaded == {"serial_ports": []}

    def test_load_all_empty(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.load_configs() == {}

    def test_update_status(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "s1", "device_id": "d1", "container_path": "/dev/s1"}])
        repo.update_status(
            "plc1", "s1", "connected",
            current_host_path="/dev/ttyUSB0", major=188, minor=0,
        )
        loaded = repo.load_configs("plc1")
        port = loaded["serial_ports"][0]
        assert port["status"] == "connected"
        assert port["current_host_path"] == "/dev/ttyUSB0"
        assert port["major"] == 188

    def test_update_status_disconnected_clears_fields(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save_configs("plc1", [{"name": "s1", "device_id": "d1", "container_path": "/dev/s1"}])
        repo.update_status(
            "plc1", "s1", "connected",
            current_host_path="/dev/ttyUSB0", major=188, minor=0,
        )
        repo.update_status("plc1", "s1", "disconnected")
        loaded = repo.load_configs("plc1")
        port = loaded["serial_ports"][0]
        assert port["status"] == "disconnected"
        assert port["current_host_path"] is None
        assert port["major"] is None
