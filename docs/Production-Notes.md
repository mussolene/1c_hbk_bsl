# Production Notes

## Scope
This runbook covers production usage of:
- `onec-hbk-bsl` server (LSP + MCP + diagnostics/indexing)
- `vscode-extension` activation and binary startup behavior

**Note:** `onec-hbk-bsl` does **not** bundle or call a separate **Java BSL analyzer** at runtime. Rule-name compatibility with the common reference is documented, not a shared process; see [architecture.md](architecture.md) and [BSLLS_BASELINE.md](BSLLS_BASELINE.md).

## Startup And Activation
- VSCode extension activates on:
  - `onLanguage:bsl`
  - `onCommand:onecHbkBsl.reindexWorkspace`
  - `onCommand:onecHbkBsl.reindexCurrentFile`
  - `onCommand:onecHbkBsl.showStatus`
- Server binary resolution order:
  1. `onecHbkBsl.serverPath` (explicit filesystem path; default placeholder does not override)
  2. bundled extension binary
  3. previously downloaded binary in extension global storage
  4. release download fallback (if supported for platform)  
  (System `PATH` is not searched — set `serverPath` to a `onec-hbk-bsl` from `pip`/`uv`/build output if needed.)

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
- Incremental indexer parallelizes parse stage with bounded worker pool:
  - set `BSL_INDEX_PARSE_WORKERS` to tune
  - SQLite writes remain serialized via index API

## Operational Commands
- Lint: `ruff check`
- Tests + coverage gate: `PYTHONPATH=src pytest -q`
- Benchmarks: `PYTHONPATH=src python -m onec_hbk_bsl --bench <workspace>`
- VSCode extension compile: `npm run compile` (in `vscode-extension`)

## Release Go/No-Go
- `ruff check` passes.
- `PYTHONPATH=src pytest -q` passes with coverage threshold.
- If extension changed, `npm run compile` passes.
- Bench output is collected and reviewed (cold/warm index, diagnostics timing).
