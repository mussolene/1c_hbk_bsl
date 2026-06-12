# Production Notes

## Scope
This runbook covers production usage of:
- `onec-hbk-bsl` server (LSP + MCP + diagnostics/indexing)
- `vscode-extension` activation and binary startup behavior

**Note:** `onec-hbk-bsl` does **not** bundle or call a separate Java analyzer at runtime.

## Public Compatibility Contract
- `onec-hbk-bsl` is the product contract: CLI, LSP, MCP, formatter and Python API.
- The primary project config is `onec-hbk-bsl.toml`; `.bsl-language-server.json` is not a supported runtime config.
- `BSL_SELECT` / `onecHbkBsl.diagnostics.select` select the exact rules to run, including rules disabled by default.
- `BSL_IGNORE` / `onecHbkBsl.diagnostics.ignore` suppress rules from the default-enabled set.
- Rule selectors accept stable `BSL###` codes and BSLLS-compatible diagnostic names; the generated reference is [diagnostic-rules.md](diagnostic-rules.md).
- Source suppressions such as `// noqa: BSL###` and `// BSLLS-off/on` are supported for compatibility with existing BSL codebases.
- Formatting defaults are tabs for `[bsl]`, logical indent width 4, and safe on-type indentation on newline only.
- Diagnostics/indexing parser fallbacks are internal resilience mechanisms for malformed or partially parsed documents; they are not separate product modes and should not be documented as user-selectable behavior.
- The formatter has no parser/line/CST fallback mode: it formats from the product token stream.

## Startup And Activation
- VSCode extension activates on:
  - `onLanguage:bsl`
  - `onCommand:onecHbkBsl.reindexWorkspace`
  - `onCommand:onecHbkBsl.reindexCurrentFile`
  - `onCommand:onecHbkBsl.showStatus`
- Server binary resolution order:
  1. `onecHbkBsl.serverPath` (explicit filesystem path; default placeholder does not override)
  2. installed `onec-hbk-bsl` found on system `PATH`
  3. bundled extension binary
  4. previously downloaded binary in extension global storage
  5. release download fallback (if supported for platform)

## Docker LSP (`onecHbkBsl.useDocker`)

When `useDocker` is true, the extension runs:

`docker exec -i -e LOG_LEVEL=… [-e INDEX_DB_PATH=…] [-e BSL_SELECT=…] [-e BSL_IGNORE=…] <container> onec-hbk-bsl lsp`

— the same environment keys as for a local binary (`extension.ts`), so log level, DB path, and rule selection match non-Docker mode. The container must already exist; mount workspace and index paths so `INDEX_DB_PATH` (if set) resolves inside the container.

## LSP Parity Checklist
- Navigation: definition, references, rename, call hierarchy
- Editor help: hover, completion, signature help, inlay hints
- Structure/UX: document symbols, workspace symbols, folding, semantic tokens
- Editing: formatting, on-type formatting, code actions
- Diagnostics: rules engine, select/ignore settings, suppression comments

## MCP Parity Checklist
- Symbol/code tools: status, find symbol, file symbols, callers/callees, references, search
- File tools: read file, format, fix, rename, workspace scan
- Metadata tools: meta object, meta collection, metadata index
- Scope boundary: MCP tools stay project-local; external help MCPs are not proxied here.

## Multi-Project Safety
- MCP tools use `workspace_root`/`config_root` where relevant.
- Index instances are cached by resolved DB path (LRU policy).
- `SymbolIndex` keeps per-db thread-local connections to avoid cross-project contamination.

## Indexing And Concurrency
- LSP workspace reindex uses single-flight scheduling:
  - no concurrent full reindex runs
  - one pending rerun is queued during active indexing
- Incremental indexer parallelizes the parse stage (SQLite writes stay serialized):
  - default worker count is `min(4, CPU count)`; override with `BSL_INDEX_PARSE_WORKERS` (capped at 32).
  - each worker uses its own Tree-sitter parser (shared parser is not thread-safe).
  - a bounded queue back-pressures parsers when commits lag — avoids holding tens of thousands of parsed trees in RAM on huge workspaces (30k+ files).

## Operational Commands
- Lint: `ruff check`
- Tests + coverage gate: `PYTHONPATH=src pytest -q`
- Benchmarks: use repository scripts or dedicated test tooling; benchmark
  helpers are not part of the product CLI.
- VSCode extension compile: `npm run compile` (in `vscode-extension`)

## Release Go/No-Go
- `ruff check` passes.
- `PYTHONPATH=src pytest -q` passes with coverage threshold.
- If extension changed, `npm run compile` passes.
- Compatibility oracle checks for selected release corpora have no message, severity, or anchor mismatches.
- Bench output is collected and reviewed (cold/warm index, diagnostics timing).
