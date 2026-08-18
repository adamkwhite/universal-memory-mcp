"""Tests for universal metadata field validation (tags/session_id/user_id/
conversation_type/custom_fields) — src/validators.py.
"""

import pytest

from universal_memory_mcp.exceptions import MetadataValidationError
from universal_memory_mcp.validators import (
    MAX_CONVERSATION_TYPE_LENGTH,
    MAX_CUSTOM_FIELDS_BYTES,
    MAX_CUSTOM_FIELDS_DEPTH,
    MAX_CUSTOM_FIELDS_KEYS,
    MAX_SESSION_ID_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS_COUNT,
    MAX_USER_ID_LENGTH,
    validate_conversation_type,
    validate_custom_fields,
    validate_session_id,
    validate_tags,
    validate_user_id,
)


class TestValidateTags:
    def test_valid_tags_pass_through(self):
        assert validate_tags(["python", "docker"]) == ["python", "docker"]

    def test_none_returns_none(self):
        """None must round-trip as None, not [] — update_conversation's
        set_tags relies on this to distinguish "not provided" from "clear"."""
        assert validate_tags(None) is None

    def test_empty_list_returns_empty_list(self):
        assert validate_tags([]) == []

    def test_realistic_importer_tags(self):
        """Mirrors tags produced by cursor/claude/chatgpt importers."""
        tags = [
            "workspace:my-project",
            "has-file-changes",
            "variant:claude_web",
            "starred",
            "gizmo:g-abc123",
        ]
        assert validate_tags(tags) == tags

    def test_not_a_list_raises(self):
        with pytest.raises(MetadataValidationError, match="must be a list"):
            validate_tags("not-a-list")

    def test_non_string_tag_raises(self):
        with pytest.raises(MetadataValidationError, match="must be a string"):
            validate_tags(["ok", 123])

    def test_empty_string_tags_skipped(self):
        assert validate_tags(["a", "", "b"]) == ["a", "b"]

    def test_too_many_tags_raises(self):
        with pytest.raises(MetadataValidationError, match="Too many tags"):
            validate_tags([f"tag{i}" for i in range(MAX_TAGS_COUNT + 1)])

    def test_max_tags_count_passes(self):
        tags = [f"tag{i}" for i in range(MAX_TAGS_COUNT)]
        assert validate_tags(tags) == tags

    def test_tag_too_long_raises(self):
        with pytest.raises(MetadataValidationError, match="Tag too long"):
            validate_tags(["a" * (MAX_TAG_LENGTH + 1)])

    def test_max_length_tag_passes(self):
        tag = "a" * MAX_TAG_LENGTH
        assert validate_tags([tag]) == [tag]

    def test_null_byte_in_tag_raises(self):
        with pytest.raises(MetadataValidationError, match="null bytes"):
            validate_tags(["bad\x00tag"])

    def test_control_chars_stripped(self):
        assert validate_tags(["te\x01st"]) == ["test"]

    def test_whitespace_only_tag_dropped(self):
        assert validate_tags(["   "]) == []


class TestValidateSessionId:
    def test_valid_passes_through(self):
        assert validate_session_id("sess-123") == "sess-123"

    def test_none_returns_none(self):
        assert validate_session_id(None) is None

    def test_uuid_style_id_passes(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_session_id(uid) == uid

    def test_non_string_raises(self):
        with pytest.raises(MetadataValidationError, match="must be a string"):
            validate_session_id(12345)

    def test_too_long_raises(self):
        with pytest.raises(MetadataValidationError, match="too long"):
            validate_session_id("a" * (MAX_SESSION_ID_LENGTH + 1))

    def test_max_length_passes(self):
        sid = "a" * MAX_SESSION_ID_LENGTH
        assert validate_session_id(sid) == sid

    def test_null_byte_raises(self):
        with pytest.raises(MetadataValidationError, match="null bytes"):
            validate_session_id("bad\x00id")

    def test_control_chars_stripped(self):
        assert validate_session_id("id\x0112") == "id12"

    def test_blank_after_clean_returns_none(self):
        assert validate_session_id("   ") is None


class TestValidateUserId:
    def test_valid_passes_through(self):
        assert validate_user_id("user-456") == "user-456"

    def test_none_returns_none(self):
        assert validate_user_id(None) is None

    def test_too_long_raises(self):
        with pytest.raises(MetadataValidationError, match="too long"):
            validate_user_id("a" * (MAX_USER_ID_LENGTH + 1))


class TestValidateConversationType:
    def test_valid_passes_through(self):
        assert validate_conversation_type("code") == "code"

    def test_none_returns_none(self):
        assert validate_conversation_type(None) is None

    def test_too_long_raises(self):
        with pytest.raises(MetadataValidationError, match="too long"):
            validate_conversation_type("a" * (MAX_CONVERSATION_TYPE_LENGTH + 1))

    def test_document_transcription_type_passes(self):
        # Real value used in tests/test_update_conversation.py
        assert validate_conversation_type("document-transcription") == "document-transcription"


class TestValidateCustomFields:
    def test_none_returns_empty_dict(self):
        assert validate_custom_fields(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert validate_custom_fields({}) == {}

    def test_realistic_cursor_custom_fields(self):
        """Mirrors CursorImporter._extract_cursor_custom_fields output."""
        cf = {
            "workspace_path": "/home/user/projects/myapp",
            "files_involved": ["src/main.py", "src/utils.py", "tests/test_main.py"],
        }
        assert validate_custom_fields(cf) == cf

    def test_realistic_chatgpt_custom_fields(self):
        cf = {
            "default_model_slug": "gpt-4",
            "gizmo_id": "g-abc123",
            "gizmo_type": "assistant",
        }
        assert validate_custom_fields(cf) == cf

    def test_not_a_dict_raises(self):
        with pytest.raises(MetadataValidationError, match="must be a dictionary"):
            validate_custom_fields(["not", "a", "dict"])

    def test_too_many_keys_raises(self):
        cf = {f"key{i}": i for i in range(MAX_CUSTOM_FIELDS_KEYS + 1)}
        with pytest.raises(MetadataValidationError, match="too many keys"):
            validate_custom_fields(cf)

    def test_max_keys_passes(self):
        cf = {f"key{i}": i for i in range(MAX_CUSTOM_FIELDS_KEYS)}
        assert validate_custom_fields(cf) == cf

    def test_excessive_nesting_raises(self):
        nested = {}
        cursor = nested
        for _ in range(MAX_CUSTOM_FIELDS_DEPTH + 3):
            cursor["next"] = {}
            cursor = cursor["next"]
        with pytest.raises(MetadataValidationError, match="nesting too deep"):
            validate_custom_fields(nested)

    def test_reasonable_nesting_passes(self):
        cf = {"a": {"b": {"c": ["d", "e"]}}}
        assert validate_custom_fields(cf) == cf

    def test_non_serializable_raises(self):
        with pytest.raises(MetadataValidationError, match="JSON-serializable"):
            validate_custom_fields({"bad": object()})

    def test_null_byte_raises(self):
        with pytest.raises(MetadataValidationError, match="null bytes"):
            validate_custom_fields({"key": "bad\x00value"})

    def test_oversized_raises(self):
        cf = {"blob": "x" * (MAX_CUSTOM_FIELDS_BYTES + 1)}
        with pytest.raises(MetadataValidationError, match="too large"):
            validate_custom_fields(cf)
