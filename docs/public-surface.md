# <span class="doc-lang doc-lang-ru">Toolkit</span><span class="doc-lang doc-lang-en">Toolkit</span>

<div class="doc-lang doc-lang-ru" markdown="1">

Toolkit — это Python-пакет и автономный исполняемый файл `onec-hbk-bsl`.
Он подходит для локальных проверок, CI, интеграции с редакторами и агентами.

## Установка

Для CLI, форматтера и Language Server:

```bash
pip install onec-hbk-bsl-core
```

Для полного набора, включая MCP:

```bash
pip install onec-hbk-bsl
```

Требуется Python 3.12+. В [GitHub Releases](https://github.com/mussolene/1c_hbk_bsl/releases)
также публикуются автономные бинарники для macOS, Linux и Windows.

## Основные команды

| Задача | Команда |
|---|---|
| Проверить проект | `onec-hbk-bsl check .` |
| Исправить безопасные нарушения | `onec-hbk-bsl check . --fix` |
| Отформатировать файлы | `onec-hbk-bsl format .` |
| Показать правила | `onec-hbk-bsl rules` |
| Создать конфигурацию | `onec-hbk-bsl init` |
| Запустить Language Server | `onec-hbk-bsl lsp` |
| Запустить локальный MCP-сервер | `onec-hbk-bsl mcp` |
| Управлять индексом | `onec-hbk-bsl index --status` |

Используйте `onec-hbk-bsl <команда> --help` для полного списка параметров.

## Конфигурация проекта

Создайте `onec-hbk-bsl.toml` в корне проекта:

```toml
select = ["BSL012", "BSL236"]
ignore = ["BSL002"]
exclude = ["vendor", "*.gen.bsl"]

[per-file-ignores]
"legacy/*.bsl" = ["BSL011"]
```

В `select` и `ignore` принимаются коды `BSL###` и совместимые псевдонимы.
Форматы подавления для конкретного правила приведены в
[каталоге диагностик](diagnostic-rules.md).

## Отчёты и CI

```bash
onec-hbk-bsl check . --format sarif > onec-hbk-bsl.sarif
onec-hbk-bsl check . --jobs 4
onec-hbk-bsl check . --baseline baseline.json
onec-hbk-bsl check . --diff --since origin/main
```

Доступны форматы `text`, `json` и `sarif`. Для постепенного внедрения можно
использовать baseline, проверку diff и `--exit-zero`.

## Language Server и MCP

Language Server предоставляет диагностики, форматирование, definition,
references, rename, hover, completion, signature help, folding, code actions,
inlay hints и semantic tokens. Обычно его запускает
[расширение VS Code / Cursor](extension.md).

Локальный MCP-сервер открывает агентам диагностику, навигацию и безопасный
план переименования в пределах указанного workspace. Запускайте его только для
доверенных локальных клиентов.

## Поддерживаемые входы

- исходные файлы `.bsl` и `.os`;
- выгрузка конфигурации из Конфигуратора в файлы;
- проекты с `onec-hbk-bsl.toml`;
- Python 3.12, 3.13 и 3.14.

</div>

<div class="doc-lang doc-lang-en" markdown="1">

The Toolkit is distributed as Python packages and the standalone
`onec-hbk-bsl` executable. It supports local checks, CI, editor integrations,
and local agents.

## Installation

For the CLI, formatter, and Language Server:

```bash
pip install onec-hbk-bsl-core
```

For the complete package including MCP:

```bash
pip install onec-hbk-bsl
```

Python 3.12+ is required. Standalone macOS, Linux, and Windows binaries are also
published in [GitHub Releases](https://github.com/mussolene/1c_hbk_bsl/releases).

## Main commands

| Task | Command |
|---|---|
| Check a project | `onec-hbk-bsl check .` |
| Apply safe fixes | `onec-hbk-bsl check . --fix` |
| Format files | `onec-hbk-bsl format .` |
| List rules | `onec-hbk-bsl rules` |
| Create a configuration | `onec-hbk-bsl init` |
| Start the Language Server | `onec-hbk-bsl lsp` |
| Start the local MCP server | `onec-hbk-bsl mcp` |
| Inspect the index | `onec-hbk-bsl index --status` |

Run `onec-hbk-bsl <command> --help` for the complete option list.

## Project configuration

Create `onec-hbk-bsl.toml` in the project root:

```toml
select = ["BSL012", "BSL236"]
ignore = ["BSL002"]
exclude = ["vendor", "*.gen.bsl"]

[per-file-ignores]
"legacy/*.bsl" = ["BSL011"]
```

Both `BSL###` codes and compatible aliases are accepted by `select` and
`ignore`. Rule-specific suppression forms are documented in the
[diagnostic catalog](diagnostic-rules.md).

## Reports and CI

```bash
onec-hbk-bsl check . --format sarif > onec-hbk-bsl.sarif
onec-hbk-bsl check . --jobs 4
onec-hbk-bsl check . --baseline baseline.json
onec-hbk-bsl check . --diff --since origin/main
```

The supported formats are `text`, `json`, and `sarif`. Baselines, diff checks,
and `--exit-zero` help with gradual adoption.

## Language Server and MCP

The Language Server provides diagnostics, formatting, definition, references,
rename, hover, completion, signature help, folding, code actions, inlay hints,
and semantic tokens. It is normally started by the
[VS Code / Cursor extension](extension.md).

The local MCP server exposes diagnostics, navigation, and safe rename plans to
agents within the configured workspace. Use it only with trusted local clients.

## Supported inputs

- `.bsl` and `.os` source files;
- Designer configuration exports;
- projects configured with `onec-hbk-bsl.toml`;
- Python 3.12, 3.13, and 3.14.

</div>
