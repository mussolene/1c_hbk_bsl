# 1C HBK BSL для VS Code / Cursor

Расширение подключает `onec-hbk-bsl` к редактору для проектов 1С:
диагностики, навигация по BSL-коду, hover, completion, rename, formatting,
semantic tokens и inlay hints.

## Быстрый Старт

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте проект с `.bsl` / `.os`.
3. Дождитесь запуска сервера: диагностики появятся в Problems.

Рекомендуемые настройки:

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

## Возможности

| Возможность | Что делает |
|---|---|
| Diagnostics | Показывает ошибки и предупреждения в Problems |
| Navigation | Definition, references, workspace symbols, call hierarchy |
| Editing | Formatting, on-type indentation, rename, quick fixes |
| Assistance | Hover, completion, signature help, inlay hints |
| Highlighting | TextMate grammar + semantic tokens |

Сервер работает как отдельный исполняемый файл `onec-hbk-bsl`. Расширение может
использовать бинарник из `PATH`, вложенный бинарник из VSIX или скачанный
релизный бинарник.

## Настройки

| Ключ | Назначение |
|---|---|
| `onecHbkBsl.serverPath` | Явный путь к `onec-hbk-bsl`; пусто/`onec-hbk-bsl` = искать автоматически |
| `onecHbkBsl.indexDbPath` | Явный путь к SQLite-индексу |
| `onecHbkBsl.logLevel` | Уровень логов сервера |
| `onecHbkBsl.diagnostics.enabled` | Включить диагностики |
| `onecHbkBsl.diagnostics.select` | Запускать только указанные правила |
| `onecHbkBsl.diagnostics.ignore` | Игнорировать указанные правила |
| `onecHbkBsl.format.indentSize` | Логический размер отступа |
| `onecHbkBsl.inlayHints.enabled` | Включить inlay hints |
| `onecHbkBsl.semanticTokens.enabled` | Включить semantic tokens |
| `onecHbkBsl.useDocker` | Запускать LSP через уже поднятый Docker-контейнер |
| `onecHbkBsl.dockerContainer` | Имя контейнера для Docker LSP |

## Конфигурация Проекта

Основной проектный конфиг сервера: `onec-hbk-bsl.toml`.

```toml
ignore = ["BSL012"]
exclude = ["vendor", "*.gen.bsl"]

[per-file-ignores]
"legacy/*.bsl" = ["BSL002", "BSL011"]
```

Настройки расширения управляют поведением редактора и запуском сервера.
Настройки проекта управляют анализом кода.

## Docker LSP

Если включить `onecHbkBsl.useDocker`, расширение запускает:

```bash
docker exec -i -e LOG_LEVEL=... <container> onec-hbk-bsl lsp
```

Контейнер должен быть уже запущен и видеть workspace по тому же пути, который
открыт в редакторе. В контейнер также передаются `INDEX_DB_PATH`, `BSL_SELECT`
и `BSL_IGNORE`, если они заданы.

## Команды

Command Palette:

- `1C HBK BSL: Reindex Workspace`
- `1C HBK BSL: Reindex Current File`
- `1C HBK BSL: Show Index Status`
- `1C HBK BSL: Show Server Log`

## Репозиторий

Исходный код и документация: <https://github.com/mussolene/1c_hbk_bsl>
