# 1C HBK BSL

Инструменты для разработки на платформе **«1С:Предприятие» / BSL**: расширение
для VS Code и Cursor, CLI-линтер, форматтер, а также LSP- и MCP-серверы для
локальных интеграций.

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![Security](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/security.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/security.yml)
[![Documentation](https://img.shields.io/badge/docs-Material-4051B5?logo=materialformkdocs&logoColor=white)](https://mussolene.github.io/1c_hbk_bsl/)
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

Проект не запускает Java-анализатор в рантайме. В репозитории выпускаются два
связанных продукта: Toolkit (`CLI`, LSP, MCP и Python API) и расширение
VS Code / Cursor со встроенным сервером.

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
[руководстве по расширению](https://mussolene.github.io/1c_hbk_bsl/extension/).

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

Полное руководство по конфигурации и публичным интерфейсам:
[Toolkit](https://mussolene.github.io/1c_hbk_bsl/public-surface/).

## Диагностики и подавления

`BSL###` — стабильный код правила для вывода, `--select`, `--ignore`,
`onec-hbk-bsl.toml` и подавляющих комментариев `noqa`. Совместимые имена из
существующих BSL-проектов, например `LineLength`, также принимаются, но в
результатах всегда выводится код `BSL###`.

```bsl
Пароль = "dev_only";  // noqa: BSL012
// BSLLS:MethodSize-off
```

Полный перечень с RU/EN-описаниями, примерами и исключениями:
[опубликованный справочник диагностических правил](https://mussolene.github.io/1c_hbk_bsl/diagnostic-rules/).

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

Эти проекты дополняют друг друга, но не требуются для установки Toolkit или
расширения.

## Документация

Полная документация публикуется на
[mussolene.github.io/1c_hbk_bsl](https://mussolene.github.io/1c_hbk_bsl/).
Она поддерживает русский и английский языки, системную светлую/тёмную тему,
полнотекстовый поиск и прямые страницы всех 180 правил.

- [Toolkit](https://mussolene.github.io/1c_hbk_bsl/public-surface/) — установка,
  CLI, конфигурация, CI, LSP и MCP.
- [Расширение VS Code / Cursor](https://mussolene.github.io/1c_hbk_bsl/extension/) —
  установка, возможности, настройки и устранение проблем.
- [Диагностические правила](https://mussolene.github.io/1c_hbk_bsl/diagnostic-rules/) —
  180 карточек с описаниями, примерами и подавлениями.
- [Security policy](SECURITY.md) и
  [third-party notices](docs/THIRD_PARTY_NOTICES.md) — безопасность, лицензии и
  происхождение данных.

RU/EN-описания диагностик адаптированы из документационного корпуса
[BSL Language Server](https://github.com/1c-syntax/bsl-language-server) и
распространяются с сохранением указанной в
[сторонних уведомлениях](docs/THIRD_PARTY_NOTICES.md) лицензии.

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
