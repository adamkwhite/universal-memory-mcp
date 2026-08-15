"""SearchDatabase must not leave SQLite file handles open.

``with sqlite3.connect(...) as conn`` manages the *transaction*, not the
connection: it commits or rolls back and leaves the handle open until the
garbage collector happens to reclaim it. Every call site in
``search_database.py`` used that form, so each operation leaked a handle.

On Linux this is invisible -- an open file can still be unlinked -- which is
why it survived. On Windows the open handle makes the database file
undeletable, which is what produced the teardown errors when the suite first
ran on ``windows-latest``.

These tests assert the property directly rather than through a platform
symptom, so they fail on Linux too if the fix regresses.
"""

import gc
import sqlite3

import psutil
import pytest

from search_database import SearchDatabase


def _conversation(conv_id: str) -> dict:
    return {
        "id": conv_id,
        "title": f"Conversation {conv_id}",
        "content": "hello world",
        "date": "2026-08-15T00:00:00",
        "created_at": "2026-08-15T00:00:00",
        "topics": ["testing"],
        "tags": [],
    }


@pytest.fixture
def db(tmp_path):
    return SearchDatabase(str(tmp_path / "search.db"))


def _open_handles(db: SearchDatabase) -> int:
    """Count this process's open handles on the database file."""
    target = str(db.db_path)
    return sum(1 for f in psutil.Process().open_files() if f.path == target)


def test_operations_leave_no_open_handles(db):
    # gc is disabled for the duration so a leak cannot be masked by a
    # collection happening to run mid-test. Before the fix this reached 11.
    gc.disable()
    try:
        assert _open_handles(db) == 0, "constructor left a handle open"

        for i in range(5):
            db.add_conversation(_conversation(f"c{i}"), f"{i}.json")
        assert _open_handles(db) == 0, "add_conversation leaked a handle"

        for _ in range(5):
            db.search_conversations("hello")
        assert _open_handles(db) == 0, "search_conversations leaked a handle"

        db.get_conversation_stats()
        assert _open_handles(db) == 0, "get_conversation_stats leaked a handle"
    finally:
        gc.enable()


def test_connection_closes_even_when_the_body_raises(db):
    def _fail_inside_the_connection():
        with db._connect() as conn:
            conn.execute("SELECT * FROM a_table_that_does_not_exist")

    with pytest.raises(sqlite3.OperationalError):
        _fail_inside_the_connection()

    assert _open_handles(db) == 0, "handle survived an exception in the body"


def test_transaction_still_rolls_back_on_error(db):
    """The close must not cost us the existing transaction semantics."""
    db.add_conversation(_conversation("keep"), "keep.json")

    def _delete_then_fail():
        with db._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = 'keep'")
            conn.execute("SELECT * FROM a_table_that_does_not_exist")

    with pytest.raises(sqlite3.OperationalError):
        _delete_then_fail()

    with db._connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM conversations WHERE id = 'keep'").fetchone()
    assert row[0] == 1, "rollback semantics of `with conn` were lost"
