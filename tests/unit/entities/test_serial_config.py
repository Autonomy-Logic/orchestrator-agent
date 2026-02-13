from entities.serial_config import SerialConfig


class TestSerialConfig:
    def test_defaults(self):
        config = SerialConfig()
        assert config.name == ""
        assert config.device_id == ""
        assert config.container_path == ""
        assert config.baud_rate is None
        assert config.status == "disconnected"
        assert config.current_host_path is None
        assert config.major is None
        assert config.minor is None

    def test_to_dict(self):
        config = SerialConfig(
            name="modbus_rtu",
            device_id="usb-FTDI_FT232R-if00",
            container_path="/dev/modbus0",
            baud_rate=9600,
            status="connected",
            current_host_path="/dev/ttyUSB0",
            major=188,
            minor=0,
        )
        d = config.to_dict()
        assert d["name"] == "modbus_rtu"
        assert d["baud_rate"] == 9600
        assert d["status"] == "connected"
        assert d["major"] == 188

    def test_from_dict(self):
        data = {
            "name": "modbus_rtu",
            "device_id": "usb-FTDI_FT232R-if00",
            "container_path": "/dev/modbus0",
            "baud_rate": 9600,
        }
        config = SerialConfig.from_dict(data)
        assert config.name == "modbus_rtu"
        assert config.baud_rate == 9600
        assert config.status == "disconnected"  # default

    def test_from_dict_ignores_unknown(self):
        data = {"name": "test", "unknown_field": "ignored"}
        config = SerialConfig.from_dict(data)
        assert config.name == "test"

    def test_roundtrip(self):
        original = SerialConfig(
            name="modbus_rtu",
            device_id="usb-FTDI_FT232R-if00",
            container_path="/dev/modbus0",
            baud_rate=9600,
            status="connected",
            current_host_path="/dev/ttyUSB0",
            major=188,
            minor=0,
        )
        rebuilt = SerialConfig.from_dict(original.to_dict())
        assert rebuilt == original
