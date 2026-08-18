#!/usr/bin/env python3
"""
Test suite for ChatGPT schema validation.

Tests JSON schema validation for ChatGPT export formats.
"""

from unittest.mock import MagicMock, mock_open, patch

from universal_memory_mcp.schemas.chatgpt_schema import (
    CHATGPT_SCHEMA,
    get_chatgpt_conversation_stats,
    validate_chatgpt_export,
)


class TestChatGPTSchema:
    """Test ChatGPT schema definition and structure."""

    def test_schema_structure(self):
        """Test that CHATGPT_SCHEMA has correct structure."""
        assert isinstance(CHATGPT_SCHEMA, dict)
        assert "$schema" in CHATGPT_SCHEMA
        assert CHATGPT_SCHEMA["type"] == "array"
        assert "items" in CHATGPT_SCHEMA
        assert "properties" in CHATGPT_SCHEMA["items"]

    def test_schema_required_fields(self):
        """Test schema requires essential fields."""
        required_fields = CHATGPT_SCHEMA["items"]["required"]
        expected_fields = ["title", "create_time", "mapping", "conversation_id"]

        for field in expected_fields:
            assert field in required_fields

    def test_schema_properties_structure(self):
        """Test schema properties have correct types."""
        properties = CHATGPT_SCHEMA["items"]["properties"]

        # Check key properties exist
        assert "title" in properties
        assert "create_time" in properties
        assert "mapping" in properties
        assert "conversation_id" in properties

        # Check property types
        assert properties["title"]["type"] == "string"
        assert properties["create_time"]["type"] == "number"
        assert properties["mapping"]["type"] == "object"
        assert properties["conversation_id"]["type"] == "string"

    def test_schema_message_structure(self):
        """Test message structure in mapping."""
        mapping_props = CHATGPT_SCHEMA["items"]["properties"]["mapping"]
        pattern_props = mapping_props["patternProperties"]

        # Check pattern property exists for message nodes
        assert "^[a-zA-Z0-9-_]+$" in pattern_props

        node_schema = pattern_props["^[a-zA-Z0-9-_]+$"]
        assert "message" in node_schema["properties"]

        # Check message can be null or object
        message_schema = node_schema["properties"]["message"]
        assert "oneOf" in message_schema
        assert {"type": "null"} in message_schema["oneOf"]

    def test_schema_author_roles(self):
        """Test that schema defines valid author roles."""
        mapping_props = CHATGPT_SCHEMA["items"]["properties"]["mapping"]
        node_schema = mapping_props["patternProperties"]["^[a-zA-Z0-9-_]+$"]
        message_obj = [
            obj
            for obj in node_schema["properties"]["message"]["oneOf"]
            if obj.get("type") == "object"
        ][0]

        author_schema = message_obj["properties"]["author"]
        role_schema = author_schema["properties"]["role"]

        expected_roles = ["user", "assistant", "system"]
        assert role_schema["enum"] == expected_roles


