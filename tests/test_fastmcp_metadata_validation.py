#!/usr/bin/env python3
"""Tests that the MCP add_conversation/update_conversation tools validate
universal metadata fields (tags/session_id/user_id/conversation_type)
before forwarding to the core memory server.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from universal_memory_mcp import server_fastmcp

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestAddConversationMetadataValidation:
    @pytest.mark.asyncio
    async def test_valid_metadata_forwarded_sanitized(self, monkeypatch):
        captured = {}

        async def fake_add(*args, **kwargs):
            captured["kwargs"] = kwargs
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "add_conversation", fake_add)

        result = await server_fastmcp.add_conversation(
            content="c",
            title="t",
            session_id="sess\x0112",  # control char gets stripped
            user_id="u1",
            tags=["a", "", "b"],  # empty tag dropped
            conversation_type="code",
        )

        assert "Status: success" in result
        assert captured["kwargs"] == {
            "session_id": "sess12",
            "user_id": "u1",
            "tags": ["a", "b"],
            "conversation_type": "code",
        }

    @pytest.mark.asyncio
    async def test_too_many_tags_rejected_before_forwarding(self, monkeypatch):
        called = {"hit": False}

        async def fake_add(*args, **kwargs):
            called["hit"] = True
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "add_conversation", fake_add)

        result = await server_fastmcp.add_conversation(
            content="c",
            tags=[f"tag{i}" for i in range(51)],
        )

        assert "Status: error" in result
        assert "Too many tags" in result
        assert called["hit"] is False

    @pytest.mark.asyncio
    async def test_oversized_session_id_rejected(self, monkeypatch):
        called = {"hit": False}

        async def fake_add(*args, **kwargs):
            called["hit"] = True
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "add_conversation", fake_add)

        result = await server_fastmcp.add_conversation(content="c", session_id="x" * 300)

        assert "Status: error" in result
        assert called["hit"] is False

    @pytest.mark.asyncio
    async def test_null_byte_in_tag_rejected(self, monkeypatch):
        called = {"hit": False}

        async def fake_add(*args, **kwargs):
            called["hit"] = True
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "add_conversation", fake_add)

        result = await server_fastmcp.add_conversation(content="c", tags=["bad\x00tag"])

        assert "Status: error" in result
        assert called["hit"] is False


@pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP server not available")
class TestUpdateConversationMetadataValidation:
    @pytest.mark.asyncio
    async def test_valid_tag_ops_forwarded_sanitized(self, monkeypatch):
        captured = {}

        async def fake_update(conversation_id, **kwargs):
            captured["kwargs"] = kwargs
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "update_conversation", fake_update)

        result = await server_fastmcp.update_conversation(
            "conv_20260101_000000_abcd1234",
            add_tags=["new", ""],
            remove_tags=["old"],
            conversation_type="code",
        )

        assert "Status: success" in result
        assert captured["kwargs"]["add_tags"] == ["new"]
        assert captured["kwargs"]["remove_tags"] == ["old"]
        assert captured["kwargs"]["conversation_type"] == "code"

    @pytest.mark.asyncio
    async def test_set_tags_none_stays_none(self, monkeypatch):
        """set_tags=None (not provided) must not be turned into [] — that
        would silently clear all tags in the core update_conversation."""
        captured = {}

        async def fake_update(conversation_id, **kwargs):
            captured["kwargs"] = kwargs
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "update_conversation", fake_update)

        await server_fastmcp.update_conversation("conv_20260101_000000_abcd1234", title="renamed")

        assert captured["kwargs"]["set_tags"] is None

    @pytest.mark.asyncio
    async def test_invalid_conversation_type_rejected_before_forwarding(self, monkeypatch):
        called = {"hit": False}

        async def fake_update(conversation_id, **kwargs):
            called["hit"] = True
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "update_conversation", fake_update)

        result = await server_fastmcp.update_conversation(
            "conv_20260101_000000_abcd1234",
            conversation_type="x" * 200,
        )

        assert "Status: error" in result
        assert called["hit"] is False

    @pytest.mark.asyncio
    async def test_invalid_set_tags_rejected_before_forwarding(self, monkeypatch):
        called = {"hit": False}

        async def fake_update(conversation_id, **kwargs):
            called["hit"] = True
            return {"status": "success", "message": "ok"}

        monkeypatch.setattr(server_fastmcp.memory_server, "update_conversation", fake_update)

        result = await server_fastmcp.update_conversation(
            "conv_20260101_000000_abcd1234",
            set_tags=[f"tag{i}" for i in range(51)],
        )

        assert "Status: error" in result
        assert called["hit"] is False
