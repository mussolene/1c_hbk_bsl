# BSL Analyzer

Static analysis toolkit for **1C Enterprise BSL** language.

Provides three interfaces over a single shared symbol index:

| Interface    | Command                    | Client             |
|--------------|----------------------------|--------------------|
| MCP server   | `bsl-analyzer --mcp`       | Claude             |
| LSP server   | `bsl-analyzer --lsp`       | VSCode / Cursor    |
| CLI linter   | `bsl-analyzer --check`     | CI / terminal      |

## Architecture

```
┌──────────────────────────────────────────────┐
│               bsl-analyzer                   │
│  ┌─────────┐  ┌─────────┐  ┌──────────────┐ │
│  │ MCP     │  │ LSP     │  │ CLI --check  │ │
│  │ HTTP    │  │ stdio   │  │ rich output  │ │
│  └────┬────┘  └────┬────┘  └──────┬───────┘ │
│       └────────────┴──────────────┘          │
│              Analysis Layer                  │
│         symbols · call_graph · diagnostics   │
│              Indexer Layer                   │
│     IncrementalIndexer · FileWatcher         │
│              SymbolIndex (SQLite FTS5)        │
│              Parser Layer                    │
│     BslParser (tree-sitter) + regex fallback │
└──────────────────────────────────────────────┘
```

## Quick Start

### pip install

```bash
pip install bsl-analyzer

# Index your workspace
bsl-analyzer --index /path/to/1c/project

# Start the MCP server (port 8051)
bsl-analyzer --mcp

# Or start the LSP server (stdio, for VSCode/Cursor)
bsl-analyzer --lsp

# Run the linter
bsl-analyzer --check /path/to/1c/project
```

### uv (recommended)

```bash
uv tool install bsl-analyzer
bsl-analyzer --mcp --port 8051
```

## MCP Tools

Configure in Claude Desktop / Cursor by pointing to `http://localhost:8051/mcp`:

| Tool               | Description                                        |
|--------------------|----------------------------------------------------|
| `bsl_status`       | Index health check (symbol count, last commit)     |
| `bsl_find_symbol`  | Search symbols by name (exact or prefix)           |
| `bsl_file_symbols` | All symbols defined in a file                      |
| `bsl_callers`      | Who calls a given procedure/function               |
| `bsl_callees`      | What a procedure/function calls                    |
| `bsl_diagnostics`  | Lint rules: BSL001 syntax, BSL002 length, BSL004   |
| `bsl_definition`   | Definition location(s) of a symbol                 |
| `bsl_index_file`   | Force re-index a single file                       |

### Example MCP session

```
You: Find the definition of ОбработатьЗаказ in the project
Claude: [calls bsl_find_symbol("ОбработатьЗаказ")]
        Found in /workspace/src/Orders.bsl:142 — exported procedure

You: Who calls it?
Claude: [calls bsl_callers("ОбработатьЗаказ", depth=2)]
        Called from:
          - DocumentPosting.bsl:88 in ОбработкаПроведения
          - WebhookHandler.bsl:55 in ОбработатьВебхук
```

## LSP Capabilities

| Capability                    | Status       |
|-------------------------------|--------------|
| Go to definition              | ✓            |
| Hover (signature + doc)       | ✓            |
| Document symbols (outline)    | ✓            |
| Workspace symbol search       | ✓            |
| Diagnostics on save           | ✓            |
| Completions                   | Planned      |
| Find references               | Planned      |
| Rename                        | Planned      |

## CLI Linter

```bash
# Check a single file
bsl-analyzer --check src/Orders.bsl

# Check entire directory, JSON output
bsl-analyzer --check src/ --format json

# Exit code 0 = clean, 1 = issues found
```

Output format (text):

```
src/Orders.bsl:145:0: W BSL002 Procedure 'ОбработатьЗаказ' is 215 lines long (maximum 200)
src/Utils.bsl:78:4:  W BSL004 Empty exception handler: Except block contains no statements.
```

### Built-in Rules

| Code   | Severity | Description                                       |
|--------|----------|---------------------------------------------------|
| BSL001 | ERROR    | Syntax error detected by the parser               |
| BSL002 | WARNING  | Procedure / function longer than 200 lines        |
| BSL003 | WARNING  | Public procedure missing Export keyword (planned) |
| BSL004 | WARNING  | Empty exception handler (Except block)            |

## Docker

```bash
# Build and start
HOST_WORKSPACE=/path/to/your/1c/project \
  docker compose -f docker/docker-compose.yml up -d

# Check status
curl http://localhost:8051/health
```

Environment variables:

| Variable         | Default                  | Description                  |
|------------------|--------------------------|------------------------------|
| `WORKSPACE_ROOT` | `/workspace`             | Path inside the container    |
| `INDEX_DB_PATH`  | `/data/bsl_index.sqlite` | SQLite DB location           |
| `MCP_PORT`       | `8051`                   | HTTP port                    |
| `LOG_LEVEL`      | `info`                   | Logging verbosity            |
| `GIT_DIFF_BASE`  | `HEAD`                   | Base for incremental diff    |

## VSCode / Cursor Extension

The extension lives in `vscode-extension/`.

### Development install

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VSCode to open a new Extension Development Host window
```

### Configuration

```json
// .vscode/settings.json
{
  "bslAnalyzer.serverPath": "bsl-analyzer",
  "bslAnalyzer.useDocker": false,
  "bslAnalyzer.logLevel": "info"
}
```

To use Docker instead of a local binary:

```json
{
  "bslAnalyzer.useDocker": true,
  "bslAnalyzer.dockerContainer": "bsl-analyzer-default"
}
```

## Incremental Indexing

On startup the indexer runs `git diff --name-only <last_commit> HEAD` to find
changed files and only re-parses those. First run (or `--force`) does a full
workspace scan.

```bash
# Full reindex
bsl-analyzer --index /workspace --force

# Incremental (automatic, uses stored commit hash)
bsl-analyzer --index /workspace
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, test, and style instructions.

```bash
uv pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## License

MIT
