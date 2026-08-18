#!/usr/bin/env python3
"""Tests for add_conversation/update_conversation rollback-on-partial-failure
behavior (todos.md 2.4.3).

Both methods call SearchDatabase.add_conversation(), which catches
sqlite3.Error internally and returns False rather than raising. Both used
to ignore that return value: add_conversation left an orphaned file +
index entries behind while still reporting "success"; update_conversation
left the file overwritten with new content (with no way back) while doing
the same. These tests force a *real* SQLite failure (not a mock) and
assert nothing is left inconsistent.
"""

import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.conversation_memory import ConversationMemoryServer  # noqa: E402


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp(prefix="claude_memory_rollback_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def server(temp_storage):
    return ConversationMemoryServer(temp_storage)


def _all_conversation_files(server):
    return list(server.conversations_path.rglob("conv_*.json"))


def _index_conversations(server):
    with open(server.index_file, encoding="utf-8") as f:
        return json.load(f).get("conversations", [])


def _topics_index(server):
    with open(server.topics_file, encoding="utf-8") as f:
        return json.load(f).get("topics", {})


@pytest.mark.asyncio
async def test_add_conversation_succeeds_normally(server):
    """Baseline / non-regression: a healthy SQLite index still works."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    result = await server.add_conversation(
        content="Notes about python and docker", title="Baseline"
    )
    assert result["status"] == "success"
    assert len(_all_conversation_files(server)) == 1
    assert len(_index_conversations(server)) == 1


@pytest.mark.asyncio
async def test_add_conversation_rolls_back_on_real_sqlite_failure(server):
    """Force a genuine SQLite failure (not a mock): drop the conversations
    table so the next INSERT raises sqlite3.OperationalError, which is
    caught inside SearchDatabase.add_conversation() and surfaced as a
    False return. add_conversation must then undo the file + index writes
    rather than reporting success with an orphaned file on disk.
    """
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    with closing(sqlite3.connect(server.search_db.db_path)) as conn, conn:
        conn.execute("DROP TABLE conversations")
        conn.commit()

    result = await server.add_conversation(
        content="Notes about python and docker that should not survive",
        title="Should Roll Back",
    )

    assert result["status"] == "error"
    assert "rolled back" in result["message"]

    # No orphaned JSON file anywhere under conversations_path.
    assert _all_conversation_files(server) == []

    # index.json must not reference the failed conversation.
    assert _index_conversations(server) == []

    # topics.json ("python"/"docker" were extracted from the content) must
    # not reference the failed conversation under any topic.
    topics = _topics_index(server)
    all_conv_ids = {
        e.get("conversation_id")
        for entries in topics.values()
        for e in entries
        if isinstance(e, dict)
    }
    assert not any(cid and cid.startswith("conv_") for cid in all_conv_ids)


@pytest.mark.asyncio
async def test_add_conversation_rollback_leaves_other_conversations_intact(server):
    """Rollback must only remove the failed conversation's own entries,
    not unrelated conversations already in the index."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    good = await server.add_conversation(
        content="Existing conversation about kubernetes", title="Existing"
    )
    assert good["status"] == "success"
    good_id = Path(good["file_path"]).stem

    with closing(sqlite3.connect(server.search_db.db_path)) as conn, conn:
        conn.execute("DROP TABLE conversations")
        conn.commit()

    bad = await server.add_conversation(content="This one should roll back", title="Bad")
    assert bad["status"] == "error"

    # The earlier, healthy conversation is untouched.
    remaining_files = _all_conversation_files(server)
    assert len(remaining_files) == 1
    assert remaining_files[0].stem == good_id

    index_ids = {c["id"] for c in _index_conversations(server)}
    assert index_ids == {good_id}


@pytest.mark.asyncio
async def test_rollback_helper_is_best_effort_on_missing_file(server):
    """_rollback_add_conversation must not raise if the file is already
    gone (e.g. removed by something else before rollback runs)."""
    missing_path = server.conversations_path / "conv_20260101_000000_ffffffff.json"
    # Should not raise even though the file was never created.
    server._rollback_add_conversation(missing_path, "conv_20260101_000000_ffffffff", ["python"])

    topics = _topics_index(server)
    assert all(
        e.get("conversation_id") != "conv_20260101_000000_ffffffff"
        for e in topics.get("python", [])
    )


@pytest.mark.asyncio
async def test_update_conversation_rolls_back_on_real_sqlite_failure(server):
    """update_conversation had the identical ignored-return-value bug.
    Unlike add_conversation, there's no new file to unlink -- the record
    already existed -- so "rollback" here means restoring the file's
    prior content rather than deleting it. Force a genuine SQLite failure
    (drop the table) and assert the file, index.json, and topics.json all
    still reflect the *pre-update* state.
    """
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    created = await server.add_conversation(
        content="Original notes about python", title="Original Title"
    )
    assert created["status"] == "success"
    conv_id = Path(created["file_path"]).stem
    file_path = Path(created["file_path"])

    original_raw = file_path.read_text(encoding="utf-8")
    original_index = _index_conversations(server)
    original_topics = _topics_index(server)

    with closing(sqlite3.connect(server.search_db.db_path)) as conn, conn:
        conn.execute("DROP TABLE conversations")
        conn.commit()

    result = await server.update_conversation(
        conv_id, content="New content about kubernetes and docker"
    )

    assert result["status"] == "error"
    assert "restored" in result["message"]

    # File content reverted to exactly what it was before the update.
    assert file_path.read_text(encoding="utf-8") == original_raw
    # index.json/topics.json were never touched (SQLite failure short-
    # circuits before either is called), so they're still the originals.
    assert _index_conversations(server) == original_index
    assert _topics_index(server) == original_topics


@pytest.mark.asyncio
async def test_update_conversation_succeeds_normally(server):
    """Baseline / non-regression: a healthy SQLite index still works."""
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")

    created = await server.add_conversation(
        content="Original notes about python", title="Original Title"
    )
    conv_id = Path(created["file_path"]).stem

    result = await server.update_conversation(conv_id, title="Renamed")
    assert result["status"] == "success"
    assert _load_conversation(server, created["file_path"])["title"] == "Renamed"


def _load_conversation(server, file_path):
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)
