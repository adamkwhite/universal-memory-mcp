"""
End-to-end tests for the logging *wiring* set up by setup_logging().

This file exists because PR #157 (correlation IDs) and PR #160 (log
sampling) each shipped with unit tests for their filter *classes* only
(instantiate the filter, call .filter(record) directly) and never asserted
that a record survives the REAL configured logger end-to-end. Both filters
were attached to the "universal_memory_mcp" logger itself, but the app logs
through CHILD loggers (get_logger("universal_memory_mcp.server") etc.).
Python only consults a logger's own filters for records it emits directly —
never for records propagating up from a descendant logger to the parent's
handlers. The result: every child-logger record hit the default TEXT
formatter's "[%(correlation_id)s]" field with no such attribute set,
raised, and was silently dropped. Application logging was dead in
production for an hour before this was caught.

These tests exercise the real setup_logging() -> child logger -> handler ->
formatter path, the same path server_fastmcp.py uses, so a regression here
fails loudly instead of passing on a technicality.
"""

import pytest

from logging_config import (
    SamplingFilter,
    get_logger,
    set_correlation_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_correlation_id():
    """Mirrors test_correlation_id.py's fixture: don't leak a correlation ID
    set by one test into whatever test (in this file or another) runs next
    in the same process/thread."""
    from logging_config import _correlation_id

    yield
    _correlation_id.set(None)


class TestCorrelationIdEndToEnd:
    """Mandatory test #1: default text format, child logger, no dropped
    records, no formatting error."""

    def test_child_logger_record_lands_in_file_with_default_text_format(self, tmp_path, capsys):
        log_file = tmp_path / "app.log"

        # Default format ("text"), the same as init_default_logging() uses
        # in production. console_output=False keeps stdout clean for the
        # capsys assertion below.
        setup_logging(log_file=str(log_file), console_output=False)

        set_correlation_id("e2e-test-id")
        child_logger = get_logger("universal_memory_mcp.server")
        child_logger.info("child logger message")

        # No "--- Logging error ---" / traceback should have been printed
        # to stderr by Handler.handleError() (the KeyError path this bug
        # hit lives there, since RotatingFileHandler swallows the
        # exception rather than raising it out of .info()).
        captured = capsys.readouterr()
        assert "Logging error" not in captured.err
        assert "KeyError" not in captured.err

        # The line must actually be written — this is the assertion that
        # fails outright on unfixed main: the record never reaches the file
        # at all (the KeyError happens during formatting, inside the
        # handler, after the record was already accepted).
        contents = log_file.read_text()
        assert "child logger message" in contents
        assert "e2e-test-id" in contents


class TestSamplingEndToEnd:
    """Mandatory test #2: sampling actually samples through a child logger,
    and WARNING/ERROR are never sampled."""

    def test_sampling_through_child_logger_drops_records_at_configured_rate(self, tmp_path):
        from config import Config

        log_file = tmp_path / "sampled.log"
        rate = 5
        cfg = Config(log_sample_rates={"noisy": rate})
        setup_logging(config=cfg, log_file=str(log_file), console_output=False)

        child_logger = get_logger("universal_memory_mcp.server")
        total = 50
        for i in range(total):
            child_logger.info(f"noisy record {i}", extra={"context": {"type": "noisy"}})

        lines = [line for line in log_file.read_text().splitlines() if "noisy record" in line]
        assert len(lines) == total // rate

    def test_warning_and_error_are_never_sampled_through_child_logger(self, tmp_path):
        from config import Config

        log_file = tmp_path / "warnings.log"
        # Absurdly high rate: if WARNING/ERROR were subject to sampling,
        # essentially none of them would appear.
        cfg = Config(log_sample_rates={"noisy": 1000})
        setup_logging(config=cfg, log_file=str(log_file), console_output=False)

        child_logger = get_logger("universal_memory_mcp.server")
        for i in range(10):
            child_logger.warning(f"warning {i}", extra={"context": {"type": "noisy"}})
            child_logger.error(f"error {i}", extra={"context": {"type": "noisy"}})

        contents = log_file.read_text()
        for i in range(10):
            assert f"warning {i}" in contents
            assert f"error {i}" in contents


class TestNoDoubleCountingAcrossHandlers:
    """Mandatory test #3: a shared SamplingFilter instance on 2 handlers
    must not double-count (i.e. must not sample at 2x the configured
    rate)."""

    def test_two_handlers_do_not_double_count(self, tmp_path):
        from config import Config

        log_file = tmp_path / "multi.log"
        rate = 4
        cfg = Config(log_sample_rates={"noisy": rate})
        # console_output=True + log_file=... attaches TWO handlers
        # (console StreamHandler and RotatingFileHandler) sharing the one
        # SamplingFilter instance created inside setup_logging().
        logger = setup_logging(config=cfg, log_file=str(log_file), console_output=True)

        sampling_filters = {
            id(f)
            for handler in logger.handlers
            for f in handler.filters
            if isinstance(f, SamplingFilter)
        }
        # Exactly one shared instance, not one-per-handler.
        assert len(sampling_filters) == 1

        child_logger = get_logger("universal_memory_mcp.server")
        total = 40
        for i in range(total):
            child_logger.info(f"noisy record {i}", extra={"context": {"type": "noisy"}})

        # If the counter advanced once per handler (double-counting), the
        # effective rate would be rate/2 and this would be total // (rate/2).
        file_lines = [line for line in log_file.read_text().splitlines() if "noisy record" in line]
        assert len(file_lines) == total // rate


def demo() -> None:
    """ponytail: smallest runnable self-check, not a pytest replacement."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        log_file = Path(d) / "demo.log"
        setup_logging(log_file=str(log_file), console_output=False)
        set_correlation_id("demo-id")
        get_logger("universal_memory_mcp.server").info("demo message")
        contents = log_file.read_text()
        assert "demo message" in contents, "child-logger record was dropped"
        assert "demo-id" in contents, "correlation id missing from output"
    print("demo() OK")


if __name__ == "__main__":
    demo()
