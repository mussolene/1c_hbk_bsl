# BSL Analyzer — Architecture

## Overview

BSL Analyzer is a static analysis toolkit for 1C Enterprise BSL language,
providing three interfaces over a single shared symbol index:

1. **MCP server** — exposes BSL analysis tools to Claude via FastMCP
2. **LSP server** — powers VSCode/Cursor with go-to-definition, hover, and diagnostics
3. **CLI linter** — ruff-style `bsl-analyzer --check` command

## Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      bsl-analyzer process                    │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────────────┐ │
│  │  --mcp   │   │  --lsp   │   │  --check / --index       │ │
│  │ FastMCP  │   │  pygls   │   │  CLI (rich output)        │ │
│  │ HTTP/SSE │   │  stdio   │   │                          │ │
│  └────┬─────┘   └────┬─────┘   └────────────┬─────────────┘ │
│       │              │                       │               │
│  ─────┴──────────────┴───────────────────────┴─────────────  │
│                   Analysis Layer                              │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  symbols.py  │  │ call_graph.py │  │  diagnostics.py  │  │
│  │  Symbol      │  │  Call         │  │  DiagnosticEngine│  │
│  │  extraction  │  │  build_call_  │  │  BSL001–BSL004   │  │
│  │              │  │  graph()      │  │                  │  │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────────┘  │
│         │                  │                  │               │
│  ─────────────────────────────────────────────────────────── │
│                   Indexer Layer                               │
│  ┌────────────────────┐    ┌───────────────────────────────┐  │
│  │  IncrementalIndexer│    │  FileWatcher (watchfiles)     │  │
│  │  git diff → index  │    │  debounce 500ms               │  │
│  └──────────┬─────────┘    └───────────────────────────────┘  │
│             │                                                  │
│  ┌──────────▼──────────────────────────────────────────────┐  │
│  │              SymbolIndex (SQLite WAL)                    │  │
│  │  symbols  │  symbols_fts (FTS5)  │  calls  │  git_state │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                              │
│  ─────────────────────────────────────────────────────────── │
│                   Parser Layer                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  BslParser (tree-sitter-languages["bsl"])               │  │
│  │  Fallback: _RegexTree (regex-based extraction)          │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
         ↕ STDIO                    ↕ HTTP :8051
  ┌──────────────┐           ┌──────────────────┐
  │  VSCode /    │           │   Claude (MCP)   │
  │  Cursor      │           │                  │
  └──────────────┘           └──────────────────┘
```

## Data Flow

### Indexing

```
BSL workspace on disk
        │
        ▼  (git diff --name-only <last_commit> HEAD)
Changed file list
        │
        ▼  (BslParser.parse_file)
tree-sitter Tree (or _RegexTree fallback)
        │
        ├──▶ extract_symbols() ──▶ list[Symbol]
        │                                │
        └──▶ extract_calls()  ──▶ list[Call]
                                         │
                              SymbolIndex.upsert_file()
                                         │
                                   SQLite WAL DB
```

### Query (MCP / LSP)

```
Claude / VSCode request
        │
        ▼  (e.g. bsl_find_symbol("ОбработатьЗаказ"))
SymbolIndex.find_symbol() — FTS5 or exact lookup
        │
        ▼
Formatted response (dict / LSP Location)
```

## SQLite Schema

### `symbols`

| Column       | Type    | Description                              |
|--------------|---------|------------------------------------------|
| id           | INTEGER | Primary key                              |
| name         | TEXT    | Symbol name                              |
| file_path    | TEXT    | Absolute path to source file             |
| line         | INTEGER | 1-based start line                       |
| character    | INTEGER | 0-based start column                     |
| end_line     | INTEGER | 1-based end line                         |
| end_character| INTEGER | 0-based end column                       |
| kind         | TEXT    | `procedure` / `function` / `variable`    |
| is_export    | INTEGER | 1 if declared with Экспорт/Export        |
| container    | TEXT    | Enclosing procedure/function name        |
| signature    | TEXT    | Full signature string                    |
| doc_comment  | TEXT    | Leading `//` comment block               |
| indexed_at   | REAL    | Unix timestamp of last index             |

### `symbols_fts`

FTS5 virtual table mirroring `symbols(name)` for fast prefix/substring search.

### `calls`

| Column           | Type    | Description                    |
|------------------|---------|--------------------------------|
| id               | INTEGER | Primary key                    |
| caller_file      | TEXT    | File where the call occurs     |
| caller_line      | INTEGER | 1-based line of the call       |
| caller_name      | TEXT    | Enclosing procedure name       |
| callee_name      | TEXT    | Name of the called symbol      |
| callee_args_count| INTEGER | Number of arguments passed     |

### `git_state`

| Column        | Type  | Description                          |
|---------------|-------|--------------------------------------|
| id            | INT   | Always 1 (singleton row)             |
| commit_hash   | TEXT  | Last successfully indexed commit     |
| indexed_at    | REAL  | Unix timestamp                       |
| workspace_root| TEXT  | Workspace root path                  |

## MCP Tool Reference

| Tool               | Description                                        |
|--------------------|----------------------------------------------------|
| `bsl_status`       | Index health: symbol/file counts, last commit      |
| `bsl_find_symbol`  | Search symbols by name (exact or FTS prefix)       |
| `bsl_file_symbols` | All symbols in a single file                       |
| `bsl_callers`      | Recursive callers tree up to N depth               |
| `bsl_callees`      | Symbols called by a given procedure/function       |
| `bsl_diagnostics`  | Run lint rules on a file (BSL001–BSL004)           |
| `bsl_definition`   | Definition location(s) of a symbol                 |
| `bsl_index_file`   | Force re-parse and re-index a single file          |

## LSP Capabilities

| Capability                | Status       | Notes                                |
|---------------------------|--------------|--------------------------------------|
| `textDocument/definition` | Implemented  | Index lookup                         |
| `textDocument/hover`      | Implemented  | Signature + doc comment              |
| `textDocument/documentSymbol` | Implemented | File outline                     |
| `workspace/symbol`        | Implemented  | FTS5 prefix search                   |
| `textDocument/publishDiagnostics` | Implemented | On save, BSL001–BSL004     |
| `textDocument/completion` | Planned      | Symbol name completions              |
| `textDocument/references` | Planned      | find_callers via index               |
| `textDocument/rename`     | Planned      | Workspace-wide rename                |
| `textDocument/signatureHelp` | Planned   | Parameter hints                      |

## Roadmap

### Phase 1 — Core (current)
- [x] SQLite symbol index with FTS5
- [x] Incremental git-diff indexing
- [x] tree-sitter parsing with regex fallback
- [x] MCP server (8 tools)
- [x] LSP server skeleton (definition, hover, symbols, diagnostics)
- [x] CLI linter (BSL001, BSL002, BSL004)
- [x] VSCode extension (process launcher)

### Phase 2 — Analysis
- [ ] BSL003: missing Export on public API
- [ ] Type inference for basic types (Строка, Число, Булево)
- [ ] Platform API autocomplete from `data/platform_api/`
- [ ] Signature help (parameter count/type hints)
- [ ] textDocument/references via `find_callers`

### Phase 3 — Intelligence
- [ ] Cross-file rename with workspace edit
- [ ] Dead code detection (exported but never called)
- [ ] Cyclomatic complexity metric
- [ ] Integration with 1C Help MCP (sibling project)

### Phase 4 — Ecosystem
- [ ] OneScript (.os) full support
- [ ] Configuration metadata awareness (ОМ, справочники, etc.)
- [ ] Performance: parallel file indexing
- [ ] GitHub Actions CI integration
