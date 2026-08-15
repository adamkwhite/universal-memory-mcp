#!/usr/bin/env python3
"""
Test suite for ClaudeImporter.

Tests Claude conversation import functionality for various export formats.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

from importers.claude_importer import ClaudeImporter


class TestClaudeImporter:
    """Test ClaudeImporter core functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_importer_initialization(self):
        """Test ClaudeImporter initialization."""
        importer = ClaudeImporter(self.storage_path)
        assert importer.storage_path == self.storage_path
        assert importer.platform_name == "claude"
        assert importer.logger is not None

    def test_get_supported_formats(self):
        """Test supported file formats."""
        formats = self.importer.get_supported_formats()
        expected_formats = [".json", ".md", ".txt"]
        for fmt in expected_formats:
            assert fmt in formats

    def test_import_file_nonexistent(self):
        """Test importing non-existent file."""
        non_existent = self.storage_path / "does_not_exist.json"
        result = self.importer.import_file(non_existent)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "File not found" in result.errors[0]

    def test_import_file_general_exception(self):
        """Test import with general exception."""
        test_file = self.storage_path / "test.json"
        test_file.write_text('{"test": "data"}')

        with patch.object(
            self.importer, "_import_json_format", side_effect=Exception("Test error")
        ):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Import failed" in result.errors[0]


class TestClaudeImporterJSONFormat:
    """Test ClaudeImporter JSON format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_import_claude_memory_format(self):
        """Test importing existing Claude Memory format."""
        memory_data = {
            "id": "conv_20250115_120000_abcd1234",
            "platform": "claude",
            "title": "Test Claude Memory Conversation",
            "content": "**Human**: Hello Claude\n\n**Claude**: Hello! How can I help you?",
            "messages": [
                {
                    "role": "user",
                    "content": "Hello Claude",
                    "timestamp": "2025-01-15T12:00:00Z",
                },
                {
                    "role": "assistant",
                    "content": "Hello! How can I help you?",
                    "timestamp": "2025-01-15T12:01:00Z",
                },
            ],
            "date": "2025-01-15T12:00:00Z",
            "topics": ["greeting"],
            "created_at": "2025-01-15T12:00:00Z",
        }

        test_file = self.storage_path / "claude_memory.json"
        test_file.write_text(json.dumps(memory_data))

        result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert result.metadata["format"] == "claude_memory"
        assert result.metadata["already_imported"] is True
        assert result.imported_ids == ["conv_20250115_120000_abcd1234"]

    def test_import_json_invalid_format(self):
        """Test importing invalid JSON."""
        test_file = self.storage_path / "invalid.json"
        test_file.write_text('{"invalid": json syntax}')

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Invalid JSON format" in result.errors[0]

    def test_import_json_unsupported_format(self):
        """Test importing JSON with unsupported Claude format."""
        unsupported_data = {"not_claude": "data", "random": "fields"}

        test_file = self.storage_path / "unsupported.json"
        test_file.write_text(json.dumps(unsupported_data))

        result = self.importer.import_file(test_file)

        # Should successfully import as generic Claude JSON
        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert result.metadata["format"] == "claude_generic_json"


class TestClaudeImporterTextFormat:
    """Test ClaudeImporter text format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_import_claude_web_markdown(self):
        """Test importing Claude web interface markdown."""
        markdown_content = """# Conversation with Claude

**Human**: Hello Claude, how are you today?

**Claude**: Hello! I'm doing well, thank you for asking. I'm here and ready to help with any questions or tasks you might have. How are you doing today?
"""

        test_file = self.storage_path / "claude_web.md"
        test_file.write_text(markdown_content)

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_text_exception(self):
        """Test text import with exception."""
        test_file = self.storage_path / "test.txt"
        test_file.write_text("Test content")

        with patch.object(
            self.importer, "_import_text_format", side_effect=Exception("Parse error")
        ):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Import failed" in result.errors[0]


class TestClaudeImporterParsingMethods:
    """Test ClaudeImporter parsing methods."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_parse_conversation_dict(self):
        """Test parsing dict as conversation."""
        data = {
            "title": "Test Conv",
            "content": "Test content",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        result = self.importer.parse_conversation(data)

        assert result["platform"] == "claude"
        assert result["title"] == "Test Conv"
        assert len(result["messages"]) == 1

    def test_parse_conversation_invalid_type(self):
        """Test parsing invalid type raises TypeError."""
        with pytest.raises(TypeError, match="Claude conversation data must be"):
            self.importer.parse_conversation(123)

    def test_detect_claude_format_memory(self):
        """Test Claude Memory format detection."""
        data = {
            "id": "conv_20250115_120000_abcd",
            "platform": "claude",
            "content": "test",
            "messages": [],
            "topics": [],
            "created_at": "2025-01-15",
        }

        result = self.importer._is_claude_memory_format(data)
        assert result is True

    def test_detect_claude_format_unknown(self):
        """Test unknown format detection."""
        data = {"random": "data"}

        result = self.importer._is_claude_memory_format(data)
        assert result is False


class TestClaudeImporterSaveConversation:
    """Test ClaudeImporter conversation saving."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_save_conversation(self):
        """Test saving conversation to storage."""
        conversation = {
            "id": "claude_20250115_120000_abcd1234",
            "date": "2025-01-15T12:00:00",
            "title": "Test Claude Conversation",
            "content": "Test content",
            "platform": "claude",
        }

        file_path = self.importer._save_conversation(conversation)

        # Verify file was created
        assert file_path.exists()
        assert "2025" in str(file_path)
        assert "01-january" in str(file_path)
        assert file_path.name.endswith(".json")

        # Verify content
        with open(file_path) as f:
            saved_data = json.load(f)

        assert saved_data["id"] == conversation["id"]
        assert saved_data["platform"] == "claude"


