"""
JSON Schema for ChatGPT export format validation.

Based on actual ChatGPT export structure analysis.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ChatGPT export schema based on real structure analysis
CHATGPT_SCHEMA = {
    "$schema": "https://json-schema.org/draft-07/schema#",
    "type": "array",
    "description": "ChatGPT export format - array of conversations",
    "items": {
        "type": "object",
        "description": "Individual ChatGPT conversation",
        "required": ["title", "create_time", "mapping", "conversation_id"],
        "properties": {
            "title": {"type": "string", "description": "Conversation title"},
            "create_time": {
                "type": "number",
                "description": "Conversation creation timestamp (Unix epoch)",
            },
            "update_time": {
                "type": "number",
                "description": "Last update timestamp (Unix epoch)",
            },
            "conversation_id": {
                "type": "string",
                "description": "Unique conversation identifier",
            },
            "id": {
                "type": "string",
                "description": "Conversation ID (may be same as conversation_id)",
            },
            "mapping": {
                "type": "object",
                "description": "Message nodes mapping",
                "patternProperties": {
                    "^[a-zA-Z0-9-_]+$": {
                        "type": "object",
                        "description": "Message node",
                        "required": ["id"],
                        "properties": {
                            "id": {"type": "string", "description": "Node ID"},
                            "message": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "object",
                                        "description": "Message content",
                                        "required": ["id", "author", "content"],
                                        "properties": {
                                            "id": {
                                                "type": "string",
                                                "description": "Message ID",
                                            },
                                            "author": {
                                                "type": "object",
                                                "description": "Message author",
                                                "required": ["role"],
                                                "properties": {
                                                    "role": {
                                                        "type": "string",
                                                        "enum": [
                                                            "user",
                                                            "assistant",
                                                            "system",
                                                        ],
                                                        "description": "Author role",
                                                    },
                                                    "name": {
                                                        "oneOf": [
                                                            {"type": "string"},
                                                            {"type": "null"},
                                                        ],
                                                        "description": "Author name",
                                                    },
                                                    "metadata": {
                                                        "type": "object",
                                                        "description": "Author metadata",
                                                    },
                                                },
                                            },
                                            "content": {
                                                "type": "object",
                                                "description": "Message content",
                                                "required": ["content_type"],
                                                "properties": {
                                                    "content_type": {
                                                        "type": "string",
                                                        "enum": [
                                                            "text",
                                                            "code",
                                                            "multimodal",
                                                            "multimodal_text",
                                                            "user_editable_context",
                                                        ],
                                                        "description": "Content type",
                                                    },
                                                    "parts": {
                                                        "type": "array",
                                                        "description": "Content parts",
                                                        "items": {"type": "string"},
                                                        "minItems": 1,
                                                    },
                                                    "user_profile": {
                                                        "type": "string",
                                                        "description": "User profile information",
                                                    },
                                                    "user_instructions": {
                                                        "type": "string",
                                                        "description": "User instructions",
                                                    },
                                                },
                                            },
                                            "create_time": {
                                                "oneOf": [
                                                    {"type": "number"},
                                                    {"type": "null"},
                                                ],
                                                "description": "Message creation time",
                                            },
                                            "update_time": {
                                                "oneOf": [
                                                    {"type": "number"},
                                                    {"type": "null"},
                                                ],
                                                "description": "Message update time",
                                            },
                                            "status": {
                                                "type": "string",
                                                "description": "Message status",
                                            },
                                            "end_turn": {
                                                "oneOf": [
                                                    {"type": "boolean"},
                                                    {"type": "null"},
                                                ],
                                                "description": "Whether message ends the turn",
                                            },
                                            "weight": {
                                                "type": "number",
                                                "description": "Message weight",
                                            },
                                            "metadata": {
                                                "type": "object",
                                                "description": "Message metadata",
                                            },
                                            "recipient": {
                                                "type": "string",
                                                "description": "Message recipient",
                                            },
                                            "channel": {
                                                "oneOf": [
                                                    {"type": "string"},
                                                    {"type": "null"},
                                                ],
                                                "description": "Message channel",
                                            },
                                        },
                                    },
                                ]
                            },
                            "parent": {
                                "oneOf": [{"type": "string"}, {"type": "null"}],
                                "description": "Parent node ID",
                            },
                            "children": {
                                "type": "array",
                                "description": "Child node IDs",
                                "items": {"type": "string"},
                            },
                        },
                    }
                },
            },
            "moderation_results": {
                "type": "array",
                "description": "Content moderation results",
                "items": {"type": "object"},
            },
            "current_node": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Current active node ID",
            },
            "plugin_ids": {
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ],
                "description": "Plugin IDs used",
            },
            "conversation_template_id": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Conversation template ID",
            },
            "gizmo_id": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "GPT/Gizmo ID",
            },
            "gizmo_type": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "GPT/Gizmo type",
            },
            "is_archived": {
                "oneOf": [{"type": "boolean"}, {"type": "null"}],
                "description": "Whether conversation is archived",
            },
            "is_starred": {
                "oneOf": [{"type": "boolean"}, {"type": "null"}],
                "description": "Whether conversation is starred",
            },
            "safe_urls": {
                "type": "array",
                "description": "Safe URLs",
                "items": {"type": "string"},
            },
            "blocked_urls": {
                "type": "array",
                "description": "Blocked URLs",
                "items": {"type": "string"},
            },
            "default_model_slug": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Default model used",
            },
            "conversation_origin": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Conversation origin",
            },
            "voice": {
                "oneOf": [{"type": "object"}, {"type": "null"}],
                "description": "Voice settings",
            },
            "async_status": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Async processing status",
            },
            "disabled_tool_ids": {
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ],
                "description": "Disabled tool IDs",
            },
            "is_do_not_remember": {
                "oneOf": [{"type": "boolean"}, {"type": "null"}],
                "description": "Do not remember setting",
            },
            "memory_scope": {
                "oneOf": [{"type": "string"}, {"type": "null"}],
                "description": "Memory scope setting",
            },
        },
    },
}


def validate_chatgpt_export(data: Any) -> dict[str, Any]:
    """
    Validate ChatGPT export data against schema.

    Args:
        data: Data to validate

    Returns:
        Dict with validation results
    """
    try:
        import jsonschema

        # Validate against schema
        jsonschema.validate(data, CHATGPT_SCHEMA)

        # Additional semantic validation
        validation_warnings = []

        if isinstance(data, list):
            for i, conversation in enumerate(data):
                # Check for empty mapping
                if not conversation.get("mapping"):
                    validation_warnings.append(f"Conversation {i} has empty mapping")

                # Check for messages in mapping
                mapping = conversation.get("mapping", {})
                message_count = sum(
                    1 for node in mapping.values() if node.get("message") is not None
                )

                if message_count == 0:
                    validation_warnings.append(f"Conversation {i} has no messages")
                elif message_count < 2:
                    validation_warnings.append(f"Conversation {i} has only {message_count} message")

        return {
            "valid": True,
            "errors": [],
            "warnings": validation_warnings,
            "conversation_count": len(data) if isinstance(data, list) else 0,
        }

    except ImportError:
        return {
            "valid": False,
            "errors": ["jsonschema library not available"],
            "warnings": [],
            "conversation_count": 0,
        }
    except jsonschema.ValidationError as e:
        return {
            "valid": False,
            "errors": [f"Schema validation error: {str(e)}"],
            "warnings": [],
            "conversation_count": 0,
        }
    except Exception as e:  # noqa: BLE001  # schema-validation boundary: return a structured {valid: False} result rather than crash the caller
        return {
            "valid": False,
            "errors": [f"Validation error: {str(e)}"],
            "warnings": [],
            "conversation_count": 0,
        }


def get_chatgpt_conversation_stats(conversation: dict[str, Any]) -> dict[str, Any]:
    """Get statistics about a ChatGPT conversation."""
    stats = {
        "title": conversation.get("title", "Untitled"),
        "conversation_id": conversation.get("conversation_id", "unknown"),
        "create_time": conversation.get("create_time"),
        "update_time": conversation.get("update_time"),
        "model": conversation.get("default_model_slug", "unknown"),
        "is_archived": conversation.get("is_archived", False),
        "is_starred": conversation.get("is_starred", False),
    }

    # Count messages in mapping
    mapping = conversation.get("mapping", {})
    message_nodes = [node for node in mapping.values() if node.get("message")]

    stats["total_nodes"] = len(mapping)
    stats["message_nodes"] = len(message_nodes)

    # Count by role
    role_counts = {"user": 0, "assistant": 0, "system": 0, "other": 0}
    total_characters = 0

    for node in message_nodes:
        message = node["message"]
        role = message.get("author", {}).get("role", "other")

        if role in role_counts:
            role_counts[role] += 1
        else:
            role_counts["other"] += 1

        # Count characters in content parts
        content = message.get("content", {})
        parts = content.get("parts", [])
        if parts is not None:
            for part in parts:
                if isinstance(part, str):
                    total_characters += len(part)

    stats["role_counts"] = role_counts
    stats["total_characters"] = total_characters

    return stats


# Example usage for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        from ..validators import validate_import_file_path

        try:
            file_path = validate_import_file_path(sys.argv[1])

            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            result = validate_chatgpt_export(data)
            print(f"Validation Result: {json.dumps(result, indent=2)}")

            if result["valid"] and isinstance(data, list) and data:
                # Show stats for first conversation
                stats = get_chatgpt_conversation_stats(data[0])
                print(f"\nFirst Conversation Stats: {json.dumps(stats, indent=2)}")

        except Exception as e:  # noqa: BLE001  # CLI demo entry point: print and exit rather than an unhandled traceback
            print(f"Error: {e}")
    else:
        print("Usage: python chatgpt_schema.py <chatgpt_export.json>")
