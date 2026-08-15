#!/usr/bin/env python3
"""Tests for ConversationMigrator's ``except Exception`` boundaries.

migrate_to_sqlite.py's job is to walk a directory of untrusted, possibly
hand-edited JSON files and load them into SQLite without one bad file
aborting the whole run. Each handler here is either a per-item resilience
boundary (skip this item, keep going) or a top-level boundary (report
failure in the returned dict rather than raise). These were flagged as
untested new code in PR #175. Each test forces a *real* failure (malformed
JSON on disk, a missing required key, a corrupted DB column) rather than
mocking the exception, and asserts the documented degradation contract:
the batch keeps going and the specific error surfaces in the stats/result
dict.
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

from conversation_memory import ConversationMemoryServer  # noqa: E402
from migrate_to_sqlite import ConversationMigrator  # noqa: E402


@pytest.fixture
def temp_storage():
    d = tempfile.mkdtemp(prefix="migrate_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _write_conversation_file(conversations_dir: Path, conv_id: str) -> Path:
    year_dir = conversations_dir / "2025" / "01-january"
    year_dir.mkdir(parents=True, exist_ok=True)
    path = year_dir / f"{conv_id}.json"
    path.write_text(
        json.dumps(
            {
                "id": conv_id,
                "title": "Valid conversation",
                "content": "some real content about python",
                "date": "2025-01-01T00:00:00",
                "created_at": "2025-01-01T00:00:00",
                "topics": ["python"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_detect_data_directory_structure_defaults_to_new_layout(temp_storage):
    """_detect_data_directory_structure (line ~59, simplified in PR #175
    from an if/return chain to a single boolean expression) is not an
    exception handler but is new code from the same PR: exercise its
    auto-detect path (use_data_dir=None) directly, rather than the other
    tests' explicit use_data_dir=True, to cover the actual branch."""
    # Neither data/conversations nor conversations exists yet -> must
    # default to the new data/ layout.
    migrator = ConversationMigrator(temp_storage, use_data_dir=None)
    assert migrator.conversations_path == Path(temp_storage) / "data" / "conversations"


def test_migrate_all_conversations_reports_error_on_malformed_index_json(temp_storage):
    """migrate_all_conversations's top-level except (line ~98) must catch a
    genuinely malformed index.json (not a mock) and report the failure in
    the returned stats dict rather than raising out of the MCP tool call."""
    conversations_dir = Path(temp_storage) / "data" / "conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)
    (conversations_dir / "index.json").write_text("{not valid json,,,", encoding="utf-8")

    migrator = ConversationMigrator(temp_storage, use_data_dir=True)
    stats = migrator.migrate_all_conversations()

    assert "error" in stats
    assert stats["successfully_migrated"] == 0


def test_migrate_single_conversation_skips_entry_missing_file_path_and_keeps_batch_going(
    temp_storage,
):
    """_migrate_single_conversation's except (line ~162) must catch a real
    KeyError from an index entry that's missing the required "file_path"
    key -- e.g. a hand-edited or partially-written index.json -- and skip
    just that entry, not abort the whole migration. Verified end-to-end
    through migrate_all_conversations with one good entry alongside the
    malformed one."""
    conversations_dir = Path(temp_storage) / "data" / "conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)
    good_path = _write_conversation_file(conversations_dir, "conv_good")

    index_data = {
        "conversations": [
            {
                "id": "conv_good",
                "file_path": str(good_path.relative_to(Path(temp_storage))),
            },
            {
                # Missing "file_path" entirely -> conv_info["file_path"]
                # raises a real KeyError inside _migrate_single_conversation.
                "id": "conv_malformed",
            },
        ]
    }
    (conversations_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    migrator = ConversationMigrator(temp_storage, use_data_dir=True)
    stats = migrator.migrate_all_conversations()

    assert "error" not in stats
    assert stats["total_found"] == 2
    assert stats["successfully_migrated"] == 1
    assert stats["failed_migrations"] == 1


def test_migrate_json_file_skips_unparseable_file_and_keeps_batch_going(temp_storage):
    """_migrate_json_file's except (line ~195) must catch a real
    json.JSONDecodeError from a genuinely corrupt file on disk (not a
    mock) during the no-index directory scan, and skip just that file."""
    conversations_dir = Path(temp_storage) / "data" / "conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)
    _write_conversation_file(conversations_dir, "conv_good")

    garbage_dir = conversations_dir / "2025" / "01-january"
    (garbage_dir / "corrupt.json").write_text("this is not { valid json at all", encoding="utf-8")

    # No index.json written -> migrate_all_conversations falls through to
    # the directory-scan path (_migrate_without_index -> _migrate_json_file).
    migrator = ConversationMigrator(temp_storage, use_data_dir=True)
    stats = migrator.migrate_all_conversations()

    assert "error" not in stats
    assert stats["total_found"] == 2
    assert stats["successfully_migrated"] == 1
    assert stats["failed_migrations"] == 1


def test_verify_migration_reports_error_on_real_search_failure(temp_storage):
    """verify_migration's top-level except (line ~235) must catch a
    genuine, unmocked failure surfacing from the search layer and report
    it via {"error": ...} rather than raising. Forced by corrupting the
    topics_json column directly (simulating a partially-written/corrupted
    row) so search_conversations's inline json.loads raises a
    JSONDecodeError that SearchDatabase's own except sqlite3.Error does
    not catch."""
    conversations_dir = Path(temp_storage) / "data" / "conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)

    migrator = ConversationMigrator(temp_storage, use_data_dir=True)
    assert migrator.search_db.add_conversation(
        {
            "id": "conv_1",
            "title": "t",
            "content": "python notes",
            "date": "2025-01-01T00:00:00",
            "created_at": "2025-01-01T00:00:00",
            "topics": ["python"],
        },
        "2025/01-january/conv_1.json",
    )

    with closing(sqlite3.connect(migrator.search_db.db_path)) as conn, conn:
        conn.execute("UPDATE conversations SET topics_json = 'not-json' WHERE id = 'conv_1'")
        conn.commit()

    result = migrator.verify_migration()

    assert "error" in result
    assert "sqlite_count" not in result


@pytest.mark.asyncio
async def test_migrate_to_sqlite_import_is_not_dead(tmp_path):
    """ConversationMemoryServer.migrate_to_sqlite() must actually import the migrator.

    Regression: the method used a RELATIVE import (``from .migrate_to_sqlite
    import ConversationMigrator``) inside conversation_memory.py, which is
    always loaded as a top-level module (``__package__`` is ""). So the import
    raised ImportError on every call, the method's own ``except ImportError``
    swallowed it, and the whole migration feature silently returned
    {"error": "Migration module not available"} forever. #156 converted the
    module-level imports to the canonical bare style but missed this one
    because it lives inside a function body.

    This asserts the import path resolves -- i.e. the feature is reachable at
    all. It fails if anyone reintroduces the relative form.
    """
    server = ConversationMemoryServer(str(tmp_path), enable_sqlite=True)

    result = await server.migrate_to_sqlite()

    assert result.get("error") != "Migration module not available", (
        "migrate_to_sqlite() cannot import ConversationMigrator -- the feature "
        "is dead. Check for a relative import inside the method body."
    )
    # An empty store migrates zero conversations, but it must actually report
    # stats rather than an import failure.
    assert "total_found" in result