class TestClaudeImporterIntegration:
    """Test ClaudeImporter integration scenarios."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def test_end_to_end_claude_memory_import(self):
        """Test complete end-to-end Claude Memory import workflow."""
        claude_data = {
            "id": "conv_20250115_090000_e2etest",
            "platform": "claude",
            "title": "E2E Claude Memory Test",
            "content": "**Human**: Test the Claude importer\n\n**Claude**: Testing the Claude Memory import functionality.",
            "messages": [
                {
                    "role": "user",
                    "content": "Test the Claude importer",
                    "timestamp": "2025-01-15T09:00:00Z",
                },
                {
                    "role": "assistant",
                    "content": "Testing the Claude Memory import functionality.",
                    "timestamp": "2025-01-15T09:01:00Z",
                },
            ],
            "date": "2025-01-15T09:00:00Z",
            "topics": ["testing", "import"],
            "created_at": "2025-01-15T09:00:00Z",
        }

        test_file = self.storage_path / "claude_e2e_test.json"
        test_file.write_text(json.dumps(claude_data))

        result = self.importer.import_file(test_file)

        # Verify import success
        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 1

        # Verify metadata
        assert result.metadata["platform"] == "claude"
        # Resolve both sides: on Windows the fixture path arrives as the 8.3
        # short name (C:\Users\RUNNER~1) while the importer records the long
        # form (C:\Users\runneradmin). Same file, different spelling.
        assert Path(result.metadata["source_file"]).resolve() == Path(test_file).resolve()

        # Verify Claude Memory format was recognized (no new file created,
        # existing format validated)
        assert result.metadata["format"] == "claude_memory"
        assert result.metadata["already_imported"] is True

        # For Claude Memory format, the original file IS the conversation
        # (no separate conversation file is created)
        assert test_file.exists()

        with open(test_file) as f:
            original_data = json.load(f)

        assert original_data["platform"] == "claude"
        assert original_data["id"] == "conv_20250115_090000_e2etest"
        assert len(original_data["messages"]) == 2
        assert "Claude Memory import" in original_data["content"]


class TestClaudeUniversalMetadata:
    """Claude importer populates universal metadata fields (5.1.3-5.2.4)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = ClaudeImporter(self.storage_path)

    def _base_payload(self, **overrides):
        payload = {
            "id": "claude-conv-9",
            "title": "Claude Test",
            "date": "2025-03-01T09:00:00",
            "content": "Hello world",
            "messages": [
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": "pong"},
            ],
            "model": "claude-3.5-sonnet",
        }
        payload.update(overrides)
        return payload

    def test_session_id_uses_explicit_session_id(self):
        conv = self.importer._parse_claude_json(self._base_payload(session_id="claude-sess-1"))
        assert conv["session_id"] == "claude-sess-1"

    def test_session_id_falls_back_to_conversation_id(self):
        conv = self.importer._parse_claude_json(self._base_payload(conversation_id="claude-conv-2"))
        assert conv["session_id"] == "claude-conv-2"

    def test_session_id_falls_back_to_platform_id(self):
        """When neither session_id nor conversation_id present, 'id' is used."""
        conv = self.importer._parse_claude_json(self._base_payload())
        assert conv["session_id"] == "claude-conv-9"

    def test_user_id_passes_through(self):
        conv = self.importer._parse_claude_json(self._base_payload(user_id="claude-user-x"))
        assert conv["user_id"] == "claude-user-x"

    def test_user_id_falls_back_to_account_id(self):
        conv = self.importer._parse_claude_json(self._base_payload(account_id="acct-7"))
        assert conv["user_id"] == "acct-7"

    def test_tags_include_variant(self):
        """The detected Claude variant is exposed as a tag."""
        conv = self.importer._parse_claude_json(self._base_payload())
        # variant detection from generic data => 'claude_generic'
        assert any(t.startswith("variant:") for t in conv["tags"])

    def test_tags_explicit_appended(self):
        conv = self.importer._parse_claude_json(self._base_payload(tags=["research", "deep-dive"]))
        assert "research" in conv["tags"]
        assert "deep-dive" in conv["tags"]

    def test_conversation_type_default_chat(self):
        conv = self.importer._parse_claude_json(self._base_payload())
        assert conv["conversation_type"] == "chat"

    def test_conversation_type_code_heuristic(self):
        code = "```py\nx=1\n```\n```py\ny=2\n```"
        conv = self.importer._parse_claude_json(self._base_payload(content=code))
        assert conv["conversation_type"] == "code"

    def test_conversation_type_explicit_overrides(self):
        conv = self.importer._parse_claude_json(self._base_payload(conversation_type="creative"))
        assert conv["conversation_type"] == "creative"

    def test_custom_fields_capture_optional_keys(self):
        conv = self.importer._parse_claude_json(
            self._base_payload(
                project_id="proj-1",
                organization_id="org-2",
                workspace_id="ws-3",
                custom_fields={"flow": "ad-hoc"},
            )
        )
        assert conv["custom_fields"]["project_id"] == "proj-1"
        assert conv["custom_fields"]["organization_id"] == "org-2"
        assert conv["custom_fields"]["workspace_id"] == "ws-3"
        assert conv["custom_fields"]["flow"] == "ad-hoc"

    def test_custom_fields_default_empty(self):
        conv = self.importer._parse_claude_json(self._base_payload())
        assert conv["custom_fields"] == {}
