#!/usr/bin/env python3
"""Tests for ``src/exporters/json_exporter.py``."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest  # type: ignore[import-not-found]
from conftest import requires_posix_permissions

# Ensure ``src/`` is importable so we can use bare ``exporters.X`` imports
# (matching the pattern used by tests/test_config.py).
SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from universal_memory_mcp.exporters.base_exporter import (  # noqa: E402
    Filters,  # type: ignore[import-not-found]
)
from universal_memory_mcp.exporters.json_exporter import (  # type: ignore[import-not-found]  # noqa: E402
    JSON_EXPORT_FORMAT_VERSION,
    JsonExporter,
)

from .test_base_exporter import (  # noqa: E402
    _build_storage,
    _legacy_conversation,
    _universal_conversation,
)


class TestJsonExporterBasics:
    def test_export_writes_envelope(self, tmp_path):
        _build_storage(
            tmp_path,
            [_universal_conversation(conv_id="c1", platform="chatgpt")],
        )
        out = tmp_path / "out.json"
        exporter = JsonExporter(tmp_path)
        result = exporter.export(out)

        assert result.success is True
        assert result.conversations_exported == 1
        assert result.conversations_failed == 0
        assert result.output_path == str(out)
        assert result.metadata["format"] == "universal"
        assert result.metadata["format_version"] == JSON_EXPORT_FORMAT_VERSION
        assert result.success_rate == 1.0

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["format"] == "universal"
        assert payload["conversation_count"] == 1
        assert len(payload["conversations"]) == 1
        assert payload["conversations"][0]["id"] == "c1"
        # Filters block should be present and empty.
        assert payload["filters_applied"] == {}

    def test_export_empty_storage(self, tmp_path):
        out = tmp_path / "out.json"
        exporter = JsonExporter(tmp_path)
        result = exporter.export(out)

        assert result.success is True
        assert result.conversations_exported == 0
        assert out.exists()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["conversation_count"] == 0
        assert payload["conversations"] == []

    @requires_posix_permissions
    def test_export_to_unwritable_path_returns_error(self, tmp_path):
        _build_storage(tmp_path, [_universal_conversation()])
        bad = Path("/proc/no-such-dir/out.json")
        exporter = JsonExporter(tmp_path)
        result = exporter.export(bad)
        assert result.success is False
        assert result.output_path is None
        assert result.errors

    def test_load_failure_propagates(self, tmp_path, monkeypatch):
        exporter = JsonExporter(tmp_path)

        def boom():
            raise RuntimeError("explode")

        monkeypatch.setattr(exporter, "load_conversations", boom)
        result = exporter.export(tmp_path / "out.json")
        assert result.success is False
        assert any("Failed to load" in e for e in result.errors)


class TestJsonExporterFilters:
    def test_export_with_filters_records_them_in_envelope(self, tmp_path):
        _build_storage(
            tmp_path,
            [
                _universal_conversation(
                    conv_id="a", platform="chatgpt", date="2025-01-01T00:00:00"
                ),
                _universal_conversation(
                    conv_id="b", platform="chatgpt", date="2025-08-01T00:00:00"
                ),
                _universal_conversation(conv_id="c", platform="claude", date="2025-08-01T00:00:00"),
            ],
        )
        out = tmp_path / "out.json"
        exporter = JsonExporter(tmp_path)
        filters = Filters(
            date_from=datetime(2025, 6, 1),
            platforms=["chatgpt"],
            limit=10,
        )
        result = exporter.export(out, filters)
        assert result.conversations_exported == 1

        payload = json.loads(out.read_text(encoding="utf-8"))
        applied = payload["filters_applied"]
        assert applied["platforms"] == ["chatgpt"]
        assert applied["date_from"] == "2025-06-01T00:00:00"
        assert applied["date_to"] is None
        assert applied["limit"] == 10
        assert payload["conversations"][0]["id"] == "b"

    def test_limit_truncates_output(self, tmp_path):
        convs = [_universal_conversation(conv_id=f"c{i}") for i in range(5)]
        _build_storage(tmp_path, convs)
        out = tmp_path / "out.json"
        exporter = JsonExporter(tmp_path)
        result = exporter.export(out, Filters(limit=2))
        assert result.conversations_exported == 2
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert len(payload["conversations"]) == 2


class TestJsonExporterValidate:
    def _write_payload(self, path: Path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_validate_round_trip_success(self, tmp_path):
        _build_storage(tmp_path, [_universal_conversation()])
        out = tmp_path / "out.json"
        exporter = JsonExporter(tmp_path)
        exporter.export(out)
        result = exporter.validate(out)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["conversation_count"] == 1

    def test_validate_missing_file(self, tmp_path):
        exporter = JsonExporter(tmp_path)
        result = exporter.validate(tmp_path / "nope.json")
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_validate_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json{", encoding="utf-8")
        result = JsonExporter(tmp_path).validate(bad)
        assert result["valid"] is False

    def test_validate_top_level_not_object(self, tmp_path):
        bad = tmp_path / "list.json"
        self._write_payload(bad, [1, 2, 3])
        result = JsonExporter(tmp_path).validate(bad)
        assert result["valid"] is False
        assert "object" in result["errors"][0].lower()

    def test_validate_conversations_not_list(self, tmp_path):
        bad = tmp_path / "bad.json"
        self._write_payload(bad, {"format": "universal", "conversations": {}})
        result = JsonExporter(tmp_path).validate(bad)
        assert result["valid"] is False
        assert any("must be a list" in e for e in result["errors"])

    def test_validate_warns_on_wrong_format(self, tmp_path):
        out = tmp_path / "out.json"
        self._write_payload(
            out,
            {
                "format": "chatgpt",
                "conversations": [
                    {
                        "id": "x",
                        "platform": "chatgpt",
                        "title": "t",
                        "content": "c",
                        "messages": [],
                        "date": "2025-01-01",
                    }
                ],
            },
        )
        result = JsonExporter(tmp_path).validate(out)
        assert result["valid"] is True
        assert result["warnings"]

    def test_validate_missing_required_fields(self, tmp_path):
        out = tmp_path / "missing.json"
        self._write_payload(
            out,
            {
                "format": "universal",
                "conversations": [{"id": "x", "title": "incomplete"}],
            },
        )
        result = JsonExporter(tmp_path).validate(out)
        assert result["valid"] is False
        assert len(result["errors"]) >= 4  # missing platform/content/etc.

    def test_validate_non_dict_conversation(self, tmp_path):
        out = tmp_path / "weird.json"
        self._write_payload(
            out,
            {"format": "universal", "conversations": ["not an object"]},
        )
        result = JsonExporter(tmp_path).validate(out)
        assert result["valid"] is False
        assert any("not an object" in e for e in result["errors"])

    def test_validate_messages_not_list(self, tmp_path):
        out = tmp_path / "bad_msgs.json"
        self._write_payload(
            out,
            {
                "format": "universal",
                "conversations": [
                    {
                        "id": "x",
                        "platform": "chatgpt",
                        "title": "t",
                        "content": "c",
                        "messages": "should-be-list",
                        "date": "2025-01-01",
                    }
                ],
            },
        )
        result = JsonExporter(tmp_path).validate(out)
        assert result["valid"] is False
        assert any("must be a list" in e for e in result["errors"])


class TestJsonExporterLegacyUpgrade:
    def test_legacy_records_upgraded_in_export(self, tmp_path):
        _build_storage(
            tmp_path,
            [_legacy_conversation(conv_id="legacy_1")],
        )
        out = tmp_path / "out.json"
        result = JsonExporter(tmp_path).export(out)
        assert result.conversations_exported == 1
        payload = json.loads(out.read_text(encoding="utf-8"))
        conv = payload["conversations"][0]
        # Synthetic universal fields populated
        assert conv["platform"] == "unknown"
        assert isinstance(conv["messages"], list)
        assert conv["messages"], "should have synthetic message"
        assert conv["messages"][0]["metadata"]["synthetic"] is True


class TestJsonExporterRoundTrip:
    """Full round-trip: import ChatGPT → universal storage → export → re-validate."""

    def _write_chatgpt_export(self, tmp_path: Path) -> Path:
        export_data = {
            "conversations": [
                {
                    "id": "conv-r-1",
                    "title": "Round Trip 1",
                    "create_time": "2025-03-01T10:00:00Z",
                    "update_time": "2025-03-01T10:30:00Z",
                    "messages": [
                        {
                            "id": "m1",
                            "role": "user",
                            "content": "Hello",
                            "create_time": "2025-03-01T10:00:00Z",
                        },
                        {
                            "id": "m2",
                            "role": "assistant",
                            "content": "Hi there!",
                            "create_time": "2025-03-01T10:01:00Z",
                        },
                    ],
                }
            ]
        }
        export_path = tmp_path / "chatgpt_export.json"
        export_path.write_text(json.dumps(export_data), encoding="utf-8")
        return export_path

    def test_round_trip_preserves_key_universal_fields(self, tmp_path):
        # Lazy import: avoid mypy following src/importers into the schema
        # module which has a pre-existing missing-stubs warning.
        from universal_memory_mcp.importers.chatgpt_importer import (  # type: ignore[import-not-found]
            ChatGPTImporter,
        )

        # Step 1: import a ChatGPT export into universal storage layout.
        storage_root = tmp_path / "storage"
        importer_storage = storage_root / "data" / "conversations"
        importer = ChatGPTImporter(importer_storage)
        result = importer.import_file(self._write_chatgpt_export(tmp_path))
        assert result.success
        assert result.conversations_imported == 1
        original_id = result.imported_ids[0]

        # Step 2: build minimal index.json so the exporter can find it.
        # ChatGPT importer doesn't update index.json, so do it manually
        # (mirrors what ConversationMemoryServer._sync_index_from_files does).
        conv_file = next(importer_storage.rglob("conv_*.json"))
        index_entry = {
            "id": original_id,
            "title": "Round Trip 1",
            "date": "2025-03-01T10:00:00",
            "topics": [],
            "file_path": str(conv_file.relative_to(storage_root)),
            "added_at": "2025-03-01T10:00:00",
        }
        (importer_storage / "index.json").write_text(
            json.dumps({"conversations": [index_entry]}, indent=2),
            encoding="utf-8",
        )

        # Step 3: export and validate.
        out = tmp_path / "exported.json"
        exporter = JsonExporter(storage_root)
        export_result = exporter.export(out)
        assert export_result.success
        assert export_result.conversations_exported == 1

        validation = exporter.validate(out)
        assert validation["valid"], validation

        payload = json.loads(out.read_text(encoding="utf-8"))
        exported_conv = payload["conversations"][0]

        # Key fields preserved verbatim from the universal-format file.
        assert exported_conv["id"] == original_id
        assert exported_conv["platform"] == "chatgpt"
        assert exported_conv["title"] == "Round Trip 1"
        assert exported_conv["model"] == "gpt-4"
        assert len(exported_conv["messages"]) == 2
        assert exported_conv["messages"][0]["role"] == "user"
        assert exported_conv["messages"][1]["role"] == "assistant"
        assert "Hello" in exported_conv["messages"][0]["content"]


@pytest.mark.parametrize(
    "filter_kwargs,expected_count",
    [
        ({}, 3),
        ({"limit": 1}, 1),
        ({"platforms": ["chatgpt"]}, 2),
        ({"date_from": datetime(2025, 6, 1)}, 1),
    ],
)
def test_filter_combinations(tmp_path, filter_kwargs, expected_count):
    convs = [
        _universal_conversation(conv_id="a", platform="chatgpt", date="2025-01-01T00:00:00"),
        _universal_conversation(conv_id="b", platform="chatgpt", date="2025-12-01T00:00:00"),
        _universal_conversation(conv_id="c", platform="claude", date="2025-02-01T00:00:00"),
    ]
    _build_storage(tmp_path, convs)
    out = tmp_path / "out.json"
    exporter = JsonExporter(tmp_path)
    result = exporter.export(out, Filters(**filter_kwargs))
    assert result.conversations_exported == expected_count
