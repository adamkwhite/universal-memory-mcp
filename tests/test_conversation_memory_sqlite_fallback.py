#!/usr/bin/env python3
"""Tests for ConversationMemoryServer's SQLite-failure fallback/handler
paths in search_conversations / search_by_topic / search_by_tag /
search_by_session_id / search_by_conversation_type.

Each of these wraps its call into ``self.search_db`` in a broad
``except Exception`` -- flagged as untested new code in PR #175 -- with one
of two documented contracts: fall through to the JSON-based search (topic
and full-text search have a JSON mirror), or surface a
``[{"error": ...}]`` result (tag/session/conversation_type have no JSON
mirror, per PR #114).

SearchDatabase's own methods already catch ``sqlite3.Error`` internally, so
dropping a table does *not* reach these outer handlers -- it's absorbed one
layer down (see test_search_database_error_handling.py). What *does* reach
these outer handlers, without any mocking, is a row whose ``topics_json``
column is not valid JSON: every SearchDatabase read method does an inline
``json.loads(row["topics_json"])`` that is *not* wrapped by its own
``except sqlite3.Error``, so a corrupted column genuinely raises
``json.JSONDecodeError`` up through SearchDatabase into these handlers.
This is a real gap (a corrupted DB row -- e.g. from a partial write --
would otherwise crash the caller), not a contrived mock.
"""

import logging
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from conversation_memory import ConversationMemoryServer  # noqa: E402


@pytest.fixture
def temp_storage():
    d = tempfile.mkdtemp(prefix="claude_memory_sqlite_fallback_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def server(temp_storage):
    return ConversationMemoryServer(temp_storage)


def _corrupt_topics_json(server, conversation_id: str) -> None:
    """Simulate a corrupted row (e.g. a partial/interrupted write) by
    forcing the topics_json column to non-JSON text via a direct SQL
    UPDATE -- not a mock of the exception, a genuine malformed row."""
    with closing(sqlite3.connect(server.search_db.db_path)) as conn, conn:
        conn.execute(
            "UPDATE conversations SET topics_json = 'not-json' WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()


@pytest.mark.asyncio
async def test_search_conversations_falls_back_to_linear_on_real_sqlite_failure(server, caplog):
    """search_conversations (line ~799): on a real (unmocked) SQLite
    search failure it must log a warning and fall through to the linear
    JSON search rather than raise or silently return nothing -- the linear
    fallback must still find the conversation."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    added = await server.add_conversation(
        content="Notes about python asyncio patterns", title="Async notes"
    )
    assert added["status"] == "success"
    conv_id = Path(added["file_path"]).stem
    _corrupt_topics_json(server, conv_id)

    with caplog.at_level(logging.WARNING):
        results = await server.search_conversations("asyncio", limit=5)

    assert any("falling back to linear search" in r.message for r in caplog.records)
    # The linear fallback must actually have found it -- not just "didn't crash".
    assert any(r.get("id") == conv_id for r in results)


@pytest.mark.asyncio
async def test_search_by_topic_falls_back_to_json_on_real_sqlite_failure(server, caplog):
    """search_by_topic (line ~1093): on a real SQLite topic-search failure
    it must log a warning and fall through to _search_topic_json, which
    must still find the conversation via topics.json."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    added = await server.add_conversation(
        content="Deep dive into python generators", title="Generators"
    )
    assert added["status"] == "success"
    conv_id = Path(added["file_path"]).stem
    _corrupt_topics_json(server, conv_id)

    with caplog.at_level(logging.WARNING):
        results = await server.search_by_topic("python", limit=5)

    assert any("SQLite topic search failed" in r.message for r in caplog.records)
    assert any(r.get("id") == conv_id for r in results)


@pytest.mark.asyncio
async def test_search_by_tag_reports_error_on_real_sqlite_failure_no_json_fallback(server, caplog):
    """search_by_tag (line ~1109) has no JSON mirror (tags are SQLite-only,
    PR #114): on a real SQLite failure it must log a warning and return
    the documented [{"error": ...}] shape rather than raise or return an
    empty/misleading result."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    added = await server.add_conversation(
        content="Tagged conversation content", title="Tagged", tags=["urgent"]
    )
    assert added["status"] == "success"
    conv_id = Path(added["file_path"]).stem
    _corrupt_topics_json(server, conv_id)

    with caplog.at_level(logging.WARNING):
        results = await server.search_by_tag("urgent", limit=5)

    assert any("SQLite tag search failed" in r.message for r in caplog.records)
    assert results == [{"error": results[0]["error"]}]
    assert "Tag search failed" in results[0]["error"]


@pytest.mark.asyncio
async def test_search_by_session_id_reports_error_on_real_sqlite_failure(server, caplog):
    """search_by_session_id (line ~1120) has no JSON mirror: on a real
    SQLite failure it must log a warning and return the documented
    [{"error": ...}] shape rather than raise."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    added = await server.add_conversation(
        content="Session-scoped content", title="Session", session_id="sess-42"
    )
    assert added["status"] == "success"
    conv_id = Path(added["file_path"]).stem
    _corrupt_topics_json(server, conv_id)

    with caplog.at_level(logging.WARNING):
        results = await server.search_by_session_id("sess-42", limit=5)

    assert any("SQLite session search failed" in r.message for r in caplog.records)
    assert results == [{"error": results[0]["error"]}]
    assert "Session search failed" in results[0]["error"]


@pytest.mark.asyncio
async def test_search_by_conversation_type_reports_error_on_real_sqlite_failure(server, caplog):
    """search_by_conversation_type (line ~1133) has no JSON mirror: on a
    real SQLite failure it must log a warning and return the documented
    [{"error": ...}] shape rather than raise."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    added = await server.add_conversation(
        content="Debugging session content",
        title="Debug",
        conversation_type="debugging",
    )
    assert added["status"] == "success"
    conv_id = Path(added["file_path"]).stem
    _corrupt_topics_json(server, conv_id)

    with caplog.at_level(logging.WARNING):
        results = await server.search_by_conversation_type("debugging", limit=5)

    assert any("SQLite conversation-type search failed" in r.message for r in caplog.records)
    assert results == [{"error": results[0]["error"]}]
    assert "Conversation-type search failed" in results[0]["error"]
