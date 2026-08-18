"""
Test suite for correlation ID support (issue #16).

Covers: ContextVar get/set semantics, propagation across await boundaries,
isolation between concurrent asyncio tasks, the CorrelationIdFilter, and
JSONFormatter/text-formatter output.
"""

import asyncio
import json
import logging
import uuid
from io import StringIO

import pytest

from universal_memory_mcp.logging_config import (
    NO_CORRELATION_ID,
    CorrelationIdFilter,
    JSONFormatter,
    get_correlation_id,
    set_correlation_id,
)


@pytest.fixture(autouse=True)
def _reset_correlation_id():
    """Every test starts (and ends) with no correlation ID set."""
    from universal_memory_mcp.logging_config import _correlation_id

    yield
    _correlation_id.set(None)


class TestCorrelationIdBasics:
    def test_get_returns_none_when_unset(self):
        assert get_correlation_id() is None

    def test_set_generates_uuid4_when_omitted(self):
        value = set_correlation_id()
        assert get_correlation_id() == value
        # Must be a valid UUID4 string
        parsed = uuid.UUID(value, version=4)
        assert str(parsed) == value

    def test_set_uses_explicit_value(self):
        value = set_correlation_id("my-explicit-id")
        assert value == "my-explicit-id"
        assert get_correlation_id() == "my-explicit-id"

    def test_successive_calls_generate_different_ids(self):
        first = set_correlation_id()
        second = set_correlation_id()
        assert first != second


class TestCorrelationIdFilter:
    def test_filter_stamps_record_and_always_returns_true(self):
        set_correlation_id("stamped-id")
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
        result = CorrelationIdFilter().filter(record)
        assert result is True
        assert record.correlation_id == "stamped-id"

    def test_filter_uses_placeholder_when_unset(self):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
        CorrelationIdFilter().filter(record)
        assert record.correlation_id == NO_CORRELATION_ID


class TestCorrelationIdAsyncPropagation:
    @pytest.mark.asyncio
    async def test_propagates_across_await_boundary(self):
        set_correlation_id("await-test-id")

        async def inner():
            await asyncio.sleep(0)
            return get_correlation_id()

        assert await inner() == "await-test-id"

    @pytest.mark.asyncio
    async def test_concurrent_tasks_do_not_leak_ids(self):
        async def operation(op_id: str):
            set_correlation_id(op_id)
            await asyncio.sleep(0.01)
            # After the await, this task must still see its own ID, not a
            # sibling task's ID.
            return get_correlation_id()

        results = await asyncio.gather(
            operation("task-a"), operation("task-b"), operation("task-c")
        )
        assert results == ["task-a", "task-b", "task-c"]


class TestCorrelationIdFormatterOutput:
    def _make_json_logger(self):
        logger = logging.getLogger("test_correlation_json_logger")
        logger.setLevel(logging.DEBUG)
        logger.handlers = []
        logger.filters = []
        logger.addFilter(CorrelationIdFilter())
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        return logger, buf

    def test_json_output_includes_correlation_id_when_set(self):
        logger, buf = self._make_json_logger()
        set_correlation_id("json-corr-id")
        logger.info("hello")
        data = json.loads(buf.getvalue().strip())
        assert data["correlation_id"] == "json-corr-id"

    def test_json_output_omits_correlation_id_when_unset(self):
        logger, buf = self._make_json_logger()
        logger.info("hello")
        data = json.loads(buf.getvalue().strip())
        assert "correlation_id" not in data

    def test_text_formatter_includes_correlation_id(self):
        logger = logging.getLogger("test_correlation_text_logger")
        logger.setLevel(logging.DEBUG)
        logger.handlers = []
        logger.filters = []
        logger.addFilter(CorrelationIdFilter())
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s | [%(correlation_id)s]"))
        logger.addHandler(handler)

        set_correlation_id("text-corr-id")
        logger.info("hello")
        assert "[text-corr-id]" in buf.getvalue()
