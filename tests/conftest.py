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
