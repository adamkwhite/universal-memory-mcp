#!/usr/bin/env python3
"""Tests for ConversationMemoryServer's best-effort rollback/index-repair
handlers: ``_rollback_add_conversation``, ``_remove_index_entry``,
``_rollback_update_conversation``, ``_replace_index_entry``, and
``_resync_topics_index`` (both its read and write ``except`` branches),
plus the legacy ``_analyze_conversations`` per-item handler. All were
flagged as untested new code in PR #175 (the noqa-comment PR that also
upgraded their ``logger.error`` calls to ``logger.exception`` for full
tracebacks).

Each handler is documented as "best-effort: logged, not raised" -- these
run *inside* an already-failing rollback path, so a second failure there
must not crash the caller or corrupt state further. Each test forces a
*real* OSError/ValueError (a directory where a file is expected, a
read-only file, malformed JSON on disk) rather than mocking the exception,
and asserts both the logged record and that the method returns normally
without raising or making things worse.
"""

import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from conversation_memory import ConversationMemoryServer  # noqa: E402


@pytest.fixture
def temp_storage():
    d = tempfile.mkdtemp(prefix="claude_memory_rollback_logging_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def server(temp_storage):
    return ConversationMemoryServer(temp_storage)


def test_rollback_add_conversation_logs_on_real_os_error_removing_file(server, caplog):
    """_rollback_add_conversation (line ~433): file_path.unlink() must log
    and swallow a real OSError rather than raise. Forced by pointing it at
    a directory -- unlink(missing_ok=True) only suppresses
    FileNotFoundError, not IsADirectoryError -- simulating a stray
    directory left behind by something else at that path."""
    stray_dir = server.conversations_path / "conv_20260101_000000_deadbeef.json"
    stray_dir.mkdir()

    with caplog.at_level(logging.ERROR):
        # Must not raise.
        server._rollback_add_conversation(stray_dir, "conv_20260101_000000_deadbeef", [])

    assert stray_dir.exists()  # best-effort: not force-deleted some other way
    assert any("Rollback: failed to remove orphaned file" in r.message for r in caplog.records)


def test_remove_index_entry_logs_on_real_malformed_index(server, caplog):
    """_remove_index_entry (line ~455): must log and swallow a real
    json.JSONDecodeError from a genuinely corrupt index.json rather than
    raise."""
    server.index_file.write_text("{not valid json,,,", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        server._remove_index_entry("conv_x")

    # Best-effort: the corrupt file is left as-is, not silently blown away.
    assert server.index_file.read_text(encoding="utf-8") == "{not valid json,,,"
    assert any("Rollback: failed to remove index entry" in r.message for r in caplog.records)


def test_rollback_update_conversation_logs_on_real_os_error_restoring_content(server, caplog):
    """_rollback_update_conversation (line ~648): the write-back must log
    and swallow a real OSError rather than raise. Forced by pointing it at
    a directory -- open(path, "w") on a directory raises
    IsADirectoryError."""
    stray_dir = server.conversations_path / "conv_20260101_000000_cafebabe.json"
    stray_dir.mkdir()

    with caplog.at_level(logging.ERROR):
        server._rollback_update_conversation(stray_dir, "original content")

    assert any("Rollback: failed to restore prior content" in r.message for r in caplog.records)


def test_replace_index_entry_logs_on_real_malformed_index(server, caplog):
    """_replace_index_entry (line ~687): must log and swallow a real
    json.JSONDecodeError from a genuinely corrupt index.json rather than
    raise."""
    server.index_file.write_text("{not valid json,,,", encoding="utf-8")
    conversation_data = {
        "id": "conv_x",
        "title": "t",
        "date": "2026-01-01T00:00:00",
        "topics": [],
    }
    fake_file = server.conversations_path / "2026" / "01-january" / "conv_x.json"

    with caplog.at_level(logging.ERROR):
        server._replace_index_entry(conversation_data, fake_file)

    assert server.index_file.read_text(encoding="utf-8") == "{not valid json,,,"
    assert any("Error replacing index entry" in r.message for r in caplog.records)


def test_resync_topics_index_logs_on_real_malformed_topics_file(server, caplog):
    """_resync_topics_index's read except (line ~703): must log and return
    early on a real json.JSONDecodeError from a genuinely corrupt
    topics.json, rather than raise or attempt the update."""
    server.topics_file.write_text("{not valid json,,,", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        result = server._resync_topics_index(["python"], ["docker"], "conv_x")

    assert result is None
    # Best-effort: corrupt file left untouched, no write attempted.
    assert server.topics_file.read_text(encoding="utf-8") == "{not valid json,,,"
    assert any("Error loading topics index" in r.message for r in caplog.records)


def test_resync_topics_index_logs_on_real_os_error_writing(server, caplog):
    """_resync_topics_index's write except (line ~742): the read must
    succeed (valid JSON) but the write must fail with a real OSError --
    forced by making topics.json read-only -- and the handler must log
    and swallow it rather than raise."""
    server.topics_file.write_text(json.dumps({"topics": {}}), encoding="utf-8")
    os.chmod(server.topics_file, 0o444)
    try:
        with caplog.at_level(logging.ERROR):
            # Must not raise even though the write below will fail.
            server._resync_topics_index(["python"], ["docker"], "conv_x")

        assert any("Error writing topics index" in r.message for r in caplog.records)
    finally:
        os.chmod(server.topics_file, 0o644)


def test_analyze_conversations_reports_error_on_real_type_error(server):
    """_analyze_conversations (line ~1184, legacy per-item helper): a
    malformed entry (non-string file_path, e.g. from a hand-edited or
    partially-written index) must produce a real TypeError from
    ``Path / int`` that's caught and reported per-item, not crash the
    whole batch."""
    good = {"file_path": "does/not/exist.json", "title": "Fine"}
    malformed = {"file_path": 12345, "title": "Bad"}  # not a str/PathLike

    results = server._analyze_conversations([good, malformed])

    assert len(results) == 2
    assert results[0] == {"error": "Conversation file not found"}
    assert "error" in results[1]
