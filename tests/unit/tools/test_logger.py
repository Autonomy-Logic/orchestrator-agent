import logging
from unittest.mock import patch

from tools.logger import (
    log_info,
    log_error,
    log_warning,
    log_debug,
    log_critical,
    set_log_level,
    LOGGER,
)


class TestLogFunctions:
    @patch.object(LOGGER, "info")
    def test_log_info(self, mock_info):
        log_info("test message")
        mock_info.assert_called_once()
        assert "test message" in mock_info.call_args[0][0]

    @patch.object(LOGGER, "error")
    def test_log_error(self, mock_error):
        log_error("error message")
        mock_error.assert_called_once()
        assert "error message" in mock_error.call_args[0][0]

    @patch.object(LOGGER, "warning")
    def test_log_warning(self, mock_warning):
        log_warning("warning message")
        mock_warning.assert_called_once()
        assert "warning message" in mock_warning.call_args[0][0]

    @patch.object(LOGGER, "debug")
    def test_log_debug(self, mock_debug):
        log_debug("debug message")
        mock_debug.assert_called_once()
        assert "debug message" in mock_debug.call_args[0][0]

    @patch.object(LOGGER, "critical")
    def test_log_critical(self, mock_critical):
        log_critical("critical message")
        mock_critical.assert_called_once()
        assert "critical message" in mock_critical.call_args[0][0]


class TestSetLogLevel:
    def test_changes_handler_levels(self):
        """set_log_level changes non-debugger handler levels."""
        original_levels = {h.name: h.level for h in LOGGER.handlers}

        set_log_level(logging.WARNING)

        for handler in LOGGER.handlers:
            if handler.name != "debugger_handler":
                assert handler.level == logging.WARNING

        # Restore original levels
        for handler in LOGGER.handlers:
            if handler.name in original_levels:
                handler.setLevel(original_levels[handler.name])

    def test_preserves_debugger_handler(self):
        """set_log_level does NOT change debugger_handler level."""
        debugger = None
        for handler in LOGGER.handlers:
            if handler.name == "debugger_handler":
                debugger = handler
                break

        if debugger is None:
            return  # Skip if debugger handler not present

        original_level = debugger.level
        set_log_level(logging.CRITICAL)

        assert debugger.level == original_level

        # Restore
        set_log_level(logging.INFO)
