#!/usr/bin/env python3
"""Build the public diagnostic rules reference from the runtime registry."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DOC_OUT = REPO_ROOT / "docs" / "diagnostic-rules.md"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from onec_hbk_bsl.analysis.diagnostics import RULE_DESCRIPTIONS_RU, RULE_METADATA  # noqa: E402


def _rule_sort_key(code: str) -> tuple[int, str]:
    suffix = code.removeprefix("BSL")
    return (int(suffix) if suffix.isdigit() else 10_000, code)


def _escape_table_cell(value: object) -> str:
    text = str(value).replace("\n", " ").strip()
    return text.replace("|", r"\|")


def build_markdown() -> str:
    lines = [
        "# Diagnostic Rules",
        "",
        "This reference is generated from the `onec-hbk-bsl` runtime registry.",
        "It is the product-facing source for rule identifiers used by CLI, config,",
        "LSP, MCP, SARIF/JSON output, and suppression comments.",
        "",
        "## Identifiers",
        "",
        "- `BSL###` is the stable `onec-hbk-bsl` rule code used in diagnostics output,",
        "  `--select`, `--ignore`, `onec-hbk-bsl.toml`, and `// noqa: BSL###`.",
        "- `Compatible key` is the stable diagnostic alias accepted for compatibility",
        "  with existing BSL projects, such as `LineLength` or `ConsecutiveEmptyLines`.",
        "- CLI and config accept both forms, but output uses `BSL###`.",
        "- Rule numbering is stable but not continuous. Missing numbers, for example",
        "  `BSL053`, are not valid rules unless they appear in this table.",
        "- Unknown rule codes or compatible keys are configuration errors.",
        "",
        "## Справочник Правил",
        "",
        "| Code | Compatible key | Default | Severity | Русское описание | English description | Tags |",
        "|---|---|---:|---|---|---|---|",
    ]

    for code in sorted(RULE_METADATA, key=_rule_sort_key):
        meta = RULE_METADATA[code]
        tags = ", ".join(str(tag) for tag in meta.get("tags", []))
        row = [
            f"`{code}`",
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
            "## Maintenance",
            "",
            "Regenerate this file after changing `RULE_METADATA`,",
            "`RULE_DESCRIPTIONS_RU`, or diagnostic default behavior:",
            "",
            "```bash",
            "./.venv/bin/python scripts/build_diagnostic_rules_doc.py",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    DOC_OUT.write_text(build_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
