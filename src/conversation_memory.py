#!/usr/bin/env python3
"""
Common ConversationMemoryServer implementation

This module contains the core conversation memory functionality
shared between the FastMCP server and standalone implementations.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles

# Plain absolute import: ``src/`` is always a direct sys.path entry (see
# server_fastmcp.py for the full explanation), so no relative-import
# fallback is needed. ImportError is still caught here because it's a
# genuine possible failure -- SearchDatabase needs stdlib ``sqlite3``,
# which some minimal Python builds omit -- not a dual-style redefinition.
try:
    from search_database import SearchDatabase

    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False

# Plain absolute import, matching the ``search_database`` import above and
# validators.py's own header comment: ``src/`` is always a direct sys.path
# entry, so no relative-import fallback is needed here.
from validators import validate_storage_path


class ConversationMemoryServer:
    def __init__(
        self,
        storage_path: str = "~/claude-memory",
        use_data_dir: bool | None = None,
        enable_sqlite: bool = True,
    ):
        # Reject malformed storage_path values (empty, null bytes, the
        # stringified-None sentinel, relative paths) before they're used to
        # build any Path or create any directory. See validators.py for the
        # full rationale -- this is the single choke point both this class
        # and FastMCPConversationMemoryServer (which calls super().__init__)
        # go through.
        validate_storage_path(storage_path)
        self.storage_path = Path(storage_path).expanduser()

        # Auto-detect directory structure if not specified
        if use_data_dir is None:
            use_data_dir = self._detect_data_directory_structure()

        # Configure paths based on structure
        if use_data_dir:
            # New consolidated structure: data/conversations, data/summaries
            self.conversations_path = self.storage_path / "data" / "conversations"
            self.summaries_path = self.storage_path / "data" / "summaries"
        else:
            # Legacy structure: conversations/, summaries/ in storage root
            self.conversations_path = self.storage_path / "conversations"
            self.summaries_path = self.storage_path / "summaries"

        self.index_file = self.conversations_path / "index.json"
        self.topics_file = self.conversations_path / "topics.json"

        # Initialize logger
        self.logger = logging.getLogger(__name__)

        # Initialize SQLite search database if available and enabled
        self.search_db = None
        self.use_sqlite_search = False

        if enable_sqlite and SQLITE_AVAILABLE:
            try:
                db_path = self.conversations_path / "search.db"
                self.search_db = SearchDatabase(str(db_path))
                self.use_sqlite_search = True
                self.logger.info("SQLite FTS search enabled")
            except Exception as e:  # noqa: BLE001 - optional SQLite init: fall back to linear/JSON search rather than crash server startup
                self.logger.warning(f"Failed to initialize SQLite search: {e}")
                self.use_sqlite_search = False

        # Ensure directories exist
        self.conversations_path.mkdir(parents=True, exist_ok=True)
        self.summaries_path.mkdir(parents=True, exist_ok=True)
        (self.summaries_path / "weekly").mkdir(exist_ok=True)

        # Initialize index files if they don't exist
        self._init_index_files()

        # Sync index.json with conversation files on disk
        self._sync_index_from_files()

    def _detect_data_directory_structure(self) -> bool:
        """
        Auto-detect whether to use new data/ structure or legacy structure.

        Returns:
            True if data/ directory exists and contains conversations/
            False for legacy structure (conversations/ in storage root)
        """
        data_conversations = self.storage_path / "data" / "conversations"
        legacy_conversations = self.storage_path / "conversations"

        # If data/conversations exists, use new structure
        if data_conversations.exists():
            return True

        # If neither exists, default to new structure for new installations.
        # Legacy structure only applies when conversations/ exists in root.
        return not legacy_conversations.exists()

    def _init_index_files(self):
        """Initialize index and topics files if they don't exist"""
        if not self.index_file.exists():
            with open(self.index_file, "w") as f:
                json.dump(
                    {
                        "conversations": [],
                        "last_updated": datetime.now().isoformat(),
                    },
                    f,
                )

        if not self.topics_file.exists():
            with open(self.topics_file, "w") as f:
                json.dump(
                    {"topics": {}, "last_updated": datetime.now().isoformat()},
                    f,
                )

    def _sync_index_from_files(self):
        """Rebuild index.json from conversation files on disk if out of sync."""
        try:
            with open(self.index_file) as f:
                index_data = json.load(f)
            indexed_ids = {c["id"] for c in index_data.get("conversations", [])}
            indexed_paths = {
                c.get("file_path")
                for c in index_data.get("conversations", [])
                if c.get("file_path")
            }
        except (OSError, ValueError, KeyError, TypeError):
            indexed_ids = set()
            indexed_paths = set()
            index_data = {
                "conversations": [],
                "last_updated": datetime.now().isoformat(),
            }

        # Scan all conversation JSON files on disk.
        #
        # Narrow to files whose path is absent from index.json rather than
        # comparing counts. The previous guard was
        # ``if len(conv_files) <= len(indexed_ids): return``, which is wrong
        # whenever drift nets to zero: delete one conversation and add
        # another and the counts stay equal, so the new file was never
        # indexed. Same failure shape as the FTS5 desync fixed in #190 —
        # equal totals over non-equal sets.
        #
        # Diffing by path is also cheaper than the old code's fallback, which
        # opened every conversation on disk once the guard let it through.
        # ``conv_id`` lives inside the JSON, so a path-level filter is the
        # most we can decide without reading; the id check in the loop stays
        # as the authority. An index entry with no ``file_path`` (older
        # format) just makes its file a candidate and costs one extra read
        # before the id check skips it.
        conv_files = [
            f
            for f in self.conversations_path.rglob("conv_*.json")
            if str(f.relative_to(self.storage_path)) not in indexed_paths
        ]
        if not conv_files:
            return  # Every file on disk is already indexed

        added = 0
        for conv_file in conv_files:
            try:
                with open(conv_file, encoding="utf-8") as f:
                    conv_data = json.load(f)
                conv_id = conv_data.get("id", "")
                if conv_id and conv_id not in indexed_ids:
                    relative_path = conv_file.relative_to(self.storage_path)
                    index_data["conversations"].append(
                        {
                            "id": conv_id,
                            "title": conv_data.get("title", "Untitled"),
                            "date": conv_data.get("date", ""),
                            "topics": conv_data.get("topics", []),
                            "file_path": str(relative_path),
                            "added_at": conv_data.get("created_at", datetime.now().isoformat()),
                        }
                    )
                    indexed_ids.add(conv_id)
                    added += 1
            except (OSError, ValueError, KeyError, TypeError):
                continue

        if added > 0:
            index_data["last_updated"] = datetime.now().isoformat()
            with open(self.index_file, "w") as f:
                json.dump(index_data, f, indent=2)
            self.logger.info(
                f"Synced index.json: added {added} conversations ({len(indexed_ids)} total)"
            )

    def _get_date_folder(self, date: datetime) -> Path:
        """Get the folder path for a given date"""
        year_folder = self.conversations_path / str(date.year)
        month_folder = year_folder / f"{date.month:02d}-{date.strftime('%B').lower()}"
        month_folder.mkdir(parents=True, exist_ok=True)
        return month_folder

    def _extract_topics(self, content: str) -> list[str]:
        """Extract topics from conversation content using simple keyword extraction"""
        common_tech_terms = [
            "python",
            "javascript",
            "java",
            "css",
            "html",
            "react",
            "vue",
            "angular",
            "django",
            "flask",
            "nodejs",
            "express",
            "api",
            "database",
            "sql",
            "mongodb",
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "gcp",
            "git",
            "github",
            "gitlab",
            "testing",
            "debugging",
            "deployment",
            "authentication",
            "security",
            "encryption",
            "machine learning",
            "ai",
            "neural network",
            "data science",
            "analytics",
            "frontend",
            "backend",
            "fullstack",
            "devops",
            "cicd",
            "microservices",
            "rest",
            "graphql",
            "websocket",
            "json",
            "xml",
            "yaml",
            "markdown",
            "linux",
            "windows",
            "macos",
            "bash",
            "powershell",
            "terminal",
            "cli",
            "performance",
            "optimization",
            "scalability",
            "architecture",
            "design patterns",
            "agile",
            "scrum",
            "kanban",
            "project management",
            "code review",
        ]

        # Convert to lowercase for matching
        content_lower = content.lower()

        # Find quoted terms (likely important concepts)
        quoted_terms = re.findall(r'"([^"]+)"', content)
        quoted_terms.extend(re.findall(r"'([^']+)'", content))

        # Find technical terms
        found_topics = []
        for term in common_tech_terms:
            if term in content_lower:
                found_topics.append(term)

        # Add quoted terms (filtered for reasonable length)
        for term in quoted_terms:
            if len(term) > 2 and len(term) < 50 and term.lower() not in found_topics:
                found_topics.append(term.lower())

        # Find capitalized words that might be technologies/frameworks.
        # The trailing (?:[A-Z][a-zA-Z]*)* group this pattern used to carry was
        # redundant -- [a-zA-Z]* already matches uppercase -- but it made the
        # two halves ambiguous, so input like "AAAA...1" (a hex digest, base64
        # blob, or CONST_2) backtracked exponentially. Same matches, linear time.
        tech_pattern = r"\b[A-Z][a-zA-Z]*\b"
        capitalized_words = re.findall(tech_pattern, content)
        for word in capitalized_words:
            if (
                len(word) > 2
                and word.lower() not in found_topics
                and word
                not in [
                    "The",
                    "This",
                    "That",
                    "When",
                    "Where",
                    "How",
                    "What",
                    "Why",
                ]
            ):
                found_topics.append(word.lower())

        return found_topics[:10]  # Limit to top 10 topics

    async def add_conversation(
        self,
        content: str,
        title: str | None = None,
        conversation_date: str | None = None,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        conversation_type: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a new conversation to storage.

        The ``session_id``/``user_id``/``tags``/``conversation_type``/
        ``custom_fields`` parameters are keyword-only and all optional; they
        mirror the universal metadata fields produced by the importers in
        ``src/importers`` (PR #114) and are persisted alongside the
        conversation JSON plus indexed in the SQLite FTS database when
        available.
        """
        try:
            # Parse date or use current
            if conversation_date:
                try:
                    date = datetime.fromisoformat(conversation_date.replace("Z", "+00:00"))
                except ValueError:
                    date = datetime.now()
            else:
                date = datetime.now()

            # Generate title if not provided
            if not title:
                # Extract first line or first 50 characters as title
                lines = content.strip().split("\n")
                first_line = lines[0] if lines else content
                title = first_line[:50] + "..." if len(first_line) > 50 else first_line

            # Create conversation record
            conversation_id = f"conv_{date.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

            date_folder = self._get_date_folder(date)
            file_path = date_folder / f"{conversation_id}.json"

            # Extract topics
            topics = self._extract_topics(content)

            conversation_data: dict[str, Any] = {
                "id": conversation_id,
                "title": title,
                "content": content,
                "date": date.isoformat(),
                "topics": topics,
                "created_at": datetime.now().isoformat(),
            }

            # Only persist metadata keys when non-empty so legacy JSON files
            # stay shaped the same for existing users.
            if session_id:
                conversation_data["session_id"] = session_id
            if user_id:
                conversation_data["user_id"] = user_id
            if tags:
                conversation_data["tags"] = list(tags)
            if conversation_type:
                conversation_data["conversation_type"] = conversation_type
            if custom_fields:
                conversation_data["custom_fields"] = dict(custom_fields)

            # Save conversation file
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(conversation_data, indent=2, ensure_ascii=False))

            # Update index
            self._update_index(conversation_data, file_path)

            # Update topics index
            self._update_topics_index(topics, conversation_id)

            # Add to SQLite search database if available. Its return value
            # was previously ignored, so a failed SQLite write still left
            # the JSON file + index.json/topics.json entries behind while
            # reporting "success" — silent drift between JSON and SQLite.
            # Roll back the file/index writes on failure so a partial
            # add_conversation call doesn't leave an orphan.
            if self.use_sqlite_search and self.search_db:
                relative_path = str(file_path.relative_to(self.storage_path))
                sqlite_ok = self.search_db.add_conversation(conversation_data, relative_path)
                if not sqlite_ok:
                    self._rollback_add_conversation(file_path, conversation_id, topics)
                    return {
                        "status": "error",
                        "message": (
                            "Failed to save conversation: SQLite index update "
                            "failed; file and index writes were rolled back"
                        ),
                    }

            return {
                "status": "success",
                "file_path": str(file_path),
                "topics": topics,
                "message": f"Conversation saved successfully with ID: {conversation_id}",
            }

        except (OSError, ValueError, TypeError) as e:
            return {
                "status": "error",
                "message": f"Failed to save conversation: {str(e)}",
            }

    def _rollback_add_conversation(
        self, file_path: Path, conversation_id: str, topics: list[str]
    ) -> None:
        """Undo the file + index writes from a failed add_conversation call
        so a SQLite indexing failure doesn't leave an orphaned JSON file
        behind. Best-effort: each step is independently guarded (logged,
        not raised) since we're already in an error path and a failure in
        one cleanup step shouldn't block the others.

        Not a true transaction — see PR description for what "rollback"
        does and doesn't guarantee here.
        """
        try:
            file_path.unlink(missing_ok=True)
        except OSError as e:
            self.logger.exception(f"Rollback: failed to remove orphaned file: {e}")

        self._remove_index_entry(conversation_id)
        # Reuse the topics-diff helper with an empty new_topics set: every
        # entry in `topics` is treated as "dropped" for this conversation.
        self._resync_topics_index(topics, [], conversation_id)

    def _remove_index_entry(self, conversation_id: str) -> None:
        """Remove a conversation's entry from index.json (rollback helper)."""
        try:
            with open(self.index_file) as f:
                index_data = json.load(f)

            index_data["conversations"] = [
                c for c in index_data.get("conversations", []) if c.get("id") != conversation_id
            ]
            index_data["last_updated"] = datetime.now().isoformat()

            with open(self.index_file, "w") as f:
                json.dump(index_data, f, indent=2)

        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.exception(f"Rollback: failed to remove index entry: {e}")

    _CONVERSATION_ID_RE = re.compile(r"^conv_(\d{8})_(\d{6})_[\w]+$")

    def _resolve_conversation_path(self, conversation_id: str) -> Path | None:
        """Resolve a conversation_id to its on-disk JSON path, or None if the
        ID is malformed or the file is missing."""
        match = self._CONVERSATION_ID_RE.match(conversation_id)
        if not match:
            return None
        try:
            date = datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            return None
        year_folder = self.conversations_path / str(date.year)
        month_folder = year_folder / (f"{date.month:02d}-{date.strftime('%B').lower()}")
        file_path = month_folder / f"{conversation_id}.json"
        return file_path if file_path.exists() else None

    async def update_conversation(
        self,
        conversation_id: str,
        *,
        content: str | None = None,
        title: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        set_tags: list[str] | None = None,
        conversation_type: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        change_note: str | None = None,
    ) -> dict[str, Any]:
        """Update fields on an existing conversation in place.

        Mirrors ``add_conversation`` but operates on an existing record. The
        first line of ``content`` is always rewritten with a self-documenting
        change line — ``[update <iso-timestamp> — <change_note>]`` — so the
        record carries its own audit trail (chained for repeated updates).

        Tag ops: ``set_tags`` replaces the full list; ``add_tags`` /
        ``remove_tags`` mutate it. ``set_tags`` is mutually exclusive with the
        other two. Pass ``set_tags=[]`` to clear all tags.

        Returns ``{"status": "success", ...}`` on success or
        ``{"status": "error", "message": ...}`` on failure (malformed ID,
        missing file, no-op call, conflicting tag ops, I/O error).
        """
        if set_tags is not None and (add_tags or remove_tags):
            return {
                "status": "error",
                "message": ("set_tags is mutually exclusive with add_tags/remove_tags"),
            }

        file_path = self._resolve_conversation_path(conversation_id)
        if file_path is None:
            return {
                "status": "error",
                "message": (f"Conversation not found or invalid ID: {conversation_id}"),
            }

        try:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                original_raw = await f.read()
                conversation_data = json.loads(original_raw)
        except (OSError, ValueError) as e:
            return {
                "status": "error",
                "message": f"Failed to read conversation: {str(e)}",
            }

        changes: list[str] = []

        if title is not None and title != conversation_data.get("title"):
            conversation_data["title"] = title
            changes.append("title")

        if content is not None:
            conversation_data["content"] = content
            changes.append("content")

        if conversation_type is not None:
            conversation_data["conversation_type"] = conversation_type
            changes.append("conversation_type")

        if session_id is not None:
            conversation_data["session_id"] = session_id
            changes.append("session_id")

        if user_id is not None:
            conversation_data["user_id"] = user_id
            changes.append("user_id")

        existing_tags = list(conversation_data.get("tags") or [])
        new_tags = existing_tags
        if set_tags is not None:
            new_tags = list(dict.fromkeys(set_tags))
        elif add_tags or remove_tags:
            tags_set = list(dict.fromkeys(existing_tags))
            for t in add_tags or []:
                if t and t not in tags_set:
                    tags_set.append(t)
            if remove_tags:
                remove_lookup = set(remove_tags)
                tags_set = [t for t in tags_set if t not in remove_lookup]
            new_tags = tags_set
        if new_tags != existing_tags:
            conversation_data["tags"] = new_tags
            changes.append("tags")

        if not changes and change_note is None:
            return {
                "status": "error",
                "message": "No changes provided",
            }

        # Compose blockchain-style audit line and prepend to content.
        timestamp = datetime.now().isoformat(timespec="seconds")
        note = change_note if change_note else "; ".join(changes) or "no-op"
        audit_line = f"[update {timestamp} — {note}]"
        body = conversation_data.get("content", "")
        conversation_data["content"] = f"{audit_line}\n\n{body}"

        # Re-extract topics now that content has changed.
        old_topics = list(conversation_data.get("topics") or [])
        new_topics = self._extract_topics(conversation_data["content"])
        conversation_data["topics"] = new_topics
        conversation_data["updated_at"] = datetime.now().isoformat()

        try:
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(conversation_data, indent=2, ensure_ascii=False))
        except OSError as e:
            return {
                "status": "error",
                "message": f"Failed to write conversation: {str(e)}",
            }

        # Resync derived stores. INSERT OR REPLACE on the SQLite row also
        # cascades through the FTS triggers, so the FTS index stays current.
        #
        # Its return value was previously ignored -- the same latent defect
        # fixed in add_conversation. Unlike add_conversation there's no new
        # file to unlink on failure: update_conversation mutates an
        # *existing* record, so "rollback" here means restoring the file's
        # prior content rather than deleting it. index.json/topics.json
        # haven't been touched yet at this point (the calls below haven't
        # run), so there's nothing to revert there -- returning early is
        # enough to keep them consistent with the restored file.
        if self.use_sqlite_search and self.search_db:
            relative_path = str(file_path.relative_to(self.storage_path))
            sqlite_ok = self.search_db.add_conversation(conversation_data, relative_path)
            if not sqlite_ok:
                self._rollback_update_conversation(file_path, original_raw)
                return {
                    "status": "error",
                    "message": (
                        "Failed to update conversation: SQLite index update "
                        "failed; file content was restored to its prior state"
                    ),
                }

        self._replace_index_entry(conversation_data, file_path)
        self._resync_topics_index(old_topics, new_topics, conversation_id)

        return {
            "status": "success",
            "id": conversation_id,
            "file_path": str(file_path),
            "changes": changes,
            "audit_line": audit_line,
            "message": (
                f"Conversation {conversation_id} updated "
                f"({', '.join(changes) if changes else 'note-only'})"
            ),
        }

    def _rollback_update_conversation(self, file_path: Path, original_raw: str) -> None:
        """Undo the file write from a failed update_conversation call.

        update_conversation mutates an *existing* record in place, so
        rollback here means restoring the file's prior on-disk content
        (captured before the update ran) rather than unlinking it the way
        _rollback_add_conversation does for a brand-new file -- deleting
        would destroy a previously-valid conversation. index.json and
        topics.json are untouched by the time this runs (see call site),
        so there's nothing to revert there. Best-effort: logged, not
        raised, since we're already in an error path.
        """
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(original_raw)
        except OSError as e:
            self.logger.exception(f"Rollback: failed to restore prior content: {e}")

    def _replace_index_entry(self, conversation_data: dict, file_path: Path):
        """Replace (or insert) the index.json entry for a conversation."""
        try:
            with open(self.index_file) as f:
                index_data = json.load(f)

            relative_path = file_path.relative_to(self.storage_path)
            new_entry = {
                "id": conversation_data["id"],
                "title": conversation_data["title"],
                "date": conversation_data["date"],
                "topics": conversation_data["topics"],
                "file_path": str(relative_path),
                "added_at": datetime.now().isoformat(),
            }

            conversations = index_data.get("conversations", [])
            replaced = False
            for i, entry in enumerate(conversations):
                if entry.get("id") == conversation_data["id"]:
                    # Preserve original added_at if present so the entry's
                    # creation time isn't rewritten on every update.
                    if "added_at" in entry:
                        new_entry["added_at"] = entry["added_at"]
                    conversations[i] = new_entry
                    replaced = True
                    break
            if not replaced:
                conversations.append(new_entry)

            index_data["conversations"] = conversations
            index_data["last_updated"] = datetime.now().isoformat()

            with open(self.index_file, "w") as f:
                json.dump(index_data, f, indent=2)

        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.exception(f"Error replacing index entry: {e}")

    def _resync_topics_index(
        self,
        old_topics: list[str],
        new_topics: list[str],
        conversation_id: str,
    ):
        """Update the topics index after a content change: drop entries for
        topics no longer present, add entries for newly-extracted topics.
        Topics still present after the update are left untouched so we don't
        churn ``added_at`` timestamps."""
        try:
            with open(self.topics_file) as f:
                topics_data = json.load(f)
        except (OSError, ValueError) as e:
            self.logger.exception(f"Error loading topics index: {e}")
            return

        topics_index = topics_data.get("topics", {})
        old_set = set(old_topics)
        new_set = set(new_topics)
        dropped = old_set - new_set
        added = new_set - old_set

        for topic in dropped:
            entries = topics_index.get(topic)
            if not isinstance(entries, list):
                continue
            topics_index[topic] = [
                e
                for e in entries
                if not (isinstance(e, dict) and e.get("conversation_id") == conversation_id)
            ]
            if not topics_index[topic]:
                del topics_index[topic]

        for topic in added:
            existing = topics_index.get(topic)
            if not isinstance(existing, list):
                topics_index[topic] = []
            topics_index[topic].append(
                {
                    "conversation_id": conversation_id,
                    "added_at": datetime.now().isoformat(),
                }
            )

        topics_data["topics"] = topics_index
        topics_data["last_updated"] = datetime.now().isoformat()

        try:
            with open(self.topics_file, "w") as f:
                json.dump(topics_data, f, indent=2)
        except OSError as e:
            self.logger.exception(f"Error writing topics index: {e}")

    def _calculate_search_score(
        self,
        query_terms: list[str],
        content: str,
        title: str,
        topics: list[str],
    ) -> int:
        """Calculate relevance score for a conversation based on query terms"""
        score = 0
        for term in query_terms:
            score += content.count(term) * 1
            score += title.count(term) * 3
            if term in topics:
                score += 5
        return score

    async def _process_conversation_for_search(
        self, conv_info: dict, query_terms: list[str]
    ) -> dict | None:
        """Process a single conversation for search results"""
        try:
            file_path = self.storage_path / conv_info["file_path"]
            if not file_path.exists():
                return None

            async with aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()
                conv_data = json.loads(content)

            content = conv_data.get("content", "").lower()
            title = conv_data.get("title", "").lower()
            topics = [t.lower() for t in conv_data.get("topics", [])]

            score = self._calculate_search_score(query_terms, content, title, topics)

            if score > 0:
                return {
                    "id": conv_data["id"],
                    "title": conv_data["title"],
                    "date": conv_data["date"],
                    "topics": conv_data["topics"],
                    "score": score,
                    "preview": (content[:200] + "..." if len(content) > 200 else content),
                }
            return None

        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def search_conversations(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by content and topics"""
        # Use SQLite FTS search if available and enabled
        if self.use_sqlite_search and self.search_db:
            try:
                return self.search_db.search_conversations(query, limit)
            except Exception as e:  # noqa: BLE001 - documented fallback: SQLite search failure falls through to linear search below
                self.logger.warning(f"SQLite search failed, falling back to linear search: {e}")
                # Fall through to linear search

        # Fallback to linear search through JSON files
        try:
            # Load index
            async with aiofiles.open(self.index_file) as f:
                content = await f.read()
                index_data = json.loads(content)

            conversations = index_data.get("conversations", [])
            query_terms = query.lower().split()

            results = []
            for conv_info in conversations:
                result = await self._process_conversation_for_search(conv_info, query_terms)
                if result:
                    results.append(result)

            # Sort by score and return top results
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]

        except (OSError, ValueError, KeyError, TypeError) as e:
            return [{"error": f"Search failed: {str(e)}"}]

    def _get_preview(self, file_path: Path, query_terms: list[str]) -> str:
        """Get a preview of the conversation around the search terms"""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            lines = content.split("\n")
            preview_lines = []

            for i, line in enumerate(lines):
                line_lower = line.lower()
                if any(term in line_lower for term in query_terms):
                    # Include context lines around the match
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    context = lines[start:end]
                    preview_lines.extend(context)
                    break

            preview = "\n".join(preview_lines[:10])  # Limit preview length
            return preview[:500] + "..." if len(preview) > 500 else preview

        except (OSError, ValueError, KeyError, TypeError):
            return "Preview unavailable"

    def get_preview(self, conversation_id: str) -> str:
        """Get a preview of a specific conversation"""
        try:
            # Load index to find the conversation
            with open(self.index_file) as f:
                index_data = json.load(f)

            conversations = index_data.get("conversations", [])

            for conv_info in conversations:
                if conv_info["id"] == conversation_id:
                    file_path = self.storage_path / conv_info["file_path"]

                    if file_path.exists():
                        with open(file_path, encoding="utf-8") as f:
                            conv_data = json.load(f)

                        content = conv_data.get("content", "")
                        return content[:500] + "..." if len(content) > 500 else content
                    else:
                        return "Conversation file not found"

            return "Conversation not found"

        except (OSError, ValueError, KeyError, TypeError) as e:
            return f"Error retrieving conversation: {str(e)}"

    def _update_index(self, conversation_data: dict, file_path: Path):
        """Update the main index with new conversation"""
        try:
            # Load existing index
            with open(self.index_file) as f:
                index_data = json.load(f)

            # Add new conversation to index
            relative_path = file_path.relative_to(self.storage_path)
            conv_entry = {
                "id": conversation_data["id"],
                "title": conversation_data["title"],
                "date": conversation_data["date"],
                "topics": conversation_data["topics"],
                "file_path": str(relative_path),
                "added_at": datetime.now().isoformat(),
            }

            index_data["conversations"].append(conv_entry)
            index_data["last_updated"] = datetime.now().isoformat()

            # Save updated index
            with open(self.index_file, "w") as f:
                json.dump(index_data, f, indent=2)

        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.exception(f"Error updating index: {e}")

    def _update_topics_index(self, topics: list[str], conversation_id: str):
        """Update the topics index with new conversation topics"""
        try:
            # Load existing topics index
            with open(self.topics_file) as f:
                topics_data = json.load(f)

            topics_index = topics_data.get("topics", {})

            # Add conversation to each topic
            for topic in topics:
                if topic not in topics_index or isinstance(topics_index[topic], int):
                    # Initialize new topics or handle legacy format where topics were stored
                    # as counts
                    topics_index[topic] = []

                topics_index[topic].append(
                    {
                        "conversation_id": conversation_id,
                        "added_at": datetime.now().isoformat(),
                    }
                )

            topics_data["topics"] = topics_index
            topics_data["last_updated"] = datetime.now().isoformat()

            # Save updated topics index
            with open(self.topics_file, "w") as f:
                json.dump(topics_data, f, indent=2)

        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.exception(f"Error updating topics index: {e}")

    async def generate_weekly_summary(self, week_offset: int = 0) -> str:
        """Generate a weekly summary of conversations"""
        try:
            today = datetime.now()
            start_of_week = today - timedelta(days=today.weekday() + (week_offset * 7))
            end_of_week = start_of_week + timedelta(days=6)

            week_conversations = self._get_week_conversations(start_of_week, end_of_week)
            if not week_conversations:
                if week_offset == 0:
                    return (
                        f"No conversations found for current week "
                        f"({start_of_week.strftime('%Y-%m-%d')})"
                    )
                else:
                    return (
                        f"No conversations found for week of "
                        f"{start_of_week.strftime('%Y-%m-%d')} ({week_offset} week(s) ago)"
                    )

            summary_text = self._build_weekly_summary_text(
                start_of_week, end_of_week, week_conversations
            )

            summary_filename = f"week-{start_of_week.strftime('%Y-%m-%d')}.md"
            summary_file = self.summaries_path / "weekly" / summary_filename
            async with aiofiles.open(summary_file, "w", encoding="utf-8") as f:
                await f.write(summary_text)

            summary_text += f"\n---\n*Summary saved to {summary_file}*"
            return summary_text

        except (OSError, ValueError, KeyError, TypeError) as e:
            return f"Failed to generate weekly summary: {str(e)}"

    def _get_week_conversations(self, start_of_week: datetime, end_of_week: datetime) -> list[dict]:
        """Return conversations for the given week range"""
        try:
            with open(self.index_file) as f:
                index_data = json.load(f)
            conversations = index_data.get("conversations", [])
        except (OSError, ValueError, KeyError, TypeError):
            return []

        week_conversations = []
        for conv_info in conversations:
            try:
                conv_date = datetime.fromisoformat(conv_info["date"].replace("Z", "+00:00"))
                if start_of_week.date() <= conv_date.date() <= end_of_week.date():
                    file_path = self.storage_path / conv_info["file_path"]
                    if file_path.exists():
                        try:
                            with open(file_path, encoding="utf-8") as f:
                                conv_data = json.load(f)
                            week_conversations.append(conv_data)
                        except (OSError, ValueError, KeyError, TypeError):
                            week_conversations.append(
                                {
                                    "title": conv_info.get("title", "Untitled"),
                                    "date": conv_info["date"],
                                    "topics": conv_info.get("topics", []),
                                }
                            )
            except (ValueError, KeyError, TypeError):
                continue
        return week_conversations

    def _build_weekly_summary_text(
        self,
        start_of_week: datetime,
        end_of_week: datetime,
        week_conversations: list[dict],
    ) -> str:
        """Build the markdown summary text for the week"""
        summary_parts = []
        summary_parts.append(
            f"# Weekly Summary: {start_of_week.strftime('%Y-%m-%d')} "
            f"to {end_of_week.strftime('%Y-%m-%d')}"
        )
        summary_parts.append(f"\n## Overview\n- Total conversations: {len(week_conversations)}")

        all_topics = []
        for conv in week_conversations:
            all_topics.extend(conv.get("topics", []))

        topic_counts: dict[str, int] = {}
        for topic in all_topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

        if topic_counts:
            summary_parts.append("\n## Popular Topics")
            sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
            for topic, count in sorted_topics[:10]:
                summary_parts.append(f"- {topic}: {count} conversations")

        summary_parts.append("\n## Conversations")
        for conv in week_conversations:
            date_str = conv.get("date", "").split("T")[0]
            topics_str = ", ".join(conv.get("topics", [])[:3])
            if len(conv.get("topics", [])) > 3:
                topics_str += "..."
            conv_line = f"- [{date_str}] {conv.get('title', 'Untitled')}"
            if topics_str:
                conv_line += f" *Topics: {topics_str}*"
            summary_parts.append(conv_line)

        return "\n".join(summary_parts)

    # Only this many example paths are reported per drift category — enough to
    # start investigating, not enough to flood an MCP response.
    CONSISTENCY_SAMPLE_LIMIT = 5

    def check_consistency(self) -> dict[str, Any]:
        """Compare the conversation stores by identity and report the drift.

        A conversation lives in three places: its JSON file on disk, an entry
        in ``index.json``, and a row in SQLite (which in turn backs the FTS5
        index). Nothing kept them honest against each other. The checks that
        existed compared *totals* — ``verify_migration``'s ``counts_match``,
        and the old ``_sync_index_from_files`` guard fixed in #193 — and equal
        totals over non-equal sets is precisely how drift stayed invisible.
        A live store was found holding 31 JSON files that no index row
        referenced; a count comparison called it healthy.

        This is deliberately **read-only**. Re-indexing an orphaned file is
        additive and safe, but deleting a row whose file is missing is not:
        a mis-set ``CLAUDE_MEMORY_PATH`` or an unmounted storage directory
        makes *every* file look missing, and a repair wired into startup would
        take the whole index with it. Report here; let repair be explicit.
        """
        on_disk = {
            str(f.relative_to(self.storage_path))
            for f in self.conversations_path.rglob("conv_*.json")
        }

        try:
            with open(self.index_file) as f:
                index_entries = json.load(f).get("conversations", [])
            in_index = {c["file_path"] for c in index_entries if c.get("file_path")}
        except (OSError, ValueError, KeyError, TypeError):
            index_entries = []
            in_index = set()

        report: dict[str, Any] = {
            "json_files": len(on_disk),
            "index_entries": len(index_entries),
            "index_missing": sorted(on_disk - in_index),
            "index_stale": sorted(in_index - on_disk),
        }

        if self.use_sqlite_search and self.search_db:
            in_db = self.search_db.get_indexed_file_paths()
            report["db_rows"] = len(in_db)
            report["orphan_files"] = sorted(on_disk - in_db)
            report["dangling_rows"] = sorted(in_db - on_disk)
        else:
            report["db_rows"] = None
            report["orphan_files"] = []
            report["dangling_rows"] = []

        # Report counts, keep only a handful of paths as evidence.
        samples = {}
        for key in ("orphan_files", "dangling_rows", "index_missing", "index_stale"):
            paths = report[key]
            report[key] = len(paths)
            if paths:
                samples[key] = paths[: self.CONSISTENCY_SAMPLE_LIMIT]

        report["consistent"] = not samples
        if samples:
            report["samples"] = samples
        return report

    async def get_search_stats(self) -> dict[str, Any]:
        """Get search engine statistics and status."""
        stats: dict[str, Any] = {
            "sqlite_available": SQLITE_AVAILABLE,
            "sqlite_enabled": self.use_sqlite_search,
            "search_engine": ("sqlite_fts" if self.use_sqlite_search else "linear_json"),
        }

        if self.use_sqlite_search and self.search_db:
            try:
                db_stats = self.search_db.get_conversation_stats()
                stats.update(db_stats)
            except Exception as e:  # noqa: BLE001 - read-only diagnostics endpoint: report sqlite_error rather than crash the stats call
                stats["sqlite_error"] = str(e)

        # Walks the store, so it is meaningfully more expensive than the rest
        # of this call. Acceptable here because get_search_stats is invoked by
        # a user asking after the store's health, not on the init path.
        try:
            stats["consistency"] = self.check_consistency()
        except Exception as e:  # noqa: BLE001 - read-only diagnostics endpoint: a failed consistency scan must not take down the stats call
            stats["consistency_error"] = str(e)

        return stats

    async def migrate_to_sqlite(self) -> dict[str, Any]:
        """Migrate existing conversations to SQLite database."""
        if not SQLITE_AVAILABLE:
            return {"error": "SQLite not available"}

        if not self.use_sqlite_search:
            return {"error": "SQLite search not enabled"}

        try:
            from migrate_to_sqlite import ConversationMigrator

            # Determine directory structure
            use_data_dir = self.conversations_path.parent.name == "data"

            migrator = ConversationMigrator(str(self.storage_path), use_data_dir)
            migration_stats = migrator.migrate_all_conversations()

            return migration_stats

        except ImportError:
            return {"error": "Migration module not available"}
        except Exception as e:  # noqa: BLE001 - MCP tool handler: report migration failure rather than crash the server
            return {"error": f"Migration failed: {str(e)}"}

    async def search_by_topic(self, topic: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by specific topic."""
        if self.use_sqlite_search and self.search_db:
            try:
                return self.search_db.search_by_topic(topic, limit)
            except Exception as e:  # noqa: BLE001 - documented fallback: SQLite topic search failure falls through to JSON topic search
                self.logger.warning(f"SQLite topic search failed: {e}")

        # Fallback to JSON-based topic search
        return await self._search_topic_json(topic, limit)

    async def search_by_tag(self, tag: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by a specific tag (D2 metadata field).

        SQLite-only: if SQLite search is unavailable, returns an empty list
        with an error marker. Tags were introduced in PR #114 and are not
        maintained in the JSON topic index.
        """
        if self.use_sqlite_search and self.search_db:
            try:
                return self.search_db.search_by_tag(tag, limit)
            except Exception as e:  # noqa: BLE001 - MCP tool handler: report tag-search failure rather than crash the server (no JSON fallback exists)
                self.logger.warning("SQLite tag search failed: %s", e)
                return [{"error": f"Tag search failed: {e}"}]

        return [{"error": "Tag search requires SQLite FTS to be enabled"}]

    async def search_by_session_id(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search conversations by session_id (D2 metadata field)."""
        if self.use_sqlite_search and self.search_db:
            try:
                return self.search_db.search_by_session_id(session_id, limit)
            except Exception as e:  # noqa: BLE001 - MCP tool handler: report session-search failure rather than crash the server (no JSON fallback exists)
                self.logger.warning("SQLite session search failed: %s", e)
                return [{"error": f"Session search failed: {e}"}]

        return [{"error": "Session search requires SQLite FTS to be enabled"}]

    async def search_by_conversation_type(
        self, conversation_type: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search conversations by conversation_type (D2 metadata field)."""
        if self.use_sqlite_search and self.search_db:
            try:
                return self.search_db.search_by_conversation_type(conversation_type, limit)
            except Exception as e:  # noqa: BLE001 - MCP tool handler: report conversation-type-search failure rather than crash the server (no JSON fallback exists)
                self.logger.warning("SQLite conversation-type search failed: %s", e)
                return [{"error": f"Conversation-type search failed: {e}"}]

        return [{"error": "Conversation-type search requires SQLite FTS to be enabled"}]

    async def _search_topic_json(self, topic: str, limit: int) -> list[dict[str, Any]]:
        """Helper method for JSON-based topic search."""
        try:
            async with aiofiles.open(self.topics_file) as f:
                content = await f.read()
                topics_data = json.loads(content)

            topics_index = topics_data.get("topics", {})
            if topic not in topics_index:
                return []

            # Get conversation IDs for this topic
            topic_convs = topics_index[topic]

            # Load conversation details
            results = []
            for topic_conv in topic_convs[:limit]:
                conv_id = topic_conv.get("conversation_id")
                if conv_id:
                    preview = self.get_preview(conv_id)
                    if preview and "not found" not in preview.lower():
                        results.append(
                            {
                                "id": conv_id,
                                "preview": (
                                    preview[:200] + "..." if len(preview) > 200 else preview
                                ),
                            }
                        )

            return results

        except (OSError, ValueError, KeyError, TypeError) as e:
            return [{"error": f"Topic search failed: {str(e)}"}]

    def _analyze_conversations(self, conversations: list[dict]) -> list[dict]:
        """Legacy method for test compatibility - analyze conversation data"""
        results = []
        for conv in conversations:
            try:
                file_path = self.storage_path / conv.get("file_path", "")
                if not file_path.exists():
                    results.append({"error": "Conversation file not found"})
                    continue
                results.append({"title": conv.get("title", "Unknown")})
            except Exception as e:  # noqa: BLE001 - legacy per-item analysis helper: report error per conversation rather than abort the whole batch
                results.append({"error": str(e)})
        return results
