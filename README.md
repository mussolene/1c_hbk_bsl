# 1C HBK BSL

Инструменты для разработки на **1C Enterprise / BSL**: расширение VS Code /
Cursor, CLI-линтер, formatter, LSP-сервер и MCP-сервер для AI-агентов.

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/mussolene.1c-hbk-bsl)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![PyPI](https://img.shields.io/pypi/v/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Быстрый Гид

### VS Code / Cursor

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте проект с файлами `.bsl` / `.os`.
3. Диагностики появятся в Problems, навигация и форматирование заработают через LSP.

Рекомендуемые настройки проекта:

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

### CLI / CI

```bash
uv tool install onec-hbk-bsl
onec-hbk-bsl check .
onec-hbk-bsl check . --format sarif > bsl-results.sarif
onec-hbk-bsl format . --check
```

Для GitHub Code Scanning загрузите SARIF:

```yaml
- name: 1C HBK BSL
  run: |
    pip install onec-hbk-bsl
    onec-hbk-bsl check . --format sarif > bsl-results.sarif

- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: bsl-results.sarif
```

## Что Входит

| Поверхность | Назначение |
|---|---|
| VS Code / Cursor | Диагностики, навигация, hover, completion, rename, formatting, inlay hints |
| CLI | `check`, `format`, SARIF/JSON/text output, baseline для постепенного внедрения |
| LSP | Сервер для редакторов и локальных интеграций |
| MCP | Поиск символов, граф вызовов, диагностики, форматирование и метаданные для AI-агентов |
| Python API | `check_files(...)` и диагностический движок для встраивания |

`onec-hbk-bsl` не запускает Java-анализатор в рантайме. Совместимость с
существующими BSL-практиками поддерживается там, где она полезна: например,
комментарии `// BSLLS-off/on` в коде учитываются как suppression comments.

## Конфигурация

Основной конфиг проекта: `onec-hbk-bsl.toml`.

```toml
# onec-hbk-bsl.toml
ignore = ["BSL012"]
exclude = ["vendor", "build", "*.gen.bsl"]
format = "text"
jobs = 0

[per-file-ignores]
"legacy/*.bsl" = ["BSL002", "BSL011"]
```

Также поддерживается секция `[tool."onec-hbk-bsl"]` в `pyproject.toml`.
Явные CLI-флаги имеют приоритет над конфигом.

Подавление в коде:

```bsl
Пароль = "dev_only";  // noqa: BSL012
// BSLLS:MethodSize-off
```

## Основные Команды

```bash
# Линтинг
onec-hbk-bsl check .
onec-hbk-bsl check . --select BSL001,BSL012
onec-hbk-bsl check . --ignore BSL014

# CI / отчеты
onec-hbk-bsl check . --format json
onec-hbk-bsl check . --format sarif > bsl-results.sarif
onec-hbk-bsl check . --exit-zero

# Gradual adoption
onec-hbk-bsl check . --update-baseline bsl-baseline.json
onec-hbk-bsl check . --baseline bsl-baseline.json

# Форматирование
onec-hbk-bsl format .
onec-hbk-bsl format . --check

# Серверы и индекс
onec-hbk-bsl lsp
onec-hbk-bsl mcp --stdio --workspace /path/to/project
onec-hbk-bsl index /path/to/project
```

Полная классификация публичных, CI и внутренних команд: [docs/public-surface.md](docs/public-surface.md).

## Python API

```python
from onec_hbk_bsl import check_files

diagnostics = check_files(["src/Модуль.bsl"], jobs=1)
for diagnostic in diagnostics:
    print(diagnostic.code, diagnostic.file, diagnostic.line)
```

## Документация

| Документ | Для чего |
|---|---|
| [docs/public-surface.md](docs/public-surface.md) | Публичный контракт CLI, API, VS Code и MCP |
| [docs/architecture.md](docs/architecture.md) | Архитектура сервера, индекса и анализатора |
| [docs/Production-Notes.md](docs/Production-Notes.md) | Эксплуатация, релизы, проверки |
| [docs/metadata_registry.md](docs/metadata_registry.md) | Метаданные конфигураций 1С |
| [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) | Лицензии и источники данных |

## Разработка

```bash
git clone https://github.com/mussolene/1c_hbk_bsl
cd 1c_hbk_bsl
make install
make lint
make test
make build
```

Для локальной сборки VSIX используйте `make vsix`, чтобы в расширение попал
актуальный бинарник.

## Лицензия

MIT © 2024 1C HBK BSL Contributors
