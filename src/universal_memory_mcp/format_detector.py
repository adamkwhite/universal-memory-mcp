#!/usr/bin/env python3
"""
Format detection module for Universal Memory MCP.

Automatically detects the source platform and format of conversation exports
from various AI assistants (ChatGPT, Cursor, Claude, etc.).
"""

import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any

from .validators import validate_import_file_path

logger = logging.getLogger(__name__)


class PlatformType(Enum):
    """Supported AI platform types."""

    CHATGPT = "chatgpt"
    CURSOR = "cursor"
    CLAUDE_WEB = "claude_web"
    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_MEMORY = "claude_memory"  # Our current format
    GENERIC_JSON = "generic_json"
    GENERIC_MARKDOWN = "generic_markdown"
    UNKNOWN = "unknown"


class FormatDetector:
    """Detects and validates AI conversation export formats."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def detect_format(self, file_path: Path) -> dict[str, Any]:
        """
        Detect the format of a conversation export file.

        Args:
            file_path: Path to the file to analyze

        Returns:
            Dict containing platform, confidence, and metadata
        """
        try:
            if not file_path.exists():
                return self._create_result(PlatformType.UNKNOWN, 0.0, "File not found")

            file_path = validate_import_file_path(file_path)

            # Check file extension
            extension = file_path.suffix.lower()

            if extension == ".json":
                return self._detect_json_format(file_path)
            elif extension in [".md", ".txt"]:
                return self._detect_text_format(file_path)
            else:
                return self._create_result(
                    PlatformType.UNKNOWN, 0.0, f"Unsupported extension: {extension}"
                )

        except Exception as e:  # noqa: BLE001  # best-effort platform classification: report UNKNOWN/0.0 rather than crash on arbitrary file content
            self.logger.exception(f"Error detecting format for {file_path}: {e}")
            return self._create_result(PlatformType.UNKNOWN, 0.0, f"Detection error: {str(e)}")

    def _detect_json_format(self, file_path: Path) -> dict[str, Any]:
        """Detect format for JSON files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # Check for ChatGPT format
            if self._is_chatgpt_format(data):
                return self._create_result(PlatformType.CHATGPT, 0.95, "ChatGPT export detected")

            # Check for Cursor format
            if self._is_cursor_format(data):
                return self._create_result(PlatformType.CURSOR, 0.95, "Cursor AI export detected")

            # Check for our own Claude Memory format
            if self._is_claude_memory_format(data):
                return self._create_result(
                    PlatformType.CLAUDE_MEMORY, 0.99, "Claude Memory format detected"
                )

            # Check for Claude Desktop format
            if self._is_claude_desktop_format(data):
                return self._create_result(
                    PlatformType.CLAUDE_DESKTOP, 0.90, "Claude Desktop export detected"
                )

            # Generic JSON with conversation-like structure
            if self._has_conversation_structure(data):
                return self._create_result(
                    PlatformType.GENERIC_JSON,
                    0.60,
                    "Generic conversation JSON detected",
                )

            return self._create_result(PlatformType.UNKNOWN, 0.0, "Unknown JSON format")

        except json.JSONDecodeError as e:
            return self._create_result(PlatformType.UNKNOWN, 0.0, f"Invalid JSON: {str(e)}")
        except Exception as e:  # noqa: BLE001  # best-effort platform classification: report UNKNOWN/0.0 rather than crash on arbitrary file content
            return self._create_result(PlatformType.UNKNOWN, 0.0, f"JSON analysis error: {str(e)}")

    def _detect_text_format(self, file_path: Path) -> dict[str, Any]:
        """Detect format for text/markdown files."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Check for Claude web interface format
            if self._is_claude_web_format(content):
                return self._create_result(
                    PlatformType.CLAUDE_WEB, 0.85, "Claude web conversation detected"
                )

            # Check for generic markdown conversation
            if self._is_markdown_conversation(content):
                return self._create_result(
                    PlatformType.GENERIC_MARKDOWN,
                    0.70,
                    "Generic markdown conversation detected",
                )

            return self._create_result(PlatformType.UNKNOWN, 0.0, "Unknown text format")

        except Exception as e:  # noqa: BLE001  # best-effort platform classification: report UNKNOWN/0.0 rather than crash on arbitrary file content
            return self._create_result(PlatformType.UNKNOWN, 0.0, f"Text analysis error: {str(e)}")

    def _is_chatgpt_format(self, data: Any) -> bool:
        """Check if data matches ChatGPT export format."""
        # ChatGPT exports can be an array of conversations directly
        if isinstance(data, list) and data and isinstance(data[0], dict):
            conv = data[0]
            # Check for ChatGPT-specific structure (title, create_time, mapping)
            return (
                isinstance(conv, dict)
                and "title" in conv
                and "create_time" in conv
                and "mapping" in conv
                and isinstance(conv["mapping"], dict)
            )

        # Or wrapped in a 'conversations' key
        if (
            isinstance(data, dict)
            and "conversations" in data
            and isinstance(data["conversations"], list)
            and data["conversations"]
        ):
            # Check a sample conversation structure
            conv = data["conversations"][0]
            return (
                isinstance(conv, dict)
                and "messages" in conv
                and isinstance(conv["messages"], list)
                and self._has_role_based_messages(conv["messages"])
            )

        return False

    def _is_cursor_format(self, data: Any) -> bool:
        """Check if data matches Cursor AI export format."""
        if not isinstance(data, dict):
            return False

        # Cursor format indicators
        cursor_indicators = ["session_id", "workspace", "interactions", "model"]
        has_indicators = sum(1 for key in cursor_indicators if key in data)

        # Also check for workspace path patterns
        if "workspace" in data:
            workspace = data["workspace"]
            if isinstance(workspace, str) and ("/" in workspace or "\\" in workspace):
                has_indicators += 1

        return has_indicators >= 2

    def _is_claude_memory_format(self, data: Any) -> bool:
        """Check if data matches our current Claude Memory format."""
        if not isinstance(data, dict):
            return False

        # Our format has specific structure
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

    def _is_claude_desktop_format(self, data: Any) -> bool:
        """Check if data matches Claude Desktop export format."""
        if not isinstance(data, dict):
            return False

        # Claude Desktop might have MCP-specific fields
        claude_indicators = ["claude", "desktop", "mcp", "anthropic"]
        content_str = json.dumps(data).lower()

        indicator_count = sum(1 for indicator in claude_indicators if indicator in content_str)

        # Also check for conversation structure
        if self._has_conversation_structure(data):
            indicator_count += 1

        return indicator_count >= 2

    def _is_claude_web_format(self, content: str) -> bool:
        """Check if text matches Claude web interface format."""
        # Look for Claude web conversation patterns
        claude_patterns = [
            r"\*\*Human\*\*:",
            r"\*\*Claude\*\*:",
            r"# Conversation with Claude",
            r"Human:.*\n.*Claude:",
        ]

        pattern_matches = sum(
            1
            for pattern in claude_patterns
            if re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
        )

        return pattern_matches >= 1

    def _is_markdown_conversation(self, content: str) -> bool:
        """Check if text is a markdown-formatted conversation."""
        # Look for conversation indicators
        conversation_patterns = [
            r"\*\*.*\*\*:",  # Bold role indicators
            r"^[A-Z][a-z]+:",  # Simple role indicators
            r"^\s*>\s*",  # Quote blocks
            r"#{1,3}\s*",  # Headers
        ]

        pattern_matches = sum(
            1 for pattern in conversation_patterns if re.search(pattern, content, re.MULTILINE)
        )

        # Also check for back-and-forth conversation flow
        lines = content.split("\n")
        role_changes = 0
        current_role = None

        for line in lines:
            if ":" in line and line.strip():
                potential_role = line.split(":")[0].strip("*# ")
                if potential_role != current_role and len(potential_role) < 20:
                    role_changes += 1
                    current_role = potential_role

        return pattern_matches >= 2 or role_changes >= 3

    def _has_role_based_messages(self, messages: list[Any]) -> bool:
        """Check if messages have role-based structure (user/assistant)."""
        if not messages or not isinstance(messages, list):
            return False

        role_count = 0
        for msg in messages[:5]:  # Check first 5 messages
            if isinstance(msg, dict) and "role" in msg:
                role = msg["role"].lower()
                if role in ["user", "assistant", "system"]:
                    role_count += 1

        return role_count >= 2

    def _has_conversation_structure(self, data: Any) -> bool:
        """Check if data has general conversation structure."""
        if not isinstance(data, dict):
            return False

        # Look for common conversation fields
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

    def _create_result(
        self, platform: PlatformType, confidence: float, message: str
    ) -> dict[str, Any]:
        """Create a standardized detection result."""
        return {
            "platform": platform.value,
            "confidence": confidence,
            "message": message,
            "timestamp": Path(__file__).stat().st_mtime,  # Detection time
        }

    def get_supported_platforms(self) -> list[str]:
        """Get list of supported platform types."""
        return [platform.value for platform in PlatformType if platform != PlatformType.UNKNOWN]

    def validate_platform_support(self, platform: str) -> bool:
        """Check if a platform is supported for import."""
        return platform in self.get_supported_platforms()


def detect_file_format(file_path: Path) -> dict[str, Any]:
    """Convenience function for format detection."""
    detector = FormatDetector()
    return detector.detect_format(file_path)


# Example usage and testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        result = detect_file_format(file_path)
        print(f"Detection Result: {json.dumps(result, indent=2)}")
    else:
        print("Usage: python format_detector.py <file_path>")
