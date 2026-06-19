# 1C HBK BSL

Инструменты для разработки на **1C Enterprise / BSL**: расширение VS Code /
Cursor, CLI-линтер, formatter, LSP-сервер и MCP-сервер для локальных
интеграций.

[![CI](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml/badge.svg)](https://github.com/mussolene/1c_hbk_bsl/actions/workflows/ci.yml)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/mussolene.1c-hbk-bsl)](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl)
[![PyPI](https://img.shields.io/pypi/v/onec-hbk-bsl)](https://pypi.org/project/onec-hbk-bsl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Что Это

`onec-hbk-bsl` помогает держать BSL-код в порядке:

- показывает диагностики в редакторе и CLI;
- форматирует `.bsl` / `.os`;
- дает навигацию, hover, completion, rename и inlay hints через LSP;
- умеет отдавать SARIF/JSON для CI;
- предоставляет MCP-инструменты для локальных AI-ассистентов.

Проект не запускает Java-анализатор в рантайме. Публичный контракт продукта:
`BSL###` коды правил, `onec-hbk-bsl.toml`, CLI/LSP/MCP и VS Code extension.

## Быстрый Старт

### VS Code / Cursor

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте каталог с исходниками 1С.
3. Диагностики появятся в Problems; форматирование и навигация заработают через LSP.

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

[per-file-ignores]
"legacy/*.bsl" = ["BSL002", "BSL011"]
```

Также поддерживается секция `[tool."onec-hbk-bsl"]` в `pyproject.toml`.
CLI-флаги имеют приоритет над конфигом.
Python API `check_files(...)` автоматически ищет этот конфиг от первого
переданного пути; если передать `config=cfg`, он применяется как набор
дефолтов целиком. CLI `format` также читает конфиг для `exclude`,
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
```

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
| `onec-hbk-bsl` | Полный совместимый пакет поверх `onec-hbk-bsl-core[mcp]` |

## Документация

| Документ | Для чего |
|---|---|
| [VS Code extension guide](https://github.com/mussolene/1c_hbk_bsl/blob/main/vscode-extension/README.md) | Расширение VS Code / Cursor |
| [Diagnostic rules](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/diagnostic-rules.md) | Справочник правил |
| [Public surface](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/public-surface.md) | Публичный контракт CLI/API/extension |
| [Architecture](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/architecture.md) | Архитектура сервера и анализатора |
| [Production notes](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/Production-Notes.md) | Release и эксплуатационные проверки |
| [Third-party notices](https://github.com/mussolene/1c_hbk_bsl/blob/main/docs/THIRD_PARTY_NOTICES.md) | Лицензии и источники данных |

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
