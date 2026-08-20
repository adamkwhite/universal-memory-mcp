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
import re
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


# --------------------------------------------------------------------------
# Codex CLI (~/.codex/config.toml)
#
# Same server, different host. Two things differ from the JSON side:
#
# 1. The table name is NOT renamed. In Claude Code the key sets the tool
#    namespace that hand-written skills refer to, so it has to be uniform. Codex
#    has no such dependency here, and a Codex server table owns child tables
#    (``.env``, ``.tools.*``) that would all have to be renamed with it -- five
#    renames, each a chance to silently drop config, for no gain. Only the
#    command is actually broken, so only the command is touched.
#
# 2. Rewriting is line-based rather than parse-and-dump. tomllib is read-only,
#    and even with a writer, round-tripping would discard comments and ordering
#    in a file the user maintains by hand.
# --------------------------------------------------------------------------

TABLE_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
SERVER_TABLE_RE = re.compile(r"^mcp_servers\.([^.]+)$")


def _toml_table_name(line: str) -> str | None:
    match = TABLE_RE.match(line)
    return match.group(1).strip() if match else None


def _is_our_toml_server(name: str, body: list[str]) -> bool:
    """Decide from a server table's own lines whether it is our server.

    ``name`` is the bare table name (``claude-memory``), ``body`` the lines
    belonging to that table and no child table.
    """
    if name.strip('"') in KNOWN_KEYS:
        return True
    return any(marker in line for line in body for marker in SOURCE_MARKERS)


def rewrite_toml_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """Repoint any of our server tables at the console script.

    Returns ``(new_lines, changes)``. Only ``command`` and ``args`` inside a
    matching ``[mcp_servers.<name>]`` table are touched; child tables, other
    servers, comments, ordering and every other key are preserved byte for byte.
    """
    # Split into (table_name_or_None, [lines]) runs so each table is self-contained.
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in lines:
        name = _toml_table_name(line)
        if name is not None:
            sections.append((name, [line]))
        else:
            sections[-1][1].append(line)

    changes: list[str] = []
    out: list[str] = []

    for name, body in sections:
        server = SERVER_TABLE_RE.match(name) if name else None
        if not server or not _is_our_toml_server(server.group(1), body):
            out += body
            continue

        rewritten = []
        for line in body:
            if re.match(r"\s*command\s*=", line):
                if line.strip() != 'command = "universal-memory-mcp"':
                    changes.append(f"[{name}] {line.strip()}")
                rewritten.append('command = "universal-memory-mcp"\n')
            elif re.match(r"\s*args\s*=", line):
                if line.strip() != "args = []":
                    changes.append(f"[{name}] {line.strip()}")
                rewritten.append("args = []\n")
            else:
                rewritten.append(line)
        out += rewritten

    return out, changes


def process_file(path: Path, apply: bool) -> bool:
    """Report, and optionally write, the changes for one config file.

    Dispatches on suffix: ``.toml`` is a Codex config, anything else is a
    Claude Code JSON config. Returns True if anything was (or would be) changed.
    """
    if not path.exists():
        print(f"{path}: not found, skipping.")
        return False

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        new_lines, changes = rewrite_toml_lines(text.splitlines(keepends=True))
        new_text = "".join(new_lines)
    else:
        config = json.loads(text)
        changes = rewrite_config(config)
        new_text = json.dumps(config, indent=2) + "\n"

    if not changes:
        print(f"{path}: already correct, nothing to do.")
        return False

    print(f"{path}: {len(changes)} entr{'y' if len(changes) == 1 else 'ies'} to rewrite\n")
    for change in changes:
        print(f"  {change}")
    print()

    if apply:
        backup = backup_path(path, datetime.datetime.now())
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        print(f"  Written. Backup: {backup}\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Point MCP server entries at the universal-memory-mcp console script. "
            "Handles Claude Code (~/.claude.json) and Codex (~/.codex/config.toml)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default is a dry run that only reports them)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        action="append",
        dest="configs",
        help=(
            "config file to rewrite; repeatable. "
            "Default: ~/.claude.json and ~/.codex/config.toml, whichever exist."
        ),
    )
    args = parser.parse_args(argv)

    paths = args.configs or [
        Path.home() / ".claude.json",
        Path.home() / ".codex" / "config.toml",
    ]

    changed = [process_file(p, args.apply) for p in paths]

    if any(changed) and args.apply:
        print("Restart each client to reconnect: /mcp in Claude Code, or restart Codex.")
    elif any(changed):
        print("Dry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
