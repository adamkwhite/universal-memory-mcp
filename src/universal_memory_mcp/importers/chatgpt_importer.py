#!/usr/bin/env python3
"""
ChatGPT conversation importer for Universal Memory MCP.

Handles OpenAI ChatGPT export format and converts to universal conversation format.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..validators import validate_import_file_path
from .base_importer import BaseImporter, ImportResult

logger = logging.getLogger(__name__)


class ChatGPTImporter(BaseImporter):
    """Importer for ChatGPT conversation exports."""

    def __init__(self, storage_path: Path):
        super().__init__(storage_path, "chatgpt")
        self.logger = logging.getLogger(f"{__name__}.ChatGPTImporter")

    def get_supported_formats(self) -> list[str]:
        """Return list of supported file formats."""
        return [".json"]

    def import_file(self, file_path: Path) -> ImportResult:
        """
        Import conversations from a ChatGPT export file.

        ChatGPT exports contain a 'conversations' array with message-based structure.
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

            # Load and validate ChatGPT export file
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            if not self._validate_chatgpt_format(data):
                return ImportResult(
                    success=False,
                    conversations_imported=0,
                    conversations_failed=1,
                    errors=["File is not a valid ChatGPT export format"],
                    imported_ids=[],
                    metadata={},
                )

            # Process each conversation
            conversations = data.get("conversations", [])
            return self._process_conversations(conversations, file_path)

        except json.JSONDecodeError as e:
            return ImportResult(
                success=False,
                conversations_imported=0,
                conversations_failed=1,
                errors=[f"Invalid JSON format: {str(e)}"],
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

    def _process_conversations(self, conversations: list[Any], file_path: Path) -> ImportResult:
        """Process list of conversations and return import result."""
        imported_count = 0
        failed_count = 0
        errors = []
        imported_ids = []

        for conversation in conversations:
            try:
                # Parse the conversation into universal format
                universal_conv = self.parse_conversation(conversation)

                if self._validate_conversation(universal_conv):
                    # Save the conversation
                    self._save_conversation(universal_conv)
                    imported_ids.append(universal_conv["id"])
                    imported_count += 1
                    self.logger.info("Imported ChatGPT conversation: %s", universal_conv["id"])
                else:
                    failed_count += 1
                    errors.append(
                        f"Invalid conversation format for ID: {conversation.get('id', 'unknown')}"
                    )

            except Exception as e:  # noqa: BLE001  # resilience: skip unparseable conversation, keep processing the rest of the batch
                failed_count += 1
                conv_id = conversation.get("id", "unknown")
                error_msg = f"Failed to process conversation {conv_id}: {str(e)}"
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
                "total_conversations_in_file": len(conversations),
                "platform": "chatgpt",
                "import_format": "openai_export",
            },
        )

    def parse_conversation(self, raw_data: Any) -> dict[str, Any]:
        """
        Parse raw ChatGPT conversation data into universal format.

        ChatGPT format:
        {
            "id": "conversation-uuid",
            "title": "Conversation Title",
            "create_time": "2025-01-01T12:00:00",
            "update_time": "2025-01-01T12:30:00",
            "messages": [
                {
                    "id": "message-uuid",
                    "role": "user",
                    "content": "Hello",
                    "create_time": "2025-01-01T12:00:00"
                }
            ]
        }
        """
        if not isinstance(raw_data, dict):
            raise TypeError("ChatGPT conversation data must be a dictionary")

        # Extract basic information
        platform_id = raw_data.get("id", "")
        title = raw_data.get("title", "Untitled ChatGPT Conversation")

        # Parse timestamps
        create_time_str = raw_data.get("create_time", "")
        update_time_str = raw_data.get("update_time", "")

        date = self._parse_timestamp(create_time_str) if create_time_str else datetime.now()

        # Process messages
        raw_messages = raw_data.get("messages", [])
        messages = []
        content_parts = []

        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            msg_time_str = msg.get("create_time", "")

            # Skip empty messages
            if not content or not content.strip():
                continue

            # Create standardized message
            timestamp = self._parse_timestamp(msg_time_str) if msg_time_str else date

            message = self._create_message(
                role=role,
                content=content,
                timestamp=timestamp,
                message_id=msg.get("id"),
                metadata={"original_create_time": msg_time_str, "platform": "chatgpt"},
            )
            messages.append(message)

            # Add to content string for full conversation text
            role_display = "**Human**" if role == "user" else f"**{role.title()}**"
            content_parts.append(f"{role_display}: {content}")

        # Combine all messages into content string
        content = "\n\n".join(content_parts)

        # Extract model information if available
        model = self._extract_model_info(raw_data)

        # Universal metadata extraction.
        # ChatGPT exports use ``conversation_id`` (and sometimes ``id``)
        # as the stable identifier — treat this as the session_id so
        # multiple imports of the same conversation can be grouped.
        session_id = raw_data.get("conversation_id") or raw_data.get("id") or None
        # ChatGPT exports rarely include a user identifier, but if a
        # caller has injected one we preserve it.
        user_id = raw_data.get("user_id") or None
        tags = self._extract_chatgpt_tags(raw_data)
        conversation_type = self._classify_conversation_type(raw_data, content)
        custom_fields = self._extract_chatgpt_custom_fields(raw_data)

        # Create universal conversation
        return self.create_universal_conversation(
            platform_id=platform_id,
            title=title,
            content=content,
            messages=messages,
            date=date,
            model=model,
            session_context={
                "update_time": update_time_str,
                "original_platform": "chatgpt",
            },
            metadata={
                "original_id": platform_id,
                "original_create_time": create_time_str,
                "original_update_time": update_time_str,
                "message_count": len(messages),
            },
            session_id=session_id,
            user_id=user_id,
            tags=tags,
            conversation_type=conversation_type,
            custom_fields=custom_fields,
        )

    def _extract_chatgpt_tags(self, raw_data: dict[str, Any]) -> list[str]:
        """Build tags list from ChatGPT-specific signals (starred, archived, gizmo)."""
        tags: list[str] = []
        if raw_data.get("is_starred"):
            tags.append("starred")
        if raw_data.get("is_archived"):
            tags.append("archived")
        gizmo_id = raw_data.get("gizmo_id")
        if gizmo_id:
            tags.append(f"gizmo:{gizmo_id}")
        # Allow callers to inject explicit tags
        explicit = raw_data.get("tags")
        if isinstance(explicit, list):
            tags.extend(str(t) for t in explicit if t)
        return tags

    def _classify_conversation_type(self, raw_data: dict[str, Any], content: str) -> str:
        """Classify a ChatGPT conversation as chat/code/analysis/etc.

        Uses lightweight heuristics — explicit hints win, otherwise content
        is inspected for code-fence density.
        """
        explicit = raw_data.get("conversation_type")
        if isinstance(explicit, str) and explicit:
            return explicit
        # Heuristic: lots of code fences => code conversation
        if content and content.count("```") >= 4:
            return "code"
        return "chat"

    def _extract_chatgpt_custom_fields(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Capture optional ChatGPT-specific fields into custom_fields.

        Only populates entries that are actually present in the source so the
        default empty dict is preserved for typical exports.
        """
        custom: dict[str, Any] = {}
        for key in (
            "default_model_slug",
            "conversation_template_id",
            "gizmo_id",
            "gizmo_type",
            "memory_scope",
        ):
            value = raw_data.get(key)
            if value is not None:
                custom[key] = value
        # Pass through any caller-supplied custom_fields dict.
        extra = raw_data.get("custom_fields")
        if isinstance(extra, dict):
            custom.update(extra)
        return custom

    def _validate_chatgpt_format(self, data: Any) -> bool:
        """Validate that data is in ChatGPT export format."""
        if not isinstance(data, dict):
            return False

        if not self._validate_conversations_array(data):
            return False

        return self._validate_conversation_structure(data["conversations"])

    def _validate_conversations_array(self, data: dict[str, Any]) -> bool:
        """Validate conversations array exists and is valid."""
        if "conversations" not in data:
            return False

        conversations = data["conversations"]
        return isinstance(conversations, list)

    def _validate_conversation_structure(self, conversations: list[Any]) -> bool:
        """Validate conversation structure if conversations exist."""
        if not conversations:
            return True

        sample_conv = conversations[0]
        if not isinstance(sample_conv, dict):
            return False

        return self._validate_messages_structure(sample_conv)

    def _validate_messages_structure(self, conversation: dict[str, Any]) -> bool:
        """Validate messages structure within conversation."""
        if "messages" not in conversation:
            return False

        messages = conversation["messages"]
        if not isinstance(messages, list):
            return False

        if not messages:
            return True

        sample_msg = messages[0]
        if not isinstance(sample_msg, dict):
            return False

        return "role" in sample_msg and "content" in sample_msg

    def _extract_model_info(self, conversation_data: dict[str, Any]) -> str:
        """Extract model information from conversation data."""
        # ChatGPT exports don't always include model info explicitly
        # We can infer from metadata or default to GPT-4

        # Check if there's model info in the conversation
        if "model" in conversation_data:
            return conversation_data["model"]

        # Check messages for model hints
        messages = conversation_data.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                # Look for model indicators in assistant responses
                content = msg.get("content", "").lower()
                if "gpt-4" in content:
                    return "gpt-4"
                elif "gpt-3.5" in content:
                    return "gpt-3.5-turbo"

        # Default assumption for ChatGPT exports
        return "gpt-4"

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

        self.logger.info(f"Saved conversation to: {file_path}")
        return file_path

    def _extract_topics(self, content: str) -> list[str]:
        """Override base topic extraction for ChatGPT-specific patterns."""
        topics = super()._extract_topics(content)

        # Add ChatGPT-specific topic indicators
        content_lower = content.lower()

        # ChatGPT-specific terms
        chatgpt_topics = [
            "openai",
            "gpt",
            "artificial intelligence",
            "language model",
            "prompt",
            "chatbot",
            "ai assistant",
            "machine learning",
        ]

        for topic in chatgpt_topics:
            if topic in content_lower and topic not in topics:
                topics.append(topic)

        # Always include platform identifier
        if "chatgpt" not in topics:
            topics.append("chatgpt")

        return topics[:10]  # Limit to 10 topics


# Example usage and testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        storage_path = Path("./test_imports")

        importer = ChatGPTImporter(storage_path)
        result = importer.import_file(file_path)

        print("Import Result:")
        print(f"  Success: {result.success}")
        print(f"  Imported: {result.conversations_imported}")
        print(f"  Failed: {result.conversations_failed}")
        print(f"  Success Rate: {result.success_rate:.2%}")

        if result.errors:
            print(f"  Errors: {result.errors}")

        if result.imported_ids:
            print(f"  Imported IDs: {result.imported_ids[:3]}...")
    else:
        print("Usage: python chatgpt_importer.py <chatgpt_export.json>")
