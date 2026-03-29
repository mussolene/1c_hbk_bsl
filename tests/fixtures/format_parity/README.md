# Фикстуры паритета форматтера

Используются `format_compare_bslls.py` и (вместе с `diag_baseline/sample.bsl`) `compare_diag_two_servers.py` через `scripts/run_bslls_parity.sh`.

- **Формат:** оба `.bsl` здесь должны совпадать с BSLLS `format` (при наличии JAR).
- **Диагностики:** `compare_diag_two_servers.py` на этих фикстурах + `diag_baseline/sample.bsl` должен давать **OK** (наборы кодов на строке совпадают с BSLLS при актуальном JAR).
