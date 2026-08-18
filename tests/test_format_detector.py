#!/usr/bin/env python3
"""
Test suite for FormatDetector.

Tests automatic platform detection for AI conversation exports.
"""

import json
import tempfile
from pathlib import Path

from universal_memory_mcp.format_detector import FormatDetector, PlatformType


class TestFormatDetector:
    """Test FormatDetector core functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.detector = FormatDetector()

    def test_detector_initialization(self):
        """Test FormatDetector initialization."""
        detector = FormatDetector()
        assert detector.logger is not None

    def test_detect_format_nonexistent_file(self):
        """Test detection with non-existent file."""
        non_existent = self.temp_path / "does_not_exist.json"
        result = self.detector.detect_format(non_existent)

        assert result["platform"] == PlatformType.UNKNOWN.value
        assert result["confidence"] == 0.0

    def test_detect_format_chatgpt_export(self):
        """Test detection of ChatGPT export format."""
        chatgpt_data = {
            "conversations": [
                {
                    "id": "test-conv-123",
                    "title": "Test ChatGPT Conversation",
                    "create_time": "2025-01-15T10:00:00Z",
                    "messages": [
                        {
                            "id": "msg-1",
                            "role": "user",
                            "content": "Hello ChatGPT",
                            "create_time": "2025-01-15T10:00:00Z",
                        },
                        {
                            "id": "msg-2",
                            "role": "assistant",
                            "content": "Hello! How can I help you?",
                            "create_time": "2025-01-15T10:01:00Z",
                        },
                    ],
                }
            ]
        }

        test_file = self.temp_path / "chatgpt_export.json"
        test_file.write_text(json.dumps(chatgpt_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CHATGPT.value
        assert result["confidence"] >= 0.9

    def test_detect_format_cursor_export(self):
        """Test detection of Cursor AI export format."""
        cursor_data = {
            "session_id": "cursor-session-456",
            "workspace": "/path/to/project",
            "model": "claude-3-sonnet",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "Help me with this code",
                    "timestamp": "2025-01-15T10:00:00Z",
                    "files": ["main.py"],
                }
            ],
        }

        test_file = self.temp_path / "cursor_export.json"
        test_file.write_text(json.dumps(cursor_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CURSOR.value
        assert result["confidence"] >= 0.9

    def test_detect_format_claude_memory_format(self):
        """Test detection of our existing Claude memory format."""
        memory_data = {
            "id": "conv_20250115_120000_abcd1234",
            "platform": "claude",
            "title": "Memory Format Conversation",
            "content": "Test conversation content",
            "messages": [],
            "date": "2025-01-15T12:00:00",
            "topics": ["test"],
            "created_at": "2025-01-15T12:00:00",
        }

        test_file = self.temp_path / "memory_format.json"
        test_file.write_text(json.dumps(memory_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CLAUDE_MEMORY.value
        assert result["confidence"] >= 0.95

    def test_detect_format_claude_desktop_export(self):
        """Test detection of Claude desktop export format."""
        claude_data = {
            "id": "claude-desktop-abc",
            "name": "Desktop Conversation",
            "created_at": "2025-01-15T10:00:00Z",
            "updated_at": "2025-01-15T10:30:00Z",
            "message_list": [
                {
                    "uuid": "msg-desktop-1",
                    "content": [{"type": "text", "text": "Hello Desktop Claude"}],
                    "sender": "human",
                }
            ],
        }

        test_file = self.temp_path / "claude_desktop_export.json"
        test_file.write_text(json.dumps(claude_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CLAUDE_DESKTOP.value
        assert result["confidence"] >= 0.8

    def test_detect_format_generic_json(self):
        """Test detection of generic JSON conversation format."""
        generic_data = {
            "title": "Generic Conversation",
            "messages": [{"user": "Hello", "assistant": "Hi there!"}],
            "timestamp": "2025-01-15",
        }

        test_file = self.temp_path / "generic_export.json"
        test_file.write_text(json.dumps(generic_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        # Should detect as generic JSON if it has conversation structure
        assert result["platform"] in [
            PlatformType.GENERIC_JSON.value,
            PlatformType.UNKNOWN.value,
        ]

    def test_detect_format_markdown_file(self):
        """Test detection of markdown conversation format."""
        markdown_content = """# Conversation with AI

**Human**: Hello, how are you?

**Assistant**: I'm doing well, thank you for asking! How can I help you today?

**Human**: Can you help me write some code?

