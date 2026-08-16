[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=bugs)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=coverage)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=adamkwhite_claude-memory-mcp&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=adamkwhite_claude-memory-mcp)

# Universal Memory MCP — AI Conversation Memory

A Model Context Protocol (MCP) server that provides persistent, searchable conversation memory across multiple AI platforms. Store, search, and retrieve conversation history with fast full-text search powered by SQLite FTS5.

## Features

- 🔍 **Fast full-text search** via SQLite FTS5 with relevance ranking — ~10x faster than a linear scan ([measured](#performance))
- 🏷️ **Automatic topic extraction** — 574+ unique topics across 2,000+ associations
- 📊 **Weekly summaries** with insights and patterns
- 🗃️ **Organized file storage** by date and topic
- 🤖 **Multi-platform support** — Claude, ChatGPT, Cursor AI, and custom formats
- 🔌 **MCP integration** for Claude Desktop and Claude Code

## Quick Start

### Prerequisites

- Python 3.10+ (CI runs 3.14)
- Ubuntu/WSL environment recommended
- Claude Desktop (for MCP integration)

### Installation

#### Option 1: Install with Claude Code (Recommended)

**Quick Install** - Copy and paste this into Claude Code:

```bash
claude mcp add --transport stdio claude-memory -- sh -c "cd $HOME/Code/universal-memory-mcp && python3 src/server_fastmcp.py"
```

**Important**: Replace `$HOME/Code/universal-memory-mcp` with the actual path where you cloned this repository.

**Examples for different locations:**

```bash
# If cloned to ~/Code/universal-memory-mcp (default)
claude mcp add --transport stdio claude-memory -- sh -c "cd $HOME/Code/universal-memory-mcp && python3 src/server_fastmcp.py"

# If cloned to ~/projects/universal-memory-mcp
claude mcp add --transport stdio claude-memory -- sh -c "cd $HOME/projects/universal-memory-mcp && python3 src/server_fastmcp.py"

# If cloned to ~/dev/universal-memory-mcp
claude mcp add --transport stdio claude-memory -- sh -c "cd $HOME/dev/universal-memory-mcp && python3 src/server_fastmcp.py"
```

**What this does:**
- `--transport stdio`: Uses standard input/output for local processes
- `claude-memory`: Server identifier name
- `--`: Separates Claude CLI flags from the server command
- `sh -c "cd ... && python3 ..."`: Changes to project directory before running server

This adds the MCP server to your Claude Desktop configuration automatically.

Documentation: https://code.claude.com/docs/en/mcp

#### Option 2: Manual Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/adamkwhite/universal-memory-mcp.git
   cd universal-memory-mcp
   ```

2. **Set up virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   ```

   This installs the package in editable mode along with all required dependencies:
   - `mcp[cli]>=1.9.2` - Model Context Protocol
   - `jsonschema>=4.0.0` - JSON schema validation
   - `aiofiles>=24.1.0` - Async file operations

4. **Test the system:**
   ```bash
   python3 tests/validate_system.py
   ```

### Basic Usage

#### MCP Server Mode
```bash
# Run as MCP server (from project root)
python3 src/server_fastmcp.py

# Or from src directory
cd src && python3 server_fastmcp.py
```

#### Bulk Import
```bash
# Import conversations from JSON export
python3 scripts/bulk_import_enhanced.py your_conversations.json
```

## MCP Tools

### `search_conversations(query, limit=5)`
Full-text search across all stored conversations with relevance ranking. Query text is treated as literal Unicode terms, so punctuation and FTS5 operators do not change the query semantics. Results include conversation IDs for exact retrieval.

### `get_conversation(conversation_id, max_chars=12000)`
Retrieve a stored conversation by an ID returned from a search tool. Content is read from the authoritative JSON store and truncated to `max_chars` to protect the model context. `max_chars` must be between 1 and 50,000.

### `search_by_topic(topic, limit=10)`
Find conversations tagged with a specific topic.

### `add_conversation(content, title, date)`
Store a new conversation with automatic topic extraction and FTS indexing.

### `generate_weekly_summary(week_offset=0)`
Generate insights and patterns from recent conversations.

### `get_search_stats()`
View search engine statistics — index size, topic counts, and engine status.

### `update_conversation(conversation_id, content=None, title=None, add_tags=None, remove_tags=None, set_tags=None, conversation_type=None, session_id=None, user_id=None, change_note=None, record_audit=True)`
Update fields on an existing conversation in place. Pass `conversation_id` plus any subset of fields to change; unspecified fields are left alone. By default, the first line of stored content is rewritten with a self-documenting audit line — `[update <iso-timestamp> — <change_note>]` — chained across repeated updates. If `change_note` is omitted, it is derived from the changed fields.

Set `record_audit=False` only for authoritative imports whose content must remain an exact replica of the source system. Normal interactive updates should retain the default audit record.

Tag operations: `set_tags` replaces the full tag list and is mutually exclusive with `add_tags`/`remove_tags` (pass `set_tags=[]` to clear all tags); `add_tags`/`remove_tags` mutate the existing list.

Returns a status string. On success: `Status: success` plus a summary message and, when enabled, the audit line. On failure (malformed ID, conversation not found, no changes provided, conflicting tag ops, or an I/O error): `Status: error` plus a message describing the problem.

### `search_by_tag(tag, limit=10)`
Find conversations tagged with a specific tag — a universal metadata field populated by importers or set via `update_conversation` (e.g. `starred`, `archived`, `workspace:my-project`). Exact match, case-sensitive. Requires SQLite FTS to be enabled; without it, returns an error message.

### `search_by_session_id(session_id, limit=10)`
Find all conversations sharing a `session_id`, useful for reconstructing a multi-turn session that spans several stored conversation records (e.g. a Cursor working session, a Claude thread continued across days). Results are sorted chronologically (oldest first). Requires SQLite FTS to be enabled; without it, returns an error message.

### `search_by_conversation_type(conversation_type, limit=10)`
Find conversations by `conversation_type` (e.g. `chat`, `code`, `analysis`). Exact match, most recent first. Requires SQLite FTS to be enabled; without it, returns an error message.

## Architecture

```
~/claude-memory/
├── conversations/
│   ├── 2025/
│   │   └── 06-june/
│   │       └── 2025-06-01_topic-name.md
│   ├── index.json          # Search index
│   └── topics.json         # Topic frequency
└── summaries/
    └── weekly/
        └── week-2025-06-01.md
```

## Configuration

### Claude Desktop Integration

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "claude-memory": {
      "command": "python",
      "args": ["/absolute/path/to/universal-memory-mcp/src/server_fastmcp.py"],
      "cwd": "/absolute/path/to/universal-memory-mcp"
    }
  }
}
```

### Configuration Precedence

Settings are resolved by `src/config.py`'s `Config.load()`, consulted in this
order (highest wins):

1. **Environment variables** (`CLAUDE_MEMORY_*` / `CLAUDE_MCP_*`)
2. **Config file** (default `~/.claude-memory/config.json`)
3. **Platform profile** (`default`, `claude`, `chatgpt`, or `cursor` — selects
   a partial set of defaults, e.g. `log_format`)
4. **Built-in defaults**

### Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `CLAUDE_MEMORY_PATH` | Conversation storage directory | `~/claude-memory` |
| `CLAUDE_MEMORY_DISABLE_SQLITE` | Set `true` to disable SQLite FTS and fall back to JSON linear search. Inverse alias of `CLAUDE_MCP_ENABLE_SQLITE`; wins if both are set. | unset (SQLite enabled) |
| `CLAUDE_MCP_LOG_FORMAT` | Log output format: `text` or `json` | `text` |
| `CLAUDE_MCP_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `CLAUDE_MCP_ENABLE_SQLITE` | Enable/disable SQLite FTS search (boolean: `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`) | `true` |
| `CLAUDE_MCP_CONSOLE_OUTPUT` | Echo logs to stdout in addition to the log file (boolean) | `false` |
| `CLAUDE_MCP_PLATFORM_PROFILE` | Platform profile to apply: `default`, `claude`, `chatgpt`, or `cursor` | `default` |

