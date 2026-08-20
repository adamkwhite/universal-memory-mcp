#!/usr/bin/env python3
"""Point every Claude Code MCP entry for this project at the published console script.

Why this exists
---------------
PR #225 moved the modules under ``src/universal_memory_mcp/`` and made the
package use relative imports. An MCP config that launches the server as a loose
file -- ``python3 .../src/server_fastmcp.py`` -- therefore fails outright with
``attempted relative import with no known parent package``, and one pointing at
the pre-#225 path fails even earlier with ``No such file or directory``.

The fix on each machine is the same: install the published package and point the
config at its console script. Doing that by hand means editing ``~/.claude.json``
once for the global block and once per project block, which is exactly the sort
of repetitive JSON surgery that gets a comma wrong at 11pm.

The server key matters, not just the command
--------------------------------------------
Entries are rewritten to the key ``universal-memory-mcp``. The key is the user's
to choose and nothing in the store depends on it, but it *does* set the tool
namespace the client exposes (``mcp__<key>__*``). Anything referring to those
tool names by hand -- slash commands, skills, saved prompts -- breaks if the key
differs between machines. Keeping it uniform is the whole point.

What it does not touch
----------------------
Conversation storage. That lives in ``~/claude-memory/`` and is unaffected by
any of this; there is nothing to migrate. Unrelated MCP servers in the same
config are left exactly as found.

Usage
-----
    python3 scripts/switch_mcp_config.py            # dry run: report only
    python3 scripts/switch_mcp_config.py --apply    # write, after a backup

Idempotent: re-running against an already-correct config reports and changes
nothing. Safe to run from any directory -- the target is resolved from
``Path.home()``, not the working directory.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
from pathlib import Path
from typing import Any

TARGET_KEY = "universal-memory-mcp"
TARGET_VALUE: dict[str, Any] = {"command": "universal-memory-mcp", "args": []}

# Keys this project has shipped under. ``universal-memory-mcp`` is included so a
# correctly-named entry with a stale *command* is still rewritten.
KNOWN_KEYS = frozenset({"claude-memory", "claude-memory-mcp", "universal-memory-mcp"})

# Substrings that identify an entry launching this server from a source checkout,
# whatever key it happens to be filed under.
SOURCE_MARKERS = ("server_fastmcp", "claude-memory-mcp", "universal_memory_mcp")


def is_our_server(key: str, value: Any) -> bool:
    """True if this entry is this project's MCP server.

    Matches on the key when it is one we have shipped, and otherwise on the
    command/args referencing a source checkout -- so an entry someone filed
    under a custom key is still found.
    """
    if key in KNOWN_KEYS:
        return True
    return any(marker in json.dumps(value) for marker in SOURCE_MARKERS)


def rewrite_servers(servers: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return ``(new_servers, changes)`` for one ``mcpServers`` block.

    Unrelated servers are copied through untouched and keep their position.
    """
    rewritten: dict[str, Any] = {}
    changes: list[str] = []

    for key, value in servers.items():
        if not is_our_server(key, value):
            rewritten[key] = value
            continue
        if key == TARGET_KEY and value == TARGET_VALUE:
            rewritten[key] = value
            continue
        changes.append(f"{key}: {json.dumps(value)}  ->  {TARGET_KEY}: {json.dumps(TARGET_VALUE)}")
        rewritten[TARGET_KEY] = dict(TARGET_VALUE)

    return rewritten, changes


def rewrite_config(config: dict[str, Any]) -> list[str]:
    """Rewrite every ``mcpServers`` block in a parsed config, in place.

    Returns a human-readable description of each change, labelled by the block
    it came from. An empty list means the config was already correct.
    """
    changes: list[str] = []

    if config.get("mcpServers"):
        config["mcpServers"], block_changes = rewrite_servers(config["mcpServers"])
        changes += [f"[global] {c}" for c in block_changes]

    for project, project_config in (config.get("projects") or {}).items():
        if not project_config.get("mcpServers"):
            continue
        project_config["mcpServers"], block_changes = rewrite_servers(project_config["mcpServers"])
        changes += [f"[{project}] {c}" for c in block_changes]

    return changes


def backup_path(path: Path, now: datetime.datetime) -> Path:
    """Timestamped sibling of ``path``, so repeated runs never clobber a backup."""
    return path.with_name(f"{path.name}.bak-{now:%Y%m%d-%H%M%S}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Point Claude Code MCP entries at the universal-memory-mcp console script."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default is a dry run that only reports them)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".claude.json",
        help="config file to rewrite (default: ~/.claude.json)",
    )
    args = parser.parse_args(argv)

    if not args.config.exists():
        print(f"{args.config}: not found -- nothing to do.")
        return 0

    config = json.loads(args.config.read_text(encoding="utf-8"))
    changes = rewrite_config(config)

    if not changes:
        print(f"{args.config}: already correct, nothing to do.")
        return 0

    print(f"{args.config}: {len(changes)} entr{'y' if len(changes) == 1 else 'ies'} to rewrite\n")
    for change in changes:
        print(f"  {change}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    backup = backup_path(args.config, datetime.datetime.now())
    shutil.copy2(args.config, backup)
    args.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten. Backup: {backup}")
    print("Now run /mcp in each open Claude Code session to reconnect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
