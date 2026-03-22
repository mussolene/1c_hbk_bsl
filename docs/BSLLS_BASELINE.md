# Офлайн-эталон диагностик (сравнение с BSLLS)

**onec-hbk-bsl** не вызывает Java **bsl-language-server** в рантайме. Чтобы сверять предупреждения с эталоном BSLLS, снимок собирается **отдельно** и сохраняется как JSON.

## Локально

- JAR анализатора из экосистемы 1c-syntax (см. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). Путь к JAR: переменная окружения **`BSLLS_JAVA`** / **`BSLLS_JAR`** по вашей среде.
- Один корень workspace и воспроизводимый профиль правил (например `.bsl-language-server.json` в корне).

## Снятие снимка

1. Проанализируйте нужные `.bsl` средствами BSLLS (IDE или CLI вашей сборки).
2. Сохраните результат в JSON, совместимый со [схемой baseline](../tests/fixtures/diag_baseline/README.md).

При использовании внешнего **MCP→LSP** учитывайте согласование URI workspace и хоста — [LSP_BRIDGE_PATH_MAPPING.md](LSP_BRIDGE_PATH_MAPPING.md).

## Сравнение с onec-hbk-bsl

Запустите движок тем же набором правил, что и для эталона (`BSL_SELECT` / `BSL_IGNORE`), и сравните наборы `(файл, строка, код)` с baseline. Удобная точка входа: `onec-hbk-bsl --check` по тем же файлам и workspace.

## Связанные документы

- [architecture.md](architecture.md) — отношение к справочнику правил.
- [bsl_rules_matrix.md](bsl_rules_matrix.md).
- [BSLLS_PARITY.md](BSLLS_PARITY.md) — намеренные отличия по кодам.
