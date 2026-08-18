#!/usr/bin/env python3
"""
Claude Conversation Memory MCP Server (FastMCP Version)

This MCP server provides tools for managing and searching Claude conversation history.
Supports storing conversations locally and retrieving context for current sessions.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Plain absolute imports: ``src/`` is always a direct sys.path entry (the
# editable install's .pth, ``PYTHONPATH=.`` in tests, or the script's own
# directory when run as ``python3 src/server_fastmcp.py``). No package
# context is required, so there's no relative-import fallback to maintain --
# that dual try/except used to generate every no-redef mypy error here.
from .config import Config
from .conversation_memory import ConversationMemoryServer as CoreMemoryServer
from .exceptions import ValidationError
from .logging_config import (
    get_logger,
    init_default_logging,
    log_function_call,
    log_security_event,
    set_correlation_id,
)
from .validators import (
    validate_conversation_type,
    validate_session_id,
    validate_tags,
    validate_user_id,
)

# Constants
DEFAULT_PREVIEW_LENGTH = 500
DEFAULT_CONTENT_PREVIEW = 200
MAX_PREVIEW_LINES = 10
CONTEXT_LINES_BEFORE = 2
CONTEXT_LINES_AFTER = 3
DEFAULT_SEARCH_LIMIT = 5
MAX_RESULTS_DISPLAY = 10
DEFAULT_CONVERSATION_CHARS = 12000
MAX_CONVERSATION_CHARS = 50000
UTC_OFFSET_REPLACEMENT = "+00:00"

COMMON_TECH_TERMS = [
    "python",
    "javascript",
    "react",
    "node",
    "aws",
    "docker",
    "kubernetes",
    "terraform",
    "mcp",
    "api",
    "database",
    "sql",
    "mongodb",
    "redis",
    "git",
    "github",
    "vscode",
    "linux",
    "ubuntu",
    "windows",
    "wsl",
    "authentication",
    "security",
    "testing",
    "deployment",
    "ci/cd",
]


class FastMCPConversationMemoryServer(CoreMemoryServer):
    """FastMCP-specific wrapper around the core ConversationMemoryServer."""

    # Sentinel used to detect "caller did not pass storage_path" so we can
    # fall back to the Config-derived value while preserving the public API.
    _DEFAULT_STORAGE_SENTINEL = "~/claude-memory"

    def __init__(
        self,
        storage_path: str = _DEFAULT_STORAGE_SENTINEL,
        use_data_dir: bool | None = None,
        config: Config | None = None,
    ):
        # Load (or accept) centralized configuration. Validation runs here so
        # misconfiguration fails loudly at server startup rather than later.
        # ConfigError is a ValueError subclass and is allowed to propagate.
        self.config = config if config is not None else Config.load()

        # If the caller didn't explicitly override storage_path, defer to
        # the Config value (which honours CLAUDE_MEMORY_PATH and the config
        # file). This keeps backwards compatibility: explicit args win.
        if storage_path == self._DEFAULT_STORAGE_SENTINEL:
            storage_path = self.config.storage_path

        # Initialize logging using the (validated) Config so log_format /
        # log_level / console_output flow from the same source.
        init_default_logging(self.config)
        self.fastmcp_logger = get_logger("universal_memory_mcp.server")

        log_function_call(
            "FastMCPConversationMemoryServer.__init__",
            storage_path=storage_path,
            use_data_dir=use_data_dir,
        )

        # Validate storage path for security. A path the user deliberately
        # configured (explicit arg, CLAUDE_MEMORY_PATH, or config file) is
        # trusted for location — the home-directory jail below only applies to
        # the built-in default. This lets the server run on Windows/WSL where
        # storage may legitimately live off the home drive or on a UNC path.
        trusted = str(storage_path) != self._DEFAULT_STORAGE_SENTINEL
        storage_path_obj = Path(storage_path).expanduser().resolve()
        self._validate_storage_path(storage_path_obj, trusted=trusted)

        # Initialize the core memory server with SQLite per Config.
        super().__init__(
            storage_path=storage_path,
            use_data_dir=use_data_dir,
            enable_sqlite=self.config.enable_sqlite,
        )

        self.fastmcp_logger.info(
            f"FastMCP Server initialized with SQLite: {self.use_sqlite_search}"
        )

    def _validate_storage_path(self, storage_path: Path, trusted: bool = False):
        """Validate storage path for security.

        The ``..`` traversal guard always applies. The home-directory jail is
        skipped when ``trusted`` is True (the path was explicitly configured
        rather than defaulted).
        """
        log_function_call("_validate_storage_path", storage_path=str(storage_path))

        # Ensure path doesn't contain traversal attempts
        if ".." in str(storage_path):
            log_security_event(
                "PATH_TRAVERSAL_ATTEMPT",
                f"Storage path contains '..' traversal: {storage_path}",
                "ERROR",
            )
            raise ValueError("Storage path cannot contain '..' for security reasons")

        # An explicitly-configured path is trusted for location.
        if trusted:
            self.fastmcp_logger.debug(f"Storage path validation passed (trusted): {storage_path}")
            return

        # Ensure path is within user's home directory or explicit allowed paths
        home = Path.home().resolve()
        project_root = Path(__file__).parent.parent.resolve()

        # Allow paths in home directory or project directory (for testing)
        if not (
            str(storage_path).startswith(str(home))
            or str(storage_path).startswith(str(project_root))
        ):
            log_security_event(
                "PATH_OUTSIDE_HOME",
                f"Storage path outside allowed directories: {storage_path}",
                "ERROR",
            )
            raise ValueError(
                "Storage path must be within user's home directory or project directory"
            )

        self.fastmcp_logger.debug(f"Storage path validation passed: {storage_path}")


# Initialize FastMCP server and memory system
mcp = FastMCP("universal-memory-mcp")
memory_server = FastMCPConversationMemoryServer()


@mcp.tool()
async def search_conversations(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> str:
    """Search through stored Claude conversations for relevant content"""
    set_correlation_id()
    results = await memory_server.search_conversations(query, limit)

    errors = [result["error"] for result in results if "error" in result]
    if errors:
        return f"Search failed for '{query}': {errors[0]}"

    if not results:
        return f"No conversations found matching '{query}'"

    response = f"Found {len(results)} conversations matching '{query}':\n\n"
    for i, result in enumerate(results, 1):
        response += f"**{i}. {result['title']}**\n"
        response += f"ID: {result['id']}\n"
        response += f"Date: {result['date']}\n"
        if result.get("session_id"):
            response += f"Session: {result['session_id']}\n"
        if result.get("conversation_type"):
            response += f"Type: {result['conversation_type']}\n"
        response += f"Topics: {', '.join(result['topics'])}\n"
        response += f"Relevance Score: {result['score']}\n"
        response += f"Preview:\n```\n{result['preview']}\n```\n\n"

    return response


@mcp.tool()
async def add_conversation(
    content: str,
    title: str | None = None,
    date: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    conversation_type: str | None = None,
) -> str:
    """Add a new conversation to the memory system.

    ``session_id``, ``user_id``, ``tags``, and ``conversation_type`` are the
    universal metadata fields introduced in PR #114; when provided, they are
    persisted alongside the conversation and indexed for metadata search
    (``search_by_tag`` / ``search_by_session_id`` /
    ``search_by_conversation_type``). All four are validated/sanitized
    before storage since this data may originate from external imports.
    """
    set_correlation_id()

    try:
        session_id = validate_session_id(session_id)
        user_id = validate_user_id(user_id)
        tags = validate_tags(tags)
        conversation_type = validate_conversation_type(conversation_type)
    except ValidationError as e:
        return f"Status: error\n{e}"

    result = await memory_server.add_conversation(
        content,
        title,
        date,
        session_id=session_id,
        user_id=user_id,
        tags=tags,
        conversation_type=conversation_type,
    )
    return f"Status: {result['status']}\n{result['message']}"


@mcp.tool()
async def update_conversation(
    conversation_id: str,
    content: str | None = None,
    title: str | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    set_tags: list[str] | None = None,
    conversation_type: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    change_note: str | None = None,
    record_audit: bool = True,
) -> str:
    """Update fields on an existing conversation in place.

    Pass ``conversation_id`` plus any subset of fields to change. The first
    line of the stored content is rewritten with a self-documenting audit
    line: ``[update <iso-timestamp> — <change_note>]``. If ``change_note`` is
    omitted, it's auto-derived from which fields changed.

    Tag ops: ``set_tags`` replaces the full list; ``add_tags`` and
    ``remove_tags`` mutate it. ``set_tags`` is mutually exclusive with the
    other two; pass ``set_tags=[]`` to clear all tags.

    Metadata fields (tags, conversation_type, session_id, user_id) are
    validated/sanitized before storage since this data may originate from
    external imports.

    ``record_audit=False`` preserves authoritative imported content verbatim.
    Normal interactive updates should retain the default audit record.
    """
    try:
        add_tags = validate_tags(add_tags)
        remove_tags = validate_tags(remove_tags)
        set_tags = validate_tags(set_tags)
        conversation_type = validate_conversation_type(conversation_type)
        session_id = validate_session_id(session_id)
        user_id = validate_user_id(user_id)
    except ValidationError as e:
        return f"Status: error\n{e}"

    result = await memory_server.update_conversation(
        conversation_id,
        content=content,
        title=title,
        add_tags=add_tags,
        remove_tags=remove_tags,
        set_tags=set_tags,
        conversation_type=conversation_type,
        session_id=session_id,
        user_id=user_id,
        change_note=change_note,
        record_audit=record_audit,
    )
    response = f"Status: {result['status']}\n{result['message']}"
    if result.get("audit_line"):
        response += f"\nAudit: {result['audit_line']}"
    return response


@mcp.tool()
async def get_conversation(
    conversation_id: str,
    max_chars: int = DEFAULT_CONVERSATION_CHARS,
) -> str:
    """Retrieve a stored conversation by an ID returned from a search tool.

    The complete record is read from the authoritative JSON store. Content is
    capped to protect the model context; increase ``max_chars`` when necessary.
    """
    set_correlation_id()
    if not 1 <= max_chars <= MAX_CONVERSATION_CHARS:
        return f"Status: error\nmax_chars must be between 1 and {MAX_CONVERSATION_CHARS}"

    result = await memory_server.get_conversation(conversation_id)
    if "error" in result:
        return f"Status: error\n{result['error']}"

    content = result.get("content", "")
    if not isinstance(content, str):
        return "Status: error\nConversation content is not text"

    excerpt = content[:max_chars]
    response = f"**{result.get('title', 'Untitled')}**\n"
    response += f"ID: {result.get('id', conversation_id)}\n"
    if result.get("date"):
        response += f"Date: {result['date']}\n"
    if result.get("session_id"):
        response += f"Session: {result['session_id']}\n"
    if result.get("conversation_type"):
        response += f"Type: {result['conversation_type']}\n"
    response += f"Content: {len(excerpt)} of {len(content)} characters\n\n"
    response += excerpt
    if len(content) > max_chars:
        if max_chars < MAX_CONVERSATION_CHARS:
            response += (
                "\n\n[Content truncated; request a larger max_chars value to retrieve more.]"
            )
        else:
            response += "\n\n[Content truncated at the server maximum.]"
    return response


@mcp.tool()
async def generate_weekly_summary(week_offset: int = 0) -> str:
    """Generate a summary of conversations from the past week"""
    set_correlation_id()
    return await memory_server.generate_weekly_summary(week_offset)


@mcp.tool()
async def search_by_topic(topic: str, limit: int = 10) -> str:
    """Search conversations by a specific topic"""
    results = await memory_server.search_by_topic(topic, limit)
    return _format_metadata_results(results, label="topic", value=topic)


@mcp.tool()
async def search_by_tag(tag: str, limit: int = 10) -> str:
    """Search conversations tagged with a specific tag (D2 metadata field).

    Tags are universal metadata populated by the importers (e.g.
    ``starred``, ``archived``, ``workspace:my-project``, ``variant:web``).
    Requires SQLite FTS.
    """
    results = await memory_server.search_by_tag(tag, limit)
    return _format_metadata_results(results, label="tag", value=tag)


@mcp.tool()
async def search_by_session_id(session_id: str, limit: int = 10) -> str:
    """Find all conversations sharing a session_id (D2 metadata field).

    Useful for reconstructing a multi-turn session that spans several
    stored conversation records (e.g. a Cursor working session, a Claude
    thread continued across days). Results are sorted chronologically.
    Requires SQLite FTS.
    """
    results = await memory_server.search_by_session_id(session_id, limit)
    return _format_metadata_results(results, label="session", value=session_id)


@mcp.tool()
async def search_by_conversation_type(conversation_type: str, limit: int = 10) -> str:
    """Search conversations by conversation_type (D2 metadata field).

    Typical values: ``chat``, ``code``, ``analysis``. Requires SQLite FTS.
    """
    results = await memory_server.search_by_conversation_type(conversation_type, limit)
    return _format_metadata_results(results, label="conversation_type", value=conversation_type)


def _format_metadata_results(results: list, *, label: str, value: str) -> str:
    """Shared rendering for metadata-query MCP tools."""
    if not results:
        return f"No conversations found for {label} '{value}'"

    response = f"Found {len(results)} conversations for {label} '{value}':\n\n"
    for i, result in enumerate(results, 1):
        if "error" in result:
            response += f"Error: {result['error']}\n"
            continue

        response += f"**{i}. {result.get('title', 'Untitled')}**\n"
        response += f"ID: {result['id']}\n"
        if "date" in result:
            response += f"Date: {result['date']}\n"
        if result.get("session_id"):
            response += f"Session: {result['session_id']}\n"
        if result.get("conversation_type"):
            response += f"Type: {result['conversation_type']}\n"
        if "preview" in result:
            response += f"Preview:\n```\n{result['preview']}\n```\n\n"
        else:
            response += "\n"

    return response


def _format_consistency_section(consistency: dict | None) -> str:
    """Render the store-consistency section of the search-stats report.

    Only speaks up when something is actually wrong — a healthy store gets one
    line, not a table of zeros. Returns "" when no consistency data is present.
    """
    if not consistency:
        return ""

    if consistency.get("consistent", True):
        return f"\n• Store Consistency: OK ({consistency['json_files']} files)\n"

    labels = {
        "orphan_files": "files on disk missing from the search index",
        "dangling_rows": "indexed rows whose file is gone",
        "index_missing": "files on disk missing from index.json",
        "index_stale": "index.json entries whose file is gone",
    }
    section = "\n⚠ Store Consistency — drift detected:\n"
    for key, label in labels.items():
        if consistency.get(key):
            section += f"  - {consistency[key]} {label}\n"
    for key, paths in consistency.get("samples", {}).items():
        section += f"    e.g. {key}: {', '.join(paths)}\n"
    return section


@mcp.tool()
async def get_search_stats() -> str:
    """Get search engine statistics and performance information"""
    stats = await memory_server.get_search_stats()

    response = "Search Engine Statistics:\n\n"
    response += f"• SQLite Available: {stats.get('sqlite_available', 'Unknown')}\n"
    response += f"• SQLite Enabled: {stats.get('sqlite_enabled', 'Unknown')}\n"
    response += f"• Current Engine: {stats.get('search_engine', 'Unknown')}\n"

    if "total_conversations" in stats:
        response += f"• Total Conversations: {stats['total_conversations']}\n"

    if "unique_topics" in stats:
        response += f"• Unique Topics: {stats['unique_topics']}\n"

    if "popular_topics" in stats:
        response += "\nPopular Topics:\n"
        for topic_info in stats["popular_topics"][:5]:
            response += f"  - {topic_info['topic']}: {topic_info['count']} conversations\n"

    if stats.get("popular_tags"):
        response += "\nPopular Tags:\n"
        for tag_info in stats["popular_tags"][:5]:
            response += f"  - {tag_info['tag']}: {tag_info['count']} conversations\n"

    if stats.get("conversation_types"):
        response += "\nConversation Types:\n"
        for type_info in stats["conversation_types"]:
            response += f"  - {type_info['type']}: {type_info['count']}\n"

    response += _format_consistency_section(stats.get("consistency"))

    if "consistency_error" in stats:
        response += f"\nConsistency Check Error: {stats['consistency_error']}\n"

    if "sqlite_error" in stats:
        response += f"\nSQLite Error: {stats['sqlite_error']}\n"

    return response


# DISABLED: migrate_to_sqlite tool (saves 573 tokens in context)
# SQLite is enabled by default and auto-migrates on first use.
# Uncomment if manual migration is needed:
#
# @mcp.tool()
# async def migrate_to_sqlite() -> str:
#     """Migrate JSON conversations to SQLite for better search
#     performance"""
#     result = await memory_server.migrate_to_sqlite()
#
#     if "error" in result:
#         return f"Migration failed: {result['error']}"
#
#     response = "Migration Results:\n\n"
#     response += f"• Total Found: {result.get('total_found', 0)}\n"
#     response += (
#         f"• Successfully Migrated: "
#         f"{result.get('successfully_migrated', 0)}\n"
#     )
#     response += (
#         f"• Failed Migrations: {result.get('failed_migrations', 0)}\n"
#     )
#     response += f"• Skipped: {result.get('skipped', 0)}\n"
#
#     if result.get("successfully_migrated", 0) > 0:
#         response += "\n✅ Migration completed successfully!"
#         response += (
#             "\nSearch performance should now be significantly "
#             "improved."
#         )
#     else:
#         response += "\n⚠️ No conversations were migrated."
#
#     return response


def main() -> None:
    """Console-script entry point (``universal-memory-mcp``).

    Exists so the package can be launched without naming a file path. Running
    the module file directly no longer works — the modules use relative
    imports, so ``python .../server_fastmcp.py`` raises "attempted relative
    import with no known parent package". Use the console script, or
    ``python -m universal_memory_mcp.server_fastmcp``.
    """
    mcp.run()


if __name__ == "__main__":
    main()
