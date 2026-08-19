#!/usr/bin/env python3
"""
JSON exporter for Universal Memory MCP.

Exports stored conversations to a single JSON file in the universal
internal format. This is essentially an "identity" export -- it preserves
the structure used by the importer pipeline -- with optional filtering.

Output shape:

.. code-block:: json

    {
        "format": "universal",
        "format_version": "1.0",
        "exported_at": "2026-04-18T12:34:56",
        "source_storage_path": "/home/user/claude-memory",
        "conversation_count": 42,
        "filters_applied": {...},
        "conversations": [ {...universal conversation...}, ... ]
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .base_exporter import (
    UNIVERSAL_REQUIRED_FIELDS,
    BaseExporter,
    ExportResult,
    Filters,
)

logger = logging.getLogger(__name__)


# Bumped whenever the export envelope structure changes.
JSON_EXPORT_FORMAT_VERSION = "1.0"


class JsonExporter(BaseExporter):
    """Exports conversations to universal-format JSON."""

    def export(
        self,
        output_path: Path,
        filters: Filters | None = None,
    ) -> ExportResult:
        """Write all (filtered) conversations to ``output_path`` as JSON."""
        output_path = Path(output_path)
        try:
            conversations = self.load_conversations()
        except Exception as exc:  # noqa: BLE001  # defensive boundary
            return ExportResult(
                success=False,
                conversations_exported=0,
                conversations_failed=0,
                errors=[f"Failed to load source conversations: {exc}"],
                output_path=None,
                metadata={"format": "universal"},
            )

        filtered = self.apply_filters(conversations, filters)

        envelope = self._build_envelope(filtered, filters)

        try:
            self.write_json(output_path, envelope)
        except OSError as exc:
            return ExportResult(
                success=False,
                conversations_exported=0,
                conversations_failed=len(filtered),
                errors=[f"Failed to write {output_path}: {exc}"],
                output_path=None,
                metadata={"format": "universal"},
            )

        self.logger.info("Exported %d conversations to %s", len(filtered), output_path)
        return ExportResult(
            success=True,
            conversations_exported=len(filtered),
            conversations_failed=0,
            errors=[],
            output_path=str(output_path),
            metadata={
                "format": "universal",
                "format_version": JSON_EXPORT_FORMAT_VERSION,
                "source_total": len(conversations),
            },
        )

    def validate(self, output_path: Path) -> dict[str, Any]:
        """Re-parse exported file and verify universal-format compliance."""
        output_path = Path(output_path)
        if not output_path.exists():
            return {
                "valid": False,
                "errors": [f"Output file not found: {output_path}"],
                "warnings": [],
                "conversation_count": 0,
            }

        try:
            with open(output_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "valid": False,
                "errors": [f"Failed to read/parse {output_path}: {exc}"],
                "warnings": [],
                "conversation_count": 0,
            }

        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(payload, dict):
            return {
                "valid": False,
                "errors": ["Top-level payload must be a JSON object"],
                "warnings": [],
                "conversation_count": 0,
            }

        if payload.get("format") != "universal":
            warnings.append(
                f"Unexpected format field: {payload.get('format')!r} (expected 'universal')"
            )

        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            errors.append("'conversations' must be a list")
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "conversation_count": 0,
            }

        errors.extend(self._validate_conversation_entries(conversations))

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "conversation_count": len(conversations),
        }

    @staticmethod
    def _validate_conversation_entries(conversations: list[Any]) -> list[str]:
        """Per-conversation universal-format checks. Returns error strings."""
        errors: list[str] = []
        for idx, conv in enumerate(conversations):
            if not isinstance(conv, dict):
                errors.append(f"Conversation {idx} is not an object")
                continue
            for field_name in UNIVERSAL_REQUIRED_FIELDS:
                if field_name not in conv:
                    errors.append(f"Conversation {idx} missing required field '{field_name}'")
            if "messages" in conv and not isinstance(conv["messages"], list):
                errors.append(f"Conversation {idx} 'messages' must be a list")
        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_envelope(
        self,
        conversations: list[dict[str, Any]],
        filters: Filters | None,
    ) -> dict[str, Any]:
        return {
            "format": "universal",
            "format_version": JSON_EXPORT_FORMAT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "source_storage_path": str(self.source_storage_path),
            "conversation_count": len(conversations),
            "filters_applied": _serialize_filters(filters),
            "conversations": conversations,
        }


def _serialize_filters(filters: Filters | None) -> dict[str, Any]:
    """Serialize a Filters dataclass into JSON-safe dict."""
    if filters is None or filters.is_empty():
        return {}
    return {
        "date_from": (filters.date_from.isoformat() if filters.date_from else None),
        "date_to": (filters.date_to.isoformat() if filters.date_to else None),
        "platforms": list(filters.platforms) if filters.platforms else None,
        "limit": filters.limit,
    }