When `CLAUDE_MEMORY_PATH` is set explicitly, the path may live outside your
home directory (e.g. a separate data drive on Windows: `D:\claude-memory`).
Paths that are *not* explicitly configured are still restricted to the home
or project directory for safety.

### Config File

As an alternative to environment variables, settings can be placed in
`~/.claude-memory/config.json`. The file is optional — a missing file falls
back to platform-profile/built-in defaults. Example:

```json
{
  "storage_path": "~/claude-memory",
  "log_format": "json",
  "log_level": "INFO",
  "enable_sqlite": true,
  "console_output": false,
  "platform_profile": "default"
}
```

Unknown keys in the file raise a configuration error rather than being
silently ignored. Environment variables still override anything set here.

### Disabling SQLite

SQLite FTS5 search is enabled by default. On platforms where SQLite/FTS5 is
unavailable (e.g. some Windows Python builds), disable it to fall back to
JSON-based linear search:
```bash
export CLAUDE_MEMORY_DISABLE_SQLITE=true
```

### Logging Configuration

#### Log Format

Switch between human-readable text logs (default) and structured JSON logs for production:

```bash
# JSON format (for production log aggregation)
export CLAUDE_MCP_LOG_FORMAT=json

# Text format (default, for development)
export CLAUDE_MCP_LOG_FORMAT=text
```

