#!/usr/bin/env python3
"""
Base importer class for Universal Memory MCP.

Defines the interface and common functionality for all platform importers.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    conversations_imported: int
    conversations_failed: int
    errors: list[str]
    imported_ids: list[str]
    metadata: dict[str, Any]

    @property
    def total_processed(self) -> int:
        return self.conversations_imported + self.conversations_failed

    @property
    def success_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.conversations_imported / self.total_processed


class BaseImporter(ABC):
    """Base class for all conversation importers."""

    def __init__(self, storage_path: Path, platform_name: str):
        """
        Initialize the importer.

        Args:
            storage_path: Path where conversations will be stored
            platform_name: Name of the source platform
        """
        self.storage_path = Path(storage_path)
        self.platform_name = platform_name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def import_file(self, file_path: Path) -> ImportResult:
        """
        Import conversations from a file.

        Args:
            file_path: Path to the file to import

        Returns:
            ImportResult with import statistics and any errors
        """

    @abstractmethod
    def parse_conversation(self, raw_data: Any) -> dict[str, Any]:
        """
        Parse raw conversation data into universal format.

        Args:
            raw_data: Raw conversation data from the platform

        Returns:
            Conversation in universal internal format
        """

    def create_universal_conversation(
        self,
        platform_id: str,
        title: str,
        content: str,
        messages: list[dict[str, Any]],
        date: datetime,
        model: str | None = None,
        session_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        conversation_type: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a conversation in universal internal format.

        Args:
            platform_id: Original ID from the source platform
            title: Conversation title
            content: Unified conversation content
            messages: List of individual messages
            date: Conversation start date
            model: AI model used (if available)
            session_context: Optional session/workspace context
            metadata: Additional platform-specific metadata
            session_id: Identifier for grouping related conversations within
                a session (e.g., a Cursor session, ChatGPT conversation_id).
            user_id: Identifier for the user that owns the conversation
                (reserved for future multi-user support).
            tags: Platform-specific categorization tags. Defaults to an
                empty list when not provided.
            conversation_type: High-level classification such as "chat",
                "code", "analysis", etc. Free-form string.
            custom_fields: Open extensibility bucket for arbitrary
                platform/user-defined metadata. Defaults to an empty dict.

        Returns:
            Conversation in universal format
        """
        conversation_id = self._generate_conversation_id(date)
        topics = self._extract_topics(content)

        universal_conv = {
            "id": conversation_id,
            "platform": self.platform_name,
            "platform_id": platform_id,
            "model": model or "unknown",
            "title": title or f"{self.platform_name.title()} Conversation",
            "content": content,
            "messages": messages,
            "date": date.isoformat(),
            "last_updated": (
                messages[-1].get("timestamp", date.isoformat()) if messages else date.isoformat()
            ),
            "topics": topics,
            "session_context": session_context or {},
            # Universal metadata fields (todos 5.1.3, 5.1.4, 5.2.1, 5.2.3, 5.2.4).
            # All optional with sensible defaults so existing callers and
            # stored conversations remain valid without these fields.
            "session_id": session_id,
            "user_id": user_id,
            "tags": list(tags) if tags else [],
            "conversation_type": conversation_type,
            "custom_fields": dict(custom_fields) if custom_fields else {},
            "import_metadata": {
                "imported_at": datetime.now().isoformat(),
                "source_format": self.platform_name,
                "import_version": "1.0",
                "original_platform_id": platform_id,
            },
            "created_at": datetime.now().isoformat(),
        }

        # Add any additional metadata
        if metadata:
            universal_conv["platform_metadata"] = metadata

        return universal_conv

    def _generate_conversation_id(self, date: datetime) -> str:
        """Generate a unique conversation ID."""
        timestamp = date.strftime("%Y%m%d_%H%M%S")
        random_suffix = str(uuid.uuid4())[:8]
        return f"conv_{timestamp}_{random_suffix}"

    def _extract_topics(self, content: str) -> list[str]:
        """
        Extract topics from conversation content.

        This is a basic implementation that can be overridden by specific importers
        for platform-specific topic extraction.
        """
        if not content:
            return []

        content_lower = content.lower()

        # Common technology and conversation topics
        tech_topics = [
            "python",
            "javascript",
            "java",
            "css",
            "html",
            "react",
            "vue",
            "angular",
            "django",
            "flask",
            "nodejs",
            "express",
            "api",
            "database",
            "sql",
            "mongodb",
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "gcp",
            "git",
            "github",
            "gitlab",
            "testing",
            "debugging",
            "deployment",
            "authentication",
            "security",
            "encryption",
            "machine learning",
            "ai",
            "neural network",
            "data science",
            "analytics",
            "programming",
            "coding",
            "development",
            "software",
            "web development",
            "mobile",
            "ios",
            "android",
            "frontend",
            "backend",
            "fullstack",
        ]

        found_topics = []
        for topic in tech_topics:
            if topic in content_lower:
                found_topics.append(topic)

        # Add platform-specific topic
        found_topics.append(self.platform_name)

        return list(set(found_topics))  # Remove duplicates

    def _create_message(
        self,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a standardized message object."""
        return {
            "id": message_id or str(uuid.uuid4()),
            "role": role.lower(),
            "content": content,
            "timestamp": (timestamp or datetime.now()).isoformat(),
            "metadata": metadata or {},
        }

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse various timestamp formats to datetime."""
        # Common timestamp formats
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO with microseconds and Z
            "%Y-%m-%dT%H:%M:%SZ",  # ISO with Z
            "%Y-%m-%dT%H:%M:%S",  # ISO basic
            "%Y-%m-%d %H:%M:%S",  # Standard datetime
            "%Y-%m-%d",  # Date only
        ]

        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str.replace("Z", ""), fmt.replace("Z", ""))
            except ValueError:
                continue

        # If all formats fail, use current time and log warning.
        # ``timestamp_str`` is untrusted (platform export data); log it via
        # %r (through lazy %-formatting) rather than f-string concatenation
        # so control/newline characters are escaped instead of injected
        # verbatim into the log (SonarCloud pythonsecurity:S5145).
        self.logger.warning("Could not parse timestamp: %r, using current time", timestamp_str)
        return datetime.now()

    def _combine_messages_to_content(self, messages: list[dict[str, Any]]) -> str:
        """Combine individual messages into a single content string."""
        content_parts = []

        for msg in messages:
            role = msg.get("role", "unknown")
            text = msg.get("content", "")

            # Format based on role
            if role == "user":
                content_parts.append(f"**Human**: {text}")
            elif role == "assistant":
                content_parts.append(f"**Assistant**: {text}")
            elif role == "system":
                content_parts.append(f"**System**: {text}")
            else:
                content_parts.append(f"**{role.title()}**: {text}")

        return "\n\n".join(content_parts)

    def _validate_conversation(self, conversation: dict[str, Any]) -> bool:
        """Validate that a conversation has required fields."""
        required_fields = ["id", "platform", "title", "content", "date", "messages"]

        for field in required_fields:
            if field not in conversation:
                self.logger.error(f"Missing required field: {field}")
                return False

        # Validate messages structure
        if not isinstance(conversation["messages"], list):
            self.logger.error("Messages must be a list")
            return False

        return True

    def get_import_stats(self) -> dict[str, Any]:
        """Get statistics about the importer."""
        return {
            "platform": self.platform_name,
            "storage_path": str(self.storage_path),
            "supported_formats": self.get_supported_formats(),
        }

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """Return list of supported file formats for this importer."""

    def batch_import(self, file_paths: list[Path]) -> ImportResult:
        """Import multiple files and combine results."""
        total_conversations = 0
        total_failed = 0
        all_errors = []
        all_imported_ids = []
        combined_metadata = {}

        for file_path in file_paths:
            try:
                result = self.import_file(file_path)
                total_conversations += result.conversations_imported
                total_failed += result.conversations_failed
                all_errors.extend(result.errors)
                all_imported_ids.extend(result.imported_ids)

                # Combine metadata
                combined_metadata[str(file_path)] = result.metadata

            except Exception as e:  # noqa: BLE001 - resilience: skip unimportable file, keep processing the rest of the batch
                self.logger.exception(f"Failed to import {file_path}: {e}")
                all_errors.append(f"Failed to import {file_path}: {str(e)}")
                total_failed += 1

        return ImportResult(
            success=total_conversations > 0,
            conversations_imported=total_conversations,
            conversations_failed=total_failed,
            errors=all_errors,
            imported_ids=all_imported_ids,
            metadata={
                "batch_import": True,
                "files_processed": len(file_paths),
                "individual_results": combined_metadata,
            },
        )