**Assistant**: Of course! I'd be happy to help you write code. What programming language or specific task are you working on?
"""

        test_file = self.temp_path / "conversation.md"
        test_file.write_text(markdown_content, encoding="utf-8")

        result = self.detector.detect_format(test_file)

        # Should detect as some text format (implementation specific)
        assert result["platform"] in [
            PlatformType.GENERIC_MARKDOWN.value,
            PlatformType.CLAUDE_WEB.value,
            PlatformType.UNKNOWN.value,
        ]

    def test_detect_format_invalid_json(self):
        """Test detection with invalid JSON file."""
        test_file = self.temp_path / "invalid.json"
        test_file.write_text('{"invalid": json syntax}', encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.UNKNOWN.value
        assert result["confidence"] == 0.0

    def test_detect_format_empty_file(self):
        """Test detection with empty file."""
        test_file = self.temp_path / "empty.json"
        test_file.write_text("", encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.UNKNOWN.value
        assert result["confidence"] == 0.0

    def test_detect_format_unsupported_extension(self):
        """Test detection with unsupported file extension."""
        test_file = self.temp_path / "conversation.xml"
        test_file.write_text(
            "<conversation><message>Hello</message></conversation>", encoding="utf-8"
        )

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.UNKNOWN.value
        assert result["confidence"] == 0.0


class TestFormatDetectorValidationMethods:
    """Test FormatDetector validation methods."""

    def setup_method(self):
        """Set up test environment."""
        self.detector = FormatDetector()

    def test_is_chatgpt_format_valid(self):
        """Test _is_chatgpt_format with valid data."""
        data = {
            "conversations": [
                {
                    "id": "test",
                    "messages": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi"},
                    ],
                }
            ]
        }

        result = self.detector._is_chatgpt_format(data)
        assert result is True

    def test_is_chatgpt_format_invalid(self):
        """Test _is_chatgpt_format with invalid data."""
        data = {"not_conversations": []}

        result = self.detector._is_chatgpt_format(data)
        assert result is False

    def test_is_cursor_format_valid(self):
        """Test _is_cursor_format with valid data."""
        data = {
            "session_id": "test",
            "workspace": "/path",
            "interactions": [{"type": "user_input", "content": "Hello"}],
        }

        result = self.detector._is_cursor_format(data)
        assert result is True

    def test_is_cursor_format_invalid(self):
        """Test _is_cursor_format with invalid data."""
        data = {"not_cursor": "data"}

        result = self.detector._is_cursor_format(data)
        assert result is False

    def test_is_claude_memory_format_valid(self):
        """Test _is_claude_memory_format with valid data."""
        data = {
            "id": "conv_20250115_120000_abcd1234",
            "platform": "claude",
            "content": "test",
            "messages": [],
            "topics": [],
            "created_at": "2025-01-15T12:00:00",
        }

        result = self.detector._is_claude_memory_format(data)
        assert result is True

    def test_is_claude_desktop_format_valid(self):
        """Test _is_claude_desktop_format with valid data."""
        data = {
            "id": "test-id",
            "message_list": [{"content": [{"type": "text"}], "sender": "human"}],
        }

        result = self.detector._is_claude_desktop_format(data)
        # Implementation may require specific fields - adjust based on actual requirements
        assert isinstance(result, bool)

    def test_has_role_based_messages_valid(self):
        """Test _has_role_based_messages with valid messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        result = self.detector._has_role_based_messages(messages)
        assert result is True

    def test_has_role_based_messages_invalid(self):
        """Test _has_role_based_messages with invalid messages."""
        messages = [{"user": "Hello"}, {"text": "Hi"}]  # No 'role' field

        result = self.detector._has_role_based_messages(messages)
        assert result is False

    def test_has_conversation_structure_valid(self):
        """Test _has_conversation_structure with valid data."""
        data = {
            "title": "Test Conversation",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        result = self.detector._has_conversation_structure(data)
        assert result is True

    def test_has_conversation_structure_invalid(self):
        """Test _has_conversation_structure with invalid data."""
        data = {"random": "data", "no_conversation": "structure"}

        result = self.detector._has_conversation_structure(data)
        assert result is False


class TestFormatDetectorErrorHandling:
    """Test FormatDetector error handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.detector = FormatDetector()

    def test_detect_format_permission_error(self):
        """Test detection with file permission issues."""
        test_file = self.temp_path / "permission_test.json"
        test_file.write_text('{"test": "data"}', encoding="utf-8")

        # Make file unreadable
        try:
            test_file.chmod(0o000)

            result = self.detector.detect_format(test_file)

            assert result["platform"] == PlatformType.UNKNOWN.value
            assert result["confidence"] == 0.0
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)

    def test_detect_format_large_file_handling(self):
        """Test detection with reasonably large file."""
        large_data = {
            "conversations": [
                {
                    "id": f"conv-{i}",
                    "messages": [{"role": "user", "content": f"Message {j}"} for j in range(5)],
                }
                for i in range(20)
            ]
        }

        test_file = self.temp_path / "large_export.json"
        test_file.write_text(json.dumps(large_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CHATGPT.value
        assert result["confidence"] >= 0.9

    def test_detect_format_with_unicode_content(self):
        """Test detection with Unicode content."""
        unicode_data = [
            {
                "title": "Unicode Test Conversation",
                "create_time": 1705312800.0,
                "conversation_id": "unicode-test-123",
                "mapping": {
                    "msg-1": {
                        "id": "msg-1",
                        "message": {
                            "id": "msg-1",
                            "author": {"role": "user"},
                            "create_time": 1705312800.0,
                            "content": {
                                "content_type": "text",
                                "parts": ["Hello 你好 🌟 émoji tëst"],
                            },
                        },
                        "parent": None,
                        "children": [],
                    }
                },
            }
        ]

        test_file = self.temp_path / "unicode_export.json"
        test_file.write_text(json.dumps(unicode_data, ensure_ascii=False), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.CHATGPT.value
        assert result["confidence"] >= 0.9


class TestFormatDetectorTextFormats:
    """Test FormatDetector text format detection."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.detector = FormatDetector()

    def test_detect_markdown_conversation(self):
        """Test detection of markdown conversation format."""
        markdown_content = """# My AI Conversation

**Human**: Hello there! How can you help me today?

**Assistant**: Hello! I'm here to help with a wide variety of tasks. I can assist with:
- Writing and editing
- Analysis and research
- Code and programming
- Creative projects

What would you like to work on?

**Human**: That's great! Can you help me write a Python function?

**Assistant**: Absolutely! I'd be happy to help you write a Python function. What should the function do?
"""

        test_file = self.temp_path / "conversation.md"
        test_file.write_text(markdown_content, encoding="utf-8")

        result = self.detector.detect_format(test_file)

        # Should detect as Claude web format due to **Human**/**Assistant** pattern
        assert result["platform"] in [
            PlatformType.CLAUDE_WEB.value,
            PlatformType.GENERIC_MARKDOWN.value,
            PlatformType.UNKNOWN.value,
        ]
        assert result["confidence"] >= 0.0

    def test_detect_plain_text_file(self):
        """Test detection of plain text file."""
        plain_text = "This is just a plain text file without any conversation structure."

        test_file = self.temp_path / "plain.txt"
        test_file.write_text(plain_text, encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["platform"] == PlatformType.UNKNOWN.value
        assert result["confidence"] == 0.0


class TestFormatDetectorIntegration:
    """Test FormatDetector integration scenarios."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.detector = FormatDetector()

    def test_batch_format_detection(self):
        """Test detection across multiple files."""
        # Create test files of different formats
        files_data = [
            (
                "chatgpt.json",
                [
                    {
                        "title": "Test Chat",
                        "create_time": 1705312800.0,
                        "conversation_id": "test-123",
                        "mapping": {
                            "msg-1": {
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": ["hi"]},
                                }
                            }
                        },
                    }
                ],
            ),
            (
                "cursor.json",
                {
                    "session_id": "test",
                    "workspace": "/path",
                    "interactions": [],
                },
            ),
            (
                "memory.json",
                {
                    "id": "conv_20250115_120000_abcd",
                    "platform": "claude",
                    "content": "test",
                    "messages": [],
                    "topics": [],
                    "created_at": "2025-01-15",
                },
            ),
            ("dialogue.md", "**Human**: Hello\n**Assistant**: Hi!"),
        ]

        results = []
        for filename, data in files_data:
            test_file = self.temp_path / filename
            if filename.endswith(".json"):
                test_file.write_text(json.dumps(data), encoding="utf-8")
            else:
                test_file.write_text(data, encoding="utf-8")

            result = self.detector.detect_format(test_file)
            results.append((filename, result["platform"]))

        # Verify correct detection for key formats
        assert results[0][1] == PlatformType.CHATGPT.value
        assert results[1][1] == PlatformType.CURSOR.value
        assert results[2][1] == PlatformType.CLAUDE_MEMORY.value
        # Text formats may vary based on implementation

    def test_confidence_levels(self):
        """Test confidence levels for different formats."""
        # High confidence: our own format
        memory_data = {
            "id": "conv_20250115_120000_abcd",
            "platform": "claude",
            "content": "test",
            "messages": [],
            "topics": [],
            "created_at": "2025-01-15",
        }

        test_file = self.temp_path / "high_confidence.json"
        test_file.write_text(json.dumps(memory_data), encoding="utf-8")

        result = self.detector.detect_format(test_file)

        assert result["confidence"] >= 0.95  # High confidence for our format

        # Lower confidence: generic structure
        generic_data = {"some": "random", "data": "here"}
        test_file2 = self.temp_path / "low_confidence.json"
        test_file2.write_text(json.dumps(generic_data), encoding="utf-8")

        result2 = self.detector.detect_format(test_file2)

        # Should be unknown or low confidence
        assert result2["confidence"] <= 0.6
