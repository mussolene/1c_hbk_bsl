# Production Notes

## Scope
This runbook covers production usage of:
- `onec-hbk-bsl` server (LSP + MCP + diagnostics/indexing)
- `vscode-extension` activation and binary startup behavior

The normative compatibility contract is
[public-surface.md](public-surface.md). This document only explains how to run
and verify that contract. When a command, setting or capability differs, update
the canonical contract and its executable checks first; do not redefine it here.

## Startup And Activation
- On VS Code 1.85+, contributed languages and commands provide activation for:
  - `onLanguage:bsl`
  - `onCommand:onecHbkBsl.reindexWorkspace`
  - `onCommand:onecHbkBsl.reindexCurrentFile`
  - `onCommand:onecHbkBsl.showStatus`
  - `onCommand:onecHbkBsl.showOutput`
- Server binary resolution order:
  1. `onecHbkBsl.serverPath` (explicit filesystem path; default placeholder does not override)
  2. bundled extension binary
  3. installed `onec-hbk-bsl` found on system `PATH`
  4. previously downloaded binary in extension global storage
  5. release download fallback (if supported for platform)

## Docker LSP (`onecHbkBsl.useDocker`)

When `useDocker` is true, the extension runs:

`docker exec -i -e LOG_LEVEL=… [-e INDEX_DB_PATH=…] [-e BSL_INDEX_MODE=…] [-e BSL_INDEX_MAX_BYTES=…] [-e BSL_SELECT=…] [-e BSL_IGNORE=…] [-e BSL_DIAGNOSTICS_ENABLED=…] <container> onec-hbk-bsl lsp`

— the same environment keys as for a local binary (`extension.ts`), so log level, DB path, and rule selection match non-Docker mode. The container must already exist; mount workspace and index paths so `INDEX_DB_PATH` (if set) resolves inside the container.

## LSP Compatibility Checklist
- Navigation: definition, references, rename, call hierarchy
- Editor help: hover, completion, signature help, inlay hints
- Structure/UX: document symbols, workspace symbols, folding, semantic tokens
- Editing: formatting, on-type formatting, code actions
- Diagnostics: rules engine, select/ignore settings, suppression comments

## MCP Compatibility Checklist
- Symbol/code tools: status, find symbol, file symbols, callers/callees, references, search
- File tools: read file, format, fix, exact-span transactional rename, workspace scan
- Metadata tools: meta object, meta collection, metadata index
- Scope boundary: MCP tools stay project-local; external help MCPs are not proxied here.
- Rename safety: dry-run and apply use one deterministic plan; collision,
  receiver ambiguity, stale index, or changed content must refuse before writes.

## Multi-Project Safety
- MCP tools use `workspace_root`/`config_root` where relevant.
- Index instances are cached by resolved DB path (LRU policy).
- `SymbolIndex` owns and closes all of its per-thread connections; instances do not share them.

## Indexing And Concurrency
- Full discovery uses `git ls-files -co --exclude-standard`: tracked files remain
  eligible, while ignored untracked files are skipped. Project `index-exclude`
  patterns are applied after Git filtering and default to `exclude` for compatibility.
  Set `index-exclude=[]` when lint-excluded dependencies must remain navigable.
  Non-Git workspaces use the filesystem fallback.
- A discovery-policy version stored in `git_state` forces one full reconciliation
  after scope semantics change, even when the Git commit itself is unchanged.
- `index-mode=off|symbols|full` (or `BSL_INDEX_MODE`) controls persistence and detail.
  `symbols` omits call edges; `off` skips persistent background indexing.
- A persistent OS file lock beside the DB permits one writer process per index.
- WAL autocheckpoint defaults to 1,000 pages; a completed workspace pass performs
  `wal_checkpoint(TRUNCATE)`. `index --compact` additionally runs `VACUUM`.
- `index-max-bytes` / `BSL_INDEX_MAX_BYTES` provides an optional hard budget (0 = unlimited).
- Stop LSP/MCP processes before `index --clean`. The command removes DB/WAL/SHM
  and legacy `.corrupt.*` while holding the writer lock; the lock prevents new-version
  writers but cannot prove that an idle reader or an older binary has no open handle.
- Corrupt cache databases are deleted and rebuilt; they are not retained as durable evidence.
- LSP workspace reindex uses single-flight scheduling:
  - no concurrent full reindex runs
  - one pending rerun is queued during active indexing
- Incremental indexer parallelizes the parse stage (SQLite writes stay serialized):
  - default worker count is `min(4, CPU count)`; override with `BSL_INDEX_PARSE_WORKERS` (capped at 32).
  - each worker uses its own Tree-sitter parser (shared parser is not thread-safe).
  - a bounded queue back-pressures parsers when commits lag — avoids holding tens of thousands of parsed trees in RAM on huge workspaces (30k+ files).

