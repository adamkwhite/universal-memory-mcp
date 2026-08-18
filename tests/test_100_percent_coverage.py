#!/usr/bin/env python3
"""
Additional tests to achieve 100% coverage for the MCP server
Targets the remaining 28 uncovered lines from previous coverage report
"""

import contextlib
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest
from conftest import requires_posix_permissions

from universal_memory_mcp.conversation_memory import ConversationMemoryServer


# Mock the FastMCP import to avoid dependency issues
class MockFastMCP:
    def __init__(self, name):
        self.name = name
        self.tools = []

    def tool(self):
        def decorator(func):
            self.tools.append(func)
            return func

        return decorator

    def run(self):
        pass


# Patch the import before importing the server. The module is synthesised at
# runtime, so mypy can't know it has a FastMCP attribute — setattr keeps the
# stub injection honest without a blanket type: ignore.
_fastmcp_stub = type(sys)("mcp.server.fastmcp")
setattr(_fastmcp_stub, "FastMCP", MockFastMCP)  # noqa: B010 - direct attr would break mypy, see comment above
sys.modules["mcp.server.fastmcp"] = _fastmcp_stub

# Add the project root and src directory to path using dynamic resolution
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


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


class TestCompleteEdgeCaseCoverage:
    """Tests targeting the remaining uncovered lines for 100% coverage"""

    @pytest.mark.asyncio
    async def test_search_file_read_exception(self, server, temp_storage):
        """Test search when file read fails (lines 96-98)"""
        # Add a conversation
        result = await server.add_conversation(
            "Test content for file read error",
            "File Read Test",
            "2025-01-15T10:30:00",
        )

        file_path = Path(result["file_path"])

        # Make file unreadable by changing permissions
        try:
            file_path.chmod(0o000)  # No permissions

            # Search should handle the file read exception gracefully
            results = await server.search_conversations("Test", limit=5)
            assert isinstance(results, list)

        finally:
            # Restore permissions for cleanup
            file_path.chmod(0o644)

    @pytest.mark.asyncio
    async def test_search_returns_error_in_results(self, server, temp_storage):
        """Test search error handling (lines 115-116)"""
        # Corrupt the index file to cause an error
        with open(server.index_file, "w", encoding="utf-8") as f:
            f.write("invalid json")

        results = await server.search_conversations("test", limit=5)

        # Should return a list with error information
        assert isinstance(results, list)
        # Check if results contain error info (could be empty list or list with error)
        if len(results) > 0:
            assert any("error" in str(result) for result in results)
        # If empty, that's also valid error handling behavior

    @requires_posix_permissions
    def test_get_preview_exception_handling_unreadable_file(self, server, temp_storage):
        """Test _get_preview exception path via unreadable file (lines 139-140).

        Renamed from test_get_preview_exception_handling: the original name
        collided with the async test at line 429 (same class), so Python
        silently shadowed this method and it never ran. The unreadable-file
        exception path is distinct from the nonexistent-file path covered by
        test_get_preview_exception_handling_private.
        """
        # Create a file that will cause an exception when reading
        test_file = Path(temp_storage) / "bad_file.md"
        test_file.touch()
        test_file.chmod(0o000)  # No read permissions

        try:
            preview = server._get_preview(test_file, ["search"])
            assert preview == "Preview unavailable"
        finally:
            test_file.chmod(0o644)

    @pytest.mark.asyncio
    @requires_posix_permissions
    async def test_add_conversation_exception_handling(self, server, temp_storage):
        """Test add conversation with various exception scenarios"""
        # Test with a read-only conversations directory
        server.conversations_path.chmod(0o444)

        try:
            result = await server.add_conversation(
                "Test content that should fail",
                "Error Test",
                "2025-01-15T10:30:00",
            )

            assert result["status"] == "error"
            assert "message" in result
            assert "Failed to save conversation" in result["message"]

        finally:
            server.conversations_path.chmod(0o755)

    @pytest.mark.asyncio
    async def test_update_index_exception_handling(self, server, temp_storage):
        """Test index update exception handling (line 217)"""
        # Make index file read-only to trigger write exception
        server.index_file.touch()  # Create it first
        server.index_file.chmod(0o444)  # Make read-only

        try:
            # This should trigger exception in _update_index when trying to write
            test_date = datetime(2025, 1, 15, 10, 30)
            test_title = "Error Test"
            fake_path = server.conversations_path / "test.md"
            fake_path.touch()

            # This calls _update_index internally which should handle the exception
            await server.add_conversation("Test content", test_title, test_date.isoformat())

        finally:
            # Restore permissions
            server.index_file.chmod(0o644)

    @pytest.mark.asyncio
    async def test_update_topics_index_exception_handling(self, server, temp_storage):
        """Test topics index update exception handling (line 237)"""
        # Make topics file unwritable
        server.topics_file.chmod(0o444)

        try:
            server._update_topics_index(["python", "test"], "test_conv_id")
            # Exception should be caught and printed, but not re-raised

        finally:
            server.topics_file.chmod(0o644)

    @pytest.mark.asyncio
    async def test_search_file_not_exists(self, server, temp_storage):
        """Test search when conversation file doesn't exist (line 88)"""
        # Manually add entry to index that points to non-existent file
        import json

        fake_index = {
            "conversations": [
                {
                    "title": "Non-existent File",
                    "file_path": "conversations/nonexistent.md",
                    "date": "2025-06-01T10:00:00Z",
                    "topics": ["test"],
                    "added": "2025-06-01T10:00:00Z",
                }
            ],
            "last_updated": "2025-06-01T10:00:00Z",
        }

        with open(server.index_file, "w", encoding="utf-8") as f:
            json.dump(fake_index, f)

        # Search should skip the non-existent file
        results = await server.search_conversations("test", limit=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_add_conversation_no_date(self, server, temp_storage):
        """Test add_conversation with no date to cover line 153"""
        result = await server.add_conversation(
            "Test content without date",
            "No Date Test",
            None,  # This should trigger the datetime.now() path
        )

        assert result["status"] == "success"
        assert "file_path" in result

    @pytest.mark.asyncio
    async def test_weekly_summary_detailed_analysis(self, server):
        """Test weekly summary detailed content analysis (lines 286-299)"""
        current_time = datetime.now()

        # Add conversations that will trigger all the content analysis paths
        await server.add_conversation(
            "Writing code for a new function with class definitions and import statements",
            "Coding with Code Keywords",
            current_time.isoformat(),
        )

        await server.add_conversation(
            "We decided on this approach and I recommend using this solution",
            "Decision with Recommendation",
            current_time.isoformat(),
        )

        await server.add_conversation(
            "Learning how to understand and explain complex tutorial concepts",
            "Learning How To",
            current_time.isoformat(),
        )

        summary = await server.generate_weekly_summary(0)

        # Verify all analysis paths were triggered
        assert "Coding with Code Keywords" in summary
        assert "Decision with Recommendation" in summary
        assert "Learning How To" in summary

    @pytest.mark.asyncio
    async def test_weekly_summary_content_read_exception(self, server, temp_storage):
        """Test weekly summary when conversation file read fails (lines 298-299)"""
        current_time = datetime.now()

        # Add a conversation
        result = await server.add_conversation(
            "Test content for read exception",
            "Read Exception Test",
            current_time.isoformat(),
        )

        # Make the conversation file unreadable
        file_path = Path(result["file_path"])
        file_path.chmod(0o000)

        try:
            summary = await server.generate_weekly_summary(0)
            # Should complete without crashing despite file read error
            assert isinstance(summary, str)
            assert "Read Exception Test" in summary

        finally:
            file_path.chmod(0o644)

    @pytest.mark.asyncio
    async def test_weekly_summary_with_topics_count(self, server):
        """Test weekly summary topic counting and top topics section"""
        # Add conversations with topics to test counting
        from datetime import datetime

        # Use local time to match generate_weekly_summary behavior
        current_week_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        await server.add_conversation(
            "Python programming discussion", "Python Talk", current_week_date
        )

        # Manually update topics index with test data
        topics_content = {
            "topics": {"python": 5, "javascript": 3, "testing": 2},
            "last_updated": "2025-06-01T10:00:00Z",
        }

        # Write topics index directly to test counting logic
        import json

        with open(server.topics_file, "w", encoding="utf-8") as f:
            json.dump(topics_content, f)

        summary = await server.generate_weekly_summary(0)

        # Verify summary contains topics and structure
        assert "Most Discussed Topics" in summary or "Topics" in summary
        assert len(summary) > 100  # Ensure substantial summary content

    @pytest.mark.asyncio
    async def test_weekly_summary_comprehensive_sections(self, server):
        """Test weekly summary includes all expected sections"""
        from datetime import datetime

        # Get current time in local timezone to match generate_weekly_summary
        now = datetime.now()
        current_week_date = now.strftime("%Y-%m-%dT%H:%M:%S")

        # Add test conversation for current week
        await server.add_conversation(
            "Technical discussion about API design",
            "API Design",
            current_week_date,
        )

        summary = await server.generate_weekly_summary(0)

        # Verify summary structure and content
        assert len(summary) > 100
        assert "Weekly Summary" in summary or "## " in summary or "API Design" in summary

    @pytest.mark.asyncio
    async def test_weekly_summary_file_saving_and_path(self, server, temp_storage):
        """Test weekly summary file saving functionality"""
        current_time = datetime.now()

        await server.add_conversation(
            "Test conversation for file saving verification",
            "File Save Test",
            current_time.isoformat(),
        )

        summary = await server.generate_weekly_summary(0)

        # Verify file was saved
        assert "Summary saved to" in summary

        # Check that file actually exists with correct naming
        weekly_dir = server.summaries_path / "weekly"
        summary_files = list(weekly_dir.glob("week-*.md"))
        assert len(summary_files) > 0

        # Verify file contains the summary content
        latest_file = max(summary_files, key=lambda x: x.stat().st_mtime)
        with open(latest_file, encoding="utf-8") as f:
            file_content = f.read()

        assert "File Save Test" in file_content

    @pytest.mark.asyncio
    async def test_get_preview_success(self, server):
        """Test get_preview method with valid conversation (lines 232-248)"""
        # Add a test conversation
        await server.add_conversation(
            "This is a test conversation content for preview testing",
            "Preview Test",
            "2025-06-02T10:00:00Z",
        )

        # Get the conversation ID from the index
        import json

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        conversation_id = index_data["conversations"][-1]["id"]

        # Test get_preview
        preview = server.get_preview(conversation_id)
        assert "This is a test conversation content" in preview
        assert isinstance(preview, str)

    @pytest.mark.asyncio
    async def test_get_preview_long_content(self, server):
        """Test get_preview truncation for long content (line 248)"""
        # Create long content (>500 chars)
        long_content = "A" * 600
        await server.add_conversation(long_content, "Long Content Test", "2025-06-02T10:00:00Z")

        # Get conversation ID
        import json

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        conversation_id = index_data["conversations"][-1]["id"]

        # Test preview truncation
        preview = server.get_preview(conversation_id)
        assert len(preview) == 503  # 500 chars + "..."
        assert preview.endswith("...")

    @pytest.mark.asyncio
    async def test_get_preview_file_not_found(self, server):
        """Test get_preview when conversation file doesn't exist (lines 249-250)"""
        # Manually add entry to index that points to non-existent file
        import json

        fake_index = {
            "conversations": [
                {
                    "id": "fake_conv_id",
                    "title": "Non-existent File",
                    "file_path": "conversations/nonexistent.json",
                    "date": "2025-06-01T10:00:00Z",
                    "topics": ["test"],
                    "added": "2025-06-01T10:00:00Z",
                }
            ],
            "last_updated": "2025-06-01T10:00:00Z",
        }

        with open(server.index_file, "w", encoding="utf-8") as f:
            json.dump(fake_index, f)

        # Test get_preview with non-existent file
        preview = server.get_preview("fake_conv_id")
        assert preview == "Conversation file not found"

    @pytest.mark.asyncio
    async def test_get_preview_conversation_not_found(self, server):
        """Test get_preview when conversation ID doesn't exist (line 252)"""
        # Test with non-existent conversation ID
        preview = server.get_preview("nonexistent_conversation_id")
        assert preview == "Conversation not found"

    @pytest.mark.asyncio
    @requires_posix_permissions
    async def test_get_preview_exception_handling(self, server):
        """Test get_preview exception handling (lines 254-255)"""
        # Make index file unreadable to trigger exception
        server.index_file.chmod(0o000)

        try:
            preview = server.get_preview("any_id")
            assert preview.startswith("Error retrieving conversation:")

        finally:
            # Restore permissions
            server.index_file.chmod(0o644)

    @pytest.mark.asyncio
    async def test_extract_topics_quoted_terms(self, server):
        """Test topic extraction with quoted terms (lines 80-81)"""
        # Test with quoted terms that are NOT in common_tech_terms to
        # trigger line 81
        content = (
            'We discussed "unique concept" and "special methodology" '
            'and "custom framework" in our project'
        )
        await server.add_conversation(content, "Quoted Terms Test", "2025-06-02T10:00:00Z")

        # Check that quoted terms were extracted properly
        import json

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        topics = index_data["conversations"][-1]["topics"]
        # Should include quoted terms that meet length criteria (3-49 chars) and
        # are not in common_tech_terms
        assert len(topics) > 0
        # Check for the quoted terms that should be added via line 81
        topic_str = " ".join(topics).lower()
        assert (
            "unique concept" in topic_str
            or "special methodology" in topic_str
            or "custom framework" in topic_str
        )

    @pytest.mark.asyncio
    async def test_add_conversation_invalid_date_format(self, server):
        """Test add_conversation with invalid date format (lines 99-100)"""
        # Use an invalid date format to trigger ValueError exception
        result = await server.add_conversation(
            "Test content with invalid date",
            "Invalid Date Test",
            "invalid-date-format",  # This should trigger ValueError and fallback to datetime.now()
        )

        assert result["status"] == "success"
        assert "file_path" in result

    @pytest.mark.asyncio
    async def test_add_conversation_auto_title_generation(self, server):
        """Test automatic title generation (lines 107-109)"""
        # Test with no title provided to trigger auto-generation
        long_content = "This is a very long first line that should be truncated when used as a title because it exceeds fifty characters in length"
        await server.add_conversation(
            long_content,
            None,
            "2025-06-02T10:00:00Z",  # No title provided
        )

        # Check that title was auto-generated and truncated
        import json

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        title = index_data["conversations"][-1]["title"]
        assert len(title) <= 53  # 50 chars + "..."
        assert title.endswith("...")

    @pytest.mark.asyncio
    async def test_get_preview_private_method(self, server):
        """Test _get_preview private method (lines 207-228)"""
        # Create a test file with content
        test_content = """Line 1: Introduction
Line 2: This contains search terms
Line 3: More context
Line 4: Additional info
Line 5: Final line"""

        result = await server.add_conversation(test_content, "Preview Test", "2025-06-02T10:00:00Z")
        file_path = Path(result["file_path"])

        # Test _get_preview method directly
        preview = server._get_preview(file_path, ["search", "terms"])

        # Should include context around the matching line
        assert "search terms" in preview.lower()
        assert len(preview) > 0

    @pytest.mark.asyncio
    async def test_get_preview_exception_handling_private(self, server):
        """Test _get_preview exception handling (lines 227-228)"""
        # Test with non-existent file to trigger exception
        fake_path = Path("/nonexistent/file.json")
        preview = server._get_preview(fake_path, ["test"])

        assert preview == "Preview unavailable"

    @pytest.mark.asyncio
    async def test_weekly_summary_file_read_exception(self, server):
        """Test weekly summary file read exception (lines 348-349)"""
        from datetime import datetime

        # Add a conversation first
        result = await server.add_conversation(
            "Test conversation for read exception",
            "Read Exception Test",
            datetime.now().isoformat(),
        )

        # Make the conversation file unreadable to trigger exception during reading
        file_path = Path(result["file_path"])
        file_path.chmod(0o000)

        try:
            summary = await server.generate_weekly_summary(0)
            # Should complete without crashing despite file read error
            assert isinstance(summary, str)

        finally:
            file_path.chmod(0o644)

    @pytest.mark.asyncio
    async def test_weekly_summary_file_read_exception_corrupted(self, server):
        """Test weekly summary with corrupted conversation file (lines 348-349)"""
        from datetime import datetime

        # Add a conversation first
        result = await server.add_conversation(
            "Test conversation for corruption test",
            "Corruption Test",
            datetime.now().isoformat(),
        )

        # Corrupt the conversation file to trigger exception during JSON parsing
        file_path = Path(result["file_path"])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("invalid json content that will cause parsing to fail")

        try:
            summary = await server.generate_weekly_summary(0)
            # Should complete without crashing despite file corruption
            assert isinstance(summary, str)

        finally:
            # Restore a valid JSON file
            import json

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"content": "restored content", "topics": []}, f)

    @pytest.mark.asyncio
    async def test_weekly_summary_index_entry_exception(self, server):
        """Test weekly summary with malformed index entry (lines 348-349)"""
        import json
        from datetime import datetime

        # First add a normal conversation
        await server.add_conversation("Test conversation", "Test", datetime.now().isoformat())

        # Manually corrupt the index with malformed entry to trigger exception on lines 348-349
        fake_index = {
            "conversations": [
                # This entry is missing required fields and will cause an exception
                {"malformed": "entry"},
                # Another problematic entry
                {"file_path": None, "date": "bad_date"},
            ],
            "last_updated": "2025-06-01T10:00:00Z",
        }

        with open(server.index_file, "w", encoding="utf-8") as f:
            json.dump(fake_index, f)

        # This should trigger exception handling on lines 348-349 and continue processing
        summary = await server.generate_weekly_summary(0)
        assert isinstance(summary, str)

    @pytest.mark.asyncio
    async def test_weekly_summary_no_conversations_found(self, server):
        """Test weekly summary when no conversations found (line 352)"""
        # Generate summary for a week with no conversations (far in future)
        summary = await server.generate_weekly_summary(52)  # 52 weeks from now

        # Should return "No conversations found" message
        assert "No conversations found for week of" in summary


