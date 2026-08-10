"""Guard: the suite must never write to the developer's real memory store.

Regression cover for conftest.py. If the module-scope redirect there is
removed, reordered into a fixture, or shadowed by a nested conftest, these
fail loudly instead of silently polluting ~/claude-memory again.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import conftest  # noqa: E402  (the suite's own conftest, imported as a module)

import server_fastmcp  # noqa: E402


def _real_store() -> Path:
    return (Path.home() / "claude-memory").resolve()


def test_env_points_at_the_throwaway_store():
    assert os.environ["CLAUDE_MEMORY_PATH"] == conftest._TEST_STORAGE_PATH


def test_module_level_singleton_avoids_the_real_store():
    """The singleton is built at import time — the case a fixture can't cover."""
    resolved = server_fastmcp.memory_server.storage_path.expanduser().resolve()
    assert resolved != _real_store()
    assert resolved.is_relative_to(Path(conftest._TEST_STORAGE_PATH).resolve())


@pytest.mark.asyncio
async def test_mcp_tool_writes_land_in_the_throwaway_store():
    """The exact call shape that leaked 611 rows into the live store."""
    result = await server_fastmcp.add_conversation(
        "isolation guard", "Isolation Guard Test", "2026-01-01T00:00:00Z"
    )
    assert "Status: success" in result

    written = list(Path(conftest._TEST_STORAGE_PATH).rglob("*.json"))
    assert written, "add_conversation wrote nothing under the throwaway store"
    assert not any(p.is_relative_to(_real_store()) for p in written)
