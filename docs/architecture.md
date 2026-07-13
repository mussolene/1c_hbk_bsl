# 1C HBK BSL — Architecture

Актуальный контракт по эксплуатации, совместимости LSP/MCP и индексации: [Production-Notes.md](Production-Notes.md).

## Overview

`onec-hbk-bsl` — статический анализ для языка 1C Enterprise BSL. Три интерфейса над общим SQLite-индексом символов, вызовов и метаданных конфигурации:

1. **MCP server** (Python MCP SDK) — инструменты для ассистентов (поиск символов, диагностики, метаданные, и др.)
2. **LSP server** (pygls) — VS Code / Cursor: определение, ссылки, переименование, дополнение, подсказки сигнатур, форматирование, диагностики
3. **CLI** — `onec-hbk-bsl check`, `index`, и т.д.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      onec-hbk-bsl process                    │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────────────┐ │
│  │   mcp    │   │   lsp    │   │   check / index          │ │
│  │   MCP    │   │  pygls   │   │  CLI (rich output)       │ │
│  │ Streamable│  │  stdio   │   │                          │ │
│  │   HTTP    │  │          │   │                          │ │
│  └────┬─────┘   └────┬─────┘   └────────────┬─────────────┘ │
│       │              │                       │               │
│  ─────┴──────────────┴───────────────────────┴─────────────  │
│                   Analysis Layer                            │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  symbols.py  │  │ call_graph.py │  │  diagnostics.py  │  │
│  │  Symbol      │  │  Call         │  │  DiagnosticEngine│  │
│  │  extraction  │  │  build_call_  │  │  Rule registry   │  │
│  │              │  │  graph()      │  │  180 public rules│  │
│  │              │  │               │  │  enabled default │  │
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
│  │  BslParser (tree-sitter-hbk grammar package)            │  │
│  │  CST-first diagnostics over shared parse artifacts       │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
         ↕ STDIO                    ↕ HTTP :8051
  ┌──────────────┐           ┌──────────────────┐
  │  VSCode /    │           │   Claude (MCP)   │
  │  Cursor      │           │                  │
  └──────────────┘           └──────────────────┘
```

Классификация правил по **фазе вызова** (строки / CST / гибрид и т.д.) и снимок в `last_metrics["rule_invoke"]`: [diagnostics_rule_invoke.md](diagnostics_rule_invoke.md) (модуль `src/onec_hbk_bsl/analysis/diagnostic/registry.py`; на исполнение правил не влияет).

## Data Flow

### Indexing

```
BSL workspace on disk
        │
        ▼  (Git tracked + untracked non-ignored, then project index-exclude)
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

- **Product token stream:** `formatter_tokens.py` provides the lexer used
  by the formatter. It recognizes preprocessor lines, comments, annotations,
  strings/query pipes, datetime literals, keywords, operators, and punctuation.
- **Formatting state:** `formatter.py` applies product indentation and spacing
  from the token stream. Range formatting formats the full document first and
  then returns the requested lines, so the selected range keeps surrounding
  token context.
- **CST helpers:** diagnostics and snapshots use `diagnostic/cst.py` for CST
  parse-error checks. Formatting no longer depends on CST indentation fallbacks.

Совместимые diagnostic aliases поддерживаются в текущем наборе тестов и правилах движка.

Политика структурных правил и CST: [cst_policy.md](cst_policy.md).

## SQLite Schema

### `symbols`

| Column       | Type    | Description                              |
|--------------|---------|------------------------------------------|
| id           | INTEGER | Primary key                              |
| name         | TEXT    | Symbol name                              |
| name_lower   | TEXT    | Case-folded name for indexed lookup      |
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

FTS5 virtual table mirroring symbol name, file path, and signature for indexed
name search.

### `calls`

| Column           | Type    | Description                    |
|------------------|---------|--------------------------------|
| id               | INTEGER | Primary key                    |
| caller_file      | TEXT    | File where the call occurs     |
| caller_line      | INTEGER | 1-based line of the call       |
| caller_character | INTEGER | 0-based call column             |
| caller_name      | TEXT    | Enclosing procedure name       |
| callee_name      | TEXT    | Name of the called symbol      |
| callee_name_lower| TEXT    | Case-folded callee name         |
| callee_args_count| INTEGER | Number of arguments passed     |

