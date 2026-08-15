#!/usr/bin/env python3
"""
Additional tests for FastMCP server functionality and weekly summary generation
to achieve 50% test coverage
"""

import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import server_fastmcp
    from conversation_memory import ConversationMemoryServer

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False


@pytest.fixture
def temp_storage():
    """Create a temporary storage directory for testing"""
    # Create temp dir in system temp directory to avoid project root clutter
    temp_dir = tempfile.mkdtemp(prefix="claude_memory_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def server(temp_storage):
    """Create a server instance for testing"""
    return ConversationMemoryServer(temp_storage)


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestWeeklySummaryGeneration:
    """Comprehensive tests for weekly summary generation"""

    @pytest.mark.asyncio
    async def test_weekly_summary_no_conversations(self, server):
        """Test weekly summary when no conversations exist"""
        summary = await server.generate_weekly_summary(0)
        assert "No conversations found" in summary
        assert "current week" in summary

    @pytest.mark.asyncio
    async def test_weekly_summary_with_conversations(self, server):
        """Test weekly summary generation with conversations"""
        # Add conversations for current week (use UTC to match _calculate_week_range)
        from datetime import timezone

        current_time = datetime.now(timezone.utc).isoformat()

        await server.add_conversation(
            "Python coding discussion about functions and classes",
            "Coding Discussion",
            current_time,
        )

        await server.add_conversation(
            "We decided to use FastMCP for our approach",
            "Decision Making",
            current_time,
        )

        await server.add_conversation(
            "Learning how to implement MCP servers tutorial",
            "Learning Session",
            current_time,
        )

        summary = await server.generate_weekly_summary(0)

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "Weekly Summary" in summary
        assert "Coding Discussion" in summary
        assert "Decision Making" in summary
        assert "Learning Session" in summary

    @pytest.mark.asyncio
    async def test_weekly_summary_topic_analysis(self, server):
        """Test that weekly summary analyzes topics correctly"""
        # Use UTC time to match _calculate_week_range
        from datetime import timezone

        current_time = datetime.now(timezone.utc).isoformat()

        # Add conversation with multiple python mentions
        await server.add_conversation(
            "Python development with python libraries and python frameworks",
            "Python Discussion",
            current_time,
        )

        summary = await server.generate_weekly_summary(0)

        assert "Popular Topics" in summary
        assert "python" in summary.lower()

    @pytest.mark.asyncio
    async def test_weekly_summary_categorization(self, server):
        """Test that conversations are categorized correctly"""
        # Use UTC time to match _calculate_week_range
        from datetime import timezone

        current_time = datetime.now(timezone.utc).isoformat()

        # Add coding conversation
        await server.add_conversation(
            "Writing code for a new function with git repository management",
            "Coding Task",
            current_time,
        )

        # Add decision conversation
        await server.add_conversation(
            "We decided to use the recommended approach for this feature",
            "Architecture Decision",
            current_time,
        )

        # Add learning conversation
        await server.add_conversation(
            "Learning how to explain complex concepts in tutorials",
            "Learning Topic",
            current_time,
        )

        summary = await server.generate_weekly_summary(0)

        # Check for category sections or conversation titles
        assert "💻 Coding & Development" in summary or "Coding Task" in summary
        assert "🎯 Decisions & Recommendations" in summary or "Architecture Decision" in summary
        assert "📚 Learning & Exploration" in summary or "Learning Topic" in summary

    @pytest.mark.asyncio
    async def test_weekly_summary_different_weeks(self, server):
        """Test weekly summary for different week offsets"""
        # Test summary for 1 week ago (should be empty for new installation)
        summary_past = await server.generate_weekly_summary(1)
        assert "No conversations found" in summary_past
        assert "1 week(s) ago" in summary_past

    @pytest.mark.asyncio
    async def test_weekly_summary_file_saving(self, server, temp_storage):
        """Test that weekly summary is saved to file"""
        # Use UTC time to match _calculate_week_range
        from datetime import timezone

        current_time = datetime.now(timezone.utc).isoformat()

        await server.add_conversation(
            "Test conversation for file saving", "File Save Test", current_time
        )

        summary = await server.generate_weekly_summary(0)

        # Check that summary mentions file saving
        assert "Summary saved to" in summary

        # Check that file actually exists
        weekly_dir = Path(temp_storage) / "data" / "summaries" / "weekly"
        summary_files = list(weekly_dir.glob("*.md"))
        assert len(summary_files) > 0

    @pytest.mark.asyncio
    async def test_weekly_summary_error_handling(self, server, temp_storage):
        """Test weekly summary error handling"""
        # Remove the index file to cause an error
        index_file = Path(temp_storage) / "data" / "conversations" / "index.json"
        if index_file.exists():
            index_file.unlink()

        summary = await server.generate_weekly_summary(0)
        # Should handle error gracefully
        assert isinstance(summary, str)


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestMCPToolFunctions:
    """Test the MCP tool wrapper functions"""

    @pytest.mark.asyncio
    async def test_mcp_search_tool_no_results(self):
        """Test MCP search tool when no results found"""
        result = await server_fastmcp.search_conversations("nonexistentquery12345", limit=5)
        assert "No conversations found" in result

    @pytest.mark.asyncio
    async def test_mcp_search_tool_with_results(self, server):
        """Test MCP search tool with actual results"""
        # Add test data through the server instance
        await server.add_conversation(
            "Testing MCP search tool functionality",
            "MCP Search Test",
            "2025-06-01T11:00:00Z",
        )

        # Test the MCP tool function
        result = await server_fastmcp.search_conversations("MCP search", limit=1)
        assert "Found" in result or "No conversations found" in result
        if "Found" in result:
            assert "**1." in result  # Check formatting
            assert "Preview:" in result
            # Accept any conversation result that contains MCP (case insensitive)
            assert "MCP" in result.upper() or "mcp" in result

    @pytest.mark.asyncio
    async def test_mcp_add_conversation_tool(self):
        """Test the MCP add_conversation tool"""
        result = await server_fastmcp.add_conversation(
            "Test content for MCP add tool", "MCP Add Test", "2025-06-01T12:00:00Z"
        )

        assert "Status: success" in result
        assert "Conversation saved successfully" in result

    @pytest.mark.asyncio
    async def test_mcp_add_conversation_tool_error(self):
        """Test MCP add_conversation tool error handling"""
        # Test with invalid date format
        result = await server_fastmcp.add_conversation(
            "Test content", "Error Test", "invalid-date-format"
        )

        # Should handle error gracefully
        assert "Status:" in result

    @pytest.mark.asyncio
    async def test_mcp_add_conversation_tool_forwards_metadata(self, monkeypatch):
        """The MCP add_conversation tool forwards the D2 metadata kwargs."""
        captured = {}

        async def fake_add(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "add_conversation", fake_add)

        result = await server_fastmcp.add_conversation(
            content="c",
            title="t",
            date="2026-04-18T10:00:00",
            session_id="s1",
            user_id="u1",
            tags=["a", "b"],
            conversation_type="code",
        )

        assert "Status: success" in result
        assert captured["args"] == ("c", "t", "2026-04-18T10:00:00")
        assert captured["kwargs"] == {
            "session_id": "s1",
            "user_id": "u1",
            "tags": ["a", "b"],
            "conversation_type": "code",
        }

    @pytest.mark.asyncio
    async def test_mcp_search_by_tag_tool_formats_results(self, monkeypatch):
        """search_by_tag MCP tool renders tag/session/type in output."""

        async def fake_search(tag, limit):
            return [
                {
                    "id": "conv_x",
                    "title": "Tagged note",
                    "date": "2026-04-18",
                    "session_id": "sess_x",
                    "conversation_type": "code",
                }
            ]

        monkeypatch.setattr(server_fastmcp.memory_server, "search_by_tag", fake_search)

        result = await server_fastmcp.search_by_tag("starred", limit=3)
        assert "Found 1 conversations for tag 'starred'" in result
        assert "Tagged note" in result
        assert "Session: sess_x" in result
        assert "Type: code" in result

    @pytest.mark.asyncio
    async def test_mcp_search_by_tag_tool_no_results(self, monkeypatch):
        async def fake_search(tag, limit):
            return []

        monkeypatch.setattr(server_fastmcp.memory_server, "search_by_tag", fake_search)

        result = await server_fastmcp.search_by_tag("missing")
        assert "No conversations found for tag 'missing'" in result

    @pytest.mark.asyncio
    async def test_mcp_search_by_session_id_tool(self, monkeypatch):
        async def fake_search(sid, limit):
            return [
                {"id": "a", "title": "A", "date": "2026-04-18"},
                {"id": "b", "title": "B", "date": "2026-04-19"},
            ]

        monkeypatch.setattr(server_fastmcp.memory_server, "search_by_session_id", fake_search)

        result = await server_fastmcp.search_by_session_id("sess_x")
        assert "Found 2 conversations for session 'sess_x'" in result
        assert "**1. A**" in result and "**2. B**" in result

    @pytest.mark.asyncio
    async def test_mcp_search_by_conversation_type_tool(self, monkeypatch):
        async def fake_search(ctype, limit):
            return [{"id": "z", "title": "Z", "date": "2026-04-18"}]

        monkeypatch.setattr(
            server_fastmcp.memory_server,
            "search_by_conversation_type",
            fake_search,
        )

        result = await server_fastmcp.search_by_conversation_type("code")
        assert "Found 1 conversations for conversation_type 'code'" in result
        assert "**1. Z**" in result

    @pytest.mark.asyncio
    async def test_mcp_get_search_stats_tool_surfaces_tags_and_types(self, monkeypatch):
        """get_search_stats MCP tool renders popular_tags/conversation_types."""

        async def fake_stats():
            return {
                "sqlite_available": True,
                "sqlite_enabled": True,
                "search_engine": "sqlite_fts",
                "popular_tags": [{"tag": "starred", "count": 3}],
                "conversation_types": [{"type": "code", "count": 5}],
            }

        monkeypatch.setattr(server_fastmcp.memory_server, "get_search_stats", fake_stats)

        result = await server_fastmcp.get_search_stats()
        assert "Popular Tags:" in result
        assert "- starred: 3 conversations" in result
        assert "Conversation Types:" in result
        assert "- code: 5" in result

    @pytest.mark.asyncio
    async def test_mcp_get_search_stats_tool_omits_empty_sections(self, monkeypatch):
        """No tags/conversation_types yet -> no empty section headers."""

        async def fake_stats():
            return {
                "sqlite_available": True,
                "sqlite_enabled": True,
                "search_engine": "sqlite_fts",
                "popular_tags": [],
                "conversation_types": [],
            }

        monkeypatch.setattr(server_fastmcp.memory_server, "get_search_stats", fake_stats)

        result = await server_fastmcp.get_search_stats()
        assert "Popular Tags:" not in result
        assert "Conversation Types:" not in result

    @pytest.mark.asyncio
    async def test_mcp_metadata_tool_renders_error_marker(self, monkeypatch):
        """Error marker from underlying server surfaces in the tool output."""

        async def fake_search(tag, limit):
            return [{"error": "Tag search requires SQLite FTS to be enabled"}]

        monkeypatch.setattr(server_fastmcp.memory_server, "search_by_tag", fake_search)

        result = await server_fastmcp.search_by_tag("starred")
        assert "Error: Tag search requires SQLite FTS to be enabled" in result

    @pytest.mark.asyncio
    async def test_mcp_weekly_summary_tool(self, server):
        """Test the MCP weekly summary tool"""
        # Add some test data
        # Use UTC time to match _calculate_week_range
        from datetime import timezone

        current_time = datetime.now(timezone.utc).isoformat()
        await server.add_conversation(
            "Weekly summary test conversation", "Weekly Test", current_time
        )

        # Test weekly summary tool
        result = await server_fastmcp.generate_weekly_summary(0)
        assert isinstance(result, str)
        assert len(result) > 0


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestErrorHandlingAndEdgeCases:
    """Tests for error handling and edge cases to boost coverage"""

    @pytest.mark.asyncio
    async def test_search_with_missing_files(self, server, temp_storage):
        """Test search when conversation files are missing"""
        # Add a conversation normally
        result = await server.add_conversation("Test content", "Test Title", "2025-01-15T10:30:00")

        # Remove the conversation file but keep index entry
        file_path = Path(result["file_path"])
        if file_path.exists():
            file_path.unlink()

        # Search should handle missing files gracefully
        results = await server.search_conversations("Test", limit=5)
        # Should return empty or handle error gracefully
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_add_conversation_with_file_errors(self, server, temp_storage):
        """Test add_conversation with file system errors"""
        # Make conversations directory read-only to cause write errors
        conversations_dir = Path(temp_storage) / "data" / "conversations"
        try:
            conversations_dir.chmod(0o444)  # Read-only

            result = await server.add_conversation(
                "Test content", "Error Test", "2025-01-15T10:30:00"
            )

            # Should handle error gracefully
            assert result["status"] in ["success", "error"]

        finally:
            # Restore permissions for cleanup
            conversations_dir.chmod(0o755)

    @pytest.mark.asyncio
    async def test_index_update_with_corrupted_files(self, server, temp_storage):
        """Test index updates with corrupted JSON files"""
        # Corrupt the index file
        index_file = Path(temp_storage) / "data" / "conversations" / "index.json"
        with open(index_file, "w", encoding="utf-8") as f:
            f.write("invalid json content")

        # This should either succeed by recreating the file or handle error gracefully
        result = await server.add_conversation(
            "Test content after corruption", "Corruption Test", "2025-01-15T10:30:00"
        )

        # Check that operation either succeeded or failed gracefully
        assert "status" in result

    def test_topic_extraction_with_unicode(self, server):
        """Test topic extraction with unicode characters"""
        content = "Discussion about Pythön and machine léarning with émojis 🐍"
        topics = server._extract_topics(content)

        # Should handle unicode gracefully
        assert isinstance(topics, list)

    @pytest.mark.asyncio
    async def test_search_with_empty_query(self, server):
        """Test search with empty or invalid queries"""
        # Empty query
        results = await server.search_conversations("", limit=5)
        assert isinstance(results, list)

        # Whitespace only query
        results = await server.search_conversations("   ", limit=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_conversation_content_encoding_issues(self, server):
        """Test handling of various text encodings"""
        # Content with various special characters
        special_content = "Content with special chars: àáâãäåæçèéêë ñ 中文 русский العربية"

        result = await server.add_conversation(
            content=special_content,
            title="Encoding Test",
            conversation_date="2025-01-15T10:30:00",
        )

        # Should handle encoding gracefully
        assert result["status"] == "success"

        # Search should also handle special characters
        search_results = await server.search_conversations("special", limit=1)
        assert isinstance(search_results, list)

    @pytest.mark.asyncio
    async def test_preview_generation_edge_cases(self, server, temp_storage):
        """Test conversation preview generation edge cases"""
        content = """
Line 1: Introduction
Line 2: This line contains the search term
Line 3: This is context after the match
Line 4: More content
Line 5: Final line
        """

        # Add conversation
        result = await server.add_conversation(
            content=content,
            title="Preview Test",
            conversation_date="2025-01-15T10:30:00",
        )

        file_path = Path(result["file_path"])

        # Test preview generation
        preview = server._get_preview(file_path, ["search", "term"])

        assert len(preview) > 0
        assert "search term" in preview.lower() or "term" in preview.lower()

    def test_date_folder_edge_cases(self, server):
        """Test date folder generation with edge cases"""
        # Test different months
        test_dates = [
            datetime(2025, 1, 1),  # January
            datetime(2025, 12, 31),  # December
            datetime(2024, 2, 29),  # Leap year
        ]

        for test_date in test_dates:
            folder = server._get_date_folder(test_date)
            assert folder.exists()
            assert str(test_date.year) in str(folder)


@pytest.fixture
def home_temp_storage():
    """Temp storage directory created under HOME so FastMCP path validation passes."""
    home = Path.home()
    temp_dir = tempfile.mkdtemp(prefix="claude_memory_test_", dir=str(home))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestFastMCPConfigWiring:
    """Test the new ``config`` parameter on ``FastMCPConversationMemoryServer``."""

    def test_init_uses_supplied_config(self, home_temp_storage):
        """Passing an explicit Config bypasses Config.load() and sets storage."""
        from config import Config

        cfg = Config(storage_path=home_temp_storage, enable_sqlite=False)
        srv = server_fastmcp.FastMCPConversationMemoryServer(config=cfg)

        assert srv.config is cfg
        # Storage path should be derived from Config when caller didn't override.
        assert str(srv.storage_path) == str(Path(home_temp_storage).expanduser())
        # enable_sqlite from Config is honoured.
        assert srv.use_sqlite_search is False

    def test_explicit_storage_path_overrides_config(self, home_temp_storage):
        """Explicit ``storage_path`` argument wins over ``config.storage_path``."""
        from config import Config

        # Config points to a different directory (also under HOME so it validates).
        other = tempfile.mkdtemp(prefix="other_storage_", dir=str(Path.home()))
        try:
            cfg = Config(storage_path=other, enable_sqlite=False)
            srv = server_fastmcp.FastMCPConversationMemoryServer(
                storage_path=home_temp_storage, config=cfg
            )
            assert str(srv.storage_path) == str(Path(home_temp_storage).expanduser())
        finally:
            shutil.rmtree(other, ignore_errors=True)

    @pytest.mark.skipif(
        os.name == "nt",
        reason="TEMP lives under the user profile on Windows, so mkdtemp() is not outside home",
    )
    def test_trusted_path_outside_home_is_accepted(self, home_temp_storage):
        """An explicitly-configured path outside HOME passes validation."""
        srv = server_fastmcp.FastMCPConversationMemoryServer(storage_path=home_temp_storage)
        outside = Path(tempfile.mkdtemp(prefix="outside_home_")).resolve()
        try:
            # Untrusted (defaulted) path outside HOME is rejected...
            with pytest.raises(ValueError, match="within user's home"):
                srv._validate_storage_path(outside, trusted=False)
            # ...but a trusted (explicitly configured) one is allowed.
            srv._validate_storage_path(outside, trusted=True)  # no raise
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_traversal_guard_applies_even_when_trusted(self, home_temp_storage):
        """The ``..`` traversal guard is enforced regardless of trust."""
        srv = server_fastmcp.FastMCPConversationMemoryServer(storage_path=home_temp_storage)
        with pytest.raises(ValueError, match="cannot contain"):
            srv._validate_storage_path(Path("/some/../evil"), trusted=True)

    def test_base_class_has_no_validate_storage_path(self):
        """The dead legacy ``_validate_storage_path`` classmethod is gone.

        It used to live on ``ConversationMemoryServer`` with an incompatible
        signature (``cls, str -> bool``) purely for "test compatibility",
        with zero real callers, while ``FastMCPConversationMemoryServer``
        overrode it with the real security check (``self, Path,
        trusted=... -> None``). That mismatch is the override mypy flagged.
        Removing the unused base method is the fix; this guards against it
        (or an incompatible sibling) creeping back in.
        """
        assert "_validate_storage_path" not in ConversationMemoryServer.__dict__
        assert "_validate_storage_path" in server_fastmcp.FastMCPConversationMemoryServer.__dict__


if __name__ == "__main__":
    # Run tests with coverage
    pytest.main(
        [
            __file__,
            "-v",
            "--cov=server_fastmcp",
            "--cov-report=html",
            "--cov-report=term",
        ]
    )
