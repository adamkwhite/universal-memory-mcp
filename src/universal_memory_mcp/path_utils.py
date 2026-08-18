"""Path resolution utilities for cross-platform compatibility.

This module provides utilities for resolving paths dynamically to ensure
the project works correctly regardless of installation location.

The path-resolution helpers below accept an optional :class:`~config.Config`
instance. When supplied, the helpers read paths from the config rather than
re-reading environment variables. When omitted, they call
``Config.load(validate=False)`` so existing call sites that rely on env-var
behaviour continue to work unchanged.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from .config import Config


def _resolve_config(config: "Config | None") -> "Config":
    """Return ``config`` when supplied, otherwise build one from env+file.

    ``validate=False`` is used because the path helpers are called from many
    lightweight contexts (logging setup, importers, scripts) where attempting
    to create the storage directory is unwanted side-effect.
    """
    if config is not None:
        return config
    # Local import keeps the module side-effect free at import time and
    # avoids a circular import between ``path_utils`` and ``config``.
    from .config import Config as _Config

    return _Config.load(validate=False)


def get_project_root() -> Path:
    """Find the project root directory by looking for markers.

    Searches up the directory tree from the current file location
    to find the project root, identified by the presence of certain
    marker files or directories.

    Returns:
        Path: The project root directory

    Raises:
        RuntimeError: If project root cannot be determined
    """
    current_path = Path(__file__).resolve()

    # Walk up the directory tree looking for project markers
    for parent in current_path.parents:
        # Check for common project root indicators
        if (parent / "pyproject.toml").exists():
            return parent
        if (parent / ".git").exists() and (parent / "src").exists():
            return parent
        if (parent / "setup.py").exists():
            return parent

    # If we can't find a marker, assume parent of src directory
    if current_path.parent.name == "src":
        return current_path.parent.parent

    raise RuntimeError("Could not determine project root directory")


def get_data_directory(config: "Config | None" = None) -> Path:
    """Get the data directory for storing conversations.

    The directory is determined by the following priority:
    1. ``config.storage_path`` (if ``config`` is provided)
    2. ``CLAUDE_MEMORY_PATH`` environment variable (resolved via
       :class:`~config.Config`)
    3. Default: ``~/claude-memory/``

    Args:
        config: Optional pre-loaded :class:`~config.Config` instance. When
            omitted, a fresh ``Config.load(validate=False)`` is used.

    Returns:
        Path: The data directory path
    """
    cfg = _resolve_config(config)
    return cfg.resolved_storage_path()


def get_log_directory(config: "Config | None" = None) -> Path:
    """Get the log directory for storing application logs.

    The directory is determined by:
    1. ``CLAUDE_MCP_LOG_FILE`` environment variable (if set, extract directory)
    2. Default: ``~/.claude-memory/logs/``

    ``CLAUDE_MCP_LOG_FILE`` is intentionally not part of :class:`~config.Config`
    yet, so this function still reads it directly. The ``config`` parameter is
    accepted for API symmetry and forward-compatibility.

    Args:
        config: Optional pre-loaded :class:`~config.Config` instance. Reserved
            for forward compatibility; currently unused.

    Returns:
        Path: The log directory path
    """
    # ``config`` is accepted for API symmetry; CLAUDE_MCP_LOG_FILE is not (yet)
    # part of Config so we still read it directly here.
    del config  # explicitly unused

    # Check if log file is specified
    log_file = os.environ.get("CLAUDE_MCP_LOG_FILE")
    if log_file:
        return Path(log_file).parent.expanduser().resolve()

    # Default to hidden directory in home
    return Path.home() / ".claude-memory" / "logs"


def get_default_log_file(config: "Config | None" = None) -> Path:
    """Get the default log file path.

    Args:
        config: Optional pre-loaded :class:`~config.Config` instance, forwarded
            to :func:`get_log_directory`.

    Returns:
        Path: The default log file path
    """
    return get_log_directory(config) / "claude-mcp.log"


def resolve_user_path(path: str) -> Path:
    """Resolve a user-provided path, expanding ~ and environment variables.

    Args:
        path: The path string to resolve

    Returns:
        Path: The resolved absolute path
    """
    # Expand user home directory
    expanded = os.path.expanduser(path)
    # Expand environment variables
    expanded = os.path.expandvars(expanded)
    # Convert to Path and resolve to absolute
    return Path(expanded).resolve()


def ensure_directory_exists(path: Path) -> None:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: The directory path to ensure exists

    Raises:
        OSError: If directory cannot be created
    """
    path.mkdir(parents=True, exist_ok=True)


def get_uv_command() -> str | None:
    """Find the uv command in PATH or common locations.

    Returns:
        Optional[str]: The path to uv command, or None if not found
    """
    import shutil

    # First check if it's in PATH
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    # Check common installation locations
    common_locations = [
        Path.home() / ".local" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
        Path("/opt/homebrew/bin/uv"),  # macOS with Homebrew on Apple Silicon
        Path("/usr/bin/uv"),
    ]

    for location in common_locations:
        if location.exists() and location.is_file():
            return str(location)

    return None