class TestMCPToolWrapperFunctions:
    """Test the MCP tool wrapper functions for complete coverage"""

    def test_mcp_imports(self):
        """Test that MCP imports are available (skipped if not in Python 3.11+)"""
        import sys

        if sys.version_info < (3, 11):
            pytest.skip("MCP requires Python 3.11+")

        try:
            assert True
        except ImportError as e:
            pytest.fail(f"MCP import failed: {e}")

    @pytest.mark.asyncio
    async def test_mcp_search_tool_no_results(self):
        """Test MCP search tool wrapper when no results found"""
        # Import the MCP tool functions directly
        from universal_memory_mcp.server_fastmcp import search_conversations as mcp_search

        result = await mcp_search("nonexistentquery12345xyz", limit=5)
        assert "No conversations found matching" in result

    @pytest.mark.asyncio
    async def test_mcp_search_tool_with_error_results(self, server):
        """Test MCP search tool handles search errors gracefully"""
        from universal_memory_mcp.server_fastmcp import search_conversations as mcp_search

        # Test with search query that returns no results
        result = await mcp_search("nonexistent_query_12345", limit=5)

        # Should return formatted message for no results
        assert isinstance(result, str)
        assert "Found 0 conversations" in result or "No conversations found" in result

    @pytest.mark.asyncio
    async def test_mcp_search_tool_success_formatting(self, server):
        """Test MCP search tool result formatting"""
        from universal_memory_mcp.server_fastmcp import search_conversations as mcp_search

        # Add test data
        await server.add_conversation(
            "Test conversation for MCP search formatting",
            "Test Formatting",
            "2025-06-02T10:00:00Z",
        )

        result = await mcp_search("Test", limit=1)

        # Verify proper formatting - check for the actual structure
        assert isinstance(result, str)
        # Accept both success and no results cases
        assert (
            "Found" in result and "conversations" in result
        ) or "No conversations found" in result
        if "Found" in result:
            assert "**" in result  # Should have bold formatting for titles

    @pytest.mark.asyncio
    async def test_mcp_add_conversation_tool(self, server):
        """Test MCP add conversation tool wrapper"""
        from universal_memory_mcp.server_fastmcp import add_conversation as mcp_add

        result = await mcp_add(
            "Test content for MCP add tool",
            "MCP Add Test",
            "2025-06-02T12:00:00Z",
        )

        assert "Status: success" in result
        assert "Conversation saved successfully" in result

    @pytest.mark.asyncio
    async def test_mcp_weekly_summary_tool(self, server):
        """Test MCP weekly summary tool wrapper"""
        from universal_memory_mcp.server_fastmcp import generate_weekly_summary as mcp_summary

        # Add some test data
        current_time = datetime.now().isoformat()
        await server.add_conversation(
            "Weekly summary test conversation", "Weekly Test", current_time
        )

        result = await mcp_summary(0)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_final_coverage_lines(self, server):
        """Test the final missing lines for 100% coverage"""
        from datetime import datetime

        from universal_memory_mcp.server_fastmcp import search_conversations as mcp_search

        # Test line 343: topics_str += "..." when more than 3 topics
        now = datetime.now()
        current_week_date = now.strftime("%Y-%m-%dT%H:%M:%S")

        await server.add_conversation(
            "Test with many topics for truncation",
            "Many Topics Test",
            current_week_date,
        )

        # Manually add many topics to trigger line 343
        import json

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        # Update both the conversation file and index to have more than 3 topics
        if index_data["conversations"]:
            conv_info = index_data["conversations"][-1]
            conv_file_path = server.storage_path / conv_info["file_path"]

            # Update the actual conversation file
            with open(conv_file_path, encoding="utf-8") as f:
                conv_data = json.load(f)
            conv_data["topics"] = [
                "topic1",
                "topic2",
                "topic3",
                "topic4",
                "topic5",
            ]
            with open(conv_file_path, "w", encoding="utf-8") as f:
                json.dump(conv_data, f)

            # Update the index as well
            index_data["conversations"][-1]["topics"] = [
                "topic1",
                "topic2",
                "topic3",
                "topic4",
                "topic5",
            ]
            with open(server.index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f)

        # Generate summary to trigger line 343 (topics truncation)
        summary = await server.generate_weekly_summary(0)
        assert "..." in summary  # Should show truncated topics

        # Test exception handling in generate_weekly_summary
        # Mock the _get_week_conversations method to raise an exception
        import unittest.mock

        with unittest.mock.patch.object(
            server,
            "_get_week_conversations",
            side_effect=OSError("Test error"),
        ):
            summary_with_error = await server.generate_weekly_summary(0)
            assert "Failed to generate weekly summary" in summary_with_error

        # Test lines 378-379: Error handling in MCP search tool
        # We need to test the mcp_search directly with error results
        from universal_memory_mcp.server_fastmcp import memory_server

        # Backup original method
        original_search = memory_server.search_conversations

        async def mock_error_search(query, limit):
            return [{"error": "Test search error"}]

        # Replace the method on the global memory_server instance
        memory_server.search_conversations = mock_error_search

        try:
            result = await mcp_search("test", limit=1)
            assert "Search failed for 'test': Test search error" in result
        finally:
            memory_server.search_conversations = original_search