### `git_state`

| Column        | Type  | Description                          |
|---------------|-------|--------------------------------------|
| id            | INT   | Always 1 (singleton row)             |
| commit_hash   | TEXT  | Last successfully indexed commit     |
| indexed_at    | REAL  | Unix timestamp                       |
| workspace_root| TEXT  | Workspace root path                  |

### Configuration metadata

`meta_objects`, `meta_members`, and `metadata_state` store the structured 1C
configuration snapshot used by metadata-aware navigation and diagnostics.
Objects are indexed by normalized name/kind; members retain kind and type
information; `metadata_state` records the configuration fingerprint and counts.

## MCP tools (summary)

| Group | Tools |
|-------|--------|
| Contract / index | `bsl_contract_version`, `bsl_status`, `bsl_index_file` |
| Symbols & navigation | `bsl_find_symbol`, `bsl_file_symbols`, `bsl_definition`, `bsl_references`, `bsl_callers`, `bsl_callees` |
| Diagnostics & edits | `bsl_diagnostics`, `bsl_check_file`, `bsl_list_rules`, `bsl_format`, `bsl_rename`, `bsl_fix` |
| Files & search | `bsl_read_file`, `bsl_search`, `bsl_workspace_scan`, `bsl_hover` |
| Metadata | `bsl_meta_object`, `bsl_meta_collection`, `bsl_meta_index` |

`bsl_diagnostics` / `bsl_check_file` run the product diagnostic engine for a file. Optional `include_unused=true` appends **BSL-DEAD** (unused non-export symbols) when the index is populated — same signal as LSP Problems under source `onec-hbk-bsl · BSL-DEAD`. Multi-project: pass `workspace_root` / `config_root` as documented in tool handlers and [Production-Notes.md](Production-Notes.md).

MCP tools are intentionally scoped to the current BSL project workspace: code navigation,
diagnostics, formatting, fixes, search, and configuration metadata. External help/reference
MCP servers are separate integrations and are not cross-bound into `onec-hbk-bsl`.

## LSP capabilities (current)

| Capability | Status | Notes |
|------------|--------|-------|
| `textDocument/definition` | Implemented | Index lookup |
| `textDocument/hover` | Implemented | Signature + doc comment |
| `textDocument/documentSymbol` | Implemented | File outline |
| `workspace/symbol` | Implemented | FTS5 prefix search |
| `textDocument/diagnostic` | Implemented | LSP 3.17 pull diagnostics; large files complete in background and request refresh |
| `textDocument/publishDiagnostics` | Implemented | Adaptive debounced fallback for clients without pull support |
| `textDocument/completion` | Implemented | Globals + workspace + metadata-aware members |
| `textDocument/references` | Implemented | Via index |
| `textDocument/rename` / `prepareRename` | Implemented | Workspace edits |
| `textDocument/signatureHelp` | Implemented | Parameter hints |
| `textDocument/formatting` / `rangeFormatting` | Implemented | `BslFormatter` stack |
| Code lens / highlights / folding / code actions | Implemented | Editor structure and quick-fix surfaces |
| Selection ranges | Implemented | Smart structural selection |
| Semantic tokens / inlay hints | Implemented | Controlled by standard VS Code editor settings |

## Отношение к справочнику правил BSL (совместимость имён)

**onec-hbk-bsl** — отдельная кодовая база (Python, tree-sitter, свой LSP/MCP). Внешние анализаторы не вызываются в рантайме сервера; интеграция с ними относится только к внутренним исследовательским процессам разработки.

## Further work

Ongoing work and release notes: [CHANGELOG.md](../CHANGELOG.md) and project issues. Долгосрочные темы (не исчерпывающе): более глубокий вывод типов, расширенная поддержка EDT-выгрузки без Designer XML, производительность индексации на очень больших конфигурациях.
