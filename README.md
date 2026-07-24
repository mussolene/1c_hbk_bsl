# 1C HBK BSL

Инструменты для разработки на **1C Enterprise / BSL**: расширение VS Code /
Cursor, CLI-линтер, formatter, LSP-сервер и MCP-сервер для локальных
интеграций.

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/mussolene.1c-hbk-bsl)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![VS Marketplace installs](https://img.shields.io/visual-studio-marketplace/i/mussolene.1c-hbk-bsl)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![PyPI](https://img.shields.io/pypi/v/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![Python](https://img.shields.io/pypi/pyversions/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Что Это

`onec-hbk-bsl` помогает держать BSL-код в порядке:

- показывает диагностики в редакторе и CLI;
- включает 180 публичных диагностических правил;
- форматирует `.bsl` / `.os`;
- дает навигацию, hover, completion, rename и inlay hints через LSP;
- умеет отдавать SARIF/JSON для CI;
- предоставляет MCP-инструменты для локальных AI-ассистентов.

Проект не запускает Java-анализатор в рантайме. Публичный контракт продукта:
`BSL###` коды правил, `onec-hbk-bsl.toml`, CLI/LSP/MCP и VS Code extension.

Текущий релиз требует Python 3.12+ при установке из PyPI. Платформенные VSIX
содержат готовый бинарник и не требуют системного Python. Исторический,
versioned-снимок проверок v0.8.38 и методика замеров приведены в
[Production notes](docs/Production-Notes.md#verification-snapshot-v0838);
актуальный статус подтверждают CI badge и artifacts конкретного релиза.

## Место в экосистеме

`onec-hbk-bsl` — локальный code-intelligence слой для текущего checkout. Он
индексирует именно открытый workspace и владеет диагностикой, LSP-навигацией,
форматированием, rename/fix и графом вызовов. Он не является общей базой
справки по платформе и не управляет runtime-окружением.

Соседние проекты закрывают другие уровни:

| Слой | Проект | Источник истины |
|---|---|---|
| Runtime / orchestration | [`1c-develop`](https://github.com/mussolene/1c-develop) | воспроизводимый контейнер, 1С runtime, тестовые и агентные инструменты |
| Shared help/context service | [`onec-context-mcp`](https://github.com/mussolene/onec-context-mcp) | централизованные platform help, API, standards, snippets и versioned context |
| Source-first project context | [`onec-context-toolkit`](https://github.com/mussolene/onec-context-toolkit) | packs из конкретного `ConfigDump`/HBK, target/version binding и drift |
| Local BSL code intelligence | **этот репозиторий** | текущие `.bsl`/`.os`, metadata XML и локальный индекс checkout |

Обычно агенту, который меняет код, нужен `onec-hbk-bsl` и **один** подходящий
help/context route: общий `onec-context-mcp` либо project-bound packs toolkit.
`1c-develop` добавляется только когда нужен воспроизводимый 1С runtime. Не
подключайте два источника одной и той же справки/metadata без явного
приоритета: их версии и свежесть могут различаться.

Полная карта deployment-сценариев, authority и совместного подключения:
[Product boundaries and deployment map](docs/architecture.md#product-boundaries-and-deployment-map).

## Быстрый Старт

### VS Code / Cursor

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте каталог с исходниками 1С.
3. Диагностики появятся в Problems; форматирование и навигация заработают через LSP.

Поддерживаются VS Code / Cursor с API VS Code 1.85+ и платформенные сборки для
macOS Apple Silicon, macOS Intel, Linux x64 и Windows x64.

Рекомендуемые настройки workspace:

```json
{
  "[bsl]": {
    "editor.defaultFormatter": "mussolene.1c-hbk-bsl",
    "editor.formatOnSave": true,
    "editor.tabSize": 4,
    "editor.insertSpaces": false
  }
}
```

Подробнее: [vscode-extension/README.md](https://github.com/mussolene/1c_hbk_bsl/blob/main/vscode-extension/README.md).

### CLI

```bash
uv tool install onec-hbk-bsl

onec-hbk-bsl check .
onec-hbk-bsl format . --check
onec-hbk-bsl check . --format sarif > bsl-results.sarif
```

Для обычной установки через pip:

```bash
pip install onec-hbk-bsl
```

## Конфигурация

Основной файл проекта: `onec-hbk-bsl.toml`.

```toml
ignore = ["BSL012"]
exclude = ["vendor", "build", "*.gen.bsl"]
format = "text"
jobs = 0
insert-spaces = false
indent-size = 4
index-mode = "full"      # off | symbols | full
index-max-bytes = 0      # 0 = unlimited

[per-file-ignores]
"legacy/*.bsl" = ["BSL002", "BSL011"]
```

Также поддерживается секция `[tool."onec-hbk-bsl"]` в `pyproject.toml`.
CLI, Python API, LSP и MCP используют один порядок разрешения значений:
явный параметр → переменная окружения → конфиг проекта → встроенный дефолт.
Переменные окружения существуют только для уже публичных server/index
настроек: `BSL_SELECT`, `BSL_IGNORE`, `BSL_INDEX_MODE` и
`BSL_INDEX_MAX_BYTES`. Явные значения, совпадающие с дефолтами
(`--format text`, `--jobs 0`, `--no-exit-zero`, `--no-insert-spaces`),
всё равно перекрывают конфиг проекта.
`jobs = 0` включает адаптивное планирование: несколько модулей размером от
2 MiB на fork-capable ОС распределяются между file-workers, а каждый worker
получает ограниченную долю общего бюджета правил. `jobs = 1` всегда выполняет
файлы последовательно.
Python API `check_files(...)` автоматически ищет этот конфиг от первого
переданного пути; если передать `config=cfg`, он применяется как набор
дефолтов целиком. CLI `format` читает `exclude`; workspace-индекс читает
`index-exclude`, который по умолчанию наследует `exclude`, и дополнительно
учитывает Git ignore. Пустой `index-exclude` оставляет исключённые из диагностик
библиотеки доступными для hover/F12. После изменения области индекса выполните
`index --force`. Formatter читает
`insert-spaces` и `indent-size`; низкоуровневый `default_formatter.format(...)`
остаётся чистой функцией от текста и явных параметров.

## Правила

- `BSL###` — стабильный код правила для вывода, `--select`, `--ignore`,
  `onec-hbk-bsl.toml` и `// noqa: BSL###`.
- `Compatible key` — совместимый alias для существующих BSL-проектов, например
  `LineLength` или `ConsecutiveEmptyLines`.
- CLI и конфиг принимают оба вида, но выводят `BSL###`.

Справочник правил: [docs/diagnostic-rules.md](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/diagnostic-rules.md).

Подавление:

```bsl
Пароль = "dev_only";  // noqa: BSL012
// BSLLS:MethodSize-off
```

## Команды

```bash
# Диагностики
onec-hbk-bsl check .
onec-hbk-bsl check . --select BSL001,BSL012
onec-hbk-bsl check . --ignore BSL014

# Отчеты и постепенное внедрение
onec-hbk-bsl check . --format json
onec-hbk-bsl check . --format sarif > bsl-results.sarif
onec-hbk-bsl check . --update-baseline bsl-baseline.json
onec-hbk-bsl check . --baseline bsl-baseline.json

# Форматирование
onec-hbk-bsl format .
onec-hbk-bsl format . --check

# Серверы
onec-hbk-bsl lsp
onec-hbk-bsl mcp --stdio --workspace /path/to/project
onec-hbk-bsl index /path/to/project
onec-hbk-bsl index /path/to/project --mode symbols
onec-hbk-bsl index /path/to/project --status
onec-hbk-bsl index /path/to/project --compact
onec-hbk-bsl index /path/to/project --clean  # сначала остановить LSP/MCP
```

В Git-репозитории индексируются tracked-файлы и untracked-файлы, не исключённые
Git (`.gitignore`, `.git/info/exclude`, global excludes). Затем применяются
паттерны `index-exclude` из `onec-hbk-bsl.toml`; если ключ не задан, он наследует
`exclude`. Режим `symbols` не хранит граф вызовов,
`off` отключает постоянный workspace-индекс, а `full` сохраняет все cross-file
возможности. Повреждённый индекс является кэшем и удаляется для пересборки —
копии `.corrupt.*` не сохраняются. Перед `--clean` остановите LSP/MCP: writer-lock
не может обнаружить бездействующий reader или старую версию процесса с открытым файлом.

Публичная поверхность CLI/API описана в [docs/public-surface.md](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/public-surface.md).

## Python И Пакеты

```python
from onec_hbk_bsl import check_files

diagnostics = check_files(["src/Модуль.bsl"], jobs=1)
for diagnostic in diagnostics:
    print(diagnostic.code, diagnostic.file, diagnostic.line)
```

Публикуются два PyPI-дистрибутива:

| Пакет | Назначение |
|---|---|
| `onec-hbk-bsl-core` | CLI, formatter, diagnostics, Python API и LSP без MCP-зависимостей |
| `onec-hbk-bsl` | Полный совместимый пакет поверх `onec-hbk-bsl-core[mcp]` той же версии |

## Документация

Канонические владельцы фактов и полный индекс закреплены в разделе
[Documentation Ownership](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/public-surface.md#documentation-ownership).

| Документ | Роль |
|---|---|
| [VS Code extension guide](https://github.com/mussolene/1c_hbk_bsl/blob/main/vscode-extension/README.md) | Нормативные настройки и поведение расширения VS Code / Cursor |
| [Diagnostic rules](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/diagnostic-rules.md) | Генерируемый справочник правил |
| [Public surface](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/public-surface.md) | Нормативный публичный контракт CLI/Python/LSP/MCP/package |
| [Architecture](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/architecture.md) | Описательная архитектура сервера и анализатора |
| [Production notes](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/Production-Notes.md) | Runbook, release checks и датированные snapshots |
| [Security policy](https://github.com/mussolene/1c_hbk_bsl/blob/main/SECURITY.md) | Поддерживаемые версии и приватный канал для уязвимостей |
| [Third-party notices](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/THIRD_PARTY_NOTICES.md) | Зависимости, лицензии и происхождение данных |

## Разработка

```bash
git clone https://github.com/mussolene/1c_hbk_bsl
cd 1c_hbk_bsl
make install
make lint
make test
```

Для локальной сборки VSIX используйте `make vsix`.

## Лицензия

MIT © 2024 1C HBK BSL Contributors
