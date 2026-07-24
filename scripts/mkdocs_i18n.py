"""Remove the inactive language from each MkDocs build.

Source pages remain bilingual and canonical.  The RU and EN builds receive
only their own blocks, so hidden text cannot leak into rendered HTML or search.
"""

from __future__ import annotations

import re
from typing import Any

_DIV_OPEN = re.compile(r"<div\b", re.IGNORECASE)
_DIV_CLOSE = re.compile(r"</div>", re.IGNORECASE)


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
