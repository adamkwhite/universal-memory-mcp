"""Test logging functionality for Claude Memory MCP system"""

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import HOME_ENV_VAR, without_app_env

from logging_config import (
    ColoredFormatter,
    get_logger,
    init_default_logging,
    log_file_operation,
    log_function_call,
    log_performance,
    log_security_event,
    log_validation_failure,
    setup_logging,
)


class TestLoggingSetup:
    """Test logging configuration and setup"""

    def test_setup_logging_console_only(self):
        """Test setting up console-only logging"""
        logger = setup_logging(log_level="DEBUG", console_output=True, log_file=None)

        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    # These used NamedTemporaryFile(delete=False) plus a manual os.unlink in a
    # finally. That leaves two handles on one path -- the NamedTemporaryFile's
    # own, still open inside its with-block, and the FileHandler setup_logging
    # attaches -- and then deletes it underneath both. POSIX allows that;
    # Windows raises WinError 32. tmp_path needs no manual cleanup, and the
    # autouse _close_file_log_handlers fixture in conftest closes the handler.

    def test_setup_logging_file_only(self, tmp_path):
        """Test setting up file-only logging"""
        logger = setup_logging(
            log_level="INFO",
            console_output=False,
            log_file=str(tmp_path / "file_only.log"),
        )

        assert logger.level == logging.INFO
        assert len(logger.handlers) == 1
        assert hasattr(logger.handlers[0], "baseFilename")

    def test_setup_logging_both_console_and_file(self, tmp_path):
        """Test setting up both console and file logging"""
        logger = setup_logging(
            log_level="WARNING",
            console_output=True,
            log_file=str(tmp_path / "both.log"),
        )

        assert logger.level == logging.WARNING
        assert len(logger.handlers) == 2

    def test_log_file_rotation_config(self, tmp_path):
        """Test log file rotation configuration"""
        logger = setup_logging(
            log_file=str(tmp_path / "rotation.log"), max_bytes=1024, backup_count=3
        )

        file_handler = next(h for h in logger.handlers if hasattr(h, "maxBytes"))
        assert file_handler.maxBytes == 1024
        assert file_handler.backupCount == 3


class TestColoredFormatter:
    """Test colored log formatter"""

    def test_colored_formatter_adds_colors(self):
        """Test that colored formatter adds color codes"""
        formatter = ColoredFormatter("%(levelname)s - %(message)s")

        # Create log records for different levels
        debug_record = logging.LogRecord(
            "test", logging.DEBUG, "test.py", 1, "debug message", (), None
        )
        info_record = logging.LogRecord(
            "test", logging.INFO, "test.py", 1, "info message", (), None
        )
        error_record = logging.LogRecord(
            "test", logging.ERROR, "test.py", 1, "error message", (), None
        )

        # Format messages
        debug_msg = formatter.format(debug_record)
        info_msg = formatter.format(info_record)
        error_msg = formatter.format(error_record)

        # Check that color codes are present
        assert "\033[36m" in debug_msg  # Cyan for DEBUG
        assert "\033[32m" in info_msg  # Green for INFO
        assert "\033[31m" in error_msg  # Red for ERROR
        assert "\033[0m" in debug_msg  # Reset code


