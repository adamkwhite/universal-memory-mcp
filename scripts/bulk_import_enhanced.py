#!/usr/bin/env python3
"""
Enhanced Bulk Conversation Import Script for Claude Memory System

Auto-detects export format (Claude/ChatGPT/Cursor/Generic) using
``src.format_detector.FormatDetector`` and dispatches to the matching
importer in ``src.importers``. Falls back to the original hand-rolled
extraction logic when detection confidence is low or when an importer
cannot parse the file, preserving backward compatibility with prior
Claude exports.

Features:
    * ``--format <claude|chatgpt|cursor|generic|auto>`` (default ``auto``).
    * ``--dry-run`` previews work without writing.
    * Periodic progress reporting (every N conversations) for large imports.
    * Aggregated import statistics with per-format counts.
"""

# Add src directory to path before importing project modules.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# The ``noqa: E402`` markers below are intentional: project-local modules
# under ``src/`` are only importable after the ``sys.path`` insertion above.
import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

# ``ConversationMemoryServer`` lives in ``conversation_memory``; the older
# script imported from ``server_fastmcp`` which now exports it under a
# different name (``FastMCPConversationMemoryServer``).
# Note: these are project-local modules added to ``sys.path`` above; mypy
# can't follow them without a ``py.typed`` marker on the ``src`` package.
from universal_memory_mcp.conversation_memory import (  # type: ignore[import-not-found]  # noqa: E402
    ConversationMemoryServer,
)
from universal_memory_mcp.format_detector import (  # type: ignore[import-not-found]  # noqa: E402
    FormatDetector,
    PlatformType,
)
from universal_memory_mcp.importers import (  # type: ignore[import-not-found]  # noqa: E402
    ChatGPTImporter,
    ClaudeImporter,
    CursorImporter,
    GenericImporter,
)

logger = logging.getLogger(__name__)

# Confidence below this threshold triggers the legacy fallback path.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# Emit a progress message every N conversations during large imports.
PROGRESS_REPORT_INTERVAL = 25

# Mapping from CLI ``--format`` value to ``PlatformType``.
FORMAT_CHOICES = ("auto", "claude", "chatgpt", "cursor", "generic")
FORMAT_TO_PLATFORM = {
    "chatgpt": PlatformType.CHATGPT,
    "cursor": PlatformType.CURSOR,
    "claude": PlatformType.CLAUDE_WEB,  # Treated as a Claude-family hint
    "generic": PlatformType.GENERIC_JSON,
}


