#!/usr/bin/env python3
"""Tests for FormatDetector's ``except Exception`` boundaries.

detect_format() runs on arbitrary user-supplied files during bulk import --
it must classify anything as UNKNOWN/0.0 rather than crash the import CLI.
Flagged as untested new code in PR #175. Each test forces a genuinely
malformed input rather than mocking the exception:

- detect_format's own outer handler: pointed at a directory, so the shared
  ``validate_import_file_path`` choke point raises MetadataValidationError
  (it exists but is not a regular file).
- _detect_json_format's generic handler (distinct from its dedicated
  JSONDecodeError branch): a syntactically-valid JSON file whose
  ``role`` field is not a string, so ``_has_role_based_messages``'s
  ``msg["role"].lower()`` raises a real AttributeError.
- _detect_text_format's handler: a .txt file containing bytes that are not
  valid UTF-8, so the file read itself raises UnicodeDecodeError.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from format_detector import FormatDetector, PlatformType  # noqa: E402


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="format_detector_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def detector():
    return FormatDetector()


def test_detect_format_reports_unknown_on_real_validation_error(detector, temp_dir):
    """detect_format's outer except: a directory passed where a file is
    expected makes validate_import_file_path raise a real
    MetadataValidationError (not a mock) -- must be classified as
    UNKNOWN/0.0 with a message, not propagate."""
    directory_path = Path(temp_dir)  # exists, but is not a regular file

    result = detector.detect_format(directory_path)

    assert result["platform"] == PlatformType.UNKNOWN.value
    assert result["confidence"] == 0.0
    assert "not a regular file" in result["message"] or "Detection error" in result["message"]


def test_detect_json_format_reports_unknown_on_real_non_json_decode_error(detector, temp_dir):
    """_detect_json_format's generic except (distinct from its dedicated
    json.JSONDecodeError branch): syntactically valid JSON whose "role"
    field is a non-string int makes _has_role_based_messages's
    ``msg["role"].lower()`` raise a real AttributeError -- must be
    classified as UNKNOWN/0.0, not propagate."""
    export_file = Path(temp_dir) / "export.json"
    export_file.write_text(
        json.dumps({"conversations": [{"messages": [{"role": 1}, {"role": 2}]}]}), encoding="utf-8"
    )

    result = detector.detect_format(export_file)

    assert result["platform"] == PlatformType.UNKNOWN.value
    assert result["confidence"] == 0.0
    assert "JSON analysis error" in result["message"]


def test_detect_text_format_reports_unknown_on_real_undecodable_bytes(detector, temp_dir):
    """_detect_text_format's except: a .txt file containing bytes that are
    not valid UTF-8 makes the file read itself raise a real
    UnicodeDecodeError -- must be classified as UNKNOWN/0.0, not
    propagate."""
    notes_file = Path(temp_dir) / "notes.txt"
    notes_file.write_bytes(b"\xff\xfe\x00invalid utf8 \x80\x81")

    result = detector.detect_format(notes_file)

    assert result["platform"] == PlatformType.UNKNOWN.value
    assert result["confidence"] == 0.0
    assert "Text analysis error" in result["message"]
