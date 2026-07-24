# 1C HBK BSL

<div class="doc-lang doc-lang-ru" markdown="1">

Инструменты качества и редакторская поддержка для встроенного языка
«1С:Предприятия» (BSL). Репозиторий выпускает два связанных продукта.

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } **Toolkit**

    ---

    Python-пакет и автономные бинарники: 180 диагностик, форматтер, CLI,
    Language Server, Python API, SARIF и локальный MCP-сервер.

    [Установить Toolkit](public-surface.md){ .md-button }

-   :material-microsoft-visual-studio-code:{ .lg .middle } **Расширение VS Code / Cursor**

    ---

    Готовая редакторская интеграция с подсветкой, диагностикой, форматированием,
    навигацией, автодополнением, переименованием и встроенным сервером.

    [Установить расширение](extension.md){ .md-button .md-button--primary }

</div>

## Как выбрать

- Нужна проверка в терминале или CI — установите **Toolkit**.
- Нужны подсказки и навигация в редакторе — установите **расширение**.
- Для полного рабочего места используйте оба: расширение отвечает за редактор,
  а CLI — за воспроизводимые проверки проекта и CI.

## Быстрый запуск

=== "VS Code / Cursor"

    Установите `mussolene.1c-hbk-bsl` из Marketplace и откройте каталог с
    файлами `.bsl` или `.os`. Системный Python не требуется.

=== "CLI"

    ```bash
    pip install onec-hbk-bsl
    onec-hbk-bsl check .
    ```

[Открыть каталог правил](diagnostic-rules.md){ .md-button }

</div>

<div class="doc-lang doc-lang-en" markdown="1">

Quality tooling and editor support for the 1C:Enterprise built-in language
(BSL). The repository ships two related products.

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } **Toolkit**

    ---

    Python packages and standalone binaries providing 180 diagnostics, a
    formatter, CLI, Language Server, Python API, SARIF, and a local MCP server.

    [Install the Toolkit](public-surface.md){ .md-button }

-   :material-microsoft-visual-studio-code:{ .lg .middle } **VS Code / Cursor extension**

    ---

    Ready-to-use editor integration with highlighting, diagnostics, formatting,
    navigation, completion, rename, and a bundled server.

    [Install the extension](extension.md){ .md-button .md-button--primary }

</div>

## Which one to use

- Install the **Toolkit** for terminal and CI checks.
- Install the **extension** for editor assistance and navigation.
- Use both for a complete setup: the extension handles the editor while the
  CLI provides reproducible project and CI checks.

## Quick start

=== "VS Code / Cursor"

    Install `mussolene.1c-hbk-bsl` from Marketplace and open a folder containing
    `.bsl` or `.os` files. A system Python installation is not required.

=== "CLI"

    ```bash
    pip install onec-hbk-bsl
    onec-hbk-bsl check .
    ```

[Browse diagnostic rules](diagnostic-rules.md){ .md-button }

</div>