class EnhancedBulkImporter:
    """Bulk import driver with format auto-detection and legacy fallback."""

    def __init__(
        self,
        dry_run: bool = False,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        progress_interval: int = PROGRESS_REPORT_INTERVAL,
        memory_server: Optional[ConversationMemoryServer] = None,
        detector: Optional[FormatDetector] = None,
    ):
        self.dry_run = dry_run
        self.confidence_threshold = confidence_threshold
        self.progress_interval = max(1, int(progress_interval))

        # Allow tests to inject collaborators; otherwise build them lazily so
        # ``--dry-run`` does not require write access to the storage path.
        self.memory_server = memory_server
        if self.memory_server is None and not dry_run:
            self.memory_server = ConversationMemoryServer()

        self.detector = detector or FormatDetector()

        # Aggregate counters and bookkeeping.
        self.imported_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.errors: List[str] = []
        self.platform_counts: Dict[str, int] = {}
        self.detection_result: Optional[Dict[str, Any]] = None
        self.format_used: Optional[str] = None
        self.fallback_used: bool = False
        self.conversation_titles: set = set()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(self, json_file: Path, requested_format: str = "auto") -> None:
        """Drive the import for ``json_file`` using ``requested_format``.

        ``requested_format`` may be ``auto`` (detect) or any of the explicit
        platform keys in :data:`FORMAT_CHOICES`. The detection result is
        always stored on ``self.detection_result`` for reporting.
        """
        if not json_file.exists():
            self.errors.append(f"File does not exist: {json_file}")
            print(f"File does not exist: {json_file}")
            return

        self.detection_result = self.detector.detect_format(json_file)
        detected_platform = self.detection_result.get(
            "platform", PlatformType.UNKNOWN.value
        )
        confidence = float(self.detection_result.get("confidence", 0.0))

        print(
            "Detection: platform={platform} confidence={confidence:.2f} ({message})".format(
                platform=detected_platform,
                confidence=confidence,
                message=self.detection_result.get("message", ""),
            )
        )

        platform_to_use, used_fallback = self._resolve_platform(
            requested_format, detected_platform, confidence
        )
        self.format_used = platform_to_use
        self.fallback_used = used_fallback

        print(
            "Importer selected: {p} (requested={r}, fallback={f})".format(
                p=platform_to_use,
                r=requested_format,
                f="yes" if used_fallback else "no",
            )
        )

        if used_fallback:
            await self._import_with_legacy(json_file)
        else:
            await self._import_with_importer(json_file, platform_to_use)

    # ------------------------------------------------------------------
    # Platform resolution
    # ------------------------------------------------------------------
    def _resolve_platform(
        self,
        requested_format: str,
        detected_platform: str,
        confidence: float,
    ) -> Tuple[str, bool]:
        """Decide which importer (or legacy path) to dispatch to.

        Returns a tuple of ``(platform_label, fallback_used)`` where
        ``platform_label`` is either ``"legacy"`` or one of the importer
        keys (``chatgpt``/``cursor``/``claude``/``generic``).
        """
        # Explicit override always wins.
        if requested_format != "auto":
            if requested_format == "claude":
                return "claude", False
            if requested_format in {"chatgpt", "cursor", "generic"}:
                return requested_format, False
            # Defensive: argparse should already have rejected this.
            return "legacy", True

        # Auto path: low confidence drops back to legacy.
        if confidence < self.confidence_threshold:
            return "legacy", True

        if detected_platform == PlatformType.CHATGPT.value:
            return "chatgpt", False
        if detected_platform == PlatformType.CURSOR.value:
            return "cursor", False
        if detected_platform in {
            PlatformType.CLAUDE_WEB.value,
            PlatformType.CLAUDE_DESKTOP.value,
            PlatformType.CLAUDE_MEMORY.value,
        }:
            return "claude", False
        if detected_platform == PlatformType.GENERIC_JSON.value:
            return "generic", False

        # Unknown / unsupported - use legacy hand-rolled extraction.
        return "legacy", True

    # ------------------------------------------------------------------
    # Importer-based path
    # ------------------------------------------------------------------
    def _build_importer(self, platform_label: str, storage_path: Path):
        """Instantiate the correct importer for ``platform_label``."""
        if platform_label == "chatgpt":
            return ChatGPTImporter(storage_path)
        if platform_label == "cursor":
            return CursorImporter(storage_path)
        if platform_label == "claude":
            return ClaudeImporter(storage_path)
        if platform_label == "generic":
            return GenericImporter(storage_path)
        raise ValueError(f"Unknown importer label: {platform_label}")

    async def _import_with_importer(self, json_file: Path, platform_label: str) -> None:
        """Parse via importer, then persist via ``ConversationMemoryServer``.

        Importers normally save to their own staging directory in their own
        on-disk format. We reuse the parsing logic but route the resulting
        universal conversations through the memory server so the existing
        index, topics file and SQLite FTS database all stay consistent.
        """
        with tempfile.TemporaryDirectory(prefix="bulk-import-stage-") as tmpdir:
            importer = self._build_importer(platform_label, Path(tmpdir))

            try:
                result = importer.import_file(json_file)
            except Exception as exc:  # pragma: no cover - defensive
                msg = f"Importer error ({platform_label}): {exc}"
                self.errors.append(msg)
                print(msg)
                return

            # Surface importer-level errors to the operator.
            for err in result.errors:
                self.errors.append(f"[{platform_label}] {err}")

            staged_paths = self._collect_staged_files(Path(tmpdir))
            if not staged_paths:
                if result.conversations_imported == 0:
                    print(
                        "Importer produced no conversations; falling back to "
                        "legacy extraction."
                    )
                    self.fallback_used = True
                    self.format_used = "legacy"
                    await self._import_with_legacy(json_file)
                return

            total = len(staged_paths)
            print(f"Parsed {total} conversation(s) from {platform_label} format")

            for index, path in enumerate(staged_paths, start=1):
                await self._persist_staged_conversation(path, platform_label)
                self._maybe_print_progress(index, total)

    def _collect_staged_files(self, staging_dir: Path) -> List[Path]:
        """Return all conversation JSON files written by an importer."""
        return sorted(staging_dir.rglob("*.json"))

    async def _persist_staged_conversation(
        self, conversation_file: Path, platform_label: str
    ) -> None:
        """Load a staged universal conversation and forward to the memory server."""
        try:
            data = json.loads(conversation_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.failed_count += 1
            self.errors.append(
                f"Failed to read staged conversation {conversation_file}: {exc}"
            )
            return

        title = self._unique_title(data.get("title") or "Imported Conversation")
        content = data.get("content") or ""
        date_str = data.get("date") or datetime.now(timezone.utc).isoformat()

        if not content.strip():
            self.skipped_count += 1
            return

        await self._save_conversation(
            content=content,
            title=title,
            date=date_str,
            platform_label=platform_label,
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            tags=data.get("tags"),
            conversation_type=data.get("conversation_type"),
            custom_fields=data.get("custom_fields"),
        )

    # ------------------------------------------------------------------
    # Legacy hand-rolled path (preserved for backward compatibility)
    # ------------------------------------------------------------------
    async def _import_with_legacy(self, json_file: Path) -> None:
        """Original hand-rolled Claude export extraction logic."""
        try:
            print(f"Reading {json_file} (legacy extractor)...")

            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Error reading JSON file: {exc}"
            print(msg)
            self.errors.append(msg)
            return

        conversations = self._collect_legacy_conversations(data)
        if not conversations:
            print("No conversations found in the JSON file")
            return

        total = len(conversations)
        print(f"Starting legacy import of {total} conversations...")

        for index, conv in enumerate(conversations, start=1):
            try:
                conversation_data = self.extract_conversation_content(conv)
            except Exception as exc:  # pragma: no cover - defensive
                self.failed_count += 1
                self.errors.append(f"Error processing conversation {index}: {exc}")
                continue

            if not conversation_data:
                self.skipped_count += 1
                continue

            await self._save_conversation(
                content=conversation_data["content"],
                title=self._unique_title(conversation_data["title"]),
                date=conversation_data["date"],
                platform_label="legacy",
            )

            self._maybe_print_progress(index, total)

    def _collect_legacy_conversations(self, data: Any) -> List[Dict[str, Any]]:
        """Extract a list of conversations from common Claude export shapes."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("conversations", "chats", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return [data]
        return []

    def extract_conversation_content(
        self, conversation: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Extract content/title/date from a heterogeneous conversation dict."""
        content_fields = ["content", "text", "body", "conversation", "messages"]
        title_fields = ["title", "name", "subject", "conversation_title"]
        date_fields = ["date", "created_at", "timestamp", "created", "date_created"]

        content: Any = None
        for field in content_fields:
            if field in conversation and conversation[field]:
                content = conversation[field]
                break

        if isinstance(content, list):
            content = self._stringify_message_list(content)

        if not content:
            return None

        title = self._first_present(conversation, title_fields)
        if title is None:
            title = self._derive_title_from_content(str(content))

        date_str = self._first_present(conversation, date_fields)
        date_str = self._normalize_date(date_str)

        return {
            "content": str(content),
            "title": (
                str(title).strip()
                if title
                else f"Conversation {self.imported_count + 1}"
            ),
            "date": date_str,
        }

    @staticmethod
    def _first_present(mapping: Dict[str, Any], keys: List[str]) -> Optional[Any]:
        for key in keys:
            value = mapping.get(key)
            if value:
                return value
        return None

    @staticmethod
    def _stringify_message_list(messages: List[Any]) -> str:
        if messages and isinstance(messages[0], dict):
            parts: List[str] = []
            for msg in messages:
                role = msg.get("role", msg.get("sender", "unknown"))
                text = msg.get("content", msg.get("text", msg.get("message", "")))
                parts.append(f"**{str(role).title()}**: {text}")
            return "\n\n".join(parts)
        return "\n\n".join(str(item) for item in messages)

    @staticmethod
    def _derive_title_from_content(content: str) -> Optional[str]:
        for line in content.split("\n"):
            stripped = line.strip()
            if len(stripped) > 10 and not stripped.startswith("**"):
                return (stripped[:80] + "...") if len(stripped) > 80 else stripped
        return None

    @staticmethod
    def _normalize_date(date_value: Any) -> str:
        if date_value is None:
            return datetime.now(timezone.utc).isoformat()

        if isinstance(date_value, (int, float)):
            try:
                return datetime.fromtimestamp(
                    float(date_value), tz=timezone.utc
                ).isoformat()
            except (OverflowError, OSError, ValueError):
                return datetime.now(timezone.utc).isoformat()

        if isinstance(date_value, str):
            try:
                return datetime.fromisoformat(
                    date_value.replace("Z", "+00:00")
                ).isoformat()
            except ValueError:
                pass
            try:
                return datetime.strptime(date_value, "%Y-%m-%d %H:%M:%S").isoformat()
            except ValueError:
                return date_value  # Pass through unparseable strings.

        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Persistence + bookkeeping helpers
    # ------------------------------------------------------------------
    def _unique_title(self, base_title: str) -> str:
        original = base_title
        counter = 1
        while base_title in self.conversation_titles:
            base_title = f"{original} ({counter})"
            counter += 1
        self.conversation_titles.add(base_title)
        return base_title

    async def _save_conversation(
        self,
        content: str,
        title: str,
        date: str,
        platform_label: str,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        conversation_type: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist via the memory server, or simulate when ``dry_run``.

        Universal metadata fields (``session_id``/``user_id``/``tags``/
        ``conversation_type``/``custom_fields``) are forwarded so the memory
        server can persist and FTS-index them.
        """
        if self.dry_run:
            self.imported_count += 1
            self.platform_counts[platform_label] = (
                self.platform_counts.get(platform_label, 0) + 1
            )
            print(
                f"[DRY RUN] Would import via {platform_label}: {title[:60]} "
                f"(date={date}, len={len(content)})"
            )
            return

        try:
            assert self.memory_server is not None  # for mypy/readers
            result = await self.memory_server.add_conversation(
                content,
                title,
                date,
                session_id=session_id,
                user_id=user_id,
                tags=tags,
                conversation_type=conversation_type,
                custom_fields=custom_fields,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.failed_count += 1
            self.errors.append(f"Exception importing '{title}': {exc}")
            return

        if result.get("status") == "success":
            self.imported_count += 1
            self.platform_counts[platform_label] = (
                self.platform_counts.get(platform_label, 0) + 1
            )
        else:
            self.failed_count += 1
            self.errors.append(
                f"Failed to import '{title}': {result.get('message', 'Unknown error')}"
            )

    def _maybe_print_progress(self, processed: int, total: int) -> None:
        """Emit a periodic progress line (every ``progress_interval``)."""
        if total <= 0:
            return
        if processed == total or processed % self.progress_interval == 0:
            pct = (processed / total) * 100
            print(f"Progress: {processed}/{total} ({pct:.1f}%)")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def print_summary(self) -> None:
        print()
        print("=" * 60)
        print("IMPORT SUMMARY")
        print("=" * 60)

        if self.detection_result is not None:
            print(
                "Detected format: {p} (confidence={c:.2f})".format(
                    p=self.detection_result.get("platform"),
                    c=float(self.detection_result.get("confidence", 0.0)),
                )
            )
        if self.format_used:
            print(
                "Importer used: {f}{fb}".format(
                    f=self.format_used,
                    fb=" (legacy fallback)" if self.fallback_used else "",
                )
            )

        if self.dry_run:
            print(f"Would import: {self.imported_count}")
            print(f"Would skip:   {self.skipped_count}")
            print(f"Would fail:   {self.failed_count}")
        else:
            print(f"Imported: {self.imported_count}")
            print(f"Skipped:  {self.skipped_count}")
            print(f"Failed:   {self.failed_count}")

        total_processed = self.imported_count + self.skipped_count + self.failed_count
        if total_processed > 0:
            success_rate = (self.imported_count / total_processed) * 100
            print(f"Success rate: {success_rate:.1f}%")

        if self.platform_counts:
            print("Per-format counts:")
            for label, count in sorted(self.platform_counts.items()):
                print(f"  {label}: {count}")

        if self.errors:
            print(f"Errors encountered ({len(self.errors)}):")
            for index, err in enumerate(self.errors[:5], start=1):
                print(f"  {index}. {err}")
            if len(self.errors) > 5:
                print(f"  ... and {len(self.errors) - 5} more error(s)")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bulk import AI conversation exports with auto-detection of "
            "Claude / ChatGPT / Cursor / Generic formats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect format and dry-run (no writes)
  python bulk_import_enhanced.py /path/to/export.json --dry-run

  # Force ChatGPT importer
  python bulk_import_enhanced.py export.json --format chatgpt

  # Use legacy hand-rolled extractor explicitly
  python bulk_import_enhanced.py export.json --format generic
        """,
    )
    parser.add_argument(
        "json_file",
        help="Path to the conversation export JSON file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the import without writing any data",
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default="auto",
        help="Force a specific importer (default: auto-detect)",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        help=(
            "Minimum detection confidence required to use an importer in "
            "auto mode; below this the legacy extractor runs"
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=PROGRESS_REPORT_INTERVAL,
        help="Emit a progress line every N conversations (default: 25)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output",
    )
    return parser


async def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    json_path = Path(args.json_file)

    print("Claude Memory bulk import")
    print(f"Source: {json_path}")
    print(f"Mode:   {'DRY RUN' if args.dry_run else 'IMPORT'}")
    print(f"Format: {args.format}")
    print("-" * 60)

    importer = EnhancedBulkImporter(
        dry_run=args.dry_run,
        confidence_threshold=args.confidence_threshold,
        progress_interval=args.progress_interval,
    )

    try:
        await importer.run(json_path, requested_format=args.format)
    except KeyboardInterrupt:
        print("Import interrupted by user")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Unexpected error: {exc}")
        importer.print_summary()
        return 1

    importer.print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
