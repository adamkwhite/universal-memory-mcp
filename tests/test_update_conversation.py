#!/usr/bin/env python3
"""Tests for ConversationMemoryServer.update_conversation."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from universal_memory_mcp.conversation_memory import ConversationMemoryServer  # noqa: E402

SAMPLE_CONTENT = "# Test\n\nDiscussion of python MCP server setup with docker."


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp(prefix="claude_memory_update_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def server(temp_storage):
    return ConversationMemoryServer(temp_storage)


async def _seed(server, **kwargs):
    """Create a conversation and return its ID + file path."""
    result = await server.add_conversation(
        content=kwargs.get("content", SAMPLE_CONTENT),
        title=kwargs.get("title", "Original Title"),
        conversation_date=kwargs.get("conversation_date", "2026-05-01T12:00:00"),
        tags=kwargs.get("tags"),
        conversation_type=kwargs.get("conversation_type"),
        session_id=kwargs.get("session_id"),
        user_id=kwargs.get("user_id"),
    )
    assert result["status"] == "success"
    file_path = Path(result["file_path"])
    conv_id = file_path.stem
    return conv_id, file_path


def _load(file_path):
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_update_content_prepends_audit_line(server):
    conv_id, file_path = await _seed(server)
    result = await server.update_conversation(
        conv_id, content="New content about react and javascript"
    )
    assert result["status"] == "success"
    assert "content" in result["changes"]

    data = _load(file_path)
    first_line = data["content"].split("\n", 1)[0]
    assert first_line.startswith("[update ")
    assert first_line.endswith("— content]")
    # Body follows the audit line + blank line
    assert "react" in data["content"]
    # Topics re-extracted from new content
    assert "react" in data["topics"]
    assert "python" not in data["topics"]


@pytest.mark.asyncio
async def test_update_title_only_uses_title_in_audit(server):
    conv_id, file_path = await _seed(server)
    result = await server.update_conversation(conv_id, title="Renamed")
    assert result["status"] == "success"
    assert result["changes"] == ["title"]

    data = _load(file_path)
    assert data["title"] == "Renamed"
    assert data["content"].splitlines()[0].endswith("— title]")


@pytest.mark.asyncio
async def test_set_tags_replaces_existing(server):
    conv_id, file_path = await _seed(server, tags=["old1", "old2"])
    result = await server.update_conversation(conv_id, set_tags=["new1", "new2"])
    assert result["status"] == "success"
    assert _load(file_path)["tags"] == ["new1", "new2"]


@pytest.mark.asyncio
async def test_add_tags_dedups_and_appends(server):
    conv_id, file_path = await _seed(server, tags=["existing"])
    result = await server.update_conversation(conv_id, add_tags=["existing", "neetu"])
    assert result["status"] == "success"
    assert _load(file_path)["tags"] == ["existing", "neetu"]


@pytest.mark.asyncio
async def test_remove_tags_drops_named(server):
    conv_id, file_path = await _seed(server, tags=["a", "b", "c"])
    result = await server.update_conversation(conv_id, remove_tags=["b"])
    assert result["status"] == "success"
    assert _load(file_path)["tags"] == ["a", "c"]


@pytest.mark.asyncio
async def test_set_tags_empty_clears(server):
    conv_id, file_path = await _seed(server, tags=["a", "b"])
    result = await server.update_conversation(conv_id, set_tags=[])
    assert result["status"] == "success"
    assert _load(file_path)["tags"] == []


@pytest.mark.asyncio
async def test_set_tags_conflicts_with_add_tags(server):
    conv_id, _ = await _seed(server)
    result = await server.update_conversation(conv_id, set_tags=["x"], add_tags=["y"])
    assert result["status"] == "error"
    assert "mutually exclusive" in result["message"]


@pytest.mark.asyncio
async def test_malformed_id_returns_error(server):
    result = await server.update_conversation("not-a-real-id", title="x")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower() or "invalid" in result["message"].lower()


@pytest.mark.asyncio
async def test_missing_file_returns_error(server):
    # Well-formed ID but no file on disk
    result = await server.update_conversation("conv_20260501_120000_9999", title="x")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_no_changes_returns_error(server):
    conv_id, _ = await _seed(server)
    result = await server.update_conversation(conv_id)
    assert result["status"] == "error"
    assert "No changes" in result["message"]


@pytest.mark.asyncio
async def test_explicit_change_note_used(server):
    conv_id, file_path = await _seed(server)
    result = await server.update_conversation(
        conv_id, add_tags=["neetu"], change_note="added Neetu per request"
    )
    assert result["status"] == "success"
    first_line = _load(file_path)["content"].splitlines()[0]
    assert "added Neetu per request" in first_line


@pytest.mark.asyncio
async def test_audit_line_chains_on_repeat_updates(server):
    conv_id, file_path = await _seed(server)
    await server.update_conversation(conv_id, title="First rename")
    await server.update_conversation(conv_id, title="Second rename")

    content_lines = _load(file_path)["content"].splitlines()
    audit_lines = [ln for ln in content_lines if ln.startswith("[update ")]
    # Two updates → two audit lines stacked at the top
    assert len(audit_lines) == 2


@pytest.mark.asyncio
async def test_index_entry_replaced_not_duplicated(server):
    conv_id, _ = await _seed(server)
    await server.update_conversation(conv_id, title="Renamed in index")

    with open(server.index_file, encoding="utf-8") as f:
        index = json.load(f)
    matching = [c for c in index["conversations"] if c["id"] == conv_id]
    assert len(matching) == 1
    assert matching[0]["title"] == "Renamed in index"


@pytest.mark.asyncio
async def test_topics_index_drops_obsolete_topics(server):
    conv_id, _ = await _seed(server)
    # Replace content so old topics (python, mcp, docker) are gone
    await server.update_conversation(conv_id, content="Notes on react and javascript only")

    with open(server.topics_file, encoding="utf-8") as f:
        topics_data = json.load(f)
    topics = topics_data.get("topics", {})
    # python should no longer reference this conversation
    python_entries = topics.get("python", [])
    assert all(e.get("conversation_id") != conv_id for e in python_entries)
    # react should now reference it
    react_entries = topics.get("react", [])
    assert any(e.get("conversation_id") == conv_id for e in react_entries)


@pytest.mark.asyncio
async def test_sqlite_search_reflects_updated_content(server):
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")
    conv_id, _ = await _seed(server)
    await server.update_conversation(conv_id, content="Brand new keyword: zebracorn appears here")
    results = await server.search_conversations("zebracorn", limit=5)
    assert any(r.get("id") == conv_id for r in results)


@pytest.mark.asyncio
async def test_sqlite_search_reflects_updated_tags(server):
    if not server.use_sqlite_search:
        pytest.skip("SQLite search unavailable")
    conv_id, _ = await _seed(server, tags=["original"])
    await server.update_conversation(conv_id, add_tags=["neetu"])

    tag_results = await server.search_by_tag("neetu", limit=5)
    assert any(r.get("id") == conv_id for r in tag_results)


@pytest.mark.asyncio
async def test_update_metadata_fields(server):
    """conversation_type / session_id / user_id all flow through."""
    conv_id, file_path = await _seed(server)
    result = await server.update_conversation(
        conv_id,
        conversation_type="document-transcription",
        session_id="sess-123",
        user_id="user-456",
    )
    assert result["status"] == "success"
    assert set(result["changes"]) == {
        "conversation_type",
        "session_id",
        "user_id",
    }
    data = _load(file_path)
    assert data["conversation_type"] == "document-transcription"
    assert data["session_id"] == "sess-123"
    assert data["user_id"] == "user-456"


@pytest.mark.asyncio
async def test_well_formed_id_invalid_date_returns_error(server):
    """ID matches the regex but encodes a non-existent calendar date."""
    result = await server.update_conversation("conv_20269999_120000_0001", title="x")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_updated_at_set(server):
    conv_id, file_path = await _seed(server)
    await server.update_conversation(conv_id, title="x")
    data = _load(file_path)
    assert "updated_at" in data


# ---------------------------------------------------------------------------
# The no-op guard. Extracted to _is_noop_update to bring update_conversation
# under the cognitive-complexity limit; it had no direct coverage before, and
# its second clause is the least obvious rule in the function.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_with_nothing_at_all_is_rejected(server):
    conv_id, _ = await _seed(server)
    result = await server.update_conversation(conv_id)
    assert result["status"] == "error"
    assert result["message"] == "No changes provided"


@pytest.mark.asyncio
async def test_note_only_update_is_allowed_when_auditing(server):
    """A change_note with no field changes is a real update: the audit line it
    writes into content *is* the change. This is the point of change_note."""
    conv_id, file_path = await _seed(server)
    before = _load(file_path)["content"]

    result = await server.update_conversation(conv_id, change_note="reviewed, no edits")

    assert result["status"] == "success"
    assert result["changes"] == []
    assert "note-only" in result["message"]
    after = _load(file_path)["content"]
    assert after != before
    assert "reviewed, no edits" in after
    assert result["audit_line"] in after


@pytest.mark.asyncio
async def test_note_only_update_is_rejected_when_not_auditing(server):
    """Same call with auditing off writes nothing, so it must be rejected
    rather than silently bumping updated_at."""
    conv_id, file_path = await _seed(server)
    before = _load(file_path)

    result = await server.update_conversation(
        conv_id, change_note="reviewed, no edits", record_audit=False
    )

    assert result["status"] == "error"
    assert result["message"] == "No changes provided"
    assert _load(file_path) == before, "a rejected update must not touch the file"


@pytest.mark.asyncio
async def test_real_change_still_applies_with_auditing_off(server):
    """record_audit=False suppresses the audit line, not the update itself."""
    conv_id, file_path = await _seed(server)
    result = await server.update_conversation(conv_id, title="New Title", record_audit=False)

    assert result["status"] == "success"
    assert "audit_line" not in result
    data = _load(file_path)
    assert data["title"] == "New Title"
    assert not data["content"].startswith("[update ")


class TestNoopPredicate:
    """Direct tests for the extracted predicate, so a regression names itself."""

    @pytest.mark.parametrize(
        "changes,note,audit,expected",
        [
            ([], None, True, True),  # nothing at all
            ([], None, False, True),  # nothing, auditing off
            ([], "note", False, True),  # note but nothing records it
            ([], "note", True, False),  # the audit line IS the change
            (["title"], None, True, False),  # a real field change
            (["title"], None, False, False),  # real change, auditing off
        ],
    )
    def test_truth_table(self, changes, note, audit, expected):
        assert ConversationMemoryServer._is_noop_update(changes, note, audit) is expected


class TestConflictingTagOps:
    @pytest.mark.parametrize(
        "set_tags,add_tags,remove_tags,expected",
        [
            (None, ["a"], None, False),
            (None, None, ["a"], False),
            (["a"], None, None, False),
            (["a"], ["b"], None, True),
            (["a"], None, ["b"], True),
            ([], ["b"], None, True),  # set_tags=[] is "clear", not "unset"
            ([], None, None, False),  # clearing alone is fine
            (["a"], [], [], False),  # empty mutations are not a conflict
        ],
    )
    def test_truth_table(self, set_tags, add_tags, remove_tags, expected):
        assert (
            ConversationMemoryServer._conflicting_tag_ops(set_tags, add_tags, remove_tags)
            is expected
        )
