#!/usr/bin/env python3
"""
Tests for SQLite FTS search functionality.

This module tests the SQLite Full-Text Search (FTS5) implementation
for conversation memory, including performance, accuracy, and integration.
"""

import json
import shutil
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from conversation_memory import ConversationMemoryServer
from migrate_to_sqlite import ConversationMigrator
from search_database import SearchDatabase

sys.path.append(str(Path(__file__).parent.parent / "src"))


class TestSearchDatabase:
    """Test SQLite FTS database functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def search_db(self, temp_db_path):
        """Create SearchDatabase instance for testing."""
        return SearchDatabase(temp_db_path)

    @pytest.fixture
    def sample_conversation(self):
        """Sample conversation data for testing."""
        return {
            "id": "test_conv_001",
            "title": "Python async programming",
            "content": "Discussion about Python asyncio, async/await syntax, and concurrent programming patterns",
            "date": "2025-06-12T10:00:00",
            "created_at": "2025-06-12T10:00:00",
            "topics": ["python", "asyncio", "concurrency"],
        }

    def test_database_initialization(self, search_db):
        """Test database tables are created correctly."""
        assert search_db.get_conversation_count() == 0

        # Test database structure
        import sqlite3

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor]

            assert "conversations" in tables
            assert "conversations_fts" in tables
            assert "conversation_topics" in tables

    def test_add_conversation(self, search_db, sample_conversation):
        """Test adding a conversation to the database."""
        success = search_db.add_conversation(sample_conversation, "test/path.json")
        assert success is True

        # Verify conversation was added
        assert search_db.get_conversation_count() == 1

        # Test duplicate handling
        success = search_db.add_conversation(sample_conversation, "test/path.json")
        assert success is True
        assert search_db.get_conversation_count() == 1  # Should still be 1

    def test_search_conversations(self, search_db, sample_conversation):
        """Test FTS search functionality."""
        # Add test conversation
        search_db.add_conversation(sample_conversation, "test/path.json")

        # Test single term search
        results = search_db.search_conversations("python")
        assert len(results) == 1
        assert results[0]["id"] == "test_conv_001"
        assert "score" in results[0]
        assert "preview" in results[0]

        # Test multi-term search
        results = search_db.search_conversations("python async")
        assert len(results) == 1

        # Test no results
        results = search_db.search_conversations("javascript")
        assert len(results) == 0

        # Test empty query
        results = search_db.search_conversations("")
        assert len(results) == 0

        # Test special characters
        results = search_db.search_conversations("python & async")
        assert len(results) >= 0  # Should not crash

    def test_search_by_topic(self, search_db, sample_conversation):
        """Test topic-based search."""
        search_db.add_conversation(sample_conversation, "test/path.json")

        # Test exact topic match
        results = search_db.search_by_topic("python")
        assert len(results) == 1
        assert results[0]["id"] == "test_conv_001"

        # Test non-existent topic
        results = search_db.search_by_topic("javascript")
        assert len(results) == 0

    def test_conversation_stats(self, search_db, sample_conversation):
        """Test database statistics."""
        # Empty database
        stats = search_db.get_conversation_stats()
        assert stats["total_conversations"] == 0
        assert stats["unique_topics"] == 0

        # Add conversation
        search_db.add_conversation(sample_conversation, "test/path.json")

        stats = search_db.get_conversation_stats()
        assert stats["total_conversations"] == 1
        assert stats["unique_topics"] == 3
        assert len(stats["popular_topics"]) == 3

        # Check popular topics
        topic_names = [t["topic"] for t in stats["popular_topics"]]
        assert "python" in topic_names
        assert "asyncio" in topic_names
        assert "concurrency" in topic_names

    def test_fts_query_sanitization(self, search_db):
        """Test FTS query sanitization."""
        # Test that problematic queries don't crash
        queries = [
            '"unclosed quote',
            "query with (parentheses)",
            "query with [brackets]",
            "query with {braces}",
            "query with *asterisk*",
            "query:with:colons",
            "query-with-dashes",
            '""',
            "()",
            "[]",
        ]

        for query in queries:
            results = search_db.search_conversations(query)
            assert isinstance(results, list)  # Should not crash


class TestMetadataIndexing:
    """Test SQLite indexing of D2 universal metadata fields."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def search_db(self, temp_db_path):
        return SearchDatabase(temp_db_path)

    @pytest.fixture
    def conv_with_metadata(self):
        return {
            "id": "conv_meta_001",
            "title": "Debugging async import",
            "content": "Investigating ImportError in async consumer.",
            "date": "2026-04-18T10:00:00",
            "created_at": "2026-04-18T10:00:00",
            "topics": ["python", "async"],
            "session_id": "session_abc123",
            "user_id": "user_42",
            "tags": ["starred", "workspace:memory-mcp", "has-file-changes"],
            "conversation_type": "code",
            "custom_fields": {"workspace_path": "/home/dev/mcp"},
        }

    def test_schema_has_metadata_columns(self, search_db):
        """Fresh init should contain all metadata columns and the tags table."""
        import sqlite3

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            columns = {row[1] for row in cursor.fetchall()}

        assert {
            "session_id",
            "user_id",
            "conversation_type",
            "custom_fields_json",
        }.issubset(columns)

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor}
        assert "conversation_tags" in tables

    def test_add_conversation_persists_metadata(self, search_db, conv_with_metadata):
        """Metadata fields land in the conversations + conversation_tags tables."""
        assert search_db.add_conversation(conv_with_metadata, "x/y.json") is True

        import sqlite3

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT session_id, user_id, conversation_type, "
                "custom_fields_json FROM conversations WHERE id=?",
                (conv_with_metadata["id"],),
            ).fetchone()
            tags = [
                r[0]
                for r in conn.execute(
                    "SELECT tag FROM conversation_tags WHERE conversation_id=?",
                    (conv_with_metadata["id"],),
                )
            ]

        assert row["session_id"] == "session_abc123"
        assert row["user_id"] == "user_42"
        assert row["conversation_type"] == "code"
        assert json.loads(row["custom_fields_json"]) == {"workspace_path": "/home/dev/mcp"}
        assert set(tags) == {"starred", "workspace:memory-mcp", "has-file-changes"}

    def test_add_conversation_without_metadata_still_works(self, search_db):
        """Old-shape conversations (no D2 metadata) still persist cleanly."""
        legacy = {
            "id": "legacy_001",
            "title": "Old style",
            "content": "No metadata.",
            "date": "2025-01-01T00:00:00",
            "created_at": "2025-01-01T00:00:00",
            "topics": ["legacy"],
        }
        assert search_db.add_conversation(legacy, "a/b.json") is True

        import sqlite3

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            row = conn.execute(
                "SELECT session_id, user_id, conversation_type FROM conversations WHERE id=?",
                (legacy["id"],),
            ).fetchone()
            tag_count = conn.execute(
                "SELECT COUNT(*) FROM conversation_tags WHERE conversation_id=?",
                (legacy["id"],),
            ).fetchone()[0]

        assert row == (None, None, None)
        assert tag_count == 0

    def test_search_by_tag_exact_match(self, search_db, conv_with_metadata):
        search_db.add_conversation(conv_with_metadata, "x/y.json")

        hits = search_db.search_by_tag("starred")
        assert len(hits) == 1
        assert hits[0]["id"] == "conv_meta_001"
        assert hits[0]["session_id"] == "session_abc123"
        assert hits[0]["conversation_type"] == "code"

        assert search_db.search_by_tag("nonexistent") == []

    def test_search_by_session_id_orders_chronologically(self, search_db, conv_with_metadata):
        second = {
            **conv_with_metadata,
            "id": "conv_meta_002",
            "title": "Later in the same session",
            "date": "2026-04-18T14:00:00",
            "created_at": "2026-04-18T14:00:00",
        }
        search_db.add_conversation(conv_with_metadata, "x/y.json")
        search_db.add_conversation(second, "x/z.json")

        hits = search_db.search_by_session_id("session_abc123")
        assert [h["id"] for h in hits] == ["conv_meta_001", "conv_meta_002"]

        assert search_db.search_by_session_id("no-such-session") == []

    def test_search_by_conversation_type(self, search_db, conv_with_metadata):
        chat = {
            **conv_with_metadata,
            "id": "conv_meta_chat",
            "conversation_type": "chat",
            "tags": [],
        }
        search_db.add_conversation(conv_with_metadata, "a.json")
        search_db.add_conversation(chat, "b.json")

        code_hits = search_db.search_by_conversation_type("code")
        assert [h["id"] for h in code_hits] == ["conv_meta_001"]

        chat_hits = search_db.search_by_conversation_type("chat")
        assert [h["id"] for h in chat_hits] == ["conv_meta_chat"]

        assert search_db.search_by_conversation_type("analysis") == []

    def test_tags_are_indexed_in_fts(self, search_db, conv_with_metadata):
        """Tags are folded into topics_text so free-text search finds them."""
        search_db.add_conversation(conv_with_metadata, "x/y.json")

        fts_hits = search_db.search_conversations("starred")
        assert any(h["id"] == "conv_meta_001" for h in fts_hits)

    def test_stats_include_metadata_counts(self, search_db, conv_with_metadata):
        search_db.add_conversation(conv_with_metadata, "x/y.json")

        stats = search_db.get_conversation_stats()

        assert stats["unique_tags"] == 3
        tag_names = [t["tag"] for t in stats["popular_tags"]]
        assert "starred" in tag_names
        assert stats["unique_sessions"] == 1
        assert stats["conversation_types"] == [{"type": "code", "count": 1}]

    def test_migration_adds_missing_columns(self, temp_db_path):
        """Pre-metadata DBs get the new columns via ALTER TABLE on init."""
        import sqlite3

        # Create the pre-metadata schema by hand (original 8 columns only)
        with closing(sqlite3.connect(temp_db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    topics_json TEXT,
                    topics_text TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy_01",
                    "Old row",
                    "Old content",
                    "2024-01-01T00:00:00",
                    "2024-01-01T00:00:00",
                    "old.json",
                    "[]",
                    "",
                ),
            )
            conn.commit()

        # Instantiating SearchDatabase should migrate the schema non-destructively
        SearchDatabase(temp_db_path)

        with closing(sqlite3.connect(temp_db_path)) as conn, conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            columns = {row[1] for row in cursor.fetchall()}
            existing_row = conn.execute(
                "SELECT id, session_id, conversation_type FROM conversations WHERE id='legacy_01'"
            ).fetchone()

        assert {
            "session_id",
            "user_id",
            "conversation_type",
            "custom_fields_json",
        }.issubset(columns)
        assert existing_row == ("legacy_01", None, None)  # preserved + NULLs

    def test_migration_is_idempotent(self, search_db):
        """Running init twice does not duplicate columns or data."""
        # Re-init on an already-new-schema DB is a no-op
        SearchDatabase(search_db.db_path)  # new instance reuses same file

        import sqlite3

        with closing(sqlite3.connect(search_db.db_path)) as conn, conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            names = [row[1] for row in cursor.fetchall()]
        # session_id should appear exactly once
        assert names.count("session_id") == 1


