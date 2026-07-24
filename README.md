# 1C HBK BSL

Инструменты для разработки на платформе **«1С:Предприятие» / BSL**: расширение
для VS Code и Cursor, CLI-линтер, форматтер, а также LSP- и MCP-серверы для
локальных интеграций.

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![Security](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/security.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/security.yml)
[![GitHub Release](https://img.shields.io/github/v/release/mussolene/1c_hbk_bsl?sort=semver)](https://github.com/mussolene/1c_hbk_bsl/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![VS Marketplace](https://img.shields.io/badge/VS%20Marketplace-install-007ACC?logo=visualstudiocode&logoColor=white)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![Python](https://img.shields.io/pypi/pyversions/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Что это

`onec-hbk-bsl` помогает держать BSL-код в порядке:

- показывает диагностики в редакторе и CLI;
- включает 180 публичных диагностических правил;
- форматирует `.bsl` / `.os`;
- даёт навигацию, hover, completion, rename и inlay hints через LSP;
- умеет отдавать SARIF/JSON для CI;
- предоставляет MCP-инструменты для локальных AI-ассистентов.

Проект не запускает Java-анализатор в рантайме. Публичный контракт продукта:
коды правил `BSL###`, файл `onec-hbk-bsl.toml`, интерфейсы CLI/LSP/MCP и
расширение VS Code.

При установке из PyPI требуется Python 3.12 или новее. Платформенные VSIX
содержат готовый бинарный файл и не требуют системного Python. Актуальное
состояние подтверждают CI, проверка безопасности и артефакты конкретного
релиза.

## Быстрый старт

### VS Code / Cursor

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте каталог с исходниками 1С.
3. Дождитесь запуска сервера: диагностики появятся в Problems, а форматирование
   и навигация заработают через LSP.

Поддерживаются VS Code / Cursor с API VS Code 1.85+ и платформенные сборки для
macOS Apple Silicon, macOS Intel, Linux x64 и Windows x64.

Настройки редактора, команды и порядок поиска сервера описаны в
[руководстве по расширению](vscode-extension/README.md).

### CLI

```bash
uv tool install onec-hbk-bsl

onec-hbk-bsl check .
onec-hbk-bsl format . --check
onec-hbk-bsl check . --format sarif > bsl-results.sarif
```

Установка через `pip`:

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
Основные правила разрешения настроек:

- явный параметр → переменная окружения → конфигурация проекта → встроенное
  значение по умолчанию;
- `jobs = 0` включает адаптивное выполнение, а `jobs = 1` — последовательное;
- `index-exclude` управляет областью навигации и по умолчанию наследует
  `exclude`;
- после изменения области индекса выполните `onec-hbk-bsl index . --force`.

Полный контракт конфигурации и публичных интерфейсов:
[Public surface](docs/public-surface.md#product-contract).

## Диагностики и подавления

`BSL###` — стабильный код правила для вывода, `--select`, `--ignore`,
`onec-hbk-bsl.toml` и подавляющих комментариев `noqa`. Совместимые имена из
существующих BSL-проектов, например `LineLength`, также принимаются, но в
результатах всегда выводится код `BSL###`.

```bsl
Пароль = "dev_only";  // noqa: BSL012
// BSLLS:MethodSize-off
```

Полный перечень: [справочник диагностических правил](docs/diagnostic-rules.md).

## Основные команды

| Задача | Команда |
|---|---|
| Проверить проект | `onec-hbk-bsl check .` |
| Получить SARIF для CI | `onec-hbk-bsl check . --format sarif > bsl-results.sarif` |
| Создать или применить baseline-файл | `onec-hbk-bsl check . --update-baseline bsl-baseline.json` / `--baseline bsl-baseline.json` |
| Проверить форматирование | `onec-hbk-bsl format . --check` |
| Запустить LSP | `onec-hbk-bsl lsp` |
| Запустить локальный MCP | `onec-hbk-bsl mcp --stdio --workspace /path/to/project` |
| Проверить состояние индекса | `onec-hbk-bsl index . --status` |
| Пересобрать индекс | `onec-hbk-bsl index . --force` |

Режимы индекса: `off`, `symbols` и `full`. Перед `--clean` остановите LSP и MCP.
Операционные подробности приведены в
[Production notes](docs/Production-Notes.md#indexing-and-concurrency).

## Python и пакеты

```python
from onec_hbk_bsl import check_files

diagnostics = check_files(["src/Модуль.bsl"], jobs=1)
for diagnostic in diagnostics:
    print(diagnostic.code, diagnostic.file, diagnostic.line)
```

Публикуются два PyPI-дистрибутива:

| Пакет | Назначение |
|---|---|
| `onec-hbk-bsl-core` | CLI, форматтер, диагностики, Python API и LSP без MCP-зависимостей |
| `onec-hbk-bsl` | Полный совместимый пакет поверх `onec-hbk-bsl-core[mcp]` той же версии |

## Место в экосистеме

`onec-hbk-bsl` отвечает за анализ и безопасное изменение кода в текущей рабочей
области. Централизованную справку предоставляет
[`onec-context-mcp`](https://github.com/mussolene/onec-context-mcp), контекстные
пакеты конкретной версии проекта собирает
[`onec-context-toolkit`](https://github.com/mussolene/onec-context-toolkit), а
воспроизводимой средой выполнения управляет
[`1c-develop`](https://github.com/mussolene/1c-develop).

Сценарии совместного использования и правила выбора авторитетного источника
описаны в единой
[карте границ продукта](docs/architecture.md#product-boundaries-and-deployment-map).

## Документация

Канонические владельцы фактов и полный индекс закреплены в
[Documentation ownership](docs/public-surface.md#documentation-ownership).

| Документ | Роль |
|---|---|
| [VS Code extension guide](vscode-extension/README.md) | Настройки и поведение расширения VS Code / Cursor |
| [Diagnostic rules](docs/diagnostic-rules.md) | Генерируемый справочник правил |
| [Public surface](docs/public-surface.md) | Публичный контракт CLI, Python, LSP, MCP и пакетов |
| [Architecture](docs/architecture.md) | Архитектура сервера, анализатора и границы продукта |
| [Production notes](docs/Production-Notes.md) | Эксплуатационные инструкции, релизные проверки и датированные снимки |
| [Security policy](SECURITY.md) | Поддерживаемые версии и приватный канал для сообщений об уязвимостях |
| [Third-party notices](docs/THIRD_PARTY_NOTICES.md) | Зависимости, лицензии и происхождение данных |

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
