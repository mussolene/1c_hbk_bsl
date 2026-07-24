#!/usr/bin/env python3
"""Build the public diagnostic rules reference from the runtime registry.

The rule pages are a user-facing reference.  The builder owns their bounded
metadata and configuration header and preserves the curated RU/EN description.
Internal implementation dossiers are deliberately excluded from public docs.
"""

from __future__ import annotations

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

from onec_hbk_bsl.analysis.diagnostics import RULE_DESCRIPTIONS_RU, RULE_METADATA  # noqa: E402


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
    tags = ", ".join(f"`{tag}`" for tag in meta.get("tags", [])) or "—"
    implemented = "Да" if bool(meta.get("implemented", True)) else "Нет"
    ru_description = RULE_DESCRIPTIONS_RU.get(code, str(meta.get("description", "")))
    en_description = str(meta.get("description", "")).strip()
    bslls_off = f"// BSLLS:{alias}-off" if alias else "// BSLLS-off"
    bslls_on = f"// BSLLS:{alias}-on" if alias else "// BSLLS-on"

    return "\n".join(
        [
            RULE_HEADER_START,
            "",
            '<a href="../diagnostic-rules.md">'
            '<span class="doc-lang doc-lang-ru">← Все правила</span>'
            '<span class="doc-lang doc-lang-en">← All rules</span>'
            "</a>",
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
            "| Включено по умолчанию | Да |",
            f"| Реализовано | {implemented} |",
            f"| Теги | {tags} |",
            "",
            "## Поведение",
            "",
            f"- Публичный идентификатор `{code}` и псевдоним `{alias}` стабильны.",
            "- Правило сообщает о случаях, описанных на этой странице.",
            "- Подавления и проектная конфигурация применяются до публикации результата.",
            "- Для выполнения правила не требуется внешний анализатор или сетевой доступ.",
            "",
            "## Настройка и подавление",
            "",
            "Код `BSL###` — основной стабильный идентификатор. Совместимый псевдоним",
            "принимается в `select`, `ignore` и совместимых блоковых комментариях.",
            "",
            "```toml",
            "[tool.onec-hbk-bsl]",
            f'select = ["{code}"]',
            f'ignore = ["{alias}"]',
            "```",
            "",
            "Подавить диагностику только на текущей строке:",
            "",
            "```bsl",
            f'Значение = "пример";  // noqa: {code}',
            f'Значение = "пример";  // bsl-disable: {code}',
            "```",
            "",
            "Отключить правило для блока или всего файла:",
            "",
            "```bsl",
            bslls_off,
            "// код без этой диагностики",
            bslls_on,
            "```",
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
            "| Enabled by default | Yes |",
            f"| Implemented | {'Yes' if implemented == 'Да' else 'No'} |",
            f"| Tags | {tags} |",
            "",
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
            "Suppress the diagnostic on the current line:",
            "",
            "```bsl",
            f'Value = "example";  // noqa: {code}',
            f'Value = "example";  // bsl-disable: {code}',
            "```",
            "",
            "Disable the rule for a block or the whole file:",
            "",
            "```bsl",
            bslls_off,
            "// code without this diagnostic",
            bslls_on,
            "```",
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
        f'# {code} — <span class="doc-lang doc-lang-ru">{ru_title}</span>'
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
        "</div>",
        "",
        '<div class="doc-lang doc-lang-en" markdown="1">',
        "",
        "This reference is generated from the `onec-hbk-bsl` runtime registry. Every",
        "rule code links to its single page with usage documentation, examples,",
        "configuration, and suppressions.",
        "",
        "</div>",
        "",
        '<div class="doc-lang doc-lang-ru" markdown="1">',
        "",
        "## Идентификаторы",
        "",
        "- `BSL###` — основной стабильный код для вывода, `select`, `ignore`,",
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
            '<span class="doc-lang doc-lang-ru">Да</span>'
            '<span class="doc-lang doc-lang-en">Yes</span>',
            str(meta.get("severity", "")),
            '<span class="doc-lang doc-lang-ru">'
            f"{RULE_DESCRIPTIONS_RU.get(code, str(meta.get('description', '')))}</span>"
            '<span class="doc-lang doc-lang-en">'
            f"{meta.get('description', '')}</span>",
            tags,
        ]
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    DOC_OUT.write_text(build_markdown(), encoding="utf-8")
    for path, content in expected_rule_pages().items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
