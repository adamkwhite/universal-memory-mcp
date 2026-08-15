"""Regression tests for literal FTS search and authoritative retrieval."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import server_fastmcp
from conversation_memory import ConversationMemoryServer
from search_database import SearchDatabase


def _record(*, conversation_id: str, content: str) -> dict:
    return {
        "id": conversation_id,
        "title": "Llama.cpp UI Cache race condition",
        "content": content,
        "date": "2026-08-15T00:00:00",
        "created_at": "2026-08-15T00:00:00",
        "topics": ["debugging"],
        "tags": ["source:llama.cpp"],
        "session_id": "llama.cpp:source-session",
        "conversation_type": "chat",
    }


def test_fts_treats_punctuation_and_operators_as_literal_terms(tmp_path: Path) -> None:
    database = SearchDatabase(str(tmp_path / "search.db"))
    conversation_id = "conv_20260815_000000_12345678"
    assert database.add_conversation(
        _record(
            conversation_id=conversation_id,
            content="A llama.cpp cache race condition involving C++ and OR handling.",
        ),
        "data/conversations/example.json",
    )

    for query in (
        "llama.cpp",
        'llama.cpp (OR) "cache"',
        "C++",
    ):
        results = database.search_conversations(query)
        assert results
        assert "error" not in results[0]
        assert results[0]["id"] == conversation_id
        assert results[0]["session_id"] == "llama.cpp:source-session"
        assert results[0]["conversation_type"] == "chat"

    assert database.search_conversations("...()[]{}-:*") == []


def test_get_conversation_reads_authoritative_json_and_rejects_bad_ids(
    tmp_path: Path,
) -> None:
    server = ConversationMemoryServer(
        str(tmp_path),
        use_data_dir=True,
        enable_sqlite=False,
    )
    added = asyncio.run(
        server.add_conversation(
            "original content",
            "Authoritative import",
            "2026-08-15T00:00:00",
            session_id="llama.cpp:source-session",
            conversation_type="chat",
        )
    )
    conversation_id = Path(added["file_path"]).stem

    retrieved = asyncio.run(server.get_conversation(conversation_id))
    assert retrieved["content"] == "original content"
    assert retrieved["session_id"] == "llama.cpp:source-session"

    invalid = asyncio.run(server.get_conversation("../../outside"))
    assert "error" in invalid


def test_authoritative_update_can_skip_audit_without_changing_default(
    tmp_path: Path,
) -> None:
    server = ConversationMemoryServer(
        str(tmp_path),
        use_data_dir=True,
        enable_sqlite=False,
    )
    added = asyncio.run(
        server.add_conversation(
            "version one",
            "Imported conversation",
            "2026-08-15T00:00:00",
        )
    )
    conversation_id = Path(added["file_path"]).stem

    result = asyncio.run(
        server.update_conversation(
            conversation_id,
            content="version two",
            record_audit=False,
        )
    )
    assert result["status"] == "success"
    assert "audit_line" not in result
    retrieved = asyncio.run(server.get_conversation(conversation_id))
    assert retrieved["content"] == "version two"

    result = asyncio.run(
        server.update_conversation(
            conversation_id,
            content="version three",
            change_note="interactive edit",
        )
    )
    assert result["status"] == "success"
    assert result["audit_line"].startswith("[update ")
    retrieved = asyncio.run(server.get_conversation(conversation_id))
    assert retrieved["content"].startswith(result["audit_line"] + "\n\nversion three")


class _FakeFastMCPMemory:
    async def search_conversations(self, query: str, limit: int) -> list[dict]:
        if query == "broken":
            return [{"error": "database unavailable"}]
        return [
            {
                "id": "conv_20260815_000000_12345678",
                "title": "Llama.cpp UI Cache race condition",
                "date": "2026-08-15T00:00:00",
                "topics": ["debugging"],
                "score": -4.2,
                "preview": "cache race",
                "session_id": "llama.cpp:source-session",
                "conversation_type": "chat",
            }
        ]

    async def get_conversation(self, conversation_id: str) -> dict:
        return {
            "id": conversation_id,
            "title": "Llama.cpp UI Cache race condition",
            "date": "2026-08-15T00:00:00",
            "content": "abcdefghij",
            "session_id": "llama.cpp:source-session",
            "conversation_type": "chat",
        }


def test_fastmcp_search_exposes_ids_and_reports_errors_truthfully() -> None:
    with patch.object(server_fastmcp, "memory_server", _FakeFastMCPMemory()):
        response = asyncio.run(server_fastmcp.search_conversations("llama.cpp"))
        assert "ID: conv_20260815_000000_12345678" in response
        assert "Session: llama.cpp:source-session" in response
        assert "Type: chat" in response

        error = asyncio.run(server_fastmcp.search_conversations("broken"))
        assert error == "Search failed for 'broken': database unavailable"
        assert "Found 1" not in error


def test_fastmcp_get_conversation_caps_and_marks_content() -> None:
    with patch.object(server_fastmcp, "memory_server", _FakeFastMCPMemory()):
        response = asyncio.run(
            server_fastmcp.get_conversation(
                "conv_20260815_000000_12345678",
                max_chars=5,
            )
        )
        assert "Content: 5 of 10 characters" in response
        assert "abcde" in response
        assert "retrieve more" in response

        invalid = asyncio.run(
            server_fastmcp.get_conversation(
                "conv_20260815_000000_12345678",
                max_chars=0,
            )
        )
        assert invalid.startswith("Status: error")
