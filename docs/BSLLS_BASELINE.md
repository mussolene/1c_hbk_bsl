# Офлайн-эталон диагностик BSLLS (для сравнения с onec-hbk-bsl)

**onec-hbk-bsl** не вызывает **bsl-language-server** (JAR) в рантайме. Чтобы сверять набор предупреждений с BSLLS, эталон собирается **отдельно** — вручную или скриптом у разработчика — и сохраняется как JSON.

## Что нужно локально

- Установленный или собранный [bsl-language-server](https://github.com/1c-syntax/bsl-language-server) (часто клон в `.nosync/bsl-language-server`).
- Один и тот же корень workspace (например, корень выгрузки конфигурации из EDT).
- Воспроизводимый профиль правил: файл `.bsl-language-server.json` в корне workspace (или эквивалентные настройки в IDE).

## Снятие снимка

1. Откройте проект в редакторе с подключённым BSL Language Server **или** используйте возможности вашей сборки BSLLS для анализа каталога (зависит от версии JAR и обвязки).
2. Экспортируйте список диагностик по интересующим `.bsl` (Problems / вывод анализатора) в структурированный вид.
3. Сохраните JSON в формате, совместимом со [схемой baseline](../tests/fixtures/diag_baseline/README.md) (минимум: `file`, `line`, `code`).

Альтернатива: через MCP **MCP-LSP-bridge** и инструмент `document_diagnostics` по `file://` URI — сохраните ответ в файл и при необходимости преобразуйте в упрощённый baseline.  
**Важно:** URI в bridge часто **не совпадают** с путями на хосте — см. [LSP_BRIDGE_PATH_MAPPING.md](LSP_BRIDGE_PATH_MAPPING.md) и скрипт `scripts/host_to_lsp_bridge_uri.py`.

## Сравнение с onec-hbk-bsl

После сохранения baseline-файла:

```bash
PYTHONPATH=src python scripts/compare_diag_baseline.py \
  --baseline path/to/baseline.json \
  --workspace /path/to/same/workspace \
  --files path/to/File.bsl
```

Скрипт запускает `DiagnosticEngine` с теми же переменными `BSL_SELECT` / `BSL_IGNORE`, что и в окружении (или задайте их явно в shell перед запуском).

## Связь с документацией

- Граница проектов (без делегирования в BSLLS): [architecture.md](architecture.md#отношение-к-bsl-language-server-bslls).
- Матрица правил: [bsl_rules_matrix.md](bsl_rules_matrix.md).
