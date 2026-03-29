# Фикстуры паритета форматтера

Используются `format_compare_bslls.py` и (вместе с `diag_baseline/sample.bsl`) `compare_diag_two_servers.py` через `scripts/run_bslls_parity.sh`.

- **Формат:** оба `.bsl` здесь должны совпадать с BSLLS `format` (при наличии JAR).
- **Диагностики:** на `sample_module.bsl` (одна строка `А = 1;`) BSLLS может дать **BSL007** на уровне модуля, тогда как onec — нет; на `procedure_export.bsl` возможны отличия по **BSL007** на строке с выражением — это кандидаты на дальнейшую сверку движка.
