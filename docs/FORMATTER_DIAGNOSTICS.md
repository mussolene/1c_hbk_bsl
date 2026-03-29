# Согласование форматтера и диагностик

`BslFormatter` (`formatter.py` + `formatter_structural.py`, `formatter_ast_spacing.py`) и движок диагностик (`diagnostics.py`) решают разные задачи, но часть правил BSLLS относится к **стилю оформления**. Ниже — зафиксированные связи и как их проверять.

## Правила «после полного format не должны срабатывать»

| Код | Имя BSLLS | Что делает форматтер | Проверка |
|-----|-----------|----------------------|----------|
| BSL024 | SpaceAtStartComment | Нормализует пробел после `//` на полных строках комментария; общая логика «когда ругаться» — `bsl024_should_report_line` (движок + LSP quick-fix) | `tests/test_formatter_diagnostics_parity.py` |
| BSL055 | ConsecutiveEmptyLines | Схлопывает подряд идущие пустые строки до **одной** (`_normalize_blank_lines`; тот же порог, что `DiagnosticEngine.MAX_BLANK_LINES`) | см. выше + `tests/test_formatter.py` |
| BSL136 | MissingSpaceBeforeComment | Пробел перед хвостовым `//` на строке кода (`_process_code_line_static`) | см. выше |
| BSL216 | MissingSpace | Пробелы вокруг `=` и операторов сравнения в сегментах кода (`_add_operator_spaces`) | см. выше |

**По умолчанию выключены** (шум или дубли): **BSL120** (хвостовые пробелы), **BSL121** (табы) — форматтер при этом может использовать табы, если LSP/CLI передал `insert_spaces=False` (см. паритет с BSLLS CLI в `format_compare_bslls.py`).

## Офлайн-сверка с BSLLS

Скрипты лежат в **Cursor skill** (каталог не в git): `.cursor/skills/bsl-ast-mcp-skill/checks/`.

| Скрипт | Назначение |
|--------|------------|
| `format_compare_bslls.py` | `BslFormatter` vs `java -jar … format` |
| `compare_diag_two_servers.py` | BSLLS `analyze` vs `onec-hbk-bsl --check` |

Из корня репозитория (нужен JAR, см. [BSLLS_BASELINE.md](BSLLS_BASELINE.md)):

```bash
chmod +x scripts/run_bslls_parity.sh
./scripts/run_bslls_parity.sh
```

Логи и diff: **`.nosync/reports/`**. Если skill не развёрнут, задайте `PARITY_CHECKS=/путь/к/checks`.

Вручную, те же вызовы:

```bash
export PYTHONPATH=src
python3 .cursor/skills/bsl-ast-mcp-skill/checks/format_compare_bslls.py \
  --fixtures tests/fixtures/format_parity
python3 .cursor/skills/bsl-ast-mcp-skill/checks/compare_diag_two_servers.py \
  tests/fixtures/diag_baseline/sample.bsl \
  tests/fixtures/format_parity/sample_module.bsl \
  tests/fixtures/format_parity/procedure_export.bsl \
  -o .nosync/reports/compare_diag.txt --summary-codes --stats
```

## См. также

- [BSLLS_PARITY.md](BSLLS_PARITY.md) — намеренные отличия по кодам.
- [architecture.md](architecture.md) — раздел Formatting.
- [cst_policy.md](cst_policy.md) — CST и форматтер.
