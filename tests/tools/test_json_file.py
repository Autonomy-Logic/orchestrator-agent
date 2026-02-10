import json
import os
from unittest.mock import patch

from tools.json_file import read_json_file, write_json_file, JsonConfigStore


class TestReadJsonFile:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = read_json_file(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_invalid_json_returns_empty_dict(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json{{{")
        result = read_json_file(str(bad_file))
        assert result == {}

    def test_valid_json(self, tmp_path):
        good_file = tmp_path / "good.json"
        good_file.write_text('{"key": "value"}')
        result = read_json_file(str(good_file))
        assert result == {"key": "value"}

    def test_generic_exception_returns_empty_dict(self, tmp_path):
        """Lines 20-22: non-JSONDecodeError exception returns {}."""
        good_file = tmp_path / "exists.json"
        good_file.write_text('{"key": "value"}')

        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = read_json_file(str(good_file))
        assert result == {}


class TestWriteJsonFile:
    def test_write_and_read_roundtrip(self, tmp_path):
        file_path = str(tmp_path / "test.json")
        data = {"containers": {"plc1": {"ip": "172.18.0.2"}}}
        write_json_file(file_path, data)
        result = read_json_file(file_path)
        assert result == data

    def test_creates_parent_dirs(self, tmp_path):
        file_path = str(tmp_path / "subdir" / "nested" / "test.json")
        write_json_file(file_path, {"key": "value"})
        assert os.path.exists(file_path)
        result = read_json_file(file_path)
        assert result == {"key": "value"}


class TestJsonConfigStore:
    def test_read_all_empty(self, tmp_path):
        store = JsonConfigStore(str(tmp_path / "config.json"))
        assert store.read_all() == {}

    def test_modify_and_read(self, tmp_path):
        store = JsonConfigStore(str(tmp_path / "config.json"))
        store.modify(lambda data: data.__setitem__("plc1", {"ip": "172.18.0.2"}))
        result = store.read_all()
        assert result == {"plc1": {"ip": "172.18.0.2"}}

    def test_multiple_modifications(self, tmp_path):
        store = JsonConfigStore(str(tmp_path / "config.json"))
        store.modify(lambda data: data.__setitem__("plc1", "a"))
        store.modify(lambda data: data.__setitem__("plc2", "b"))
        result = store.read_all()
        assert result == {"plc1": "a", "plc2": "b"}

    def test_modify_delete(self, tmp_path):
        store = JsonConfigStore(str(tmp_path / "config.json"))
        store.modify(lambda data: data.__setitem__("plc1", "a"))
        store.modify(lambda data: data.pop("plc1", None))
        assert store.read_all() == {}
