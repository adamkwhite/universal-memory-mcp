"""Identity-based consistency checking across the conversation stores.

A conversation lives in three places — its JSON file, an ``index.json`` entry,
and a SQLite row backing the FTS5 index. The checks that existed before this
compared totals, and equal totals over non-equal sets is how the FTS5 desync
(#190) and the index-sync drift (#193) both stayed invisible.
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conversation_memory import ConversationMemoryServer  # noqa: E402


@pytest.fixture
def server():
    temp_dir = tempfile.mkdtemp(prefix="claude_memory_consistency_")
    yield ConversationMemoryServer(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


async def _add(server, title, content="content about python and testing"):
    result = await server.add_conversation(content, title, "2026-01-15T10:00:00")
    assert result["status"] == "success", result
    return result


@pytest.mark.asyncio
async def test_clean_store_reports_consistent(server):
    await _add(server, "First")
    await _add(server, "Second")

    report = server.check_consistency()

    assert report["consistent"] is True
    assert report["json_files"] == 2
    assert report["db_rows"] == 2
    assert report["orphan_files"] == 0
    assert report["dangling_rows"] == 0
    assert "samples" not in report


@pytest.mark.asyncio
async def test_orphan_file_is_detected(server):
    """A JSON file no index row references — the real-world case (31 of them)."""
    await _add(server, "Indexed")

    orphan = server.conversations_path / "2026" / "01-january" / "conv_20260115_000000_9999.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({"id": "conv_20260115_000000_9999", "title": "Orphan"}))

    report = server.check_consistency()

    assert report["consistent"] is False
    assert report["orphan_files"] == 1
    assert report["dangling_rows"] == 0
    assert "conv_20260115_000000_9999.json" in report["samples"]["orphan_files"][0]


@pytest.mark.asyncio
async def test_dangling_row_is_detected(server):
    """An indexed row whose file was removed underneath it."""
    await _add(server, "Doomed")

    next(server.conversations_path.rglob("conv_*.json")).unlink()

    report = server.check_consistency()

    assert report["consistent"] is False
    assert report["dangling_rows"] == 1
    assert report["json_files"] == 0


@pytest.mark.asyncio
async def test_equal_counts_with_disjoint_sets_is_not_consistent(server):
    """The case every count-based check reports as healthy.

    One orphan file and one dangling row net to identical totals — 1 file,
    1 row — while sharing no members at all.
    """
    await _add(server, "Doomed")
    next(server.conversations_path.rglob("conv_*.json")).unlink()

    orphan = server.conversations_path / "2026" / "01-january" / "conv_20260115_000000_7777.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({"id": "conv_20260115_000000_7777", "title": "Orphan"}))

    report = server.check_consistency()

    assert report["json_files"] == report["db_rows"], "precondition: counts must match"
    assert report["consistent"] is False, "equal counts hid disjoint sets"
    assert report["orphan_files"] == 1
    assert report["dangling_rows"] == 1


@pytest.mark.asyncio
async def test_check_is_read_only(server):
    """Detection must never mutate. Repair is deliberately not wired in here."""
    await _add(server, "Keeper")

    orphan = server.conversations_path / "2026" / "01-january" / "conv_20260115_000000_5555.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({"id": "conv_20260115_000000_5555", "title": "Orphan"}))

    before_files = sorted(p.name for p in server.conversations_path.rglob("conv_*.json"))
    before_index = server.index_file.read_text()
    before_rows = server.search_db.get_indexed_file_paths()

    server.check_consistency()
    server.check_consistency()

    assert sorted(p.name for p in server.conversations_path.rglob("conv_*.json")) == before_files
    assert server.index_file.read_text() == before_index
    assert server.search_db.get_indexed_file_paths() == before_rows


@pytest.mark.asyncio
async def test_samples_are_capped(server):
    """Evidence, not a full dump — an MCP response shouldn't carry the store."""
    for i in range(server.CONSISTENCY_SAMPLE_LIMIT + 3):
        orphan = server.conversations_path / "2026" / "01-january" / f"conv_2026011500000{i}_1.json"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text(json.dumps({"id": f"conv_2026011500000{i}_1", "title": f"Orphan {i}"}))

    report = server.check_consistency()

    assert report["orphan_files"] == server.CONSISTENCY_SAMPLE_LIMIT + 3
    assert len(report["samples"]["orphan_files"]) == server.CONSISTENCY_SAMPLE_LIMIT


@pytest.mark.asyncio
async def test_get_search_stats_carries_the_report(server):
    await _add(server, "First")

    stats = await server.get_search_stats()

    assert stats["consistency"]["consistent"] is True
    assert "consistency_error" not in stats


@pytest.mark.asyncio
async def test_index_json_drift_is_reported_separately(server):
    """index.json is its own store and drifts independently of SQLite."""
    await _add(server, "First")

    server.index_file.write_text(json.dumps({"conversations": [], "last_updated": "2026-01-01"}))

    report = server.check_consistency()

    assert report["index_missing"] == 1
    assert report["orphan_files"] == 0, "SQLite is still in sync; only index.json drifted"
    assert report["consistent"] is False
