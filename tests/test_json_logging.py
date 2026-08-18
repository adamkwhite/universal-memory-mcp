"""
Comprehensive test suite for JSON logging functionality

Tests JSONFormatter, environment variable handling, and all specialized logging functions
with both JSON and text formats.
"""

import json
import logging
import os
from io import StringIO

import pytest

from universal_memory_mcp.logging_config import (
    JSONFormatter,
    _get_log_format,
    log_file_operation,
    log_function_call,
    log_performance,
    log_security_event,
    log_validation_failure,
    setup_logging,
)


@pytest.fixture
def json_logger():
    """Create a logger with JSON formatter for testing"""
    logger = logging.getLogger("test_json_logger")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []

    # Create string buffer to capture log output
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.addHandler(handler)

    # Return both logger and buffer for assertions
    return logger, log_buffer


@pytest.fixture
def text_logger():
    """Create a logger with text formatter for testing"""
    logger = logging.getLogger("test_text_logger")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []

    # Create string buffer to capture log output
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(funcName)s() | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)

    # Return both logger and buffer for assertions
    return logger, log_buffer


@pytest.fixture
def temp_log_file(tmp_path):
    """Path for a log file the test's own setup_logging call will create.

    This used NamedTemporaryFile(delete=False) with an os.unlink in its
    teardown. Because pytest finalizes autouse fixtures *last*, that unlink
    ran before conftest's _close_file_log_handlers had closed the FileHandler
    setup_logging attaches to this path -- so on Windows the delete hit a live
    handle and every test using the fixture ended in a teardown error.
    tmp_path needs no explicit cleanup, which removes the ordering problem
    rather than working around it.
    """
    return str(tmp_path / "test.log")


@pytest.fixture(autouse=True)
def reset_env_vars():
    """Reset environment variables after each test"""
    original_format = os.getenv("CLAUDE_MCP_LOG_FORMAT")

    yield

    # Restore original value
    if original_format is not None:
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = original_format
    elif "CLAUDE_MCP_LOG_FORMAT" in os.environ:
        del os.environ["CLAUDE_MCP_LOG_FORMAT"]


class TestJSONFormatterBasic:
    """Test JSONFormatter basic functionality"""

    def test_json_formatter_basic_fields(self, json_logger):
        """Test that JSONFormatter produces valid JSON with all standard fields"""
        logger, log_buffer = json_logger

        # Log a test message
        logger.info("Test message")

        # Get the logged output
        log_output = log_buffer.getvalue().strip()

        # Parse as JSON
        log_data = json.loads(log_output)

        # Verify all standard fields are present
        assert "timestamp" in log_data
        assert "level" in log_data
        assert "logger" in log_data
        assert "function" in log_data
        assert "line" in log_data
        assert "message" in log_data

        # Verify field values
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test_json_logger"
        assert log_data["message"] == "Test message"
        assert isinstance(log_data["line"], int)
        assert log_data["line"] > 0

    def test_all_log_levels_produce_valid_json(self, json_logger):
        """Test that all log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL) produce valid JSON"""
        logger, log_buffer = json_logger

        # Test all log levels
        log_levels = [
            (logging.DEBUG, "DEBUG", "Debug message"),
            (logging.INFO, "INFO", "Info message"),
            (logging.WARNING, "WARNING", "Warning message"),
            (logging.ERROR, "ERROR", "Error message"),
            (logging.CRITICAL, "CRITICAL", "Critical message"),
        ]

        for level_int, level_name, message in log_levels:
            # Clear buffer
            log_buffer.truncate(0)
            log_buffer.seek(0)

            # Log at this level
            logger.log(level_int, message)

            # Get output and parse
            log_output = log_buffer.getvalue().strip()
            log_data = json.loads(log_output)

            # Verify level
            assert log_data["level"] == level_name
            assert log_data["message"] == message

    def test_json_parsing_validates_structure(self, json_logger):
        """Test that JSON output can be parsed and has correct structure"""
        logger, log_buffer = json_logger

        # Log message with various field types
        logger.info("Test message")

        # Get output
        log_output = log_buffer.getvalue().strip()

        # Should parse without errors
        log_data = json.loads(log_output)

        # Verify types
        assert isinstance(log_data, dict)
        assert isinstance(log_data["timestamp"], str)
        assert isinstance(log_data["level"], str)
        assert isinstance(log_data["logger"], str)
        assert isinstance(log_data["function"], str)
        assert isinstance(log_data["line"], int)
        assert isinstance(log_data["message"], str)

    def test_json_formatter_with_context(self, json_logger):
        """Test that context field is serialized correctly"""
        logger, log_buffer = json_logger

        # Log with context
        test_context = {
            "type": "test",
            "user_id": 123,
            "tags": ["python", "logging"],
            "metadata": {"key": "value"},
        }

        logger.info("Test with context", extra={"context": test_context})

        # Parse output
        log_output = log_buffer.getvalue().strip()
        log_data = json.loads(log_output)

        # Verify context is present and correct
        assert "context" in log_data
        assert log_data["context"] == test_context
        assert log_data["context"]["type"] == "test"
        assert log_data["context"]["user_id"] == 123
        assert log_data["context"]["tags"] == ["python", "logging"]
        assert log_data["context"]["metadata"]["key"] == "value"

    def test_non_serializable_objects_fallback(self, json_logger):
        """Test that non-serializable objects fallback to string representation"""
        logger, log_buffer = json_logger

        # Create a non-serializable object
        class CustomObject:
            def __repr__(self):
                return "<CustomObject instance>"

        # Log with non-serializable context
        non_serializable_context = {
            "type": "test",
            "custom_obj": CustomObject(),
        }

        logger.info(
            "Test with non-serializable",
            extra={"context": non_serializable_context},
        )

        # Parse output
        log_output = log_buffer.getvalue().strip()
        log_data = json.loads(log_output)

        # Should have context as string (fallback)
        assert "context" in log_data
        assert isinstance(log_data["context"], str)
        # The string representation should contain info about the object
        assert "CustomObject" in log_data["context"] or "type" in log_data["context"]


