#!/usr/bin/env python3
"""verify_migration must compare stores by identity, not by total.

It previously reported ``counts_match`` from ``sqlite_count == json_count``,
and ``main()`` printed "Migration verified successfully!" on that basis —
then exited 0. A store with one unmigrated file and one stale row satisfies
that check while sharing no members, so a genuinely broken migration was
reported as verified. A live store was found in exactly that shape (31 files
no index row referenced).
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from conversation_memory import ConversationMemoryServer  # noqa: E402
from migrate_to_sqlite import VERIFY_SAMPLE_LIMIT, ConversationMigrator  # noqa: E402


@pytest.fixture
def storage():
    d = tempfile.mkdtemp(prefix="migrate_verify_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def server(storage):
    return ConversationMemoryServer(storage)


def _migrator(storage):
    return ConversationMigrator(storage, use_data_dir=True)


def _stray_file(server, suffix):
    """A conversation file on disk that no index row references."""
    path = server.conversations_path / "2026" / "01-january" / f"conv_2026011500000{suffix}_1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": f"conv_2026011500000{suffix}_1", "title": "Stray"}))
    return path


async def _add(server, title):
    result = await server.add_conversation("content about python", title, "2026-01-15T10:00:00")
    assert result["status"] == "success", result


@pytest.mark.asyncio
async def test_clean_store_verifies(server, storage):
    await _add(server, "First")
    await _add(server, "Second")

    verification = _migrator(storage).verify_migration()

    assert verification["contents_match"] is True
    assert verification["counts_match"] is True
    assert verification["missing_from_index"] == 0
    assert verification["missing_from_disk"] == 0


@pytest.mark.asyncio
async def test_equal_counts_over_disjoint_sets_fails_verification(server, storage):
    """The exact state the old count comparison passed.

    One indexed conversation whose file is deleted, plus one file that was
    never indexed: totals match at 1 and 1, membership overlaps at zero.
    """
    await _add(server, "Doomed")
    next(server.conversations_path.rglob("conv_*.json")).unlink()
    _stray_file(server, "7")

    verification = _migrator(storage).verify_migration()

    assert verification["counts_match"] is True, "precondition: the old check would have passed"
    assert verification["contents_match"] is False, "identity comparison must catch it"
    assert verification["missing_from_index"] == 1
    assert verification["missing_from_disk"] == 1


@pytest.mark.asyncio
async def test_unmigrated_file_is_reported_with_evidence(server, storage):
    await _add(server, "Indexed")
    stray = _stray_file(server, "9")

    verification = _migrator(storage).verify_migration()

    assert verification["contents_match"] is False
    assert verification["missing_from_index"] == 1
    assert stray.name in verification["samples"]["missing_from_index"][0]


@pytest.mark.asyncio
async def test_indexed_row_without_a_file_is_reported(server, storage):
    await _add(server, "Doomed")
    next(server.conversations_path.rglob("conv_*.json")).unlink()

    verification = _migrator(storage).verify_migration()

    assert verification["contents_match"] is False
    assert verification["missing_from_disk"] == 1
    assert verification["json_count"] == 0


@pytest.mark.asyncio
async def test_samples_are_capped(server, storage):
    for i in range(VERIFY_SAMPLE_LIMIT + 2):
        _stray_file(server, i)

    verification = _migrator(storage).verify_migration()

    assert verification["missing_from_index"] == VERIFY_SAMPLE_LIMIT + 2
    assert len(verification["samples"]["missing_from_index"]) == VERIFY_SAMPLE_LIMIT


@pytest.mark.asyncio
async def test_index_and_topics_files_are_not_counted_as_conversations(server, storage):
    """index.json / topics.json live alongside conversations and must not
    register as unmigrated files."""
    await _add(server, "First")

    verification = _migrator(storage).verify_migration()

    assert verification["json_count"] == 1
    assert verification["contents_match"] is True
