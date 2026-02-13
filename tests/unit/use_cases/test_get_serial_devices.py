from unittest.mock import MagicMock

from use_cases.get_serial_devices import get_serial_devices_data


class TestGetSerialDevicesData:
    def test_returns_formatted_devices(self):
        """Formats list with path, device_id (from by_id), vendor_id, etc."""
        listener = MagicMock()
        listener.get_available_devices.return_value = [
            {
                "path": "/dev/ttyUSB0",
                "by_id": "usb-FTDI_FT232R_ABC-if00-port0",
                "vendor_id": "0403",
                "product_id": "6001",
                "serial": "ABC",
                "manufacturer": "FTDI",
                "product": "FT232R",
            }
        ]

        result = get_serial_devices_data(network_event_listener=listener)

        assert result["count"] == 1
        assert result["devices"][0]["path"] == "/dev/ttyUSB0"
        assert result["devices"][0]["device_id"] == "usb-FTDI_FT232R_ABC-if00-port0"
        assert result["devices"][0]["vendor_id"] == "0403"
        assert result["devices"][0]["product_id"] == "6001"
        assert result["devices"][0]["serial"] == "ABC"
        assert result["devices"][0]["manufacturer"] == "FTDI"
        assert result["devices"][0]["product"] == "FT232R"

    def test_empty_devices(self):
        """Empty device list returns count 0."""
        listener = MagicMock()
        listener.get_available_devices.return_value = []

        result = get_serial_devices_data(network_event_listener=listener)

        assert result == {"devices": [], "count": 0}

    def test_partial_device_fields(self):
        """Missing fields default to None."""
        listener = MagicMock()
        listener.get_available_devices.return_value = [
            {"path": "/dev/ttyUSB0"}
        ]

        result = get_serial_devices_data(network_event_listener=listener)

        assert result["count"] == 1
        dev = result["devices"][0]
        assert dev["path"] == "/dev/ttyUSB0"
        assert dev["device_id"] is None
        assert dev["vendor_id"] is None
        assert dev["product_id"] is None
        assert dev["serial"] is None
        assert dev["manufacturer"] is None
        assert dev["product"] is None
