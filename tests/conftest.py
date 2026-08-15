"""Suite-wide storage isolation.

``src/server_fastmcp.py`` builds its module-level ``memory_server`` singleton
at import time, and several test modules call the MCP tool functions
(``server_fastmcp.add_conversation`` and friends) directly rather than through
a fixture-built server. Those calls hit whatever store the singleton was
constructed with, which — with no override — is the user's real
``~/claude-memory``.

That is not theoretical: the live store had accumulated 611 junk rows
("MCP Add Test" x402, "Error Test" x209) out of 1381, written by ordinary
suite runs.

The redirect has to happen at conftest *module* scope, not in a fixture:
pytest imports conftest before it imports any test module, and the test
module's own ``import server_fastmcp`` is what constructs the singleton. An
autouse fixture — even session-scoped — runs after collection and is too late.

``CLAUDE_MEMORY_PATH`` is the highest-precedence storage input (env > config
file > profile > default, see ``src/config.py``), so setting it here wins over
any real config the developer has. Tests that exercise path/config precedence
themselves clear or patch the environment explicitly and are unaffected.
"""

import atexit
import os
import shutil
import tempfile

# ponytail: mkdtemp matches the temp-dir pattern already used by the fixtures
# in test_fastmcp_coverage.py; it honours TMPDIR if a runner needs to relocate.
_TEST_STORAGE_PATH = tempfile.mkdtemp(prefix="claude_memory_suite_")

os.environ["CLAUDE_MEMORY_PATH"] = _TEST_STORAGE_PATH
atexit.register(shutil.rmtree, _TEST_STORAGE_PATH, ignore_errors=True)


import logging  # noqa: E402  (module-level env setup above must run first)
from contextlib import contextmanager  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _close_file_log_handlers():
    """Close file-backed logging handlers after every test.

    ``logging`` keeps a handler (and its open file) alive on the logger object
    for the life of the process, so a test that points a ``FileHandler`` at a
    ``tmp_path`` leaves that file open once the test returns. POSIX lets the
    fixture unlink it anyway; Windows raises ``[WinError 32] The process
    cannot access the file because it is being used by another process`` and
    turns a passing test into a teardown error.

    Only ``FileHandler`` instances are touched. pytest's own capture handlers
    (``LogCaptureHandler``, ``_LiveLoggingNullHandler``) are not file-backed,
    and closing those would break ``caplog`` for subsequent tests.
    """
    yield

    loggers = [logging.getLogger()]
    loggers += [
        obj for obj in logging.root.manager.loggerDict.values() if isinstance(obj, logging.Logger)
    ]
    for logger in loggers:
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
                handler.close()


@contextmanager
def without_app_env():
    """Remove this project's env vars, leaving the rest of the environment.

    Replaces ``patch.dict(os.environ, {}, clear=True)``. What those call sites
    mean is "no CLAUDE_* override is set" — but wiping the whole environment
    also removes ``USERPROFILE``/``HOMEDRIVE``/``HOMEPATH``, which is how
    Windows resolves ``~``. ``Path.home()`` then raises ``RuntimeError: Could
    not determine home directory``. POSIX never notices because
    ``os.path.expanduser`` falls back to the ``pwd`` database.

    The variable list comes from ``Config.ENV_MAPPING`` rather than a literal,
    so adding a config field cannot silently leave a variable set here.
    """
    with patch.dict(os.environ):
        for var in (*Config.ENV_MAPPING.values(), "CLAUDE_MCP_LOG_FILE"):
            os.environ.pop(var, None)
        yield


#: Skip marker for tests that assert on POSIX file-mode bits.
#:
#: These call ``chmod(0o000)`` / ``chmod(0o444)`` and then assert the operation
#: fails. On Windows ``os.chmod`` only toggles the read-only attribute, and
#: never for directories, so the "unreadable" file reads fine and the
#: "read-only" directory accepts writes — the test then fails with
#: ``DID NOT RAISE`` or an inverted assertion. The behaviour under test is real
#: on POSIX and simply has no Windows equivalent to assert, so these are
#: skipped rather than rewritten.
requires_posix_permissions = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX file-mode bits; chmod on Windows only toggles the read-only attribute",
)


#: Skip marker for tests that exercise the ``HOME``-based log-file fallback.
#:
#: ``logging_config.init_default_logging`` falls back to
#: ``os.getenv("HOME")`` when ``get_default_log_file`` is unavailable, and
#: these tests assert the POSIX paths that produces. Windows resolves ``~``
#: from ``USERPROFILE`` (or ``HOMEDRIVE`` + ``HOMEPATH``) and does not consult
#: ``HOME`` at all, so setting it changes nothing and the branch is
#: unreachable there. The fallback being POSIX-only is a real (minor) gap in
#: src -- tracked in todos.md -- not something these tests can assert around.
requires_posix_home = pytest.mark.skipif(
    os.name == "nt",
    reason="HOME-based log path fallback; Windows resolves ~ from USERPROFILE, not HOME",
)
