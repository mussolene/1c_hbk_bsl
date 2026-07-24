# 1C HBK BSL — Architecture

Нормативный публичный контракт CLI/Python/LSP/MCP/package:
[public-surface.md](public-surface.md). Эксплуатационный runbook и датированные
проверки: [Production-Notes.md](Production-Notes.md). Этот документ описывает
внутреннюю архитектуру и не создаёт второй compatibility contract.

## Overview

`onec-hbk-bsl` — статический анализ для языка 1C Enterprise BSL. Три интерфейса над общим SQLite-индексом символов, вызовов и метаданных конфигурации:

1. **MCP server** (Python MCP SDK) — инструменты для ассистентов (поиск символов, диагностики, метаданные, и др.)
2. **LSP server** (pygls) — VS Code / Cursor: определение, ссылки, переименование, дополнение, подсказки сигнатур, форматирование, диагностики
3. **CLI** — `onec-hbk-bsl check`, `index`, и т.д.

## Product boundaries and deployment map

### Слои ответственности

Эти проекты дополняют друг друга, но не образуют один обязательный монолит:

| Слой | Владелец | Отвечает за | Не отвечает за |
|---|---|---|---|
| Runtime / orchestration | [`1c-develop`](https://github.com/mussolene/1c-develop) | воспроизводимый контейнер, 1С runtime, VNC/RDP, тестовые утилиты, запуск агентных инструментов | актуальность локального code index и содержание platform help |
| Shared help/context | [`onec-context-mcp`](https://github.com/mussolene/onec-context-mcp) | централизованный сервис platform help/API, standards, snippets и versioned metadata context | изменение текущего checkout, LSP и точные локальные refactoring edits |
| Source-first project context | [`onec-context-toolkit`](https://github.com/mussolene/onec-context-toolkit) | сборка и проверка version/target-bound packs из HBK и `ConfigDump`, drift, read-only export | редакторная навигация и владение runtime-контейнером |
| Local code intelligence | `onec-hbk-bsl` | диагностики, formatter, LSP/MCP/CLI, символы, вызовы, metadata XML и безопасные edits в текущем workspace | общая энциклопедия 1С, HBK ingest и runtime orchestration |

Главное правило authority: изменение кода и навигация опираются на текущий
checkout через `onec-hbk-bsl`; справочные утверждения — на version-exact
help/context; выполнение и интеграционные тесты — на выбранный 1С runtime.
Context из другой ветки или версии конфигурации не должен автоматически
становиться основанием для edit в локальном workspace.

### Deployment-сценарии

#### 1. Centralized help для команды

- Один общий `onec-context-mcp` индексирует platform help, standards и
  разрешённые versioned context datasets.
- На рабочих местах `onec-hbk-bsl` индексирует каждый локальный checkout.
- `1c-develop` не обязателен; он подключается для воспроизводимого запуска 1С
  и тестов.

Это основной командный вариант, когда дорогой HBK/knowledge ingest не нужно
повторять у каждого разработчика.

#### 2. Branch/project context

- `onec-context-toolkit` строит packs из зафиксированного `ConfigDump`/HBK и
  сохраняет target, platform/config version и source snapshot.
- Packs обновляются при изменении выбранной ветки или версии и могут
  экспортироваться как read-only runtime bundle.
- `onec-hbk-bsl` всё равно работает с локальным checkout; project pack даёт
  контекст и подтверждение, но не подменяет локальный индекс для navigation и
  edits.

Такой режим подходит базовым конфигурациям, release branches и другим
контекстам, которые меняются реже рабочего дерева.

#### 3. Local dev workspace

- `onec-hbk-bsl` запускается через extension/LSP, CLI или локальный MCP и
  следит за текущей папкой.
- Toolkit добавляется локально только когда нужны exact HBK, metadata/code/full
  packs, multi-target выбор или offline context.
- Для небольшого расширения/обработки без отдельной context-базы достаточно
  `onec-hbk-bsl`; общий help service можно подключить отдельно.

### Что подключать агенту

| Задача | Обязательный слой | Опционально | Не смешивать без явного приоритета |
|---|---|---|---|
| Редактирование и навигация в текущем BSL | `onec-hbk-bsl` | один help/context route | два code index для одного checkout |
| Вопрос по API/стандарту платформы | `onec-context-mcp` **или** toolkit platform pack | `onec-hbk-bsl` для проверки употребления в проекте | help snapshots разных версий |
| Анализ зафиксированной конфигурации/ветки | toolkit metadata/code/full pack | `onec-hbk-bsl` на соответствующем checkout | project pack другой версии как authority для edit |
| Запуск 1С, Vanessa или интеграционных тестов | `1c-develop` либо другой явно выбранный runtime | оба analysis/context слоя | считать контейнер источником актуального кода без bind mount/sync |
| CI lint/SARIF | `onec-hbk-bsl` CLI | `1c-develop` для runtime tests | общий help ingest в каждом CI job без необходимости |

Если подключены `onec-context-mcp` и toolkit одновременно, агент обязан назвать,
какой источник авторитетен для platform version, metadata target и конкретного
ответа. Молчаливое объединение результатов запрещено: одинаковые имена при
разных версиях дают правдоподобные, но неверные ответы.

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

### SDBL field identity facts

`analysis/query_field_resolver.py` строит conservative field identity facts для
статических текстов запросов. Resolver переиспользует SDBL CST из
`tree-sitter-hbk>=0.1.11` и metadata snapshot в `SymbolIndex`:

- строит отдельное alias environment для каждого `SELECT`, включая `JOIN`;
- переносит типы через временные таблицы, вложенные запросы и
  `ВЫРАЗИТЬ(...).Поле`;
- возвращает `resolved`, `ambiguous` со стабильно отсортированными кандидатами
  или `unknown`, не выбирая первый совпавший metadata type;
- запрашивает metadata object одновременно по имени и kind, поэтому
  одноимённые объекты разных коллекций не смешиваются.

Динамически собранные query strings не анализируются. Суффиксные поля
виртуальных таблиц, которых нет у базового регистра, консервативно дают
`unknown`. Это внутренняя analysis primitive; единый snapshot/revision fact
boundary и подключение к нескольким LSP/MCP/diagnostic surfaces остаются в
scope roadmap issue #37.

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

`bsl_rename` contract version 0.5 builds the same immutable exact-span
`RenamePlan` used by LSP. Dry-run responses include sorted file edits and
content hashes. `apply=true` first validates every precondition, stages all
files, and then replaces them as one transaction; a replacement failure rolls
back every file already changed. Bare-name index data cannot prove a qualified
receiver, so such calls return `receiver_ambiguity` without writing.

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
| `textDocument/rename` / `prepareRename` | Implemented | Shared exact-span `RenamePlan`; ambiguity refuses the edit |
| `textDocument/signatureHelp` | Implemented | Parameter hints |
| `textDocument/formatting` / `rangeFormatting` | Implemented | `BslFormatter` stack |
| Code lens / highlights / folding / code actions | Implemented | Editor structure and quick-fix surfaces |
| Selection ranges | Implemented | Smart structural selection |
| Semantic tokens / inlay hints | Implemented | Controlled by standard VS Code editor settings |

### Multi-root ownership and lifecycle

Each canonical workspace root owns an independent `WorkspaceState`: index,
indexer, diagnostic engine, resolved config, and monotonic index/metadata/config
revisions. Document requests are routed by the canonical file path. For nested
workspace folders the deepest containing root owns the file; duplicate/aliased
roots or any equally specific ownership are rejected explicitly.

`workspace/didChangeWorkspaceFolders` creates or retires those states without a
server restart. Retirement stops the root watcher, prevents stale contexts from
committing diagnostics, and closes the root index exactly once. Workspace
symbol results are merged in a stable name/path/range/root order. The
single-root CLI and the primary-root LSP aliases remain backward compatible;
cross-root symbol or diagnostic caches are not shared.

### Immutable semantic fact boundary

`SemanticFactSnapshot` is a surface-neutral immutable view derived from an
existing `DocumentSnapshot`; it is not another parser or semantic engine. Every
fact snapshot has a `FactRevision` containing the content hash and the
index/metadata/config revisions. Every concrete fact carries a zero-based LSP
`SourceSpan`.

The first vertical slice normalizes existing symbol, call, and query extractors.
One fact snapshot is cached per document/revision and reused by the BSL011/175
diagnostic task group, open-document LSP navigation/outline, and live-source
`RenamePlan` validation.

Query facts additionally normalize typed metadata source contexts, nullable
outer-join spans, redundant reference-dereference spans, and temporary-table
names from the existing SDBL CST helpers. BSL187/236/238 and query-aware LSP
hover/completion consume that same immutable snapshot. Metadata contexts retain
the exact metadata kind, catalog availability, deterministic candidates, and
an explicit `resolved`, `ambiguous`, or `unknown` state; consumers must not
guess through ambiguity. Text-only query style diagnostics, XML ownership
policies, and runtime-call policies remain with their existing domain facts
instead of expanding the shared boundary with diagnostic-specific fields.

Qualified call facts additionally retain the exact receiver expression/span
and bind it to the existing `BslTypeEngine` result as `resolved`, `ambiguous`,
or `unknown`. LSP hover, definition, and references use a resolved metadata
identity only when it maps to the concrete object/manager/record-set module;
they do not fall back to an unrelated exported symbol with the same name.
Ambiguous and unknown receivers therefore produce no navigation or rename
target. The MCP definition/reference tools remain explicitly name-based
because their public input has no document position; they preserve the same
no-guessing contract instead of manufacturing receiver context.

Further diagnostic rule-family migrations remain separate changes so parity
can be reviewed per bounded family.

The first bounded diagnostic follow-up is the BSL175/BSL176 deprecated-API
symbol/call batch. Both local and large-file execution paths now receive the
same `SemanticFactSnapshot.symbols/calls`; their public diagnostic signatures
(severity, message, multiplicity, and ranges) remain unchanged. The
metadata-property subcheck in BSL176 keeps its existing single targeted CST
walk because it needs structured `property_access` and index membership, not a
generic call fact.

## Отношение к справочнику правил BSL (совместимость имён)

**onec-hbk-bsl** — отдельная кодовая база (Python, tree-sitter, свой LSP/MCP). Внешние анализаторы не вызываются в рантайме сервера; интеграция с ними относится только к внутренним исследовательским процессам разработки.

## Further work

Ongoing work and release notes: [CHANGELOG.md](../CHANGELOG.md) and project issues. Долгосрочные темы (не исчерпывающе): более глубокий вывод типов, расширенная поддержка EDT-выгрузки без Designer XML, производительность индексации на очень больших конфигурациях.
