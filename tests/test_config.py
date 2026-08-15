"""Tests for ``src.config`` (centralized configuration module)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest  # type: ignore[import-not-found]

# Make ``src/`` importable when tests are run via pytest from repo root.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conftest import requires_posix_home  # noqa: E402

from config import (  # type: ignore[import-not-found]  # noqa: E402
    DEFAULT_CONFIG_FILE,
    DEFAULT_STORAGE_PATH,
    PLATFORM_PROFILES,
    VALID_LOG_FORMATS,
    VALID_LOG_LEVELS,
    Config,
    ConfigError,
    _parse_bool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def writable_storage(tmp_path: Path) -> Path:
    """Provide a writable directory for use as ``storage_path``."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture
def empty_env() -> dict:
    """Return an empty environment dict (so env vars don't leak in)."""
    return {}


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_dataclass_defaults(self) -> None:
        cfg = Config()
        assert cfg.storage_path == DEFAULT_STORAGE_PATH
        assert cfg.log_format == "text"
        assert cfg.log_level == "INFO"
        assert cfg.enable_sqlite is True
        assert cfg.console_output is False
        assert cfg.platform_profile == "default"

    def test_load_defaults_when_no_env_no_file(
        self, tmp_path: Path, empty_env: dict, writable_storage: Path
    ) -> None:
        # Use a missing config-file path and override storage to a tmp dir
        # so validation doesn't try to write to the real ~/claude-memory.
        missing_file = tmp_path / "absent.json"
        empty_env["CLAUDE_MEMORY_PATH"] = str(writable_storage)
        cfg = Config.load(config_file=missing_file, env=empty_env)
        assert cfg.log_format == "text"
        assert cfg.log_level == "INFO"
        assert cfg.platform_profile == "default"
        assert cfg.resolved_storage_path() == writable_storage.resolve()

    def test_default_config_file_path(self) -> None:
        # Sanity-check the documented default.
        assert Path.home() / ".claude-memory" / "config.json" == DEFAULT_CONFIG_FILE


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    def test_env_overrides_all_fields(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_LOG_FORMAT": "json",
            "CLAUDE_MCP_LOG_LEVEL": "debug",
            "CLAUDE_MCP_ENABLE_SQLITE": "false",
            "CLAUDE_MCP_CONSOLE_OUTPUT": "true",
            "CLAUDE_MCP_PLATFORM_PROFILE": "claude",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.log_format == "json"
        assert cfg.log_level == "DEBUG"  # normalised
        assert cfg.enable_sqlite is False
        assert cfg.console_output is True
        assert cfg.platform_profile == "claude"
        assert cfg.resolved_storage_path() == writable_storage.resolve()

    def test_monkeypatched_environ(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        writable_storage: Path,
    ) -> None:
        monkeypatch.setenv("CLAUDE_MEMORY_PATH", str(writable_storage))
        monkeypatch.setenv("CLAUDE_MCP_LOG_FORMAT", "json")
        # Use the real os.environ via env=None.
        cfg = Config.load(config_file=tmp_path / "no.json")
        assert cfg.log_format == "json"
        assert cfg.resolved_storage_path() == writable_storage.resolve()

    def test_empty_env_value_is_ignored(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_LOG_FORMAT": "",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.log_format == "text"  # default kept

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("False", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("NO", False),
            ("on", True),
            ("off", False),
        ],
    )
    def test_bool_env_parsing(
        self,
        value: str,
        expected: bool,
        tmp_path: Path,
        writable_storage: Path,
    ) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_ENABLE_SQLITE": value,
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.enable_sqlite is expected

    def test_disable_sqlite_off_switch(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MEMORY_DISABLE_SQLITE": "true",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.enable_sqlite is False

    def test_disable_sqlite_wins_over_enable(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_ENABLE_SQLITE": "true",
            "CLAUDE_MEMORY_DISABLE_SQLITE": "true",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.enable_sqlite is False


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------


class TestFileLoading:
    def test_loads_values_from_json_file(
        self, tmp_path: Path, writable_storage: Path, empty_env: dict
    ) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "storage_path": str(writable_storage),
                    "log_format": "json",
                    "log_level": "WARNING",
                    "enable_sqlite": False,
                    "console_output": True,
                }
            ),
            encoding="utf-8",
        )
        cfg = Config.load(config_file=cfg_file, env=empty_env)
        assert cfg.log_format == "json"
        assert cfg.log_level == "WARNING"
        assert cfg.enable_sqlite is False
        assert cfg.console_output is True
        assert cfg.resolved_storage_path() == writable_storage.resolve()

    def test_missing_file_uses_defaults(
        self, tmp_path: Path, empty_env: dict, writable_storage: Path
    ) -> None:
        empty_env["CLAUDE_MEMORY_PATH"] = str(writable_storage)
        cfg = Config.load(config_file=tmp_path / "absent.json", env=empty_env)
        # Defaults preserved.
        assert cfg.log_format == "text"
        assert cfg.log_level == "INFO"

    def test_invalid_json_raises(self, tmp_path: Path, empty_env: dict) -> None:
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            Config.load(config_file=cfg_file, env=empty_env)

    def test_non_mapping_top_level_raises(self, tmp_path: Path, empty_env: dict) -> None:
        cfg_file = tmp_path / "list.json"
        cfg_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ConfigError, match="JSON object"):
            Config.load(config_file=cfg_file, env=empty_env)

    def test_unknown_field_in_file_raises(
        self, tmp_path: Path, empty_env: dict, writable_storage: Path
    ) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "storage_path": str(writable_storage),
                    "totally_made_up": "value",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="Unknown configuration key"):
            Config.load(config_file=cfg_file, env=empty_env)

    def test_unreadable_file_raises(
        self, tmp_path: Path, empty_env: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "secret.json"
        cfg_file.write_text("{}", encoding="utf-8")

        # Force read_text to raise OSError other than FileNotFoundError.
        original_read_text = Path.read_text

        def _raise(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self == cfg_file:
                raise PermissionError("denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _raise)
        with pytest.raises(ConfigError, match="Could not read config file"):
            Config.load(config_file=cfg_file, env=empty_env)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_env_beats_file(self, tmp_path: Path, writable_storage: Path) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "storage_path": str(writable_storage),
                    "log_format": "text",
                    "log_level": "INFO",
                }
            ),
            encoding="utf-8",
        )
        env = {"CLAUDE_MCP_LOG_FORMAT": "json", "CLAUDE_MCP_LOG_LEVEL": "ERROR"}
        cfg = Config.load(config_file=cfg_file, env=env)
        assert cfg.log_format == "json"  # env wins
        assert cfg.log_level == "ERROR"  # env wins
        # File-only fields still applied.
        assert cfg.resolved_storage_path() == writable_storage.resolve()

    def test_file_beats_default(
        self, tmp_path: Path, writable_storage: Path, empty_env: dict
    ) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "storage_path": str(writable_storage),
                    "log_format": "json",
                }
            ),
            encoding="utf-8",
        )
        cfg = Config.load(config_file=cfg_file, env=empty_env)
        assert cfg.log_format == "json"

    def test_profile_beats_default_but_loses_to_file_and_env(
        self, tmp_path: Path, writable_storage: Path
    ) -> None:
        # ``chatgpt`` profile defaults to log_format=json. File then forces
        # text; env then forces json again.
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "platform_profile": "chatgpt",
                    "storage_path": str(writable_storage),
                    "log_format": "text",
                }
            ),
            encoding="utf-8",
        )
        # Without env override, file wins over profile.
        cfg = Config.load(config_file=cfg_file, env={})
        assert cfg.log_format == "text"
        assert cfg.platform_profile == "chatgpt"

        # With env override, env wins over file and profile.
        cfg2 = Config.load(
            config_file=cfg_file,
            env={"CLAUDE_MCP_LOG_FORMAT": "json"},
        )
        assert cfg2.log_format == "json"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_log_format(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), log_format="xml")
        with pytest.raises(ConfigError, match="Invalid log_format"):
            cfg.validate()

    def test_log_sample_rates_defaults_to_empty_dict(self) -> None:
        assert Config().log_sample_rates == {}

    def test_log_sample_rates_non_dict_raises(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), log_sample_rates="nope")  # type: ignore[arg-type]
        with pytest.raises(ConfigError, match="log_sample_rates must be a dict"):
            cfg.validate()

    def test_log_sample_rates_non_int_value_raises(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), log_sample_rates={"search": "ten"})  # type: ignore[dict-item]
        with pytest.raises(ConfigError, match="log_sample_rates must be a dict"):
            cfg.validate()

    def test_log_sample_rates_zero_or_negative_raises(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), log_sample_rates={"search": 0})
        with pytest.raises(ConfigError, match="log_sample_rates must be a dict"):
            cfg.validate()

    def test_log_sample_rates_from_env_json(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_LOG_SAMPLE_RATES": '{"performance": 10, "file_operation": 50}',
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.log_sample_rates == {"performance": 10, "file_operation": 50}

    def test_log_sample_rates_from_env_invalid_json_raises(
        self, tmp_path: Path, writable_storage: Path
    ) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_LOG_SAMPLE_RATES": "{not json",
        }
        with pytest.raises(ConfigError, match="Invalid JSON for log_sample_rates"):
            Config.load(config_file=tmp_path / "no.json", env=env)

    def test_log_sample_rates_from_file(
        self, tmp_path: Path, writable_storage: Path, empty_env: dict
    ) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "storage_path": str(writable_storage),
                    "log_sample_rates": {"search": 10},
                }
            ),
            encoding="utf-8",
        )
        cfg = Config.load(config_file=config_file, env=empty_env)
        assert cfg.log_sample_rates == {"search": 10}

    def test_invalid_log_level(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), log_level="LOUD")
        with pytest.raises(ConfigError, match="Invalid log_level"):
            cfg.validate()

    def test_invalid_platform_profile_via_validate(self, writable_storage: Path) -> None:
        cfg = Config(storage_path=str(writable_storage), platform_profile="bogus")
        with pytest.raises(ConfigError, match="Unknown platform_profile"):
            cfg.validate()

    def test_invalid_platform_profile_via_load(
        self, tmp_path: Path, writable_storage: Path
    ) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_PLATFORM_PROFILE": "bogus",
        }
        with pytest.raises(ConfigError, match="Unknown platform_profile"):
            Config.load(config_file=tmp_path / "no.json", env=env)

    def test_empty_storage_path(self) -> None:
        cfg = Config(storage_path="   ")
        with pytest.raises(ConfigError, match="non-empty"):
            cfg.validate()

    def test_unwritable_storage_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "unwritable"
        target.mkdir()

        # Force os.access to claim the dir is not writable.
        real_access = os.access

        def fake_access(path, mode):  # type: ignore[no-untyped-def]
            if Path(path).resolve() == target.resolve() and mode == os.W_OK:
                return False
            return real_access(path, mode)

        monkeypatch.setattr(os, "access", fake_access)
        # Patch the symbol used inside src.config too.
        import config as config_module

        monkeypatch.setattr(config_module.os, "access", fake_access)

        cfg = Config(storage_path=str(target))
        with pytest.raises(ConfigError, match="not writable"):
            cfg.validate()

    @pytest.mark.parametrize(
        "sentinel", ["None", "none", "NONE", "null", "Null", "nil", "  None  "]
    )
    def test_storage_path_rejects_python_sentinel_string(self, sentinel: str) -> None:
        """``storage_path`` set to the literal string 'None'/'null'/'nil' is rejected.

        Defends against the bug observed 2026-04-19 where an upstream caller
        stringified a None value into the config, producing a ``./None/``
        directory next to the cwd. Validation now catches this class of typo
        loudly instead of silently creating a misnamed data directory.
        """
        cfg = Config(storage_path=sentinel)
        with pytest.raises(ConfigError, match="literal sentinel string"):
            cfg.validate()

    def test_storage_path_mkdir_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "mkdir-blocked"

        def boom(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self.resolve() == target.resolve():
                raise PermissionError("nope")
            return None

        monkeypatch.setattr(Path, "mkdir", boom)
        cfg = Config(storage_path=str(target))
        with pytest.raises(ConfigError, match="not writable"):
            cfg.validate()

    def test_load_skips_validation_when_disabled(self, tmp_path: Path) -> None:
        env = {"CLAUDE_MCP_LOG_FORMAT": "xml"}  # bogus
        # Should not raise because validate=False.
        cfg = Config.load(config_file=tmp_path / "no.json", env=env, validate=False)
        assert cfg.log_format == "xml"


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class TestProfiles:
    def test_known_profiles_present(self) -> None:
        for name in ("default", "claude", "chatgpt", "cursor"):
            assert name in PLATFORM_PROFILES

    def test_chatgpt_profile_defaults(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_PLATFORM_PROFILE": "chatgpt",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.platform_profile == "chatgpt"
        assert cfg.log_format == "json"

    def test_claude_profile_defaults(self, tmp_path: Path, writable_storage: Path) -> None:
        env = {
            "CLAUDE_MEMORY_PATH": str(writable_storage),
            "CLAUDE_MCP_PLATFORM_PROFILE": "claude",
        }
        cfg = Config.load(config_file=tmp_path / "no.json", env=env)
        assert cfg.platform_profile == "claude"
        assert cfg.log_format == "text"


# ---------------------------------------------------------------------------
# Helpers / misc
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_to_dict_roundtrip(self, writable_storage: Path) -> None:
        cfg = Config(
            storage_path=str(writable_storage),
            log_format="json",
            log_level="DEBUG",
            enable_sqlite=False,
            console_output=True,
            platform_profile="claude",
        )
        data = cfg.to_dict()
        assert data["log_format"] == "json"
        assert data["enable_sqlite"] is False
        # Reconstruct via Config(**data) (sanity check).
        rebuilt = Config(**data)
        assert rebuilt == cfg

    @requires_posix_home
    def test_resolved_storage_path_expands(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = Config(storage_path="~/abc")
        assert cfg.resolved_storage_path() == (tmp_path / "abc").resolve()

    def test_resolved_storage_path_expands_envvar(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MY_DATA_DIR", str(tmp_path / "envroot"))
        cfg = Config(storage_path="$MY_DATA_DIR/sub")
        assert cfg.resolved_storage_path() == (tmp_path / "envroot" / "sub").resolve()

    def test_parse_bool_native_types(self) -> None:
        assert _parse_bool(True) is True
        assert _parse_bool(False) is False
        assert _parse_bool(1) is True
        assert _parse_bool(0) is False

    def test_parse_bool_invalid_raises(self) -> None:
        with pytest.raises(ConfigError):
            _parse_bool("maybe")
        with pytest.raises(ConfigError):
            _parse_bool(object())

    def test_valid_constants_exposed(self) -> None:
        # Defensive: external callers may import these.
        assert "text" in VALID_LOG_FORMATS
        assert "json" in VALID_LOG_FORMATS
        assert "INFO" in VALID_LOG_LEVELS
