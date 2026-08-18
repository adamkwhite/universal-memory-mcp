#!/usr/bin/env python3
"""
Base exporter class for Universal Memory MCP.

Defines the interface and common functionality for all platform exporters.
Exporters are the inverse of importers: they read conversations from local
storage (in universal or legacy internal format) and write them out to a
platform-specific or universal JSON format.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Required fields on the universal conversation format.
# Mirrors create_universal_conversation in src/importers/base_importer.py.
UNIVERSAL_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "platform",
    "title",
    "content",
    "messages",
    "date",
)


@dataclass
class ExportResult:
    """Result of an export operation."""

    success: bool
    conversations_exported: int
    conversations_failed: int
    errors: list[str]
    output_path: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_processed(self) -> int:
        return self.conversations_exported + self.conversations_failed

    @property
    def success_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.conversations_exported / self.total_processed


@dataclass
class Filters:
    """Filtering options for exports.

    Attributes:
        date_from: Only include conversations on or after this datetime.
        date_to: Only include conversations on or before this datetime.
        platforms: Only include conversations matching one of these platform
            names (case-insensitive). ``None`` means no platform filter. Use
            ``"unknown"`` to match conversations with no platform field
            (legacy format).
        limit: Maximum number of conversations to export. ``None`` for
            unlimited.
    """

    date_from: datetime | None = None
    date_to: datetime | None = None
    platforms: list[str] | None = None
    limit: int | None = None

    def is_empty(self) -> bool:
        """Return True if no filters are configured."""
        return (
            self.date_from is None
            and self.date_to is None
            and not self.platforms
            and self.limit is None
        )


class BaseExporter(ABC):
    """Base class for all conversation exporters.

    Subclasses implement :meth:`export` (writes the output file) and
    :meth:`validate` (verifies the output file).
    """

    def __init__(self, source_storage_path: Path):
        """Initialize the exporter.

        Args:
            source_storage_path: Root storage path that contains the
                ``data/conversations`` (or legacy ``conversations``)
                directory tree with ``index.json`` and per-conversation JSON
                files. Equivalent to ``ConversationMemoryServer``'s
                ``storage_path``.
        """
        self.source_storage_path = Path(source_storage_path).expanduser()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def export(
        self,
        output_path: Path,
        filters: Filters | None = None,
    ) -> ExportResult:
        """Export conversations to ``output_path``.

        Args:
            output_path: Destination file path. Parent directory must be
                writable; it will be created if it does not exist.
            filters: Optional filtering options. ``None`` means export all
                conversations.

        Returns:
            ExportResult with statistics and any errors encountered.
        """

    @abstractmethod
    def validate(self, output_path: Path) -> dict[str, Any]:
        """Validate a previously exported file.

        Returns:
            ``{"valid": bool, "errors": list[str], "warnings": list[str],
            "conversation_count": int}``.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def load_conversations(self) -> list[dict[str, Any]]:
        """Load all on-disk conversations and normalize to universal format.

        Returns:
            List of conversations in universal internal format. Conversations
            stored in the legacy simple format (id/title/content/date/topics/
            created_at) are upgraded with sensible defaults so downstream
            exporters always see a uniform shape.
        """
        conversations_dir = self._resolve_conversations_dir()
        index_file = conversations_dir / "index.json"

        if not index_file.exists():
            self.logger.warning("No index.json found at %s", index_file)
            return []

        try:
            with open(index_file, encoding="utf-8") as f:
                index_data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.exception("Failed to read index.json: %s", exc)
            return []

        loaded: list[dict[str, Any]] = []
        for conv_info in index_data.get("conversations", []):
            rel_path = conv_info.get("file_path")
            if not rel_path:
                continue
            file_path = self.source_storage_path / rel_path
            if not file_path.exists():
                self.logger.debug("Skipping missing file: %s", file_path)
                continue
            try:
                with open(file_path, encoding="utf-8") as f:
                    conv = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self.logger.warning("Failed to load %s: %s", file_path, exc)
                continue
            loaded.append(self._normalize_to_universal(conv))

        return loaded

    def apply_filters(
        self,
        conversations: Iterable[dict[str, Any]],
        filters: Filters | None,
    ) -> list[dict[str, Any]]:
        """Apply filtering options to a list of conversations.

        Args:
            conversations: Conversations in universal internal format.
            filters: Filtering options. May be ``None`` (no-op).

        Returns:
            Filtered list. Order is preserved.
        """
        items = list(conversations)
        if filters is None or filters.is_empty():
            return items

        normalized_platforms: list[str] | None = None
        if filters.platforms:
            normalized_platforms = [p.lower() for p in filters.platforms]

        result: list[dict[str, Any]] = []
        for conv in items:
            if not self._matches_date_range(conv, filters.date_from, filters.date_to):
                continue
            if normalized_platforms is not None and not self._matches_platform(
                conv, normalized_platforms
            ):
                continue
            result.append(conv)
            if filters.limit is not None and len(result) >= filters.limit:
                break

        return result

    def write_json(
        self,
        output_path: Path,
        payload: Any,
    ) -> None:
        """Write a JSON payload to ``output_path`` atomically-ish.

        Creates parent directories as needed. Raises ``OSError`` on failure.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_conversations_dir(self) -> Path:
        """Locate the conversations directory (data/ or legacy layout)."""
        data_layout = self.source_storage_path / "data" / "conversations"
        if data_layout.exists():
            return data_layout
        legacy_layout = self.source_storage_path / "conversations"
        if legacy_layout.exists():
            return legacy_layout
        # Default to new layout for empty installations.
        return data_layout

    @staticmethod
    def _normalize_to_universal(
        conversation: dict[str, Any],
    ) -> dict[str, Any]:
        """Upgrade a legacy conversation into universal format if needed.

        Universal-format conversations are returned untouched (other than
        ensuring required fields exist). Legacy conversations gain default
        values for ``platform``, ``messages``, ``model``, ``last_updated``,
        ``session_context``, and ``import_metadata``.
        """
        conv = dict(conversation)  # shallow copy; do not mutate caller

        conv.setdefault("platform", "unknown")
        conv.setdefault("model", "unknown")
        conv.setdefault("messages", [])
        conv.setdefault("topics", [])
        conv.setdefault("session_context", {})
        conv.setdefault("import_metadata", {})
        conv.setdefault("last_updated", conv.get("date", ""))
        conv.setdefault("created_at", conv.get("date", ""))

        # If the conversation has content but no messages, synthesize a
        # single combined message so downstream consumers always see at
        # least one entry.
        if not conv["messages"] and conv.get("content"):
            conv["messages"] = [
                {
                    "id": f"msg_{conv.get('id', 'legacy')}",
                    "role": "assistant",
                    "content": conv["content"],
                    "timestamp": conv.get("date", ""),
                    "metadata": {"synthetic": True, "source": "legacy_upgrade"},
                }
            ]

        return conv

    @staticmethod
    def _parse_iso(date_str: str) -> datetime | None:
        """Parse an ISO date string, returning None on failure."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _matches_date_range(
        cls,
        conversation: dict[str, Any],
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> bool:
        """Return True if conversation's date is inside [from, to]."""
        if date_from is None and date_to is None:
            return True

        conv_date = cls._parse_iso(conversation.get("date", ""))
        if conv_date is None:
            # Conversations with unparseable dates are excluded when
            # any date filter is active.
            return False

        # Strip timezone for comparison if needed (compare naive-vs-naive)
        if date_from is not None:
            df = cls._strip_tz_for_compare(date_from, conv_date)
            cd = cls._strip_tz_for_compare(conv_date, date_from)
            if cd < df:
                return False
        if date_to is not None:
            dt = cls._strip_tz_for_compare(date_to, conv_date)
            cd = cls._strip_tz_for_compare(conv_date, date_to)
            if cd > dt:
                return False
        return True

    @staticmethod
    def _strip_tz_for_compare(target: datetime, reference: datetime) -> datetime:
        """Drop tzinfo from ``target`` if ``reference`` is naive."""
        if reference.tzinfo is None and target.tzinfo is not None:
            return target.replace(tzinfo=None)
        return target

    @staticmethod
    def _matches_platform(conversation: dict[str, Any], platforms: list[str]) -> bool:
        """Return True if conversation's platform matches one of ``platforms``."""
        platform = str(conversation.get("platform", "unknown")).lower()
        return platform in platforms
