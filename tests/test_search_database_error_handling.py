#!/usr/bin/env python3
"""Tests for SearchDatabase's ``except sqlite3.Error`` handlers.

Every method in SearchDatabase wraps its SQL in a broad
``except sqlite3.Error`` that logs and returns a documented fallback
(``[]``, ``0``, ``{"error": ...}``) instead of letting a corrupt/locked
database crash the caller -- or, for ``_init_database``/``rebuild_fts_index``,
re-raises after logging so the caller can react. These handlers were flagged
as untested new code in PR #175 (the noqa-comment PR). Each test here forces
a *real* sqlite3.Error (dropped table, directory-as-db-file) rather than
mocking the exception into existence, and asserts the documented fallback
value -- not merely "it didn't raise".
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

from universal_memory_mcp.search_database import SearchDatabase  # noqa: E402

SAMPLE_CONVERSATION = {
    "id": "conv_1",
    "title": "Python asyncio notes",
    "content": "Discussion about python asyncio and docker",
    "date": "2025-01-01T00:00:00",
    "created_at": "2025-01-01T00:00:00",
    "topics": ["python", "asyncio"],
    "tags": ["work"],
}


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="search_db_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def db(temp_dir):
    sdb = SearchDatabase(str(Path(temp_dir) / "search.db"))
    assert sdb.add_conversation(dict(SAMPLE_CONVERSATION), "path/conv_1.json")
    return sdb


def _drop(db, table):
    with closing(sqlite3.connect(db.db_path)) as conn, conn:
        conn.execute(f"DROP TABLE {table}")
        conn.commit()


def test_init_database_raises_and_logs_on_real_sqlite_error(temp_dir, caplog):
    """_init_database's except (line ~151) must log and *re-raise* rather
    than silently swallow a real init failure. Force a genuine
    sqlite3.OperationalError by pointing db_path at a pre-existing
    directory -- sqlite3.connect() cannot open a directory as a database
    file. No mocking: this is what happens if deployment creates the
    parent path as a directory by mistake."""
    dir_as_db = Path(temp_dir) / "search.db"
    dir_as_db.mkdir()

    with caplog.at_level(logging.ERROR), pytest.raises(sqlite3.Error):
        SearchDatabase(str(dir_as_db))

    assert any("Database initialization failed" in r.message for r in caplog.records)


def test_search_conversations_falls_back_on_real_sqlite_error(db, caplog):
    """search_conversations (line ~296) must log and return the documented
    ``[{"error": ...}]`` shape, not raise, when the FTS table backing the
    query is gone."""
    _drop(db, "conversations_fts")

    with caplog.at_level(logging.ERROR):
        result = db.search_conversations("python", limit=5)

    assert result == [{"error": result[0]["error"]}]
    assert "Search failed" in result[0]["error"]
    assert any("Search failed" in r.message for r in caplog.records)


def test_search_by_topic_falls_back_on_real_sqlite_error(db, caplog):
    """search_by_topic (line ~331) must log and return ``[]`` (its
    documented fallback) when the topics join table is gone, not raise."""
    _drop(db, "conversation_topics")

    with caplog.at_level(logging.ERROR):
        result = db.search_by_topic("python", limit=5)

    assert result == []
    assert any("Topic search failed" in r.message for r in caplog.records)


def test_search_by_tag_falls_back_on_real_sqlite_error(db, caplog):
    """search_by_tag (line ~356) must log and return ``[]`` when the tags
    join table is gone, not raise."""
    _drop(db, "conversation_tags")

    with caplog.at_level(logging.ERROR):
        result = db.search_by_tag("work", limit=5)

    assert result == []
    assert any("Tag search failed" in r.message for r in caplog.records)


def test_search_by_session_id_falls_back_on_real_sqlite_error(db, caplog):
    """search_by_session_id (line ~380) must log and return ``[]`` when the
    conversations table itself is gone, not raise."""
    _drop(db, "conversations")

    with caplog.at_level(logging.ERROR):
        result = db.search_by_session_id("sess-1", limit=5)

    assert result == []
    assert any("Session search failed" in r.message for r in caplog.records)


def test_search_by_conversation_type_falls_back_on_real_sqlite_error(db, caplog):
    """search_by_conversation_type (line ~406) must log and return ``[]``
    when the conversations table itself is gone, not raise."""
    _drop(db, "conversations")

    with caplog.at_level(logging.ERROR):
        result = db.search_by_conversation_type("chat", limit=5)

    assert result == []
    assert any("Conversation-type search failed" in r.message for r in caplog.records)


def test_get_conversation_stats_falls_back_on_real_sqlite_error(db, caplog):
    """get_conversation_stats (line ~477) must log and return
    ``{"error": ...}`` (not the normal stats dict) when the conversations
    table is gone, not raise -- this backs the ``get_search_stats`` MCP
    diagnostics tool."""
    _drop(db, "conversations")

    with caplog.at_level(logging.ERROR):
        result = db.get_conversation_stats()

    assert "error" in result
    assert "total_conversations" not in result
    assert any("Stats query failed" in r.message for r in caplog.records)


def test_rebuild_fts_index_raises_and_logs_on_real_sqlite_error(db, caplog):
    """rebuild_fts_index (line ~509) must log *and re-raise* -- unlike the
    search methods, a failed rebuild cannot be silently swallowed because
    the caller (migrate_to_sqlite.py) depends on knowing it failed."""
    _drop(db, "conversations_fts")

    with caplog.at_level(logging.ERROR), pytest.raises(sqlite3.Error):
        db.rebuild_fts_index()

    assert any("FTS index rebuild failed" in r.message for r in caplog.records)


def test_get_conversation_count_falls_back_on_real_sqlite_error(db, caplog):
    """get_conversation_count (line ~520) must log and return ``0`` (its
    documented fallback), not raise, when the conversations table is
    gone."""
    _drop(db, "conversations")

    with caplog.at_level(logging.ERROR):
        result = db.get_conversation_count()

    assert result == 0
    assert any("Count query failed" in r.message for r in caplog.records)
