#!/usr/bin/env python3
"""Tests for ``scripts/bulk_import_enhanced.py``.

These tests focus on the refactored auto-detection / dispatch logic:

    * Auto-detect picks the right importer per detected platform.
    * Explicit ``--format`` overrides detection.
    * Low-confidence detection triggers the legacy fallback.
    * ``--dry-run`` does not invoke the memory server's writes.
    * Empty / malformed input is handled gracefully.
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Module loading: bulk_import_enhanced lives under scripts/ and isn't on the
# default import path. Load it explicitly so tests can exercise its classes.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "bulk_import_enhanced.py"

# Ensure ``src`` is importable for the side-effect imports inside the script.
sys.path.insert(0, str(REPO_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("bulk_import_enhanced", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
bulk_import_enhanced: Any = importlib.util.module_from_spec(_spec)
sys.modules["bulk_import_enhanced"] = bulk_import_enhanced
_spec.loader.exec_module(bulk_import_enhanced)

EnhancedBulkImporter = bulk_import_enhanced.EnhancedBulkImporter
PlatformType = bulk_import_enhanced.PlatformType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_memory_server():
    """Async memory server stub returning success."""
    server = MagicMock()
    server.add_conversation = AsyncMock(return_value={"status": "success", "message": "ok"})
    return server


def _make_detector(platform: Any, confidence: float):
    detector = MagicMock()
    detector.detect_format.return_value = {
        "platform": platform.value,
        "confidence": confidence,
        "message": f"mock detection: {platform.value}",
        "timestamp": 0,
    }
    return detector


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Platform resolution unit tests
# ---------------------------------------------------------------------------
class TestResolvePlatform:
    def setup_method(self):
        self.importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )

    def test_explicit_format_overrides_detection(self):
        for fmt in ("chatgpt", "cursor", "claude", "generic"):
            label, fallback = self.importer._resolve_platform(
                requested_format=fmt,
                detected_platform=PlatformType.UNKNOWN.value,
                confidence=0.0,
            )
            assert label == fmt
            assert fallback is False

    def test_auto_dispatches_to_chatgpt(self):
        label, fallback = self.importer._resolve_platform("auto", PlatformType.CHATGPT.value, 0.95)
        assert label == "chatgpt"
        assert fallback is False

    def test_auto_dispatches_to_cursor(self):
        label, fallback = self.importer._resolve_platform("auto", PlatformType.CURSOR.value, 0.95)
        assert label == "cursor"
        assert fallback is False

    @pytest.mark.parametrize(
        "platform",
        [
            PlatformType.CLAUDE_WEB,
            PlatformType.CLAUDE_DESKTOP,
            PlatformType.CLAUDE_MEMORY,
        ],
    )
    def test_auto_dispatches_to_claude_variants(self, platform):
        label, fallback = self.importer._resolve_platform("auto", platform.value, 0.95)
        assert label == "claude"
        assert fallback is False

    def test_auto_dispatches_to_generic(self):
        label, fallback = self.importer._resolve_platform(
            "auto", PlatformType.GENERIC_JSON.value, 0.7
        )
        assert label == "generic"
        assert fallback is False

    def test_low_confidence_falls_back_to_legacy(self):
        label, fallback = self.importer._resolve_platform("auto", PlatformType.CHATGPT.value, 0.1)
        assert label == "legacy"
        assert fallback is True

    def test_unknown_platform_falls_back_to_legacy(self):
        label, fallback = self.importer._resolve_platform("auto", PlatformType.UNKNOWN.value, 0.99)
        assert label == "legacy"
        assert fallback is True


# ---------------------------------------------------------------------------
# End-to-end dispatch tests using temp files
# ---------------------------------------------------------------------------
class TestRunDispatch:
    @pytest.mark.asyncio
    async def test_auto_detect_uses_chatgpt_importer(self, tmp_path, fake_memory_server):
        # ChatGPT-shaped data so that even if the detector mock is bypassed
        # the parser succeeds.
        chatgpt_payload = {
            "conversations": [
                {
                    "id": "conv-1",
                    "title": "Hello",
                    "create_time": "2025-01-01T12:00:00Z",
                    "messages": [
                        {
                            "id": "m1",
                            "role": "user",
                            "content": "Hi there",
                            "create_time": "2025-01-01T12:00:00Z",
                        },
                        {
                            "id": "m2",
                            "role": "assistant",
                            "content": "Hello human",
                            "create_time": "2025-01-01T12:00:01Z",
                        },
                    ],
                }
            ]
        }
        export = _write_json(tmp_path / "chatgpt.json", chatgpt_payload)

        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.CHATGPT, 0.95),
        )
        await importer.run(export, requested_format="auto")

        assert importer.format_used == "chatgpt"
        assert importer.fallback_used is False
        assert importer.imported_count == 1
        assert importer.platform_counts == {"chatgpt": 1}
        fake_memory_server.add_conversation.assert_awaited()

    @pytest.mark.asyncio
    async def test_explicit_format_overrides_detection(self, tmp_path, fake_memory_server):
        chatgpt_payload = {
            "conversations": [
                {
                    "id": "conv-1",
                    "title": "Force",
                    "create_time": "2025-01-01T12:00:00Z",
                    "messages": [
                        {
                            "id": "m1",
                            "role": "user",
                            "content": "ping",
                            "create_time": "2025-01-01T12:00:00Z",
                        },
                        {
                            "id": "m2",
                            "role": "assistant",
                            "content": "pong",
                            "create_time": "2025-01-01T12:00:01Z",
                        },
                    ],
                }
            ]
        }
        export = _write_json(tmp_path / "force.json", chatgpt_payload)

        # Detector says UNKNOWN, but explicit ``--format chatgpt`` should win.
        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(export, requested_format="chatgpt")

        assert importer.format_used == "chatgpt"
        assert importer.fallback_used is False
        assert importer.imported_count >= 1

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_legacy(self, tmp_path, fake_memory_server):
        # Legacy-shaped Claude export (list of conversations with content).
        legacy_payload = [
            {
                "title": "Legacy chat",
                "content": "Some legacy content body",
                "date": "2025-01-01T12:00:00",
            }
        ]
        export = _write_json(tmp_path / "legacy.json", legacy_payload)

        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.CHATGPT, 0.1),
        )
        await importer.run(export, requested_format="auto")

        assert importer.format_used == "legacy"
        assert importer.fallback_used is True
        assert importer.imported_count == 1
        assert importer.platform_counts == {"legacy": 1}

    @pytest.mark.asyncio
    async def test_dry_run_does_not_invoke_memory_server(self, tmp_path, fake_memory_server):
        legacy_payload = [
            {
                "title": "Dry chat",
                "content": "Body content " * 5,
                "date": "2025-01-01T12:00:00",
            }
        ]
        export = _write_json(tmp_path / "dry.json", legacy_payload)

        importer = EnhancedBulkImporter(
            dry_run=True,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(export, requested_format="auto")

        assert importer.imported_count == 1
        # Most importantly: the memory server is never called in dry-run.
        fake_memory_server.add_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_file_records_error(self, tmp_path, fake_memory_server):
        importer = EnhancedBulkImporter(
            dry_run=True,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(tmp_path / "does_not_exist.json", requested_format="auto")

        assert importer.imported_count == 0
        assert any("does not exist" in err for err in importer.errors)

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_and_records_error(self, tmp_path, fake_memory_server):
        bad = tmp_path / "bad.json"
        bad.write_text("{this is not json", encoding="utf-8")

        # Detector will report an error/UNKNOWN -> legacy path which then
        # also fails to parse, so we expect an error and zero imports.
        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(bad, requested_format="auto")

        assert importer.imported_count == 0
        assert any("Error reading JSON" in err for err in importer.errors)

    @pytest.mark.asyncio
    async def test_empty_conversations_list_reports_no_work(self, tmp_path, fake_memory_server):
        export = _write_json(tmp_path / "empty.json", [])

        importer = EnhancedBulkImporter(
            dry_run=True,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(export, requested_format="auto")

        # No errors, but nothing imported either.
        assert importer.imported_count == 0
        assert importer.failed_count == 0


# ---------------------------------------------------------------------------
# Helper-method tests (legacy extraction utilities)
# ---------------------------------------------------------------------------
class TestLegacyExtractors:
    def setup_method(self):
        self.importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )

    def test_extract_conversation_from_messages_list(self):
        conv = {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello back"},
            ],
            "title": "Greeting",
            "date": "2025-01-01T00:00:00",
        }
        result = self.importer.extract_conversation_content(conv)
        assert result is not None
        assert "Hello back" in result["content"] or "hello back" in result["content"]
        assert result["title"] == "Greeting"

    def test_extract_conversation_returns_none_when_empty(self):
        assert self.importer.extract_conversation_content({}) is None

    def test_unique_title_appends_counter(self):
        first = self.importer._unique_title("Same")
        second = self.importer._unique_title("Same")
        third = self.importer._unique_title("Same")
        assert first == "Same"
        assert second == "Same (1)"
        assert third == "Same (2)"

    def test_normalize_date_handles_iso_string(self):
        result = EnhancedBulkImporter._normalize_date("2025-01-01T12:00:00Z")
        assert result.startswith("2025-01-01T12:00:00")

    def test_normalize_date_handles_unix_timestamp(self):
        result = EnhancedBulkImporter._normalize_date(0)
        assert "1970" in result

    def test_normalize_date_falls_back_for_unparseable_string(self):
        # Should pass through untouched (caller may still accept it)
        result = EnhancedBulkImporter._normalize_date("not a date")
        assert result == "not a date"

    def test_collect_legacy_conversations_dict_with_known_keys(self):
        data = {"chats": [{"content": "x"}]}
        result = self.importer._collect_legacy_conversations(data)
        assert result == [{"content": "x"}]

    def test_collect_legacy_conversations_single_dict(self):
        data = {"content": "single"}
        result = self.importer._collect_legacy_conversations(data)
        assert result == [data]

    def test_collect_legacy_conversations_unsupported_type(self):
        assert self.importer._collect_legacy_conversations("not a dict") == []


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
class TestArgParser:
    def test_default_format_is_auto(self):
        parser = bulk_import_enhanced._build_arg_parser()
        args = parser.parse_args(["some.json"])
        assert args.format == "auto"
        assert args.dry_run is False

    def test_format_choice_validation(self):
        parser = bulk_import_enhanced._build_arg_parser()
        args = parser.parse_args(["x.json", "--format", "chatgpt", "--dry-run"])
        assert args.format == "chatgpt"
        assert args.dry_run is True

    def test_invalid_format_rejected(self):
        parser = bulk_import_enhanced._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["x.json", "--format", "nope"])


# ---------------------------------------------------------------------------
# Persistence + reporting helpers
# ---------------------------------------------------------------------------
class TestSaveAndReport:
    @pytest.mark.asyncio
    async def test_save_conversation_records_failure(self, tmp_path):
        memory = MagicMock()
        memory.add_conversation = AsyncMock(return_value={"status": "error", "message": "boom"})
        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=memory,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer._save_conversation(
            content="hello",
            title="t",
            date="2025-01-01T00:00:00",
            platform_label="legacy",
        )
        assert importer.failed_count == 1
        assert importer.imported_count == 0
        assert any("boom" in err for err in importer.errors)

    @pytest.mark.asyncio
    async def test_save_conversation_dry_run_increments_counts(self):
        importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer._save_conversation(
            content="payload",
            title="dry title",
            date="2025-01-01T00:00:00",
            platform_label="chatgpt",
        )
        assert importer.imported_count == 1
        assert importer.platform_counts == {"chatgpt": 1}

    @pytest.mark.asyncio
    async def test_save_conversation_forwards_metadata_kwargs(self, fake_memory_server):
        """Metadata kwargs are forwarded to memory_server.add_conversation."""
        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer._save_conversation(
            content="c",
            title="t",
            date="2026-04-18T10:00:00",
            platform_label="chatgpt",
            session_id="sess_x",
            user_id="user_y",
            tags=["starred"],
            conversation_type="code",
            custom_fields={"workspace": "/x"},
        )
        fake_memory_server.add_conversation.assert_awaited_once_with(
            "c",
            "t",
            "2026-04-18T10:00:00",
            session_id="sess_x",
            user_id="user_y",
            tags=["starred"],
            conversation_type="code",
            custom_fields={"workspace": "/x"},
        )

    @pytest.mark.asyncio
    async def test_persist_staged_conversation_lifts_metadata_from_json(
        self, tmp_path, fake_memory_server
    ):
        """A staged universal-format JSON has its metadata extracted and passed through."""
        staged = tmp_path / "conv.json"
        staged.write_text(
            json.dumps(
                {
                    "title": "Imported from staging",
                    "content": "some content",
                    "date": "2026-04-18T10:00:00",
                    "session_id": "sess_42",
                    "user_id": "user_42",
                    "tags": ["imported", "starred"],
                    "conversation_type": "chat",
                    "custom_fields": {"origin": "chatgpt"},
                }
            ),
            encoding="utf-8",
        )

        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )

        await importer._persist_staged_conversation(staged, "chatgpt")

        call = fake_memory_server.add_conversation.await_args
        assert call.kwargs["session_id"] == "sess_42"
        assert call.kwargs["user_id"] == "user_42"
        assert call.kwargs["tags"] == ["imported", "starred"]
        assert call.kwargs["conversation_type"] == "chat"
        assert call.kwargs["custom_fields"] == {"origin": "chatgpt"}

    def test_print_summary_with_no_run(self, capsys):
        importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        importer.print_summary()
        out = capsys.readouterr().out
        assert "IMPORT SUMMARY" in out
        # When nothing has run, success rate line is skipped (total_processed = 0).
        assert "Success rate" not in out

    def test_print_summary_includes_per_format_and_truncated_errors(self, capsys):
        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=MagicMock(),
            detector=_make_detector(PlatformType.CHATGPT, 0.95),
        )
        importer.detection_result = {
            "platform": "chatgpt",
            "confidence": 0.95,
            "message": "ok",
        }
        importer.format_used = "chatgpt"
        importer.fallback_used = False
        importer.imported_count = 7
        importer.skipped_count = 1
        importer.failed_count = 2
        importer.platform_counts = {"chatgpt": 7}
        importer.errors = [f"err {i}" for i in range(7)]

        importer.print_summary()
        out = capsys.readouterr().out

        assert "Imported: 7" in out
        assert "Per-format counts:" in out
        assert "chatgpt: 7" in out
        # First 5 errors listed, then "and N more" line.
        assert "err 0" in out
        assert "err 4" in out
        assert "and 2 more" in out

    def test_maybe_print_progress_zero_total(self, capsys):
        importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        importer._maybe_print_progress(processed=0, total=0)
        assert capsys.readouterr().out == ""

    def test_maybe_print_progress_emits_at_interval(self, capsys):
        importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
            progress_interval=2,
        )
        importer._maybe_print_progress(processed=2, total=10)
        importer._maybe_print_progress(processed=3, total=10)  # no print
        out = capsys.readouterr().out
        assert "Progress: 2/10" in out
        assert "Progress: 3/10" not in out

    def test_build_importer_unknown_label_raises(self, tmp_path):
        importer = EnhancedBulkImporter(
            dry_run=True,
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        with pytest.raises(ValueError, match="Unknown importer label"):
            importer._build_importer("not-a-real-format", tmp_path)


# ---------------------------------------------------------------------------
# Importer-staging fallback path
# ---------------------------------------------------------------------------
class TestStagingFallback:
    @pytest.mark.asyncio
    async def test_importer_with_no_output_falls_back_to_legacy(self, tmp_path, fake_memory_server):
        """If the importer parses nothing, we fall back to the legacy extractor."""
        # ChatGPT importer requires "conversations" key. Provide a payload that
        # is valid Claude-legacy (list of dicts with content) but NOT valid
        # ChatGPT, so the ChatGPT importer produces zero conversations and
        # the runner should fall back.
        legacy_payload = [
            {
                "title": "Fallback me",
                "content": "body content here",
                "date": "2025-01-01",
            }
        ]
        export = _write_json(tmp_path / "fallback.json", legacy_payload)

        importer = EnhancedBulkImporter(
            dry_run=False,
            memory_server=fake_memory_server,
            # Force ChatGPT explicitly even though file isn't ChatGPT format.
            detector=_make_detector(PlatformType.UNKNOWN, 0.0),
        )
        await importer.run(export, requested_format="chatgpt")

        # The runner started in chatgpt, the importer produced nothing,
        # so it fell back to legacy and imported via the hand-rolled path.
        assert importer.fallback_used is True
        assert importer.format_used == "legacy"
        assert importer.imported_count == 1


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------
class TestMain:
    @pytest.mark.asyncio
    async def test_main_dry_run_returns_zero(self, tmp_path, monkeypatch):
        legacy_payload = [{"title": "Main test", "content": "main body", "date": "2025-01-01"}]
        export = _write_json(tmp_path / "main.json", legacy_payload)

        monkeypatch.setattr(
            sys,
            "argv",
            ["bulk_import_enhanced.py", str(export), "--dry-run", "--format", "auto"],
        )

        rc = await bulk_import_enhanced.main()
        assert rc == 0
