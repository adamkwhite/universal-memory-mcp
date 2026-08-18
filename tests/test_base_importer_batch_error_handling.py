#!/usr/bin/env python3
"""Test for BaseImporter.batch_import's ``except Exception`` boundary
(line ~351), flagged as untested new code in PR #175.

Every concrete importer in this repo (Claude/ChatGPT/Cursor/Generic)
already wraps its own ``import_file`` in a top-level try/except and never
raises (see the sibling *_error_handling.py test files), so this
particular boundary can only be reached by a *faulty importer plugin*
whose ``import_file`` raises directly -- exactly the scenario the
docstring describes ("skip unimportable file, keep processing the rest of
the batch"). This test exercises that documented contract with a
deliberately-raising, real (non-mocked) BaseImporter subclass -- the same
pattern tests/test_importers/test_base_importer.py already uses to test
the abstract base class -- rather than mocking the exception on top of an
existing importer, since no existing importer can trigger this path by
design.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.importers.base_importer import BaseImporter, ImportResult  # noqa: E402


class _FlakyImporter(BaseImporter):
    """A conforming BaseImporter subclass whose import_file raises for one
    specific input, to exercise batch_import's per-file resilience
    boundary the way a real (if buggy) importer plugin would."""

    def __init__(self, storage_path: Path):
        super().__init__(storage_path, "flaky")

    def get_supported_formats(self) -> list[str]:
        return [".json"]

    def import_file(self, file_path: Path) -> ImportResult:
        if file_path.name == "boom.json":
            raise RuntimeError("simulated importer plugin bug")
        return ImportResult(
            success=True,
            conversations_imported=1,
            conversations_failed=0,
            errors=[],
            imported_ids=[file_path.stem],
            metadata={},
        )

    def parse_conversation(self, raw_data: Any) -> dict[str, Any]:
        return self.create_universal_conversation(
            platform_id="x",
            title="x",
            content="x",
            messages=[],
            date=None,
        )


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="base_importer_batch_error_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_batch_import_skips_raising_file_and_keeps_processing_the_rest(temp_dir):
    """A file whose import_file raises must be recorded as a failure with
    the exception message in errors, while unrelated files in the same
    batch still succeed -- not abort the whole batch."""
    importer = _FlakyImporter(Path(temp_dir) / "storage")
    good_one = Path(temp_dir) / "good1.json"
    boom = Path(temp_dir) / "boom.json"
    good_two = Path(temp_dir) / "good2.json"
    for p in (good_one, boom, good_two):
        p.write_text("{}", encoding="utf-8")

    result = importer.batch_import([good_one, boom, good_two])

    assert result.conversations_imported == 2
    assert result.conversations_failed == 1
    assert any("simulated importer plugin bug" in e for e in result.errors)
    assert any("boom.json" in e for e in result.errors)
    # The two well-behaved files were still processed despite boom.json.
    assert set(result.imported_ids) == {"good1", "good2"}
