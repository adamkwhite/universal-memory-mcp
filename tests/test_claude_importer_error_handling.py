#!/usr/bin/env python3
"""Tests for ClaudeImporter's top-level ``except Exception`` boundary in
import_file (line ~73), flagged as untested new code in PR #175. Real
(non-mocked) triggers:

- a directory passed where a file is expected, so the shared
  validate_import_file_path choke point raises MetadataValidationError.
- a syntactically valid JSON file whose top-level value is a bare int
  (not an object/array) -- ``_is_claude_memory_format``'s
  ``"id" not in data`` raises a real TypeError for a non-iterable data
  type. Note this is *not* wrapped by ``_import_json_format``'s own
  try/except (which only catches json.JSONDecodeError), so it propagates
  up to import_file's outer boundary rather than one of the inner
  format-branch handlers.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from importers.claude_importer import ClaudeImporter  # noqa: E402


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="claude_importer_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def importer(temp_dir):
    return ClaudeImporter(Path(temp_dir) / "storage")


def test_import_file_reports_failure_on_real_validation_error(importer, temp_dir):
    """A directory passed as file_path makes validate_import_file_path
    raise a real MetadataValidationError -- must be reported via
    ImportResult(success=False), not propagate."""
    result = importer.import_file(Path(temp_dir))

    assert result.success is False
    assert result.conversations_failed == 1
    assert any("not a regular file" in e for e in result.errors)


def test_import_file_reports_failure_on_real_non_dict_json_content(importer, temp_dir):
    """A JSON file whose top-level value is a bare scalar (valid JSON, but
    not an object/array) makes the format-detection helpers raise a real
    TypeError -- must be reported via ImportResult(success=False), not
    propagate."""
    scalar_file = Path(temp_dir) / "weird.json"
    scalar_file.write_text("42", encoding="utf-8")

    result = importer.import_file(scalar_file)

    assert result.success is False
    assert result.conversations_failed == 1
    assert result.errors  # some failure message was recorded, not silently dropped
