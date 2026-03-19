# BSL Analyzer

Языковой сервер, линтер и MCP-сервер для **1C Enterprise / BSL** (язык 1С:Предприятие).

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/mussolene.bsl-analyzer)](https://marketplace.visualstudio.com/items?itemName=mussolene.bsl-analyzer)
[![PyPI](https://img.shields.io/pypi/v/bsl-analyzer)](https://pypi.org/project/bsl-analyzer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Возможности

| Функция | Описание |
|---|---|
| **Подсветка синтаксиса** | TextMate-грамматика: процедуры, функции, директивы `&НаКлиенте`, аннотации, встроенные запросы |
| **Диагностики в реальном времени** | Ошибки и предупреждения по мере ввода (дебаунс 0.6 с), 30+ правил |
| **Переход к определению** | `F12` — перейти к объявлению функции / процедуры / переменной |
| **Поиск использований** | `Shift+F12` — все места вызова символа по всему воркспейсу |
| **Граф вызовов** | `Shift+Alt+H` — иерархия входящих и исходящих вызовов |
| **Hover-документация** | Сигнатура + doc-комментарий при наведении на имя символа |
| **Автодополнение** | 500+ глобальных функций платформы + символы воркспейса |
| **Переименование** | `F2` — безопасное переименование символа во всём воркспейсе |
| **Форматирование** | `Shift+Alt+F` / Format on Save |
| **Семантические токены** | Расширенная подсветка поверх TextMate-грамматики |
| **Inlay Hints** | Подсказки имён параметров в вызовах функций |
| **Snippets** | 219 сниппетов: процедуры, функции, все типы метаданных 1С (RU + EN) |
| **MCP-сервер** | Поиск символов, граф вызовов, диагностики для AI-агентов (Claude и др.) |
| **CLI-линтер** | `bsl-analyzer --check` для использования в CI |
| **Инкрементальная индексация** | SQLite-индекс, обновляется только при изменении файлов |

**Производительность:** ~600 файлов/сек · <100 мс запуска · ~80 МБ RAM

---

## Установка в VSCode

Установите расширение из [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=mussolene.bsl-analyzer):

```
ext install mussolene.bsl-analyzer
```

При первом открытии `.bsl` файла расширение автоматически скачает серверный бинарник.

Для ручной настройки добавьте в `.vscode/settings.json`:

```json
{
  "[bsl]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "mussolene.bsl-analyzer",
    "editor.tabSize": 4
  },
  "bslAnalyzer.indexDbPath": "${workspaceFolder}/bsl_index.sqlite"
}
```

---

## CLI

```bash
pip install bsl-analyzer
# или
uv tool install bsl-analyzer

# Линтинг проекта
bsl-analyzer --check /path/to/1c-project

# MCP-сервер для Claude
bsl-analyzer --mcp --port 8051

# LSP-сервер для VSCode/Cursor
bsl-analyzer --lsp

# Предварительная индексация большого репозитория
bsl-analyzer --index /path/to/1c-project
```

---

## Настройки VSCode

| Параметр | По умолчанию | Описание |
|---|---|---|
| `bslAnalyzer.serverPath` | `bsl-analyzer` | Путь к исполняемому файлу сервера |
| `bslAnalyzer.indexDbPath` | `<workspace>/bsl_index.sqlite` | Путь к SQLite-индексу |
| `bslAnalyzer.logLevel` | `info` | Уровень логирования |
| `bslAnalyzer.diagnostics.enabled` | `true` | Диагностики в реальном времени |
| `bslAnalyzer.diagnostics.select` | `[]` | Запустить только указанные правила |
| `bslAnalyzer.diagnostics.ignore` | `[]` | Игнорировать указанные правила |
| `bslAnalyzer.format.indentSize` | `4` | Размер отступа |
| `bslAnalyzer.inlayHints.enabled` | `true` | Подсказки имён параметров |
| `bslAnalyzer.semanticTokens.enabled` | `true` | Семантическая подсветка |

---

## Правила диагностик

| Код | Уровень | Название | Описание |
|---|---|---|---|
| BSL001 | ERR | ParseError | Синтаксическая ошибка (tree-sitter) |
| BSL002 | WRN | MethodSize | Метод длиннее 200 строк |
| BSL004 | WRN | EmptyCodeBlock | Пустой блок `Исключение` |
| BSL005 | WRN | HardcodeNetworkAddress | Захардкоженный IP / URL |
| BSL011 | WRN | CognitiveComplexity | Когнитивная сложность > 15 |
| BSL012 | WRN | HardcodeCredentials | Захардкоженный пароль / токен |
| BSL019 | WRN | CyclomaticComplexity | Цикломатическая сложность > 10 |
| BSL033 | ERR | QueryInLoop | Запрос внутри цикла |
| BSL050 | WRN | LargeTransaction | `НачатьТранзакцию` без Зафиксировать/Отменить |
| BSL051 | WRN | UnreachableCode | Код после безусловного `Возврат` |
| BSL053 | WRN | ExecuteDynamic | `Выполнить()` — динамическое исполнение кода |

Полный список: `bsl-analyzer --list-rules`

### Подавление в коде

```bsl
Пароль = "dev_only";  // noqa: BSL012
Пароль = "dev_only";  // noqa  ← все правила на этой строке
```

---

## MCP-сервер для AI-агентов

При первом запуске сервер автоматически индексирует воркспейс в фоне если индекс пустой.

**stdio-режим** для Claude Desktop (рекомендуется):
```bash
bsl-analyzer --mcp --stdio --workspace /path/to/1c-project
```

**HTTP-режим** для удалённого доступа:
```bash
bsl-analyzer --mcp --port 8051 --workspace /path/to/1c-project
```

Конфигурация `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bsl-analyzer": {
      "command": "bsl-analyzer",
      "args": ["--mcp", "--stdio", "--workspace", "/path/to/1c-project"],
      "env": {
        "INDEX_DB_PATH": "/path/to/1c-project/bsl_index.sqlite"
      }
    }
  }
}
```

Доступные инструменты: `bsl_find_symbol`, `bsl_callers`, `bsl_callees`, `bsl_diagnostics`, `bsl_definition`, `bsl_file_symbols`, `bsl_status`, `bsl_check_file`, `bsl_list_rules`

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

## Архитектура

```
bsl-analyzer/
├── src/bsl_analyzer/
│   ├── parser/       # tree-sitter BSL
│   ├── analysis/     # символы, граф вызовов, диагностики
│   ├── indexer/      # инкрементальный SQLite-индекс (FTS5)
│   ├── lsp/          # pygls LSP-сервер
│   ├── mcp/          # MCP-сервер (fastmcp)
│   └── cli/          # CLI-интерфейс
└── vscode-extension/
    ├── src/          # TypeScript LanguageClient
    ├── syntaxes/     # TextMate грамматика
    └── snippets/     # 219 сниппетов
```

**Бинарник** собирается через [Nuitka](https://nuitka.net/) — standalone, ~40 МБ, не требует Python.

---

## Разработка

```bash
git clone https://github.com/mussolene/1c_hbk_bsl
cd 1c_hbk_bsl
make install    # установить зависимости
make test       # запустить тесты
make lint       # ruff check
make build      # собрать бинарник (Nuitka)
make lsp        # запустить LSP-сервер из исходников
```

---

## Лицензия

MIT © 2024 BSL Analyzer Contributors
