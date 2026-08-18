#!/usr/bin/env python3
"""
ChatGPT-format exporter for Universal Memory MCP.

Converts conversations stored in universal internal format back into the
ChatGPT (OpenAI) export shape used by ``src/schemas/chatgpt_schema.py``.

Notes
-----
The ChatGPT export format is a JSON array of conversation objects whose
messages are stored under a ``mapping`` dict keyed by node id. We
reconstruct a linear parent->child chain from the universal ``messages``
list. Round-tripping through the universal format is lossy:

* Tree branching present in real ChatGPT exports is collapsed into a
  single linear chain.
* Per-message metadata such as model slug, request id, and tool call
  details is not stored in our universal format and therefore cannot be
  reconstructed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .base_exporter import BaseExporter, ExportResult, Filters


def _validate_chatgpt_export(data):
    """Lazy proxy to ``schemas.chatgpt_schema.validate_chatgpt_export``.

    Resolving the import inside the call (rather than at module load) keeps
    static analysis from getting confused about whether the schemas module
    is reached via ``src.schemas`` or just ``schemas`` (depending on how
    the surrounding package was imported).
    """
    import importlib

    for mod_name in ("schemas.chatgpt_schema", "src.schemas.chatgpt_schema"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:  # pragma: no cover - import wiring fallback
            continue
        return mod.validate_chatgpt_export(data)
    raise ImportError(  # pragma: no cover - both import paths failed
        "Could not locate schemas.chatgpt_schema"
    )


logger = logging.getLogger(__name__)


# ChatGPT supports these author roles in its export schema.
_VALID_CHATGPT_ROLES = ("user", "assistant", "system")


class ChatgptExporter(BaseExporter):
    """Exports conversations to ChatGPT export-compatible JSON."""

    def export(
        self,
        output_path: Path,
        filters: Filters | None = None,
    ) -> ExportResult:
        """Write conversations as a ChatGPT-format JSON array."""
        output_path = Path(output_path)
        try:
            conversations = self.load_conversations()
        except Exception as exc:  # noqa: BLE001 - defensive boundary
            return ExportResult(
                success=False,
                conversations_exported=0,
                conversations_failed=0,
                errors=[f"Failed to load source conversations: {exc}"],
                output_path=None,
                metadata={"format": "chatgpt"},
            )

        filtered = self.apply_filters(conversations, filters)

        chatgpt_array: list[dict[str, Any]] = []
        errors: list[str] = []
        failed = 0
        for conv in filtered:
            try:
                chatgpt_array.append(self._to_chatgpt(conv))
            except Exception as exc:  # noqa: BLE001 - per-conv resilience
                failed += 1
                errors.append(f"Failed to convert {conv.get('id', '<unknown>')}: {exc}")

        try:
            self.write_json(output_path, chatgpt_array)
        except OSError as exc:
            return ExportResult(
                success=False,
                conversations_exported=0,
                conversations_failed=len(filtered),
                errors=[f"Failed to write {output_path}: {exc}"],
                output_path=None,
                metadata={"format": "chatgpt"},
            )

        self.logger.info(
            "Exported %d conversations to %s in ChatGPT format",
            len(chatgpt_array),
            output_path,
        )
        return ExportResult(
            success=len(chatgpt_array) > 0 or len(filtered) == 0,
            conversations_exported=len(chatgpt_array),
            conversations_failed=failed,
            errors=errors,
            output_path=str(output_path),
            metadata={
                "format": "chatgpt",
                "source_total": len(conversations),
                "filtered_total": len(filtered),
            },
        )

    def validate(self, output_path: Path) -> dict[str, Any]:
        """Validate the exported file against the ChatGPT JSON schema."""
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
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "valid": False,
                "errors": [f"Failed to read/parse {output_path}: {exc}"],
                "warnings": [],
                "conversation_count": 0,
            }

        return _validate_chatgpt_export(data)

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _to_chatgpt(self, conv: dict[str, Any]) -> dict[str, Any]:
        """Convert one universal conversation into ChatGPT export shape."""
        conv_id = conv.get("platform_id") or conv.get("id") or str(uuid.uuid4())
        title = conv.get("title") or "Untitled Conversation"
        create_time = self._iso_to_epoch(conv.get("date"))
        update_time = self._iso_to_epoch(conv.get("last_updated") or conv.get("date"))

        mapping, current_node = self._build_mapping(conv)

        return {
            "title": title,
            "create_time": create_time,
            "update_time": update_time,
            "conversation_id": conv_id,
            "id": conv_id,
            "mapping": mapping,
            "moderation_results": [],
            "current_node": current_node,
            "default_model_slug": conv.get("model") or "unknown",
        }

    def _build_mapping(self, conv: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Build a ChatGPT-style ``mapping`` dict from universal messages.

        Returns:
            (mapping, current_node_id).
        """
        messages = conv.get("messages") or []

        # The schema requires a non-empty mapping with at least one node.
        # Insert a synthetic root node so we always have something to anchor.
        root_id = f"root_{conv.get('id', uuid.uuid4().hex[:8])}"
        mapping: dict[str, Any] = {
            root_id: {
                "id": root_id,
                "message": None,
                "parent": None,
                "children": [],
            }
        }

        previous_id: str = root_id
        last_real_id: str | None = None
        for idx, msg in enumerate(messages):
            node_id = msg.get("id") or f"node_{idx}_{uuid.uuid4().hex[:8]}"
            # Avoid collisions with the root node id.
            if node_id == root_id:
                node_id = f"{node_id}_msg"
            role = (msg.get("role") or "assistant").lower()
            if role not in _VALID_CHATGPT_ROLES:
                # ChatGPT schema only accepts user/assistant/system. Map
                # everything else to "assistant" to stay valid.
                role = "assistant"
            content_text = msg.get("content") or ""
            timestamp = msg.get("timestamp") or conv.get("date") or ""
            create_time = self._iso_to_epoch(timestamp)

            chatgpt_message: dict[str, Any] = {
                "id": node_id,
                "author": {
                    "role": role,
                    "name": None,
                    "metadata": {},
                },
                "content": {
                    "content_type": "text",
                    "parts": [content_text if content_text else ""],
                },
                "create_time": create_time,
                "update_time": create_time,
                "status": "finished_successfully",
                "end_turn": role == "assistant",
                "weight": 1.0,
                "metadata": dict(msg.get("metadata") or {}),
                "recipient": "all",
                "channel": None,
            }

            mapping[node_id] = {
                "id": node_id,
                "message": chatgpt_message,
                "parent": previous_id,
                "children": [],
            }
            mapping[previous_id]["children"].append(node_id)
            previous_id = node_id
            last_real_id = node_id

        return mapping, last_real_id or root_id

    @staticmethod
    def _iso_to_epoch(date_value: Any) -> float:
        """Convert an ISO datetime string (or epoch number) to epoch seconds.

        Returns 0.0 for empty / unparseable input.
        """
        if date_value is None or date_value == "":
            return 0.0
        if isinstance(date_value, (int, float)):
            return float(date_value)
        try:
            text = str(date_value).replace("Z", "+00:00")
            return datetime.fromisoformat(text).timestamp()
        except (ValueError, TypeError, OSError):
            return 0.0