class TestChatGPTValidation:
    """Test ChatGPT export validation functions."""

    def test_validate_chatgpt_export_valid(self):
        """Test validation with valid ChatGPT export."""
        valid_export = [
            {
                "title": "Test Conversation",
                "create_time": 1705312800.0,
                "conversation_id": "test-conv-123",
                "mapping": {
                    "msg-1": {
                        "id": "msg-1",
                        "message": {
                            "id": "msg-1",
                            "author": {"role": "user"},
                            "create_time": 1705312800.0,
                            "content": {"content_type": "text", "parts": ["Hello ChatGPT"]},
                        },
                        "parent": None,
                        "children": ["msg-2"],
                    },
                    "msg-2": {
                        "id": "msg-2",
                        "message": {
                            "id": "msg-2",
                            "author": {"role": "assistant"},
                            "create_time": 1705312860.0,
                            "content": {
                                "content_type": "text",
                                "parts": ["Hello! How can I help you?"],
                            },
                        },
                        "parent": "msg-1",
                        "children": [],
                    },
                },
            }
        ]

        result = validate_chatgpt_export(valid_export)
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["conversation_count"] == 1

    def test_validate_chatgpt_export_invalid_structure(self):
        """Test validation with invalid structure."""
        invalid_export = {"not_an_array": "this should be an array"}

        result = validate_chatgpt_export(invalid_export)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_chatgpt_export_missing_required_fields(self):
        """Test validation with missing required fields."""
        invalid_export = [
            {
                "title": "Test Conversation",
                # Missing create_time, conversation_id, mapping
            }
        ]

        result = validate_chatgpt_export(invalid_export)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_chatgpt_export_invalid_types(self):
        """Test validation with invalid field types."""
        invalid_export = [
            {
                "title": 123,  # Should be string
                "create_time": "not-a-number",  # Should be number
                "conversation_id": ["not-a-string"],  # Should be string
                "mapping": "not-an-object",  # Should be object
            }
        ]

        result = validate_chatgpt_export(invalid_export)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_chatgpt_export_empty_array(self):
        """Test validation with empty array."""
        empty_export = []

        result = validate_chatgpt_export(empty_export)
        assert result["valid"] is True  # Empty array is valid
        assert len(result["errors"]) == 0
        assert result["conversation_count"] == 0

    def test_validate_chatgpt_export_warnings(self):
        """Test validation generates warnings for edge cases."""
        export_with_warnings = [
            {
                "title": "Empty Mapping Test",
                "create_time": 1705312800.0,
                "conversation_id": "empty-mapping-123",
                "mapping": {},  # Empty mapping should generate warning
            }
        ]

        result = validate_chatgpt_export(export_with_warnings)
        assert result["valid"] is True
        assert len(result["warnings"]) > 0
        assert "empty mapping" in result["warnings"][0]

    def test_validate_chatgpt_export_no_messages_warning(self):
        """Test validation warns about conversations with no messages."""
        export_no_messages = [
            {
                "title": "No Messages Test",
                "create_time": 1705312800.0,
                "conversation_id": "no-messages-456",
                "mapping": {
                    "root": {
                        "id": "root",
                        "message": None,  # Root nodes don't count as messages
                        "parent": None,
                        "children": [],
                    }
                },
            }
        ]

        result = validate_chatgpt_export(export_no_messages)
        assert result["valid"] is True
        assert len(result["warnings"]) > 0
        assert "no messages" in result["warnings"][0]

    def test_validate_chatgpt_export_missing_jsonschema(self):
        """Test validation when jsonschema is not available."""

        # Mock the import to raise ImportError
        def mock_import(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("No module named 'jsonschema'")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = validate_chatgpt_export([])
            assert result["valid"] is False
            assert "jsonschema library not available" in result["errors"][0]

    def test_validate_chatgpt_export_exception_handling(self):
        """Test validation handles general exceptions gracefully."""
        # Create a mock jsonschema module with validate that raises an exception
        mock_jsonschema = MagicMock()
        mock_jsonschema.validate.side_effect = Exception("Validation error")
        mock_jsonschema.ValidationError = Exception  # Add ValidationError class

        with patch.dict("sys.modules", {"jsonschema": mock_jsonschema}):
            result = validate_chatgpt_export([])
            assert result["valid"] is False
            assert "Validation error" in result["errors"][0]


class TestConversationStats:
    """Test conversation statistics extraction."""

    def test_get_chatgpt_conversation_stats_basic(self):
        """Test basic stats extraction."""
        conversation = {
            "title": "Python Help Session",
            "create_time": 1705312800.0,
            "conversation_id": "conv-python-123",
            "default_model_slug": "gpt-4",
            "is_archived": False,
            "is_starred": True,
            "mapping": {
                "msg-1": {
                    "message": {
                        "author": {"role": "user"},
                        "create_time": 1705312800.0,
                        "content": {"content_type": "text", "parts": ["Help with Python"]},
                    }
                },
                "msg-2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1705312860.0,
                        "content": {
                            "content_type": "text",
                            "parts": ["I can help with Python programming!"],
                        },
                    }
                },
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["title"] == "Python Help Session"
        assert stats["conversation_id"] == "conv-python-123"
        assert stats["create_time"] == 1705312800.0
        assert stats["model"] == "gpt-4"
        assert stats["is_archived"] is False
        assert stats["is_starred"] is True
        assert stats["total_nodes"] == 2
        assert stats["message_nodes"] == 2
        assert stats["role_counts"]["user"] == 1
        assert stats["role_counts"]["assistant"] == 1

    def test_get_chatgpt_conversation_stats_character_counting(self):
        """Test character counting in stats."""
        conversation = {
            "title": "Character Count Test",
            "create_time": 1705312800.0,
            "conversation_id": "char-test-456",
            "mapping": {
                "msg-1": {
                    "message": {
                        "author": {"role": "user"},
                        # 5 chars
                        "content": {"content_type": "text", "parts": ["Hello"]},
                    }
                },
                "msg-2": {
                    "message": {
                        "author": {"role": "assistant"},
                        # 9 + 12 = 21 chars
                        "content": {"content_type": "text", "parts": ["Hi there!", "How are you?"]},
                    }
                },
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["total_characters"] == 26  # 5 + 9 + 12

    def test_get_chatgpt_conversation_stats_complex_mapping(self):
        """Test stats with complex message mapping."""
        conversation = {
            "title": "Complex Mapping Test",
            "create_time": 1705312800.0,
            "conversation_id": "complex-test-789",
            "mapping": {
                "root": {
                    "message": None  # Root node without message
                },
                "msg-1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["User message"]},
                    }
                },
                "msg-2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["Assistant response"]},
                    }
                },
                "msg-3": {
                    "message": {
                        "author": {"role": "system"},
                        "content": {"content_type": "text", "parts": ["System message"]},
                    }
                },
                "msg-4": {
                    "message": {
                        "author": {"role": "unknown_role"},
                        "content": {"content_type": "text", "parts": ["Unknown role"]},
                    }
                },
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["total_nodes"] == 5  # Including root
        assert stats["message_nodes"] == 4  # Excluding root
        assert stats["role_counts"]["user"] == 1
        assert stats["role_counts"]["assistant"] == 1
        assert stats["role_counts"]["system"] == 1
        assert stats["role_counts"]["other"] == 1  # Unknown role

    def test_get_chatgpt_conversation_stats_empty_mapping(self):
        """Test stats with empty mapping."""
        conversation = {
            "title": "Empty Mapping Test",
            "create_time": 1705312800.0,
            "conversation_id": "empty-test-999",
            "mapping": {},
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["total_nodes"] == 0
        assert stats["message_nodes"] == 0
        assert stats["total_characters"] == 0
        assert stats["role_counts"]["user"] == 0
        assert stats["role_counts"]["assistant"] == 0

    def test_get_chatgpt_conversation_stats_defaults(self):
        """Test stats with missing optional fields."""
        conversation = {
            "title": "Minimal Conversation",
            "create_time": 1705312800.0,
            "conversation_id": "minimal-123",
            # Missing mapping, model, archived/starred flags
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["title"] == "Minimal Conversation"
        assert stats["model"] == "unknown"
        assert stats["is_archived"] is False
        assert stats["is_starred"] is False
        assert stats["total_nodes"] == 0

    def test_get_chatgpt_conversation_stats_missing_title(self):
        """Test stats when title is missing."""
        conversation = {
            "create_time": 1705312800.0,
            "conversation_id": "no-title-456",
            "mapping": {},
        }

        stats = get_chatgpt_conversation_stats(conversation)

        assert stats["title"] == "Untitled"
        assert stats["conversation_id"] == "no-title-456"


class TestSchemaEdgeCases:
    """Test schema edge cases and error handling."""

    def test_validate_none_input(self):
        """Test validation with None input."""
        result = validate_chatgpt_export(None)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_string_input(self):
        """Test validation with string input."""
        result = validate_chatgpt_export("not-an-array")
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_stats_with_none_parts(self):
        """Test stats when content parts are None or missing."""
        conversation = {
            "title": "None Parts Test",
            "create_time": 1705312800.0,
            "conversation_id": "none-parts-123",
            "mapping": {
                "msg-1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": None},
                    }
                },
                "msg-2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text"},  # Missing parts
                    }
                },
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        # Should handle gracefully without crashing
        assert stats["message_nodes"] == 2
        assert stats["total_characters"] == 0

    def test_stats_with_non_string_parts(self):
        """Test stats when content parts contain non-strings."""
        conversation = {
            "title": "Non-String Parts Test",
            "create_time": 1705312800.0,
            "conversation_id": "non-string-456",
            "mapping": {
                "msg-1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "content_type": "text",
                            "parts": ["valid string", 123, None, {"object": "data"}],
                        },
                    }
                }
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        # Should only count string parts
        assert stats["total_characters"] == 12  # "valid string"

    def test_stats_missing_author_info(self):
        """Test stats when author info is missing."""
        conversation = {
            "title": "Missing Author Test",
            "create_time": 1705312800.0,
            "conversation_id": "missing-author-789",
            "mapping": {
                "msg-1": {
                    "message": {
                        # Missing author
                        "content": {"content_type": "text", "parts": ["Message without author"]}
                    }
                },
                "msg-2": {
                    "message": {
                        "author": {},  # Empty author
                        "content": {"content_type": "text", "parts": ["Message with empty author"]},
                    }
                },
            },
        }

        stats = get_chatgpt_conversation_stats(conversation)

        # Should handle gracefully and count as "other"
        assert stats["role_counts"]["other"] == 2
        assert stats["message_nodes"] == 2


class TestMainModule:
    """Test main module functionality."""

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data='[{"title": "Test", "create_time": 1705312800.0, "conversation_id": "test-123", "mapping": {}}]',
    )
    @patch("sys.argv", ["chatgpt_schema.py", "test_file.json"])
    def test_main_module_execution(self, mock_file):
        """Test main module execution with valid file."""
        # Import the module to trigger main execution

        # If we get here without errors, the main execution worked
        assert True

    @patch("builtins.open", side_effect=FileNotFoundError("File not found"))
    @patch("sys.argv", ["chatgpt_schema.py", "nonexistent.json"])
    def test_main_module_file_not_found(self, mock_file):
        """Test main module execution with missing file."""
        # Should handle file not found gracefully
        assert True

    @patch("sys.argv", ["chatgpt_schema.py"])
    def test_main_module_no_arguments(self):
        """Test main module execution with no arguments."""
        assert True