class TestEnvironmentVariableHandling:
    """Test environment variable configuration for log format"""

    def test_get_log_format_default_text(self):
        """Test that _get_log_format defaults to 'text' when not set"""
        # Ensure env var is not set
        if "CLAUDE_MCP_LOG_FORMAT" in os.environ:
            del os.environ["CLAUDE_MCP_LOG_FORMAT"]

        result = _get_log_format()
        assert result == "text"

    def test_get_log_format_json(self):
        """Test that _get_log_format returns 'json' when set"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"
        result = _get_log_format()
        assert result == "json"

    def test_get_log_format_text(self):
        """Test that _get_log_format returns 'text' when explicitly set"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "text"
        result = _get_log_format()
        assert result == "text"

    def test_get_log_format_case_insensitive(self):
        """Test that _get_log_format is case insensitive"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "JSON"
        result = _get_log_format()
        assert result == "json"

        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "Text"
        result = _get_log_format()
        assert result == "text"

    def test_get_log_format_invalid_defaults_to_text(self):
        """Test that invalid values default to 'text' with warning"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "invalid"
        result = _get_log_format()
        assert result == "text"

    def test_setup_logging_uses_json_formatter(self, temp_log_file):
        """Test that setup_logging uses JSONFormatter when CLAUDE_MCP_LOG_FORMAT=json"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        logger = setup_logging(log_level="INFO", log_file=temp_log_file, console_output=False)

        # Check that file handler uses JSONFormatter
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_setup_logging_uses_text_formatter(self, temp_log_file):
        """Test that setup_logging uses text formatter when CLAUDE_MCP_LOG_FORMAT=text"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "text"

        logger = setup_logging(log_level="INFO", log_file=temp_log_file, console_output=False)

        # Check that file handler uses standard formatter
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, logging.Formatter)
        assert not isinstance(handler.formatter, JSONFormatter)


