#!/usr/bin/env python3
"""
Test suite for ChatGPT importer.

Tests ChatGPT-specific conversation import functionality and OpenAI export format parsing.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

from importers.chatgpt_importer import ChatGPTImporter


class TestChatGPTImporter:
    """Test ChatGPT importer functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ChatGPTImporter(self.storage_path)

        # Load test data
        test_data_dir = Path(__file__).parent.parent / "data" / "chatgpt"
        with open(test_data_dir / "valid_export.json", encoding="utf-8") as f:
            self.valid_export = json.load(f)
        with open(test_data_dir / "malformed_export.json", encoding="utf-8") as f:
            self.malformed_export = json.load(f)

    def test_importer_initialization(self):
        """Test ChatGPT importer initialization."""
        assert self.importer.platform_name == "chatgpt"
        assert self.importer.storage_path == self.storage_path
        assert self.importer.logger is not None

    def test_get_supported_formats(self):
        """Test supported file formats."""
        formats = self.importer.get_supported_formats()
        assert formats == [".json"]

    def test_validate_chatgpt_format_valid(self):
        """Test ChatGPT format validation with valid data."""
        assert self.importer._validate_chatgpt_format(self.valid_export) is True

    def test_validate_chatgpt_format_invalid_structure(self):
        """Test ChatGPT format validation with invalid structure."""
        # Missing conversations array
        invalid_data = {"not_conversations": []}
        assert self.importer._validate_chatgpt_format(invalid_data) is False

        # Conversations not an array
        invalid_data = {"conversations": "not an array"}
        assert self.importer._validate_chatgpt_format(invalid_data) is False

        # Not a dictionary
        assert self.importer._validate_chatgpt_format("not a dict") is False

    def test_validate_chatgpt_format_empty_conversations(self):
        """Test ChatGPT format validation with empty conversations."""
        empty_data = {"conversations": []}
        assert self.importer._validate_chatgpt_format(empty_data) is True

    def test_validate_chatgpt_format_malformed_conversation(self):
        """Test ChatGPT format validation with malformed conversation."""
        malformed_data = {
            "conversations": [
                {"messages": "not an array"}  # Invalid messages structure
            ]
        }
        assert self.importer._validate_chatgpt_format(malformed_data) is False

    def test_parse_conversation_valid(self):
        """Test parsing valid ChatGPT conversation."""
        conv_data = self.valid_export["conversations"][0]
        conversation = self.importer.parse_conversation(conv_data)

        # Check basic fields
        assert conversation["platform_id"] == "conv-123e4567-e89b-12d3-a456-426614174000"
        assert conversation["title"] == "Python Programming Help"
        assert conversation["platform"] == "chatgpt"
        assert conversation["model"] == "gpt-4"  # Default assumption

        # Check content generation
        assert "**Human**:" in conversation["content"]
        assert "**Assistant**:" in conversation["content"]
        assert "How do I create a list in Python?" in conversation["content"]

        # Check messages
        assert len(conversation["messages"]) == 4
        assert conversation["messages"][0]["role"] == "user"
        assert conversation["messages"][1]["role"] == "assistant"

        # Check metadata
        assert conversation["platform_metadata"]["original_id"] == conv_data["id"]
        assert conversation["platform_metadata"]["message_count"] == 4

    def test_parse_conversation_with_model_hints(self):
        """Test parsing conversation with model hints in content."""
        conv_data = {
            "id": "test_conv",
            "title": "GPT-3.5 Test",
            "create_time": "2025-01-15T10:00:00Z",
            "messages": [
                {
                    "id": "msg1",
                    "role": "assistant",
                    "content": "I'm GPT-3.5 and I can help you with this task.",
                    "create_time": "2025-01-15T10:01:00Z",
                }
            ],
        }

        conversation = self.importer.parse_conversation(conv_data)
        assert conversation["model"] == "gpt-3.5-turbo"

    def test_parse_conversation_invalid_data(self):
        """Test parsing invalid conversation data."""
        with pytest.raises(TypeError, match="ChatGPT conversation data must be a dictionary"):
            self.importer.parse_conversation("not a dict")

    def test_parse_conversation_missing_messages(self):
        """Test parsing conversation with missing messages."""
        conv_data = {
            "id": "test_conv",
            "title": "Test",
            "create_time": "2025-01-15T10:00:00Z",
            # No messages field
        }

        conversation = self.importer.parse_conversation(conv_data)
        assert conversation["messages"] == []
        assert conversation["content"] == ""

    def test_parse_conversation_empty_messages(self):
        """Test parsing conversation with empty content messages."""
        conv_data = {
            "id": "test_conv",
            "title": "Test",
            "create_time": "2025-01-15T10:00:00Z",
            "messages": [
                {"role": "user", "content": ""},
                {"role": "user", "content": "   "},  # Whitespace only
                {"role": "user", "content": "Valid message"},
            ],
        }

        conversation = self.importer.parse_conversation(conv_data)
        # Should skip empty messages
        assert len(conversation["messages"]) == 1
        assert conversation["messages"][0]["content"] == "Valid message"

    def test_extract_model_info_default(self):
        """Test model extraction with default fallback."""
        conv_data = {"messages": []}
        model = self.importer._extract_model_info(conv_data)
        assert model == "gpt-4"

    def test_extract_model_info_explicit(self):
        """Test model extraction with explicit model field."""
        conv_data = {"model": "gpt-3.5-turbo", "messages": []}
        model = self.importer._extract_model_info(conv_data)
        assert model == "gpt-3.5-turbo"

    def test_extract_model_info_from_content(self):
        """Test model extraction from message content."""
        conv_data = {
            "messages": [{"role": "assistant", "content": "I'm powered by GPT-4 technology"}]
        }
        model = self.importer._extract_model_info(conv_data)
        assert model == "gpt-4"

    def test_process_conversations_success(self):
        """Test successful conversation processing."""
        conversations = self.valid_export["conversations"]
        test_file = self.storage_path / "test.json"

        # Mock save method to avoid file I/O
        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer._process_conversations(conversations, test_file)

        assert result.success is True
        assert result.conversations_imported == 2
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 2
        assert result.metadata["total_conversations_in_file"] == 2
        assert mock_save.call_count == 2

    def test_process_conversations_with_failures(self):
        """Test conversation processing with some failures."""
        conversations = self.malformed_export["conversations"]
        test_file = self.storage_path / "test.json"

        # Mock validation to fail for second conversation
        with patch.object(self.importer, "_validate_conversation") as mock_validate:
            # First succeeds, second fails
            mock_validate.side_effect = [True, False]
            with patch.object(self.importer, "_save_conversation"):
                result = self.importer._process_conversations(conversations, test_file)

        assert result.conversations_imported == 1
        assert result.conversations_failed == 1
        assert len(result.errors) == 1

    def test_process_conversations_parse_exception(self):
        """Test conversation processing with parsing exceptions."""
        conversations = [{"invalid": "data"}]
        test_file = self.storage_path / "test.json"

        # Mock parse_conversation to raise exception
        with patch.object(self.importer, "parse_conversation") as mock_parse:
            mock_parse.side_effect = Exception("Parse error")
            result = self.importer._process_conversations(conversations, test_file)

        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Parse error" in result.errors[0]

    def test_import_file_nonexistent(self):
        """Test importing non-existent file."""
        nonexistent_file = self.storage_path / "nonexistent.json"
        result = self.importer.import_file(nonexistent_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "File not found" in result.errors[0]

    def test_import_file_invalid_json(self):
        """Test importing file with invalid JSON."""
        invalid_file = self.storage_path / "invalid.json"
        invalid_file.write_text("{ invalid json }", encoding="utf-8")

        result = self.importer.import_file(invalid_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Invalid JSON format" in result.errors[0]

    def test_import_file_invalid_format(self):
        """Test importing file with invalid ChatGPT format."""
        invalid_file = self.storage_path / "invalid.json"
        invalid_file.write_text('{"not_conversations": []}', encoding="utf-8")

        result = self.importer.import_file(invalid_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "not a valid ChatGPT export format" in result.errors[0]

    def test_import_file_valid(self):
        """Test importing valid ChatGPT export file."""
        valid_file = self.storage_path / "valid.json"
        valid_file.write_text(json.dumps(self.valid_export), encoding="utf-8")

        # Mock save method to avoid file I/O
        with patch.object(self.importer, "_save_conversation"):
            result = self.importer.import_file(valid_file)

        assert result.success is True
        assert result.conversations_imported == 2
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 2
        assert result.metadata["platform"] == "chatgpt"
        assert result.metadata["import_format"] == "openai_export"

    def test_import_file_general_exception(self):
        """Test import file with general exception."""
        valid_file = self.storage_path / "valid.json"
        valid_file.write_text(json.dumps(self.valid_export), encoding="utf-8")

        # Mock to raise general exception
        with patch.object(self.importer, "_validate_chatgpt_format") as mock_validate:
            mock_validate.side_effect = Exception("General error")
            result = self.importer.import_file(valid_file)

        assert result.success is False
        assert "Import failed: General error" in result.errors[0]

    def test_save_conversation(self):
        """Test conversation saving functionality."""
        conversation = {
            "id": "conv_test_123",
            "title": "Test Conversation",
            "date": "2025-01-15T10:30:00Z",
            "content": "Test content",
        }

        file_path = self.importer._save_conversation(conversation)

        # Check file was created in correct location
        assert file_path.exists()
        assert file_path.parent.name == "01-january"
        assert file_path.parent.parent.name == "2025"
        assert file_path.name == "conv_test_123.json"

        # Check file content
        with open(file_path, encoding="utf-8") as f:
            saved_data = json.load(f)
        assert saved_data == conversation

    def test_extract_topics_chatgpt_specific(self):
        """Test ChatGPT-specific topic extraction."""
        content = "This is about OpenAI and GPT models for AI development."
        topics = self.importer._extract_topics(content)

        # Should include ChatGPT-specific topics
        assert "openai" in topics
        assert "gpt" in topics
        assert "ai" in topics
        assert "chatgpt" in topics  # Platform identifier

    def test_extract_topics_platform_identifier(self):
        """Test that platform identifier is always included."""
        content = "Generic conversation content without specific keywords."
        topics = self.importer._extract_topics(content)

        # Should always include platform identifier
        assert "chatgpt" in topics

    def test_extract_topics_limit_respected(self):
        """Test topic extraction respects 10-topic limit."""
        # Create content with many ChatGPT-related terms
        content = "openai gpt artificial intelligence language model prompt chatbot ai assistant machine learning neural networks deep learning natural language processing"
        topics = self.importer._extract_topics(content)

        assert len(topics) <= 10


class TestChatGPTImporterEdgeCases:
    """Test edge cases and error conditions for ChatGPT importer."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ChatGPTImporter(self.storage_path)

    def test_parse_conversation_no_title(self):
        """Test parsing conversation without title."""
        conv_data = {
            "id": "test_conv",
            "create_time": "2025-01-15T10:00:00Z",
            "messages": [],
        }

        conversation = self.importer.parse_conversation(conv_data)
        assert conversation["title"] == "Untitled ChatGPT Conversation"

    def test_parse_conversation_invalid_timestamps(self):
        """Test parsing conversation with invalid timestamps."""
        conv_data = {
            "id": "test_conv",
            "title": "Test",
            "create_time": "invalid-date",
            "messages": [
                {
                    "id": "msg1",
                    "role": "user",
                    "content": "Test",
                    "create_time": "also-invalid",
                }
            ],
        }

        conversation = self.importer.parse_conversation(conv_data)
        # Should handle gracefully and use current time
        assert "date" in conversation
        assert len(conversation["messages"]) == 1

    def test_parse_conversation_mixed_message_types(self):
        """Test parsing conversation with mixed valid/invalid messages."""
        conv_data = {
            "id": "test_conv",
            "title": "Test",
            "create_time": "2025-01-15T10:00:00Z",
            "messages": [
                "not a dict",  # Invalid
                {
                    "role": "user",
                    "content": "Valid message",
                    "create_time": "2025-01-15T10:01:00Z",
                },
                {
                    "role": "assistant",
                    "content": "",  # Empty content - should be skipped
                    "create_time": "2025-01-15T10:02:00Z",
                },
            ],
        }

        conversation = self.importer.parse_conversation(conv_data)
        # Should only include valid messages with content
        assert len(conversation["messages"]) == 1
        assert conversation["messages"][0]["content"] == "Valid message"

    def test_validate_chatgpt_format_edge_cases(self):
        """Test ChatGPT format validation edge cases."""
        # Empty messages array is valid
        data = {"conversations": [{"messages": []}]}
        assert self.importer._validate_chatgpt_format(data) is True

        # Message without role/content should fail
        data = {
            "conversations": [
                {
                    "messages": [
                        {"id": "msg1"}  # Missing role and content
                    ]
                }
            ]
        }
        assert self.importer._validate_chatgpt_format(data) is False


class TestChatGPTUniversalMetadata:
    """ChatGPT importer populates universal metadata fields (5.1.3-5.2.4)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ChatGPTImporter(self.storage_path)

    def _base_payload(self, **overrides):
        payload = {
            "id": "fallback-id",
            "title": "Test",
            "create_time": "2025-01-15T10:30:00Z",
            "messages": [
                {
                    "role": "user",
                    "content": "hi",
                    "create_time": "2025-01-15T10:30:00Z",
                },
                {
                    "role": "assistant",
                    "content": "hello",
                    "create_time": "2025-01-15T10:31:00Z",
                },
            ],
        }
        payload.update(overrides)
        return payload

    def test_session_id_uses_conversation_id_when_available(self):
        """ChatGPT's conversation_id maps to universal session_id."""
        payload = self._base_payload(conversation_id="conv-real-uuid")
        conv = self.importer.parse_conversation(payload)
        assert conv["session_id"] == "conv-real-uuid"

    def test_session_id_falls_back_to_id(self):
        """When conversation_id is absent the legacy 'id' becomes session_id."""
        payload = self._base_payload()  # only 'id', no 'conversation_id'
        conv = self.importer.parse_conversation(payload)
        assert conv["session_id"] == "fallback-id"

    def test_user_id_passes_through_when_present(self):
        """A caller-injected user_id flows through to the universal field."""
        payload = self._base_payload(user_id="user-123")
        conv = self.importer.parse_conversation(payload)
        assert conv["user_id"] == "user-123"

    def test_user_id_default_none(self):
        """Standard ChatGPT exports omit user_id; default is None."""
        conv = self.importer.parse_conversation(self._base_payload())
        assert conv["user_id"] is None

    def test_tags_include_starred_archived_and_gizmo(self):
        """Starred/archived/gizmo signals become tags."""
        payload = self._base_payload(is_starred=True, is_archived=True, gizmo_id="g-abc")
        conv = self.importer.parse_conversation(payload)
        assert "starred" in conv["tags"]
        assert "archived" in conv["tags"]
        assert "gizmo:g-abc" in conv["tags"]

    def test_tags_explicit_tags_appended(self):
        """Caller-supplied tags are merged in."""
        payload = self._base_payload(tags=["work", "ml"])
        conv = self.importer.parse_conversation(payload)
        assert "work" in conv["tags"]
        assert "ml" in conv["tags"]

    def test_tags_default_empty(self):
        """No tag-worthy signals => empty tags list."""
        conv = self.importer.parse_conversation(self._base_payload())
        assert conv["tags"] == []

    def test_conversation_type_explicit_wins(self):
        payload = self._base_payload(conversation_type="analysis")
        conv = self.importer.parse_conversation(payload)
        assert conv["conversation_type"] == "analysis"

    def test_conversation_type_code_heuristic(self):
        """Heavy code-fence content triggers the 'code' classification."""
        code_blob = "```python\nprint('x')\n```\n```bash\nls\n```"
        payload = self._base_payload(
            messages=[
                {
                    "role": "user",
                    "content": code_blob,
                    "create_time": "2025-01-15T10:30:00Z",
                },
                {
                    "role": "assistant",
                    "content": code_blob,
                    "create_time": "2025-01-15T10:31:00Z",
                },
            ],
        )
        conv = self.importer.parse_conversation(payload)
        assert conv["conversation_type"] == "code"

    def test_conversation_type_default_chat(self):
        """Plain chat content defaults to 'chat'."""
        conv = self.importer.parse_conversation(self._base_payload())
        assert conv["conversation_type"] == "chat"

    def test_custom_fields_capture_extras(self):
        """Optional ChatGPT-specific keys are captured into custom_fields."""
        payload = self._base_payload(
            default_model_slug="gpt-4o",
            gizmo_id="g-1",
            memory_scope="user_memory",
            custom_fields={"experiment": "alpha"},
        )
        conv = self.importer.parse_conversation(payload)
        assert conv["custom_fields"]["default_model_slug"] == "gpt-4o"
        assert conv["custom_fields"]["gizmo_id"] == "g-1"
        assert conv["custom_fields"]["memory_scope"] == "user_memory"
        assert conv["custom_fields"]["experiment"] == "alpha"

    def test_custom_fields_default_empty(self):
        """Standard exports without optional keys produce an empty dict."""
        conv = self.importer.parse_conversation(self._base_payload())
        assert conv["custom_fields"] == {}
