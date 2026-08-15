#!/usr/bin/env python3
"""
SQLite FTS-based search database for conversation memory.

This module provides optimized search functionality using SQLite's FTS5
extension for full-text search, replacing the linear search approach.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar


class SearchDatabase:
    """SQLite FTS5-based search database for conversations."""

    def __init__(self, db_path: str):
        """Initialize the search database."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

        # Initialize database
        self._init_database()

    @contextmanager
    def _connect(self):
        """Open a connection, manage its transaction, and always close it.

        ``with sqlite3.connect(...) as conn`` manages the *transaction* -- it
        commits on success and rolls back on exception -- and does **not**
        close the connection. Every call site here used that form, so each
        operation left a live handle waiting on the garbage collector.
        Measured before this helper: one leaked handle per operation (1 after
        __init__, 6 after five adds, 11 after five searches, 0 only after an
        explicit ``gc.collect()``).

        Invisible on Linux, which lets you unlink a file that is still open.
        On Windows the open handle makes the database file undeletable, which
        is what produced ~40 teardown errors when the suite first ran there.
        A long-lived server also has no guarantee about when GC runs.

        ``with conn`` inside keeps the existing transaction semantics
        unchanged; the ``finally`` is the only new behaviour.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # Metadata columns added by PR adding FTS indexing of D2 universal fields.
    # Column name -> SQL type. All default to NULL (nullable) for backwards
    # compat with conversations imported before the metadata fields existed.
    _METADATA_COLUMNS: ClassVar[dict[str, str]] = {
        "session_id": "TEXT",
        "user_id": "TEXT",
        "conversation_type": "TEXT",
        "custom_fields_json": "TEXT",
    }

    def _init_database(self):
        """Initialize SQLite database with FTS5 tables."""
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                # Create main conversations table. New installs get the full
                # schema up front; existing installs are migrated next so
                # later ``CREATE INDEX`` on metadata columns doesn't fail.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        date TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        topics_json TEXT,
                        topics_text TEXT,
                        session_id TEXT,
                        user_id TEXT,
                        conversation_type TEXT,
                        custom_fields_json TEXT
                    )
                """)

                # Migrate existing pre-metadata databases before creating
                # any indexes that reference the new columns.
                self._migrate_metadata_columns(conn)

                # Create FTS5 virtual table for full-text search. Tags are
                # folded into ``topics_text`` when rows are written, so the
                # FTS schema itself does not need new columns — keeping the
                # virtual-table schema stable across migrations.
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                        id,
                        title,
                        content,
                        topics_text,
                        content='conversations',
                        content_rowid='rowid'
                    )
                """)

                # Create topics table for topic-based searches
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_topics (
                        conversation_id TEXT,
                        topic TEXT,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                        PRIMARY KEY (conversation_id, topic)
                    )
                """)

                # Create tags table for precise tag-based searches (analogous
                # to conversation_topics, but for the D2 ``tags`` field).
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_tags (
                        conversation_id TEXT,
                        tag TEXT,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                        PRIMARY KEY (conversation_id, tag)
                    )
                """)

                # Create indexes for performance
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_date ON conversations(date)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_topics_topic ON conversation_topics(topic)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON conversation_tags(tag)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_session_id "
                    "ON conversations(session_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_type "
                    "ON conversations(conversation_type)"
                )

                # Create triggers to maintain the FTS5 table.
                #
                # ``conversations_fts`` is an EXTERNAL CONTENT table
                # (``content='conversations'``), so it stores only the index
                # and reads column values back from ``conversations`` by
                # rowid. That makes rowid alignment the whole contract:
                # entries must be written with an explicit ``rowid`` and
                # removed with the ``'delete'`` command carrying the ORIGINAL
                # column values. Ordinary INSERT/DELETE/UPDATE statements
                # against the virtual table silently desync the index, and a
                # later MATCH that hits an orphaned entry fails the read-back
                # with "database disk image is malformed".
                #
                # These are dropped and recreated unconditionally so databases
                # carrying the earlier (non-external-content) trigger bodies
                # are migrated in place.
                conn.execute("DROP TRIGGER IF EXISTS conversations_ai")
                conn.execute("DROP TRIGGER IF EXISTS conversations_ad")
                conn.execute("DROP TRIGGER IF EXISTS conversations_au")

                conn.execute("""
                    CREATE TRIGGER conversations_ai
                    AFTER INSERT ON conversations BEGIN
                        INSERT INTO conversations_fts(
                            rowid, id, title, content, topics_text)
                        VALUES (new.rowid, new.id, new.title, new.content,
                                new.topics_text);
                    END
                """)

                conn.execute("""
                    CREATE TRIGGER conversations_ad
                    AFTER DELETE ON conversations BEGIN
                        INSERT INTO conversations_fts(
                            conversations_fts, rowid, id, title, content, topics_text)
                        VALUES ('delete', old.rowid, old.id, old.title, old.content,
                                old.topics_text);
                    END
                """)

                conn.execute("""
                    CREATE TRIGGER conversations_au
                    AFTER UPDATE ON conversations BEGIN
                        INSERT INTO conversations_fts(
                            conversations_fts, rowid, id, title, content, topics_text)
                        VALUES ('delete', old.rowid, old.id, old.title, old.content,
                                old.topics_text);
                        INSERT INTO conversations_fts(
                            rowid, id, title, content, topics_text)
                        VALUES (new.rowid, new.id, new.title, new.content,
                                new.topics_text);
                    END
                """)

                conn.commit()

                # Heal databases that already desynced under the old triggers.
                self._repair_fts_desync(conn)

        except sqlite3.Error as e:
            self.logger.exception(f"Database initialization failed: {e}")
            raise

    def _repair_fts_desync(self, conn: sqlite3.Connection) -> None:
        """Rebuild the FTS index if it holds more documents than the table.

        Databases written under the pre-external-content triggers leaked one
        orphaned index entry per re-saved conversation. Those orphans are
        invisible until a MATCH happens to hit one, at which point the
        read-back against ``conversations`` fails the whole query with
        "database disk image is malformed" — so every search breaks at once
        while tag and topic lookups keep working.

        Comparing indexed-document count against row count is cheap enough to
        run at init; the rebuild only fires when they actually disagree.
        """
        try:
            rows = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            docs = conn.execute("SELECT COUNT(*) FROM conversations_fts_docsize").fetchone()[0]
        except sqlite3.Error:
            # ``columnsize=0`` builds have no docsize shadow table. Nothing to
            # compare against, so leave the index alone.
            return

        if docs == rows:
            return

        self.logger.warning(
            "FTS index desynced (%d indexed documents vs %d rows); rebuilding",
            docs,
            rows,
        )
        conn.execute("INSERT INTO conversations_fts(conversations_fts) VALUES('rebuild')")
        conn.commit()

    def _migrate_metadata_columns(self, conn: sqlite3.Connection) -> None:
        """Add metadata columns to pre-existing ``conversations`` tables.

        Pre-metadata databases (created before the FTS-metadata indexing PR)
        are missing ``session_id``/``user_id``/``conversation_type``/
        ``custom_fields_json``. ``ALTER TABLE ADD COLUMN`` is used rather
        than rebuilding because the FTS5 virtual table would need a full
        rebuild too, and these scalar columns are not in the FTS schema.
        """
        cursor = conn.execute("PRAGMA table_info(conversations)")
        existing = {row[1] for row in cursor.fetchall()}

        for column_name, column_type in self._METADATA_COLUMNS.items():
            if column_name in existing:
                continue
            conn.execute(f"ALTER TABLE conversations ADD COLUMN {column_name} {column_type}")
            self.logger.info(
                "Migrated conversations table: added column %s %s",
                column_name,
                column_type,
            )

    def add_conversation(self, conversation_data: dict[str, Any], file_path: str) -> bool:
        """Add a conversation to the search database."""
        try:
            topics = conversation_data.get("topics", []) or []
            tags = conversation_data.get("tags", []) or []
            topics_json = json.dumps(topics)

            # Fold tags into topics_text so the existing FTS5 schema picks
            # them up without needing a virtual-table rebuild. Precise
            # tag-only lookups use the conversation_tags table below.
            topics_text = " ".join(topics + tags)

            custom_fields = conversation_data.get("custom_fields") or {}
            custom_fields_json = json.dumps(custom_fields) if custom_fields else None

            with self._connect() as conn:
                # Upsert rather than INSERT OR REPLACE: REPLACE deletes and
                # re-inserts the row, which assigns a NEW rowid and (with
                # recursive_triggers off, the default) skips the AFTER DELETE
                # trigger entirely. Both halves break the external-content
                # FTS5 contract — the old index entry is orphaned and the new
                # one lands under a rowid the content table no longer uses.
                # ON CONFLICT keeps the rowid stable and fires AFTER UPDATE.
                conn.execute(
                    """
                    INSERT INTO conversations
                    (id, title, content, date, created_at, file_path,
                     topics_json, topics_text, session_id, user_id,
                     conversation_type, custom_fields_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        content = excluded.content,
                        date = excluded.date,
                        created_at = excluded.created_at,
                        file_path = excluded.file_path,
                        topics_json = excluded.topics_json,
                        topics_text = excluded.topics_text,
                        session_id = excluded.session_id,
                        user_id = excluded.user_id,
                        conversation_type = excluded.conversation_type,
                        custom_fields_json = excluded.custom_fields_json
                """,
                    (
                        conversation_data["id"],
                        conversation_data["title"],
                        conversation_data["content"],
                        conversation_data["date"],
                        conversation_data["created_at"],
                        file_path,
                        topics_json,
                        topics_text,
                        conversation_data.get("session_id"),
                        conversation_data.get("user_id"),
                        conversation_data.get("conversation_type"),
                        custom_fields_json,
                    ),
                )

                # Insert topics
                conn.execute(
                    "DELETE FROM conversation_topics WHERE conversation_id = ?",
                    (conversation_data["id"],),
                )

                for topic in topics:
                    conn.execute(
                        """
                        INSERT INTO conversation_topics (conversation_id, topic)
                        VALUES (?, ?)
                    """,
                        (conversation_data["id"], topic),
                    )

                # Insert tags
                conn.execute(
                    "DELETE FROM conversation_tags WHERE conversation_id = ?",
                    (conversation_data["id"],),
                )

                for tag in tags:
                    if not tag:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO conversation_tags (conversation_id, tag)
                        VALUES (?, ?)
                    """,
                        (conversation_data["id"], tag),
                    )

                conn.commit()
                return True

        except sqlite3.Error as e:
            self.logger.exception("Failed to add conversation: %s", e)
            return False

    def search_conversations(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations using FTS5."""
        try:
            # Sanitize query for FTS5
            query_cleaned = self._sanitize_fts_query(query)

            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                # Use FTS5 MATCH for full-text search
                cursor = conn.execute(
                    """
                    SELECT c.id, c.title, c.date, c.topics_json, c.file_path,
                           bm25(conversations_fts) as score,
                           snippet(conversations_fts, 2, '<mark>', '</mark>', '...', 32) as preview
                    FROM conversations_fts
                    JOIN conversations c ON conversations_fts.id = c.id
                    WHERE conversations_fts MATCH ?
                    ORDER BY bm25(conversations_fts)
                    LIMIT ?
                """,
                    (query_cleaned, limit),
                )

                results = []
                for row in cursor:
                    result = {
                        "id": row["id"],
                        "title": row["title"],
                        "date": row["date"],
                        "topics": (json.loads(row["topics_json"]) if row["topics_json"] else []),
                        "score": float(row["score"]),
                        "preview": row["preview"],
                        "file_path": row["file_path"],
                    }
                    results.append(result)

                return results

        except sqlite3.Error as e:
            self.logger.exception(f"Search failed: {e}")
            return [{"error": f"Search failed: {str(e)}"}]

    def search_by_topic(self, topic: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by specific topic."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute(
                    """
                    SELECT c.id, c.title, c.date, c.topics_json, c.file_path
                    FROM conversations c
                    JOIN conversation_topics ct ON c.id = ct.conversation_id
                    WHERE ct.topic = ?
                    ORDER BY c.date DESC
                    LIMIT ?
                """,
                    (topic, limit),
                )

                results = []
                for row in cursor:
                    result = {
                        "id": row["id"],
                        "title": row["title"],
                        "date": row["date"],
                        "topics": (json.loads(row["topics_json"]) if row["topics_json"] else []),
                        "file_path": row["file_path"],
                    }
                    results.append(result)

                return results

        except sqlite3.Error as e:
            self.logger.exception(f"Topic search failed: {e}")
            return []

    def search_by_tag(self, tag: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by a specific tag (exact match, case-sensitive)."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute(
                    """
                    SELECT c.id, c.title, c.date, c.topics_json, c.file_path,
                           c.session_id, c.conversation_type
                    FROM conversations c
                    JOIN conversation_tags ct ON c.id = ct.conversation_id
                    WHERE ct.tag = ?
                    ORDER BY c.date DESC
                    LIMIT ?
                """,
                    (tag, limit),
                )

                return [self._row_to_metadata_result(row) for row in cursor]

        except sqlite3.Error as e:
            self.logger.exception(f"Tag search failed: {e}")
            return []

    def search_by_session_id(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by session_id (exact match)."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute(
                    """
                    SELECT id, title, date, topics_json, file_path,
                           session_id, conversation_type
                    FROM conversations
                    WHERE session_id = ?
                    ORDER BY date ASC
                    LIMIT ?
                """,
                    (session_id, limit),
                )

                return [self._row_to_metadata_result(row) for row in cursor]

        except sqlite3.Error as e:
            self.logger.exception(f"Session search failed: {e}")
            return []

    def search_by_conversation_type(
        self, conversation_type: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search conversations by conversation_type (exact match)."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute(
                    """
                    SELECT id, title, date, topics_json, file_path,
                           session_id, conversation_type
                    FROM conversations
                    WHERE conversation_type = ?
                    ORDER BY date DESC
                    LIMIT ?
                """,
                    (conversation_type, limit),
                )

                return [self._row_to_metadata_result(row) for row in cursor]

        except sqlite3.Error as e:
            self.logger.exception(f"Conversation-type search failed: {e}")
            return []

    @staticmethod
    def _row_to_metadata_result(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a metadata-query row into the standard result dict."""
        return {
            "id": row["id"],
            "title": row["title"],
            "date": row["date"],
            "topics": json.loads(row["topics_json"]) if row["topics_json"] else [],
            "file_path": row["file_path"],
            "session_id": row["session_id"],
            "conversation_type": row["conversation_type"],
        }

    def get_conversation_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM conversations")
                total_conversations = cursor.fetchone()[0]

                cursor = conn.execute("SELECT COUNT(DISTINCT topic) FROM conversation_topics")
                unique_topics = cursor.fetchone()[0]

                cursor = conn.execute("""
                    SELECT topic, COUNT(*) as count
                    FROM conversation_topics
                    GROUP BY topic
                    ORDER BY count DESC
                    LIMIT 10
                """)
                popular_topics = [{"topic": row[0], "count": row[1]} for row in cursor]

                cursor = conn.execute("SELECT COUNT(DISTINCT tag) FROM conversation_tags")
                unique_tags = cursor.fetchone()[0]

                cursor = conn.execute("""
                    SELECT tag, COUNT(*) as count
                    FROM conversation_tags
                    GROUP BY tag
                    ORDER BY count DESC
                    LIMIT 10
                """)
                popular_tags = [{"tag": row[0], "count": row[1]} for row in cursor]

                cursor = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) FROM conversations "
                    "WHERE session_id IS NOT NULL"
                )
                unique_sessions = cursor.fetchone()[0]

                cursor = conn.execute(
                    "SELECT conversation_type, COUNT(*) as count FROM conversations "
                    "WHERE conversation_type IS NOT NULL "
                    "GROUP BY conversation_type ORDER BY count DESC"
                )
                conversation_types = [{"type": row[0], "count": row[1]} for row in cursor]

                return {
                    "total_conversations": total_conversations,
                    "unique_topics": unique_topics,
                    "popular_topics": popular_topics,
                    "unique_tags": unique_tags,
                    "popular_tags": popular_tags,
                    "unique_sessions": unique_sessions,
                    "conversation_types": conversation_types,
                }

        except sqlite3.Error as e:
            self.logger.exception(f"Stats query failed: {e}")
            return {"error": str(e)}

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query string for FTS5 to prevent syntax errors."""
        # Remove special FTS5 characters that could cause syntax errors
        special_chars = ['"', "'", "(", ")", "[", "]", "{", "}", "*", ":", "-"]
        sanitized = query

        for char in special_chars:
            sanitized = sanitized.replace(char, " ")

        # Split into terms and rejoin
        terms = sanitized.split()

        # Filter out empty terms and very short terms
        terms = [term for term in terms if len(term) >= 2]

        if not terms:
            return "NOT_FOUND_EMPTY_QUERY"

        # Join with OR operator for broader search
        return " OR ".join(terms)

    def rebuild_fts_index(self):
        """Rebuild the FTS5 index (useful after bulk imports)."""
        try:
            with self._connect() as conn:
                conn.execute("INSERT INTO conversations_fts(conversations_fts) VALUES('rebuild')")
                conn.commit()

        except sqlite3.Error as e:
            self.logger.exception(f"FTS index rebuild failed: {e}")
            raise

    def get_conversation_count(self) -> int:
        """Get total conversation count."""
        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM conversations")
                return cursor.fetchone()[0]

        except sqlite3.Error as e:
            self.logger.exception(f"Count query failed: {e}")
            return 0

    def get_indexed_file_paths(self) -> set[str]:
        """Return every ``file_path`` in the index, as stored (relative).

        Counts are not enough to tell whether the index matches the files on
        disk — equal totals over non-equal sets is exactly how the FTS5
        desync (#190) and the index-sync drift (#193) both stayed invisible.
        Callers that need to compare stores need the identities.
        """
        try:
            with self._connect() as conn:
                return {row[0] for row in conn.execute("SELECT file_path FROM conversations")}

        except sqlite3.Error as e:
            self.logger.exception(f"file_path query failed: {e}")
            return set()