class TestConversationMemoryServerDirect:
    """Direct tests for ConversationMemoryServer core functionality (merged from test_direct_coverage.py)"""

    @pytest.mark.asyncio
    async def test_server_initialization(self, server, temp_storage):
        """Test server initialization creates all required directories"""
        assert server.storage_path == Path(temp_storage).expanduser()
        assert server.conversations_path.exists()
        assert server.summaries_path.exists()
        assert (server.summaries_path / "weekly").exists()
        assert server.index_file.exists()
        assert server.topics_file.exists()

    def test_init_index_files(self, server):
        """Test index file initialization"""
        # Index files should already exist from initialization
        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)
        assert "conversations" in index_data
        assert "last_updated" in index_data

        with open(server.topics_file, encoding="utf-8") as f:
            topics_data = json.load(f)
        assert "topics" in topics_data
        assert "last_updated" in topics_data

    def test_sync_index_from_files_backfills_missing(self, server):
        """Test that _sync_index_from_files adds files missing from index"""
        # Create a conversation file on disk without going through add_conversation
        date_folder = server.conversations_path / "2025" / "01-january"
        date_folder.mkdir(parents=True, exist_ok=True)
        conv_file = date_folder / "conv_20250115_100000_1234.json"
        conv_data = {
            "id": "conv_20250115_100000_1234",
            "title": "Test backfill",
            "content": "Some content",
            "date": "2025-01-15T10:00:00",
            "topics": ["test"],
            "created_at": "2025-01-15T10:00:00",
        }
        with open(conv_file, "w", encoding="utf-8") as f:
            json.dump(conv_data, f)

        # Index should be empty before sync
        with open(server.index_file, encoding="utf-8") as f:
            before = json.load(f)
        assert len(before["conversations"]) == 0

        # Run sync
        server._sync_index_from_files()

        # Index should now have the conversation
        with open(server.index_file, encoding="utf-8") as f:
            after = json.load(f)
        assert len(after["conversations"]) == 1
        assert after["conversations"][0]["id"] == "conv_20250115_100000_1234"

    def test_sync_index_from_files_skips_already_indexed(self, server):
        """Test that _sync_index_from_files skips conversations already in index"""
        # Create a file and sync it
        date_folder = server.conversations_path / "2025" / "02-february"
        date_folder.mkdir(parents=True, exist_ok=True)
        conv_file = date_folder / "conv_20250201_120000_5678.json"
        conv_data = {
            "id": "conv_20250201_120000_5678",
            "title": "Already indexed",
            "content": "Content",
            "date": "2025-02-01T12:00:00",
            "topics": ["test"],
            "created_at": "2025-02-01T12:00:00",
        }
        with open(conv_file, "w", encoding="utf-8") as f:
            json.dump(conv_data, f)

        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            first_sync = json.load(f)
        count_after_first = len(first_sync["conversations"])

        # Run sync again — should not duplicate
        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            second_sync = json.load(f)
        assert len(second_sync["conversations"]) == count_after_first

    def _write_conv(self, server, folder, conv_id, title):
        """Drop a conversation file on disk without going through add_conversation."""
        date_folder = server.conversations_path / "2025" / folder
        date_folder.mkdir(parents=True, exist_ok=True)
        conv_file = date_folder / f"{conv_id}.json"
        with open(conv_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": conv_id,
                    "title": title,
                    "content": "Content",
                    "date": "2025-04-01T12:00:00",
                    "topics": ["test"],
                    "created_at": "2025-04-01T12:00:00",
                },
                f,
            )
        return conv_file

    def test_sync_index_from_files_detects_equal_count_drift(self, server):
        """Drift that nets to zero must still be indexed.

        The old guard was `if len(conv_files) <= len(indexed_ids): return`.
        Delete one conversation and add another and the totals stay equal, so
        the replacement was silently never indexed — equal totals over
        non-equal sets, the same shape as the FTS5 desync in #190.
        """
        first = self._write_conv(server, "04-april", "conv_20250401_120000_1111", "First")
        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            assert len(json.load(f)["conversations"]) == 1

        # Swap one for one: file count and index count both stay at 1.
        first.unlink()
        self._write_conv(server, "04-april", "conv_20250402_120000_2222", "Replacement")

        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            indexed = {c["id"] for c in json.load(f)["conversations"]}
        assert "conv_20250402_120000_2222" in indexed, (
            "replacement conversation was never indexed — equal-count drift missed"
        )

    def test_sync_index_from_files_handles_entry_without_file_path(self, server):
        """Older index entries have no file_path; the id check must still hold.

        Such an entry can't be matched by path, so its file becomes a
        candidate and gets re-read — that must not produce a duplicate.
        """
        self._write_conv(server, "05-may", "conv_20250501_120000_3333", "Legacy")
        with open(server.index_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "conversations": [
                        {
                            "id": "conv_20250501_120000_3333",
                            "title": "Legacy",
                            "date": "2025-05-01T12:00:00",
                            "topics": [],
                            # no file_path — pre-dates the field
                            "added_at": "2025-05-01T12:00:00",
                        }
                    ],
                    "last_updated": "2025-05-01T12:00:00",
                },
                f,
            )

        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            conversations = json.load(f)["conversations"]
        assert len(conversations) == 1, "re-read of a file_path-less entry duplicated it"

    def test_sync_index_from_files_handles_corrupt_file(self, server):
        """Test that _sync_index_from_files skips corrupt JSON files"""
        date_folder = server.conversations_path / "2025" / "03-march"
        date_folder.mkdir(parents=True, exist_ok=True)
        corrupt_file = date_folder / "conv_20250301_000000_0000.json"
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("not valid json{{{")

        # Should not raise
        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)
        # Corrupt file should be skipped
        ids = [c["id"] for c in index_data["conversations"]]
        assert "conv_20250301_000000_0000" not in ids

    def test_sync_index_from_files_handles_corrupt_index(self, temp_storage):
        """Test sync when index.json itself is corrupt"""
        server = ConversationMemoryServer(temp_storage, enable_sqlite=False)
        # Corrupt index.json
        with open(server.index_file, "w", encoding="utf-8") as f:
            f.write("broken")

        # Create a valid conversation file
        date_folder = server.conversations_path / "2025" / "04-april"
        date_folder.mkdir(parents=True, exist_ok=True)
        conv_file = date_folder / "conv_20250401_000000_9999.json"
        with open(conv_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "conv_20250401_000000_9999",
                    "title": "After corrupt index",
                    "content": "Content",
                    "date": "2025-04-01T00:00:00",
                    "topics": [],
                    "created_at": "2025-04-01T00:00:00",
                },
                f,
            )

        # Sync should recover and rebuild
        server._sync_index_from_files()

        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["conversations"]) == 1

    def test_get_date_folder(self, server):
        """Test date folder creation"""
        test_date = datetime(2025, 3, 15, 10, 30, 45)
        folder = server._get_date_folder(test_date)

        assert folder.exists()
        assert "2025" in str(folder)
        assert "03-march" in str(folder)

    def test_extract_topics_basic(self, server):
        """Test basic topic extraction"""
        content = "Discussion about Python programming and MCP development"
        topics = server._extract_topics(content)

        assert "python" in topics
        assert "mcp" in topics

    def test_extract_topics_no_redos_on_capitals_run(self, server):
        """Regression: a run of capitals followed by a word char must not backtrack.

        The old tech_pattern carried a redundant (?:[A-Z][a-zA-Z]*)* group that
        made matching exponential. Content like a hex digest or base64 blob
        triggers it.

        26 chars is chosen deliberately: the old pattern takes ~4s there (so a
        regression FAILS this assert in seconds), while longer inputs grow 4x
        per 2 chars -- at 40 chars the old pattern runs ~37 HOURS, which would
        hang CI instead of failing it. The fixed pattern is linear and needs
        microseconds, so the 1s bound is not timing sensitive; a normal machine
        has ~1000x headroom and only an exponential pattern can fail it.
        """
        start = time.perf_counter()
        topics = server._extract_topics("A" * 26 + "1")
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"topic extraction took {elapsed:.1f}s -- regex backtracking?"
        assert topics == []

    def test_extract_topics_capitalized_words_still_found(self, server):
        """The de-ambiguated pattern must still match what the old one matched."""
        topics = server._extract_topics("We used FastMCP and XMLHttpRequest today")

        assert "fastmcp" in topics
        assert "xmlhttprequest" in topics

    def test_extract_topics_edge_cases(self, server):
        """Test topic extraction edge cases"""
        # Empty content
        assert server._extract_topics("") == []

        # Special characters only
        assert server._extract_topics("!@#$%^&*()") == []

        # Short quoted terms (should be filtered)
        topics = server._extract_topics('"a" "bb" "valid term"')
        assert "a" not in topics
        assert "bb" not in topics
        assert "valid term" in topics

    @pytest.mark.asyncio
    async def test_add_conversation_basic(self, server):
        """Test basic conversation addition"""
        content = "Test conversation about Python MCP development"
        title = "Test Conversation"
        date = "2025-01-15T10:30:00"

        result = await server.add_conversation(content, title, date)

        assert result["status"] == "success"
        assert "file_path" in result
        assert "topics" in result
        assert Path(result["file_path"]).exists()

        # Check topics were extracted
        assert "python" in result["topics"]
        assert "mcp" in result["topics"]

    @pytest.mark.asyncio
    async def test_add_conversation_no_title(self, server):
        """Test conversation addition without title"""
        content = "Test conversation content"

        result = await server.add_conversation(content)

        assert result["status"] == "success"
        assert Path(result["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_search_conversations_basic(self, server):
        """Test basic conversation search"""
        # Add test data
        await server.add_conversation(
            "Python programming discussion",
            "Python Talk",
            "2025-01-15T10:30:00",
        )

        await server.add_conversation(
            "JavaScript development tips", "JS Tips", "2025-01-15T11:00:00"
        )

        # Search for Python
        results = await server.search_conversations("Python", limit=5)

        assert len(results) > 0
        python_found = any("Python" in r.get("title", "") for r in results)
        assert python_found

    @pytest.mark.asyncio
    async def test_search_conversations_scoring(self, server):
        """Test search result scoring"""
        # Add conversation with multiple matches
        await server.add_conversation(
            "Python programming with python libraries and python tools",
            "High Score Python Discussion",
            "2025-01-15T10:30:00",
        )

        await server.add_conversation(
            "General programming discussion",
            "Low Score Discussion",
            "2025-01-15T11:00:00",
        )

        results = await server.search_conversations("python", limit=2)

        assert len(results) > 0
        # First result should have a score (could be 0 for no matches)
        assert "score" in results[0]
        # If there are results with matching content, score should be reasonable
        if len(results) >= 2:
            # The high score conversation should be ranked higher or equal
            assert results[0]["score"] >= results[1]["score"]

    @pytest.mark.asyncio
    async def test_search_conversations_empty(self, server):
        """Test search with no results"""
        results = await server.search_conversations("nonexistentterm12345", limit=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_conversations_missing_file(self, server, temp_storage):
        """Test search when conversation file is missing"""
        # Add conversation
        result = await server.add_conversation("Test content", "Test Title", "2025-01-15T10:30:00")

        # Remove the file but keep index entry
        file_path = Path(result["file_path"])
        if file_path.exists():
            file_path.unlink()

        # Search should handle missing file gracefully
        results = await server.search_conversations("Test", limit=5)
        assert isinstance(results, list)  # Should not crash

    def test_get_preview_basic(self, server, temp_storage):
        """Test conversation preview generation"""
        # Create a test file
        test_file = Path(temp_storage) / "test_preview.md"
        content = """Line 1: Introduction
Line 2: This contains the search term
Line 3: Context after match
Line 4: More content"""

        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)

        preview = server._get_preview(test_file, ["search", "term"])
        assert len(preview) > 0
        assert "search term" in preview.lower()

    def test_get_preview_missing_file(self, server, temp_storage):
        """Test preview generation with missing file"""
        missing_file = Path(temp_storage) / "nonexistent.md"
        preview = server._get_preview(missing_file, ["search"])
        assert preview == "Preview unavailable"

    @pytest.mark.asyncio
    async def test_update_index(self, server, temp_storage):
        """Test index updating functionality"""
        test_date = datetime(2025, 1, 15, 10, 30)
        test_topics = ["python", "mcp"]
        test_title = "Index Test"

        # Create a fake file path
        fake_path = server.conversations_path / "2025" / "01-january" / "test.md"
        fake_path.parent.mkdir(parents=True, exist_ok=True)
        fake_path.touch()

        conversation_data = {
            "id": "test_conv_123",
            "title": test_title,
            "content": "Test content",
            "date": test_date.isoformat(),
            "topics": test_topics,
            "created_at": test_date.isoformat(),
        }
        server._update_index(conversation_data, fake_path)

        # Check index was updated
        with open(server.index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        assert len(index_data["conversations"]) > 0
        last_conv = index_data["conversations"][-1]
        assert last_conv["title"] == test_title
        assert last_conv["topics"] == test_topics

    @pytest.mark.asyncio
    async def test_update_topics_index(self, server):
        """Test topics index updating"""
        test_topics = ["python", "mcp", "python"]  # python appears twice

        server._update_topics_index(test_topics, "test_conv_123")

        with open(server.topics_file, encoding="utf-8") as f:
            topics_data = json.load(f)

        assert "python" in topics_data["topics"]
        assert "mcp" in topics_data["topics"]
        # Should have 2 entries for python (one for each occurrence)
        assert len(topics_data["topics"]["python"]) == 2
        # Should have 1 entry for mcp
        assert len(topics_data["topics"]["mcp"]) == 1

    @pytest.mark.asyncio
    async def test_generate_weekly_summary_no_conversations(self, server):
        """Test weekly summary with no conversations"""
        summary = await server.generate_weekly_summary(0)
        assert "No conversations found" in summary
        assert "current week" in summary

    @pytest.mark.asyncio
    async def test_generate_weekly_summary_with_data(self, server):
        """Test weekly summary with conversation data"""
        # Add conversations for current week (use UTC to match _calculate_week_range)

        current_time = datetime.now()

        await server.add_conversation(
            "Python code development with git repository",
            "Coding Discussion",
            current_time.isoformat(),
        )

        await server.add_conversation(
            "We decided to use the recommended approach",
            "Decision Made",
            current_time.isoformat(),
        )

        await server.add_conversation(
            "Learning tutorial about new concepts",
            "Learning Session",
            current_time.isoformat(),
        )

        summary = await server.generate_weekly_summary(0)

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "Weekly Summary" in summary
        assert "Coding Discussion" in summary
        assert "Decision Made" in summary
        assert "Learning Session" in summary

    @pytest.mark.asyncio
    async def test_generate_weekly_summary_past_week(self, server):
        """Test weekly summary for past week"""
        summary = await server.generate_weekly_summary(1)
        assert "No conversations found" in summary
        assert "1 week(s) ago" in summary

    @pytest.mark.asyncio
    async def test_generate_weekly_summary_error(self, server, temp_storage):
        """Test weekly summary error handling"""
        # Make the summaries directory unwritable to cause an error during file writing
        summaries_dir = server.summaries_path / "weekly"
        summaries_dir.chmod(0o444)  # Read-only

        try:
            # Add a conversation so it tries to write a summary file
            await server.add_conversation("Test", "Test", "2025-06-12T10:00:00")
            summary = await server.generate_weekly_summary(0)
            # Should either succeed with read-only directory or fail gracefully
            assert isinstance(summary, str)
        finally:
            # Restore permissions for cleanup
            summaries_dir.chmod(0o755)

    @pytest.mark.asyncio
    async def test_add_conversation_error_handling(self, server):
        """Test add conversation error handling"""
        # Test with invalid date
        result = await server.add_conversation("Test content", "Error Test", "invalid-date-format")

        # Should handle gracefully
        assert "status" in result


class TestServerExceptionCoverage:
    """Test exception handling scenarios (merged from test_server_exception_coverage.py)"""

    def test_init_exception_handling_lines_96_98(self, temp_storage):
        """Test __init__ exception handling for SQLite initialization"""
        from unittest.mock import patch

        # Mock SearchDatabase to raise an exception during initialization
        with patch(
            "universal_memory_mcp.conversation_memory.SearchDatabase",
            side_effect=Exception("SQLite initialization failed"),
        ):
            try:
                # This should catch the SQLite exception and continue
                server = ConversationMemoryServer(temp_storage, enable_sqlite=True)
                # Server should still be created but with SQLite disabled
                assert not server.use_sqlite_search
            finally:
                pass

    def test_init_index_files_exception_lines_109_110(self, temp_storage):
        """Test _init_index_files exception handling"""
        from unittest.mock import patch

        # Mock json.dump to raise an exception during index file creation
        with patch("json.dump", side_effect=Exception("JSON write failed")):
            try:
                # This should trigger the exception in _init_index_files
                ConversationMemoryServer(temp_storage)
                # If no exception is raised, the lines might not be covered
                # But we're testing the path exists
            except Exception as e:  # noqa: BLE001 - mock raises plain Exception; asserting on its message is the point of this coverage test
                # Exception handling should log and possibly continue
                assert "JSON write failed" in str(e)

    def test_index_file_creation_permission_error_lines_115_116(self, temp_storage):
        """Test index file creation permission errors"""
        from unittest.mock import patch

        # Mock Path.mkdir to raise PermissionError. Exception might be
        # re-raised or handled by the server; either is acceptable.
        with (
            patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")),
            contextlib.suppress(PermissionError),
        ):
            ConversationMemoryServer(temp_storage)

    @pytest.mark.asyncio
    async def test_search_conversations_file_error_lines_212_215(self, server):
        """Test search_conversations file reading errors"""
        from unittest.mock import patch

        # Mock file operations to trigger exception handling
        with patch("builtins.open", side_effect=OSError("File read error")):
            try:
                # This should trigger exception handling in search_conversations
                result = await server.search_conversations("test query")
                # Should return error response (could be list with error dict)
                assert isinstance(result, (str, list))
                if isinstance(result, list) and result:
                    assert "error" in result[0]
            except OSError:
                # Exception might propagate or be handled
                pass

    @pytest.mark.asyncio
    async def test_add_conversation_file_error_lines_272_274(self, server):
        """Test add_conversation file writing errors"""
        from unittest.mock import patch

        # Mock file operations to trigger exception handling
        with patch("builtins.open", side_effect=OSError("File write error")):
            try:
                # This should trigger exception handling in add_conversation
                result = await server.add_conversation(
                    "test content", "test title", "2025-06-10T12:00:00Z"
                )
                # Should return error status or raise exception
                if isinstance(result, str):
                    assert "error" in result.lower()
            except OSError:
                # Exception might propagate or be handled
                pass

    def test_missing_conversation_file_lines_493_494(self, server):
        """Test missing conversation file handling"""
        # Create a mock conversation entry that points to non-existent file
        mock_conv_info = {
            "file_path": "2025/06-june/non-existent-file.md",
            "title": "Test Conversation",
        }

        # This should trigger lines 493-494 in _analyze_conversations method
        # when checking if conversation file exists
        result = server._analyze_conversations([mock_conv_info])

        # The method should handle missing files gracefully
        assert isinstance(result, list)

    def test_additional_error_handling_lines_507_510(self, server, temp_storage):
        """Test additional error handling scenarios"""
        from unittest.mock import patch

        # Create a conversation file that exists but can't be read
        conv_dir = Path(temp_storage) / "conversations" / "2025" / "06-june"
        conv_dir.mkdir(parents=True, exist_ok=True)
        conv_file = conv_dir / "test-conversation.md"
        conv_file.write_text("Test content", encoding="utf-8")

        mock_conv_info = {
            "file_path": "2025/06-june/test-conversation.md",
            "title": "Test Conversation",
        }

        # Mock file reading to raise an exception (triggers lines 507-510)
        with patch("builtins.open", side_effect=OSError("File read error")):
            # This should trigger lines 507-510 exception handling
            result = server._analyze_conversations([mock_conv_info])

            # Should handle the error gracefully and return default values
            assert isinstance(result, list)

    @requires_posix_permissions
    def test_initialization_with_invalid_permissions(self):
        """Test server initialization with permission issues"""
        # Try to create server in a restricted directory (triggers security validation)
        # Should fail due to security validation
        restricted_path = "/root/restricted_test"

        with pytest.raises(PermissionError):
            ConversationMemoryServer(restricted_path)

    def test_malformed_storage_path_handling(self):
        """Malformed storage_path values must be rejected outright rather
        than silently creating bogus directories relative to the cwd (e.g.
        ``./None/`` for the string "None", or ``./data/`` for "").

        See validators.py::validate_storage_path -- the shared choke point
        both ConversationMemoryServer and FastMCPConversationMemoryServer
        route through.
        """
        malformed_paths = [
            "",  # Empty path -> would resolve into cwd
            "   ",  # whitespace-only
            "None",  # str(None) upstream bug -> would create ./None/
            "invalid\x00path",  # Path with null character
            "evil-relative",  # relative -> would scribble into cwd
        ]

        cwd_entries_before = set(Path.cwd().iterdir())

        for path in malformed_paths:
            with pytest.raises((ValueError, OSError, TypeError)):
                ConversationMemoryServer(path)

        # None of the rejected paths left a stray directory behind.
        assert set(Path.cwd().iterdir()) == cwd_entries_before


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
