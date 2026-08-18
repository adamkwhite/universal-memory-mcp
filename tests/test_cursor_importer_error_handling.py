#!/usr/bin/env python3
"""Tests for CursorImporter's two ``except Exception`` boundaries in
import_file: the per-session handler (parse/save failures) and the
top-level handler (anything before that). Flagged as untested new code in
PR #175. Both are resilience boundaries for bulk_import_enhanced.py
processing arbitrary, possibly hand-edited Cursor session exports -- they
must report failure via ImportResult rather than crash the batch run.

Each test forces a genuine failure rather than mocking the exception:

- per-session handler: a syntactically valid Cursor session (passes the
  presence-based ``_validate_cursor_format`` check) whose "workspace"
  field is an int instead of a string, so ``Path(workspace)`` in
  parse_conversation raises a real TypeError.
- top-level handler: a .json file containing bytes that are not valid
  UTF-8, distinct from the dedicated json.JSONDecodeError branch.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.importers.cursor_importer import CursorImporter  # noqa: E402


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="cursor_importer_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def importer(temp_dir):
    return CursorImporter(Path(temp_dir) / "storage")


def test_import_file_reports_failure_on_real_type_error_during_parse(importer, temp_dir):
    """The per-session except: a session that passes format validation but
    has a non-string "workspace" makes Path(workspace) raise a real
    TypeError inside parse_conversation -- must be reported via
    ImportResult(success=False), not propagate."""
    session_file = Path(temp_dir) / "session.json"
    session_file.write_text(
        '{"session_id": "s1", "workspace": 12345, "interactions": []}', encoding="utf-8"
    )

    result = importer.import_file(session_file)

    assert result.success is False
    assert result.conversations_failed == 1
    assert result.conversations_imported == 0
    assert any("Failed to process Cursor session" in e for e in result.errors)


def test_import_file_reports_failure_on_real_undecodable_bytes(importer, temp_dir):
    """The top-level except (distinct from the dedicated JSONDecodeError
    branch): a .json file containing bytes that are not valid UTF-8 makes
    the file read itself raise UnicodeDecodeError -- must be reported via
    ImportResult(success=False), not propagate."""
    session_file = Path(temp_dir) / "session.json"
    session_file.write_bytes(b"\xff\xfe\x00 not utf8 \x80\x81")

    result = importer.import_file(session_file)

    assert result.success is False
    assert result.conversations_failed == 1
    assert any("Import failed" in e for e in result.errors)
