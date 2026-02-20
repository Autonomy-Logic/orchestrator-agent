import time

from tools.utils import matches_device_id, parse_period


class TestMatchesDeviceId:
    def test_exact_match(self):
        assert matches_device_id("usb-FTDI_FT232R", "usb-FTDI_FT232R") is True

    def test_device_id_is_substring_of_by_id(self):
        """device_id is just the device part, by_id is the full path."""
        assert matches_device_id(
            "usb-FTDI_FT232R",
            "/dev/serial/by-id/usb-FTDI_FT232R-if00-port0",
        ) is True

    def test_by_id_is_substring_of_device_id(self):
        """by_id is shorter substring of device_id."""
        assert matches_device_id(
            "/dev/serial/by-id/usb-FTDI_FT232R-if00-port0",
            "usb-FTDI_FT232R",
        ) is True

    def test_no_match(self):
        assert matches_device_id("usb-FTDI", "usb-Prolific") is False

    def test_empty_device_id(self):
        assert matches_device_id("", "usb-FTDI") is False

    def test_empty_by_id(self):
        assert matches_device_id("usb-FTDI", "") is False

    def test_both_empty(self):
        assert matches_device_id("", "") is False

    def test_none_device_id(self):
        assert matches_device_id(None, "usb-FTDI") is False

    def test_none_by_id(self):
        assert matches_device_id("usb-FTDI", None) is False


class TestParsePeriod:
    def test_explicit_timestamps(self):
        """Comma-separated start,end timestamps."""
        start, end = parse_period("1000,2000")
        assert start == 1000
        assert end == 2000

    def test_hours_duration(self):
        """Duration in hours (e.g., '1h')."""
        before = int(time.time())
        start, end = parse_period("1h")
        after = int(time.time())

        assert before <= end <= after
        assert end - start == 3600

    def test_minutes_duration(self):
        """Duration in minutes (e.g., '30m')."""
        start, end = parse_period("30m")
        assert end - start == 1800

    def test_days_duration(self):
        """Duration in days (e.g., '2d')."""
        start, end = parse_period("2d")
        assert end - start == 172800

    def test_seconds_duration(self):
        """Plain integer treated as seconds."""
        start, end = parse_period("120")
        assert end - start == 120

    def test_invalid_period_defaults_to_1h(self):
        """Invalid input falls back to 1 hour."""
        start, end = parse_period("invalid")
        assert end - start == 3600
