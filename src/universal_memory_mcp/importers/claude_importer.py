#!/usr/bin/env python3
"""
Claude conversation importer for Universal Memory MCP.

Handles various Claude export formats and converts to universal conversation format.
Supports Claude web interface exports, Claude Desktop exports, and existing Claude Memory format.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..validators import validate_import_file_path
from .base_importer import BaseImporter, ImportResult

logger = logging.getLogger(__name__)


class ClaudeImporter(BaseImporter):
    """Importer for Claude conversation exports in various formats."""

    def __init__(self, storage_path: Path):
        super().__init__(storage_path, "claude")
        self.logger = logging.getLogger(f"{__name__}.ClaudeImporter")

    def get_supported_formats(self) -> list[str]:
        """Return list of supported file formats."""
        return [".json", ".md", ".txt"]

    def import_file(self, file_path: Path) -> ImportResult:
        """
        Import conversations from a Claude export file.

        Supports multiple Claude formats:
        - Claude Memory format (existing)
        - Claude web interface markdown
        - Claude Desktop MCP format
        """
        try:
            if not file_path.exists():
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=[f"File not found: {file_path}"],
                    imported_ids=[],
                    metadata={},
                )

            file_path = validate_import_file_path(file_path)

            # Determine format based on file extension
            extension = file_path.suffix.lower()

            if extension == ".json":
                return self._import_json_format(file_path)
            elif extension in [".md", ".txt"]:
                return self._import_text_format(file_path)
            else:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=[f"Unsupported file format: {extension}"],
                    imported_ids=[],
                    metadata={},
                )

        except Exception as e:  # noqa: BLE001  # top-level import boundary: report failure via ImportResult instead of crashing the batch run
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_json_format(self, file_path: Path) -> ImportResult:
        """Import JSON format Claude files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # Detect specific Claude JSON format
            if self._is_claude_memory_format(data):
                return self._import_claude_memory_format(file_path, data)
            elif self._is_claude_desktop_format(data):
                return self._import_claude_desktop_format(file_path, data)
            else:
                # Try to parse as generic Claude conversation
                return self._import_generic_claude_json(file_path, data)

        except json.JSONDecodeError as e:
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Invalid JSON format: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_text_format(self, file_path: Path) -> ImportResult:
        """Import text/markdown format Claude files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Parse markdown conversation
            universal_conv = self._parse_markdown_conversation(content, file_path)

            if self._validate_conversation(universal_conv):
                self._save_conversation(universal_conv)

                return ImportResult(
                    success=True,
                    conversations_imported=1,
                    conversations_failed=0,
                    errors=[],
                    imported_ids=[universal_conv["id"]],
                    metadata={
                        "source_file": str(file_path),
                        "format": "claude_markdown",
                        "platform": "claude",
                    },
                )
            else:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["Failed to parse markdown conversation"],
                    imported_ids=[],
                    metadata={},
                )

        except Exception as e:  # noqa: BLE001  # best-effort text parse: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Text import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_claude_memory_format(self, file_path: Path, data: dict[str, Any]) -> ImportResult:
        """Import existing Claude Memory format - already in universal format."""
        try:
            # This is already our format, but we may want to update it
            if self._validate_conversation(data):
                # File is already in correct location, just validate
                return ImportResult(
                    success=True,
                    conversations_imported=1,
                    conversations_failed=0,
                    errors=[],
                    imported_ids=[data["id"]],
                    metadata={
                        "source_file": str(file_path),
                        "format": "claude_memory",
                        "already_imported": True,
                        "platform": "claude",
                    },
                )
            else:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["Invalid Claude Memory format"],
                    imported_ids=[],
                    metadata={},
                )

        except Exception as e:  # noqa: BLE001  # top-level format-branch boundary: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Claude Memory import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_claude_desktop_format(self, file_path: Path, data: dict[str, Any]) -> ImportResult:
        """Import Claude Desktop MCP format."""
        try:
            universal_conv = self.parse_conversation(data)

            if self._validate_conversation(universal_conv):
                self._save_conversation(universal_conv)

                return ImportResult(
                    success=True,
                    conversations_imported=1,
                    conversations_failed=0,
                    errors=[],
                    imported_ids=[universal_conv["id"]],
                    metadata={
                        "source_file": str(file_path),
                        "format": "claude_desktop",
                        "platform": "claude",
                    },
                )
            else:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["Invalid conversation format after parsing"],
                    imported_ids=[],
                    metadata={},
                )

        except Exception as e:  # noqa: BLE001  # top-level format-branch boundary: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Claude Desktop import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_generic_claude_json(self, file_path: Path, data: dict[str, Any]) -> ImportResult:
        """Import generic Claude JSON format."""
        try:
            universal_conv = self.parse_conversation(data)

            if self._validate_conversation(universal_conv):
                self._save_conversation(universal_conv)

                return ImportResult(
                    success=True,
                    conversations_imported=1,
                    conversations_failed=0,
                    errors=[],
                    imported_ids=[universal_conv["id"]],
                    metadata={
                        "source_file": str(file_path),
                        "format": "claude_generic_json",
                        "platform": "claude",
                    },
                )
            else:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["Invalid conversation format after parsing"],
                    imported_ids=[],
                    metadata={},
                )

        except Exception as e:  # noqa: BLE001  # top-level format-branch boundary: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Generic Claude import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def parse_conversation(self, raw_data: Any) -> dict[str, Any]:
        """
        Parse raw Claude conversation data into universal format.

        Handles various Claude formats and converts to standardized structure.
        """
        if isinstance(raw_data, str):
            # Text format - parse as markdown conversation
            return self._parse_markdown_conversation(raw_data)
        elif isinstance(raw_data, dict):
            # JSON format - determine specific structure
            if self._is_claude_memory_format(raw_data):
                return raw_data  # Already in universal format
            else:
                return self._parse_claude_json(raw_data)
        else:
            raise TypeError("Claude conversation data must be string or dictionary")

    def _parse_claude_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse Claude JSON conversation data."""
        # Extract basic information
        platform_id = data.get("id", "")
        title = data.get("title", "Claude Conversation")

        # Parse timestamps
        date_str = data.get("date", data.get("created_at", data.get("timestamp", "")))
        date = self._parse_timestamp(date_str) if date_str else datetime.now()

        # Handle different message structures
        content = data.get("content", "")
        messages = data.get("messages", [])

        # If no messages but has content, create messages from content
        if not messages and content:
            messages = self._extract_messages_from_content(content)

        # If no content but has messages, generate content from messages
        if not content and messages:
            content = self._combine_messages_to_content(messages)

        # Extract model information
        model = data.get("model", "claude-3.5-sonnet")

        # Create session context
        session_context = {
            "claude_variant": self._detect_claude_variant(data),
            "original_format": "claude_json",
        }

        # Universal metadata extraction.
        session_id = data.get("session_id") or data.get("conversation_id") or platform_id or None
        user_id = data.get("user_id") or data.get("account_id") or None
        tags = self._extract_claude_tags(data, session_context["claude_variant"])
        conversation_type = self._classify_claude_conversation_type(data, content)
        custom_fields = self._extract_claude_custom_fields(data)

        # Create universal conversation
        return self.create_universal_conversation(
            platform_id=platform_id or f"claude_{int(date.timestamp())}",
            title=title,
            content=content,
            messages=messages,
            date=date,
            model=model,
            session_context=session_context,
            metadata={
                "original_data_keys": list(data.keys()),
                "claude_variant": session_context["claude_variant"],
            },
            session_id=session_id,
            user_id=user_id,
            tags=tags,
            conversation_type=conversation_type,
            custom_fields=custom_fields,
        )

    def _extract_claude_tags(self, data: dict[str, Any], claude_variant: str) -> list[str]:
        """Build tag list for a Claude conversation (variant + caller-supplied)."""
        tags: list[str] = []
        if claude_variant:
            tags.append(f"variant:{claude_variant}")
        explicit = data.get("tags")
        if isinstance(explicit, list):
            tags.extend(str(t) for t in explicit if t)
        return tags

    def _classify_claude_conversation_type(self, data: dict[str, Any], content: str) -> str:
        """Classify a Claude conversation as chat/code/analysis/etc."""
        explicit = data.get("conversation_type")
        if isinstance(explicit, str) and explicit:
            return explicit
        if content and content.count("```") >= 4:
            return "code"
        return "chat"

    def _extract_claude_custom_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Capture optional Claude extras into custom_fields."""
        custom: dict[str, Any] = {}
        for key in ("project_id", "organization_id", "workspace_id"):
            value = data.get(key)
            if value is not None:
                custom[key] = value
        extra = data.get("custom_fields")
        if isinstance(extra, dict):
            custom.update(extra)
        return custom

    def _parse_markdown_conversation(
        self, content: str, file_path: Path | None = None
    ) -> dict[str, Any]:
        """Parse markdown format Claude conversation."""
        # Extract title from first line or filename
        lines = content.strip().split("\n")
        title = "Claude Conversation"

        if lines and lines[0].startswith("#"):
            title = lines[0].strip("# ").strip()
        elif file_path:
            title = file_path.stem.replace("_", " ").title()

        # Extract messages using pattern matching
        messages = self._extract_messages_from_markdown(content)

        # Generate conversation ID and date
        date = datetime.now()
        platform_id = f"claude_md_{int(date.timestamp())}"

        # Create session context
        session_context = {
            "claude_variant": "web_interface",
            "original_format": "markdown",
        }

        # Create universal conversation
        return self.create_universal_conversation(
            platform_id=platform_id,
            title=title,
            content=content,
            messages=messages,
            date=date,
            model="claude-3.5-sonnet",
            session_context=session_context,
            metadata={"source_type": "markdown", "line_count": len(lines)},
        )

    def _extract_messages_from_markdown(self, content: str) -> list[dict[str, Any]]:
        """Extract individual messages from markdown conversation."""
        messages = []

        # Common Claude markdown patterns
        patterns = [
            r"\*\*Human\*\*:\s*(.*?)(?=\*\*Claude\*\*:|\*\*Human\*\*:|$)",
            r"\*\*Claude\*\*:\s*(.*?)(?=\*\*Human\*\*:|\*\*Claude\*\*:|$)",
            r"Human:\s*(.*?)(?=Claude:|Human:|$)",
            r"Claude:\s*(.*?)(?=Human:|Claude:|$)",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
            for match in matches:
                role_text = match.group(0)
                message_content = match.group(1).strip()

                if not message_content:
                    continue

                # Determine role
                if "human" in role_text.lower():
                    role = "user"
                elif "claude" in role_text.lower():
                    role = "assistant"
                else:
                    role = "unknown"

                message = self._create_message(
                    role=role,
                    content=message_content,
                    metadata={"source": "markdown_extraction"},
                )
                messages.append(message)

        # Sort messages by their position in the text
        return messages

    def _extract_messages_from_content(self, content: str) -> list[dict[str, Any]]:
        """Extract messages from a combined content string."""
        # Similar to markdown extraction but more flexible
        return self._extract_messages_from_markdown(content)

    def _is_claude_memory_format(self, data: dict[str, Any]) -> bool:
        """Check if data is in Claude Memory format."""
        required_fields = ["id", "title", "content", "date", "topics", "created_at"]
        has_required = sum(1 for field in required_fields if field in data)

        # Check for our specific ID format
        if (
            "id" in data
            and isinstance(data["id"], str)
            and data["id"].startswith("conv_")
            and len(data["id"]) > 15
        ):
            has_required += 1

        return has_required >= 5

    def _is_claude_desktop_format(self, data: dict[str, Any]) -> bool:
        """Check if data is in Claude Desktop MCP format."""
        # Look for MCP-specific indicators
        content_str = json.dumps(data).lower()
        mcp_indicators = ["mcp", "desktop", "anthropic"]

        indicator_count = sum(1 for indicator in mcp_indicators if indicator in content_str)

        # Also check for conversation structure
        if self._has_conversation_structure(data):
            indicator_count += 1

        return indicator_count >= 2

    def _has_conversation_structure(self, data: dict[str, Any]) -> bool:
        """Check if data has general conversation structure."""
        conversation_fields = [
            "messages",
            "content",
            "conversation",
            "chat",
            "dialogue",
        ]
        text_fields = ["text", "content", "message", "response"]

        has_conversation = any(field in data for field in conversation_fields)
        has_text = any(field in data for field in text_fields)

        return has_conversation or has_text

    def _detect_claude_variant(self, data: dict[str, Any]) -> str:
        """Detect which Claude variant this conversation came from."""
        content_str = json.dumps(data).lower()

        if "desktop" in content_str or "mcp" in content_str:
            return "claude_desktop"
        elif "web" in content_str or "browser" in content_str:
            return "claude_web"
        elif self._is_claude_memory_format(data):
            return "claude_memory"
        else:
            return "claude_generic"

    def _save_conversation(self, conversation: dict[str, Any]) -> Path:
        """Save a conversation to the storage directory."""
        # Create date-based subdirectory
        date = datetime.fromisoformat(conversation["date"].replace("Z", "+00:00"))
        year_folder = self.storage_path / str(date.year)
        month_folder = year_folder / f"{date.month:02d}-{date.strftime('%B').lower()}"
        month_folder.mkdir(parents=True, exist_ok=True)

        # Save conversation file
        filename = f"{conversation['id']}.json"
        file_path = month_folder / filename

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)

        self.logger.info("Saved Claude conversation to: %s", file_path)
        return file_path

    def _extract_topics(self, content: str) -> list[str]:
        """Override base topic extraction for Claude-specific patterns."""
        topics = super()._extract_topics(content)

        # Add Claude-specific topic indicators
        content_lower = content.lower()

        # Claude-specific terms
        claude_topics = [
            "claude",
            "anthropic",
            "ai assistant",
            "conversation",
            "natural language",
            "reasoning",
            "analysis",
            "creative writing",
        ]

        for topic in claude_topics:
            if topic in content_lower and topic not in topics:
                topics.append(topic)

        # Always include platform identifier
        if "claude" not in topics:
            topics.append("claude")

        return topics[:10]  # Limit to 10 topics


# Example usage and testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        storage_path = Path("./test_imports")

        importer = ClaudeImporter(storage_path)
        result = importer.import_file(file_path)

        print("Import Result:")
        print(f"  Success: {result.success}")
        print(f"  Imported: {result.conversations_imported}")
        print(f"  Failed: {result.conversations_failed}")
        print(f"  Success Rate: {result.success_rate:.2%}")

        if result.errors:
            print(f"  Errors: {result.errors}")

        if result.imported_ids:
            print(f"  Imported IDs: {result.imported_ids}")

        print(f"  Metadata: {result.metadata}")
    else:
        print("Usage: python claude_importer.py <claude_export.json|conversation.md>")