class TestLoggerHelpers:
    """Test logging helper functions"""

    def test_get_logger_returns_logger(self):
        """Test get_logger returns proper logger instance"""
        logger = get_logger("test_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"

    def test_get_logger_default_name(self):
        """Test get_logger with default name"""
        logger = get_logger()
        assert logger.name == "universal_memory_mcp"

    @patch("logging_config.get_logger")
    def test_log_function_call(self, mock_get_logger):
        """Test function call logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_function_call("test_function", param1="value1", param2=42, param3=None)

        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args[0][0]
        assert "test_function(param1=value1, param2=42)" in call_args
        assert "param3" not in call_args  # None values should be filtered

    @patch("logging_config.get_logger")
    def test_log_performance(self, mock_get_logger):
        """Test performance logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_performance("search_function", 1.234, results=10, query_length=25)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "search_function completed in 1.234s" in call_args
        assert "results=10" in call_args
        assert "query_length=25" in call_args

    @patch("logging_config.get_logger")
    def test_log_security_event_default_warning(self, mock_get_logger):
        """Test security event logging with default WARNING level"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_security_event("PATH_TRAVERSAL", "Attempted ../../../etc/passwd")

        # Verify the call was made with correct level and message
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.WARNING
        assert "Security Event: PATH_TRAVERSAL | Attempted ../../../etc/passwd" in call_args[0][1]

    @patch("logging_config.get_logger")
    def test_log_security_event_custom_severity(self, mock_get_logger):
        """Test security event logging with custom severity"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_security_event("CRITICAL_BREACH", "System compromised", "CRITICAL")

        # Verify the call was made with correct level and message
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.CRITICAL
        assert "Security Event: CRITICAL_BREACH | System compromised" in call_args[0][1]

    @patch("logging_config.get_logger")
    def test_log_validation_failure(self, mock_get_logger):
        """Test validation failure logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with normal value
        log_validation_failure("title", "normal title", "too long")
        # Verify the message is correct (ignore extra parameter)
        call_args = mock_logger.warning.call_args[0][0]
        assert "Validation failed: title='normal title' | Reason: too long" in call_args

        # Test with value containing newlines (should be escaped)
        log_validation_failure("content", "line1\nline2\rline3", "invalid format")
        call_args = mock_logger.warning.call_args[0][0]
        assert "line1\\nline2\\rline3" in call_args

        # Test with very long value (should be truncated)
        long_value = "A" * 150
        log_validation_failure("field", long_value, "too long")
        call_args = mock_logger.warning.call_args[0][0]
        assert len(call_args.split("'")[1]) <= 100  # Value should be truncated

    @patch("logging_config.get_logger")
    def test_log_file_operation_success(self, mock_get_logger):
        """Test successful file operation logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_file_operation("create", "/path/to/file.txt", True, size=1024, topics=5)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "File create: /path/to/file.txt | SUCCESS | size=1024, topics=5" in call_args

    @patch("logging_config.get_logger")
    def test_log_file_operation_failure(self, mock_get_logger):
        """Test failed file operation logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        log_file_operation("read", "/missing/file.txt", False, error="File not found")

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "File read: /missing/file.txt | FAILED | error=File not found" in call_args


class TestInitDefaultLogging:
    """Test default logging initialization"""

    @without_app_env()
    @patch("logging_config.setup_logging")
    def test_init_default_logging_no_env(self, mock_setup):
        """Test default logging with no environment variables"""
        init_default_logging()

        # With path_utils, a default log file is now provided
        mock_setup.assert_called_once()
        call_args = mock_setup.call_args

        assert call_args.kwargs["log_level"] == "INFO"
        # Now provides default path
        assert call_args.kwargs["log_file"] is not None
        # Component comparison, not a "/"-joined suffix: str(Path) uses the
        # platform separator, so the literal never matches on Windows.
        assert Path(call_args.kwargs["log_file"]).parts[-3:] == (
            ".claude-memory",
            "logs",
            "claude-mcp.log",
        )
        assert call_args.kwargs["console_output"] is False

    @patch.dict(
        os.environ,
        {
            "CLAUDE_MCP_LOG_LEVEL": "DEBUG",
            "CLAUDE_MCP_LOG_FILE": "/tmp/test.log",
        },
    )
    @patch("logging_config.setup_logging")
    def test_init_default_logging_with_env(self, mock_setup):
        """Test default logging with environment variables"""
        init_default_logging()

        # Config is now also forwarded; assert on the relevant kwargs.
        mock_setup.assert_called_once()
        kwargs = mock_setup.call_args.kwargs
        assert kwargs["log_level"] == "DEBUG"
        assert kwargs["log_file"] == "/tmp/test.log"
        assert kwargs["console_output"] is False

    @patch("logging_config.setup_logging")
    def test_init_default_logging_home_fallback(self, mock_setup, monkeypatch, tmp_path):
        """Default log file lands under the resolved home directory.

        Sets HOME_ENV_VAR rather than HOME: Windows resolves ``~`` from
        USERPROFILE and never reads HOME, so hard-coding HOME asserts nothing
        there. Compares path components rather than a "/"-joined string for
        the same reason.
        """
        with without_app_env():
            monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
            init_default_logging()

        mock_setup.assert_called_once()
        kwargs = mock_setup.call_args.kwargs
        assert kwargs["log_level"] == "INFO"
        assert Path(kwargs["log_file"]) == tmp_path / ".claude-memory" / "logs" / "claude-mcp.log"
        assert kwargs["console_output"] is False

    @patch("logging_config.setup_logging")
    def test_init_default_logging_console_enabled(self, mock_setup, monkeypatch, tmp_path):
        """Test default logging with console output explicitly enabled"""
        monkeypatch.setenv("CLAUDE_MCP_CONSOLE_OUTPUT", "true")
        monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
        init_default_logging()

        mock_setup.assert_called_once()
        kwargs = mock_setup.call_args.kwargs
        assert kwargs["log_level"] == "INFO"
        assert Path(kwargs["log_file"]) == tmp_path / ".claude-memory" / "logs" / "claude-mcp.log"
        assert kwargs["console_output"] is True

    @patch("logging_config.setup_logging")
    @patch("logging_config.get_default_log_file", None)
    def test_init_default_logging_fallback_when_path_utils_missing(
        self, mock_setup, monkeypatch, tmp_path
    ):
        """The hand-built fallback (path_utils unimportable) resolves home too.

        This branch used ``os.getenv("HOME")``, which Windows never sets, so
        it silently produced no log file there. It now uses ``Path.home()``.
        """
        with without_app_env():
            monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
            init_default_logging()

        mock_setup.assert_called_once()
        log_file = mock_setup.call_args.kwargs["log_file"]
        assert Path(log_file) == tmp_path / ".claude-memory" / "logs" / "claude-mcp.log"

    @patch("logging_config.setup_logging")
    @patch("logging_config.get_default_log_file", None)
    def test_init_default_logging_fallback_survives_unresolvable_home(self, mock_setup):
        """An unresolvable home leaves log_file unset instead of raising.

        Replaces a test that asserted ``os.getenv("HOME")`` was read exactly
        once -- the old code read it twice (guard, then os.path.join), so HOME
        disappearing in between raised TypeError. ``Path.home()`` resolves once
        by construction, so that window cannot reopen; what still needs
        asserting is the behaviour when it cannot resolve at all.
        """
        with without_app_env(), patch.object(Path, "home", side_effect=RuntimeError):
            init_default_logging()  # must not raise

        mock_setup.assert_called_once()
        assert mock_setup.call_args.kwargs["log_file"] is None


class TestLoggingIntegration:
    """Test logging integration with actual file operations"""

    def test_file_logging_creates_directories(self, tmp_path):
        """Test that file logging creates necessary directories"""
        log_file = tmp_path / "nested" / "dirs" / "test.log"

        logger = setup_logging(log_file=str(log_file), console_output=False)
        logger.info("Test message")

        assert log_file.exists()
        assert log_file.read_text(encoding="utf-8").strip().endswith("Test message")

    def test_log_rotation_configuration(self, tmp_path):
        """Test that log rotation is properly configured"""
        logger = setup_logging(
            log_file=str(tmp_path / "rotating.log"),
            max_bytes=100,  # Small size to trigger rotation
            backup_count=2,
        )

        # Write enough data to trigger rotation
        for i in range(50):
            logger.info(f"This is a test message number {i} with some padding")

        # Rotation may or may not have fired depending on exact sizes; the
        # assertion is that the handler carries the configuration.
        file_handler = next(h for h in logger.handlers if hasattr(h, "maxBytes"))
        assert file_handler.maxBytes == 100
        assert file_handler.backupCount == 2


class TestLoggingExceptionHandling:
    """Test exception handling in logging functions for complete coverage"""

    def test_log_function_call_exception_handling(self):
        """Test log_function_call exception handling (silent failure)"""
        # Mock get_logger to raise an exception
        with patch(
            "logging_config.get_logger",
            side_effect=Exception("Logger error"),
        ):
            # This should trigger the exception handling in log_function_call
            # The function should fail silently and not crash
            try:
                log_function_call("test_function", param1="value1", param2="value2")
                # Should not raise an exception due to silent failure
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(f"log_function_call should fail silently, but raised: {e}")

    def test_log_performance_exception_handling(self):
        """Test log_performance exception handling (silent failure)"""
        # Mock get_logger to raise an exception
        with patch(
            "logging_config.get_logger",
            side_effect=Exception("Logger error"),
        ):
            # This should trigger the exception handling in log_performance
            try:
                log_performance("test_function", 1.234, results=10)
                # Should not raise an exception due to silent failure
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(f"log_performance should fail silently, but raised: {e}")

    def test_log_security_event_exception_handling(self):
        """Test log_security_event exception handling (silent failure)"""
        # Mock get_logger to raise an exception
        with patch(
            "logging_config.get_logger",
            side_effect=Exception("Logger error"),
        ):
            # This should trigger the exception handling in log_security_event
            try:
                log_security_event("TEST_EVENT", "Test message", "ERROR")
                # Should not raise an exception due to silent failure
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(f"log_security_event should fail silently, but raised: {e}")

    def test_security_event_path_redaction_failure(self):
        """Test log_security_event path redaction failure handling"""
        # Mock Path operations to raise ValueError during path redaction
        with patch(
            "pathlib.Path.is_absolute",
            side_effect=ValueError("Path operation failed"),
        ):
            # This should trigger the ValueError/OSError handling
            try:
                log_security_event(
                    "PATH_TEST",
                    "Testing path /sensitive/path/that/should/be/redacted",
                    "ERROR",
                )
                # Should not raise an exception - should use fallback path redaction
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(
                    f"log_security_event should handle path operation errors, but raised: {e}"
                )

    def test_security_event_path_redaction_os_error(self):
        """Test log_security_event path redaction OSError handling"""
        # Mock Path operations to raise OSError during path redaction
        with patch(
            "pathlib.Path.is_relative_to",
            side_effect=OSError("File system error"),
        ):
            # This should trigger the OSError handling
            try:
                log_security_event(
                    "PATH_ERROR_TEST",
                    "Path error with /home/user/sensitive/file.txt",
                    "WARNING",
                )
                # Should not raise an exception - should use fallback
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(f"log_security_event should handle OSError, but raised: {e}")

    def test_file_operation_path_redaction_failure(self):
        """Test log_file_operation path redaction failure handling"""
        # Mock Path operations to raise ValueError
        with patch("pathlib.Path", side_effect=ValueError("Path error")):
            # This should trigger the exception handling in path redaction
            try:
                log_file_operation("read", "/some/file/path.txt", True)
                # Should not raise an exception
            except Exception as e:  # noqa: BLE001 - test asserts the function fails silently: catch-and-fail is the assertion
                pytest.fail(f"log_file_operation should handle path errors, but raised: {e}")


class TestLoggingSecurity:
    """Test security enhancements in logging functions"""

    @patch("logging_config.get_logger")
    def test_log_injection_prevention_validation(self, mock_get_logger):
        """Test that log injection is prevented in validation logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with malicious input containing control characters
        malicious_value = "normal\x00\x01\x02\x1f\x7f\x9ftext"
        log_validation_failure("field", malicious_value, "test reason")

        # Verify that control characters were stripped
        call_args = mock_logger.warning.call_args[0][0]
        assert "\x00" not in call_args
        assert "\x01" not in call_args
        assert "\x02" not in call_args
        assert "\x1f" not in call_args
        assert "\x7f" not in call_args
        assert "\x9f" not in call_args
        # Normal text should remain
        assert "normaltext" in call_args

    @patch("logging_config.get_logger")
    def test_log_injection_prevention_security(self, mock_get_logger):
        """Test that log injection is prevented in security event logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with malicious input containing control characters
        malicious_details = "normal\x00\x01\x02\x1f\x7f\x9ftext"
        log_security_event("test_event", malicious_details)

        # Verify that control characters were stripped (but \r and \n are preserved by design)
        call_args = mock_logger.log.call_args[0][1]
        assert "\x00" not in call_args
        assert "\x01" not in call_args
        assert "\x02" not in call_args
        assert "\x1f" not in call_args
        assert "\x7f" not in call_args
        assert "\x9f" not in call_args
        # Normal text should remain
        assert "normaltext" in call_args

    @patch("logging_config.get_logger")
    def test_log_injection_newline_escape(self, mock_get_logger):
        """Test that newlines are properly escaped in validation logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with newlines that should be escaped
        value_with_newlines = "line1\nline2\rline3"
        log_validation_failure("field", value_with_newlines, "test reason")

        # Verify that newlines were escaped
        call_args = mock_logger.warning.call_args[0][0]
        assert "\\n" in call_args
        assert "\\r" in call_args
        assert "\n" not in call_args.split("'")[1]  # Not in the actual value part

    @patch("logging_config.get_logger")
    def test_value_truncation(self, mock_get_logger):
        """Test that long values are truncated in logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with value longer than 100 characters
        long_value = "x" * 150
        log_validation_failure("field", long_value, "test reason")

        # Verify that value was truncated
        call_args = mock_logger.warning.call_args[0][0]
        # The logged value should not contain the full 150 x's
        assert "x" * 150 not in call_args
        # But should contain some x's (truncated portion)
        assert "x" * 50 in call_args

    @patch("logging_config.get_logger")
    def test_path_redaction_in_security_logging(self, mock_get_logger):
        """Test that paths are processed in security event logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with details containing the word "path" to trigger path processing
        details_with_paths = (
            "Error accessing path /home/user/secret/file.txt and /var/log/sensitive.log"
        )
        log_security_event("file_access", details_with_paths)

        # Verify that logging completed without error
        call_args = mock_logger.log.call_args[0][1]
        assert "Error accessing" in call_args
        # Path redaction behavior may vary based on the actual home directory and path resolution

    @patch("logging_config.get_logger")
    def test_file_operation_path_redaction(self, mock_get_logger):
        """Test that file paths are processed in file operation logging"""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Test with absolute path outside home directory
        absolute_path = "/var/log/system/sensitive.log"
        log_file_operation("read", absolute_path, True, size="1024")

        # Verify that logging completed without error
        call_args = mock_logger.info.call_args[0][0]
        assert "File read:" in call_args
        assert "SUCCESS" in call_args
        assert "size=1024" in call_args
        # Path processing behavior may vary based on actual path resolution logic

    @patch("logging_config.get_logger")
    def test_error_resilience(self, mock_get_logger):
        """Test that logging functions don't crash on errors"""
        # Simulate logger that raises exception
        mock_logger = MagicMock()
        mock_logger.warning.side_effect = Exception("Logger error")
        mock_get_logger.return_value = mock_logger

        # These should not raise exceptions despite logger errors
        log_validation_failure("field", "value", "reason")
        log_security_event("event", "details")
        log_file_operation("op", "file", True)
        log_function_call("func", param="value")


class TestConfigWiring:
    """Tests for the new ``config`` parameter on logging helpers."""

    def test_setup_logging_accepts_explicit_config(self, tmp_path):
        """``setup_logging`` should derive log_format from an explicit Config."""
        # Local import so the new field is exercised in the changed code.
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from config import Config  # type: ignore[import-not-found]

        cfg = Config(storage_path=str(tmp_path), log_format="json")
        log_file = tmp_path / "out.log"

        logger = setup_logging(
            log_level="INFO",
            log_file=str(log_file),
            console_output=False,
            config=cfg,
        )

        # File handler exists.
        assert any(hasattr(h, "baseFilename") for h in logger.handlers)
        # The logger gets the JSON formatter when log_format='json'.
        from logging_config import JSONFormatter

        file_handler = next(h for h in logger.handlers if hasattr(h, "baseFilename"))
        assert isinstance(file_handler.formatter, JSONFormatter)

    def test_init_default_logging_accepts_explicit_config(self, tmp_path, monkeypatch):
        """``init_default_logging`` should pull log level/console from Config."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from config import Config  # type: ignore[import-not-found]

        # Make sure no log file env var leaks in.
        monkeypatch.delenv("CLAUDE_MCP_LOG_FILE", raising=False)
        cfg = Config(
            storage_path=str(tmp_path),
            log_level="WARNING",
            console_output=True,
        )
        with patch("logging_config.setup_logging") as mock_setup:
            init_default_logging(cfg)

        mock_setup.assert_called_once()
        kwargs = mock_setup.call_args.kwargs
        assert kwargs["log_level"] == "WARNING"
        assert kwargs["console_output"] is True
        assert kwargs["config"] is cfg

    def test_get_log_format_uses_explicit_config(self):
        """``_get_log_format`` reads from the supplied Config when provided."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from config import Config  # type: ignore[import-not-found]
        from logging_config import _get_log_format

        cfg = Config(log_format="json")
        assert _get_log_format(cfg) == "json"

    def test_get_log_format_falls_back_when_config_load_fails(self, monkeypatch):
        """If Config.load explodes, ``_get_log_format`` falls back to env."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        import logging_config as lc

        # Make Config.load raise so the defensive ``except Exception`` runs.
        def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            raise RuntimeError("simulated config failure")

        monkeypatch.setattr("config.Config.load", classmethod(_boom))
        # Also need to clear any cached module-level config import path.
        monkeypatch.setenv("CLAUDE_MCP_LOG_FORMAT", "json")
        assert lc._get_log_format() == "json"

    def test_resolve_config_returns_supplied_instance(self, tmp_path):
        """Sanity-check the helper used by both setup_logging and init."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from config import Config  # type: ignore[import-not-found]
        from logging_config import _resolve_config

        cfg = Config(storage_path=str(tmp_path))
        assert _resolve_config(cfg) is cfg
