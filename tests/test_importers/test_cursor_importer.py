#!/usr/bin/env python3
"""
Test suite for CursorImporter.

Tests Cursor AI session import functionality and conversation format conversion.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

from importers.cursor_importer import CursorImporter


class TestCursorImporter:
    """Test CursorImporter core functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_importer_initialization(self):
        """Test CursorImporter initialization."""
        importer = CursorImporter(self.storage_path)
        assert importer.storage_path == self.storage_path
        assert importer.platform_name == "cursor"
        assert importer.logger is not None

    def test_get_supported_formats(self):
        """Test supported file formats."""
        formats = self.importer.get_supported_formats()
        assert ".json" in formats
        assert isinstance(formats, list)

    def test_import_file_nonexistent(self):
        """Test importing non-existent file."""
        non_existent = self.storage_path / "does_not_exist.json"
        result = self.importer.import_file(non_existent)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "File not found" in result.errors[0]

    def test_import_file_invalid_json(self):
        """Test importing invalid JSON file."""
        test_file = self.storage_path / "invalid.json"
        test_file.write_text('{"invalid": json syntax}', encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Invalid JSON format" in result.errors[0]

    def test_import_file_invalid_format(self):
        """Test importing file with invalid Cursor format."""
        invalid_data = {"not_cursor": "data"}

        test_file = self.storage_path / "invalid_cursor.json"
        test_file.write_text(json.dumps(invalid_data), encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "valid Cursor AI export format" in result.errors[0]

    def test_import_file_valid(self):
        """Test importing valid Cursor session."""
        cursor_data = {
            "session_id": "test-session-123",
            "workspace": "/path/to/project",
            "model": "claude-3-sonnet",
            "created_at": "2025-01-15T10:00:00Z",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "Help me with this code",
                    "timestamp": "2025-01-15T10:00:00Z",
                    "files": ["main.py"],
                },
                {
                    "type": "ai_response",
                    "content": "I can help you with your code",
                    "timestamp": "2025-01-15T10:01:00Z",
                },
            ],
        }

        test_file = self.storage_path / "cursor_session.json"
        test_file.write_text(json.dumps(cursor_data), encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 1
        assert result.metadata["platform"] == "cursor"
        mock_save.assert_called_once()

    def test_import_file_general_exception(self):
        """Test import with general exception."""
        test_file = self.storage_path / "test.json"
        test_file.write_text('{"session_id": "test"}', encoding="utf-8")

        with patch.object(
            self.importer,
            "_validate_cursor_format",
            side_effect=Exception("Test error"),
        ):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Import failed" in result.errors[0]


class TestCursorImporterValidation:
    """Test CursorImporter validation methods."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_validate_cursor_format_valid(self):
        """Test validation with valid Cursor format."""
        data = {
            "session_id": "test-session",
            "workspace": "/path/to/project",
            "interactions": [{"type": "user_input", "content": "Hello"}],
        }

        result = self.importer._validate_cursor_format(data)
        assert result is True

    def test_validate_cursor_format_invalid_structure(self):
        """Test validation with invalid structure."""
        data = {"not_cursor": "data"}

        result = self.importer._validate_cursor_format(data)
        assert result is False

    def test_validate_cursor_format_missing_required_fields(self):
        """Test validation with missing required fields."""
        data = {
            "session_id": "test",
            # Missing workspace and interactions
        }

        result = self.importer._validate_cursor_format(data)
        assert result is False

    def test_validate_cursor_format_invalid_interactions(self):
        """Test validation with invalid interactions format."""
        data = {
            "session_id": "test",
            "workspace": "/path",
            "interactions": "not an array",
        }

        result = self.importer._validate_cursor_format(data)
        assert result is False


class TestCursorImporterParsing:
    """Test CursorImporter conversation parsing."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_parse_conversation_valid(self):
        """Test parsing valid Cursor session."""
        data = {
            "session_id": "parse-test-123",
            "workspace": "/my/project",
            "model": "claude-3-sonnet",
            "created_at": "2025-01-15T10:00:00Z",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "Write a function",
                    "timestamp": "2025-01-15T10:00:00Z",
                    "files": ["utils.py", "main.py"],
                },
                {
                    "type": "ai_response",
                    "content": "Here's a function for you",
                    "timestamp": "2025-01-15T10:01:00Z",
                    "changes": ["modified utils.py"],
                },
            ],
        }

        conversation = self.importer.parse_conversation(data)

        # Verify universal format fields
        assert conversation["platform"] == "cursor"
        assert conversation["platform_id"] == "parse-test-123"
        assert "Cursor Session" in conversation["title"]
        assert conversation["model"] == "claude-3-sonnet"
        assert len(conversation["messages"]) == 2

        # Verify message structure
        assert conversation["messages"][0]["role"] == "user"
        assert conversation["messages"][1]["role"] == "assistant"

        # Verify content includes session header
        assert "/my/project" in conversation["content"]
        assert "claude-3-sonnet" in conversation["content"]

        # Verify topics
        assert "cursor" in conversation["topics"]

        # Verify session context
        assert conversation["session_context"]["workspace"] == "/my/project"
        assert conversation["session_context"]["model"] == "claude-3-sonnet"

    def test_parse_conversation_minimal(self):
        """Test parsing minimal Cursor session."""
        data = {
            "session_id": "minimal-test",
            "workspace": "/project",
            "interactions": [],
        }

        conversation = self.importer.parse_conversation(data)

        assert conversation["platform"] == "cursor"
        assert conversation["platform_id"] == "minimal-test"
        assert conversation["model"] == "cursor-ai"
        assert len(conversation["messages"]) == 0

    def test_parse_conversation_invalid_data(self):
        """Test parsing invalid conversation data."""
        data = "not a dictionary"

        with pytest.raises(TypeError, match="Cursor session data must be a dictionary"):
            self.importer.parse_conversation(data)

    def test_parse_conversation_missing_interactions(self):
        """Test parsing session without interactions."""
        data = {
            "session_id": "no-interactions",
            "workspace": "/project",
            # Missing interactions
        }

        conversation = self.importer.parse_conversation(data)

        assert conversation["platform"] == "cursor"
        assert len(conversation["messages"]) == 0

    def test_parse_conversation_invalid_timestamps(self):
        """Test parsing with invalid timestamps."""
        data = {
            "session_id": "invalid-timestamps",
            "workspace": "/project",
            "created_at": "invalid-date",
            "interactions": [
                {"type": "user_input", "content": "Hello", "timestamp": "also-invalid"}
            ],
        }

        # Should handle gracefully with current time fallbacks
        conversation = self.importer.parse_conversation(data)

        assert conversation["platform"] == "cursor"
        assert len(conversation["messages"]) == 1


