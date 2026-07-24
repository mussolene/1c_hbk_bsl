# 1C HBK BSL для VS Code / Cursor

Расширение подключает `onec-hbk-bsl` к редактору и дает рабочий BSL-инструментарий
без отдельной настройки сервера: диагностики, форматирование, навигацию,
completion, hover, rename, semantic tokens и inlay hints.

## Быстрый Старт

1. Установите расширение `mussolene.1c-hbk-bsl`.
2. Откройте workspace с `.bsl` / `.os`.
3. Дождитесь запуска сервера. Диагностики появятся в Problems.

Требуется VS Code / Cursor с API VS Code 1.85+. Marketplace публикует отдельные
VSIX для macOS Apple Silicon, macOS Intel, Linux x64 и Windows x64. В VSIX уже
вложен исполняемый файл сервера, поэтому системный Python не нужен.

Рекомендуемые настройки workspace:

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

| Область | Что работает |
|---|---|
| Diagnostics | Ошибки, предупреждения, `Problems`, quick fixes |
| Formatting | Полный документ, range formatting, on-type indentation |
| Navigation | Definition, references, workspace symbols, call hierarchy |
| Assistance | Hover, completion, signature help, inlay hints |
| Highlighting | TextMate grammar и semantic tokens |

## Как Находится Сервер

Расширение запускает исполняемый файл `onec-hbk-bsl`. Порядок поиска:

1. `onecHbkBsl.serverPath`, если задан явный путь;
2. бинарник, вложенный в VSIX;
3. `onec-hbk-bsl` из системного `PATH`;
4. ранее скачанный релизный бинарник в storage расширения;
5. релизный бинарник для текущей платформы, если доступен.

В большинстве случаев ничего настраивать не нужно.

## Настройки

| Ключ | Назначение |
|---|---|
| `onecHbkBsl.serverPath` | Явный путь к `onec-hbk-bsl` |
| `onecHbkBsl.indexDbPath` | Путь к SQLite-индексу |
| `onecHbkBsl.indexMode` | Детализация индекса: настройки проекта, `off`, `symbols` или `full` |
| `onecHbkBsl.indexMaxBytes` | Ограничение размера индекса; `-1` читает конфиг проекта, `0` снимает ограничение |
| `onecHbkBsl.logLevel` | Уровень логов сервера |
| `onecHbkBsl.diagnostics.enabled` | Включить диагностики |
| `onecHbkBsl.diagnostics.select` | Запускать только указанные правила (`BSL###` или compatible key) |
| `onecHbkBsl.diagnostics.ignore` | Игнорировать указанные правила (`BSL###` или compatible key) |
| `onecHbkBsl.useDocker` | Запускать LSP через уже поднятый Docker-контейнер |
| `onecHbkBsl.dockerContainer` | Имя контейнера для Docker LSP |

После изменения server/diagnostic-настроек перезапустите extension host командой
`Developer: Reload Window`.

Форматирование использует стандартные `editor.tabSize` и
`editor.insertSpaces`. Inlay hints и semantic highlighting управляются
стандартными настройками `editor.inlayHints.enabled` и
`editor.semanticHighlighting.enabled`.

## Конфигурация Проекта

Настройки расширения управляют редактором и запуском сервера. Настройки анализа
лучше хранить в `onec-hbk-bsl.toml` в корне workspace:

```toml
ignore = ["BSL012"]
exclude = ["vendor", "*.gen.bsl"]

[per-file-ignores]
"legacy/*.bsl" = ["BSL002", "BSL011"]
```

Справочник правил: [Diagnostic rules](https://mussolene.github.io/1c_hbk_bsl/diagnostic-rules/).

## Команды

Command Palette:

- `1C HBK BSL: Reindex Workspace`
- `1C HBK BSL: Reindex Current File`
- `1C HBK BSL: Show Index Status`
- `1C HBK BSL: Show Server Log`

Постоянный индекс также управляется из CLI: `onec-hbk-bsl index --status`
показывает состояние, `--compact` выполняет checkpoint/VACUUM, а `--clean`
удаляет кэш после остановки LSP/MCP. Проектные значения задаются через
`index-mode` и `index-max-bytes` в `onec-hbk-bsl.toml`.
`index-exclude` независимо ограничивает файлы навигации и по умолчанию наследует
`exclude`; после его изменения выполните `Reindex Workspace`.

## Docker LSP

Если включить `onecHbkBsl.useDocker`, расширение запускает:

```bash
docker exec -i -e LOG_LEVEL=... <container> onec-hbk-bsl lsp
```

Контейнер должен быть уже запущен и видеть workspace по тому же пути, который
открыт в редакторе. В контейнер также передаются `INDEX_DB_PATH`, `BSL_SELECT`
и `BSL_IGNORE`, если они заданы.

## Если Что-то Не Работает

- Проверьте `1C HBK BSL: Show Server Log`.
- Если сервер не стартует, задайте `onecHbkBsl.serverPath` на установленный
  `onec-hbk-bsl`.
- Если диагностики не совпадают с ожиданием, проверьте `onec-hbk-bsl.toml`,
  `onecHbkBsl.diagnostics.select` и `onecHbkBsl.diagnostics.ignore`.
- После больших изменений в проекте запустите `1C HBK BSL: Reindex Workspace`.

## Репозиторий

Полная документация: <https://mussolene.github.io/1c_hbk_bsl/extension/>

Исходный код: <https://github.com/mussolene/1c_hbk_bsl>
