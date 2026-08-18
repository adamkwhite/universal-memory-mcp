#!/usr/bin/env python3
"""Test for JSONFormatter.format's *ultimate* fallback (line ~248),
flagged as untested new code in PR #175.

tests/test_json_logging.py already covers the first-level fallback: a
non-serializable ``context`` value gets stringified and the retry
succeeds. This test covers the deeper handler -- reached only when the
retry *still* fails because some other field (not "context") is
non-serializable, so stringifying context alone doesn't fix it. A
Formatter.format() must never raise (it would break the whole logging
pipeline), so even this double-failure case must still produce valid
JSON. Forced with a real (non-mocked) unserializable value assigned to
``correlation_id`` via a genuine LogRecord, not a mock of json.dumps.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.logging_config import JSONFormatter  # noqa: E402


def test_format_falls_back_to_basic_error_message_when_retry_still_fails():
    """A non-serializable ``correlation_id`` (not "context") survives the
    first fallback's context-stringification untouched, so the retry
    ``json.dumps`` genuinely fails a second time -- forcing the ultimate
    fallback. The result must still be valid, parseable JSON with an
    error message, not raise."""
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="hello",
        args=None,
        exc_info=None,
    )
    record.correlation_id = {1, 2, 3}  # a set: not JSON serializable

    output = JSONFormatter().format(record)

    parsed = json.loads(output)  # must not raise -- proves valid JSON was produced
    assert parsed["level"] == "ERROR"
    assert "Failed to serialize log record" in parsed["message"]
    # The unserializable field must not have leaked into the fallback output.
    assert "correlation_id" not in parsed
