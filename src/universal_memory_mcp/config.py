"""Centralized configuration for the Claude Memory MCP system.

This module exposes a :class:`Config` dataclass that consolidates settings
previously scattered across environment variables and module-level constants
in ``server_fastmcp.py``, ``logging_config.py`` and ``path_utils.py``.

Loading precedence (highest wins)::

    1. Environment variables (``CLAUDE_MEMORY_*`` / ``CLAUDE_MCP_*``)
    2. Configuration file (default ``~/.claude-memory/config.json``)
    3. Built-in defaults

A configuration file is optional; when absent the defaults are used. The file
format is JSON with a flat structure mirroring the dataclass fields, e.g.::

    {
        "storage_path": "~/claude-memory",
        "log_format": "json",
        "log_level": "INFO",
        "enable_sqlite": true,
        "console_output": false,
        "platform_profile": "default"
    }

This module is intentionally side-effect free: importing it does not read any
files, parse any environment variables or create directories.  Call
:meth:`Config.load` to build a config from the environment + file, and
:meth:`Config.validate` to check the result.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, ClassVar

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default location for the on-disk configuration file.
DEFAULT_CONFIG_FILE: Path = Path.home() / ".claude-memory" / "config.json"

#: Default location for conversation storage. Mirrors ``path_utils``.
DEFAULT_STORAGE_PATH: str = "~/claude-memory"

#: Allowed values for :attr:`Config.log_format`.
VALID_LOG_FORMATS: tuple[str, ...] = ("text", "json")

#: Allowed values for :attr:`Config.log_level`.
VALID_LOG_LEVELS: tuple[str, ...] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)

#: Built-in platform profiles. Each profile supplies a partial set of
#: defaults that are layered onto the base defaults.  Users can extend this
#: behaviour by selecting a profile via the ``platform_profile`` field.
PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "default": {},
    "claude": {
        "log_format": "text",
        "enable_sqlite": True,
    },
    "chatgpt": {
        "log_format": "json",
        "enable_sqlite": True,
    },
    "cursor": {
        "log_format": "text",
        "enable_sqlite": True,
    },
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised when configuration loading or validation fails."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: Any) -> bool:
    """Parse a value into a boolean using common truthy/falsy strings.

    Accepts strings (case-insensitive: ``true``/``false``, ``1``/``0``,
    ``yes``/``no``, ``on``/``off``) as well as native ``bool``/``int`` types.

    Raises:
        ConfigError: If ``value`` cannot be interpreted as a boolean.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Cannot interpret value as boolean: {value!r}")


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """Application configuration.

    Attributes:
        storage_path: Directory used for conversation storage. Mirrors the
            ``CLAUDE_MEMORY_PATH`` environment variable.
        log_format: One of ``"text"`` or ``"json"``. Mirrors
            ``CLAUDE_MCP_LOG_FORMAT``.
        log_level: Standard ``logging`` level name. Mirrors
            ``CLAUDE_MCP_LOG_LEVEL``.
        enable_sqlite: Whether SQLite-backed search is enabled.
        console_output: Whether logs are echoed to stdout. Mirrors
            ``CLAUDE_MCP_CONSOLE_OUTPUT``.
        platform_profile: Name of a profile from :data:`PLATFORM_PROFILES`
            whose defaults are layered onto the base defaults during
            :meth:`load`.
        log_sample_rates: Per operation-type log sampling rates, keyed by
            the ``context["type"]`` value structured log calls attach
            (e.g. ``"performance"``, ``"file_operation"``). A rate of ``N``
            means "log 1 out of every N records of that type"; a type
            missing from the mapping is never sampled (rate 1). Mirrors
            ``CLAUDE_MCP_LOG_SAMPLE_RATES`` (a JSON object string). WARNING
            and above are never sampled regardless of this setting.
    """

    storage_path: str = DEFAULT_STORAGE_PATH
    log_format: str = "text"
    log_level: str = "INFO"
    enable_sqlite: bool = True
    console_output: bool = False
    platform_profile: str = "default"
    log_sample_rates: dict[str, int] = field(default_factory=dict)

    #: Mapping of dataclass field name -> environment variable name.
    ENV_MAPPING: ClassVar[dict[str, str]] = {
        "storage_path": "CLAUDE_MEMORY_PATH",
        "log_format": "CLAUDE_MCP_LOG_FORMAT",
        "log_level": "CLAUDE_MCP_LOG_LEVEL",
        "enable_sqlite": "CLAUDE_MCP_ENABLE_SQLITE",
        "console_output": "CLAUDE_MCP_CONSOLE_OUTPUT",
        "platform_profile": "CLAUDE_MCP_PLATFORM_PROFILE",
        "log_sample_rates": "CLAUDE_MCP_LOG_SAMPLE_RATES",
    }

    # -- Construction --------------------------------------------------

    @classmethod
    def load(
        cls,
        config_file: Path | None = None,
        env: Mapping[str, str] | None = None,
        validate: bool = True,
    ) -> Config:
        """Construct a :class:`Config` from the environment and config file.

        Loading order, lowest to highest precedence:

            1. Built-in defaults
            2. Profile defaults (driven by ``platform_profile``)
            3. Values in ``config_file``
            4. Environment variables

        Args:
            config_file: Path to the JSON configuration file. ``None`` uses
                :data:`DEFAULT_CONFIG_FILE`. Missing files are ignored.
            env: Mapping used in place of :data:`os.environ`. Primarily
                useful for testing.
            validate: If ``True`` (default), :meth:`validate` is invoked on
                the result.

        Raises:
            ConfigError: If the file is malformed or contains invalid values,
                or if ``validate`` is ``True`` and validation fails.
        """
        env_map: Mapping[str, str] = os.environ if env is None else env
        cfg_path = DEFAULT_CONFIG_FILE if config_file is None else config_file

        # Layer 1: built-in defaults via dataclass instantiation.
        cfg = cls()

        # Layer 2: profile defaults. Resolve the profile from env > file >
        # default so a profile chosen at any layer can still influence the
        # remaining fields. We only consume the ``platform_profile`` value
        # here; everything else is applied below.
        file_data = _load_file_data(cfg_path)
        profile_name = (
            env_map.get(cls.ENV_MAPPING["platform_profile"])
            or file_data.get("platform_profile")
            or cfg.platform_profile
        )
        cfg = _apply_profile(cfg, profile_name)

        # Layer 3: configuration file overrides.
        cfg = _apply_overrides(cfg, file_data, source="config file")

        # Layer 4: environment variable overrides.
        env_overrides = {
            field_name: env_map[env_name]
            for field_name, env_name in cls.ENV_MAPPING.items()
            if env_name in env_map and env_map[env_name] != ""
        }
        cfg = _apply_overrides(cfg, env_overrides, source="environment")

        # Explicit off-switch alias. CLAUDE_MEMORY_DISABLE_SQLITE=true is the
        # inverse of CLAUDE_MCP_ENABLE_SQLITE and, being the more specific
        # directive, wins if both are set.
        disable_sqlite = env_map.get("CLAUDE_MEMORY_DISABLE_SQLITE")
        if disable_sqlite is not None and disable_sqlite != "":
            cfg = replace(cfg, enable_sqlite=not _parse_bool(disable_sqlite))

        if validate:
            cfg.validate()
        return cfg

    # -- Validation ----------------------------------------------------

    def validate(self) -> None:
        """Validate field values and (best-effort) the storage path.

        Raises:
            ConfigError: If any field is invalid.
        """
        if self.log_format not in VALID_LOG_FORMATS:
            raise ConfigError(
                f"Invalid log_format {self.log_format!r}; "
                f"must be one of {sorted(VALID_LOG_FORMATS)}"
            )
        if self.log_level.upper() not in VALID_LOG_LEVELS:
            raise ConfigError(
                f"Invalid log_level {self.log_level!r}; must be one of {sorted(VALID_LOG_LEVELS)}"
            )
        if self.platform_profile not in PLATFORM_PROFILES:
            raise ConfigError(
                f"Unknown platform_profile {self.platform_profile!r}; "
                f"must be one of {sorted(PLATFORM_PROFILES)}"
            )
        if not isinstance(self.log_sample_rates, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 1
            for k, v in self.log_sample_rates.items()
        ):
            raise ConfigError(
                f"log_sample_rates must be a dict[str, int] with values >= 1; "
                f"got {self.log_sample_rates!r}"
            )
        # Normalise log_level to upper-case so downstream consumers don't
        # need to repeat the call.
        object.__setattr__(self, "log_level", self.log_level.upper())

        self._validate_storage_path()

    def _validate_storage_path(self) -> None:
        """Ensure the storage path is non-empty and writable.

        The directory is created if it does not exist.  Failure to create or
        write to the directory raises :class:`ConfigError`.
        """
        if not self.storage_path or not str(self.storage_path).strip():
            raise ConfigError("storage_path must be a non-empty string")

        # Defense-in-depth: reject literal Python-sentinel strings. These
        # almost always indicate an upstream bug where ``str(None)`` or
        # ``str(null_var)`` was used to build the path. Without this guard
        # the value validates fine and the server happily creates a
        # ``./None/`` (or ``./null/``) directory next to the cwd, scattering
        # data into the source tree. Observed in production 2026-04-19.
        if str(self.storage_path).strip().lower() in {"none", "null", "nil"}:
            raise ConfigError(
                f"storage_path is the literal sentinel string "
                f"{self.storage_path!r} — likely an upstream bug where a "
                f"None/null value was stringified into the config. Set "
                f"CLAUDE_MEMORY_PATH explicitly or remove the offending "
                f"override."
            )

        path = self.resolved_storage_path()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"storage_path {path!s} is not writable: {exc}") from exc

        if not os.access(path, os.W_OK):
            raise ConfigError(f"storage_path {path!s} is not writable")

    # -- Convenience ---------------------------------------------------

    def resolved_storage_path(self) -> Path:
        """Return :attr:`storage_path` with ``~`` and env vars expanded."""
        expanded = os.path.expanduser(os.path.expandvars(str(self.storage_path)))
        return Path(expanded).resolve()

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for serialisation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_file_data(path: Path) -> dict[str, Any]:
    """Read and parse the JSON configuration file.

    Returns an empty dict when ``path`` does not exist. Raises
    :class:`ConfigError` on malformed JSON or non-mapping top-level values.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object at the top level")
    return data


def _apply_profile(cfg: Config, profile_name: str) -> Config:
    """Return a new :class:`Config` with the profile's defaults applied."""
    if profile_name not in PLATFORM_PROFILES:
        raise ConfigError(
            f"Unknown platform_profile {profile_name!r}; must be one of {sorted(PLATFORM_PROFILES)}"
        )
    profile_defaults = PLATFORM_PROFILES[profile_name]
    return replace(cfg, platform_profile=profile_name, **profile_defaults)


_BOOL_FIELDS = {"enable_sqlite", "console_output"}
_VALID_FIELD_NAMES = {f.name for f in fields(Config)}


def _apply_overrides(cfg: Config, overrides: Mapping[str, Any], source: str) -> Config:
    """Return a new :class:`Config` with the given overrides applied.

    Unknown keys raise :class:`ConfigError` so typos aren't silently ignored.
    Values are coerced where appropriate (booleans from strings, etc.).
    """
    if not overrides:
        return cfg

    coerced: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in _VALID_FIELD_NAMES:
            raise ConfigError(f"Unknown configuration key {key!r} in {source}")
        if key in _BOOL_FIELDS:
            coerced[key] = _parse_bool(value)
        elif key == "log_level" and isinstance(value, str):
            coerced[key] = value.upper()
        elif key == "log_sample_rates" and isinstance(value, str):
            # Only the environment layer supplies this as a raw string
            # (a JSON object); the config file already parses to a dict.
            try:
                coerced[key] = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Invalid JSON for log_sample_rates in {source}: {exc}") from exc
        else:
            coerced[key] = value
    return replace(cfg, **coerced)
