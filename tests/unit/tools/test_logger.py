import logging
from unittest.mock import patch, MagicMock

import tools.logger as logger_mod
from tools.logger import (
    log_info,
    log_error,
    log_warning,
    log_debug,
    log_critical,
    set_log_level,
    LOGGER,
    _ensure_file_handlers,
)

# Prevent lazy file handler init from creating real files during most tests
logger_mod._file_handlers_initialized = True


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


class TestEnsureFileHandlers:
    @patch("tools.logger.logging.FileHandler")
    @patch("tools.logger.os.makedirs")
    def test_creates_handlers_on_first_call(self, mock_makedirs, mock_fh_cls):
        """_ensure_file_handlers creates debug and regular file handlers."""
        # Reset the flag so it actually runs
        logger_mod._file_handlers_initialized = False

        # Remove any existing file handlers from previous runs
        original_handlers = list(LOGGER.handlers)
        for h in original_handlers:
            if h.name in ("debugger_handler", "regular_handler"):
                LOGGER.removeHandler(h)

        mock_handler = MagicMock()
        mock_fh_cls.return_value = mock_handler

        try:
            _ensure_file_handlers()

            assert mock_makedirs.call_count == 2
            assert mock_fh_cls.call_count == 2
            # Handlers were added to LOGGER
            handler_names = [h.name for h in LOGGER.handlers]
            assert "debugger_handler" in handler_names or mock_handler.set_name.call_count == 2
        finally:
            # Restore: remove mock handlers, re-add originals, reset flag
            for h in list(LOGGER.handlers):
                if h not in original_handlers:
                    LOGGER.removeHandler(h)
            for h in original_handlers:
                if h not in LOGGER.handlers:
                    LOGGER.addHandler(h)
            logger_mod._file_handlers_initialized = True

    @patch("tools.logger.os.makedirs", side_effect=OSError("read-only filesystem"))
    def test_falls_back_to_stream_only_on_os_error(self, mock_makedirs):
        """_ensure_file_handlers falls back to stream-only if setup fails."""
        logger_mod._file_handlers_initialized = False
        handler_count_before = len(LOGGER.handlers)

        try:
            _ensure_file_handlers()

            # Flag stays False so next call will retry
            assert logger_mod._file_handlers_initialized is False
            # No new handlers were added
            assert len(LOGGER.handlers) == handler_count_before
        finally:
            logger_mod._file_handlers_initialized = True

    def test_noop_when_already_initialized(self):
        """_ensure_file_handlers returns immediately when already initialized."""
        logger_mod._file_handlers_initialized = True
        handler_count_before = len(LOGGER.handlers)

        _ensure_file_handlers()

        assert len(LOGGER.handlers) == handler_count_before


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
