# BSL Analyzer

Static analysis toolkit for **1C Enterprise BSL** language.

Three interfaces powered by a single shared symbol index:

| Interface  | Command                  | Client           |
|------------|--------------------------|------------------|
| MCP server | `bsl-analyzer --mcp`     | Claude           |
| LSP server | `bsl-analyzer --lsp`     | VSCode / Cursor  |
| CLI linter | `bsl-analyzer --check`   | CI / terminal    |

**Performance:** ~600 files/sec with `--jobs 4` · ~80 MB RAM · Python 3.11+

---

## Quick Start

```bash
pip install bsl-analyzer

# Lint a project
bsl-analyzer --check /path/to/1c/project

# Start MCP server for Claude
bsl-analyzer --mcp --port 8051

# Start LSP server (stdio) for VSCode/Cursor
bsl-analyzer --lsp
```

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install bsl-analyzer
```

---

## CLI Linter

```bash
# Check current directory (auto-discovers .bsl and .os files)
bsl-analyzer --check .

# Select specific rules
bsl-analyzer --check src/ --select BSL001,BSL011,BSL012

# Ignore rules
bsl-analyzer --check . --ignore BSL014,BSL023

# JSON output (for CI / dashboards)
bsl-analyzer --check . --format json > issues.json

# SARIF output (GitHub Code Scanning / GitLab SAST)
bsl-analyzer --check . --format sarif > results.sarif

# SonarQube Generic Issue Import
bsl-analyzer --check . --format sonarqube --sonar-root /project > sonar.json

# Parallel workers
bsl-analyzer --check . --jobs 8

# Never fail CI (collect metrics but exit 0)
bsl-analyzer --check . --exit-zero

# Watch mode — re-lint on every save
bsl-analyzer --watch src/
```

**Exit codes:** `0` = clean · `1` = issues found · `2` = internal error

### Inline suppression

```bsl
Пароль = "dev_only";  // noqa: BSL012
Пароль = "dev_only";  // bsl-disable: BSL012
Пароль = "dev_only";  // noqa          ← suppresses ALL rules on this line
```

### Output format (text)

```
src/Orders.bsl:145:0: W BSL002 Procedure 'ОбработатьЗаказ' is 215 lines long (max 200)
src/Utils.bsl:78:4:  W BSL004 Empty exception handler: Except block has no statements.
src/Utils.bsl:92:0:  E BSL012 Possible hardcoded credential: Пароль = "..."
```

---

## Configuration File

Create `bsl-analyzer.toml` in your project root (or use `[tool.bsl-analyzer]` in
`pyproject.toml`):

```toml
# bsl-analyzer.toml
select = []                  # [] = all rules (default)
ignore = ["BSL014", "BSL023"]
exclude = ["vendor", "tests/fixtures"]
format = "text"              # text | json | sonarqube | sarif
jobs = 0                     # 0 = auto
exit-zero = false

# Per-file overrides
[per-file-ignores]
"legacy_*.bsl" = ["BSL012", "BSL035"]
"*test*.bsl"   = ["BSL002"]

# Threshold overrides
max-line-length = 120
max-proc-lines  = 200
max-cognitive-complexity = 15
max-mccabe-complexity    = 10
max-nesting-depth        = 4
max-params               = 7
max-returns              = 3
max-bool-ops             = 3
min-duplicate-uses       = 3
```

---

## Baseline (gradual adoption)

Start with a clean baseline so only *new* issues break the build:

```bash
# 1. Record all current issues as baseline
bsl-analyzer --check . --update-baseline bsl-baseline.json

# 2. Commit bsl-baseline.json
git add bsl-baseline.json && git commit -m "chore: add BSL analyzer baseline"

# 3. In CI — only NEW issues fail the build
bsl-analyzer --check . --baseline bsl-baseline.json

