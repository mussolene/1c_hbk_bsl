"""
Static analysis helpers for 1C metadata dotted references (Справочники.X, Метаданные.Справочники.X).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity
from onec_hbk_bsl.indexer.metadata_registry import ALL_COLLECTION_NAMES_RU

if TYPE_CHECKING:
    from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

# Canonical Russian collection names (longest first for alternation stability)
_COLL_SORTED = sorted(set(ALL_COLLECTION_NAMES_RU), key=len, reverse=True)
_COLL_ALT = "|".join(re.escape(c) for c in _COLL_SORTED)

# Метаданные.Коллекция.Объект or Коллекция.Объект — object is a single identifier segment.
_METADATA_REF_RE = re.compile(
    rf"\b(?:Метаданные\.)?(?P<coll>{_COLL_ALT})\.(?P<obj>[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z0-9_]*)",
    re.UNICODE,
)


def diagnostics_unknown_metadata_objects(
    path: str,
    content: str,
    symbol_index: SymbolIndex,
) -> list[Diagnostic]:
    """
    Emit BSL280 when a metadata collection/object chain names an object missing from the index.

    No-op if the index has no metadata (configuration not crawled).
    """
    if not symbol_index.has_metadata():
        return []

    issues: list[Diagnostic] = []
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for m in _METADATA_REF_RE.finditer(line):
            obj_name = m.group("obj")
            if symbol_index.find_meta_object(obj_name):
                continue
            col = m.start("obj")
            issues.append(
                Diagnostic(
                    file=path,
                    line=line_no,
                    character=col,
                    end_line=line_no,
                    end_character=col + len(obj_name),
                    severity=Severity.WARNING,
                    code="BSL280",
                    message=(
                        f"Объект метаданных «{obj_name}» не найден в индексированной конфигурации "
                        f"(коллекция «{m.group('coll')}»)"
                    ),
                )
            )
    return issues
