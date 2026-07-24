"""Remove the inactive language from each MkDocs build.

Source pages remain bilingual and canonical.  The RU and EN builds receive
only their own blocks, so hidden text cannot leak into rendered HTML or search.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DIV_OPEN = re.compile(r"<div\b", re.IGNORECASE)
_DIV_CLOSE = re.compile(r"</div>", re.IGNORECASE)


def _rule_sort_key(path: Path) -> tuple[int, str]:
    code = path.stem
    suffix = code.removeprefix("BSL")
    return (int(suffix) if suffix.isdigit() else 10_000, code)


def _rule_navigation(docs_dir: Path) -> list[dict[str, list[dict[str, str]]]]:
    groups: dict[int, list[dict[str, str]]] = {}
    for path in sorted((docs_dir / "rule-contracts").glob("BSL*.md"), key=_rule_sort_key):
        number = _rule_sort_key(path)[0]
        start = ((number - 1) // 50) * 50 + 1
        groups.setdefault(start, []).append({path.stem: f"rule-contracts/{path.name}"})
    return [
        {f"BSL{start:03d}–BSL{start + 49:03d}": pages} for start, pages in sorted(groups.items())
    ]


def on_config(config: Any) -> Any:
    """Attach rule pages to the grouped Diagnostics navigation."""
    locale = str(config.get("extra", {}).get("doc_locale", "ru")).lower()
    section_title = "Diagnostics" if locale == "en" else "Диагностики"
    for item in config.get("nav", []):
        if isinstance(item, dict) and section_title in item:
            item[section_title].extend(_rule_navigation(Path(config["docs_dir"])))
            break
    return config


def _strip_div_blocks(markdown: str, hidden_class: str) -> str:
    output: list[str] = []
    depth = 0
    skipping = False
    marker = re.compile(
        rf'<div\b[^>]*class="[^"]*\b{re.escape(hidden_class)}\b[^"]*"[^>]*>',
        re.IGNORECASE,
    )

    for line in markdown.splitlines():
        if not skipping and marker.search(line):
            skipping = True
            depth = len(_DIV_OPEN.findall(line)) - len(_DIV_CLOSE.findall(line))
            if depth <= 0:
                skipping = False
            continue
        if skipping:
            depth += len(_DIV_OPEN.findall(line)) - len(_DIV_CLOSE.findall(line))
            if depth <= 0:
                skipping = False
            continue
        output.append(line)
    return "\n".join(output)


def _strip_inline_spans(markdown: str, hidden_class: str) -> str:
    pattern = re.compile(
        rf'<span\b[^>]*class="[^"]*\b{re.escape(hidden_class)}\b[^"]*"[^>]*>'
        r".*?</span>",
        re.IGNORECASE,
    )
    return pattern.sub("", markdown)


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    """MkDocs hook: retain only the locale selected by the current config."""
    del page, files
    locale = str(config.get("extra", {}).get("doc_locale", "ru")).lower()
    hidden_class = "doc-lang-ru" if locale == "en" else "doc-lang-en"
    return _strip_inline_spans(_strip_div_blocks(markdown, hidden_class), hidden_class)
