"""Input validation for Claude Memory MCP system"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Plain absolute import, matching server_fastmcp.py/conversation_memory.py:
# ``src/`` is always a direct sys.path entry, and server_fastmcp.py imports
# this module bare (``from validators import ...``), so a relative import
# here raises "attempted relative import with no known parent package" the
# moment the server runs as a script.
from .exceptions import (
    ContentValidationError,
    DateValidationError,
    MetadataValidationError,
    QueryValidationError,
    TitleValidationError,
    ValidationError,
)

# Constants for validation
MAX_TITLE_LENGTH = 200
MAX_CONTENT_LENGTH = 1_000_000  # 1MB limit
MAX_QUERY_LENGTH = 500
MIN_CONTENT_LENGTH = 1

# Universal metadata field bounds (tags/session_id/user_id/conversation_type/
# custom_fields — see PR #114). Chosen generously against real importer
# output (src/importers/*.py: short slug-style tags like "workspace:foo" or
# "gizmo:xxxx", UUID-ish session/user ids, a handful of scalar/list entries
# in custom_fields such as "files_involved") so legitimate ChatGPT/Cursor
# imports are never rejected, while still bounding what an external export
# can push into JSON files + the SQLite FTS index.
MAX_TAG_LENGTH = 100
MAX_TAGS_COUNT = 50
MAX_SESSION_ID_LENGTH = 256
MAX_USER_ID_LENGTH = 256
MAX_CONVERSATION_TYPE_LENGTH = 100
MAX_CUSTOM_FIELDS_KEYS = 100
MAX_CUSTOM_FIELDS_DEPTH = 5
MAX_CUSTOM_FIELDS_BYTES = 100_000  # 100KB serialized (well under content's 1MB)

# Dangerous patterns to prevent security issues
PATH_TRAVERSAL_PATTERN = re.compile(r"\.{2}[/\\]|[/\\]\.{2}")
NULL_BYTE_PATTERN = re.compile(r"\x00")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1F\x7F]")  # Except newline, tab, CR
SAFE_CONTROL_CHARS = {"\n", "\r", "\t"}


def validate_title(title: str | None) -> str:
    """
    Validate and sanitize conversation title

    Args:
        title: The title to validate

    Returns:
        Sanitized title string

    Raises:
        TitleValidationError: If title is invalid
    """
    if not title:
        return "Untitled Conversation"

    # Check length
    if len(title) > MAX_TITLE_LENGTH:
        raise TitleValidationError(
            f"Title too long: {len(title)} characters (max {MAX_TITLE_LENGTH})"
        )

    # Check for null bytes
    if NULL_BYTE_PATTERN.search(title):
        raise TitleValidationError("Title contains null bytes")

    # Check for path traversal attempts
    if PATH_TRAVERSAL_PATTERN.search(title):
        raise TitleValidationError("Title contains invalid path characters")

    # Remove control characters except safe ones
    cleaned_title = "".join(
        char for char in title if char in SAFE_CONTROL_CHARS or not CONTROL_CHAR_PATTERN.match(char)
    )

    # Remove potentially dangerous file characters
    cleaned_title = re.sub(r'[<>:"|?*]', "", cleaned_title)

    # Trim whitespace
    cleaned_title = cleaned_title.strip()

    if not cleaned_title:
        return "Untitled Conversation"

    return cleaned_title


def validate_content(content: str) -> str:
    """
    Validate conversation content

    Args:
        content: The content to validate

    Returns:
        Validated content string

    Raises:
        ContentValidationError: If content is invalid
    """
    if not content:
        raise ContentValidationError("Content cannot be empty")

    # Check length
    if len(content) < MIN_CONTENT_LENGTH:
        raise ContentValidationError(
            f"Content too short: {len(content)} characters (min {MIN_CONTENT_LENGTH})"
        )

    if len(content) > MAX_CONTENT_LENGTH:
        raise ContentValidationError(
            f"Content too long: {len(content)} characters (max {MAX_CONTENT_LENGTH})"
        )

    # Remove null bytes for safety
    if NULL_BYTE_PATTERN.search(content):
        content = content.replace("\x00", "")

    return content


def validate_date(date_str: str | None) -> datetime | None:
    """
    Validate and parse date string

    Args:
        date_str: ISO format date string

    Returns:
        Parsed datetime or None

    Raises:
        DateValidationError: If date format is invalid
    """
    if not date_str:
        return None

    try:
        # Handle common ISO formats
        if "Z" in date_str:
            date_str = date_str.replace("Z", "+00:00")

        # Parse the date
        parsed_date = datetime.fromisoformat(date_str)

        # Sanity check - not too far in future or past
        now = datetime.now(parsed_date.tzinfo)
        years_diff = abs((parsed_date - now).days / 365)

        if years_diff > 100:
            raise DateValidationError(f"Date is unrealistic: {years_diff:.0f} years from now")

        return parsed_date

    except (ValueError, TypeError) as e:
        raise DateValidationError(f"Invalid date format: {str(e)}") from e


def validate_search_query(query: str) -> str:
    """
    Validate search query

    Args:
        query: The search query to validate

    Returns:
        Sanitized query string

    Raises:
        QueryValidationError: If query is invalid
    """
    if not query:
        raise QueryValidationError("Query cannot be empty")

    # Check length
    if len(query) > MAX_QUERY_LENGTH:
        raise QueryValidationError(
            f"Query too long: {len(query)} characters (max {MAX_QUERY_LENGTH})"
        )

    # Remove null bytes
    if NULL_BYTE_PATTERN.search(query):
        raise QueryValidationError("Query contains null bytes")

    # Remove dangerous regex characters that could cause ReDoS
    # But keep basic search characters like spaces, letters, numbers
    query = re.sub(r"[<>\\]", "", query)

    # Trim whitespace
    query = query.strip()

    if not query:
        raise QueryValidationError("Query cannot be empty after sanitization")

    return query


def validate_limit(limit: int) -> int:
    """
    Validate search result limit

    Args:
        limit: The limit to validate

    Returns:
        Valid limit value

    Raises:
        ValidationError: If limit is invalid
    """
    if not isinstance(limit, int):
        raise ValidationError("Limit must be an integer")

    if limit < 1:
        return 1

    if limit > 100:
        return 100

    return limit


def validate_storage_path(storage_path: str | Path | None) -> str:
    """Validate a ``storage_path`` before it is used to create directories.

    This is the shared choke point for ``ConversationMemoryServer.__init__``
    (and, by inheritance, ``FastMCPConversationMemoryServer``): it rejects
    malformed values that would otherwise silently create bogus directories
    relative to the current working directory -- e.g. ``""`` -> ``./data/``,
    the stringified-None bug -> ``./None/``, or a bare relative string like
    ``"evil-relative"`` -> ``./evil-relative/``.

    This intentionally does NOT enforce location policy (``..`` traversal,
    the home-directory jail). That's a separate, caller-specific concern
    already handled by
    ``FastMCPConversationMemoryServer._validate_storage_path`` -- duplicating
    it here would mean two places to keep in sync.

    Args:
        storage_path: The raw storage_path value as passed to the
            constructor (before ``~`` expansion).

    Returns:
        The original ``storage_path`` string, unchanged, once it passes
        validation.

    Raises:
        MetadataValidationError: If storage_path is missing, not a
            string/Path, empty/whitespace-only, contains a null byte, is a
            stringified None/null/nil sentinel, or is not absolute once
            ``~`` is expanded.
    """
    if storage_path is None:
        raise MetadataValidationError("storage_path cannot be None")

    if not isinstance(storage_path, (str, Path)):
        raise MetadataValidationError(
            f"storage_path must be a string or Path, got {type(storage_path).__name__}"
        )

    text = str(storage_path)

    if not text.strip():
        raise MetadataValidationError("storage_path cannot be empty or whitespace-only")

    if NULL_BYTE_PATTERN.search(text):
        raise MetadataValidationError("storage_path contains null bytes")

    # Defense-in-depth: reject literal Python-sentinel strings. These almost
    # always indicate an upstream bug where str(None) (or a similarly
    # stringified null) was used to build the path -- without this guard the
    # value passes every other check and happily creates a ./None/ (or
    # ./null/) directory next to the cwd.
    if text.strip().lower() in {"none", "null", "nil"}:
        raise MetadataValidationError(
            f"storage_path is the literal sentinel string {text!r} -- "
            "likely an upstream bug where a None/null value was "
            "stringified into the path."
        )

    # Relative paths are the actual harm here: they silently create
    # directory trees relative to whatever the current working directory
    # happens to be at import time, rather than the location the caller
    # meant. Every legitimate caller in this codebase (tests via
    # tempfile.mkdtemp, scripts via os.path.expanduser, the "~/claude-memory"
    # default) already produces an absolute path, so this is a deliberate,
    # non-breaking restriction -- not an accident.
    if not Path(text).expanduser().is_absolute():
        raise MetadataValidationError(
            f"storage_path must be an absolute path (after ~ expansion); "
            f"got {text!r}. Relative paths silently create directories "
            "relative to the current working directory."
        )

    return text


def validate_import_file_path(file_path: str | Path | None) -> Path:
    """Validate a file path immediately before it is opened for import
    parsing or format detection.

    Shared choke point for the ``BaseImporter`` subclasses' ``import_file``
    entry points and ``FormatDetector.detect_format`` (SonarCloud
    pythonsecurity:S8707 -- "LLMs running this code with faulty CLI
    arguments can escape file system restrictions"). Every caller of these
    entry points is a human running a local script
    (``scripts/bulk_import_enhanced.py``, or an importer's own ``__main__``
    demo block) against a file of their own choosing; the importers are not
    wired into any MCP tool, so there is no remote/privilege boundary being
    crossed here -- this is hardening a CLI against its own operator, not
    closing a live hole.

    This intentionally does NOT reject ``..`` traversal or relative paths:
    doing so would only break legitimate relative-path CLI usage without
    stopping anything a local user couldn't already do directly with
    ``cat``. That mirrors the "no location policy" carve-out documented on
    ``validate_storage_path`` above, for the same reason.

    Args:
        file_path: The raw path as passed to import_file/detect_format.

    Returns:
        The path, resolved to an absolute ``Path``.

    Raises:
        MetadataValidationError: If file_path is missing, not a string or
            Path, empty/whitespace-only, contains a null byte, does not
            exist, or is not a regular file (e.g. a directory).
    """
    if file_path is None:
        raise MetadataValidationError("file_path cannot be None")

    if not isinstance(file_path, (str, Path)):
        raise MetadataValidationError(
            f"file_path must be a string or Path, got {type(file_path).__name__}"
        )

    text = str(file_path)

    if not text.strip():
        raise MetadataValidationError("file_path cannot be empty or whitespace-only")

    if NULL_BYTE_PATTERN.search(text):
        raise MetadataValidationError("file_path contains null bytes")

    resolved = Path(file_path).resolve()

    if not resolved.exists():
        raise MetadataValidationError(f"file_path does not exist: {resolved}")

    if not resolved.is_file():
        raise MetadataValidationError(f"file_path is not a regular file: {resolved}")

    return resolved


def _strip_control_chars(value: str) -> str:
    """Remove control chars (keeping safe whitespace), matching validate_title."""
    return "".join(
        char for char in value if char in SAFE_CONTROL_CHARS or not CONTROL_CHAR_PATTERN.match(char)
    ).strip()


def _validate_identifier(value: str | None, field_name: str, max_length: int) -> str | None:
    """Shared validation for single-string metadata fields (session_id,
    user_id, conversation_type). Returns None for missing/blank-after-clean
    input so "not provided" round-trips as None rather than an empty string.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        raise MetadataValidationError(f"{field_name} must be a string")

    if len(value) > max_length:
        raise MetadataValidationError(
            f"{field_name} too long: {len(value)} characters (max {max_length})"
        )

    if NULL_BYTE_PATTERN.search(value):
        raise MetadataValidationError(f"{field_name} contains null bytes")

    cleaned = _strip_control_chars(value)
    return cleaned or None


def validate_session_id(session_id: str | None) -> str | None:
    """Validate the universal ``session_id`` metadata field.

    Raises:
        MetadataValidationError: If session_id is invalid
    """
    return _validate_identifier(session_id, "session_id", MAX_SESSION_ID_LENGTH)


def validate_user_id(user_id: str | None) -> str | None:
    """Validate the universal ``user_id`` metadata field.

    Raises:
        MetadataValidationError: If user_id is invalid
    """
    return _validate_identifier(user_id, "user_id", MAX_USER_ID_LENGTH)


def validate_conversation_type(conversation_type: str | None) -> str | None:
    """Validate the universal ``conversation_type`` metadata field.

    Raises:
        MetadataValidationError: If conversation_type is invalid
    """
    return _validate_identifier(
        conversation_type, "conversation_type", MAX_CONVERSATION_TYPE_LENGTH
    )


def validate_tags(tags: list[str] | None) -> list[str] | None:
    """Validate the universal ``tags`` metadata field.

    ``None`` is returned unchanged (distinguishes "not provided" from an
    explicit empty list, which callers such as ``update_conversation``'s
    ``set_tags`` use to mean "clear all tags").

    Raises:
        MetadataValidationError: If tags is invalid
    """
    if tags is None:
        return None

    if not isinstance(tags, list):
        raise MetadataValidationError("Tags must be a list of strings")

    if len(tags) > MAX_TAGS_COUNT:
        raise MetadataValidationError(f"Too many tags: {len(tags)} (max {MAX_TAGS_COUNT})")

    cleaned_tags: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise MetadataValidationError(f"Tag must be a string, got {type(tag).__name__}")

        if not tag:
            continue

        if len(tag) > MAX_TAG_LENGTH:
            raise MetadataValidationError(
                f"Tag too long: {len(tag)} characters (max {MAX_TAG_LENGTH})"
            )

        if NULL_BYTE_PATTERN.search(tag):
            raise MetadataValidationError("Tag contains null bytes")

        cleaned_tag = _strip_control_chars(tag)
        if cleaned_tag:
            cleaned_tags.append(cleaned_tag)

    return cleaned_tags


def _check_custom_fields_depth(value: Any, current_depth: int = 0) -> None:
    """Recursively walk a custom_fields value, rejecting excessive nesting."""
    if current_depth > MAX_CUSTOM_FIELDS_DEPTH:
        raise MetadataValidationError(
            f"custom_fields nesting too deep (max {MAX_CUSTOM_FIELDS_DEPTH} levels)"
        )
    if isinstance(value, dict):
        for nested in value.values():
            _check_custom_fields_depth(nested, current_depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _check_custom_fields_depth(nested, current_depth + 1)


def validate_custom_fields(
    custom_fields: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate the universal ``custom_fields`` metadata field.

    Bounds: key count, nesting depth, and total serialized size. Values are
    otherwise left as-is (custom_fields is an open extensibility bucket) as
    long as they're JSON-serializable, matching how it's persisted (JSON
    file + ``custom_fields_json`` SQLite column).

    Raises:
        MetadataValidationError: If custom_fields is invalid
    """
    if not custom_fields:
        return {}

    if not isinstance(custom_fields, dict):
        raise MetadataValidationError("custom_fields must be a dictionary")

    if len(custom_fields) > MAX_CUSTOM_FIELDS_KEYS:
        raise MetadataValidationError(
            f"custom_fields has too many keys: {len(custom_fields)} (max {MAX_CUSTOM_FIELDS_KEYS})"
        )

    _check_custom_fields_depth(custom_fields)

    try:
        serialized = json.dumps(custom_fields)
    except (TypeError, ValueError) as e:
        raise MetadataValidationError(f"custom_fields must be JSON-serializable: {e}") from e

    # json.dumps escapes null bytes as a backslash-u0000 sequence rather
    # than emitting a raw null byte, so NULL_BYTE_PATTERN (which matches a
    # raw null byte) never fires on the serialized form -- check both.
    null_byte_escape = "\\u0000"
    if NULL_BYTE_PATTERN.search(serialized) or null_byte_escape in serialized:
        raise MetadataValidationError("custom_fields contains null bytes")

    serialized_bytes = len(serialized.encode("utf-8"))
    if serialized_bytes > MAX_CUSTOM_FIELDS_BYTES:
        raise MetadataValidationError(
            f"custom_fields too large: {serialized_bytes} bytes (max {MAX_CUSTOM_FIELDS_BYTES})"
        )

    return custom_fields
