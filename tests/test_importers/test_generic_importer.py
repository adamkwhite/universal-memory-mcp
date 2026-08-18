#!/usr/bin/env python3
"""
Test suite for GenericImporter.

Tests generic conversation import functionality for various file formats.
"""

import csv
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

from universal_memory_mcp.importers.generic_importer import GenericImporter


class TestGenericImporter:
    """Test GenericImporter core functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_importer_initialization(self):
        """Test GenericImporter initialization."""
        importer = GenericImporter(self.storage_path)
        assert importer.storage_path == self.storage_path
        assert importer.platform_name == "generic"
        assert importer.logger is not None

    def test_get_supported_formats(self):
        """Test supported file formats."""
        formats = self.importer.get_supported_formats()
        expected_formats = [".json", ".md", ".txt", ".csv", ".xml"]
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
        test_file.write_text('{"test": "data"}', encoding="utf-8")

        with patch.object(
            self.importer, "_import_json_format", side_effect=Exception("Test error")
        ):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Import failed" in result.errors[0]


class TestGenericImporterJSONFormat:
    """Test GenericImporter JSON format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_import_json_simple_conversation(self):
        """Test importing simple JSON conversation."""
        json_data = {
            "title": "Test Conversation",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        }

        test_file = self.storage_path / "simple.json"
        test_file.write_text(json.dumps(json_data), encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_json_array_of_conversations(self):
        """Test importing JSON array of conversations."""
        json_data = [
            {
                "title": "Conv 1",
                "content": "First conversation",
                "messages": [{"role": "user", "content": "Hello 1"}],
            },
            {
                "title": "Conv 2",
                "content": "Second conversation",
                "messages": [{"role": "user", "content": "Hello 2"}],
            },
        ]

        test_file = self.storage_path / "array.json"
        test_file.write_text(json.dumps(json_data), encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 2
        assert result.conversations_failed == 0
        assert mock_save.call_count == 2

    def test_import_json_invalid_format(self):
        """Test importing invalid JSON."""
        test_file = self.storage_path / "invalid.json"
        test_file.write_text('{"invalid": json syntax}', encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Invalid JSON format" in result.errors[0]

    def test_import_json_unsupported_structure(self):
        """Test importing JSON with unsupported structure."""
        json_data = "just a string"

        test_file = self.storage_path / "unsupported.json"
        test_file.write_text(json.dumps(json_data), encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Unsupported JSON structure" in result.errors[0]

    def test_parse_json_object_conversation_like(self):
        """Test parsing JSON object that looks like conversation."""
        data = {
            "title": "Test Chat",
            "content": "A conversation",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        }

        conversations = self.importer._parse_json_object(data)

        assert len(conversations) == 1
        assert conversations[0]["title"] == "Test Chat"
        assert len(conversations[0]["messages"]) == 2

    def test_parse_json_object_nested_conversations(self):
        """Test parsing JSON object with nested conversation arrays."""
        data = {
            "chats": [
                {"title": "Chat 1", "content": "First", "messages": []},
                {"title": "Chat 2", "content": "Second", "messages": []},
            ],
            "other_data": "ignored",
        }

        conversations = self.importer._parse_json_object(data)

        assert len(conversations) == 2
        assert conversations[0]["title"] == "Chat 1"
        assert conversations[1]["title"] == "Chat 2"

    def test_parse_json_object_fallback(self):
        """Test parsing JSON object as fallback conversation."""
        data = {"random_field": "random_value", "another_field": 123}

        conversations = self.importer._parse_json_object(data)

        assert len(conversations) == 1
        assert "Generic Conversation" in conversations[0]["title"]
        # Content should contain the random field data in some form
        assert (
            "random_value" in conversations[0]["content"]
            or json.dumps(data) in conversations[0]["content"]
        )


class TestGenericImporterTextFormat:
    """Test GenericImporter text format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_import_markdown_dialogue(self):
        """Test importing markdown dialogue format."""
        markdown_content = """# Conversation

**Human**: Hello, how are you?

**Assistant**: I'm doing well, thank you! How can I help you today?

**Human**: Can you write some code for me?

**Assistant**: Of course! What kind of code would you like me to write?
"""

        test_file = self.storage_path / "dialogue.md"
        test_file.write_text(markdown_content, encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_text_message_blocks(self):
        """Test importing text with message block separators."""
        text_content = """First message from user

---

Response from assistant with helpful information

---

Follow up question from user

---

Final response from assistant
"""

        test_file = self.storage_path / "blocks.txt"
        test_file.write_text(text_content, encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_plain_text(self):
        """Test importing plain text file."""
        plain_text = "This is just a plain text file with some content that should be imported as a single conversation."

        test_file = self.storage_path / "plain.txt"
        test_file.write_text(plain_text, encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_text_exception(self):
        """Test text import with exception."""
        test_file = self.storage_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        with patch.object(
            self.importer, "_parse_text_content", side_effect=Exception("Parse error")
        ):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "Text import failed" in result.errors[0]


class TestGenericImporterCSVFormat:
    """Test GenericImporter CSV format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_import_csv_conversation(self):
        """Test importing CSV conversation format."""
        csv_data = [
            ["speaker", "message", "timestamp"],
            ["user", "Hello there", "2025-01-15 10:00:00"],
            ["assistant", "Hi! How can I help?", "2025-01-15 10:01:00"],
            ["user", "I need help with code", "2025-01-15 10:02:00"],
        ]

        test_file = self.storage_path / "conversation.csv"
        with open(test_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(csv_data)

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_csv_empty_file(self):
        """Test importing empty CSV file."""
        test_file = self.storage_path / "empty.csv"
        # Touch an empty file (no contents needed for the empty-CSV test).
        test_file.write_text("", encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1

    def test_import_csv_exception(self):
        """Test CSV import with exception."""
        test_file = self.storage_path / "test.csv"
        test_file.write_text('invalid,csv,format\nwith,unbalanced,quotes"', encoding="utf-8")

        with patch("csv.DictReader", side_effect=Exception("CSV error")):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "CSV import failed" in result.errors[0]


class TestGenericImporterXMLFormat:
    """Test GenericImporter XML format handling."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_import_xml_conversation(self):
        """Test importing XML conversation format."""
        xml_content = """<?xml version="1.0"?>
<conversation>
    <message speaker="user">Hello, how are you?</message>
    <message speaker="assistant">I'm doing well, thank you!</message>
    <message speaker="user">Can you help me with something?</message>
</conversation>"""

        test_file = self.storage_path / "conversation.xml"
        test_file.write_text(xml_content, encoding="utf-8")

        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        mock_save.assert_called_once()

    def test_import_xml_invalid_format(self):
        """Test importing invalid XML."""
        xml_content = "<conversation><unclosed>tag</conversation>"

        test_file = self.storage_path / "invalid.xml"
        test_file.write_text(xml_content, encoding="utf-8")

        result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "XML import failed" in result.errors[0]

    def test_import_xml_exception(self):
        """Test XML import with general exception."""
        test_file = self.storage_path / "test.xml"
        test_file.write_text("<conversation></conversation>", encoding="utf-8")

        with patch("xml.etree.ElementTree.parse", side_effect=Exception("XML error")):
            result = self.importer.import_file(test_file)

        assert result.success is False
        assert result.conversations_imported == 0
        assert result.conversations_failed == 1
        assert "XML import failed" in result.errors[0]


class TestGenericImporterParsingMethods:
    """Test GenericImporter parsing helper methods."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_parse_conversation_string(self):
        """Test parsing string as conversation."""
        text = "This is a conversation text"
        result = self.importer.parse_conversation(text)

        assert result["platform"] == "generic"
        assert text in result["content"]
        assert len(result["messages"]) == 1

    def test_parse_conversation_dict(self):
        """Test parsing dict as conversation."""
        data = {
            "title": "Test Conv",
            "content": "Test content",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        result = self.importer.parse_conversation(data)

        assert result["platform"] == "generic"
        assert result["title"] == "Test Conv"
        assert len(result["messages"]) == 1

    def test_parse_conversation_list(self):
        """Test parsing list as conversation."""
        data = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        result = self.importer.parse_conversation(data)

        assert result["platform"] == "generic"
        assert len(result["messages"]) == 2

    def test_parse_conversation_invalid_type(self):
        """Test parsing invalid type raises TypeError."""
        with pytest.raises(TypeError, match="Generic conversation data must be"):
            self.importer.parse_conversation(123)

    def test_looks_like_conversation_positive(self):
        """Test conversation detection with positive cases."""
        # Has messages field
        data1 = {"messages": []}
        assert self.importer._looks_like_conversation(data1) is True

        # Has content field
        data2 = {"content": "some content"}
        assert self.importer._looks_like_conversation(data2) is True

        # Has text field
        data3 = {"text": "some text"}
        assert self.importer._looks_like_conversation(data3) is True

    def test_looks_like_conversation_negative(self):
        """Test conversation detection with negative cases."""
        data = {"random": "data", "no_conv": "fields"}
        assert self.importer._looks_like_conversation(data) is False

    def test_has_dialogue_markers_positive(self):
        """Test dialogue marker detection with positive cases."""
        # Simple speaker format
        text1 = "Speaker: Hello there"
        assert self.importer._has_dialogue_markers(text1) is True

        # Bold speaker format
        text2 = "**Speaker**: Hello there"
        assert self.importer._has_dialogue_markers(text2) is True

        # Quote format
        text3 = "> Speaker: Hello there"
        assert self.importer._has_dialogue_markers(text3) is True

    def test_has_dialogue_markers_negative(self):
        """Test dialogue marker detection with negative cases."""
        text = "Just plain text without any dialogue markers"
        assert self.importer._has_dialogue_markers(text) is False

    def test_has_message_blocks_positive(self):
        """Test message block detection with positive cases."""
        # Has separators
        text1 = "Message 1\n---\nMessage 2\n---\nMessage 3"
        assert self.importer._has_message_blocks(text1) is True

        # Has timestamps
        text2 = "2025-01-15 10:00:00\nMessage 1\n2025-01-15 10:01:00\nMessage 2"
        assert self.importer._has_message_blocks(text2) is True

    def test_has_message_blocks_negative(self):
        """Test message block detection with negative cases."""
        text = "Just plain text without separators or timestamps"
        assert self.importer._has_message_blocks(text) is False

    def test_normalize_role(self):
        """Test role normalization."""
        assert self.importer._normalize_role("Human") == "user"
        assert self.importer._normalize_role("AI") == "assistant"
        assert self.importer._normalize_role("System") == "system"
        assert self.importer._normalize_role("CustomRole") == "customrole"

    def test_extract_field(self):
        """Test field extraction from data."""
        data = {"title": "Test", "content": "Content"}

        # Find existing field
        assert self.importer._extract_field(data, ["title", "name"]) == "Test"

        # Find with alternatives
        assert self.importer._extract_field(data, ["name", "title"]) == "Test"

        # No match
        assert self.importer._extract_field(data, ["missing", "absent"]) is None

    def test_find_column(self):
        """Test column name matching."""
        headers = ["Speaker", "Message_Text", "Time_Stamp"]

        # Exact match
        result = self.importer._find_column(headers, ["message"])
        assert "Message" in result

        # Partial match
        result = self.importer._find_column(headers, ["time"])
        assert "Time" in result

        # No match - returns first header
        result = self.importer._find_column(headers, ["missing"])
        assert result == headers[0]


class TestGenericImporterHelperMethods:
    """Test GenericImporter helper methods."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_extract_dialogue_messages(self):
        """Test dialogue message extraction."""
        lines = [
            "**Human**: Hello there",
            "This is continued text",
            "**Assistant**: Hi! How can I help?",
            "More assistant text",
            "**Human**: Thanks!",
        ]

        messages, content_parts = self.importer._extract_dialogue_messages(lines)

        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert len(content_parts) == 3

    def test_process_speaker_change(self):
        """Test speaker change processing."""
        messages = []
        content_parts = []

        self.importer._process_speaker_change("Human", ["Hello", "there"], messages, content_parts)

        assert len(messages) == 1
        assert len(content_parts) == 1
        assert messages[0]["role"] == "user"
        assert "Hello\nthere" in messages[0]["content"]

    def test_start_new_message(self):
        """Test starting new message from regex match."""
        import re

        match = re.match(r"(\*\*)?(\w+)(\*\*)?\s*:\s*(.*)", "**Human**: Hello there")

        speaker, message = self.importer._start_new_message(match)

        assert speaker == "Human"
        assert message == ["Hello there"]

    def test_continue_current_message(self):
        """Test continuing current message."""
        current_message = ["Hello"]
        result = self.importer._continue_current_message("Human", current_message, "there")

        assert result == ["Hello", "there"]

    def test_xml_element_looks_like_conversation(self):
        """Test XML element conversation detection."""
        # Create XML elements
        conv_elem = ET.Element("conversation")
        for _ in range(5):
            ET.SubElement(conv_elem, "message")

        random_elem = ET.Element("data")

        assert self.importer._xml_element_looks_like_conversation(conv_elem) is True
        assert self.importer._xml_element_looks_like_conversation(random_elem) is False


class TestGenericImporterSaveConversation:
    """Test GenericImporter conversation saving."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_save_conversation(self):
        """Test saving conversation to storage."""
        conversation = {
            "id": "generic_20250115_120000_abcd1234",
            "date": "2025-01-15T12:00:00",
            "title": "Test Generic Conversation",
            "content": "Test content",
            "platform": "generic",
        }

        file_path = self.importer._save_conversation(conversation)

        # Verify file was created
        assert file_path.exists()
        assert "2025" in str(file_path)
        assert "01-january" in str(file_path)
        assert file_path.name.endswith(".json")

        # Verify content
        with open(file_path, encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["id"] == conversation["id"]
        assert saved_data["platform"] == "generic"

    def test_save_conversations_success(self):
        """Test saving multiple conversations successfully."""
        conversations = [
            {
                "id": "conv1",
                "date": "2025-01-15T12:00:00",
                "title": "Conv 1",
                "content": "Content 1",
                "platform": "generic",
                "messages": [],
                "topics": [],
                "created_at": "2025-01-15T12:00:00",
            },
            {
                "id": "conv2",
                "date": "2025-01-15T12:00:00",
                "title": "Conv 2",
                "content": "Content 2",
                "platform": "generic",
                "messages": [],
                "topics": [],
                "created_at": "2025-01-15T12:00:00",
            },
        ]

        file_path = self.storage_path / "test.json"
        result = self.importer._save_conversations(conversations, file_path, "test_format")

        assert result.success is True
        assert result.conversations_imported == 2
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 2

    def test_save_conversations_with_failures(self):
        """Test saving conversations with some failures."""
        conversations = [
            {
                "id": "valid_conv",
                "date": "2025-01-15T12:00:00",
                "title": "Valid",
                "content": "Valid content",
                "platform": "generic",
                "messages": [],
                "topics": [],
                "created_at": "2025-01-15T12:00:00",
            },
            {
                "id": "invalid_conv"
                # Missing required fields
            },
        ]

        file_path = self.storage_path / "test.json"
        result = self.importer._save_conversations(conversations, file_path, "test_format")

        assert result.success is True  # At least one succeeded
        assert result.conversations_imported == 1
        assert result.conversations_failed == 1
        assert len(result.errors) == 1


class TestGenericImporterIntegration:
    """Test GenericImporter integration scenarios."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def test_end_to_end_json_import(self):
        """Test complete end-to-end JSON import workflow."""
        json_data = {
            "conversations": [
                {
                    "title": "E2E Test Conversation",
                    "content": "This is a comprehensive test of the generic importer",
                    "messages": [
                        {"role": "user", "content": "Import this conversation"},
                        {"role": "assistant", "content": "I'll import this for you"},
                        {"role": "user", "content": "Make sure it works properly"},
                        {
                            "role": "assistant",
                            "content": "The import is working correctly",
                        },
                    ],
                    "metadata": {"test": "e2e_integration"},
                }
            ]
        }

        test_file = self.storage_path / "e2e_test.json"
        test_file.write_text(json.dumps(json_data), encoding="utf-8")

        result = self.importer.import_file(test_file)

        # Verify import success
        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 1

        # Verify metadata
        assert result.metadata["platform"] == "generic"
        # Resolve both sides: on Windows the fixture path arrives as the 8.3
        # short name (C:\Users\RUNNER~1) while the importer records the long
        # form (C:\Users\runneradmin). Same file, different spelling.
        assert Path(result.metadata["source_file"]).resolve() == Path(test_file).resolve()
        assert result.metadata["format_type"] == "generic_json"

        # Verify conversation file was created (excludes source file)
        conversation_files = [
            f for f in self.storage_path.rglob("*.json") if f.name != "e2e_test.json"
        ]
        assert len(conversation_files) == 1

        # Verify conversation content
        with open(conversation_files[0], encoding="utf-8") as f:
            saved_conversation = json.load(f)

        assert saved_conversation["platform"] == "generic"
        assert "E2E Test Conversation" in saved_conversation["title"]
        assert len(saved_conversation["messages"]) == 4
        assert "comprehensive test" in saved_conversation["content"]

    def test_end_to_end_markdown_import(self):
        """Test complete end-to-end markdown import workflow."""
        markdown_content = """# AI Conversation Log

**User**: I need help with implementing a feature in my application.

**Assistant**: I'd be happy to help you implement a feature! Could you tell me more about what you're trying to build?

**User**: I want to add a search functionality that can handle multiple file types.

**Assistant**: Great! For multi-file search, I recommend implementing these components:

1. File type detection
2. Content extraction for each type
3. Indexing strategy
4. Search interface

Would you like me to elaborate on any of these areas?

**User**: Yes, please explain the indexing strategy.

**Assistant**: For indexing, you have several options depending on your requirements:

- **In-memory indexing**: Fast but limited by RAM
- **SQLite FTS**: Good balance of performance and simplicity
- **Elasticsearch**: Powerful but complex setup

For most applications, I'd recommend starting with SQLite FTS as it provides excellent search capabilities with minimal overhead.
"""

        test_file = self.storage_path / "conversation_log.md"
        test_file.write_text(markdown_content, encoding="utf-8")

        result = self.importer.import_file(test_file)

        # Verify import success
        assert result.success is True
        assert result.conversations_imported == 1
        assert result.conversations_failed == 0
        assert len(result.imported_ids) == 1

        # Verify metadata
        assert result.metadata["platform"] == "generic"
        assert result.metadata["format_type"] == "generic_text"

        # Verify conversation file was created (excludes source file)
        conversation_files = [
            f for f in self.storage_path.rglob("*.json") if f.name != "conversation_log.md"
        ]
        assert len(conversation_files) == 1

        # Verify conversation content
        with open(conversation_files[0], encoding="utf-8") as f:
            saved_conversation = json.load(f)

        assert saved_conversation["platform"] == "generic"
        assert "Conversation Log" in saved_conversation["title"]
        assert len(saved_conversation["messages"]) == 6  # 3 user + 3 assistant
        assert "search functionality" in saved_conversation["content"]
        assert "SQLite FTS" in saved_conversation["content"]

    def test_unsupported_file_extension(self):
        """Test handling of unsupported file extensions."""
        test_file = self.storage_path / "unsupported.xyz"
        test_file.write_text("Some content", encoding="utf-8")

        # Should fall back to text parsing
        with patch.object(self.importer, "_save_conversation") as mock_save:
            result = self.importer.import_file(test_file)

        assert result.success is True
        assert result.conversations_imported == 1
        mock_save.assert_called_once()


class TestGenericUniversalMetadata:
    """Generic importer pass-through for universal metadata (5.1.3-5.2.4)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir)
        self.importer = GenericImporter(self.storage_path)

    def _base_dict(self, **overrides):
        data = {
            "title": "Generic Conv",
            "content": "some content",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        }
        data.update(overrides)
        return data

    def test_session_id_from_session_id_key(self):
        conv = self.importer._parse_dict_as_conversation(self._base_dict(session_id="gen-sess-1"))
        assert conv["session_id"] == "gen-sess-1"

    def test_session_id_from_conversation_id_alias(self):
        conv = self.importer._parse_dict_as_conversation(
            self._base_dict(conversation_id="gen-conv-2")
        )
        assert conv["session_id"] == "gen-conv-2"

    def test_session_id_default_none(self):
        conv = self.importer._parse_dict_as_conversation(self._base_dict())
        assert conv["session_id"] is None

    def test_user_id_from_owner_id_alias(self):
        """user_id pulls from common synonyms (user_id/account_id/owner_id)."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(owner_id="owner-9"))
        assert conv["user_id"] == "owner-9"

    def test_tags_from_labels_alias(self):
        """tags pulls from 'tags' or 'labels'."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(labels=["alpha", "beta"]))
        assert "alpha" in conv["tags"]
        assert "beta" in conv["tags"]

    def test_tags_default_empty(self):
        conv = self.importer._parse_dict_as_conversation(self._base_dict())
        assert conv["tags"] == []

    def test_conversation_type_from_type_alias(self):
        """conversation_type pulls from 'conversation_type'/'type'/'category'."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(type="support"))
        assert conv["conversation_type"] == "support"

    def test_conversation_type_default_none(self):
        conv = self.importer._parse_dict_as_conversation(self._base_dict())
        assert conv["conversation_type"] is None

    def test_custom_fields_from_extras_alias(self):
        """custom_fields pulls from 'custom_fields'/'extra'/'extras'."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(extras={"k": "v"}))
        assert conv["custom_fields"] == {"k": "v"}

    def test_custom_fields_default_empty(self):
        conv = self.importer._parse_dict_as_conversation(self._base_dict())
        assert conv["custom_fields"] == {}

    def test_non_string_session_id_ignored(self):
        """Non-string session_id values default to None (type safety)."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(session_id=12345))
        assert conv["session_id"] is None

    def test_non_list_tags_ignored(self):
        """Non-list tags values default to empty list."""
        conv = self.importer._parse_dict_as_conversation(self._base_dict(tags="not-a-list"))
        assert conv["tags"] == []
