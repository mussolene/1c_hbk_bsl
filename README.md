# 1C HBK BSL

Языковой сервер, линтер и MCP-сервер для **1C Enterprise / BSL** (язык 1С:Предприятие).

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/mussolene.1c-hbk-bsl)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![PyPI](https://img.shields.io/pypi/v/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
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
| **CLI-линтер** | `onec-hbk-bsl --check` для использования в CI |
| **Инкрементальная индексация** | SQLite-индекс, обновляется только при изменении файлов |

**Производительность:** ~600 файлов/сек · <100 мс запуска · ~80 МБ RAM

---

## Установка в VSCode

Установите расширение из [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl):

```
ext install mussolene.1c-hbk-bsl
```

При первом открытии `.bsl` файла расширение автоматически скачает серверный бинарник.

Для ручной настройки добавьте в `.vscode/settings.json`:

```json
{
  "[bsl]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "mussolene.1c-hbk-bsl",
    "editor.tabSize": 4
  },
  "onecHbkBsl.indexDbPath": "/path/to/custom/onec-hbk-bsl_index.sqlite"
}
```

По умолчанию путь к БД не задаётся: индекс лежит в `.git/onec-hbk-bsl_index.sqlite` (внутри репозитория git не попадает в коммиты) или в `~/.cache/onec-hbk-bsl/<хэш>/`, если папка не в git. Ранее использовалось имя `bsl_index.sqlite` — оно по-прежнему подхватывается, если файл уже есть.

---

## CLI

```bash
pip install onec-hbk-bsl
# или
uv tool install onec-hbk-bsl

# Линтинг проекта
onec-hbk-bsl --check /path/to/1c-project

# MCP-сервер для Claude
onec-hbk-bsl --mcp --port 8051

# LSP-сервер для VSCode/Cursor
onec-hbk-bsl --lsp

# Предварительная индексация большого репозитория
onec-hbk-bsl --index /path/to/1c-project
```

---

## Настройки VSCode

| Параметр | По умолчанию | Описание |
|---|---|---|
| `onecHbkBsl.serverPath` | `onec-hbk-bsl` | Путь к бинарнику сервера; значение по умолчанию не подставляет путь из системного `PATH` — укажите полный путь к своему `onec-hbk-bsl`, либо используйте бинарник из VSIX / скачанный расширением |
| `onecHbkBsl.indexDbPath` | *(пусто)* → `.git/onec-hbk-bsl_index.sqlite` или `~/.cache/onec-hbk-bsl/…` | Явный путь к SQLite-индексу (необязательно) |
| `onecHbkBsl.logLevel` | `info` | Уровень логирования |
| `onecHbkBsl.diagnostics.enabled` | `true` | Диагностики в реальном времени |
| `onecHbkBsl.diagnostics.select` | `[]` | Запустить только указанные правила |
| `onecHbkBsl.diagnostics.ignore` | `[]` | Игнорировать указанные правила |
| `onecHbkBsl.format.indentSize` | `4` | Размер отступа |
| `onecHbkBsl.inlayHints.enabled` | `true` | Подсказки имён параметров |
| `onecHbkBsl.semanticTokens.enabled` | `true` | Семантическая подсветка |

**Панель Problems:** включите группировку по **источнику** (меню вида в заголовке Problems) — правила линтера идут как `onec-hbk-bsl`, неиспользуемые в проекте процедуры и функции (после индексации) — отдельной группой `onec-hbk-bsl · unused` (код `BSL-DEAD`, подсветка «лишнего» кода в редакторе сохраняется).

---

## Правила диагностик

| Код | Уровень | Название | Описание |
|---|---|---|---|
| BSL001 | ERR | ParseError | Синтаксическая ошибка (tree-sitter) |
| BSL002 | WRN | MethodSize | Метод длиннее 200 строк |
| BSL004 | WRN | EmptyCodeBlock | Пустой блок `Исключение` |
| BSL005 | WRN | UsingHardcodeNetworkAddress | Захардкоженный IP / URL |
| BSL011 | WRN | CognitiveComplexity | Когнитивная сложность > 15 |
| BSL012 | WRN | UsingHardcodeSecretInformation | Захардкоженный пароль / токен |
| BSL019 | WRN | CyclomaticComplexity | Цикломатическая сложность > 10 |
| BSL033 | ERR | CreateQueryInCycle | Запрос внутри цикла |
| BSL-DEAD | INF | *(индекс)* | Неиспользуемая неэкспортная процедура/функция (нет вызовов в проекте) |
| BSL050 | WRN | LargeTransaction | `НачатьТранзакцию` без Зафиксировать/Отменить |
| BSL051 | WRN | UnreachableCode | Код после безусловного `Возврат` |
| BSL053 | WRN | ExecuteExternalCode | `Выполнить()` — динамическое исполнение кода |

Полный список: `onec-hbk-bsl --list-rules`

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
onec-hbk-bsl --mcp --stdio --workspace /path/to/1c-project
```

**HTTP-режим** для удалённого доступа:
```bash
onec-hbk-bsl --mcp --port 8051 --workspace /path/to/1c-project
```

Конфигурация `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "onec-hbk-bsl": {
      "command": "onec-hbk-bsl",
      "args": ["--mcp", "--stdio", "--workspace", "/path/to/1c-project"],
      "env": {
        "INDEX_DB_PATH": "/path/to/1c-project/onec-hbk-bsl_index.sqlite"
      }
    }
  }
}
```

Доступные инструменты: `bsl_find_symbol`, `bsl_callers`, `bsl_callees`, `bsl_diagnostics`, `bsl_definition`, `bsl_file_symbols`, `bsl_status`, `bsl_check_file`, `bsl_list_rules`

---

## GitHub Actions / CI

```yaml
- name: 1C HBK BSL Lint
  run: |
    pip install onec-hbk-bsl
    onec-hbk-bsl --check . --format sarif > bsl-results.sarif

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: bsl-results.sarif
```

---

## Архитектура

```
1c_hbk_bsl/
├── src/onec_hbk_bsl/
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
make build      # собрать бинарник (Nuitka) → dist/
make extension-bin   # make build + копия в vscode-extension/bin/ (для локального VSIX)
make vsix       # extension-bin + сборка расширения + VSIX с актуальным бинарником
make lsp        # запустить LSP-сервер из исходников
```

Локальная упаковка расширения: не вызывайте `vsce package` без синхронизации `dist/` → `vscode-extension/bin/`, иначе в VSIX попадёт старый (или пустой) бинарник — см. **`make vsix`** или **`make sync-extension-bin`**.

---

## Лицензия

MIT © 2024 1C HBK BSL Contributors

Полный перечень зависимостей и заметки по лицензированию: [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md). Источники данных `data/`: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md). Аудит секретов: [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).

---

## Используемые проекты

| Проект | Лицензия | Использование |
|--------|----------|---------------|
| [vsc-language-1c-bsl](https://github.com/1c-syntax/vsc-language-1c-bsl) | MIT | Данные Platform API (`bslGlobals.json`) — глобальные функции, типы, перечисления |
| [tree-sitter-bsl](https://github.com/1c-syntax/tree-sitter-bsl) | MIT | Парсер / грамматика BSL для синтаксического анализа |
| [pygls](https://github.com/openlawlibrary/pygls) | Apache 2.0 | LSP-сервер (Python Language Server Protocol framework) |
| [lsprotocol](https://github.com/microsoft/lsprotocol) | MIT | LSP-типы (Python) |
| [fastmcp](https://github.com/jlowin/fastmcp) | Apache 2.0 | MCP-сервер |
| [bsl-language-server](https://github.com/1c-syntax/bsl-language-server) | LGPL v3 | Справочник диагностик BSL (коды BSL*) — код не используется |
