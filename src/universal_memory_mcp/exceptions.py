"""Custom exceptions for Claude Memory MCP system"""


class ValidationError(ValueError):
    """Base validation error"""


class TitleValidationError(ValidationError):
    """Raised when conversation title validation fails"""


class ContentValidationError(ValidationError):
    """Raised when conversation content validation fails"""


class DateValidationError(ValidationError):
    """Raised when date validation fails"""


class QueryValidationError(ValidationError):
    """Raised when search query validation fails"""


class MetadataValidationError(ValidationError):
    """Raised when conversation metadata field validation fails.

    Covers the universal metadata fields (``tags``, ``session_id``,
    ``user_id``, ``conversation_type``, ``custom_fields``) introduced for
    cross-platform imports.
    """
