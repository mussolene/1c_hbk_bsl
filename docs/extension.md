# <span class="doc-lang doc-lang-ru">Расширение VS Code / Cursor</span><span class="doc-lang doc-lang-en">VS Code / Cursor extension</span>

<div class="doc-lang doc-lang-ru" markdown="1">

Расширение `mussolene.1c-hbk-bsl` добавляет в VS Code и Cursor полноценную
поддержку BSL. В платформенные VSIX уже включён сервер, поэтому отдельная
установка Python или Toolkit обычно не нужна.

[Установить из VS Marketplace](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl){ .md-button .md-button--primary }
[Скачать VSIX](https://github.com/mussolene/1c_hbk_bsl/releases){ .md-button }

## Требования и первый запуск

1. Используйте VS Code или Cursor с API VS Code 1.85+.
2. Установите расширение.
3. Откройте каталог с файлами `.bsl` или `.os`.
4. Дождитесь запуска сервера; найденные нарушения появятся в Problems.

Публикуются отдельные сборки для macOS Apple Silicon, macOS Intel, Linux x64 и
Windows x64.

## Возможности

| Область | Возможности |
|---|---|
| Код | подсветка синтаксиса и семантическая подсветка |
| Диагностика | 180 правил, панель Problems и быстрые исправления |
| Форматирование | документ, выделенный диапазон и отступ при вводе |
| Навигация | определения, ссылки, символы workspace и иерархия вызовов |
| Подсказки | описание при наведении, автодополнение, сигнатуры и inlay hints |
| Рефакторинг | переименование и быстрые действия |

## Рекомендуемые настройки

```json
{
  "[bsl]": {
    "editor.defaultFormatter": "mussolene.1c-hbk-bsl",
    "editor.formatOnSave": true,
    "editor.formatOnType": true,
    "editor.tabSize": 4,
    "editor.insertSpaces": false
  }
}
```

## Настройки расширения

| Ключ | Назначение |
|---|---|
| `onecHbkBsl.serverPath` | Явный путь к `onec-hbk-bsl`; обычно оставьте значение по умолчанию |
| `onecHbkBsl.indexDbPath` | Пользовательский путь к SQLite-индексу |
| `onecHbkBsl.indexMode` | `project`, `off`, `symbols` или `full` |
| `onecHbkBsl.indexMaxBytes` | Максимальный размер индекса; `-1` читает конфигурацию проекта |
| `onecHbkBsl.logLevel` | `debug`, `info`, `warning` или `error` |
| `onecHbkBsl.diagnostics.enabled` | Включает диагностики при наборе |
| `onecHbkBsl.diagnostics.select` | Оставляет только перечисленные правила |
| `onecHbkBsl.diagnostics.ignore` | Исключает перечисленные правила |
| `onecHbkBsl.useDocker` | Запускает LSP в уже работающем Docker-контейнере |
| `onecHbkBsl.dockerContainer` | Имя Docker-контейнера |

Коды правил и совместимые псевдонимы перечислены в
[каталоге диагностик](diagnostic-rules.md). Настройки анализа проекта лучше
хранить в `onec-hbk-bsl.toml`, а настройки запуска сервера и редактора — в
VS Code Settings.

Сообщение в панели Problems содержит конкретную причину срабатывания, например
имя устаревшего метода и рекомендуемую замену. Повторения с одинаковыми кодом и
причиной объединяются в одно сообщение с дополнительными расположениями.
Разные причины одного правила показываются отдельно.

После изменения пути к серверу или настроек диагностик выполните
`Developer: Reload Window`.

## Команды

Палитра команд содержит:

- `1C HBK BSL: Reindex Workspace`;
- `1C HBK BSL: Reindex Current File`;
- `1C HBK BSL: Show Index Status`;
- `1C HBK BSL: Show Server Log`.

## Как выбирается сервер

Расширение проверяет источники в следующем порядке:

1. явный `onecHbkBsl.serverPath`;
2. бинарник, включённый в VSIX;
3. `onec-hbk-bsl` из `PATH`;
4. ранее загруженный бинарник в storage расширения;
5. подходящий бинарник из GitHub Release.

В обычной установке используется включённый в VSIX бинарник.

## Устранение проблем

- Откройте `1C HBK BSL: Show Server Log`.
- Проверьте, что workspace содержит `.bsl` или `.os`.
- Проверьте `onec-hbk-bsl.toml`, `diagnostics.select` и `diagnostics.ignore`.
- После крупных изменений выполните `1C HBK BSL: Reindex Workspace`.
- Для собственного сервера укажите полный путь в `onecHbkBsl.serverPath`.

</div>

<div class="doc-lang doc-lang-en" markdown="1">

The `mussolene.1c-hbk-bsl` extension adds complete BSL support to VS Code and
Cursor. Platform-specific VSIX packages already include the server, so a
separate Python or Toolkit installation is normally unnecessary.

[Install from VS Marketplace](https://marketplace.visualstudio.com/items?itemName=mussolene.1c-hbk-bsl){ .md-button .md-button--primary }
[Download a VSIX](https://github.com/mussolene/1c_hbk_bsl/releases){ .md-button }

## Requirements and first run

1. Use VS Code or Cursor with VS Code API 1.85+.
2. Install the extension.
3. Open a folder containing `.bsl` or `.os` files.
4. Wait for the server to start; findings appear in Problems.

Separate builds are published for macOS Apple Silicon, macOS Intel, Linux x64,
and Windows x64.

## Features

| Area | Features |
|---|---|
| Code | syntax highlighting and semantic tokens |
| Diagnostics | 180 rules, Problems, and quick fixes |
| Formatting | document, range, and on-type indentation |
| Navigation | definition, references, workspace symbols, and call hierarchy |
| Assistance | hover, completion, signature help, and inlay hints |
| Refactoring | rename and code actions |

## Recommended settings

```json
{
  "[bsl]": {
    "editor.defaultFormatter": "mussolene.1c-hbk-bsl",
    "editor.formatOnSave": true,
    "editor.formatOnType": true,
    "editor.tabSize": 4,
    "editor.insertSpaces": false
  }
}
```

## Extension settings

| Key | Purpose |
|---|---|
| `onecHbkBsl.serverPath` | Explicit `onec-hbk-bsl` path; normally keep the default |
| `onecHbkBsl.indexDbPath` | Custom SQLite index path |
| `onecHbkBsl.indexMode` | `project`, `off`, `symbols`, or `full` |
| `onecHbkBsl.indexMaxBytes` | Index size limit; `-1` reads project configuration |
| `onecHbkBsl.logLevel` | `debug`, `info`, `warning`, or `error` |
| `onecHbkBsl.diagnostics.enabled` | Enables diagnostics while editing |
| `onecHbkBsl.diagnostics.select` | Runs only the listed rules |
| `onecHbkBsl.diagnostics.ignore` | Excludes the listed rules |
| `onecHbkBsl.useDocker` | Starts LSP in an existing Docker container |
| `onecHbkBsl.dockerContainer` | Docker container name |

Rule codes and compatible aliases are listed in the
[diagnostic catalog](diagnostic-rules.md). Keep project analysis settings in
`onec-hbk-bsl.toml` and server/editor startup settings in VS Code Settings.

After changing the server path or diagnostic settings, run
`Developer: Reload Window`.

## Commands

The Command Palette provides:

- `1C HBK BSL: Reindex Workspace`;
- `1C HBK BSL: Reindex Current File`;
- `1C HBK BSL: Show Index Status`;
- `1C HBK BSL: Show Server Log`.

## Server resolution

The extension checks these sources in order:

1. explicit `onecHbkBsl.serverPath`;
2. the binary bundled in the VSIX;
3. `onec-hbk-bsl` from `PATH`;
4. a previously downloaded binary in extension storage;
5. a matching binary from a GitHub Release.

A normal installation uses the binary bundled in the VSIX.

## Troubleshooting

- Open `1C HBK BSL: Show Server Log`.
- Confirm that the workspace contains `.bsl` or `.os` files.
- Check `onec-hbk-bsl.toml`, `diagnostics.select`, and `diagnostics.ignore`.
- Run `1C HBK BSL: Reindex Workspace` after large project changes.
- Set an absolute `onecHbkBsl.serverPath` when using a custom server.

</div>
