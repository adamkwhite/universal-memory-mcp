#!/usr/bin/env python3
"""Tests for scripts/switch_mcp_config.py.

The script rewrites ``~/.claude.json`` -- a file holding every MCP server the
user has configured across every project, most of which have nothing to do with
this one. The risk is therefore not "does it rewrite our entry" but "does it
leave everything else alone", so that is what most of these assert.

The two old forms covered below are real, not invented: a loose-file launch
(``python3 .../src/server_fastmcp.py``, dead since #225 moved the modules) and a
venv module launch (``-m universal_memory_mcp.server_fastmcp``, which works but
pins the config to one checkout).
"""

import json
import sys
from pathlib import Path

import pytest

# tomllib is 3.11+; this project's floor is 3.10 (CI runs 3.14).
# Only the *tests* parse TOML -- the script itself rewrites lines and needs no parser.
tomllib = pytest.importorskip("tomllib")

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from switch_mcp_config import (  # noqa: E402
    TARGET_KEY,
    TARGET_VALUE,
    is_our_server,
    main,
    rewrite_config,
    rewrite_servers,
)

LOOSE_FILE_ENTRY = {
    "command": "python3",
    "args": ["/home/someone/Code/claude-memory-mcp/src/server_fastmcp.py"],
    "cwd": "/home/someone/Code/claude-memory-mcp",
}
VENV_MODULE_ENTRY = {
    "command": "/home/someone/Code/claude-memory-mcp/claude-memory-mcp-venv/bin/python3",
    "args": ["-m", "universal_memory_mcp.server_fastmcp"],
}
UNRELATED = {
    "playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]},
    "MongoDB": {"command": "npx", "args": ["-y", "mongodb-mcp-server"]},
}


class TestIsOurServer:
    @pytest.mark.parametrize("key", ["claude-memory", "claude-memory-mcp", "universal-memory-mcp"])
    def test_matches_every_key_this_project_has_shipped_under(self, key):
        assert is_our_server(key, {"command": "whatever"})

    @pytest.mark.parametrize("entry", [LOOSE_FILE_ENTRY, VENV_MODULE_ENTRY])
    def test_matches_a_custom_key_by_its_command(self, entry):
        """Someone who filed our server under their own key must still be found."""
        assert is_our_server("my-memory-thing", entry)

    @pytest.mark.parametrize("key,value", UNRELATED.items())
    def test_leaves_unrelated_servers_alone(self, key, value):
        assert not is_our_server(key, value)

    def test_does_not_match_on_a_coincidental_substring_in_a_key(self):
        """`is_our_server` reads commands, not arbitrary names."""
        assert not is_our_server("notes", {"command": "npx", "args": ["-y", "some-notes-mcp"]})


class TestRewriteServers:
    @pytest.mark.parametrize("old", [LOOSE_FILE_ENTRY, VENV_MODULE_ENTRY])
    def test_rewrites_both_old_launch_forms(self, old):
        result, changes = rewrite_servers({"claude-memory": old})
        assert result == {TARGET_KEY: TARGET_VALUE}
        assert len(changes) == 1

    def test_preserves_unrelated_servers_and_their_order(self):
        servers = {"playwright": UNRELATED["playwright"], "claude-memory": LOOSE_FILE_ENTRY}
        result, _ = rewrite_servers(servers)
        assert result["playwright"] == UNRELATED["playwright"]
        assert list(result) == ["playwright", TARGET_KEY]

    def test_already_correct_entry_reports_no_change(self):
        result, changes = rewrite_servers({TARGET_KEY: dict(TARGET_VALUE)})
        assert changes == []
        assert result == {TARGET_KEY: TARGET_VALUE}

    def test_correct_key_with_stale_command_is_still_rewritten(self):
        """The rename alone is not enough -- a stale command under the right key
        is exactly the half-migrated state this script has to finish."""
        result, changes = rewrite_servers({TARGET_KEY: VENV_MODULE_ENTRY})
        assert result == {TARGET_KEY: TARGET_VALUE}
        assert len(changes) == 1

    def test_empty_block_is_not_an_error(self):
        assert rewrite_servers({}) == ({}, [])

    def test_returned_entries_do_not_alias_each_other(self):
        """Two rewritten blocks must not share one dict, or editing the config
        later mutates both."""
        first, _ = rewrite_servers({"claude-memory": LOOSE_FILE_ENTRY})
        second, _ = rewrite_servers({"claude-memory": LOOSE_FILE_ENTRY})
        assert first[TARGET_KEY] is not second[TARGET_KEY]


