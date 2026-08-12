#!/usr/bin/env python3
"""
Generic conversation importer for Universal Memory MCP.

Handles custom formats and unknown conversation exports with flexible parsing.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from validators import validate_import_file_path

from .base_importer import BaseImporter, ImportResult

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CONVERSATION_TITLE = "Generic Conversation"


class GenericImporter(BaseImporter):
    """Importer for generic and custom conversation formats."""

    def __init__(self, storage_path: Path):
        super().__init__(storage_path, "generic")
        self.logger = logging.getLogger(f"{__name__}.GenericImporter")

    def get_supported_formats(self) -> list[str]:
        """Return list of supported file formats."""
        return [".json", ".md", ".txt", ".csv", ".xml"]

    def import_file(self, file_path: Path) -> ImportResult:
        """
        Import conversations from a generic file format.

        Attempts to parse various formats and extract conversation-like data.
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
            elif extension == ".csv":
                return self._import_csv_format(file_path)
            elif extension == ".xml":
                return self._import_xml_format(file_path)
            else:
                # Try to parse as text by default
                return self._import_text_format(file_path)

        except Exception as e:  # noqa: BLE001 - top-level import boundary: report failure via ImportResult instead of crashing the batch run
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_json_format(self, file_path: Path) -> ImportResult:
        """Import generic JSON format files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # Try different parsing strategies
            conversations = []

            if isinstance(data, list):
                # Array of conversations or messages
                conversations = self._parse_json_array(data)
            elif isinstance(data, dict):
                # Single conversation or structured object
                conversations = self._parse_json_object(data)
            else:
                # Unexpected format
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["Unsupported JSON structure"],
                    imported_ids=[],
                    metadata={},
                )

            # Process and save conversations
            return self._save_conversations(conversations, file_path, "generic_json")

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
        """Import text/markdown format files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Parse text conversation
            conversations = self._parse_text_content(content, file_path)

            return self._save_conversations(conversations, file_path, "generic_text")

        except Exception as e:  # noqa: BLE001 - best-effort text parse: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Text import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_csv_format(self, file_path: Path) -> ImportResult:
        """Import CSV format files."""
        try:
            import csv

            conversations = []

            with open(file_path, encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)

                # Group rows by conversation if possible
                rows = list(csv_reader)

                # Handle empty CSV files
                if not rows:
                    return ImportResult(
                        success=False,
                        conversations_imported=0,
                        conversations_failed=1,
                        errors=["CSV file is empty or has no data rows"],
                        imported_ids=[],
                        metadata={
                            "source_file": str(file_path),
                            "format_type": "generic_csv",
                            "platform": "generic",
                        },
                    )

                conversation_data = self._parse_csv_rows(rows, file_path)

                if conversation_data:
                    conversations.append(conversation_data)

            # If no conversations were created but rows existed, treat as failure
            if not conversations:
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["No valid conversation data found in CSV"],
                    imported_ids=[],
                    metadata={
                        "source_file": str(file_path),
                        "format_type": "generic_csv",
                        "platform": "generic",
                    },
                )

            return self._save_conversations(conversations, file_path, "generic_csv")

        except Exception as e:  # noqa: BLE001 - best-effort CSV parse: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"CSV import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def _import_xml_format(self, file_path: Path) -> ImportResult:
        """Import XML format files."""
        try:
            import xml.etree.ElementTree as ET

            tree = ET.parse(file_path)
            root = tree.getroot()

            conversations = self._parse_xml_tree(root)

            return self._save_conversations(conversations, file_path, "generic_xml")

        except Exception as e:  # noqa: BLE001 - best-effort XML parse: report failure via ImportResult instead of crashing
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"XML import failed: {str(e)}"],
                imported_ids=[],
                metadata={},
            )

    def parse_conversation(self, raw_data: Any) -> dict[str, Any]:
        """
        Parse raw generic conversation data into universal format.

        Uses heuristics to identify conversation elements from various formats.
        """
        if isinstance(raw_data, str):
            return self._parse_text_as_conversation(raw_data)
        elif isinstance(raw_data, dict):
            return self._parse_dict_as_conversation(raw_data)
        elif isinstance(raw_data, list):
            return self._parse_list_as_conversation(raw_data)
        else:
            raise TypeError("Generic conversation data must be string, dict, or list")

    def _parse_json_array(self, data: list[Any]) -> list[dict[str, Any]]:
        """Parse JSON array - could be conversations or messages."""
        conversations = []

        # Check if items look like individual conversations
        if data and isinstance(data[0], dict) and self._looks_like_conversation(data[0]):
            # Array of conversations
            for item in data:
                try:
                    conv = self.parse_conversation(item)
                    conversations.append(conv)
                except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
                    self.logger.warning(f"Failed to parse conversation item: {e}")
        else:
            # Array of messages or other data - combine into single conversation
            try:
                combined_conv = self._parse_list_as_conversation(data)
                conversations.append(combined_conv)
            except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
                self.logger.warning(f"Failed to combine array into conversation: {e}")

        return conversations

    def _parse_json_object(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse JSON object - single conversation or structured data."""
        conversations = []

        if self._looks_like_conversation(data):
            conversations = self._parse_single_conversation(data)
        else:
            conversations = self._parse_nested_conversations(data)

        # If no conversations found, treat entire object as single conversation
        if not conversations:
            conversations = self._parse_fallback_conversation(data)

        return conversations

    def _parse_single_conversation(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse data as single conversation."""
        try:
            conv = self.parse_conversation(data)
            return [conv]
        except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
            self.logger.warning("Failed to parse conversation object: %s", e)
            return []

    def _parse_nested_conversations(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse nested conversation arrays within object."""
        conversations = []

        for value in data.values():
            if self._is_valid_conversation_array(value):
                conversations.extend(self._process_conversation_array(value))

        return conversations

    def _is_valid_conversation_array(self, value: Any) -> bool:
        """Check if value is a valid conversation array."""
        if not isinstance(value, list) or not value:
            return False

        first_item = value[0] if isinstance(value[0], dict) else {}
        return self._looks_like_conversation(first_item)

    def _process_conversation_array(self, items: list[Any]) -> list[dict[str, Any]]:
        """Process array of conversation items."""
        conversations = []

        for item in items:
            try:
                conv = self.parse_conversation(item)
                conversations.append(conv)
            except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
                self.logger.warning("Failed to parse nested conversation: %s", e)

        return conversations

    def _parse_fallback_conversation(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse object as single conversation fallback."""
        try:
            conv = self._parse_dict_as_conversation(data)
            return [conv]
        except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
            self.logger.warning("Failed to parse object as conversation: %s", e)
            return []

    def _parse_text_content(self, content: str, file_path: Path) -> list[dict[str, Any]]:
        """Parse text content for conversation patterns."""
        conversations = []

        # Try different conversation detection strategies
        if self._has_dialogue_markers(content):
            conv = self._parse_dialogue_text(content, file_path)
            conversations.append(conv)
        elif self._has_message_blocks(content):
            conv = self._parse_message_blocks(content, file_path)
            conversations.append(conv)
        else:
            # Treat entire content as single conversation
            conv = self._parse_text_as_conversation(content, file_path)
            conversations.append(conv)

        return conversations

    def _parse_csv_rows(self, rows: list[dict[str, str]], file_path: Path) -> dict[str, Any] | None:
        """Parse CSV rows into conversation format."""
        if not rows:
            return None

        # Try to identify conversation columns
        headers = list(rows[0].keys())

        # Look for common conversation column names
        message_col = self._find_column(headers, ["message", "content", "text", "dialogue"])
        speaker_col = self._find_column(headers, ["speaker", "role", "user", "author"])
        time_col = self._find_column(headers, ["time", "timestamp", "date", "created"])

        messages = []
        content_parts = []

        for row in rows:
            message_text = row.get(message_col, "")
            speaker = row.get(speaker_col, "unknown")
            timestamp_str = row.get(time_col, "")

            if message_text.strip():
                # Create message
                timestamp = (
                    self._parse_timestamp(timestamp_str) if timestamp_str else datetime.now()
                )

                message = self._create_message(
                    role=self._normalize_role(speaker),
                    content=message_text,
                    timestamp=timestamp,
                    metadata={"csv_row": row},
                )
                messages.append(message)

                # Add to content
                content_parts.append(f"**{speaker}**: {message_text}")

        # Create conversation
        title = file_path.stem.replace("_", " ").title()
        content = "\n\n".join(content_parts)
        date = messages[0]["timestamp"] if messages else datetime.now().isoformat()

        return self.create_universal_conversation(
            platform_id=f"csv_{int(datetime.now().timestamp())}",
            title=title,
            content=content,
            messages=messages,
            date=datetime.fromisoformat(date.replace("Z", "+00:00")),
            model="unknown",
            metadata={"csv_headers": headers, "row_count": len(rows)},
        )

    def _parse_xml_tree(self, root) -> list[dict[str, Any]]:
        """Parse XML tree for conversation data."""
        conversations = []

        # Look for conversation-like structures
        for elem in root.iter():
            if self._xml_element_looks_like_conversation(elem):
                try:
                    conv = self._parse_xml_element_as_conversation(elem)
                    conversations.append(conv)
                except Exception as e:  # noqa: BLE001 - resilience: skip unparseable item, keep processing the rest of the batch
                    self.logger.warning("Failed to parse XML conversation: %s", e)

        # If no conversations found, parse entire XML as single conversation
        if not conversations:
            conv = self._parse_xml_root_as_conversation(root)
            conversations.append(conv)

        return conversations

    def _looks_like_conversation(self, data: dict[str, Any]) -> bool:
        """Check if a dictionary looks like a conversation."""
        conversation_indicators = [
            "messages",
            "content",
            "dialogue",
            "conversation",
            "chat",
            "title",
            "participants",
            "transcript",
            "exchanges",
        ]

        text_indicators = ["text", "message", "response", "query", "answer"]

        has_conversation = any(key in data for key in conversation_indicators)
        has_text = any(key in data for key in text_indicators)

        return has_conversation or has_text

    def _has_dialogue_markers(self, content: str) -> bool:
        """Check if text has dialogue markers."""
        patterns = [
            r"\w+:\s*",  # "Speaker: message"
            r"\*\*\w+\*\*:\s*",  # "**Speaker**: message"
            r">\s*\w+:\s*",  # "> Speaker: message"
        ]

        return any(re.search(pattern, content) for pattern in patterns)

    def _has_message_blocks(self, content: str) -> bool:
        """Check if text has message block structure."""
        # Look for repeated patterns that suggest message separation
        lines = content.split("\n")

        # Check for timestamp patterns
        timestamp_pattern = r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}"
        timestamp_lines = sum(1 for line in lines if re.search(timestamp_pattern, line))

        # Check for separator patterns
        separator_patterns = ["---", "===", "***", "___"]
        separator_lines = sum(1 for line in lines if any(sep in line for sep in separator_patterns))

        return timestamp_lines >= 2 or separator_lines >= 2

    def _extract_dialogue_messages(self, lines: list[str]) -> tuple:
        """Extract messages from dialogue lines."""
        messages: list[dict[str, Any]] = []
        content_parts: list[str] = []
        current_speaker = None
        current_message: list[str] = []

        for line in lines:
            speaker_match = re.match(r"(\*\*)?(\w+)(\*\*)?\s*:\s*(.*)", line)

            if speaker_match:
                self._process_speaker_change(
                    current_speaker, current_message, messages, content_parts
                )
                current_speaker, current_message = self._start_new_message(speaker_match)
            else:
                current_message = self._continue_current_message(
                    current_speaker, current_message, line
                )

        # Save final message
        self._process_speaker_change(current_speaker, current_message, messages, content_parts)

        return messages, content_parts

    def _process_speaker_change(
        self,
        current_speaker: str | None,
        current_message: list[str],
        messages: list[dict],
        content_parts: list[str],
    ) -> None:
        """Process speaker change and save previous message."""
        if current_speaker and current_message:
            self._save_dialogue_message(current_speaker, current_message, messages, content_parts)

    def _start_new_message(self, speaker_match: re.Match) -> tuple:
        """Start new message from speaker match."""
        speaker = speaker_match.group(2)
        initial_content = speaker_match.group(4)
        message = [initial_content] if initial_content.strip() else []
        return speaker, message

    def _continue_current_message(
        self, current_speaker: str | None, current_message: list[str], line: str
    ) -> list[str]:
        """Continue current message with new line."""
        if current_speaker:
            current_message.append(line)
        return current_message

    def _save_dialogue_message(
        self,
        speaker: str,
        message_lines: list[str],
        messages: list,
        content_parts: list,
    ):
        """Save a dialogue message to collections."""
        message_text = "\n".join(message_lines).strip()
        if message_text:
            message = self._create_message(
                role=self._normalize_role(speaker),
                content=message_text,
                metadata={"source": "dialogue_parsing"},
            )
            messages.append(message)
            content_parts.append(f"**{speaker}**: {message_text}")

    def _parse_dialogue_text(self, content: str, file_path: Path | None = None) -> dict[str, Any]:
        """Parse text with dialogue markers."""
        lines = content.split("\n")
        messages, content_parts = self._extract_dialogue_messages(lines)

        # Create conversation
        title = DEFAULT_CONVERSATION_TITLE
        if file_path:
            title = file_path.stem.replace("_", " ").title()

        full_content = "\n\n".join(content_parts) if content_parts else content

        return self.create_universal_conversation(
            platform_id=f"generic_{int(datetime.now().timestamp())}",
            title=title,
            content=full_content,
            messages=messages,
            date=datetime.now(),
            model="unknown",
            metadata={"parsing_strategy": "dialogue_markers"},
        )

    def _parse_message_blocks(self, content: str, file_path: Path | None = None) -> dict[str, Any]:
        """Parse text with message block structure."""
        # Split by common separators
        separators = ["---", "===", "***", "___"]
        blocks = [content]

        for sep in separators:
            new_blocks = []
            for block in blocks:
                new_blocks.extend(block.split(sep))
            blocks = new_blocks

        messages = []
        content_parts = []

        for i, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue

            # Try to extract speaker/role from block
            role = f"speaker_{i % 2 + 1}"  # Alternate between speakers

            message = self._create_message(
                role=role,
                content=block,
                metadata={"block_index": i, "source": "message_blocks"},
            )
            messages.append(message)
            content_parts.append(f"**{role.title()}**: {block}")

        # Create conversation
        title = DEFAULT_CONVERSATION_TITLE
        if file_path:
            title = file_path.stem.replace("_", " ").title()

        full_content = "\n\n".join(content_parts)

        return self.create_universal_conversation(
            platform_id=f"generic_{int(datetime.now().timestamp())}",
            title=title,
            content=full_content,
            messages=messages,
            date=datetime.now(),
            model="unknown",
            metadata={"parsing_strategy": "message_blocks"},
        )

    def _parse_text_as_conversation(
        self, content: str, file_path: Path | None = None
    ) -> dict[str, Any]:
        """Parse entire text as single conversation."""
        # Create a single message from entire content
        message = self._create_message(
            role="content", content=content, metadata={"source": "full_text"}
        )

        title = "Generic Text"
        if file_path:
            title = file_path.stem.replace("_", " ").title()

        return self.create_universal_conversation(
            platform_id=f"generic_{int(datetime.now().timestamp())}",
            title=title,
            content=content,
            messages=[message],
            date=datetime.now(),
            model="unknown",
            metadata={"parsing_strategy": "full_text"},
        )

    def _parse_dict_as_conversation(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse dictionary as conversation using flexible mapping."""
        # Try to map common fields
        title = self._extract_field(data, ["title", "name", "subject", "topic"])
        content = self._extract_field(data, ["content", "text", "message", "body"])
        messages = self._extract_field(data, ["messages", "dialogue", "conversation"])

        # Generate defaults if missing
        if not title:
            title = DEFAULT_CONVERSATION_TITLE

        if not content and not messages:
            # Use entire data as content
            content = json.dumps(data, indent=2)

        messages = self._process_raw_messages(messages)

        # Generate content from messages if needed
        if not content and messages:
            content = self._combine_messages_to_content(messages)

        return self.create_universal_conversation(
            platform_id=f"generic_{int(datetime.now().timestamp())}",
            title=title,
            content=content,
            messages=messages,
            date=datetime.now(),
            model="unknown",
            metadata={"original_keys": list(data.keys())},
            **self._extract_universal_metadata(data),
        )

    def _process_raw_messages(self, messages: Any) -> list[dict[str, Any]]:
        """Normalize an arbitrary messages value into universal message dicts.

        Non-list input, or entries that are not dicts, are dropped.
        """
        if not (messages and isinstance(messages, list)):
            return []

        processed: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = self._extract_field(msg, ["role", "speaker", "user", "author"]) or "unknown"
            msg_content = self._extract_field(msg, ["content", "text", "message"]) or str(msg)
            processed.append(
                self._create_message(
                    role=self._normalize_role(role),
                    content=msg_content,
                    metadata={"original": msg},
                )
            )
        return processed

    def _extract_universal_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        """Forward known universal-metadata keys out of an arbitrary dict.

        The generic importer accepts any shape, so each value is type-checked
        and falls back to a neutral default rather than being trusted.
        """
        session_id = self._extract_field(data, ["session_id", "conversation_id"])
        user_id = self._extract_field(data, ["user_id", "account_id", "owner_id"])
        explicit_tags = self._extract_field(data, ["tags", "labels"])
        explicit_type = self._extract_field(data, ["conversation_type", "type", "category"])
        explicit_custom = self._extract_field(data, ["custom_fields", "extra", "extras"])

        return {
            "session_id": session_id if isinstance(session_id, str) else None,
            "user_id": user_id if isinstance(user_id, str) else None,
            "tags": (
                [str(t) for t in explicit_tags if t] if isinstance(explicit_tags, list) else []
            ),
            "conversation_type": (
                explicit_type if isinstance(explicit_type, str) and explicit_type else None
            ),
            "custom_fields": explicit_custom if isinstance(explicit_custom, dict) else {},
        }

    def _parse_list_as_conversation(self, data: list[Any]) -> dict[str, Any]:
        """Parse list as conversation - treat as messages array."""
        messages = []
        content_parts = []

        for i, item in enumerate(data):
            if isinstance(item, dict):
                # Try to extract role and content from dict
                role = (
                    self._extract_field(item, ["role", "speaker", "user", "author"])
                    or f"speaker_{i % 2 + 1}"
                )
                msg_content = self._extract_field(item, ["content", "text", "message"]) or str(item)

                message = self._create_message(
                    role=self._normalize_role(role),
                    content=msg_content,
                    metadata={"list_index": i, "original": item},
                )
                messages.append(message)
                content_parts.append(f"**{role.title()}**: {msg_content}")
            else:
                # Treat non-dict items as content
                role = f"speaker_{i % 2 + 1}"
                content = str(item)

                message = self._create_message(
                    role=role, content=content, metadata={"list_index": i}
                )
                messages.append(message)
                content_parts.append(f"**{role.title()}**: {content}")

        # Create conversation from list
        full_content = "\n\n".join(content_parts)

        return self.create_universal_conversation(
            platform_id=f"generic_{int(datetime.now().timestamp())}",
            title=DEFAULT_CONVERSATION_TITLE,
            content=full_content,
            messages=messages,
            date=datetime.now(),
            model="unknown",
            metadata={"parsing_strategy": "list_format", "list_length": len(data)},
        )

    def _extract_field(self, data: dict[str, Any], field_names: list[str]) -> Any:
        """Extract field using multiple possible names."""
        for name in field_names:
            if name in data:
                return data[name]
        return None

    def _find_column(self, headers: list[str], candidates: list[str]) -> str:
        """Find best matching column name."""
        headers_lower = [h.lower() for h in headers]
        for candidate in candidates:
            for i, header in enumerate(headers_lower):
                if candidate in header:
                    return headers[i]
        return headers[0] if headers else ""

    def _xml_element_looks_like_conversation(self, elem) -> bool:
        """Check if XML element looks like conversation."""
        conversation_tags = [
            "conversation",
            "dialogue",
            "chat",
            "messages",
            "transcript",
        ]
        return elem.tag.lower() in conversation_tags or len(list(elem)) > 3

    def _parse_xml_element_as_conversation(self, elem) -> dict[str, Any]:
        """Parse XML element as conversation."""
        content = elem.text or ""
        for child in elem:
            if child.text:
                content += f"\n{child.tag}: {child.text}"

        return self.create_universal_conversation(
            platform_id=f"xml_{int(datetime.now().timestamp())}",
            title=f"XML {elem.tag}",
            content=content,
            messages=[],
            date=datetime.now(),
            model="unknown",
            metadata={"xml_tag": elem.tag},
        )

    def _parse_xml_root_as_conversation(self, root) -> dict[str, Any]:
        """Parse entire XML root as conversation."""
        content = root.text or ""
        for elem in root.iter():
            if elem.text and elem.text.strip():
                content += f"\n{elem.tag}: {elem.text}"

        return self.create_universal_conversation(
            platform_id=f"xml_{int(datetime.now().timestamp())}",
            title="XML Document",
            content=content,
            messages=[],
            date=datetime.now(),
            model="unknown",
            metadata={"xml_root": root.tag},
        )

    def _normalize_role(self, role: str) -> str:
        """Normalize role names to standard format."""
        role_lower = role.lower().strip()

        # Map common variations
        if role_lower in ["human", "user", "person", "me"]:
            return "user"
        elif role_lower in ["ai", "assistant", "bot", "claude", "chatgpt", "cursor"]:
            return "assistant"
        elif role_lower in ["system", "admin", "moderator"]:
            return "system"
        else:
            return role_lower

    def _save_conversations(
        self, conversations: list[dict[str, Any]], file_path: Path, format_type: str
    ) -> ImportResult:
        """Save multiple conversations and return result."""
        imported_count = 0
        failed_count = 0
        errors = []
        imported_ids = []

        for conv in conversations:
            try:
                if self._validate_conversation(conv):
                    self._save_conversation(conv)
                    imported_ids.append(conv["id"])
                    imported_count += 1
                else:
                    failed_count += 1
                    errors.append(
                        f"Invalid conversation format for ID: {conv.get('id', 'unknown')}"
                    )

            except Exception as e:  # noqa: BLE001 - resilience: skip unsaveable conversation, keep processing the rest of the batch
                failed_count += 1
                conv_id = conv.get("id", "unknown")
                error_msg = f"Failed to save conversation {conv_id}: {str(e)}"
                errors.append(error_msg)
                self.logger.exception(error_msg)

        return ImportResult(
            success=imported_count > 0,
            conversations_imported=imported_count,
            conversations_failed=failed_count,
            errors=errors,
            imported_ids=imported_ids,
            metadata={
                "source_file": str(file_path),
                "format_type": format_type,
                "platform": "generic",
            },
        )

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

        self.logger.info("Saved generic conversation to: %s", file_path)
        return file_path


# Example usage and testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        storage_path = Path("./test_imports")

        importer = GenericImporter(storage_path)
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
        print("Usage: python generic_importer.py <conversation_file>")
