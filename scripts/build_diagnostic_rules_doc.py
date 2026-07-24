#!/usr/bin/env python3
"""Build the public diagnostic rules reference from the runtime registry.

The rule contract files are the single canonical pages for both users and
maintainers.  This builder owns only their bounded product-facing header; the
manually curated descriptions and engineering contract remain untouched.
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
ENGINEERING_CONTRACT_END = "<!-- engineering-contract:end -->"

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
            "## Идентификаторы / Identifiers",
            "",
            "| Поле / Field | Значение / Value |",
            "|---|---|",
            f"| Код правила / Rule code | `{code}` |",
            f"| Совместимый псевдоним / Compatible alias | `{alias}` |",
            f"| Серьёзность / Severity | `{severity}` |",
            "| Включено по умолчанию / Enabled by default | Да / Yes |",
            f"| Реализовано / Implemented | {implemented} / {'Yes' if implemented == 'Да' else 'No'} |",
            f"| Теги / Tags | {tags} |",
            "",
            '<div class="doc-lang doc-lang-ru" markdown="1">',
            "",
            "## Контракт поведения",
            "",
            f"- Публичный идентификатор `{code}` и псевдоним `{alias}` стабильны.",
            "- Правило сообщает только о случаях, описанных на этой странице и в",
            "  проверяемом инженерном контракте.",
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
            "## Behavioral contract",
            "",
            f"- The public identifier `{code}` and alias `{alias}` are stable.",
            "- The rule reports only the cases documented on this page and in its",
            "  verifiable engineering contract.",
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


def _wrap_engineering_contract(body: str) -> str:
    if ENGINEERING_CONTRACT_START in body and ENGINEERING_CONTRACT_END in body:
        return body
    if LOCALIZED_DESCRIPTION_END in body:
        prefix, contract = body.split(LOCALIZED_DESCRIPTION_END, 1)
        prefix = f"{prefix}{LOCALIZED_DESCRIPTION_END}".rstrip()
    else:
        prefix, contract = "", body
    contract = contract.strip()
    wrapped = "\n".join(
        [
            ENGINEERING_CONTRACT_START,
            "",
            "## Инженерный контракт / Engineering contract",
            "",
            '<details class="engineering-contract">',
            '<summary><span class="doc-lang doc-lang-ru">Показать полный контракт реализации</span>'
            '<span class="doc-lang doc-lang-en">Show the complete implementation contract</span>'
            "</summary>",
            "",
            '<div markdown="1">',
            "",
            contract,
            "",
            "</div>",
            "",
            "</details>",
            "",
            ENGINEERING_CONTRACT_END,
        ]
    )
    return f"{prefix}\n\n{wrapped}".strip() if prefix else wrapped


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
        body = _wrap_engineering_contract(after.lstrip())
        return f"{prefix}\n\n{header}\n\n{body}".rstrip() + "\n"

    lines = current.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = _wrap_engineering_contract("\n".join(lines).lstrip())
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
        "# Диагностические правила",
        "",
        '<div class="doc-lang doc-lang-ru" markdown="1">',
        "",
        "Справочник генерируется из runtime-реестра `onec-hbk-bsl`. Код правила",
        "ведёт на единственную страницу с описанием, примерами, подавлениями и",
        "полным инженерным контрактом.",
        "",
        "</div>",
        "",
        '<div class="doc-lang doc-lang-en" markdown="1">',
        "",
        "This reference is generated from the `onec-hbk-bsl` runtime registry. Every",
        "rule code links to its single page with usage documentation, examples,",
        "suppressions, and the complete engineering contract.",
        "",
        "</div>",
        "",
        "## Идентификаторы / Identifiers",
        "",
        "- `BSL###` — основной стабильный код для вывода, `select`, `ignore`,",
        "  `onec-hbk-bsl.toml`, SARIF/JSON и `// noqa: BSL###`.",
        "- Совместимый псевдоним можно использовать во входной конфигурации и",
        "  комментариях `// BSLLS:<RuleName>-off/on`; вывод всегда использует `BSL###`.",
        "- Нумерация стабильна, но не обязана быть непрерывной.",
        "",
        "## Каталог / Catalog",
        "",
        "| Code | Compatible alias | Default | Severity | Русское описание | English description | Tags |",
        "|---|---|---:|---|---|---|---|",
    ]

    for code in sorted(RULE_METADATA, key=_rule_sort_key):
        meta = RULE_METADATA[code]
        tags = ", ".join(str(tag) for tag in meta.get("tags", []))
        row = [
            f"[`{code}`]({_rule_page_link(code)})",
            f"`{meta.get('name', '')}`",
            "Yes",
            str(meta.get("severity", "")),
            RULE_DESCRIPTIONS_RU.get(code, str(meta.get("description", ""))),
            str(meta.get("description", "")),
            tags,
        ]
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")

    lines.extend(
        [
            "",
            "## Сопровождение / Maintenance",
            "",
            "После изменения `RULE_METADATA`, `RULE_DESCRIPTIONS_RU` или поведения",
            "правил обновите индекс и генерируемые заголовки страниц:",
            "",
            "```bash",
            "./.venv/bin/python scripts/build_diagnostic_rules_doc.py",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    DOC_OUT.write_text(build_markdown(), encoding="utf-8")
    for path, content in expected_rule_pages().items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