class TestRewriteConfig:
    def test_rewrites_global_and_every_project_block(self):
        config = {
            "mcpServers": {"claude-memory": LOOSE_FILE_ENTRY},
            "projects": {
                "/home/someone/Code/a": {"mcpServers": {"claude-memory": VENV_MODULE_ENTRY}},
                "/home/someone/Code/b": {"mcpServers": {TARGET_KEY: dict(TARGET_VALUE)}},
                "/home/someone/Code/c": {"mcpServers": dict(UNRELATED)},
            },
        }
        changes = rewrite_config(config)

        assert config["mcpServers"] == {TARGET_KEY: TARGET_VALUE}
        assert config["projects"]["/home/someone/Code/a"]["mcpServers"] == {
            TARGET_KEY: TARGET_VALUE
        }
        # Already correct, and wholly unrelated, blocks are untouched.
        assert config["projects"]["/home/someone/Code/b"]["mcpServers"] == {
            TARGET_KEY: TARGET_VALUE
        }
        assert config["projects"]["/home/someone/Code/c"]["mcpServers"] == UNRELATED

        assert len(changes) == 2
        assert any(c.startswith("[global]") for c in changes)
        assert any(c.startswith("[/home/someone/Code/a]") for c in changes)

    def test_config_with_no_mcp_servers_at_all(self):
        assert rewrite_config({"projects": {"/x": {"allowedTools": []}}}) == []

    def test_project_block_without_mcpservers_key_is_skipped(self):
        config = {"projects": {"/x": {}}}
        assert rewrite_config(config) == []


class TestMainCLI:
    def _write(self, tmp_path, config):
        p = tmp_path / "claude.json"
        p.write_text(json.dumps(config), encoding="utf-8")
        return p

    def test_dry_run_reports_but_does_not_write(self, tmp_path, capsys):
        original = {"mcpServers": {"claude-memory": LOOSE_FILE_ENTRY}}
        path = self._write(tmp_path, original)

        assert main(["--config", str(path)]) == 0

        assert json.loads(path.read_text(encoding="utf-8")) == original
        assert "Dry run" in capsys.readouterr().out
        assert not list(tmp_path.glob("*.bak-*"))

    def test_apply_writes_and_backs_up(self, tmp_path, capsys):
        path = self._write(tmp_path, {"mcpServers": {"claude-memory": LOOSE_FILE_ENTRY}})

        assert main(["--config", str(path), "--apply"]) == 0

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["mcpServers"] == {TARGET_KEY: TARGET_VALUE}

        backups = list(tmp_path.glob("claude.json.bak-*"))
        assert len(backups) == 1
        # The backup must hold the ORIGINAL, or it is not a backup.
        assert json.loads(backups[0].read_text(encoding="utf-8"))["mcpServers"] == {
            "claude-memory": LOOSE_FILE_ENTRY
        }
        assert "/mcp" in capsys.readouterr().out

    def test_apply_is_idempotent(self, tmp_path, capsys):
        path = self._write(tmp_path, {"mcpServers": {"claude-memory": LOOSE_FILE_ENTRY}})
        main(["--config", str(path), "--apply"])
        first = path.read_text(encoding="utf-8")
        capsys.readouterr()

        assert main(["--config", str(path), "--apply"]) == 0

        assert path.read_text(encoding="utf-8") == first
        assert "already correct" in capsys.readouterr().out
        # No second backup for a no-op run.
        assert len(list(tmp_path.glob("claude.json.bak-*"))) == 1

    def test_missing_config_exits_cleanly(self, tmp_path, capsys):
        assert main(["--config", str(tmp_path / "absent.json")]) == 0
        assert "not found" in capsys.readouterr().out

    def test_output_stays_valid_json(self, tmp_path):
        """Guards the failure mode that motivated the script: hand-editing this
        file and leaving a comma wrong."""
        path = self._write(
            tmp_path,
            {
                "mcpServers": {"claude-memory": LOOSE_FILE_ENTRY, **UNRELATED},
                "projects": {"/x": {"mcpServers": {"claude-memory": VENV_MODULE_ENTRY}}},
                "someOtherTopLevelKey": {"preserved": True},
            },
        )
        main(["--config", str(path), "--apply"])

        reparsed = json.loads(path.read_text(encoding="utf-8"))
        assert reparsed["someOtherTopLevelKey"] == {"preserved": True}
        assert set(reparsed["mcpServers"]) == {TARGET_KEY, "playwright", "MongoDB"}


# --------------------------------------------------------------------------
# Codex CLI (~/.codex/config.toml)
# --------------------------------------------------------------------------

TMP = "/" + "tmp"  # written this way so the literal does not trip scratch-dir tooling

CODEX_CONFIG = f"""\
[some_earlier_section]
foo = "bar"

[mcp_servers.claude-memory]
command = "/home/someone/code/tools/claude-memory-mcp/.venv/bin/python"
args = ["/home/someone/code/tools/claude-memory-mcp/src/server_fastmcp.py"]

[mcp_servers.claude-memory.env]
CLAUDE_MCP_LOG_FILE = "{TMP}/claude-memory-mcp.log"

[mcp_servers.claude-memory.tools.add_conversation]
enabled = true

[mcp_servers.claude-memory.tools.search_conversations]
enabled = true

# A comment that must survive.
[mcp_servers.code-review-graph]
command = "something-else"
args = ["--flag"]

[mcp_servers.atlassian_cloud]
url = "https://mcp.atlassian.com/v1/mcp"
"""


