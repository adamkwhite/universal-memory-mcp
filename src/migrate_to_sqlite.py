#!/usr/bin/env python3
"""
Migration script to convert existing JSON-based conversations to SQLite FTS database.

This script processes all existing conversation JSON files and imports them
into the new SQLite FTS5 database for optimized search performance.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from search_database import SearchDatabase

# Constants
INDEX_JSON_FILENAME = "index.json"
TOPICS_JSON_FILENAME = "topics.json"

# Example paths reported per drift direction — enough to start investigating,
# not enough to bury the verification output.
VERIFY_SAMPLE_LIMIT = 5

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))


class ConversationMigrator:
    """Migrates JSON conversations to SQLite database."""

    def __init__(self, storage_path: str, use_data_dir: bool | None = None):
        """Initialize migrator with storage path."""
        self.storage_path = Path(storage_path).expanduser()

        # Auto-detect directory structure if not specified
        if use_data_dir is None:
            use_data_dir = self._detect_data_directory_structure()

        # Configure paths based on structure
        if use_data_dir:
            self.conversations_path = self.storage_path / "data" / "conversations"
        else:
            self.conversations_path = self.storage_path / "conversations"

        self.index_file = self.conversations_path / INDEX_JSON_FILENAME

        # Initialize search database
        db_path = self.conversations_path / "search.db"
        self.search_db = SearchDatabase(str(db_path))

        self.logger = logging.getLogger(__name__)

    def _detect_data_directory_structure(self) -> bool:
        """Auto-detect whether to use new data/ structure or legacy structure."""
        data_conversations = self.storage_path / "data" / "conversations"
        legacy_conversations = self.storage_path / "conversations"

        if data_conversations.exists():
            return True
        return not legacy_conversations.exists()

    def migrate_all_conversations(self) -> dict[str, Any]:
        """Migrate all conversations from JSON to SQLite."""
        self.logger.info("Starting migration of conversations to SQLite...")

        stats: dict[str, Any] = {
            "total_found": 0,
            "successfully_migrated": 0,
            "failed_migrations": 0,
            "skipped": 0,
        }

        try:
            # Load conversation index
            if not self.index_file.exists():
                self.logger.warning(f"Index file not found: {self.index_file}")
                return self._migrate_without_index()

            with open(self.index_file) as f:
                index_data = json.load(f)

            conversations = index_data.get("conversations", [])
            stats["total_found"] = len(conversations)

            self.logger.info(f"Found {len(conversations)} conversations in index")

            for conv_info in conversations:
                if self._migrate_single_conversation(conv_info):
                    stats["successfully_migrated"] += 1
                else:
                    stats["failed_migrations"] += 1

            # Rebuild FTS index for optimal performance
            self.search_db.rebuild_fts_index()

            self.logger.info(f"Migration completed: {stats}")
            return stats

        except Exception as e:  # noqa: BLE001 - top-level migration boundary: report failure in stats rather than crash the migration run
            self.logger.exception(f"Migration failed: {e}")
            stats["error"] = str(e)
            return stats

    def _migrate_without_index(self) -> dict[str, int]:
        """Migrate by scanning directory structure when index is missing."""
        self.logger.info("Index file missing, scanning directory structure...")

        stats = {
            "total_found": 0,
            "successfully_migrated": 0,
            "failed_migrations": 0,
            "skipped": 0,
        }

        # Find all JSON files recursively
        json_files = list(self.conversations_path.rglob("*.json"))

        # Filter out index and topics files
        conversation_files = [
            f for f in json_files if f.name not in [INDEX_JSON_FILENAME, TOPICS_JSON_FILENAME]
        ]

        stats["total_found"] = len(conversation_files)
        self.logger.info(f"Found {len(conversation_files)} conversation files")

        for file_path in conversation_files:
            if self._migrate_json_file(file_path):
                stats["successfully_migrated"] += 1
            else:
                stats["failed_migrations"] += 1

        # Rebuild FTS index
        self.search_db.rebuild_fts_index()

        self.logger.info(f"Directory scan migration completed: {stats}")
        return stats

    def _migrate_single_conversation(self, conv_info: dict) -> bool:
        """Migrate a single conversation from index entry."""
        try:
            file_path = self.storage_path / conv_info["file_path"]

            if not file_path.exists():
                self.logger.warning(f"Conversation file not found: {file_path}")
                return False

            with open(file_path, encoding="utf-8") as f:
                conv_data = json.load(f)

            # Add conversation to search database
            relative_path = str(file_path.relative_to(self.storage_path))
            success = self.search_db.add_conversation(conv_data, relative_path)

            if success:
                self.logger.debug(f"Migrated conversation: {conv_data.get('id', 'unknown')}")
            else:
                self.logger.error(
                    f"Failed to migrate conversation: {conv_data.get('id', 'unknown')}"
                )

            return success

        except Exception as e:  # noqa: BLE001 - resilience: skip unmigratable conversation, keep processing the rest of the batch
            self.logger.exception(
                f"Error migrating conversation {conv_info.get('id', 'unknown')}: {e}"
            )
            return False

    def _migrate_json_file(self, file_path: Path) -> bool:
        """Migrate a single JSON file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                conv_data = json.load(f)

            # Validate required fields
            required_fields = ["id", "title", "content", "date"]
            if not all(field in conv_data for field in required_fields):
                self.logger.warning(f"Skipping file with missing fields: {file_path}")
                return False

            # Ensure created_at field exists
            if "created_at" not in conv_data:
                conv_data["created_at"] = conv_data["date"]

            # Add conversation to search database
            relative_path = str(file_path.relative_to(self.storage_path))
            success = self.search_db.add_conversation(conv_data, relative_path)

            if success:
                self.logger.debug(f"Migrated file: {file_path}")
            else:
                self.logger.error(f"Failed to migrate file: {file_path}")

            return success

        except Exception as e:  # noqa: BLE001 - resilience: skip unmigratable file, keep processing the rest of the batch
            self.logger.exception(f"Error migrating file {file_path}: {e}")
            return False

    def verify_migration(self) -> dict[str, Any]:
        """Verify migration by comparing the two stores by identity.

        This used to report ``counts_match`` from ``sqlite_count ==
        json_count`` and ``main()`` printed "Migration verified
        successfully!" on the strength of it. Equal totals are not equal
        sets: a store with one unmigrated file and one stale row has matching
        counts and shares no members. That is not hypothetical — a live store
        was found holding 31 files no index row referenced, and this check
        would have called it verified.

        ``contents_match`` is therefore the verdict; ``counts_match`` is kept
        only because it is cheap and shows *how* a store drifted (equal counts
        with unequal contents means writes were lost in both directions).
        """
        self.logger.info("Verifying migration...")

        try:
            # Compare the same identities SQLite stores: paths relative to
            # storage_path, which is the basis add_conversation writes.
            json_files = {
                str(f.relative_to(self.storage_path))
                for f in self.conversations_path.rglob("*.json")
                if f.name not in (INDEX_JSON_FILENAME, TOPICS_JSON_FILENAME)
            }
            indexed = self.search_db.get_indexed_file_paths()

            missing_from_index = sorted(json_files - indexed)
            missing_from_disk = sorted(indexed - json_files)

            # Get database stats
            db_stats = self.search_db.get_conversation_stats()

            # Test search functionality
            test_results = self.search_db.search_conversations("python", limit=5)
            search_working = isinstance(test_results, list) and not any(
                "error" in str(r) for r in test_results
            )

            verification = {
                "sqlite_count": len(indexed),
                "json_count": len(json_files),
                "counts_match": len(indexed) == len(json_files),
                "contents_match": not missing_from_index and not missing_from_disk,
                "missing_from_index": len(missing_from_index),
                "missing_from_disk": len(missing_from_disk),
                "samples": {
                    "missing_from_index": missing_from_index[:VERIFY_SAMPLE_LIMIT],
                    "missing_from_disk": missing_from_disk[:VERIFY_SAMPLE_LIMIT],
                },
                "database_stats": db_stats,
                "search_test_passed": search_working,
                "search_results_count": len(test_results) if search_working else 0,
            }

            self.logger.info(f"Verification results: {verification}")
            return verification

        except Exception as e:  # noqa: BLE001 - top-level verification boundary: report failure rather than crash
            self.logger.exception(f"Verification failed: {e}")
            return {"error": str(e)}


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(description="Migrate conversations from JSON to SQLite FTS")
    parser.add_argument(
        "--storage-path",
        default="~/claude-memory",
        help="Path to conversation storage directory (default: ~/claude-memory)",
    )
    parser.add_argument(
        "--use-data-dir",
        action="store_true",
        help="Force use of data/ directory structure",
    )
    parser.add_argument(
        "--legacy-structure",
        action="store_true",
        help="Force use of legacy directory structure",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only run verification, skip migration",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Determine directory structure
    use_data_dir = None
    if args.use_data_dir:
        use_data_dir = True
    elif args.legacy_structure:
        use_data_dir = False

    # Initialize migrator
    migrator = ConversationMigrator(args.storage_path, use_data_dir)

    if args.verify_only:
        verification = migrator.verify_migration()
        print(json.dumps(verification, indent=2))
        return

    # Run migration
    print(f"Starting migration from: {migrator.conversations_path}")
    start_time = datetime.now()

    migration_stats = migrator.migrate_all_conversations()

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\nMigration completed in {duration:.2f} seconds")
    print(json.dumps(migration_stats, indent=2))

    # Run verification
    print("\nRunning verification...")
    verification = migrator.verify_migration()
    print(json.dumps(verification, indent=2))

    # Gate on contents_match, not counts_match: equal totals over unequal sets
    # is precisely the state this check used to pass.
    if verification.get("contents_match") and verification.get("search_test_passed"):
        print("\n✅ Migration verified successfully!")
    else:
        print("\n❌ Migration verification failed!")
        if verification.get("missing_from_index"):
            print(f"   {verification['missing_from_index']} file(s) not in the index")
        if verification.get("missing_from_disk"):
            print(f"   {verification['missing_from_disk']} indexed row(s) with no file")
        sys.exit(1)


if __name__ == "__main__":
    main()
