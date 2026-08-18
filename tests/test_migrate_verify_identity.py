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

from universal_memory_mcp.conversation_memory import ConversationMemoryServer  # noqa: E402
from universal_memory_mcp.migrate_to_sqlite import (  # noqa: E402
    VERIFY_SAMPLE_LIMIT,
    ConversationMigrator,
)


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
    path.write_text(
        json.dumps({"id": f"conv_2026011500000{suffix}_1", "title": "Stray"}), encoding="utf-8"
    )
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


class TestCliGate:
    """main()'s exit code is the actual product of this change.

    The old gate was ``counts_match and search_test_passed``, so a store with
    equal totals and zero overlap printed "Migration verified successfully!"
    and exited 0. ``--verify-only`` returns before the gate, so these drive
    the full path and stub verify_migration to place the store in an exact
    state — the gate is the unit under test, not the scan.
    """

    @staticmethod
    def _run(monkeypatch, storage, verification):
        from universal_memory_mcp import migrate_to_sqlite

        monkeypatch.setattr(
            sys,
            "argv",
            ["migrate_to_sqlite.py", "--storage-path", str(storage), "--use-data-dir"],
        )
        monkeypatch.setattr(
            migrate_to_sqlite.ConversationMigrator,
            "migrate_all_conversations",
            lambda _self: {"migrated": 0},
        )
        monkeypatch.setattr(
            migrate_to_sqlite.ConversationMigrator,
            "verify_migration",
            lambda _self: verification,
        )
        return migrate_to_sqlite.main()

    def test_equal_counts_over_disjoint_sets_now_exits_nonzero(self, storage, monkeypatch, capsys):
        """The regression case: the old gate passed this exact dict."""
        verification = {
            "counts_match": True,  # what the old gate consulted
            "contents_match": False,  # what it should have consulted
            "missing_from_index": 1,
            "missing_from_disk": 1,
            "search_test_passed": True,
        }

        with pytest.raises(SystemExit) as exit_info:
            self._run(monkeypatch, storage, verification)

        assert exit_info.value.code == 1
        out = capsys.readouterr().out
        assert "verification failed" in out.lower()
        assert "1 file(s) not in the index" in out
        assert "1 indexed row(s) with no file" in out

    def test_matching_contents_exits_clean(self, storage, monkeypatch, capsys):
        verification = {
            "counts_match": True,
            "contents_match": True,
            "missing_from_index": 0,
            "missing_from_disk": 0,
            "search_test_passed": True,
        }

        self._run(monkeypatch, storage, verification)

        assert "verified successfully" in capsys.readouterr().out

    def test_broken_search_still_fails_even_when_contents_match(self, storage, monkeypatch, capsys):
        """contents_match replaced counts_match; it did not replace the
        search smoke test, which is the check that would have caught the
        FTS5 desync in #190."""
        verification = {
            "counts_match": True,
            "contents_match": True,
            "missing_from_index": 0,
            "missing_from_disk": 0,
            "search_test_passed": False,
        }

        with pytest.raises(SystemExit) as exit_info:
            self._run(monkeypatch, storage, verification)

        assert exit_info.value.code == 1
