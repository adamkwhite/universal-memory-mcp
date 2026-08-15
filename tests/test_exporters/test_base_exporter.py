#!/usr/bin/env python3
"""Tests for ``src/exporters/base_exporter.py``."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-not-found]
from conftest import requires_posix_permissions

# Make ``src/`` importable when tests are run via pytest from repo root.
SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from exporters.base_exporter import (  # type: ignore[import-not-found]  # noqa: E402
    UNIVERSAL_REQUIRED_FIELDS,
    BaseExporter,
    ExportResult,
    Filters,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _ConcreteExporter(BaseExporter):
    """Minimal concrete BaseExporter subclass used to test shared helpers."""

    def export(
        self,
        output_path: Path,
        filters: Filters | None = None,
    ) -> ExportResult:
        items = self.apply_filters(self.load_conversations(), filters)
        self.write_json(output_path, {"conversations": items})
        return ExportResult(
            success=True,
            conversations_exported=len(items),
            conversations_failed=0,
            errors=[],
            output_path=str(output_path),
        )

    def validate(self, output_path: Path) -> dict[str, Any]:
        return {
            "valid": output_path.exists(),
            "errors": [],
            "warnings": [],
            "conversation_count": 0,
        }


def _build_storage(
    tmp_path: Path,
    conversations: list[dict[str, Any]],
    *,
    use_data_layout: bool = True,
) -> Path:
    """Create a fake storage tree with index.json + per-conversation files."""
    convs_root = tmp_path / ("data/conversations" if use_data_layout else "conversations")
    convs_root.mkdir(parents=True, exist_ok=True)

    index_entries = []
    for conv in conversations:
        date = conv.get("date") or datetime.now().isoformat()
        try:
            parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now()
        month_dir = (
            convs_root / str(parsed.year) / f"{parsed.month:02d}-{parsed.strftime('%B').lower()}"
        )
        month_dir.mkdir(parents=True, exist_ok=True)
        file_path = month_dir / f"{conv['id']}.json"
        file_path.write_text(json.dumps(conv, indent=2), encoding="utf-8")
        index_entries.append(
            {
                "id": conv["id"],
                "title": conv.get("title", ""),
                "date": date,
                "topics": conv.get("topics", []),
                "file_path": str(file_path.relative_to(tmp_path)),
                "added_at": datetime.now().isoformat(),
            }
        )

    (convs_root / "index.json").write_text(
        json.dumps({"conversations": index_entries}, indent=2),
        encoding="utf-8",
    )
    return tmp_path


def _legacy_conversation(
    conv_id: str = "conv_20251010_120000_0001",
    *,
    date: str = "2025-10-10T12:00:00",
    title: str = "Legacy Conversation",
    content: str = "Hello world content",
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """Simulate the legacy on-disk shape used by ConversationMemoryServer."""
    return {
        "id": conv_id,
        "title": title,
        "content": content,
        "date": date,
        "topics": topics or ["test"],
        "created_at": date,
    }


def _universal_conversation(
    conv_id: str = "conv_20251010_120000_uni0",
    *,
    date: str = "2025-10-10T12:00:00",
    platform: str = "chatgpt",
    title: str = "Universal Convo",
) -> dict[str, Any]:
    """Simulate a universal-format conversation produced by importers."""
    msgs = [
        {
            "id": "m1",
            "role": "user",
            "content": "Hi there",
            "timestamp": date,
            "metadata": {},
        },
        {
            "id": "m2",
            "role": "assistant",
            "content": "Hello back",
            "timestamp": date,
            "metadata": {},
        },
    ]
    return {
        "id": conv_id,
        "platform": platform,
        "platform_id": f"native-{conv_id}",
        "model": "gpt-4",
        "title": title,
        "content": "Hi there\n\nHello back",
        "messages": msgs,
        "date": date,
        "last_updated": date,
        "topics": ["test", platform],
        "session_context": {},
        "import_metadata": {"imported_at": date},
        "created_at": date,
    }


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


class TestExportResult:
    def test_success_rate_with_zero_total(self):
        result = ExportResult(
            success=False,
            conversations_exported=0,
            conversations_failed=0,
            errors=[],
            output_path=None,
        )
        assert result.success_rate == 0.0
        assert result.total_processed == 0

    def test_success_rate_with_failures(self):
        result = ExportResult(
            success=True,
            conversations_exported=8,
            conversations_failed=2,
            errors=[],
            output_path="/tmp/out.json",
        )
        assert result.total_processed == 10
        assert result.success_rate == 0.8

    def test_success_rate_perfect(self):
        result = ExportResult(
            success=True,
            conversations_exported=5,
            conversations_failed=0,
            errors=[],
            output_path="/tmp/out.json",
        )
        assert result.success_rate == 1.0


class TestFilters:
    def test_is_empty_default(self):
        assert Filters().is_empty() is True

    def test_is_empty_with_date_from(self):
        assert Filters(date_from=datetime(2025, 1, 1)).is_empty() is False

    def test_is_empty_with_platforms(self):
        assert Filters(platforms=["chatgpt"]).is_empty() is False

    def test_is_empty_with_limit(self):
        assert Filters(limit=10).is_empty() is False

    def test_is_empty_with_empty_platforms_list(self):
        # An explicitly empty list is treated as "no platform filter".
        assert Filters(platforms=[]).is_empty() is True


class TestLoadConversations:
    def test_loads_data_layout(self, tmp_path):
        _build_storage(
            tmp_path,
            [_legacy_conversation()],
            use_data_layout=True,
        )
        exp = _ConcreteExporter(tmp_path)
        loaded = exp.load_conversations()
        assert len(loaded) == 1
        # Legacy conv should be upgraded to universal shape.
        assert loaded[0]["platform"] == "unknown"
        assert isinstance(loaded[0]["messages"], list)
        assert loaded[0]["messages"], "synthetic message expected"

    def test_loads_legacy_layout(self, tmp_path):
        _build_storage(
            tmp_path,
            [_legacy_conversation()],
            use_data_layout=False,
        )
        exp = _ConcreteExporter(tmp_path)
        loaded = exp.load_conversations()
        assert len(loaded) == 1

    def test_returns_empty_when_no_index(self, tmp_path, caplog):
        exp = _ConcreteExporter(tmp_path)
        loaded = exp.load_conversations()
        assert loaded == []

    def test_handles_corrupt_index(self, tmp_path):
        convs_root = tmp_path / "data" / "conversations"
        convs_root.mkdir(parents=True)
        (convs_root / "index.json").write_text("not json{", encoding="utf-8")
        exp = _ConcreteExporter(tmp_path)
        assert exp.load_conversations() == []

    def test_skips_missing_files(self, tmp_path):
        # Build storage then delete the conversation file but keep index.
        _build_storage(tmp_path, [_legacy_conversation()])
        for f in (tmp_path / "data" / "conversations").rglob("conv_*.json"):
            f.unlink()
        exp = _ConcreteExporter(tmp_path)
        assert exp.load_conversations() == []

    def test_skips_index_entry_without_file_path(self, tmp_path):
        convs_root = tmp_path / "data" / "conversations"
        convs_root.mkdir(parents=True)
        (convs_root / "index.json").write_text(
            json.dumps({"conversations": [{"id": "x", "title": "no path"}]}), encoding="utf-8"
        )
        exp = _ConcreteExporter(tmp_path)
        assert exp.load_conversations() == []

    def test_skips_corrupt_conversation_file(self, tmp_path):
        _build_storage(tmp_path, [_legacy_conversation()])
        # Corrupt the conversation file
        for f in (tmp_path / "data" / "conversations").rglob("conv_*.json"):
            f.write_text("totally not json", encoding="utf-8")
        exp = _ConcreteExporter(tmp_path)
        assert exp.load_conversations() == []

    def test_universal_conversation_passes_through(self, tmp_path):
        original = _universal_conversation()
        _build_storage(tmp_path, [original])
        exp = _ConcreteExporter(tmp_path)
        loaded = exp.load_conversations()
        assert loaded[0]["platform"] == "chatgpt"
        # Existing messages should be preserved (no synthetic injection).
        assert len(loaded[0]["messages"]) == 2
        assert loaded[0]["messages"][0]["role"] == "user"


class TestNormalizeToUniversal:
    def test_legacy_gains_required_defaults(self):
        legacy = _legacy_conversation()
        upgraded = BaseExporter._normalize_to_universal(legacy)
        for field_name in UNIVERSAL_REQUIRED_FIELDS:
            assert field_name in upgraded
        assert upgraded["platform"] == "unknown"
        assert upgraded["model"] == "unknown"
        assert upgraded["messages"][0]["metadata"]["synthetic"] is True

    def test_does_not_mutate_input(self):
        legacy = _legacy_conversation()
        before = dict(legacy)
        BaseExporter._normalize_to_universal(legacy)
        assert legacy == before  # outer dict unchanged

    def test_no_synthetic_message_when_content_empty(self):
        conv = _legacy_conversation(content="")
        upgraded = BaseExporter._normalize_to_universal(conv)
        assert upgraded["messages"] == []


class TestApplyFilters:
    def test_no_filters_returns_all(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [_universal_conversation(conv_id=f"c{i}") for i in range(3)]
        assert exp.apply_filters(items, None) == items
        assert exp.apply_filters(items, Filters()) == items

    def test_date_from_filter(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="old", date="2025-01-01T00:00:00"),
            _universal_conversation(conv_id="new", date="2025-12-01T00:00:00"),
        ]
        result = exp.apply_filters(items, Filters(date_from=datetime(2025, 6, 1)))
        assert [c["id"] for c in result] == ["new"]

    def test_date_to_filter(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="old", date="2025-01-01T00:00:00"),
            _universal_conversation(conv_id="new", date="2025-12-01T00:00:00"),
        ]
        result = exp.apply_filters(items, Filters(date_to=datetime(2025, 6, 1)))
        assert [c["id"] for c in result] == ["old"]

    def test_date_range_filter(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="a", date="2025-01-01T00:00:00"),
            _universal_conversation(conv_id="b", date="2025-06-15T00:00:00"),
            _universal_conversation(conv_id="c", date="2025-12-31T00:00:00"),
        ]
        result = exp.apply_filters(
            items,
            Filters(
                date_from=datetime(2025, 6, 1),
                date_to=datetime(2025, 7, 1),
            ),
        )
        assert [c["id"] for c in result] == ["b"]

    def test_date_filter_excludes_unparseable_dates(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="bad", date="not-a-date"),
            _universal_conversation(conv_id="good", date="2025-06-01T00:00:00"),
        ]
        result = exp.apply_filters(items, Filters(date_from=datetime(2025, 1, 1)))
        assert [c["id"] for c in result] == ["good"]

    def test_date_filter_handles_tz_aware_conversation(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [_universal_conversation(conv_id="tz", date="2025-06-01T00:00:00+00:00")]
        # Naive filter compared against tz-aware conversation should still
        # work without raising.
        result = exp.apply_filters(
            items,
            Filters(date_from=datetime(2025, 1, 1)),
        )
        assert [c["id"] for c in result] == ["tz"]

    def test_date_filter_tz_aware_filter_against_naive_conv(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [_universal_conversation(date="2025-06-01T00:00:00")]
        tz_filter = Filters(date_from=datetime(2025, 1, 1, tzinfo=timezone.utc))
        result = exp.apply_filters(items, tz_filter)
        assert len(result) == 1

    def test_platform_filter(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="g", platform="chatgpt"),
            _universal_conversation(conv_id="c", platform="claude"),
            _universal_conversation(conv_id="u", platform="cursor"),
        ]
        result = exp.apply_filters(items, Filters(platforms=["chatgpt", "cursor"]))
        assert sorted(c["id"] for c in result) == ["g", "u"]

    def test_platform_filter_case_insensitive(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [_universal_conversation(platform="ChatGPT")]
        result = exp.apply_filters(items, Filters(platforms=["chatgpt"]))
        assert len(result) == 1

    def test_platform_filter_unknown_matches_legacy(self):
        exp = _ConcreteExporter(Path("/tmp"))
        legacy = _legacy_conversation()
        upgraded = BaseExporter._normalize_to_universal(legacy)
        result = exp.apply_filters([upgraded], Filters(platforms=["unknown"]))
        assert len(result) == 1

    def test_limit_filter(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [_universal_conversation(conv_id=f"c{i}") for i in range(5)]
        result = exp.apply_filters(items, Filters(limit=3))
        assert len(result) == 3
        assert [c["id"] for c in result] == ["c0", "c1", "c2"]

    def test_combined_filters(self):
        exp = _ConcreteExporter(Path("/tmp"))
        items = [
            _universal_conversation(conv_id="a", platform="chatgpt", date="2025-01-01T00:00:00"),
            _universal_conversation(conv_id="b", platform="chatgpt", date="2025-06-01T00:00:00"),
            _universal_conversation(conv_id="c", platform="claude", date="2025-06-01T00:00:00"),
        ]
        result = exp.apply_filters(
            items,
            Filters(
                date_from=datetime(2025, 5, 1),
                platforms=["chatgpt"],
                limit=10,
            ),
        )
        assert [c["id"] for c in result] == ["b"]


class TestWriteJson:
    def test_writes_payload_creating_parent_dirs(self, tmp_path):
        exp = _ConcreteExporter(tmp_path)
        out = tmp_path / "subdir" / "deeper" / "out.json"
        exp.write_json(out, {"hello": "world"})
        assert out.exists()
        assert json.loads(out.read_text(encoding="utf-8")) == {"hello": "world"}

    @requires_posix_permissions
    def test_unwritable_directory_raises(self, tmp_path):
        exp = _ConcreteExporter(tmp_path)
        # /proc is non-writable on Linux; using a known pseudo-fs path keeps
        # the test platform-portable since we only need the OSError raise.
        bad_path = Path("/proc/cannot-write-here/out.json")
        # The exact OSError subclass under /proc varies by kernel/mount setup
        # (observed both FileNotFoundError and PermissionError) - narrowing to
        # one subclass or matching an exact errno string would make this test
        # environment-fragile. The contract under test is genuinely "some
        # OSError", per write_json's own docstring.
        with pytest.raises(OSError):  # noqa: PT011 - see comment above
            exp.write_json(bad_path, {"x": 1})


class TestParseIso:
    def test_parses_basic_iso(self):
        result = BaseExporter._parse_iso("2025-06-15T12:00:00")
        assert result is not None
        assert result.year == 2025

    def test_parses_iso_with_z(self):
        result = BaseExporter._parse_iso("2025-06-15T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_returns_none_for_empty(self):
        assert BaseExporter._parse_iso("") is None
        assert BaseExporter._parse_iso(None) is None  # type: ignore[arg-type]

    def test_returns_none_for_invalid(self):
        assert BaseExporter._parse_iso("not-a-date") is None
