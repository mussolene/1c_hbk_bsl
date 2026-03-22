# Сопоставление путей: хост ↔ MCP `MCP-LSP-bridge` (URI внутри `/projects`)

В среде Cursor с **devcontainer / смонтированным workspace** языковой сервер BSL и MCP **MCP-LSP-bridge** работают с **другими `file://` URI**, чем абсолютные пути на macOS/Linux хосте.

## Правило (один корень workspace)

Пусть:

- **`HOST_WS`** — корень той же выгрузки на машине, что индексирует **onec-hbk-bsl** (переменная `WORKSPACE_ROOT`, аргумент `workspace_root` в MCP).
- **`BRIDGE_PREFIX`** — префикс URI, под которым этот корень виден LSP внутри среды (часто **`file:///projects`**).

Тогда для любого файла под корнем:

```text
относительный путь = relative(HOST_FILE, HOST_WS)
URI для bridge      = BRIDGE_PREFIX + "/" + encode_path_segments(relative)
```

Обратное преобразование:

```text
relative = путь после BRIDGE_PREFIX (сегменты URL-decode)
HOST_FILE = HOST_WS / relative
```

**Важно:** кириллица и пробелы в сегментах пути в URI должны быть **percent-encoded** (`urllib.parse.quote` по сегментам).

## Пример (схема)

| Роль | Значение |
|------|----------|
| `HOST_WS` | `/path/to/your/workspace` (корень проекта на хосте) |
| `BRIDGE_PREFIX` | `file:///projects` |
| Файл на хосте | `/path/to/your/workspace/src/CommonModules/MyModule/Ext/Module.bsl` |
| URI для `document_diagnostics` | `file:///projects/src/CommonModules/.../Module.bsl` (сегменты с кириллицей — в URL-encoding) |

Если передать **хостовый** `file:///Users/...` или `file:///home/...` без согласования с тем, что открыто в LSP, bridge часто возвращает **0 диагностик** — документ не совпадает с workspace сервера. Для **onec-hbk-bsl** используйте абсолютные пути на хосте и тот же `workspace_root=HOST_WS`, что и у индексатора.

## Утилита в репозитории

```bash
PYTHONPATH=src python scripts/host_to_lsp_bridge_uri.py \
  --host-workspace /path/to/your/workspace \
  /path/to/your/workspace/src/CommonModules/MyModule/Ext/Module.bsl
```

Вывод: строка `BRIDGE_URI=` для вставки в `document_diagnostics` и опционально `HOST_PATH=` для проверки обратного соответствия.

## См. также

- [BSLLS_BASELINE.md](BSLLS_BASELINE.md) — офлайн-сверка с BSLLS.
- [Production-Notes.md](Production-Notes.md) — `WORKSPACE_ROOT`, `INDEX_DB_PATH`.
