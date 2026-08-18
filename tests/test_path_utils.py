"""Tests for path_utils module."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import without_app_env  # noqa: E402

from universal_memory_mcp.config import Config  # noqa: E402
from universal_memory_mcp.path_utils import (  # noqa: E402
    _resolve_config,
    ensure_directory_exists,
    get_data_directory,
    get_default_log_file,
    get_log_directory,
    get_project_root,
    get_uv_command,
    resolve_user_path,
)


class TestGetProjectRoot:
    """Test project root detection."""

    def test_finds_project_root_with_pyproject_toml(self):
        """Test finding project root by pyproject.toml."""
        # This should work in the actual project
        root = get_project_root()
        assert root.is_dir()
        assert (root / "pyproject.toml").exists() or (root / ".git").exists()

    @patch("universal_memory_mcp.path_utils.Path")
    def test_finds_project_root_with_git(self, mock_path):
        """Test finding project root by .git directory."""
        # Mock the file structure
        mock_file = MagicMock()
        mock_parent1 = MagicMock()
        mock_parent2 = MagicMock()

        mock_path.return_value.resolve.return_value = mock_file
        mock_file.parents = [mock_parent1, mock_parent2]

        # First parent doesn't have markers
        mock_parent1.__truediv__.return_value.exists.return_value = False

        # Second parent has .git and src
        git_mock = MagicMock()
        src_mock = MagicMock()
        git_mock.exists.return_value = True
        src_mock.exists.return_value = True

        def mock_truediv(item):
            if item == ".git":
                return git_mock
            elif item == "src":
                return src_mock
            else:
                mock = MagicMock()
                mock.exists.return_value = False
                return mock

        mock_parent2.__truediv__.side_effect = mock_truediv

        # Should return the second parent
        result = get_project_root()
        assert result == mock_parent2


class TestGetDataDirectory:
    """Test data directory resolution."""

    def test_default_data_directory(self):
        """Test default data directory location."""
        with without_app_env():
            data_dir = get_data_directory()
            assert data_dir == Path.home() / "claude-memory"

    def test_data_directory_from_env(self):
        """Test data directory from environment variable."""
        test_path = "/custom/data/path"
        with patch.dict(os.environ, {"CLAUDE_MEMORY_PATH": test_path}):
            data_dir = get_data_directory()
            assert str(data_dir).endswith("path")

    def test_data_directory_expands_user(self):
        """Test data directory expands ~ in path."""
        with patch.dict(os.environ, {"CLAUDE_MEMORY_PATH": "~/custom/memory"}):
            data_dir = get_data_directory()
            assert str(data_dir).startswith(str(Path.home()))
            # Compare path components, not a "/"-joined substring: str(Path)
            # uses the platform separator, so the literal never matches on
            # Windows even when the path is correct.
            assert data_dir.parts[-2:] == ("custom", "memory")


class TestGetLogDirectory:
    """Test log directory resolution."""

    def test_default_log_directory(self):
        """Test default log directory location."""
        with without_app_env():
            log_dir = get_log_directory()
            assert log_dir == Path.home() / ".claude-memory" / "logs"

    def test_log_directory_from_log_file_env(self):
        """Test log directory extracted from log file path."""
        test_path = "/var/log/claude/app.log"
        with patch.dict(os.environ, {"CLAUDE_MCP_LOG_FILE": test_path}):
            log_dir = get_log_directory()
            assert str(log_dir).endswith("claude")

    def test_log_directory_expands_user_in_file_path(self):
        """Test log directory expands ~ in file path."""
        with patch.dict(os.environ, {"CLAUDE_MCP_LOG_FILE": "~/logs/claude.log"}):
            log_dir = get_log_directory()
            assert str(log_dir).startswith(str(Path.home()))
            assert str(log_dir).endswith("logs")


class TestGetDefaultLogFile:
    """Test default log file path."""

    def test_default_log_file_path(self):
        """Test default log file uses log directory."""
        with without_app_env():
            log_file = get_default_log_file()
            assert log_file.name == "claude-mcp.log"
            assert log_file.parent == Path.home() / ".claude-memory" / "logs"


class TestResolveUserPath:
    """Test user path resolution."""

    def test_resolve_absolute_path(self):
        """Test resolving absolute path."""
        test_path = "/tmp/test/path"
        resolved = resolve_user_path(test_path)
        assert resolved.is_absolute()
        assert str(resolved).endswith("path")

    def test_resolve_home_path(self):
        """Test resolving path with ~."""
        resolved = resolve_user_path("~/test/path")
        assert resolved.is_absolute()
        assert str(resolved).startswith(str(Path.home()))

    @patch.dict(os.environ, {"TEST_VAR": "/custom/location"})
    def test_resolve_env_var_path(self):
        """Test resolving path with environment variable."""
        resolved = resolve_user_path("$TEST_VAR/subdir")
        assert resolved.is_absolute()
        assert resolved.parts[-3:] == ("custom", "location", "subdir")


class TestEnsureDirectoryExists:
    """Test directory creation."""

    def test_create_directory(self, tmp_path):
        """Test creating a new directory."""
        test_dir = tmp_path / "new" / "nested" / "dir"
        assert not test_dir.exists()

        ensure_directory_exists(test_dir)
        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_existing_directory(self, tmp_path):
        """Test with existing directory."""
        test_dir = tmp_path / "existing"
        test_dir.mkdir()

        # Should not raise error
        ensure_directory_exists(test_dir)
        assert test_dir.exists()


class TestGetUvCommand:
    """Test uv command detection."""

    @patch("shutil.which")
    def test_find_uv_in_path(self, mock_which):
        """Test finding uv in PATH."""
        mock_which.return_value = "/usr/bin/uv"
        result = get_uv_command()
        assert result == "/usr/bin/uv"
        mock_which.assert_called_once_with("uv")

    @patch("shutil.which")
    @patch("universal_memory_mcp.path_utils.Path")
    def test_find_uv_in_common_locations(self, mock_path_class, mock_which):
        """Test finding uv in common locations when not in PATH."""
        mock_which.return_value = None

        # Mock Path instances
        paths = []
        for _ in range(4):  # Number of common locations
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path.is_file.return_value = False
            paths.append(mock_path)

        # Make the second location exist
        paths[1].exists.return_value = True
        paths[1].is_file.return_value = True
        paths[1].__str__.return_value = "/usr/local/bin/uv"

        # Mock Path class to return our mocked paths
        mock_path_class.side_effect = paths
        mock_path_class.home.return_value = Path("/home/test")

        result = get_uv_command()
        assert result == "/usr/local/bin/uv"

    @patch("shutil.which")
    @patch("universal_memory_mcp.path_utils.Path")
    def test_uv_not_found(self, mock_path_class, mock_which):
        """Test when uv is not found anywhere."""
        mock_which.return_value = None

        # Mock all paths to not exist
        def mock_path(*args):
            mock = MagicMock()
            mock.exists.return_value = False
            return mock

        mock_path_class.side_effect = mock_path
        mock_path_class.home.return_value = Path("/home/test")

        result = get_uv_command()
        assert result is None


class TestConfigWiring:
    """Tests for the new ``config`` parameter on path-resolution helpers."""

    def test_resolve_config_returns_supplied_instance(self, tmp_path):
        """An explicit Config is returned unchanged (no env/file lookup)."""
        cfg = Config(storage_path=str(tmp_path))
        assert _resolve_config(cfg) is cfg

    def test_resolve_config_loads_when_none(self, monkeypatch, tmp_path):
        """Without an explicit config, env-driven Config.load is used."""
        monkeypatch.setenv("CLAUDE_MEMORY_PATH", str(tmp_path))
        # validate=False is used internally so this should never raise even
        # when the storage path isn't writable.
        cfg = _resolve_config(None)
        assert isinstance(cfg, Config)
        assert cfg.resolved_storage_path() == tmp_path.resolve()

    def test_get_data_directory_uses_supplied_config(self, tmp_path):
        """``get_data_directory`` should respect an explicit Config."""
        cfg = Config(storage_path=str(tmp_path))
        assert get_data_directory(cfg) == tmp_path.resolve()

    def test_get_default_log_file_accepts_config(self, tmp_path):
        """``get_default_log_file`` should accept a Config without raising."""
        cfg = Config(storage_path=str(tmp_path))
        # Even though Config doesn't (yet) drive the log-file location, the
        # helper must not break when one is supplied.
        log_file = get_default_log_file(cfg)
        assert log_file.name == "claude-mcp.log"

    def test_get_log_directory_accepts_config(self, tmp_path):
        """``get_log_directory`` should accept a Config without raising."""
        cfg = Config(storage_path=str(tmp_path))
        # Same as above: parameter is reserved for forward-compat.
        log_dir = get_log_directory(cfg)
        assert log_dir.name == "logs"