class TestCursorImporterHelperMethods:
    """Test CursorImporter helper methods."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_add_session_header(self):
        """Test _add_session_header method."""
        content_parts = []
        self.importer._add_session_header(content_parts, "/my/project", "claude-3", "session-123")

        assert "# Cursor AI Session" in content_parts
        assert "**Workspace**: /my/project" in content_parts
        assert "**Model**: claude-3" in content_parts
        assert "**Session ID**: session-123" in content_parts

    def test_process_single_interaction_user_input(self):
        """Test _process_single_interaction with user input."""
        interaction = {
            "type": "user_input",
            "content": "Help me debug this",
            "timestamp": "2025-01-15T10:00:00Z",
            "files": ["debug.py"],
        }
        date = datetime.now()

        result = self.importer._process_single_interaction(interaction, date)

        assert result is not None
        message, content_display = result
        assert message["role"] == "user"
        assert "Help me debug this" in message["content"]
        assert "**Human**:" in content_display
        assert "Files: debug.py" in message["content"]

    def test_process_single_interaction_ai_response(self):
        """Test _process_single_interaction with AI response."""
        interaction = {
            "type": "ai_response",
            "content": "Here's the solution",
            "timestamp": "2025-01-15T10:01:00Z",
            "changes": ["modified debug.py", "added test.py"],
        }
        date = datetime.now()

        result = self.importer._process_single_interaction(interaction, date)

        assert result is not None
        message, content_display = result
        assert message["role"] == "assistant"
        assert "Here's the solution" in message["content"]
        assert "**Cursor AI**:" in content_display
        assert "2 file(s) modified" in message["content"]

    def test_process_single_interaction_empty_content(self):
        """Test _process_single_interaction with empty content."""
        interaction = {
            "type": "user_input",
            "content": "",
            "timestamp": "2025-01-15T10:00:00Z",
        }
        date = datetime.now()

        result = self.importer._process_single_interaction(interaction, date)

        assert result is None  # Should skip empty interactions

    def test_get_role_info(self):
        """Test _get_role_info method."""
        # Test user input
        role, display = self.importer._get_role_info("user_input")
        assert role == "user"
        assert display == "**Human**"

        # Test AI response
        role, display = self.importer._get_role_info("ai_response")
        assert role == "assistant"
        assert display == "**Cursor AI**"

        # Test unknown type
        role, display = self.importer._get_role_info("unknown_type")
        assert role == "system"
        assert display == "**Unknown_Type**"

    def test_enhance_interaction_content(self):
        """Test _enhance_interaction_content method."""
        interaction = {
            "files": ["main.py", "utils.py"],
            "changes": ["modified main.py"],
        }
        content = "Original content"

        enhanced = self.importer._enhance_interaction_content(interaction, content)

        assert "Original content" in enhanced
        assert "Files: main.py, utils.py" in enhanced
        assert "1 file(s) modified" in enhanced

    def test_enhance_interaction_content_no_extras(self):
        """Test _enhance_interaction_content with no extra data."""
        interaction = {}
        content = "Just content"

        enhanced = self.importer._enhance_interaction_content(interaction, content)

        assert enhanced == "Just content"

    def test_create_interaction_metadata(self):
        """Test _create_interaction_metadata method."""
        interaction = {
            "type": "user_input",
            "files": ["test.py"],
            "changes": ["added feature"],
        }

        metadata = self.importer._create_interaction_metadata(interaction)

        assert metadata["interaction_type"] == "user_input"
        assert metadata["platform"] == "cursor"
        assert metadata["files"] == ["test.py"]
        assert metadata["changes"] == ["added feature"]

    def test_create_interaction_metadata_minimal(self):
        """Test _create_interaction_metadata with minimal data."""
        interaction = {"type": "ai_response"}

        metadata = self.importer._create_interaction_metadata(interaction)

        assert metadata["interaction_type"] == "ai_response"
        assert metadata["platform"] == "cursor"
        assert "files" not in metadata
        assert "changes" not in metadata


class TestCursorImporterSaveConversation:
    """Test CursorImporter conversation saving."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_save_conversation(self):
        """Test saving conversation to storage."""
        conversation = {
            "id": "conv_20250115_120000_abcd1234",
            "date": "2025-01-15T12:00:00",
            "title": "Test Cursor Session",
            "content": "Test content",
            "platform": "cursor",
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
        assert saved_data["platform"] == "cursor"


class TestCursorImporterIntegration:
    """Test CursorImporter integration scenarios."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def test_end_to_end_import(self):
        """Test complete end-to-end import workflow."""
        cursor_data = {
            "session_id": "e2e-test-session",
            "workspace": "/my/coding/project",
            "model": "claude-3.5-sonnet",
            "created_at": "2025-01-15T09:00:00Z",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "I need help implementing a binary search algorithm",
                    "timestamp": "2025-01-15T09:00:00Z",
                    "files": ["algorithms.py"],
                },
                {
                    "type": "ai_response",
                    "content": "I'll help you implement a binary search. Here's an efficient implementation...",
                    "timestamp": "2025-01-15T09:01:30Z",
                    "changes": ["modified algorithms.py"],
                },
                {
                    "type": "user_input",
                    "content": "Can you add unit tests for this function?",
                    "timestamp": "2025-01-15T09:05:00Z",
                    "files": ["algorithms.py"],
                },
                {
                    "type": "ai_response",
                    "content": "Absolutely! Here are comprehensive unit tests...",
                    "timestamp": "2025-01-15T09:07:15Z",
                    "changes": ["created test_algorithms.py"],
                },
            ],
        }

        test_file = self.storage_path / "complete_session.json"
        test_file.write_text(json.dumps(cursor_data), encoding="utf-8")

        result = self.importer.import_file(test_file)

        # Verify import success
        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 1

        # Verify metadata
        assert result.metadata["platform"] == "cursor"
        # Resolve both sides: on Windows the fixture path arrives as the 8.3
        # short name (C:\Users\RUNNER~1) while the importer records the long
        # form (C:\Users\runneradmin). Same file, different spelling.
        assert Path(result.metadata["source_file"]).resolve() == Path(test_file).resolve()
        assert result.metadata["import_format"] == "cursor_session"

        # Verify conversation file was created (exclude source file)
        conversation_files = [
            f for f in self.storage_path.rglob("*.json") if f.name != "complete_session.json"
        ]
        assert len(conversation_files) == 1

        # Verify conversation content
        with open(conversation_files[0]) as f:
            saved_conversation = json.load(f)

        assert saved_conversation["platform"] == "cursor"
        assert saved_conversation["platform_id"] == "e2e-test-session"
        assert len(saved_conversation["messages"]) == 4
        assert "binary search" in saved_conversation["content"]
        assert "claude-3.5-sonnet" in saved_conversation["content"]
        assert "/my/coding/project" in saved_conversation["content"]

    def test_import_with_complex_interactions(self):
        """Test import with complex interaction types."""
        complex_data = {
            "session_id": "complex-interactions",
            "workspace": "/complex/project",
            "model": "claude-3-opus",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "Review this code for security issues",
                    "files": ["auth.py", "user_model.py", "config.py"],
                    "metadata": {"review_type": "security"},
                },
                {
                    "type": "ai_response",
                    "content": "I've identified several security concerns...",
                    "changes": ["modified auth.py", "added security_utils.py"],
                    "metadata": {"confidence": "high"},
                },
                {
                    "type": "system_event",
                    "content": "Code analysis completed",
                    "metadata": {"duration": "45s"},
                },
            ],
        }

        test_file = self.storage_path / "complex_session.json"
        test_file.write_text(json.dumps(complex_data), encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1

        # Verify complex interactions were processed (exclude source file)
        conversation_files = [
            f for f in self.storage_path.rglob("*.json") if f.name != "complex_session.json"
        ]
        with open(conversation_files[0]) as f:
            conversation = json.load(f)

        assert "messages" in conversation
        messages = conversation["messages"]
        assert len(messages) >= 2  # At least user and AI messages

        # Check message roles
        roles = [msg["role"] for msg in messages]
        assert "user" in roles
        assert "assistant" in roles

        # Verify content includes expected patterns
        assert "auth.py" in conversation["messages"][0]["content"]
        assert "security concerns" in conversation["messages"][1]["content"]
        assert "modified" in conversation["messages"][1]["content"]


class TestCursorUniversalMetadata:
    """Cursor importer populates universal metadata fields (5.1.3-5.2.4)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = CursorImporter(self.storage_path)

    def _base_session(self, **overrides):
        session = {
            "session_id": "sess-cursor-001",
            "workspace": "/home/dev/myproject",
            "timestamp": "2025-02-01T08:00:00Z",
            "model": "claude-3.5-sonnet",
            "interactions": [
                {
                    "type": "user_input",
                    "content": "Refactor this function",
                    "files": ["src/main.py"],
                    "timestamp": "2025-02-01T08:00:00Z",
                },
                {
                    "type": "ai_response",
                    "content": "Done.",
                    "changes": [{"file": "src/main.py", "diff": "..."}],
                    "timestamp": "2025-02-01T08:00:30Z",
                },
            ],
        }
        session.update(overrides)
        return session

    def test_session_id_from_cursor_session(self):
        """Cursor's native session_id maps directly to universal session_id."""
        conv = self.importer.parse_conversation(self._base_session())
        assert conv["session_id"] == "sess-cursor-001"

    def test_session_id_none_when_blank(self):
        """Empty/blank session_id collapses to None (not empty string)."""
        conv = self.importer.parse_conversation(self._base_session(session_id=""))
        assert conv["session_id"] is None

    def test_user_id_passes_through(self):
        conv = self.importer.parse_conversation(self._base_session(user_id="dev-007"))
        assert conv["user_id"] == "dev-007"

    def test_user_id_default_none(self):
        conv = self.importer.parse_conversation(self._base_session())
        assert conv["user_id"] is None

    def test_tags_include_workspace_and_file_changes(self):
        """Workspace name and file-change presence appear as tags."""
        conv = self.importer.parse_conversation(self._base_session())
        assert "workspace:myproject" in conv["tags"]
        assert "has-file-changes" in conv["tags"]

    def test_tags_explicit_appended(self):
        conv = self.importer.parse_conversation(self._base_session(tags=["sprint-7", "urgent"]))
        assert "sprint-7" in conv["tags"]
        assert "urgent" in conv["tags"]

    def test_conversation_type_defaults_code(self):
        """Cursor sessions default to 'code' since the platform is an IDE."""
        conv = self.importer.parse_conversation(self._base_session())
        assert conv["conversation_type"] == "code"

    def test_conversation_type_explicit_overrides(self):
        conv = self.importer.parse_conversation(self._base_session(conversation_type="analysis"))
        assert conv["conversation_type"] == "analysis"

    def test_custom_fields_capture_workspace_and_files(self):
        conv = self.importer.parse_conversation(self._base_session())
        assert conv["custom_fields"]["workspace_path"] == "/home/dev/myproject"
        assert conv["custom_fields"]["files_involved"] == ["src/main.py"]

    def test_custom_fields_caller_overrides_merged(self):
        """Caller-supplied custom_fields are merged on top of defaults."""
        conv = self.importer.parse_conversation(
            self._base_session(custom_fields={"experiment": "beta", "workspace_path": "override"})
        )
        assert conv["custom_fields"]["experiment"] == "beta"
        # Caller wins on key collision
        assert conv["custom_fields"]["workspace_path"] == "override"
