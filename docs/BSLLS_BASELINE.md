# Офлайн-эталон диагностик BSLLS (для сравнения с onec-hbk-bsl)

**onec-hbk-bsl** не вызывает сторонний **Java-анализатор BSL** (JAR) в рантайме. Чтобы сверять набор предупреждений с эталоном, снимок собирается **отдельно** — вручную или скриптом у разработчика — и сохраняется как JSON.

## Что нужно локально

- Установленный или собранный JAR **Java-анализатора BSL** из экосистемы 1c-syntax (см. `docs/THIRD_PARTY_NOTICES.md`); путь к JAR задаётся переменной `BSLLS_JAR` или локально вне репозитория.
- Один и тот же корень workspace (например, корень выгрузки конфигурации из EDT).
- Воспроизводимый профиль правил: файл `.bsl-language-server.json` в корне workspace (или эквивалентные настройки в IDE).

## Снятие снимка

1. Откройте проект в редакторе с подключённым BSL Language Server **или** используйте возможности вашей сборки BSLLS для анализа каталога (зависит от версии JAR и обвязки).
2. Экспортируйте список диагностик по интересующим `.bsl` (Problems / вывод анализатора) в структурированный вид.
3. Сохраните JSON в формате, совместимом со [схемой baseline](../tests/fixtures/diag_baseline/README.md) (минимум: `file`, `line`, `code`).

Альтернатива: через MCP **document_diagnostics** по `file://` URI (если в вашей среде используется LSP через MCP) — сохраните ответ в файл и при необходимости преобразуйте в упрощённый baseline.  
**Важно:** URI внутри контейнера/моста часто **не совпадают** с путями на хосте — см. [LSP_BRIDGE_PATH_MAPPING.md](LSP_BRIDGE_PATH_MAPPING.md) и скрипт `scripts/host_to_lsp_bridge_uri.py`.

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

- Граница проектов: раздел «Отношение к справочнику правил» в [architecture.md](architecture.md).
- Матрица правил: [bsl_rules_matrix.md](bsl_rules_matrix.md).
