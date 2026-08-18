"""
JSON Schema validation for Universal Memory MCP.

Provides validation schemas for different AI platform export formats.
"""

from .chatgpt_schema import CHATGPT_SCHEMA, validate_chatgpt_export

__all__ = ["CHATGPT_SCHEMA", "validate_chatgpt_export"]
