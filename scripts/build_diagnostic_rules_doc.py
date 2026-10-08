#!/usr/bin/env python3
"""Build the public diagnostic rules reference from the runtime registry.

The rule pages are a user-facing reference.  The builder owns their bounded
metadata and configuration header and preserves the curated RU/EN description.
Internal implementation dossiers are deliberately excluded from public docs.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DOC_OUT = REPO_ROOT / "docs" / "diagnostic-rules.md"
CONTRACTS_DIR = REPO_ROOT / "docs" / "rule-contracts"
RULE_HEADER_START = "<!-- generated-rule-header:start -->"
RULE_HEADER_END = "<!-- generated-rule-header:end -->"
LOCALIZED_DESCRIPTION_END = "<!-- localized-rule-description:end -->"
ENGINEERING_CONTRACT_START = "<!-- engineering-contract:start -->"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from onec_hbk_bsl.analysis.diagnostics import (  # noqa: E402
    RULE_DESCRIPTIONS_RU,
    RULE_METADATA,
    DiagnosticEngine,
    resolve_rule_token_to_code,
)
from onec_hbk_bsl.cli.config import (  # noqa: E402
    _BSLLS_DISABLED_BY_DEFAULT,
    _BSLLS_PARAMETER_KEYS,
    BslConfig,
)

ENGINE_DEFAULTS = inspect.signature(DiagnosticEngine).parameters
DEFAULT_ENGINE = DiagnosticEngine()
BSLLS_DISABLED_CODES = {resolve_rule_token_to_code(alias) for alias in _BSLLS_DISABLED_BY_DEFAULT}


def build_parameter_table(code: str, *, english: bool) -> list[str]:
    """Render only parameters supported by the authoritative BSLLS adapter."""
    parameters = _BSLLS_PARAMETER_KEYS.get(code, {})
    if not parameters:
        return []
    lines = [
        "## Supported parameters" if english else "## Поддерживаемые параметры",
        "",
        "| TOML | BSLLS JSON | Default |" if english else "| TOML | BSLLS JSON | По умолчанию |",
        "|---|---|---|",
    ]
    for bslls_key, (native_key, _) in parameters.items():
        default = ENGINE_DEFAULTS[native_key.replace("-", "_")].default
        value = _escape_table_cell(json.dumps(default, ensure_ascii=False))
        lines.append(f"| `{native_key}` | `{bslls_key}` | `{value}` |")
    lines.extend(
        [
            "",
            "TOML keys belong in `[tool.onec-hbk-bsl]`; JSON keys belong in "
            f"`diagnostics.parameters.{RULE_METADATA[code]['name']}`."
            if english
            else "Ключи TOML задаются в `[tool.onec-hbk-bsl]`, ключи JSON в "
            f"`diagnostics.parameters.{RULE_METADATA[code]['name']}`.",
            "",
        ]
    )
    return lines


def _rule_sort_key(code: str) -> tuple[int, str]:
    suffix = code.removeprefix("BSL")
    return (int(suffix) if suffix.isdigit() else 10_000, code)


def _escape_table_cell(value: object) -> str:
    text = str(value).replace("\n", " ").strip()
    return text.replace("|", r"\|")


def _rule_page_link(code: str) -> str:
    return f"rule-contracts/{code}.md"


def build_rule_header(code: str) -> str:
    meta = RULE_METADATA[code]
    alias = str(meta.get("name", "")).strip()
    severity = str(meta.get("severity", "")).strip()
    tags = ", ".join(f"`{tag}`" for tag in meta.get("tags", [])) or "-"
    implemented = "Да" if bool(meta.get("implemented", True)) else "Нет"
    default_enabled = DEFAULT_ENGINE._rule_enabled(code)
    bslls_enabled = code not in BSLLS_DISABLED_CODES
    ru_description = RULE_DESCRIPTIONS_RU.get(code, str(meta.get("description", "")))
    en_description = str(meta.get("description", "")).strip()
    bslls_off = f"// BSLLS:{alias}-off" if alias else "// BSLLS-off"
    bslls_on = f"// BSLLS:{alias}-on" if alias else "// BSLLS-on"

    return "\n".join(
        [
            RULE_HEADER_START,
            "",
            '<div class="doc-lang doc-lang-ru" markdown="1">',
            "",
            "[← Все правила](../diagnostic-rules.md)",
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-en" markdown="1">',
            "",
            "[← All rules](../diagnostic-rules.md)",
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-ru" markdown="1">',
            "",
            "## Кратко",
            "",
            ru_description,
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-en" markdown="1">',
            "",
            "## Summary",
            "",
            en_description,
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-ru" markdown="1">',
            "",
            "## Идентификаторы",
            "",
            "| Поле | Значение |",
            "|---|---|",
            f"| Код правила | `{code}` |",
            f"| Совместимый псевдоним | `{alias}` |",
            f"| Серьёзность | `{severity}` |",
            f"| Без конфигурации | {'Да' if default_enabled else 'Нет'} |",
            f"| BSLLS JSON, режим `ON` без переопределений | {'Да' if bslls_enabled else 'Нет'} |",
            f"| Флаг реестра `implemented` | {implemented} |",
            f"| Теги | {tags} |",
            "",
            "Флаг `implemented` отражает реестр и не подтверждает проверенное совпадение с BSLLS.",
            "",
            *build_parameter_table(code, english=False),
            "## Поведение",
            "",
            f"- Публичный идентификатор `{code}` и псевдоним `{alias}` стабильны.",
            "- Правило сообщает о случаях, описанных на этой странице.",
            "- Подавления и проектная конфигурация применяются до публикации результата.",
            "- Для выполнения правила не требуется внешний анализатор или сетевой доступ.",
            "",
            "## Настройка и подавление",
            "",
            "Код `BSL###` - основной стабильный идентификатор. Совместимый псевдоним",
            "принимается в `select`, `ignore` и совместимых блоковых комментариях.",
            "",
            "```toml",
            "[tool.onec-hbk-bsl]",
            f'select = ["{code}"]',
            f'ignore = ["{alias}"]',
            "```",
            "",
            "Все три семейства подавлений работают для текущей строки и диапазона.",
            "Если открывающий комментарий стоит после кода, он действует только на",
            "эту строку. Используйте любой один вариант:",
            "",
            "- `noqa`:",
            "",
            "```bsl",
            f'Значение = "пример";  // noqa: {code}',
            "```",
            "",
            "- `bsl-disable` (совместимый вариант):",
            "",
            "```bsl",
            f'Значение = "пример";  // bsl-disable: {code}',
            "```",
            "",
            "- совместимый `BSLLS`-вариант:",
            "",
            "```bsl",
            f'Значение = "пример";  {bslls_off}',
            "```",
            "",
            "Если тот же открывающий комментарий стоит на отдельной строке, он",
            "начинает диапазон. Закройте его парным маркером того же семейства:",
            "",
            "```bsl",
            f"// noqa: {code}",
            "// код без этой диагностики",
            f"// noqa-enable: {code}",
            "",
            f"// bsl-disable: {code}",
            "// код без этой диагностики",
            f"// bsl-enable: {code}",
            "",
            bslls_off,
            "// код без этой диагностики",
            bslls_on,
            "```",
            "",
            "Чтобы отключить правило до конца файла, не добавляйте закрывающий",
            "`noqa-enable`, `bsl-enable` или `BSLLS:…-on`.",
            "",
            "Открывающий и закрывающий маркеры должны принадлежать одному семейству.",
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-en" markdown="1">',
            "",
            "## Identifiers",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Rule code | `{code}` |",
            f"| Compatible alias | `{alias}` |",
            f"| Severity | `{severity}` |",
            f"| Without configuration | {'Yes' if default_enabled else 'No'} |",
            f"| BSLLS JSON, `ON` mode without overrides | {'Yes' if bslls_enabled else 'No'} |",
            f"| Registry flag `implemented` | {'Yes' if implemented == 'Да' else 'No'} |",
            f"| Tags | {tags} |",
            "",
            "The `implemented` flag describes the registry; it does not certify verified BSLLS parity.",
            "",
            *build_parameter_table(code, english=True),
            "## Behavior",
            "",
            f"- The public identifier `{code}` and alias `{alias}` are stable.",
            "- The rule reports the cases documented on this page.",
            "- Suppressions and project configuration are applied before publication.",
            "- The rule requires neither an external analyzer nor network access.",
            "",
            "## Configuration and suppression",
            "",
            "`BSL###` is the primary stable identifier. The compatible alias is accepted",
            "in `select`, `ignore`, and compatible block suppression comments.",
            "",
            "```toml",
            "[tool.onec-hbk-bsl]",
            f'select = ["{code}"]',
            f'ignore = ["{alias}"]',
            "```",
            "",
            "All three suppression families support both a current line and a range.",
            "When an opening comment follows code, it affects only that line. Use any",
            "one form:",
            "",
            "- `noqa`:",
            "",
            "```bsl",
            f'Value = "example";  // noqa: {code}',
            "```",
            "",
            "- `bsl-disable`:",
            "",
            "```bsl",
            f'Value = "example";  // bsl-disable: {code}',
            "```",
            "",
            "- compatible `BSLLS` form:",
            "",
            "```bsl",
            f'Value = "example";  {bslls_off}',
            "```",
            "",
            "When the same opening comment is on a line by itself, it starts a range.",
            "Close it with the matching marker from the same family:",
            "",
            "```bsl",
            f"// noqa: {code}",
            "// code without this diagnostic",
            f"// noqa-enable: {code}",
            "",
            f"// bsl-disable: {code}",
            "// code without this diagnostic",
            f"// bsl-enable: {code}",
            "",
            bslls_off,
            "// code without this diagnostic",
            bslls_on,
            "```",
            "",
            "To disable the rule until the end of the file, omit the closing",
            "`noqa-enable`, `bsl-enable`, or `BSLLS:…-on` marker.",
            "",
            "Opening and closing markers must belong to the same family.",
            "",
            "</div>",
            "",
            RULE_HEADER_END,
        ]
    )


def _public_rule_body(body: str) -> str:
    """Keep only the localized user documentation from an existing page."""
    if ENGINEERING_CONTRACT_START in body:
        body = body.split(ENGINEERING_CONTRACT_START, 1)[0]
    if LOCALIZED_DESCRIPTION_END in body:
        prefix, _ = body.split(LOCALIZED_DESCRIPTION_END, 1)
        return f"{prefix}{LOCALIZED_DESCRIPTION_END}".strip()
    return body.strip()


def render_rule_page(code: str, current: str) -> str:
    ru_title = RULE_DESCRIPTIONS_RU.get(code, code)
    en_title = str(RULE_METADATA[code].get("description", code))
    title = (
        f'# {code} - <span class="doc-lang doc-lang-ru">{ru_title}</span>'
        f'<span class="doc-lang doc-lang-en">{en_title}</span>'
    )
    header = build_rule_header(code)
    if RULE_HEADER_START in current and RULE_HEADER_END in current:
        before, rest = current.split(RULE_HEADER_START, 1)
        _, after = rest.split(RULE_HEADER_END, 1)
        prefix_lines = before.strip().splitlines()
        if prefix_lines and prefix_lines[0].startswith("# "):
            prefix_lines[0] = title
        else:
            prefix_lines.insert(0, title)
        prefix = "\n".join(prefix_lines).strip()
        body = _public_rule_body(after.lstrip())
        return f"{prefix}\n\n{header}\n\n{body}".rstrip() + "\n"

    lines = current.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = _public_rule_body("\n".join(lines).lstrip())
    return f"{title}\n\n{header}\n\n{body}".rstrip() + "\n"


def expected_rule_pages() -> dict[Path, str]:
    pages: dict[Path, str] = {}
    for code in sorted(RULE_METADATA, key=_rule_sort_key):
        path = CONTRACTS_DIR / f"{code}.md"
        if not path.is_file():
            raise FileNotFoundError(f"missing rule contract: {path.relative_to(REPO_ROOT)}")
        pages[path] = render_rule_page(code, path.read_text(encoding="utf-8"))
    return pages


def build_markdown() -> str:
    lines = [
        '# <span class="doc-lang doc-lang-ru">Диагностические правила</span>'
        '<span class="doc-lang doc-lang-en">Diagnostic rules</span>',
        "",
        '<div class="doc-lang doc-lang-ru" markdown="1">',
        "",
        "Справочник генерируется из runtime-реестра `onec-hbk-bsl`. Код правила",
        "ведёт на единственную страницу с описанием, примерами, настройкой и",
        "способами подавления.",
        "",
        "Без конфигурации движок выбирает все публичные правила. При загрузке BSLLS JSON",
        "режим `ON` (также режим по умолчанию) использует отдельный набор включённых правил.",
        "Параметры, `select`, `ignore` и подавления могут изменить результат.",
        "Флаг реестра `implemented` не подтверждает проверенное совпадение поведения с BSLLS.",
        "",
        "</div>",
        "",
        '<div class="doc-lang doc-lang-en" markdown="1">',
        "",
        "This reference is generated from the `onec-hbk-bsl` runtime registry. Every",
        "rule code links to its single page with usage documentation, examples,",
        "configuration, and suppressions.",
        "",
        "Without configuration, the engine selects every public rule. Loading BSLLS JSON",
        "in `ON` mode (also the default mode) uses a separate enabled rule set.",
        "Parameters, `select`, `ignore`, and suppressions can change the result.",
        "The registry flag `implemented` does not certify verified BSLLS behavior parity.",
        "",
        "</div>",
        "",
        '<div class="doc-lang doc-lang-ru" markdown="1">',
        "",
        "## Идентификаторы",
        "",
        "- `BSL###` - основной стабильный код для вывода, `select`, `ignore`,",
        "  `onec-hbk-bsl.toml`, SARIF/JSON и `// noqa: BSL###`.",
        "- Совместимый псевдоним можно использовать во входной конфигурации и",
        "  комментариях `// BSLLS:<RuleName>-off/on`; вывод всегда использует `BSL###`.",
        "- Нумерация стабильна, но не обязана быть непрерывной.",
        "",
        "</div>",
        "",
        '<div class="doc-lang doc-lang-en" markdown="1">',
        "",
        "## Identifiers",
        "",
        "- `BSL###` is the stable identifier used in output, `select`, `ignore`,",
        "  `onec-hbk-bsl.toml`, SARIF/JSON, and `// noqa: BSL###`.",
        "- The compatible alias is accepted in input configuration and",
        "  `// BSLLS:<RuleName>-off/on` comments; output always uses `BSL###`.",
        "- Identifiers are stable but are not necessarily contiguous.",
        "",
        "</div>",
        "",
        '## <span class="doc-lang doc-lang-ru">Каталог</span>'
        '<span class="doc-lang doc-lang-en">Catalog</span>',
        "",
        '| <span class="doc-lang doc-lang-ru">Код</span><span class="doc-lang doc-lang-en">Code</span> '
        '| <span class="doc-lang doc-lang-ru">Псевдоним</span><span class="doc-lang doc-lang-en">Alias</span> '
        '| <span class="doc-lang doc-lang-ru">По умолчанию</span><span class="doc-lang doc-lang-en">Default</span> '
        '| <span class="doc-lang doc-lang-ru">Уровень</span><span class="doc-lang doc-lang-en">Severity</span> '
        '| <span class="doc-lang doc-lang-ru">Описание</span><span class="doc-lang doc-lang-en">Description</span> '
        '| <span class="doc-lang doc-lang-ru">Теги</span><span class="doc-lang doc-lang-en">Tags</span> |',
        "|---|---|---:|---|---|---|",
    ]

    for code in sorted(RULE_METADATA, key=_rule_sort_key):
        meta = RULE_METADATA[code]
        tags = ", ".join(str(tag) for tag in meta.get("tags", []))
        row = [
            f"[`{code}`]({_rule_page_link(code)})",
            f"`{meta.get('name', '')}`",
            (
                '<span class="doc-lang doc-lang-ru">Да</span>'
                '<span class="doc-lang doc-lang-en">Yes</span>'
            )
            if DEFAULT_ENGINE._rule_enabled(code)
            else (
                '<span class="doc-lang doc-lang-ru">Нет</span>'
                '<span class="doc-lang doc-lang-en">No</span>'
            ),
            str(meta.get("severity", "")),
            '<span class="doc-lang doc-lang-ru">'
            f"{RULE_DESCRIPTIONS_RU.get(code, str(meta.get('description', '')))}</span>"
            '<span class="doc-lang doc-lang-en">'
            f"{meta.get('description', '')}</span>",
            tags,
        ]
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")
    lines.extend(
        [
            "",
            '## <span class="doc-lang doc-lang-ru">Параметры TOML</span>'
            '<span class="doc-lang doc-lang-en">TOML parameters</span>',
            "",
            '<div class="doc-lang doc-lang-ru" markdown="1">',
            "",
            "Значения по умолчанию берутся из конструктора движка. Ключи задаются в",
            "`[tool.onec-hbk-bsl]`. Таблица содержит параметры, передаваемые слоем конфигурации",
            "в движок; поддерживаемые ключи BSLLS JSON указаны на страницах отдельных правил.",
            "",
            "</div>",
            "",
            '<div class="doc-lang doc-lang-en" markdown="1">',
            "",
            "Defaults come from the engine constructor. Set these keys in",
            "`[tool.onec-hbk-bsl]`. The table lists parameters forwarded by the configuration",
            "layer to the engine; supported BSLLS JSON keys appear on individual rule pages.",
            "",
            "</div>",
            "",
            '| TOML | <span class="doc-lang doc-lang-ru">По умолчанию</span>'
            '<span class="doc-lang doc-lang-en">Default</span> |',
            "|---|---|",
        ]
    )
    for name, parameter in ENGINE_DEFAULTS.items():
        key = name.replace("_", "-")
        if parameter.default is inspect.Parameter.empty:
            continue
        if name not in BslConfig({key: parameter.default}).engine_kwargs():
            continue
        value = _escape_table_cell(json.dumps(parameter.default, ensure_ascii=False))
        lines.append(f"| `{key}` | `{value}` |")
    return "\n".join(lines) + "\n"


def main() -> int:
    DOC_OUT.write_text(build_markdown(), encoding="utf-8")
    for path, content in expected_rule_pages().items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
