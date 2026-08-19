#!/usr/bin/env python3
"""Tests for GenericImporter's per-item ``except Exception`` resilience
boundaries, which skip an unparseable item and keep processing the rest of
the batch rather than failing the whole import.

Real (non-mocked) triggers: ``GenericImporter.parse_conversation`` raises
TypeError by design for data that is not a string, dict or list, so an
array carrying such an item exercises the boundary without patching
anything.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.importers.generic_importer import GenericImporter  # noqa: E402


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="generic_importer_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def importer(temp_dir):
    return GenericImporter(Path(temp_dir) / "storage")


def test_json_array_skips_unparseable_item_and_keeps_the_rest(importer):
    """An array of conversations where one entry is an unsupported type: the
    bad item is skipped, the good ones still parse. This is the whole point
    of the per-item boundary -- one malformed record must not cost the batch.
    """
    good = {"title": "Kept", "messages": [{"role": "user", "content": "hi"}]}
    data = [good, 42, dict(good, title="Also kept")]

    conversations = importer._parse_json_array(data)

    assert len(conversations) == 2
    assert {c["title"] for c in conversations} == {"Kept", "Also kept"}


def test_single_conversation_returns_empty_on_unsupported_data_type(importer):
    """``_parse_single_conversation`` reports "nothing parsed" as an empty
    list rather than propagating the TypeError from ``parse_conversation``.
    """
    assert importer._parse_single_conversation(42) == []