class TestSpecializedLoggingFunctions:
    """Integration tests for specialized logging functions with JSON format"""

    def test_log_performance_with_json_format(self, temp_log_file):
        """Test log_performance() produces correct JSON with structured context"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        setup_logging(log_level="INFO", log_file=temp_log_file, console_output=False)

        # Log performance metric
        log_performance("test_function", 0.123, query_count=5, cache_hits=3)

        # Read log file
        with open(temp_log_file, encoding="utf-8") as f:
            log_output = f.read().strip()

        # Parse JSON
        log_data = json.loads(log_output)

        # Verify structure
        assert log_data["message"].startswith("Performance: test_function")
        assert "context" in log_data
        assert log_data["context"]["type"] == "performance"
        assert log_data["context"]["duration_seconds"] == 0.123
        assert log_data["context"]["query_count"] == 5
        assert log_data["context"]["cache_hits"] == 3

    def test_log_security_event_with_json_format_and_redaction(self, temp_log_file):
        """Test log_security_event() with JSON format and path redaction"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        setup_logging(log_level="WARNING", log_file=temp_log_file, console_output=False)

        # Log security event with path
        log_security_event(
            "path_traversal_attempt",
            "Blocked suspicious path: /etc/passwd",
            severity="WARNING",
        )

        # Read log file
        with open(temp_log_file, encoding="utf-8") as f:
            log_output = f.read().strip()

        # Parse JSON
        log_data = json.loads(log_output)

        # Verify structure
        assert log_data["level"] == "WARNING"
        assert "context" in log_data
        assert log_data["context"]["type"] == "security"
        assert log_data["context"]["event_type"] == "path_traversal_attempt"
        assert log_data["context"]["severity"] == "WARNING"
        # Path should be redacted
        assert (
            "<redacted_path>" in log_data["context"]["details"]
            or "passwd" not in log_data["context"]["details"]
        )

    def test_log_validation_failure_with_json_format_and_sanitization(self, temp_log_file):
        """Test log_validation_failure() with JSON format and sanitization"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        setup_logging(log_level="WARNING", log_file=temp_log_file, console_output=False)

        # Log validation failure with potentially dangerous input
        log_validation_failure(
            "username",
            "test\nuser\x00malicious",
            "Contains control characters",
        )

        # Read log file
        with open(temp_log_file, encoding="utf-8") as f:
            log_output = f.read().strip()

        # Parse JSON
        log_data = json.loads(log_output)

        # Verify structure
        assert log_data["level"] == "WARNING"
        assert "context" in log_data
        assert log_data["context"]["type"] == "validation"
        assert log_data["context"]["field"] == "username"
        # Control characters should be sanitized
        assert "\x00" not in log_data["context"]["value"]
        assert log_data["context"]["reason"] == "Contains control characters"

    def test_log_file_operation_with_json_format(self, temp_log_file):
        """Test log_file_operation() with JSON format"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        setup_logging(log_level="INFO", log_file=temp_log_file, console_output=False)

        # Log file operation
        log_file_operation(
            "write",
            "/tmp/test.txt",
            success=True,
            size_bytes=1024,
            duration_ms=15,
        )

        # Read log file
        with open(temp_log_file, encoding="utf-8") as f:
            log_output = f.read().strip()

        # Parse JSON
        log_data = json.loads(log_output)

        # Verify structure
        assert log_data["level"] == "INFO"
        assert "context" in log_data
        assert log_data["context"]["type"] == "file_operation"
        assert log_data["context"]["operation"] == "write"
        assert log_data["context"]["success"] is True
        assert log_data["context"]["size_bytes"] == "1024"
        assert log_data["context"]["duration_ms"] == "15"

    def test_log_function_call_with_json_format(self, temp_log_file):
        """Test log_function_call() with JSON format"""
        os.environ["CLAUDE_MCP_LOG_FORMAT"] = "json"

        setup_logging(log_level="DEBUG", log_file=temp_log_file, console_output=False)

        # Log function call
        log_function_call("test_function", param1="value1", param2=42)

        # Read log file
        with open(temp_log_file, encoding="utf-8") as f:
            log_output = f.read().strip()

        # Parse JSON
        log_data = json.loads(log_output)

        # Verify structure
        assert log_data["level"] == "DEBUG"
        assert "context" in log_data
        assert log_data["context"]["type"] == "function_call"
        assert log_data["context"]["function"] == "test_function"
        assert log_data["context"]["params"]["param1"] == "value1"
        assert log_data["context"]["params"]["param2"] == 42