**JSON Log Example:**
```json
{
  "timestamp": "2025-01-15T10:30:45",
  "level": "INFO",
  "logger": "claude_memory_mcp",
  "function": "add_conversation",
  "line": 145,
  "message": "Added conversation successfully",
  "context": {
    "type": "performance",
    "duration_seconds": 0.045,
    "conversation_id": "conv_abc123"
  }
}
```

JSON logging is ideal for:
- Production deployments with log aggregation (Datadog, ELK, CloudWatch)
- Automated monitoring and alerting
- Structured log analysis and querying
- Performance tracking and debugging

See `docs/json-logging.md` for detailed JSON logging documentation.

## File Structure

```
universal-memory-mcp/
├── src/
│   ├── server_fastmcp.py       # Main MCP server
│   ├── conversation_memory.py  # Core memory engine + SQLite FTS5
│   ├── format_detector.py      # Auto-detect AI platform format
│   ├── validators.py           # Input validation
│   ├── logging_config.py       # Structured logging (text/JSON)
│   ├── importers/              # Platform-specific importers
│   │   ├── chatgpt_importer.py
│   │   ├── claude_importer.py
│   │   ├── cursor_importer.py
│   │   └── generic_importer.py
│   └── schemas/                # JSON schema validation
├── tests/                      # 435 tests, 98.68% coverage
├── data/                       # Consolidated app data
├── scripts/                    # Import and utility scripts
└── docs/                       # Documentation
```

## Performance

`scripts/benchmark_search.py` was broken (unawaited async calls, measuring
coroutine construction instead of real search time) from October 2025 until
this was found and fixed. The previous numbers below were never actually
measured and have been replaced with real ones. Reproduce with:

```bash
python scripts/generate_test_data.py --conversations 159
python scripts/benchmark_search.py --storage-path ~/claude-memory-test --iterations 5
```

Measured on a 159-conversation / 7.7MB local dataset (WSL2, Python 3.12) —
treat as order-of-magnitude, not a precise SLA, results vary by machine:

- **Search Speed (SQLite FTS5)**: mean 15–18ms, median 10–13ms per query, range 0.5–82ms across 12 query types (was claimed 0.2–0.5ms; that figure was never measured)
- **Search vs. linear JSON scan**: SQLite FTS5 is ~10x faster (mean 14.7ms vs 154.2ms; median 10.5ms vs 152.0ms) — the old "4.4x" claim had the right direction but was also never actually measured
- **Topic Search**: mean 3.4ms, median 2.5ms (was claimed 0.3–0.4ms; that figure was never measured)
- **Write Speed**: mean 14ms, median 14ms per ~49KB conversation, SQLite indexing included (was claimed ~33ms; that figure was never measured)
- **Capacity**: 371 conversations in production use over 10 months
- **Test Coverage**: 98.68% (435 tests) — 0 code smells, 0 security hotspots (SonarCloud verified)

*Last benchmarked: July 2026 | [Detailed Report](docs/PERFORMANCE_BENCHMARKS.md)*

**Note for Developers**: Performance benchmarks create a `~/claude-memory-test` directory for isolated testing. Normal MCP usage only uses `~/claude-memory/`. If you see `~/claude-memory-test`, it can be safely deleted.

## Search Examples

```python
# Technical topics
search_conversations("terraform azure")
search_conversations("mcp server setup")
search_conversations("python debugging")

# Project discussions
search_conversations("interview preparation")
search_conversations("product management")
search_conversations("architecture decisions")

# Specific problems
search_conversations("dependency issues")
search_conversations("authentication error")
search_conversations("deployment configuration")
```

## Development

### Adding New Features

1. **Topic Extraction**: Modify `_extract_topics()` in `ConversationMemoryServer`
2. **Search Algorithm**: Enhance `search_conversations()` method
3. **Summary Generation**: Improve `generate_weekly_summary()` logic

### Testing

```bash
# Run validation suite
python3 tests/validate_system.py

# Run full test suite with coverage
python3 -m pytest tests/ --cov=src --cov-report=term

# Import test data
python3 scripts/bulk_import_enhanced.py test_data.json --dry-run
```

**Test Data Storage (Developers Only)**: If you run performance benchmarks or test data generators, they create a `~/claude-memory-test` directory to isolate test data from your production `~/claude-memory` directory. **This is only for development/testing** - normal MCP usage does not create this directory.

To clean up test data after running benchmarks:

```bash
rm -rf ~/claude-memory-test
```

Or using the Makefile cleanup target:

```bash
make clean-test-data
```

## Troubleshooting

### Common Issues

**MCP Import Errors:**
```bash
pip install mcp[cli]  # Include CLI extras
```

**Search Returns No Results:**
- Check conversation indexing: `ls ~/claude-memory/conversations/index.json`
- Verify file permissions
- Run validation: `python3 tests/validate_system.py`

**Weekly Summary Timezone Errors:**
- Ensure all datetime objects use consistent timezone handling
- Recent fix addresses timezone-aware vs naive comparison

### System Requirements

- **Python**: 3.10+ (CI runs 3.14)
- **Disk Space**: ~10MB per 100 conversations
- **Memory**: <100MB RAM usage
- **OS**: Linux/WSL and Windows are both verified in CI on every PR (Ubuntu + `windows-latest`).
  macOS is expected to work but is not covered by a CI runner.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit changes: `git commit -am 'Add feature'`
4. Push to branch: `git push origin feature-name`
5. Submit a Pull Request

**A note for fork PRs:** GitHub does not give forks access to repository secrets, so the
SonarCloud scan and the performance-results comment are **skipped** on your PR rather than run.
That is expected and is not something you can or should fix — the test suite, linting, CodeQL and
the Windows run all still execute normally, and coverage on your changes is checked when the
branch lands on `main`. If you see those two skipped, nothing is wrong.

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Built with [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol/python-sdk)
- Designed for [Claude Desktop](https://claude.ai/desktop) integration
- Inspired by the need for persistent conversation context

---

**Status**: Production ready ✅
**Last Updated**: April 2026
**Version**: 2.0.0
