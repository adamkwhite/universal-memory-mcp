# Universal Memory MCP - Universal AI Memory System

## Project Overview

**Claude Memory MCP** is a universal conversation memory system that provides persistent storage and intelligent search across multiple AI platforms. Originally designed for Claude, it now supports ChatGPT, Cursor AI, and custom formats through an extensible architecture.

## Current Status (August 15, 2026)

**Branch**: `main`
**Recent Work**: First outside contribution (#200, open) exposed a fork-CI gap and a Windows
portability gap; #201–#206 closed both — see `todos.md`. Before that: store-integrity series
(#190–#196) and the rename to `universal-memory-mcp` (#197).
**Test Coverage**: 901 passed, 1 skipped (local suite, verified `pytest -q` August 15 2026); 880 passed / 10 skipped on `windows-latest` in CI (the 14 are marked POSIX-only, see the quality-gate section); 88% overall coverage (SonarCloud); ≥80% coverage required on new code

> Local benchmark tests need a generated dataset: `python scripts/generate_test_data.py --conversations 500`.
> Without it, 6 `test_performance_benchmarks.py::test_search_performance_scaling` cases fail locally with
> "No conversation files copied". CI generates it in `performance.yml`, and `build.yml` `--ignore`s that file,
> so this is a local-only papercut and not a regression.
**Code Quality**: 9 code smells, 0 security hotspots (SonarCloud, verified via API); quality gate status OK
**Architecture**: Importer/Exporter mirror pattern (`src/importers/` ↔ `src/exporters/`); `src/config.py` is the single source of configuration truth (env > file > profile > default)

### Naming: the project was renamed, the runtime identifiers were not (#197)

The repo, package and logger hierarchy are `universal-memory-mcp` / `universal_memory_mcp`.
**Everything a running install depends on deliberately still says `claude`**, and must stay that
way — each of these orphans working state if "tidied up" for consistency:

| identifier | why it must not change |
|---|---|
| `~/claude-memory/`, `~/.claude-memory/` | orphans every existing install's conversations |
| `CLAUDE_MEMORY_PATH`, `CLAUDE_MEMORY_DISABLE_SQLITE`, `CLAUDE_MCP_*` | existing setups go dead |
| `FastMCP("claude-memory")` | the key in users' `claude_desktop_config.json` |
| `sonar.projectKey=adamkwhite_claude-memory-mcp` + README badge URLs | SonarCloud-side identifier — editing it orphans the project and loses all history |
| `claude-memory-mcp-venv` | the directory exists under that name; a venv cannot be moved without breaking the absolute paths inside its scripts |

A find-and-replace across the repo will hit the last two. Don't.

### Store integrity — the bug class to watch for (August 2026)

Three separate bugs in this repo were the same shape: **two stores agreeing on a total while
disagreeing on contents.** Count comparisons cannot detect that, which is why each survived for
months. When you touch anything that keeps two stores aligned, compare identities, not counts.

- **#190** — `conversations_fts` is an external-content FTS5 table (`content='conversations'`), so
  rowid alignment is the whole contract. Broken triggers plus `INSERT OR REPLACE` leaked one
  orphaned index entry per re-saved conversation, and any `MATCH` hitting an orphan failed the
  read-back — breaking **all** content search while tag/topic search kept working. Note the trap:
  `PRAGMA integrity_check` returns `ok`, because the database file was never corrupt.
- **#193** — `_sync_index_from_files` returned early when file count == index count, so swapping one
  conversation for another left the replacement unindexed.
- **#194** — `check_consistency()` now set-differences files / `index.json` / SQLite and reports
  drift through `get_search_stats`. **Read-only by design**: never wire index repair into startup;
  a mis-set `CLAUDE_MEMORY_PATH` or unmounted directory makes every file look missing.

Related: `migrate_to_sqlite.py::verify_migration` still compares counts and can report a drifted
store as healthy. Don't trust it.

**Tests must never touch the real store.** `tests/conftest.py` redirects `CLAUDE_MEMORY_PATH` to a
temp dir at *module* scope — not in a fixture, because `server_fastmcp` builds its `memory_server`
singleton at import time, before any fixture runs. Before #191 every suite run wrote live
conversations into `~/claude-memory` (611 junk rows out of 1381). `tests/test_storage_isolation.py`
guards this; if it fails, stop and fix it rather than working around it.

### Windows is now a supported, tested platform (#202–#206, August 2026)

`build.yml` runs the suite on `windows-latest` and it is a **required check**. Before assuming a
Windows failure is environmental, read this — the first run found a real bug in `src/`.

- **Connections and file handles must be closed explicitly, never left to GC.**
  `with sqlite3.connect(...) as conn` manages the **transaction**, not the connection: it commits
  and leaves the handle open. All 11 call sites in `search_database.py` used that form and the
  module had zero `.close()` calls, leaking one handle per operation (measured: 11 after five
  searches, 0 only after `gc.collect()`). Linux hides this entirely because an open file can still
  be unlinked; Windows refuses the delete. Use `SearchDatabase._connect()`, and `contextlib.closing`
  in tests. `tests/test_sqlite_connection_lifecycle.py` asserts handle counts directly, so it fails
  on Linux too if this regresses.
- **Name `encoding="utf-8"` on every text-mode `open()`/`write_text()`/`read_text()`.** The default
  is UTF-8 on Linux and the ANSI codepage on Windows. `tests/test_source_encoding_invariant.py`
  enforces this across `src/`; `tests/` was swept to match in #205.
- **`patch.dict(os.environ, {}, clear=True)` breaks `Path.home()` on Windows** — it removes
  `USERPROFILE`/`HOMEDRIVE`/`HOMEPATH`. Use `without_app_env()` from `tests/conftest.py`, which
  pops only this project's variables and derives the list from `Config.ENV_MAPPING`.
- **Two markers exist for genuinely platform-specific behaviour**, both in `tests/conftest.py`:
  `requires_posix_permissions` (Windows `chmod` only toggles the read-only attribute, never for
  directories). Reach for it only when the behaviour under test has no Windows equivalent — not
  to silence a portable bug. A second marker, `requires_posix_home`, was deleted in #209: it
  existed because `init_default_logging` built its fallback path from `os.getenv("HOME")`, which
  is a **src** portability bug, not a test constraint. Fixing src let four tests run on both
  platforms instead of being skipped on one. When a marker starts covering for src, delete the
  marker.
- **To point `~` somewhere in a test, set `HOME_ENV_VAR` from `tests/conftest.py`**, not a literal
  `"HOME"` — Windows resolves `~` from `USERPROFILE` (then `HOMEDRIVE` + `HOMEPATH`) and never
  reads `HOME`, so a hard-coded `HOME` asserts nothing there.
- **Don't assert on `"a/b" in str(path)`** — compare `Path.parts`. And compare `Path.resolve()` on
  both sides of a path equality: Windows `tmp_path` arrives as the 8.3 short name (`RUNNER~1`)
  while code under test records the long form (`runneradmin`).
- **Resolve the home directory with `Path.home()`, never `os.getenv("HOME")`.** POSIX falls back
  to the pwd database when `HOME` is unset; Windows never sets `HOME` at all. Fixed in #209 —
  `init_default_logging`'s fallback was dead code on Windows, silently leaving an install with no
  log file. `Path.home()` raises `RuntimeError` when it cannot resolve, so suppress that where
  "no path" is an acceptable outcome.

### Recent Major Implementations
- ✅ **Centralized Configuration** (PRs #111, #116): `src/config.py` `Config` dataclass with env/file/profile precedence and validation, wired into `server_fastmcp.py`/`logging_config.py`/`path_utils.py`. Replaces scattered `os.getenv()` reads.
- ✅ **Export Module** (PR #115): `src/exporters/` mirrors `src/importers/` — `BaseExporter`, `JsonExporter`, `ChatgptExporter`, `Filters` dataclass. Reuses `chatgpt_schema` for output validation. Lossy on tree branching (linear chains only).
- ✅ **Universal Metadata Fields** (PR #114): `session_id`, `user_id`, `tags`, `conversation_type`, `custom_fields` plumbed through `BaseImporter.create_universal_conversation()` and populated by all four importers from real source data.
- ✅ **Bulk Import Auto-Detect** (PR #112): `bulk_import_enhanced.py` uses `FormatDetector` to dispatch to platform importers; falls back to legacy extractor below confidence threshold. Fixed a latent broken import.
- ✅ **Async File I/O Migration**: Converted all synchronous file operations to async using aiofiles
- ✅ **SonarCloud Quality Gates**: All code quality issues resolved, 80%+ coverage on new code
- ✅ **Universal Memory Framework**: Complete architecture for multi-platform support
- ✅ **ChatGPT Integration**: Production-ready with real export validation and jsonschema validation
- ✅ **SQLite FTS Search**: ~10x faster than linear JSON scan (measured, see README Performance section; the previously-claimed 4.4x was never actually measured — `scripts/benchmark_search.py` had unawaited async calls that silently timed coroutine construction instead of search, fixed in `fix/performance-truth`)
- ✅ **CI/CD Pipeline**: GitHub Actions with SonarCloud integration fully operational

### Open architectural follow-ups (see `todos.md` for full list)
- Round-trip-able ChatGPT export — current exporter emits `mapping` structure but importer expects flat `messages` list (asymmetric).

(Metadata-field FTS indexing — `tags`/`session_id`/`conversation_type` in `src/search_database.py` — was completed in PR #118. The project-wide mypy hook fix, dual `src.foo` ↔ `foo` import naming, was completed in PRs #156/#175 — the canonical bare-import migration; the hook now passes across all 68 files. Both previously listed here as open.)

## Technology Stack

**Core Technologies:**
- **Python 3.10+**: Primary development language (`requires-python` floor; CI runs 3.14 — see Python Version Management)
- **FastMCP**: Model Context Protocol server implementation
- **aiofiles**: Async file I/O operations for proper async/await compliance
- **SQLite FTS5**: Full-text search with relevance scoring
- **JSON Schema**: Platform format validation with jsonschema library
- **pytest**: Comprehensive testing framework with 901 tests (900 passed, 1 skipped, verified `pytest -q` August 15 2026)

**AI Platform Support:**
- **ChatGPT**: Complete OpenAI export format support
- **Cursor AI**: Session-based development context imports
- **Claude**: Multiple variants (web, desktop, memory)
- **Generic**: Flexible parsing for custom formats

**Quality Assurance:**
- **SonarCloud**: Code quality analysis with public dashboard visibility
- **GitHub Actions**: CI/CD with quality gate enforcement
- **88.1% Test Coverage**: verified via SonarCloud API, July 2026

## Project Structure

**As of June 2025, the project uses a consolidated data/ directory structure:**

```
universal-memory-mcp/
├── data/                    # Consolidated application data
│   ├── conversations/       # Local conversation storage
│   ├── summaries/          # Weekly summary storage
│   └── config/             # Project configuration files
├── pyproject.toml          # Regular file (no longer a symlink)
├── pytest.ini             # Symlink to data/config/pytest.ini
├── src/                    # Source code
├── tests/                  # Test suite
└── docs/                   # Documentation
```

**Backward Compatibility**: The ConversationMemoryServer automatically detects whether to use the new `data/` structure or legacy structure for existing installations.

**External Storage**: Claude Desktop integration still uses `~/claude-memory/` (outside project) for user conversation storage.

## Python Version Management

CI (`.github/workflows/build.yml`, `performance.yml`) runs **Python 3.14** — that's the authoritative version code must pass on. `pyproject.toml` sets `requires-python = ">=3.10"` as the package's supported floor (verified: `src/` uses no 3.11+-only stdlib features, e.g. no `tomllib`, `datetime.UTC`). `.python-version` is pinned to `3.14` to match CI.

Locally, use whatever venv you have — this repo's checked-in venvs (`.venv/`, `claude-memory-mcp-venv/`) currently run Python 3.12.3. Local exact-version matching isn't required; CI is the gate. If you need to reproduce a CI-only failure, install and use 3.14 directly.

### Recommended Commands

```bash
# Run tests
python -m pytest tests/test_100_percent_coverage.py --cov=src --cov-report=xml

# Install dependencies
python -m pip install -r requirements.txt

# Run server
python src/server_fastmcp.py

# Create a virtual environment
python3.12 -m venv .venv   # or any interpreter satisfying >=3.10
source .venv/bin/activate
```

### SonarCloud Quality Gate

Recent fixes applied to resolve code quality issues:
- ✅ Replaced bare `except:` clauses (E722: 0 remaining, verified via `ruff check --select E722`) — note this doesn't mean specific exception types throughout: `ruff check --select BLE` still finds 79 `except Exception:` (blind-except) hits repo-wide
- ✅ Removed unused import statements
- ✅ Extracted magic numbers to named constants
- ✅ Broke down complex methods (generate_weekly_summary)
- ✅ Added path validation for security
- ✅ Migrated from self-hosted SonarQube to SonarCloud for public visibility
- ✅ Fixed return type hint for add_conversation method
- ✅ Reduced cognitive complexity in search_conversations method
- ✅ Excluded archive/ and scripts/ folders from code analysis
- ✅ Added proper file formatting (newlines at end of files)

**SonarCloud Configuration:**
- Organization: adamkwhite
- Project Key: adamkwhite_claude-memory-mcp
- Dashboard: https://sonarcloud.io/summary/overall?id=adamkwhite_claude-memory-mcp
- Exclusions: `tests/**,**/*test*.py,**/test_*.py,**/*benchmark*.py,**/*performance*.py,scripts/**,**/__pycache__/**,htmlcov/**,archive/**,examples/**,docs/generated/**,benchmark_results/**`

**Current Test Coverage: 88.1%** | Duplications: **1.1%** (SonarCloud, verified via API July 2026 — local `--cov` runs undercount because they don't exercise every test file in one pass; trust the SonarCloud dashboard over a local `.coverage` file)

**Coverage Milestones Achieved (historical, at time of writing):**
- ✅ **conversation_memory.py**: 100% coverage
- ✅ **exceptions.py**: 100% coverage

**SonarCloud Exclusion Workflow:**
When creating new files, automatically check if they need SonarCloud coverage analysis:

**Files that DON'T need coverage (auto-exclude):**
- Tests: `tests/*`, `test_*.py`, `*_test.py`, `*benchmark*.py`, `*performance*.py`
- Scripts: `scripts/*`, `*.sh`, utility files
- Generated: `docs/generated/*`, `benchmark_results/*`
- Examples: `examples/*`
- Build artifacts: `build/*`, `dist/*`, `__pycache__/*`

**Process:**
1. Before creating files, identify if they need coverage analysis
2. If not, immediately update sonar-project.properties exclusions
3. Use descriptive naming that fits existing exclusion patterns
4. **Update ALL GitHub workflow actions** that run tests to exclude non-coverage files
5. Commit exclusion updates with main file changes
6. This prevents coverage drops and eliminates reactive fixes

**GitHub Workflow Update Requirements:**
When adding exclusions, also update these workflow files:
- `.github/workflows/build.yml` - Main coverage workflow (exclude from `--ignore` in pytest)
- `.github/workflows/performance.yml` - Performance testing (runs separately)
- Any other workflows running pytest with coverage

### Environment Setup

```bash
# Create a virtual environment (>=3.10 required; CI runs 3.14)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest pytest-cov pytest-asyncio
```

## Testing Strategy

**Test Suite Organization:**
- `test_100_percent_coverage.py` - Essential for edge cases, error handling, and security validation. DO NOT remove.
- `test_memory_server.py` - Functional testing of core memory server features
- `test_direct_coverage.py` - Direct testing of server components
- `test_fastmcp_coverage.py` - FastMCP-specific functionality testing
- `test_server.py` - Integration testing of complete server functionality

**Coverage Monitoring:**
- Local: Run `pytest tests/ --cov=src --cov-report=term`
- CI: GitHub Actions runs all tests and reports to SonarCloud
- Target: 90%+ coverage maintained through layered testing approach

**PR Quality Gate Enforcement:**

There are **4** required status checks, verified against ruleset 5957219 on August 15 2026:

| Required check | Workflow |
|---|---|
| `Quick Validation` | `build.yml` — ruff lint/format, mypy |
| `Tests & SonarQube Analysis` | `build.yml` — pytest + coverage + SonarCloud |
| `Tests (Windows)` | `build.yml` — the suite on `windows-latest` |
| `Analyze (python)` | `codeql.yml` |

This doc previously claimed **5**, listing `performance-tests` and `performance-comparison`
among them. Those two jobs run on every PR and are worth reading, but they have **never** been
wired into the ruleset and do not block merge. Re-check with:
`gh api repos/adamkwhite/universal-memory-mcp/rulesets/5957219 --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'`

- `Tests & SonarQube Analysis` fails the PR if the SonarCloud quality gate is red. The gate ("Sonar way", verified via the SonarCloud API) requires coverage on new code ≥ **80%**, not 90% as this doc previously (incorrectly) claimed — also new duplicated lines ≤ 3% and A ratings on new security/reliability/maintainability
- `Tests (Windows)` became required in #206, after #204/#205 took the Windows suite from 29 failures + 40 teardown errors to green. The remaining Windows skips are deliberate and marked in `tests/conftest.py` with `requires_posix_permissions` (Windows `chmod` only toggles the read-only attribute, never for directories). #209 removed the second marker by fixing the src bug it was covering for.
- Draft PRs skip all 4 checks until flipped ready (`gh pr ready`); a skipped required check reports as passing, so a draft never blocks merge, it just hasn't been checked yet
- The `changes` path filter means a PR touching only **docs** (`*.md`, `docs/**`, `LICENSE`, `.gitignore`) **skips every heavy job**, so all its required checks report as passing without having run. That is by design: a skipped *workflow* would never report at all and would hang forever at "Expected", so the workflow always starts and the `changes` job gates the heavy jobs instead.
- `.github/**` used to be in that exclusion list too, which meant a workflow change skipped the jobs it was changing — on the PR *and* on the merge to main. #206 made `Tests (Windows)` a required check and produced no CI run on any branch. Fixed in #208: `.github/**` now counts as code, so CI verifies its own changes.

**Fork PRs (#201):** GitHub withholds secrets from forks, so the `SonarCloud Scan` step and the perf-results PR comment are gated on `github.event.pull_request.head.repo.fork != true`. Both are skipped for outside contributions rather than failing them. Coverage on a fork's new code is verified when the branch lands on main. Note that **re-running a fork PR's checks does not pick up workflow changes** — GitHub replays the workflow file from the original commit, so the contributor has to push.

## Git Workflow

**MANDATORY:** This repository has branch protection rules that REQUIRE pull requests for all changes to main:

### **Standard Development Workflow (REQUIRED):**
```bash
# 1. Create feature branch (ALWAYS REQUIRED - even for documentation changes)
git checkout -b feature/your-feature-name

# 2. Make changes and commit
git add <files>
git commit -m "descriptive message"

# 3. **MANDATORY: Run full test suite after major changes**
# Activate virtual environment and run tests
source claude-memory-mcp-venv/bin/activate
python -m pytest tests/ --cov=src --cov-report=term -v

# 4. Push branch to GitHub (NEVER push directly to main)
git push origin feature/your-feature-name

# 5. Open Pull Request on GitHub
# - Open it ready (not draft) if you want CI to run now — draft PRs skip
#   all 4 required checks until you run `gh pr ready`
# - ALWAYS mention @claude in PR body or comments for review
# - PR triggers automated testing and SonarCloud analysis
# - Must pass all 4 required status checks before merge unlocks
# - SonarCloud's new-code coverage threshold is 80%, not 90%

# 6. Merge PR (only after all 4 required checks are green)
# - Quick Validation, Tests & SonarQube Analysis, Tests (Windows),
#   Analyze (python) must all pass
# - performance-tests / performance-comparison also run, but are NOT
#   required and do not block merge
# - PR conversations must be resolved ✅
```

### **CRITICAL: No Direct Pushes to Main**
- ❌ **ALL direct pushes to main are BLOCKED** - even for simple documentation updates
- ❌ **Force pushes are BLOCKED**
- ❌ **Quality gate failures block merges**
- ✅ **EVERY change must go through feature branch + PR process**
- ⚠️ **This applies to todos.md, README.md, and ALL files without exception**

### **Quality Gate Requirements:**
- All 4 required status checks must pass: `Quick Validation`, `Tests & SonarQube Analysis`, `Tests (Windows)`, `Analyze (python)`. `performance-tests` and `performance-comparison` run but are not required.
- SonarCloud coverage on new code ≥ **80%** (not 90%)
- No unresolved PR conversations
- Linear history maintained

**Note:** Branch protection (`current_user_can_bypass: never`, verified via `gh api .../rulesets/5957219`) blocks deletion, force-push, and non-fast-forward pushes to main for everyone including repository owners — that part was already true. Whether a *red CI check* also blocks merge depends on the required-status-checks rule described above, not on this bypass setting.

### **Mandatory Testing Requirements**

**ALWAYS run full test suite for these changes:**
- Any code changes to `src/` directory
- Directory structure modifications
- Configuration file updates (`pyproject.toml`, `pytest.ini`)
- Database schema changes
- API endpoint modifications
- New feature implementations
- Bug fixes involving core functionality

**Testing Command (Copy-Paste Ready):**
```bash
source claude-memory-mcp-venv/bin/activate && python -m pytest tests/ --cov=src --cov-report=term -v
```

**Expected Results:**
- ✅ All tests must pass (900 passed, 1 skipped as of August 15 2026 — the count only grows)
- ✅ Coverage: trust SonarCloud (88%), not a local `.coverage` file. The old "≥ 94%" figure here was a local number that never matched the dashboard.
- ✅ No failing tests before creating PR

**If tests fail:**
1. Fix failing tests immediately
2. Re-run test suite until all pass
3. Only then proceed with PR creation

This prevents back-and-forth in PRs due to test failures.

### **⚠️ CRITICAL: Lessons Learned from Process Failures**

**Based on SQLite FTS Search Optimization implementation (June 2025), the following workflow violations caused significant impact:**

**NEVER DO THIS:**
- ❌ Skip local testing before commits ("I'll test in CI/CD")
- ❌ Push changes without running full test suite first
- ❌ Create reactive "fix-as-we-go" PRs with multiple failure cycles
- ❌ Submit PRs before validating compatibility with existing systems
- ❌ Ignore async compatibility analysis for major changes

**CONSEQUENCES OF WORKFLOW VIOLATIONS:**
- **Technical Impact**: 64+ test failures, hours of reactive debugging
- **Team Impact**: Multiple back-and-forth cycles, wasted review time
- **Process Impact**: CI/CD pipeline blocked, delayed other features
- **Quality Impact**: Reactive fixes instead of systematic solutions

**MANDATORY PREVENTIVE MEASURES:**
1. **Pre-Commit Validation**: ALWAYS run local test suite before first commit
2. **Compatibility Analysis**: Plan async/breaking changes before implementation
3. **Script Dependencies**: Test all supporting scripts locally before CI/CD
4. **Systematic Approach**: Complete planning phase before coding phase
5. **Zero-Defect PRs**: Only submit PRs after local validation passes

**ACCOUNTABILITY:**
- Local testing is **NON-NEGOTIABLE** - no exceptions for "minor" changes
- "Speed over quality" approach is **explicitly prohibited**
- Process shortcuts that create technical debt are **unacceptable**
- Reactive debugging in PRs indicates **insufficient upfront planning**

### **📋 PRE-COMMIT CHECKLIST (MANDATORY)**

**Before making ANY commit to ANY branch:**

- [ ] **1. Run Full Test Suite Locally**
  ```bash
  source claude-memory-mcp-venv/bin/activate && python -m pytest tests/ --cov=src --cov-report=term -v
  ```
- [ ] **2. Verify All Tests Pass** (expect 900+ passing tests, 1 skipped — verified August 15 2026)
- [ ] **3. Check Coverage Baseline** (expect ≥88% coverage per SonarCloud, not local `.coverage`)
- [ ] **4. Test Supporting Scripts** (if modified any scripts/ files)
- [ ] **5. Validate Async Compatibility** (if modified async methods)
- [ ] **6. Run SonarCloud Analysis** (triggered automatically on PR)
- [ ] **7. Document Breaking Changes** (if any API changes)

**Before creating ANY Pull Request:**

- [ ] **8. Re-run Full Test Suite** (final validation)
- [ ] **9. Review All Changed Files** (ensure no debug code, console.log, etc.)
- [ ] **10. Write Descriptive PR Description** (what, why, how, testing done)
- [ ] **11. Self-Review Changes** (would you approve this PR?)
- [ ] **12. Verify No Merge Conflicts** (rebase if needed)

**⚠️ ZERO TOLERANCE:** Committing without completing this checklist violates workflow standards and creates technical debt.

**GitHub Actions Workflow Notes:**
- ✅ **Migrated to SonarCloud**: Public code quality dashboard with automatic PR decoration
- **Two build phases**: PR testing (cannot push) + post-merge execution (can push badges)
- **Badge updates**: SonarCloud badges auto-update from cloud platform
- **PR builds**: Test code without attempting repository modifications

## 100% Test Coverage Initiative

**Current Status: 88.1% coverage (SonarCloud, verified via API July 2026 — SUFFICIENT, not pursuing 100%)**

### Coverage Breakdown by Module (historical snapshot from this initiative; see SonarCloud dashboard for current per-file numbers)
- `conversation_memory.py`: **100%** ✅ (237 lines, 0 missing)
- `exceptions.py`: **100%** ✅ (10 lines, 0 missing)
- `server_fastmcp.py`: **99.01%** (405 lines, 4 missing)
- `validators.py`: **98.65%** (74 lines, 1 missing)
- `logging_config.py`: **94.44%** (108 lines, 6 missing)

### Implementation Strategy
**Phase 1: Exception Handling (COMPLETED ✅)**
- Target: ImportError blocks, JSON processing errors
- Achievement: conversation_memory.py → 100% coverage
- Progress: 95.08% → 96.52% total coverage

**Phase 2: Edge Cases (COMPLETED ✅)**
- Target: validators.py line 104, server_fastmcp.py key lines
- Achievement: 96.52% → 97.96% total coverage

**Phase 3: Integration Testing (COMPLETED ✅)**
- Target: logging_config.py remaining lines
- Achievement: 97.96% → 98.68% total coverage

### Test Modules for Coverage
- `test_importerror_coverage.py` - ImportError exception paths
- `test_json_exception_coverage.py` - JSON processing edge cases
- `test_validator_edge_cases.py` - Input validation boundaries
- `test_100_percent_coverage.py` - Comprehensive edge case testing

## Implementation Details

### Universal Memory Architecture
The system uses a pluggable importer architecture where each AI platform has a dedicated importer class inheriting from `BaseImporter`:

- **BaseImporter**: Abstract base defining universal conversation format
- **Format Detection**: Automatic platform recognition with confidence scoring
- **Schema Validation**: JSON schemas ensure data integrity and compatibility
- **Universal Format**: Standardized internal representation for cross-platform compatibility

### Key Design Decisions
- **Backward Compatibility**: Existing Claude conversations remain fully functional
- **Privacy-First Development**: Tools for sanitizing real export data for testing
- **Extensible Architecture**: Easy addition of new AI platforms
- **Performance-Optimized**: SQLite FTS5 search, measured ~10-20ms typical per query (see README Performance section) — not sub-3ms as previously claimed

## Next Steps

**Immediate Priorities (Next Session):**
1. **Test Additional Platforms** - Validate Cursor/Claude importers with real export data
2. **Complete Schema Validation** - Finish JSON schemas for all supported platforms
3. **FastMCP Integration** - Wire up importers to MCP server with new tools
4. **End-to-End Testing** - Full import pipeline validation and performance benchmarking

**Medium-Term Goals:**
- Real-time platform integrations (ChatGPT API, Cursor sessions)
- Advanced search features (date filtering, semantic search)
- Multi-user support and workspace isolation
- Cross-platform conversation sync and merging

## Recent Changes

### **November 24, 2025 - Repository Maintenance ✅**

**PR Merged: #87**
- **Achievement**: Added `.claude/` directory to gitignore for cleaner repository management
- **Impact**: Prevents 17+ auto-generated Claude Code plugin files from appearing as untracked changes

**Changes:**
- ✅ Updated `.gitignore` to ignore entire `.claude/` directory
- ✅ Replaced specific `settings.local.json` exclusion with comprehensive directory exclusion
- ✅ Maintains clean git status focusing on actual project changes

**Workflow Excellence:**
- ✅ Full branch workflow compliance (feature branch → PR → quality gates → merge)
- ✅ All quality gates passed (Quick Validation: 12s, SonarCloud: 26s, Tests: 57s)
- ✅ Demonstrates proper git workflow even for minor maintenance tasks

**Key Learnings:**
- Even simple changes benefit from full workflow process
- Auto-generated IDE/tool files should be ignored at directory level
- Clean git status improves developer experience and reduces noise

### **November 13, 2025 - Documentation & Test Cleanup ✅**

**PR Merged: #80**
- **Achievement**: Fixed critical README installation issues preventing new user onboarding
- **Impact**: Installation now works on first try, 6 GitHub issues resolved, improved code quality

**README Documentation Fixes (Issues #74-79):**
- ✅ Added Claude Code installation option (`claude mcp add`) as recommended method
- ✅ Fixed all file paths to include correct directories (`tests/`, `src/`, `scripts/`)
- ✅ Changed `pip install mcp[cli]` → `pip install -e .` for proper dependency installation
- ✅ Added explicit dependency list with versions (mcp, jsonschema, aiofiles)
- ✅ Removed comprehensive testing framework section (files didn't exist)
- ✅ Added practical Development and Testing section with verified commands

**Test Linting Cleanup (Issue #64):**
- ✅ Fixed E501 line-too-long violations using `black --line-length=79`
- ✅ Fixed F841 unused variable warnings across 11 test files
- ✅ Maintained 100% test pass rate (435/435 tests passing)
- ✅ No functional changes, only formatting improvements

**User Experience Impact:**
- New users can install and run the project successfully on first attempt
- All referenced files and paths exist and are correct
- Installation instructions are complete and accurate
- Reduced friction for project adoption

**Lessons Learned:**
- Documentation accuracy is critical for new user onboarding
- Regular validation of README instructions prevents user frustration
- Automated linting helps maintain code quality standards
- Test fixtures requiring specific variables need careful refactoring

### **October 10, 2025 - SonarCloud Async Compliance & Code Quality ✅**

**PRs Merged: #69, #70**
- **Achievement**: Resolved all SonarCloud code quality issues and async/await warnings
- **Impact**: 100% compliant with SonarCloud quality gates, proper async file I/O throughout

**Async File I/O Migration:**
- ✅ Converted `add_conversation()` to use `async with aiofiles.open()`
- ✅ Converted `generate_weekly_summary()` to async file writes
- ✅ Converted `search_conversations()` fallback path to async
- ✅ Converted `search_by_topic()` and `_search_topic_json()` to async
- ✅ Converted `_process_conversation_for_search()` to async
- ✅ Added `aiofiles>=24.1.0` dependency

**Code Quality Improvements:**
- ✅ Extracted `ISO_DATETIME_FORMAT` constant (logging_config.py)
- ✅ Removed redundant `list()` call (cursor_importer.py)
- ✅ Removed unused parameter (generic_importer.py)
- ✅ Changed HTTP to HTTPS in schema URL (chatgpt_schema.py)

**Test Coverage Enhancements:**
- ✅ Added `test_search_by_topic_json_fallback` - JSON topic search coverage
- ✅ Added `test_search_conversations_json_fallback` - Linear search coverage
- ✅ Added `test_search_with_missing_file` - Error handling coverage
- ✅ Achieved 80%+ coverage on new code (SonarCloud requirement)

**CI/CD Results:**
- ✅ All 435 tests passing (was 417)
- ✅ 78% overall coverage (was 76%)
- ✅ Zero code smells, zero security hotspots
- ✅ All SonarCloud quality gates passing

## Recent Changes (June 15, 2025)

### **🎯 MAJOR MILESTONE: Universal Memory MCP Framework - PRODUCTION READY ✅**

**Complete System Implementation Achieved:**
- **417 Tests Passing** - Comprehensive test coverage with zero failures
- **76% Overall Coverage** - Major improvement from 50% baseline after adding new framework
- **CI/CD Fully Functional** - GitHub Actions pipeline operational with SonarCloud integration
- **Public Code Quality Dashboard** - Clean codebase with zero code smells/security issues visible to recruiters

### **Universal Memory MCP Framework Implementation ✅ MAJOR FEATURE**
- **Achievement**: Complete architecture transformation from Claude-specific to universal AI platform support
- **Scope**: 13 new files implementing extensible import framework + comprehensive test suite
- **Impact**: Foundation for supporting all major AI platforms with standardized conversation management

**Core Components Implemented:**
- `src/format_detector.py` - Automatic platform recognition with confidence scoring (83% coverage)
- `src/importers/` - Complete pluggable importer system (5 classes, 75-86% coverage each)
- `src/schemas/chatgpt_schema.py` - Production-ready ChatGPT validation (57% coverage)
- `docs/ai_platform_formats.md` - Comprehensive platform format research
- `scripts/sanitize_chatgpt_export.py` - Privacy-safe development tools

**Test Suite Excellence (June 15, 2025):**
- **28 Test Classes** - Comprehensive coverage across all importer components
- **417 Individual Tests** - Detailed edge case and integration testing
- **Real Format Validation** - Tests using actual AI platform export structures
- **Mock Integration** - Proper isolation testing with comprehensive mocking
- **CI Pipeline Integration** - All tests pass in GitHub Actions environment

**Coverage Achievements:**
- `format_detector.py`: 40% → 83% (+43% improvement)
- `generic_importer.py`: 13% → 86% (+73% improvement)
- `chatgpt_schema.py`: 0% → 57% (+57% improvement)
- `cursor_importer.py`: 13% → 84% (+71% improvement)
- `claude_importer.py`: 15% → 75% (+60% improvement)

**ChatGPT Integration (Production Ready):**
- Full OpenAI export format support with complex message mapping structure
- JSON schema validation tested against real ChatGPT exports
- Privacy-safe sanitization tools for development with actual user data
- Handles conversation arrays, message nodes, and metadata preservation

**Development Excellence:**
- Real export structure analysis revealing complex mapping-based message storage
- Comprehensive error handling and validation with detailed feedback
- Privacy-first approach with tools for safe development using real data
- Extensible design ready for additional platform implementations

### **Critical System Fixes (June 15, 2025)**
- **Merge Conflict Resolution**: Successfully resolved conflicts in generic_importer.py and schemas/__init__.py
- **Test Framework Stabilization**: Fixed all 20 failing tests through systematic debugging
- **CI/CD Pipeline Repair**: Added missing jsonschema dependency to fix GitHub Actions failures
- **SonarCloud Migration**: Migrated from self-hosted SonarQube to public SonarCloud dashboard for visibility

### **Previous Major Fix: MCP JSON Parsing (PR #33)**

### **Search Optimization Implementation ✅ MAJOR PERFORMANCE IMPROVEMENT**
- **Achievement**: Implemented SQLite FTS5 full-text search replacing linear search
- **Performance**: claimed 4.4x faster / 77.5% improvement at the time — never actually measured (benchmark script had unawaited async calls); re-measured July 2026 at ~10x faster than linear scan, see README Performance section
- **Features**:
  - SQLite FTS5 database with full-text search and relevance scoring
  - Automatic migration from JSON to SQLite with verification
  - Backward compatibility with fallback to linear search
  - New MCP tools: `get_search_stats`, `search_by_topic`
  - **Note**: `migrate_to_sqlite` tool disabled by default (saves 573 tokens context) - SQLite auto-migrates on first use
- **Testing**: Comprehensive test suite covering all SQLite functionality
- **Scalability**: Search now scales efficiently with conversation growth

### **Previous Major Fix: MCP JSON Parsing (PR #33)**
- **Problem Solved**: Claude Desktop MCP communication restored
- **Root Cause**: Print statements corrupting JSON-RPC protocol
- **Solution**: Proper logging configuration with `~/.claude-memory/logs/claude-mcp.log`
- **Impact**: MCP server fully functional with Claude Desktop

### **Current Status**
- **Branch**: `feature/search-optimization-analysis`
- **Test Coverage**: 98.68% (industry-leading)
- **Code Quality**: 0 code smells, 0 security hotspots
- **Search Performance**: SQLite FTS5 enabled, ~10x faster than linear (measured July 2026; the original 4.4x figure was never actually measured)
- **Production Ready**: High-performance search with SQLite optimization

### **Completed Major Features**
1. ✅ **SQLite FTS Search** - full-text search, ~10x faster than linear scan (measured July 2026; superseded the unverified 4.4x figure)
2. ✅ **Path Portability** - Universal deployment support (PRs #36, #37, #38)
3. ✅ **Test Coverage** - 98.68% with comprehensive edge case testing
4. ✅ **Input Validation** - Security-focused validation preventing attacks
5. ✅ **MCP Integration** - Claude Desktop compatibility with proper logging

### **Next Steps (Medium Priority)**
1. **Universal Memory MCP** - Expand to support ChatGPT, Cursor, and other AI platforms
2. **Advanced Search Features** - Add date filtering, advanced queries, and search suggestions
3. **Performance Monitoring** - Add real-time performance metrics and search analytics
4. **Multi-user Support** - Architecture for supporting multiple users/sessions

### **Technical Excellence Achieved**
- **Search Performance**: ~10-20ms typical search times vs ~150ms+ linear search (measured July 2026; not sub-3ms as previously claimed, see README Performance section)
- **Scalability**: Efficient indexing handles large conversation datasets
- **Reliability**: Dual storage (JSON + SQLite) with automatic fallback
- **Security**: Comprehensive input validation and path security

## Project Management

**Task Tracking:** All todos and project tasks are maintained in `todos.md` for persistence across Claude Code sessions. This includes pending improvements, completed work, and priority classifications.

**Implementation Plans:** Major features use Cornell numbering system for systematic implementation:
- **Format**: `1.1.1`, `2.3.2`, etc. for hierarchical task organization
- **Structure**: 9 major sections, each with 2-4 subsections, each with 3-5 specific tasks
- **Purpose**: Enables intermediate developers to implement complex features step-by-step
- **Examples**: Encryption (69 tasks), Path Portability (46 tasks), SonarCloud Migration (46 tasks), Project Cleanup (57 tasks)
- **Benefits**: Clear progress tracking, logical task dependencies, comprehensive coverage

**Plan Creation Guidelines:**
- Use Cornell numbering for all multi-step implementation plans
- Break complex features into 9 logical sections
- Provide 40-70 specific, actionable subtasks
- Include testing, documentation, and validation requirements
- Maintain quality standards throughout implementation

## MCP Server Deployment Notes

### **Local Development**

**From project root directory:**
```bash
# Install dependencies
python3 -m venv claude-memory-mcp-venv
source claude-memory-mcp-venv/bin/activate
pip install -e .

# Run server directly
python3 src/server_fastmcp.py

# Enable console logging for debugging
CLAUDE_MCP_CONSOLE_OUTPUT=true python3 src/server_fastmcp.py
```

**From src/ directory:**
```bash
# Create virtual environment (if not exists)
python3 -m venv ../claude-memory-mcp-venv

# Install dependencies and run server
source ../claude-memory-mcp-venv/bin/activate && pip install -e .. && python3 server_fastmcp.py

# Or if already installed, just run server
source ../claude-memory-mcp-venv/bin/activate && python3 server_fastmcp.py
```

### **Claude Desktop Integration**
Add to Claude Desktop MCP configuration:
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

**Log Location**: `~/.claude-memory/logs/claude-mcp.log`
**Storage Location**: `~/claude-memory/conversations/`