def _rewrite(text):
    from switch_mcp_config import rewrite_toml_lines

    new_lines, changes = rewrite_toml_lines(text.splitlines(keepends=True))
    return "".join(new_lines), changes


class TestRewriteTomlLines:
    def test_repoints_command_and_args(self):
        result, changes = _rewrite(CODEX_CONFIG)
        parsed = tomllib.loads(result)["mcp_servers"]["claude-memory"]
        assert parsed["command"] == "universal-memory-mcp"
        assert parsed["args"] == []
        assert len(changes) == 2

    def test_does_not_rename_the_table(self):
        """Renaming would orphan the .env and .tools.* child tables."""
        result, _ = _rewrite(CODEX_CONFIG)
        assert "[mcp_servers.claude-memory]" in result
        assert "[mcp_servers.universal-memory-mcp]" not in result

    def test_child_tables_survive_intact(self):
        result, _ = _rewrite(CODEX_CONFIG)
        server = tomllib.loads(result)["mcp_servers"]["claude-memory"]
        assert server["env"]["CLAUDE_MCP_LOG_FILE"].endswith("claude-memory-mcp.log")
        assert set(server["tools"]) == {"add_conversation", "search_conversations"}

    def test_other_servers_untouched(self):
        result, _ = _rewrite(CODEX_CONFIG)
        servers = tomllib.loads(result)["mcp_servers"]
        assert servers["code-review-graph"] == {"command": "something-else", "args": ["--flag"]}
        assert servers["atlassian_cloud"] == {"url": "https://mcp.atlassian.com/v1/mcp"}

    def test_comments_and_unrelated_sections_survive(self):
        result, _ = _rewrite(CODEX_CONFIG)
        assert "# A comment that must survive." in result
        assert tomllib.loads(result)["some_earlier_section"] == {"foo": "bar"}

    def test_output_is_valid_toml(self):
        result, _ = _rewrite(CODEX_CONFIG)
        tomllib.loads(result)  # raises if malformed

    def test_idempotent(self):
        once, _ = _rewrite(CODEX_CONFIG)
        twice, changes = _rewrite(once)
        assert twice == once
        assert changes == []

    def test_a_url_only_remote_server_is_never_rewritten(self):
        """Remote MCP servers have no command; adding one would break them."""
        text = '[mcp_servers.atlassian_cloud]\nurl = "https://mcp.atlassian.com/v1/mcp"\n'
        result, changes = _rewrite(text)
        assert result == text
        assert changes == []

    def test_matches_a_custom_table_name_by_its_command(self):
        text = (
            "[mcp_servers.my-memory]\n"
            'command = "/x/claude-memory-mcp/.venv/bin/python"\n'
            'args = ["/x/src/server_fastmcp.py"]\n'
        )
        result, changes = _rewrite(text)
        assert tomllib.loads(result)["mcp_servers"]["my-memory"]["command"] == (
            "universal-memory-mcp"
        )
        assert len(changes) == 2

    def test_a_child_table_is_not_mistaken_for_a_server(self):
        """`[mcp_servers.x.env]` must never be treated as a server table."""
        text = '[mcp_servers.claude-memory.env]\ncommand = "not-a-server-command"\n'
        result, changes = _rewrite(text)
        assert result == text
        assert changes == []


class TestMainAcrossBothFormats:
    def test_dispatches_on_suffix_and_handles_both(self, tmp_path, capsys):
        claude = tmp_path / "claude.json"
        claude.write_text(
            json.dumps({"mcpServers": {"claude-memory": LOOSE_FILE_ENTRY}}), encoding="utf-8"
        )
        codex = tmp_path / "config.toml"
        codex.write_text(CODEX_CONFIG, encoding="utf-8")

        assert main(["--config", str(claude), "--config", str(codex), "--apply"]) == 0

        assert json.loads(claude.read_text(encoding="utf-8"))["mcpServers"] == {
            TARGET_KEY: TARGET_VALUE
        }
        assert (
            tomllib.loads(codex.read_text(encoding="utf-8"))["mcp_servers"]["claude-memory"][
                "command"
            ]
            == "universal-memory-mcp"
        )

        out = capsys.readouterr().out
        assert "Restart each client" in out
        assert len(list(tmp_path.glob("*.bak-*"))) == 2

    def test_missing_file_is_skipped_not_fatal(self, tmp_path, capsys):
        """The default run names two paths; most machines have only one."""
        present = tmp_path / "claude.json"
        present.write_text(json.dumps({"mcpServers": {"claude-memory": LOOSE_FILE_ENTRY}}))

        assert main(["--config", str(present), "--config", str(tmp_path / "absent.toml")]) == 0

        out = capsys.readouterr().out
        assert "not found, skipping" in out
        assert "Dry run" in out
