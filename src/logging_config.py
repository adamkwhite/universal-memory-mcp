"""Logging configuration for Claude Memory MCP system.

Settings (log level, log format, console output) are sourced from
:class:`~config.Config`. Functions here accept an optional ``config``
parameter; when omitted, ``Config.load(validate=False)`` is used so existing
env-var-driven tests continue to work without modification.
"""

import contextlib
import contextvars
import json
import logging
import logging.handlers
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# Import path utilities for dynamic path resolution
try:
    from path_utils import get_default_log_file
except ImportError:
    # Fallback if path_utils is not available
    get_default_log_file = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from config import Config


def _resolve_config(config: "Config | None") -> "Config":
    """Return ``config`` when supplied, otherwise build one from env+file.

    Uses ``validate=False`` because logging setup is performed early in the
    process lifecycle and we don't want to raise on (e.g.) a missing storage
    directory just because someone wanted to write a log line.
    """
    if config is not None:
        return config
    from config import Config as _Config

    return _Config.load(validate=False)


# Control character removal pattern for log injection prevention
CONTROL_CHAR_PATTERN = r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]"

# ISO 8601 datetime format for structured logging
ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Correlation ID for tracing a high-level operation (search, add_conversation,
# weekly summary, ...) across log lines and await boundaries. A ContextVar
# (not thread-local) is required because this codebase is async/aiofiles
# throughout: each asyncio Task gets its own copy of the context, so
# concurrent operations never see each other's correlation ID, while a single
# operation's own await chain keeps seeing the value it set.
_correlation_id: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "correlation_id", default=None
)

# Placeholder used in log output when no correlation ID is set for the
# current context (e.g. logging during startup, before any operation began).
NO_CORRELATION_ID = "-"


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current context, if any."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Start (or attach to) a correlation ID for the current context.

    Call this once at the top of a high-level operation (a search, an
    ``add_conversation`` call, a weekly summary run). If ``correlation_id``
    is omitted, a new UUID4 is generated. Every log record emitted for the
    rest of this context — including across ``await`` boundaries within the
    same asyncio Task — carries the returned ID.

    Returns:
        str: The correlation ID now active for this context.
    """
    value = correlation_id or str(uuid.uuid4())
    _correlation_id.set(value)
    return value


class CorrelationIdFilter(logging.Filter):
    """Attach the current context's correlation ID to every log record.

    Always returns True (it never drops records) — it exists purely to
    stamp ``record.correlation_id`` so formatters can include it.

    Not used by ``setup_logging()`` itself (see ``_install_correlation_id_
    record_factory`` below for why) — kept as a standalone, directly
    testable unit and for anyone building a logger by hand outside this
    module's wiring.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or NO_CORRELATION_ID
        return True


# Root fix for correlation IDs: a LogRecord factory, not a filter.
#
# A *logger's* filters only run for records emitted through that exact
# logger — never for records propagating up from a child logger to the
# parent's handlers (Handler.handle() calls the handler's own filters, but
# nothing re-runs the ancestor Logger.filter() chain). This app logs
# through child loggers (get_logger("universal_memory_mcp.server") etc.), so a
# logger-level CorrelationIdFilter silently never fires for real traffic —
# that was the bug. A record factory is called by logging.Logger.makeRecord
# for *every* record, on *every* logger in the process (including
# third-party ones), so it can't be bypassed by propagation the way a
# filter can.
_stdlib_record_factory = logging.getLogRecordFactory()


def _correlation_id_record_factory(*args, **kwargs):
    record = _stdlib_record_factory(*args, **kwargs)
    record.correlation_id = get_correlation_id() or NO_CORRELATION_ID
    return record


def _install_correlation_id_record_factory() -> None:
    """Install the correlation-id-stamping record factory, idempotently.

    ``setup_logging()`` may be called many times in a process (tests do
    this routinely). Re-checking ``is not`` before installing avoids
    stacking wrapper-of-a-wrapper layers on repeated calls — each call
    after the first is a no-op.
    """
    if logging.getLogRecordFactory() is not _correlation_id_record_factory:
        logging.setLogRecordFactory(_correlation_id_record_factory)


