import base64
from unittest.mock import MagicMock

from use_cases.runtime_commands.run_command import execute, execute_for_device


class TestExecute:
    def test_basic_get(self):
        """method, ip, port, api passed correctly."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        instance = {"ip": "172.18.0.2", "name": "plc1"}
        command = {"method": "GET", "api": "/api/status", "port": 8443}

        result = execute(instance, command, http_client=http_client)

        http_client.make_request.assert_called_once_with(
            "GET", "172.18.0.2", 8443, "/api/status", {}
        )
        assert result["ok"] is True

    def test_json_body(self):
        """Content-Type=application/json → json param."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "POST",
            "api": "/api/config",
            "headers": {"Content-Type": "application/json"},
            "data": {"key": "value"},
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        assert content["json"] == {"key": "value"}
        assert "data" not in content

    def test_form_body(self):
        """Other content type → data param."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "POST",
            "api": "/api/upload",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "data": "field1=value1&field2=value2",
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        assert content["data"] == "field1=value1&field2=value2"
        assert "json" not in content

    def test_with_headers_and_params(self):
        """Headers and params passed through."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "GET",
            "api": "/api/list",
            "headers": {"Authorization": "Bearer token"},
            "params": {"page": 1},
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        assert content["headers"] == {"Authorization": "Bearer token"}
        assert content["params"] == {"page": 1}

    def test_base64_file_upload(self):
        """Base64-encoded file decoded and formatted as (filename, bytes, mime)."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        raw_bytes = b"PK\x03\x04test"
        b64_content = base64.b64encode(raw_bytes).decode()

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "POST",
            "api": "/api/upload",
            "files": {
                "program": {
                    "filename": "test.zip",
                    "content_base64": b64_content,
                    "content_type": "application/zip",
                }
            },
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        files = content["files"]
        assert files["program"] == ("test.zip", raw_bytes, "application/zip")

    def test_base64_file_empty_content_skipped(self):
        """Base64 file with empty content_base64 is skipped."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "POST",
            "api": "/api/upload",
            "files": {
                "program": {
                    "filename": "test.zip",
                    "content_base64": "",
                    "content_type": "application/zip",
                }
            },
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        assert "files" not in content

    def test_raw_file_passthrough(self):
        """Non-base64 files passed through unchanged."""
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True}

        raw_tuple = ("test.bin", b"\x00\x01\x02", "application/octet-stream")

        instance = {"ip": "172.18.0.2"}
        command = {
            "method": "POST",
            "api": "/api/upload",
            "files": {"program": raw_tuple},
        }

        execute(instance, command, http_client=http_client)

        call_args = http_client.make_request.call_args
        content = call_args[0][4]
        assert content["files"]["program"] == raw_tuple


class TestExecuteForDevice:
    def test_device_not_found(self):
        """Registry miss → error dict."""
        registry = MagicMock()
        registry.get_client.return_value = None
        http_client = MagicMock()

        result = execute_for_device(
            "plc1",
            {"method": "GET", "api": "/status"},
            client_registry=registry,
            http_client=http_client,
        )

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_success(self):
        """Registry hit → status='success'."""
        registry = MagicMock()
        registry.get_client.return_value = {"ip": "172.18.0.2"}
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": True, "status_code": 200}

        result = execute_for_device(
            "plc1",
            {"method": "GET", "api": "/status"},
            client_registry=registry,
            http_client=http_client,
        )

        assert result["status"] == "success"
        assert result["http_response"]["ok"] is True

    def test_http_error(self):
        """ok=False → status='error'."""
        registry = MagicMock()
        registry.get_client.return_value = {"ip": "172.18.0.2"}
        http_client = MagicMock()
        http_client.make_request.return_value = {"ok": False, "status_code": 500}

        result = execute_for_device(
            "plc1",
            {"method": "GET", "api": "/status"},
            client_registry=registry,
            http_client=http_client,
        )

        assert result["status"] == "error"
