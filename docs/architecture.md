# BSL Analyzer — Architecture

Актуальный контракт по эксплуатации, паритету LSP/MCP и индексации: [Production-Notes.md](Production-Notes.md).

## Overview

BSL Analyzer (`onec-hbk-bsl`) — статический анализ для языка 1C Enterprise BSL. Три интерфейса над общим SQLite-индексом символов и вызовов:

1. **MCP server** (FastMCP) — инструменты для ассистентов (поиск символов, диагностики, метаданные, и др.)
2. **LSP server** (pygls) — VS Code / Cursor: определение, ссылки, переименование, дополнение, подсказки сигнатур, форматирование, диагностики
3. **CLI** — `onec-hbk-bsl --check`, `--index`, и т.д.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      onec-hbk-bsl process                    │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────────────┐ │
│  │  --mcp   │   │  --lsp   │   │  --check / --index       │ │
│  │ FastMCP  │   │  pygls   │   │  CLI (rich output)       │ │
│  │ HTTP/SSE │   │  stdio   │   │                          │ │
│  └────┬─────┘   └────┬─────┘   └────────────┬─────────────┘ │
│       │              │                       │               │
│  ─────┴──────────────┴───────────────────────┴─────────────  │
│                   Analysis Layer                            │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  symbols.py  │  │ call_graph.py │  │  diagnostics.py  │  │
│  │  Symbol      │  │  Call         │  │  DiagnosticEngine│  │
│  │  extraction  │  │  build_call_  │  │  BSL001–BSL280   │  │
│  │              │  │  graph()      │  │  (реестр; подмн. │  │
│  │              │  │               │  │   набор активен) │  │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────────┘  │
│         │                  │                  │               │
│  ─────────────────────────────────────────────────────────  │
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
│  ───────────────────────────────────────────────────────────  │
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

## Formatting

`textDocument/formatting` and `textDocument/rangeFormatting` use `BslFormatter`
(`src/onec_hbk_bsl/analysis/formatter.py`).

- **Structural block indent:** tree-sitter walk (`formatter_structural.py`),
  merged with a keyword heuristic for blank/comment/`#` lines and when the parse
  tree is a regex stub or contains ERROR nodes.
- **Multi-line expression indent (BSL LS style):** extra level after a bare `=`
  until `;`, leading `.` chains, operator context for `Если`/`Пока`/`Для` until
  `Тогда`/`Цикл`, procedure signature tracking — line-based state in `formatter.py`.
- **Token spacing in argument lists:** `formatter_ast_spacing.py` (comma spacing and related layout on valid CST).

Политика структурных правил и CST: [cst_policy.md](cst_policy.md).

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

## MCP tools (summary)

| Group | Tools |
|-------|--------|
| Contract / index | `bsl_contract_version`, `bsl_status`, `bsl_index_file` |
| Symbols & navigation | `bsl_find_symbol`, `bsl_file_symbols`, `bsl_definition`, `bsl_references`, `bsl_callers`, `bsl_callees` |
| Diagnostics & edits | `bsl_diagnostics`, `bsl_check_file`, `bsl_list_rules`, `bsl_format`, `bsl_rename`, `bsl_fix` |
| Files & search | `bsl_read_file`, `bsl_search`, `bsl_workspace_scan`, `bsl_hover` |
| Metadata | `bsl_meta_object`, `bsl_meta_collection`, `bsl_meta_index` |
| 1C Help (optional) | `bsl_1c_help_search_keyword`, `bsl_1c_help_get_topic` |

`bsl_diagnostics` runs the full diagnostic engine for a file (not limited to BSL001–BSL004). Multi-project: pass `workspace_root` / `config_root` as documented in tool handlers and [Production-Notes.md](Production-Notes.md).

## LSP capabilities (current)

| Capability | Status | Notes |
|------------|--------|-------|
| `textDocument/definition` | Implemented | Index lookup |
| `textDocument/hover` | Implemented | Signature + doc comment |
| `textDocument/documentSymbol` | Implemented | File outline |
| `workspace/symbol` | Implemented | FTS5 prefix search |
| `textDocument/publishDiagnostics` | Implemented | Debounced on change; full rule set from engine |
| `textDocument/completion` | Implemented | Globals + workspace + metadata-aware members |
| `textDocument/references` | Implemented | Via index |
| `textDocument/rename` / `prepareRename` | Implemented | Workspace edits |
| `textDocument/signatureHelp` | Implemented | Parameter hints |
| `textDocument/formatting` / `rangeFormatting` | Implemented | `BslFormatter` stack |
| Semantic tokens / inlay hints | Implemented | Configurable in extension |

## Further work

Ongoing work and release notes: [CHANGELOG.md](../CHANGELOG.md) and project issues. Долгосрочные темы (не исчерпывающе): более глубокий вывод типов, расширенная поддержка EDT-выгрузки без Designer XML, производительность индексации на очень больших конфигурациях.