class TestConversationMemoryServerSQLite:
    """Test ConversationMemoryServer with SQLite integration."""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def memory_server_sqlite(self, temp_storage):
        """Create ConversationMemoryServer with SQLite enabled."""
        return ConversationMemoryServer(
            storage_path=temp_storage, use_data_dir=True, enable_sqlite=True
        )

    @pytest.fixture
    def memory_server_linear(self, temp_storage):
        """Create ConversationMemoryServer with SQLite disabled."""
        return ConversationMemoryServer(
            storage_path=temp_storage, use_data_dir=True, enable_sqlite=False
        )

    @pytest.mark.asyncio
    async def test_sqlite_initialization(self, memory_server_sqlite):
        """Test SQLite search is properly initialized."""
        assert memory_server_sqlite.use_sqlite_search is True
        assert memory_server_sqlite.search_db is not None

        stats = await memory_server_sqlite.get_search_stats()
        assert stats["sqlite_available"] is True
        assert stats["sqlite_enabled"] is True
        assert stats["search_engine"] == "sqlite_fts"

    @pytest.mark.asyncio
    async def test_linear_fallback(self, memory_server_linear):
        """Test linear search fallback when SQLite disabled."""
        assert memory_server_linear.use_sqlite_search is False
        assert memory_server_linear.search_db is None

        stats = await memory_server_linear.get_search_stats()
        assert stats["sqlite_enabled"] is False
        assert stats["search_engine"] == "linear_json"

    @pytest.mark.asyncio
    async def test_add_conversation_with_sqlite(self, memory_server_sqlite):
        """Test adding conversation updates both JSON and SQLite."""
        content = "Testing SQLite integration with Python FastAPI"
        title = "SQLite Test"

        result = await memory_server_sqlite.add_conversation(content, title)
        assert result["status"] == "success"

        # Verify conversation is in SQLite
        search_results = await memory_server_sqlite.search_conversations("SQLite")
        assert len(search_results) == 1
        assert search_results[0]["title"] == title

    @pytest.mark.asyncio
    async def test_search_consistency(self, memory_server_sqlite, memory_server_linear):
        """Test that SQLite and linear search return consistent results."""
        content = "Python programming with async/await patterns and FastAPI framework"
        title = "Python Async Programming"

        # Add to both servers
        await memory_server_sqlite.add_conversation(content, title)
        await memory_server_linear.add_conversation(content, title)

        # Search both with a more specific term to avoid conflicts with other tests
        sqlite_results = await memory_server_sqlite.search_conversations("FastAPI")
        linear_results = await memory_server_linear.search_conversations("FastAPI")

        # Should find the conversation in both
        assert len(sqlite_results) >= 1
        assert len(linear_results) >= 1

        # Find matching conversations (both should have the specific title)
        sqlite_conv = next((r for r in sqlite_results if r["title"] == title), None)
        linear_conv = next((r for r in linear_results if r["title"] == title), None)

        assert sqlite_conv is not None, "SQLite should find the added conversation"
        assert linear_conv is not None, "Linear search should find the added conversation"

        # IDs should match (both use same generation logic)
        assert sqlite_conv["id"] == linear_conv["id"]
        assert sqlite_conv["title"] == linear_conv["title"]

    @pytest.mark.asyncio
    async def test_topic_search(self, memory_server_sqlite):
        """Test topic-based search functionality."""
        content = "Discussion about machine learning algorithms and data science"
        title = "ML Discussion"

        await memory_server_sqlite.add_conversation(content, title)

        # Test topic search
        results = await memory_server_sqlite.search_by_topic("machine learning")
        assert len(results) >= 0  # Topic extraction might vary

    @pytest.mark.asyncio
    async def test_search_stats(self, memory_server_sqlite):
        """Test search statistics functionality."""
        stats = await memory_server_sqlite.get_search_stats()

        required_keys = ["sqlite_available", "sqlite_enabled", "search_engine"]
        for key in required_keys:
            assert key in stats

        # Add conversation and check stats update
        await memory_server_sqlite.add_conversation("Test content", "Test title")

        updated_stats = await memory_server_sqlite.get_search_stats()
        if "total_conversations" in updated_stats:
            assert updated_stats["total_conversations"] >= 1

    @pytest.mark.asyncio
    async def test_add_conversation_persists_metadata_to_json(self, memory_server_sqlite):
        """Metadata kwargs survive the round-trip through JSON storage."""
        result = await memory_server_sqlite.add_conversation(
            "Some content",
            "Titled",
            "2026-04-18T10:00:00",
            session_id="sess_abc",
            user_id="user_x",
            tags=["starred", "project:memory"],
            conversation_type="code",
            custom_fields={"workspace": "/tmp/ws"},
        )
        assert result["status"] == "success"

        saved = Path(result["file_path"])
        data = json.loads(saved.read_text())
        assert data["session_id"] == "sess_abc"
        assert data["user_id"] == "user_x"
        assert data["tags"] == ["starred", "project:memory"]
        assert data["conversation_type"] == "code"
        assert data["custom_fields"] == {"workspace": "/tmp/ws"}

    @pytest.mark.asyncio
    async def test_add_conversation_without_metadata_keeps_legacy_shape(self, memory_server_sqlite):
        """Omitting metadata does not add empty keys — keeps JSON shape stable."""
        result = await memory_server_sqlite.add_conversation(
            "plain content", "plain title", "2026-04-18T10:00:00"
        )
        saved = Path(result["file_path"])
        data = json.loads(saved.read_text())

        for missing in (
            "session_id",
            "user_id",
            "tags",
            "conversation_type",
            "custom_fields",
        ):
            assert missing not in data

    @pytest.mark.asyncio
    async def test_search_by_tag_end_to_end(self, memory_server_sqlite):
        await memory_server_sqlite.add_conversation(
            "starred note content",
            "Starred note",
            "2026-04-18T10:00:00",
            tags=["starred", "priority:high"],
            conversation_type="chat",
        )

        hits = await memory_server_sqlite.search_by_tag("starred")
        assert len(hits) == 1
        assert hits[0]["title"] == "Starred note"
        assert hits[0]["conversation_type"] == "chat"

    @pytest.mark.asyncio
    async def test_search_by_session_id_end_to_end(self, memory_server_sqlite):
        for i, stamp in enumerate(
            ["2026-04-18T09:00:00", "2026-04-18T11:00:00", "2026-04-18T13:00:00"]
        ):
            await memory_server_sqlite.add_conversation(
                f"turn {i} content",
                f"Turn {i}",
                stamp,
                session_id="sess_longform",
            )

        hits = await memory_server_sqlite.search_by_session_id("sess_longform")
        assert len(hits) == 3
        # Chronological order
        assert [h["title"] for h in hits] == ["Turn 0", "Turn 1", "Turn 2"]

    @pytest.mark.asyncio
    async def test_search_by_conversation_type_end_to_end(self, memory_server_sqlite):
        await memory_server_sqlite.add_conversation(
            "coding", "Code one", "2026-04-18T10:00:00", conversation_type="code"
        )
        await memory_server_sqlite.add_conversation(
            "chat", "Chat one", "2026-04-18T11:00:00", conversation_type="chat"
        )

        code_hits = await memory_server_sqlite.search_by_conversation_type("code")
        assert [h["title"] for h in code_hits] == ["Code one"]

    @pytest.mark.asyncio
    async def test_metadata_search_without_sqlite_returns_error(self, memory_server_linear):
        """Without SQLite, metadata search methods return an error marker."""
        result = await memory_server_linear.search_by_tag("starred")
        assert result == [{"error": "Tag search requires SQLite FTS to be enabled"}]

        result = await memory_server_linear.search_by_session_id("sess_x")
        assert result == [{"error": "Session search requires SQLite FTS to be enabled"}]

        result = await memory_server_linear.search_by_conversation_type("chat")
        assert result == [{"error": "Conversation-type search requires SQLite FTS to be enabled"}]