# 4. After fixing issues, shrink the baseline
bsl-analyzer --check . --update-baseline bsl-baseline.json
```

---

## Built-in Rules

55 rules (BSL001–BSL055) covering syntax, size, complexity, security, and style.

Run `bsl-analyzer --list-rules` for the full table.

### Rule categories

| Category     | Rules                   | Description                                  |
|--------------|-------------------------|----------------------------------------------|
| Syntax       | BSL001                  | Parser errors                                |
| Size         | BSL002, BSL015, BSL031, BSL043 | Method/param count limits          |
| Complexity   | BSL011, BSL019, BSL020  | Cognitive / McCabe / nesting depth           |
| Security     | BSL005, BSL006, BSL012, BSL053 | Hardcoded secrets, paths, exec()    |
| Error handling | BSL004, BSL028, BSL034, BSL049 | Empty catch, missing try, raise  |
| Design       | BSL003, BSL032, BSL042, BSL044, BSL050 | API contracts, transactions |
| Performance  | BSL033, BSL038          | Query-in-loop, string concat in loop         |
| Style        | BSL013, BSL014, BSL023–BSL026, BSL055 | Comments, line length      |
| Deprecated   | BSL017, BSL022, BSL041  | Outdated APIs                                |
| Suspicious   | BSL009, BSL010, BSL051, BSL052 | Self-assign, dead code, literals    |

### Selected rules

| Code   | Sev | Name                        | Description                                             |
|--------|-----|-----------------------------|---------------------------------------------------------|
| BSL001 | ERR | ParseError                  | Syntax error detected by tree-sitter                   |
| BSL002 | WRN | MethodSize                  | Method longer than 200 lines                            |
| BSL004 | WRN | EmptyCodeBlock              | Empty `Исключение` block                               |
| BSL005 | WRN | HardcodeNetworkAddress      | Hardcoded IP / URL                                      |
| BSL011 | WRN | CognitiveComplexity         | Cognitive complexity > 15                               |
| BSL012 | WRN | HardcodeCredentials         | Hardcoded password / token / secret                     |
| BSL019 | WRN | CyclomaticComplexity        | McCabe complexity > 10                                  |
| BSL033 | ERR | QueryInLoop                 | DB query inside a loop (critical performance issue)     |
| BSL042 | WRN | EmptyExportMethod           | Exported method has no body                             |
| BSL049 | INF | UnconditionalRaise          | `ВызватьИсключение` outside `Попытка`                  |
| BSL050 | WRN | LargeTransaction            | `НачатьТранзакцию` without matching commit/rollback    |
| BSL051 | WRN | UnreachableCode             | Code after unconditional `Возврат`/`ВызватьИсключение` |
| BSL052 | WRN | UselessCondition            | `Если Истина/Ложь Тогда` — condition is constant       |
| BSL053 | WRN | ExecuteDynamic              | `Выполнить()` — dynamic code execution security risk    |

---

## SonarQube Integration

```bash
bsl-analyzer --check . --format sonarqube --sonar-root /project > bsl-issues.json
```

In `sonar-project.properties`:

```properties
sonar.externalIssuesReportPaths=bsl-issues.json
```

---

## GitHub Actions / CI

```yaml
- name: BSL Lint
  run: |
    pip install bsl-analyzer
    bsl-analyzer --check . --format sarif > bsl-results.sarif

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: bsl-results.sarif
```

---

## MCP Server (for Claude)

Start the server:

```bash
bsl-analyzer --mcp --port 8051
```

Configure in Claude Desktop / Cursor (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bsl-analyzer": {
      "url": "http://localhost:8051/mcp"
    }
  }
}
```

Available tools:

| Tool                  | Description                                            |
|-----------------------|--------------------------------------------------------|
| `bsl_status`          | Index health check (symbol count, last commit)         |
| `bsl_find_symbol`     | Search symbols by name (exact or prefix)               |
| `bsl_file_symbols`    | All symbols defined in a file                          |
| `bsl_callers`         | Who calls a given procedure/function                   |
| `bsl_callees`         | What a procedure/function calls                        |
| `bsl_diagnostics`     | Run lint rules on a file or directory                  |
| `bsl_definition`      | Definition location(s) of a symbol                     |
| `bsl_index_file`      | Force re-index a single file                           |
| `bsl_check_file`      | Run lint rules with select/ignore filters              |
| `bsl_list_rules`      | List all rules (with optional tag filter)              |

---

## LSP Server (for VSCode / Cursor)

```bash
bsl-analyzer --lsp
```

Capabilities:

| Feature                   | Status |
|---------------------------|--------|
| Go to definition          | ✓      |
| Hover (signature + doc)   | ✓      |
| Document symbols          | ✓      |
| Workspace symbol search   | ✓      |
| Completions               | ✓      |
| Find references           | ✓      |
| Diagnostics on save       | ✓      |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  bsl-analyzer                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ MCP HTTP │  │ LSP stdio│  │ CLI --check   │  │
│  └────┬─────┘  └────┬─────┘  └──────┬────────┘  │
│       └─────────────┴───────────────┘            │
│                Analysis Layer                    │
│     DiagnosticEngine (55 rules, BSL001–BSL055)   │
│     symbols · call_graph · platform_api          │
│                Indexer Layer                     │
│       IncrementalIndexer · FileWatcher           │
│              SymbolIndex (SQLite FTS5)           │
│                Parser Layer                      │
│      BslParser (tree-sitter-bsl) + regex         │
└─────────────────────────────────────────────────┘
```

---

## Development

```bash
git clone https://github.com/your-org/bsl-analyzer
cd bsl-analyzer
uv pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/

# Full check with coverage
pytest --cov=src/bsl_analyzer --cov-report=term-missing
```

---

## License

MIT
