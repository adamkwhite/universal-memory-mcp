#!/usr/bin/env python3
"""Tests that the FTS5 index stays in sync with the ``conversations`` table.

``conversations_fts`` is an EXTERNAL CONTENT table: it stores only the index
and reads column values back from ``conversations`` by rowid. Rowid alignment
is therefore the whole contract, and breaking it is silent until a MATCH
happens to hit an orphaned entry — at which point SQLite fails the query with
"database disk image is malformed" and *every* content search breaks while
tag/topic lookups keep working, because those never touch FTS.

The live index desynced exactly this way: the triggers were written for a
standalone FTS table (no explicit rowid, plain DELETE/UPDATE against the
virtual table), and ``INSERT OR REPLACE`` re-assigned the rowid while skipping
the AFTER DELETE trigger entirely. One orphan leaked per re-saved conversation.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from search_database import SearchDatabase  # noqa: E402


def _conversation(conv_id: str, title: str, content: str) -> dict:
    return {
        "id": conv_id,
        "title": title,
        "content": content,
        "date": "2026-08-10T18:00:00",
        "created_at": "2026-08-10T18:00:00",
        "topics": ["testing"],
        "tags": ["fts"],
    }


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield SearchDatabase(str(Path(tmp) / "search.db"))


def _counts(db: SearchDatabase) -> tuple[int, int]:
    """Return (row count, indexed-document count)."""
    with sqlite3.connect(db.db_path) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        docs = conn.execute("SELECT COUNT(*) FROM conversations_fts_docsize").fetchone()[0]
    return rows, docs


def test_resave_does_not_orphan_an_index_entry(db):
    """Re-saving the same id must update in place, not leak an FTS document."""
    db.add_conversation(_conversation("a", "First", "hello world"), "/tmp/a.json")
    db.add_conversation(_conversation("a", "Second", "goodbye moon"), "/tmp/a.json")

    assert _counts(db) == (1, 1)


def test_search_survives_a_resave(db):
    """The regression itself: search must not raise after a re-save."""
    db.add_conversation(_conversation("a", "First", "hello world"), "/tmp/a.json")
    db.add_conversation(_conversation("a", "Second", "goodbye moon"), "/tmp/a.json")

    # Superseded content is gone from the index, current content is findable.
    assert db.search_conversations("hello") == []
    assert [r["id"] for r in db.search_conversations("goodbye")] == ["a"]


def test_resave_preserves_rowid(db):
    """Rowid stability is what keeps the external-content read-back valid."""
    db.add_conversation(_conversation("a", "First", "hello world"), "/tmp/a.json")
    with sqlite3.connect(db.db_path) as conn:
        before = conn.execute("SELECT rowid FROM conversations WHERE id='a'").fetchone()[0]

    db.add_conversation(_conversation("a", "Second", "goodbye moon"), "/tmp/a.json")
    with sqlite3.connect(db.db_path) as conn:
        after = conn.execute("SELECT rowid FROM conversations WHERE id='a'").fetchone()[0]

    assert before == after


def test_delete_removes_the_index_entry(db):
    """A row delete must retract its terms, not strand them in the index."""
    db.add_conversation(_conversation("a", "First", "hello world"), "/tmp/a.json")
    db.add_conversation(_conversation("b", "Other", "unrelated text"), "/tmp/b.json")

    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DELETE FROM conversations WHERE id='a'")
        conn.commit()

    assert _counts(db) == (1, 1)
    assert db.search_conversations("hello") == []
    assert [r["id"] for r in db.search_conversations("unrelated")] == ["b"]


def test_init_repairs_a_desynced_index(tmp_path):
    """An already-broken database heals on open instead of needing an operator."""
    db_path = tmp_path / "search.db"
    db = SearchDatabase(str(db_path))
    db.add_conversation(_conversation("a", "First", "hello world"), "/tmp/a.json")

    # Forge the exact damage the old triggers caused: an index entry whose
    # rowid no longer exists in the content table.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations_fts(rowid, id, title, content, topics_text) "
            "VALUES (999, 'ghost', 'Ghost', 'phantom text', '')"
        )
        conn.commit()

    # Older SQLite reports the generic "database disk image is malformed";
    # newer builds name the orphan outright ("fts5: missing row N from content
    # table"). Accept either — the assertion is that the forged desync is
    # detectable as an error, not which wording this SQLite happens to use.
    with (
        sqlite3.connect(db_path) as conn,
        pytest.raises(sqlite3.DatabaseError, match="malformed|missing row"),
    ):
        conn.execute(
            "SELECT id FROM conversations_fts WHERE conversations_fts MATCH 'phantom'"
        ).fetchall()

    SearchDatabase(str(db_path))  # re-open: _repair_fts_desync rebuilds

    assert _counts(SearchDatabase(str(db_path))) == (1, 1)
    assert [r["id"] for r in db.search_conversations("hello")] == ["a"]