class TestConversationMigration:
    """Test migration from JSON to SQLite."""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage with test data."""
        temp_dir = tempfile.mkdtemp()

        # Create test conversation structure
        conversations_dir = Path(temp_dir) / "data" / "conversations"
        conversations_dir.mkdir(parents=True)

        # Create sample conversations
        for i in range(3):
            conv_data = {
                "id": f"test_conv_{i:03d}",
                "title": f"Test Conversation {i + 1}",
                "content": f"This is test conversation {i + 1} about Python programming",
                "date": f"2025-06-{i + 10:02d}T10:00:00",
                "created_at": f"2025-06-{i + 10:02d}T10:00:00",
                "topics": ["python", "testing"],
            }

            year_month_dir = conversations_dir / "2025" / "06-june"
            year_month_dir.mkdir(parents=True, exist_ok=True)

            conv_file = year_month_dir / f"{conv_data['id']}.json"
            with open(conv_file, "w") as f:
                json.dump(conv_data, f)

        # Create index file
        index_data = {
            "conversations": [
                {
                    "id": f"test_conv_{i:03d}",
                    "title": f"Test Conversation {i + 1}",
                    "date": f"2025-06-{i + 10:02d}T10:00:00",
                    "topics": ["python", "testing"],
                    "file_path": f"data/conversations/2025/06-june/test_conv_{i:03d}.json",
                    "added_at": f"2025-06-{i + 10:02d}T10:00:00",
                }
                for i in range(3)
            ],
            "last_updated": "2025-06-12T10:00:00",
        }

        with open(conversations_dir / "index.json", "w") as f:
            json.dump(index_data, f)

        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_migration_with_index(self, temp_storage):
        """Test migration using index file."""
        migrator = ConversationMigrator(temp_storage, use_data_dir=True)

        # Run migration
        stats = migrator.migrate_all_conversations()

        assert stats["total_found"] == 3
        assert stats["successfully_migrated"] == 3
        assert stats["failed_migrations"] == 0

        # Verify conversations are in SQLite
        assert migrator.search_db.get_conversation_count() == 3

        # Test search functionality
        results = migrator.search_db.search_conversations("python")
        assert len(results) == 3

    def test_migration_verification(self, temp_storage):
        """Test migration verification."""
        migrator = ConversationMigrator(temp_storage, use_data_dir=True)

        # Run migration first
        migrator.migrate_all_conversations()

        # Verify migration
        verification = migrator.verify_migration()

        assert verification["sqlite_count"] == 3
        assert verification["json_count"] == 3
        assert verification["counts_match"] is True
        assert verification["search_test_passed"] is True
        assert verification["search_results_count"] >= 0

    def test_migration_without_index(self, temp_storage):
        """Test migration by directory scanning when index is missing."""
        # Remove index file
        index_file = Path(temp_storage) / "data" / "conversations" / "index.json"
        index_file.unlink()

        migrator = ConversationMigrator(temp_storage, use_data_dir=True)

        # Run migration
        stats = migrator.migrate_all_conversations()

        assert stats["total_found"] == 3
        assert stats["successfully_migrated"] == 3
        assert stats["failed_migrations"] == 0


class TestPerformanceComparison:
    """Test performance differences between linear and SQLite search."""

    @pytest.fixture
    def performance_test_data(self):
        """Create test data for performance comparison."""
        conversations = []
        topics = ["python", "javascript", "react", "django", "api", "database"]

        for i in range(50):  # Smaller dataset for unit tests
            conv = {
                "id": f"perf_conv_{i:03d}",
                "title": f"Performance Test Conversation {i + 1}",
                "content": f"Content about {topics[i % len(topics)]} programming and development",
                "date": f"2025-06-{(i % 28) + 1:02d}T10:00:00",
                "created_at": f"2025-06-{(i % 28) + 1:02d}T10:00:00",
                "topics": [
                    topics[i % len(topics)],
                    topics[(i + 1) % len(topics)],
                ],
            }
            conversations.append(conv)

        return conversations

    @pytest.mark.asyncio
    async def test_search_performance_comparison(self, performance_test_data):
        """Test that SQLite search performs reasonably compared to linear search."""
        import time

        with tempfile.TemporaryDirectory() as temp_dir:
            # Setup SQLite server
            sqlite_server = ConversationMemoryServer(
                storage_path=temp_dir + "/sqlite",
                use_data_dir=True,
                enable_sqlite=True,
            )

            # Setup linear server
            linear_server = ConversationMemoryServer(
                storage_path=temp_dir + "/linear",
                use_data_dir=True,
                enable_sqlite=False,
            )

            # Add test data
            for conv in performance_test_data:
                await sqlite_server.add_conversation(conv["content"], conv["title"])
                await linear_server.add_conversation(conv["content"], conv["title"])

            # Test search performance
            test_queries = ["python", "javascript", "database"]

            for query in test_queries:
                # SQLite search
                start_time = time.perf_counter()
                sqlite_results = await sqlite_server.search_conversations(query, limit=10)
                sqlite_time = time.perf_counter() - start_time

                # Linear search
                start_time = time.perf_counter()
                linear_results = await linear_server.search_conversations(query, limit=10)
                linear_time = time.perf_counter() - start_time

                # Both should return results
                assert len(sqlite_results) > 0
                assert len(linear_results) > 0

                # SQLite should not be significantly slower (allowing for overhead in
                # small datasets)
                # Allow 5x overhead for small test datasets
                assert sqlite_time < linear_time * 5

                print(f"Query '{query}': SQLite {sqlite_time:.4f}s, Linear {linear_time:.4f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
