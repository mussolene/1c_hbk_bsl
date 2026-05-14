# Production Notes

## Scope
This runbook covers production usage of:
- `onec-hbk-bsl` server (LSP + MCP + diagnostics/indexing)
- `vscode-extension` activation and binary startup behavior

**Note:** `onec-hbk-bsl` does **not** bundle or call a separate Java analyzer at runtime.

## Public Compatibility Contract
- Default diagnostics use the BSLLS-compatible public rule set. There are no user-facing strict/legacy/compat mode switches.
- `BSL_SELECT` / `BSL_IGNORE` and `onecHbkBsl.diagnostics.select` / `ignore` only filter the default rule set.
- Formatting uses the BSLLS-oriented defaults exposed by the extension: tabs for `[bsl]`, logical indent width 4, safe on-type indentation on newline only.
- Diagnostics/indexing parser fallbacks are internal resilience mechanisms for malformed or partially parsed documents; they are not separate product modes and should not be documented as user-selectable behavior.
- The formatter has no parser/line/CST fallback mode: it formats from the BSLLS-compatible token stream.

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

`docker exec -i -e LOG_LEVEL=… [-e INDEX_DB_PATH=…] [-e BSL_SELECT=…] [-e BSL_IGNORE=…] <container> onec-hbk-bsl --lsp`

— the same environment keys as for a local binary (`extension.ts`), so log level, DB path, and rule selection match non-Docker mode. The container must already exist; mount workspace and index paths so `INDEX_DB_PATH` (if set) resolves inside the container.

## LSP Parity Checklist
- Navigation: definition, references, rename, call hierarchy
- Editor help: hover, completion, signature help, inlay hints
- Structure/UX: document symbols, workspace symbols, folding, semantic tokens
- Editing: formatting, on-type formatting, code actions
- Diagnostics: rules engine, select/ignore settings, BSLLS suppression comments

## MCP Parity Checklist
- Symbol/code tools: status, find symbol, file symbols, callers/callees, references, search
- File tools: read file, format, fix, rename, workspace scan
- Metadata tools: meta object, meta collection, metadata index
- Help tools: 1c-help keyword search and topic fetch (deterministic ordering/caching)

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
- Benchmarks: `PYTHONPATH=src python3 -m onec_hbk_bsl --bench <workspace>`
- VSCode extension compile: `npm run compile` (in `vscode-extension`)

## Release Go/No-Go
- `ruff check` passes.
- `PYTHONPATH=src pytest -q` passes with coverage threshold.
- If extension changed, `npm run compile` passes.
- BSLLS oracle parity checks for selected release corpora have no `only_ours`, `only_bslls`, message, severity, or anchor mismatches.
- Bench output is collected and reviewed (cold/warm index, diagnostics timing).
