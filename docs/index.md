# 1C HBK BSL

<div class="doc-lang doc-lang-ru" markdown="1">

Единый набор инструментов для разработки на встроенном языке 1С:
форматирование, 180 диагностических правил, Language Server, CLI, Python API
и MCP-интеграция.

[Открыть каталог правил](diagnostic-rules.md){ .md-button .md-button--primary }
[Начать работу](public-surface.md){ .md-button }

## Что входит

<div class="grid cards" markdown>

-   :material-shield-search:{ .lg .middle } **180 диагностик**

    ---

    Стабильные коды `BSL###`, совместимые псевдонимы, подавления и подробные
    контракты поведения.

-   :material-format-align-left:{ .lg .middle } **Форматтер**

    ---

    Детерминированное форматирование BSL через CLI, Python API и редактор.

-   :material-language-python:{ .lg .middle } **LSP и MCP**

    ---

    Диагностика, навигация, переименование, подсказки и инструменты для агентов.

-   :material-console:{ .lg .middle } **CLI и CI**

    ---

    Текстовые, JSON и SARIF-отчёты, baseline, diff-проверки и параллельный запуск.

</div>

## Быстрый запуск

```bash
pip install onec-hbk-bsl
onec-hbk-bsl check .
```

Настройки проекта хранятся в `onec-hbk-bsl.toml`. Полный контракт команд,
конфигурации и интеграций находится в разделе
[«Публичные интерфейсы»](public-surface.md).

</div>

<div class="doc-lang doc-lang-en" markdown="1">

A unified toolkit for the 1C Enterprise built-in language: formatting,
180 diagnostic rules, a Language Server, CLI, Python API, and MCP integration.

[Browse diagnostic rules](diagnostic-rules.md){ .md-button .md-button--primary }
[Public interfaces](public-surface.md){ .md-button }

## Included capabilities

<div class="grid cards" markdown>

-   :material-shield-search:{ .lg .middle } **180 diagnostics**

    ---

    Stable `BSL###` codes, compatible aliases, suppressions, and detailed
    behavioral contracts.

-   :material-format-align-left:{ .lg .middle } **Formatter**

    ---

    Deterministic BSL formatting through the CLI, Python API, and editor.

-   :material-language-python:{ .lg .middle } **LSP and MCP**

    ---

    Diagnostics, navigation, rename, editor assistance, and agent tools.

-   :material-console:{ .lg .middle } **CLI and CI**

    ---

    Text, JSON, and SARIF reports, baselines, diff checks, and parallel execution.

</div>

## Quick start

```bash
pip install onec-hbk-bsl
onec-hbk-bsl check .
```

Project settings live in `onec-hbk-bsl.toml`. The complete command,
configuration, and integration contract is documented under
[Public interfaces](public-surface.md).

</div>