class SamplingFilter(logging.Filter):
    """Drop a configurable fraction of high-frequency log records.

    A rate of N means "log 1 out of every N records of that operation
    type" (type == ``record.context["type"]``, falling back to
    ``"default"`` for records without structured context). A type absent
    from ``sample_rates`` — the default, empty-dict case — is never
    sampled, so this is a no-op until a rate is explicitly configured.

    WARNING and above are ALWAYS logged, regardless of sample rate: never
    sample away an error. ponytail: a plain per-type counter, not an
    adaptive-sampling engine; upgrade only if a real need for
    frequency-adaptive rates shows up.

    This filter is stateful (the per-type counters), so ``setup_logging()``
    attaches ONE shared instance to every handler on the logger rather than
    a filter-per-handler — handler-level filters are required (see the
    module-level note on ``CorrelationIdFilter``/record factory for why),
    but a handler's ``Handler.handle()`` calls ``self.filter()``
    independently for each handler that sees the record. With N handlers,
    a plain counter would advance N times per record and silently sample
    at N times the configured rate. The decision is cached on the record
    itself the first time this instance sees it, so every subsequent
    handler in the same emit reuses that decision instead of re-counting.
    """

    def __init__(self, sample_rates: dict | None = None):
        super().__init__()
        self.sample_rates = sample_rates or {}
        self._counters: dict = {}

    def filter(self, record: logging.LogRecord) -> bool:
        cached = getattr(record, "_sampling_decision", None)
        if cached is not None:
            return cached

        if record.levelno >= logging.WARNING:
            decision = True
        else:
            context = getattr(record, "context", None)
            op_type = context.get("type", "default") if isinstance(context, dict) else "default"
            rate = self.sample_rates.get(op_type, 1)
            if rate <= 1:
                decision = True
            else:
                count = self._counters.get(op_type, 0) + 1
                self._counters[op_type] = count
                decision = count % rate == 0

        record._sampling_decision = decision
        return decision


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging output.

    Outputs newline-delimited JSON (NDJSON) with standard fields:
    - timestamp: ISO 8601 formatted timestamp
    - level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - logger: Logger name
    - function: Function name where log was called
    - line: Line number where log was called
    - message: Log message
    - context: Optional structured context data (if present in record.context)

    Example output:
    {"timestamp": "2025-01-15T10:30:45.123Z", "level": "INFO", "logger": "universal_memory_mcp",
     "function": "add_conversation", "line": 145, "message": "Added conversation successfully",
     "context": {"conversation_id": "abc123", "topics": ["python", "mcp"]}}
    """

    def format(self, record):
        """
        Format a log record as a JSON object.

        Args:
            record: LogRecord instance to format

        Returns:
            str: JSON-formatted log message (single line)
        """
        # Build standard log data structure
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt or ISO_DATETIME_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        # Add correlation ID if one is active for this context (set via
        # CorrelationIdFilter, which runs before formatters see the record).
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id and correlation_id != NO_CORRELATION_ID:
            log_data["correlation_id"] = correlation_id

        # Add context if present in the log record
        if hasattr(record, "context"):
            log_data["context"] = record.context

        # Serialize to JSON with error handling
        try:
            return json.dumps(log_data)
        except (TypeError, ValueError) as e:
            # Fallback for non-serializable objects
            # Convert context to string representation if serialization fails
            if "context" in log_data:
                log_data["context"] = str(log_data["context"])
            try:
                return json.dumps(log_data)
            except Exception:  # noqa: BLE001 - ultimate JSON-serialization fallback: a Formatter.format() must never raise (breaks the whole logging pipeline)
                # Ultimate fallback: return basic error message
                return json.dumps(
                    {
                        "timestamp": self.formatTime(record, self.datefmt or ISO_DATETIME_FORMAT),
                        "level": "ERROR",
                        "logger": "logging_config",
                        "message": f"Failed to serialize log record: {str(e)}",
                    }
                )


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output"""

    COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        if hasattr(record, "levelname"):
            color = self.COLORS.get(record.levelname, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def _get_log_format(config: "Config | None" = None) -> str:
    """
    Get the log format, preferring an explicit :class:`~config.Config`.

    When ``config`` is omitted the value is sourced from
    ``Config.load(validate=False)``, which still consults
    ``CLAUDE_MCP_LOG_FORMAT`` (and the optional config file). Invalid values
    fall back to ``"text"`` with a warning, preserving the historical behaviour
    of this function.

    Args:
        config: Optional pre-loaded :class:`~config.Config` instance.

    Returns:
        str: Log format (``'json'`` or ``'text'``).

    Environment Variables:
        CLAUDE_MCP_LOG_FORMAT: Log output format (json|text). Default: text
    """
    try:
        cfg = _resolve_config(config)
        log_format = (cfg.log_format or "text").lower()
    except Exception:  # noqa: BLE001 - defensive: malformed config must never break logging setup (see comment above)
        # Defensive: never let a malformed config bring down logging setup.
        log_format = os.getenv("CLAUDE_MCP_LOG_FORMAT", "text").lower()

    # Validate format value
    valid_formats = ["json", "text"]
    if log_format not in valid_formats:
        # Log warning for invalid value and default to text
        logger = logging.getLogger("universal_memory_mcp")
        logger.warning(
            f"Invalid CLAUDE_MCP_LOG_FORMAT value: '{log_format}'. "
            f"Valid values are: {', '.join(valid_formats)}. Defaulting to 'text'."
        )
        return "text"

    return log_format


def _get_log_sample_rates(config: "Config | None" = None) -> dict:
    """Get per-operation-type log sample rates, preferring an explicit Config.

    Mirrors :func:`_get_log_format`'s defensive fallback: a malformed config
    must never break logging setup, so any error just disables sampling.
    """
    try:
        cfg = _resolve_config(config)
        return dict(cfg.log_sample_rates or {})
    except Exception:  # noqa: BLE001 - defensive: malformed config must never break logging setup (see comment above)
        return {}


def setup_logging(
    log_level: str = "INFO",
    log_file: str | None = None,
    console_output: bool = True,
    max_bytes: int = 10_485_760,  # 10MB
    backup_count: int = 5,
    config: "Config | None" = None,
) -> logging.Logger:
    """
    Set up comprehensive logging for the application

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (optional)
        console_output: Whether to output to console
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
        config: Optional pre-loaded :class:`~config.Config` instance.
            When supplied, the log format is sourced from it; otherwise
            ``Config.load(validate=False)`` is used (which still respects
            ``CLAUDE_MCP_LOG_FORMAT``).

    Returns:
        Configured logger instance

    Environment Variables:
        CLAUDE_MCP_LOG_FORMAT: Log format (json|text). Default: text
    """
    # Get logger
    logger = logging.getLogger("universal_memory_mcp")
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers/filters (setup_logging may be called more than
    # once, e.g. in tests, and filters would otherwise stack).
    logger.handlers = []
    logger.filters = []

    # Correlation IDs are stamped via a record factory (see the module-level
    # note above), not a logger filter — it works for propagated records too.
    _install_correlation_id_record_factory()

    # Sampling MUST be attached per-handler, not on the logger: this app
    # logs through child loggers (get_logger("universal_memory_mcp.<name>")),
    # and a logger's own filters never run for records that reach its
    # handlers via propagation from a descendant logger. One shared
    # instance is reused across handlers to avoid double-counting.
    sampling_filter = SamplingFilter(_get_log_sample_rates(config))

    # Determine log format via Config (env-aware) or the explicit instance.
    log_format = _get_log_format(config)

    # Create formatters based on log format
    file_formatter: logging.Formatter
    console_formatter: logging.Formatter

    if log_format == "json":
        # Use JSON formatter for both console and file
        file_formatter = JSONFormatter(datefmt=ISO_DATETIME_FORMAT)
        console_formatter = JSONFormatter(datefmt=ISO_DATETIME_FORMAT)
    else:
        # Use text formatters (default)
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(funcName)s() "
            "| [%(correlation_id)s] | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_formatter = ColoredFormatter(
            "%(asctime)s | %(levelname)-8s | %(funcName)s() | [%(correlation_id)s] | %(message)s",
            datefmt="%H:%M:%S",
        )

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.addFilter(sampling_filter)
        logger.addHandler(console_handler)

    # File handler with rotation
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # Always debug level for files
        file_handler.addFilter(sampling_filter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "universal_memory_mcp") -> logging.Logger:
    """Get a logger instance with the given name"""
    return logging.getLogger(name)


def log_function_call(func_name: str, **kwargs):
    """Log a function call with parameters and structured context"""
    try:
        logger = get_logger()
        # Only perform expensive parameter formatting if debug logging is enabled
        if logger.isEnabledFor(logging.DEBUG):
            # Create structured context for JSON logging
            context = {"type": "function_call", "function": func_name, "params": kwargs}
            params = ", ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
            logger.debug(f"Calling {func_name}({params})", extra={"context": context})
    except Exception:  # noqa: BLE001 - fail silently to prevent logging from crashing the application (see comment above)
        # Fail silently to prevent logging from crashing the application
        pass


def log_performance(func_name: str, duration: float, **metrics):
    """Log performance metrics with structured context"""
    try:
        logger = get_logger()
        # Create structured context for JSON logging
        context = {"type": "performance", "duration_seconds": duration, **metrics}
        metric_str = ", ".join(f"{k}={v}" for k, v in metrics.items())
        logger.info(
            f"Performance: {func_name} completed in {duration:.3f}s | {metric_str}",
            extra={"context": context},
        )
    except Exception:  # noqa: BLE001 - fail silently to prevent logging from crashing the application (see comment above)
        # Fail silently to prevent logging from crashing the application
        pass


def log_security_event(event_type: str, details: str, severity: str = "WARNING"):
    """Log security-related events with structured context"""
    try:
        import re
        from pathlib import Path

        logger = get_logger("universal_memory_mcp.security")
        level = getattr(logging, severity.upper())

        # Sanitize event_type and details to prevent log injection
        safe_event_type = re.sub(CONTROL_CHAR_PATTERN, "", str(event_type))
        safe_details = re.sub(CONTROL_CHAR_PATTERN, "", str(details))

        # For path-related events, use relative paths to avoid information disclosure
        if "path" in safe_details.lower():
            try:
                # Try to make paths relative to home directory
                home = Path.home()
                safe_details = re.sub(
                    r"/[^\s]+",
                    lambda m: (
                        str(Path(m.group()).relative_to(home))
                        if Path(m.group()).is_absolute() and Path(m.group()).is_relative_to(home)
                        else "<redacted_path>"
                    ),
                    safe_details,
                )
            except (ValueError, OSError):
                # If path operations fail, just redact the paths
                safe_details = re.sub(r"/[^\s]+", "<redacted_path>", safe_details)

        # Create structured context for JSON logging (with sanitized values)
        context = {
            "type": "security",
            "event_type": safe_event_type,
            "severity": severity,
            "details": safe_details,
        }

        logger.log(
            level,
            f"Security Event: {safe_event_type} | {safe_details}",
            extra={"context": context},
        )
    except Exception:  # noqa: BLE001 - fail silently to prevent logging from crashing the application (see comment above)
        # Fail silently to prevent logging from crashing the application
        pass


def log_validation_failure(field: str, value: str, reason: str):
    """Log input validation failures with structured context"""
    try:
        import re

        logger = get_logger("universal_memory_mcp.validation")
        # Comprehensive sanitization to prevent log injection
        safe_value = str(value)[:100]
        # Remove all control characters except safe whitespace
        safe_value = re.sub(CONTROL_CHAR_PATTERN, "", safe_value)
        # Escape remaining newlines and carriage returns for visibility
        safe_value = safe_value.replace("\n", "\\n").replace("\r", "\\r")
        # Sanitize field and reason as well
        safe_field = re.sub(CONTROL_CHAR_PATTERN, "", str(field))
        safe_reason = re.sub(CONTROL_CHAR_PATTERN, "", str(reason))

        # Create structured context for JSON logging (with sanitized values)
        context = {
            "type": "validation",
            "field": safe_field,
            "value": safe_value,
            "reason": safe_reason,
        }

        logger.warning(
            f"Validation failed: {safe_field}='{safe_value}' | Reason: {safe_reason}",
            extra={"context": context},
        )
    except Exception:  # noqa: BLE001 - fail silently to prevent logging from crashing the application (see comment above)
        # Fail silently to prevent logging from crashing the application
        pass


def log_file_operation(operation: str, file_path: str, success: bool, **details):
    """Log file operations with structured context"""
    try:
        import re
        from pathlib import Path

        logger = get_logger("universal_memory_mcp.files")
        status = "SUCCESS" if success else "FAILED"

        # Sanitize file path for logging (use relative path when possible)
        safe_file_path = str(file_path)
        try:
            home = Path.home()
            if Path(file_path).is_absolute() and Path(file_path).is_relative_to(home):
                safe_file_path = str(Path(file_path).relative_to(home))
        except (ValueError, OSError):
            # Use basename only if path operations fail
            safe_file_path = Path(file_path).name

        # Sanitize details
        safe_details = {}
        for k, v in details.items():
            safe_k = re.sub(CONTROL_CHAR_PATTERN, "", str(k))
            safe_v = re.sub(CONTROL_CHAR_PATTERN, "", str(v))
            safe_details[safe_k] = safe_v

        # Create structured context for JSON logging (with sanitized values)
        context = {
            "type": "file_operation",
            "operation": operation,
            "path": safe_file_path,
            "success": success,
            **safe_details,
        }

        detail_str = ", ".join(f"{k}={v}" for k, v in safe_details.items())
        logger.info(
            f"File {operation}: {safe_file_path} | {status} | {detail_str}",
            extra={"context": context},
        )
    except Exception:  # noqa: BLE001 - fail silently to prevent logging from crashing the application (see comment above)
        # Fail silently to prevent logging from crashing the application
        pass


# Default logging setup for the application
def init_default_logging(config: "Config | None" = None):
    """Initialize default logging configuration.

    Args:
        config: Optional pre-loaded :class:`~config.Config`. When omitted,
            ``Config.load(validate=False)`` is used so existing env-var-driven
            behaviour is preserved (``CLAUDE_MCP_LOG_LEVEL``,
            ``CLAUDE_MCP_CONSOLE_OUTPUT``).
    """
    cfg = _resolve_config(config)

    # Log level from Config (already upper-cased on validate, but safe).
    log_level = (cfg.log_level or "INFO").upper()

    # Get log file path from environment or use default. ``CLAUDE_MCP_LOG_FILE``
    # is not yet a Config field (deferred follow-up), so we still read it here.
    log_file = os.getenv("CLAUDE_MCP_LOG_FILE")
    if not log_file:
        if get_default_log_file is not None:
            # Use path_utils for dynamic path resolution. The helper accepts an
            # optional ``config`` kwarg in newer versions; older builds did not,
            # so we try with ``cfg`` first and gracefully fall back.
            try:
                log_file = str(get_default_log_file(cfg))
            except TypeError:
                log_file = str(get_default_log_file())
        else:
            # path_utils could not be imported, so construct the default by
            # hand. ``Path.home()`` rather than ``os.getenv("HOME")``: POSIX
            # falls back to the pwd database when HOME is unset, and Windows
            # resolves ``~`` from ``USERPROFILE`` (or ``HOMEDRIVE`` +
            # ``HOMEPATH``) and never consults ``HOME`` at all -- which made
            # this branch dead code there, silently leaving a Windows install
            # with no log file. It raises RuntimeError when it cannot resolve
            # a home directory, which is exactly the "leave log_file unset"
            # case the old ``if home:`` guard covered.
            #
            # Resolving once also closes the TOCTOU window the old code had:
            # it called os.getenv("HOME") twice, once to test and once inside
            # os.path.join, so HOME going away in between raised TypeError.
            with contextlib.suppress(RuntimeError):
                log_file = str(Path.home() / ".claude-memory" / "logs" / "claude-mcp.log")

    # Console output for MCP server mode (must remain False by default to
    # avoid corrupting the JSON-RPC stream over stdout).
    console_output = bool(cfg.console_output)

    # Set up logging
    return setup_logging(
        log_level=log_level,
        log_file=log_file,
        console_output=console_output,
        config=cfg,
    )
