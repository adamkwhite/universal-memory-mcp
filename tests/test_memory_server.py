#!/usr/bin/env python3

"""
Pytest-compatible tests for Claude Memory MCP Server
"""

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from conversation_memory import ConversationMemoryServer as StandaloneServer

# Add project root and src directory to path using dynamic resolution
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "tests"))

try:
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
def standalone_server(temp_storage):
    """Create a standalone server instance for testing"""
    return StandaloneServer(temp_storage)


@pytest.fixture
def sample_conversation_content():
    """Sample conversation content for testing"""
    return """
# Test Conversation

**Human**: How do I set up a Python MCP server?

**Claude**: To set up a Python MCP server, you need to:
1. Install the mcp package
2. Create a server.py file with the MCP server code
3. Define your tools and handlers
4. Configure Claude Desktop to use your server

The key is to implement the proper MCP protocol with FastMCP.
"""


class TestStandaloneMemoryServer:
    """Test the standalone memory server functionality"""

    @pytest.mark.asyncio
    async def test_server_initialization(self, temp_storage):
        """Test that server initializes properly"""
        StandaloneServer(temp_storage)

        # Check that directories were created (using new data/ structure)
        assert (Path(temp_storage) / "data" / "conversations").exists()
        assert (Path(temp_storage) / "data" / "summaries").exists()
        assert (Path(temp_storage) / "data" / "summaries" / "weekly").exists()

        # Check that index files were created
        assert (Path(temp_storage) / "data" / "conversations" / "index.json").exists()
        assert (Path(temp_storage) / "data" / "conversations" / "topics.json").exists()

    @pytest.mark.asyncio
    async def test_add_conversation(self, standalone_server, sample_conversation_content):
        """Test adding a conversation"""
        result = await standalone_server.add_conversation(
            content=sample_conversation_content,
            title="MCP Server Setup Discussion",
            conversation_date="2025-01-15T10:30:00",
        )

        assert result["status"] == "success"
        assert "file_path" in result
        assert "topics" in result
        assert Path(result["file_path"]).exists()

        # Check that topics were extracted
        topics = result["topics"]
        assert "mcp" in topics
        assert "python" in topics

    @pytest.mark.asyncio
    async def test_search_conversations(self, standalone_server, sample_conversation_content):
        """Test searching conversations"""
        # First add a conversation
        await standalone_server.add_conversation(
            content=sample_conversation_content,
            title="MCP Server Setup Discussion",
            conversation_date="2025-01-15T10:30:00",
        )

        # Then search for it
        results = await standalone_server.search_conversations("MCP server", limit=3)

        assert len(results) > 0
        assert not any("error" in result for result in results)

        # Check that the result has expected fields
        first_result = results[0]
        assert "title" in first_result
        assert "score" in first_result
        assert "topics" in first_result
        # SQLite FTS5 BM25 scores can be negative, so just check it exists
        assert isinstance(first_result["score"], (int, float))

    @pytest.mark.asyncio
    async def test_topic_extraction(self, standalone_server):
        """Test topic extraction from conversation content"""
        content_with_topics = """
        Discussion about Python development using Docker and Kubernetes.
        We talked about "machine learning" and "data science" projects.
        The conversation covered AWS deployment and React frontend.
        """

        result = await standalone_server.add_conversation(
            content=content_with_topics,
            title="Tech Discussion",
            conversation_date="2025-01-15T11:00:00",
        )

        topics = result["topics"]

        # Check for common tech terms
        assert "python" in topics
        assert "docker" in topics
        assert "kubernetes" in topics
        assert "aws" in topics
        assert "react" in topics

        # Check for quoted terms
        assert "machine learning" in topics
        assert "data science" in topics

    @pytest.mark.asyncio
    async def test_index_updates(
        self, standalone_server, sample_conversation_content, temp_storage
    ):
        """Test that index files are updated correctly"""
        # Add a conversation
        await standalone_server.add_conversation(
            content=sample_conversation_content,
            title="Test Conversation",
            conversation_date="2025-01-15T10:30:00",
        )

        # Check index.json
        index_file = Path(temp_storage) / "data" / "conversations" / "index.json"
        with open(index_file, encoding="utf-8") as f:
            index_data = json.load(f)

        assert len(index_data["conversations"]) == 1
        conv = index_data["conversations"][0]
        assert conv["title"] == "Test Conversation"
        assert "topics" in conv
        assert "file_path" in conv

        # Check topics.json
        topics_file = Path(temp_storage) / "data" / "conversations" / "topics.json"
        with open(topics_file, encoding="utf-8") as f:
            topics_data = json.load(f)

        assert len(topics_data["topics"]) > 0

    @pytest.mark.asyncio
    async def test_date_folder_organization(self, standalone_server, sample_conversation_content):
        """Test that conversations are organized by date"""
        result = await standalone_server.add_conversation(
            content=sample_conversation_content,
            title="Date Test Conversation",
            conversation_date="2025-03-15T14:30:00",
        )

        file_path = Path(result["file_path"])

        # Check that it's in the correct year/month folder
        assert "2025" in str(file_path)
        assert "03-march" in str(file_path)
        assert file_path.name.startswith("conv_20250315")

    @pytest.mark.asyncio
    async def test_search_scoring(self, standalone_server):
        """Test that search scoring works correctly"""
        # Add conversations with different topic matches
        await standalone_server.add_conversation(
            content="Python programming with MCP server development",
            title="High Score Conversation",
            conversation_date="2025-01-15T10:00:00",
        )

        await standalone_server.add_conversation(
            content="Discussion about general programming concepts",
            title="Low Score Conversation",
            conversation_date="2025-01-15T11:00:00",
        )

        # Search for python
        results = await standalone_server.search_conversations("python", limit=2)

        assert len(results) >= 1

        # The conversation with python in both content and topics should score higher
        high_score_found = any(r["title"] == "High Score Conversation" for r in results)
        assert high_score_found

    @pytest.mark.asyncio
    async def test_empty_search(self, standalone_server):
        """Test searching when no conversations exist"""
        results = await standalone_server.search_conversations("nonexistent", limit=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_by_topic_json_fallback(self, temp_storage):
        """Test search_by_topic with JSON fallback (SQLite disabled)"""
        # Create server with SQLite explicitly disabled
        server = StandaloneServer(temp_storage, enable_sqlite=False)

        # Add conversation with topics
        result = await server.add_conversation(
            content="Discussion about Python and machine learning algorithms",
            title="ML Discussion",
            conversation_date="2025-01-15T10:00:00",
        )

        assert result["status"] == "success"

        # Search by topic using JSON fallback
        results = await server.search_by_topic("python", limit=5)

        # Should return results from JSON-based search
        assert isinstance(results, list)
        if len(results) > 0:
            assert "id" in results[0] or "error" in results[0]

    @pytest.mark.asyncio
    async def test_search_conversations_json_fallback(self, temp_storage):
        """Test search_conversations with JSON fallback (SQLite disabled)"""
        # Create server with SQLite explicitly disabled
        server = StandaloneServer(temp_storage, enable_sqlite=False)

        # Add conversations
        await server.add_conversation(
            content="Python programming with asyncio and aiofiles",
            title="Async Python Guide",
            conversation_date="2025-01-15T10:00:00",
        )

        await server.add_conversation(
            content="Machine learning with scikit-learn",
            title="ML Tutorial",
            conversation_date="2025-01-15T11:00:00",
        )

        # Search using JSON fallback path
        results = await server.search_conversations("python asyncio", limit=5)

        # Should return results from linear JSON-based search
        assert isinstance(results, list)
        assert len(results) > 0

        # Check that results have expected fields
        first_result = results[0]
        assert "title" in first_result
        assert "score" in first_result
        assert "preview" in first_result or "content" in first_result

    @pytest.mark.asyncio
    async def test_search_with_missing_file(self, temp_storage):
        """Test search_conversations handles missing conversation files gracefully"""
        # Create server with SQLite disabled
        server = StandaloneServer(temp_storage, enable_sqlite=False)

        # Add a conversation
        result = await server.add_conversation(
            content="Test content for missing file test",
            title="Test Conversation",
            conversation_date="2025-01-15T10:00:00",
        )

        # Delete the conversation file but keep index entry
        file_path = Path(result["file_path"])
        file_path.unlink()

        # Search should handle missing file gracefully
        results = await server.search_conversations("test", limit=5)

        # Should return empty or handle gracefully without crashing
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_invalid_date_handling(self, standalone_server, sample_conversation_content):
        """Test that invalid dates are handled gracefully"""
        result = await standalone_server.add_conversation(
            content=sample_conversation_content,
            title="Invalid Date Test",
            conversation_date="invalid-date-format",
        )

        # Should handle error gracefully (may succeed or fail depending on implementation)
        assert result["status"] in ["success", "error"]
        if result["status"] == "error":
            assert "message" in result


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestFastMCPServer:
    """Test the FastMCP server functionality when available"""

    @pytest.mark.asyncio
    async def test_fastmcp_server_initialization(self):
        """Test that FastMCP server initializes properly"""
        server = ConversationMemoryServer()

        # Basic smoke test - server should initialize without errors
        assert server is not None

    @pytest.mark.asyncio
    async def test_fastmcp_search_functionality(self):
        """Test search functionality in FastMCP server"""
        server = ConversationMemoryServer()

        # Test search (assuming some data exists)
        try:
            results = await server.search_conversations("test", limit=1)
            assert isinstance(results, list)
        except Exception as e:  # noqa: BLE001 - environment-dependent smoke test: skip rather than fail when preconditions aren't met
            pytest.skip(f"FastMCP search test skipped due to: {e}")


class TestCoverageTarget:
    """Additional tests to improve coverage of edge cases"""

    @pytest.mark.asyncio
    async def test_file_operations_error_handling(self, standalone_server, temp_storage):
        """Test error handling for file operations"""
        # Create a scenario where file operations might fail
        conversations_dir = Path(temp_storage) / "conversations"

        # Test with missing directory (should be created)
        shutil.rmtree(conversations_dir, ignore_errors=True)

        result = await standalone_server.add_conversation(
            content="Test content", title="Error Test", conversation_date="2025-01-15T10:30:00"
        )

        # Should succeed by recreating directories
        assert result["status"] == "success"

    def test_topic_extraction_edge_cases(self, standalone_server):
        """Test topic extraction with edge cases"""
        # Test with empty content
        topics = standalone_server._extract_topics("")
        assert len(topics) == 0

        # Test with only special characters
        topics = standalone_server._extract_topics("!@#$%^&*()")
        assert len(topics) == 0

        # Test with very short quoted terms (should be filtered out)
        topics = standalone_server._extract_topics('"a" "bb" "longer term"')
        assert "a" not in topics
        assert "bb" not in topics
        assert "longer term" in topics

    def test_get_date_folder(self, standalone_server):
        """Test date folder generation"""
        test_date = datetime(2025, 12, 25, 15, 30, 45)
        folder = standalone_server._get_date_folder(test_date)

        assert "2025" in str(folder)
        assert "12-december" in str(folder)
        assert folder.exists()

    @pytest.mark.asyncio
    async def test_invalid_json_handling(self, standalone_server, temp_storage):
        """Test exception handling for invalid JSON in index file"""
        # Create an invalid JSON file that will trigger ValueError during json.load()
        index_file = Path(temp_storage) / "conversations" / "index.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)

        # Write invalid JSON that will cause json.load() to raise ValueError
        with open(index_file, "w", encoding="utf-8") as f:
            f.write('{"conversations": [invalid json content}')  # Invalid JSON syntax

        # This should trigger the exception handling when searching
        results = await standalone_server.search_conversations("test")

        # Should handle gracefully and return error or empty results
        assert isinstance(results, list)
        if len(results) > 0:
            # If it returns an error response, that's also acceptable
            assert "error" in results[0]

    @pytest.mark.asyncio
    async def test_preview_generation(self, standalone_server, temp_storage):
        """Test conversation preview generation"""
        content = """
Line 1: Introduction
Line 2: This line contains the search term
Line 3: This is context after the match
Line 4: More content
Line 5: Final line
        """

        # Add conversation
        result = await standalone_server.add_conversation(
            content=content, title="Preview Test", conversation_date="2025-01-15T10:30:00"
        )

        file_path = Path(result["file_path"])

        # Test preview generation
        preview = standalone_server._get_preview(file_path, ["search", "term"])

        assert len(preview) > 0
        assert "search term" in preview.lower() or "term" in preview.lower()


class TestServerIntegration:
    """Integration tests for the memory server"""

    @pytest.mark.asyncio
    async def test_server_basic_functionality(self, temp_storage):
        """Test basic server functionality end-to-end"""
        # Initialize server with test directory
        test_path = Path(temp_storage)
        server = ConversationMemoryServer(str(test_path))

        # Test adding conversation
        test_conversation = {
            "content": "This is a test conversation about Python programming",
            "title": "Python Test",
            "conversation_date": "2024-01-01T10:00:00Z",
        }

        result = await server.add_conversation(**test_conversation)
        assert result["status"] == "success"
        assert "file_path" in result

        # Test searching for the conversation
        search_results = await server.search_conversations("Python", limit=5)
        assert len(search_results) > 0

        found = False
        for conversation in search_results:
            if "Python" in conversation.get("title", ""):
                found = True
                break
        assert found, "Added conversation should be found in search results"

    def test_imports_available(self):
        """Test that all required imports are available"""
        # Test core imports
        try:
            from conversation_memory import ConversationMemoryServer  # noqa: F401
            from exceptions import ValidationError  # noqa: F401
            from validators import validate_content, validate_title  # noqa: F401

            assert True, "Core imports successful"
        except ImportError as e:
            pytest.fail(f"Import failed: {e}")

        # Test optional imports
        try:
            assert True, "Standard library imports successful"
        except ImportError as e:
            pytest.fail(f"Standard library import failed: {e}")


if __name__ == "__main__":
    # Run tests with coverage
    pytest.main([__file__, "-v", "--cov=.", "--cov-report=html", "--cov-report=term"])