## Operational Commands
- Lint: `./.venv/bin/python -m ruff check src tests scripts`
- Format gate: `./.venv/bin/python -m ruff format --check src tests scripts`
- Tests + coverage gate: `./.venv/bin/python -m pytest -q`
- Deterministic performance gate:
  `./.venv/bin/python scripts/bench_observability.py --output
  .artifacts/performance-current.json --baseline
  benchmarks/performance-baseline-v1.json --check`. The versioned synthetic
  dataset records its seed and content hash; CI compares operation, node and
  task counts, never wall-clock time.
- Nightly performance trend: the `Performance observability` workflow records
  the same schema plus runtime/tool provenance and non-blocking wall-clock
  observations. Compare compatible JSON artifacts with
  `./.venv/bin/python scripts/bench_compare.py BEFORE.json AFTER.json`.
- Benchmark helpers are development tools and are not part of the product CLI.
- VSCode extension compile: `npm run compile` (in `vscode-extension`)

## Verification Snapshot v0.8.38

This is dated release evidence, not a performance SLA. Re-run the listed
commands before using the numbers for another version or machine.

Snapshot provenance:

- captured: 2026-07-10;
- release/source: `v0.8.38`,
  commit `d5e00ffdd03adb86b02ba62799ff28af9ed7b349`;
- Python toolchain: Python 3.12.12, pytest 9.0.2, pytest-cov 7.0.0,
  Ruff 0.15.7 and tree-sitter-hbk 0.1.10;
- delivery toolchain and runner image: preserved in
  [release run 29041130145](https://github.com/mussolene/1c_hbk_bsl/actions/runs/29041130145).

Every new snapshot must record capture date, source commit and the versions of
all tools that produced its numbers. A snapshot missing any of these fields is
historical context, not release evidence.

### Product Surface

- Runtime registry: 180 public rules; all 180 are enabled by default unless
  `select` / `ignore` narrows the set.
- Python gate on 2026-07-10: 1,532 passed, 43 skipped, 81.24% statement coverage.
- Extension gate: `npm ci`, ESLint, TypeScript typecheck, and production webpack
  build passed; npm reported 0 known vulnerabilities.
- Release assets: four standalone binaries, four platform VSIX files, and
  wheel/sdist pairs for `onec-hbk-bsl-core` and `onec-hbk-bsl`.
- Published metadata: both Python packages require Python 3.12+; the meta wheel
  pins `onec-hbk-bsl-core[mcp]==0.8.38`; core requires
  `tree-sitter-hbk>=0.1.10`.

### Diagnostics Timing

Command: `./.venv/bin/python scripts/bench_timing.py --runs=10`, cache-miss
mode, trimmed mean after warm-up. Host: Apple M1 Pro, 8 logical CPUs, 16 GiB
RAM, Python 3.12.12. Fixtures differ structurally, so do not infer linear
scaling from their names.

| Fixture lines | Mean | ms / 1,000 lines | Diagnostics |
|---:|---:|---:|---:|
| 139 | 24.7 ms | 177.8 | 40 |
| 411 | 66.0 ms | 160.6 | 120 |
| 955 | 151.0 ms | 158.1 | 280 |
| 3,131 | 491.7 ms | 157.0 | 920 |
| 5,035 | 290.0 ms | 57.6 | 1,480 |

A separate CLI process over all five fixtures (9,671 lines total) completed in
2.73 seconds wall time with 79,429,632 bytes maximum RSS on the same host. This
includes interpreter startup, file collection, analysis, and JSON serialization.

### Delivery Time

For [release v0.8.38](https://github.com/mussolene/1c_hbk_bsl/actions/runs/29041130145),
measured from workflow start (`2026-07-09 18:34:06 UTC`):

| Milestone | Elapsed |
|---|---:|
| PyPI upload recorded | 49 s |
| GitHub Release published | 4 min 14 s |
| Release workflow completed | 4 min 53 s |
| Marketplace version visible through Gallery API | 14 min 37 s |

The Marketplace value includes registry propagation after the publish command.
Release frequency is not treated as a quality metric: v0.8.18 through v0.8.38
contained 21 releases over 21.5 days, which is delivery evidence but also signals
patch churn.

## Release Go/No-Go
- `ruff check` passes.
- `./.venv/bin/python -m pytest -q` passes with coverage threshold.
- If extension changed, `npm run compile` passes.
- Diagnostic stability checks on selected release corpora preserve expected counts, severity and anchors.
- Performance output is collected and reviewed (cold/warm index, diagnostics timing).
