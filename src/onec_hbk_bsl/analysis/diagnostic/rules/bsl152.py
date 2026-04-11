"""
BSL152 CachedPublic — BSLLS parity for common modules.

Flags ``#Область ПрограммныйИнтерфейс`` / ``#Region Public`` when the sibling
module XML sets ``ReturnValuesReuse`` to ``DuringRequest`` or ``DuringSession``
(BSLLS ``CachedPublicDiagnostic``), and the region contains at least one
procedure or function.

See: https://github.com/1c-syntax/bsl-language-server/blob/master/src/main/java/com/github/_1c_syntax/bsl/languageserver/diagnostics/CachedPublicDiagnostic.java
"""

from __future__ import annotations

import re
from pathlib import Path

# 1C configuration / EDT module descriptor
_RVR_RE = re.compile(
    r"<ReturnValuesReuse>\s*([^<]+?)\s*</ReturnValuesReuse>",
    re.IGNORECASE,
)

# BSLLS isCashed — not DontUse / DuringCall / etc.
_CACHED_REUSE_VALUES = frozenset({"duringrequest", "duringsession"})

_RE_REGION_NAME_COL = re.compile(
    r"^\s*#(?:Область|Region)\s+(\S+)",
    re.IGNORECASE,
)

_PUBLIC_REGION_NAMES = frozenset({"public", "программныйинтерфейс"})


def common_module_xml_for_module_bsl(module_bsl_path: str) -> Path | None:
    """
    Resolve ``CommonModules/<Name>/<Name>.xml`` (or Russian folder name) for
    ``.../<Name>/Ext/Module.bsl``. Returns None if the layout does not match.
    """
    p = Path(module_bsl_path)
    lower_parts = {x.lower() for x in p.parts}
    if "commonmodules" not in lower_parts and "общиемодули" not in lower_parts:
        return None
    if p.name.lower() != "module.bsl":
        return None
    if p.parent.name.lower() != "ext":
        return None
    mod_dir = p.parent.parent
    xml = mod_dir / f"{mod_dir.name}.xml"
    return xml if xml.is_file() else None


def return_values_reuse_cached_from_xml_text(raw: str) -> bool:
    """True when ``ReturnValuesReuse`` is DuringRequest or DuringSession (BSLLS cached)."""
    m = _RVR_RE.search(raw)
    if not m:
        return False
    val = m.group(1).strip().casefold()
    val = val.split(":")[-1].strip()
    return val in _CACHED_REUSE_VALUES


def common_module_bslls_cached_reuse(module_bsl_path: str) -> bool:
    """True when sibling XML has ReturnValuesReuse DuringRequest or DuringSession."""
    xp = common_module_xml_for_module_bsl(module_bsl_path)
    if xp is None:
        return False
    try:
        raw = xp.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    return return_values_reuse_cached_from_xml_text(raw)


def _is_public_program_interface_region(name: str) -> bool:
    return name.strip().casefold() in _PUBLIC_REGION_NAMES


def bsl152_public_region_name_spans(
    module_bsl_path: str,
    lines: list[str],
    regions: list[tuple[str, int, int]],
    procedures: list[tuple[int, int]],
) -> list[tuple[int, int, int]]:
    """
    Return (line_1based, start_col, end_col) spans for the region *name* token.

    *regions*: ``(name, start_line_0, end_line_0)`` — ``end_line_0`` is the
    ``#КонецОбласти`` line index.

    *procedures*: ``(proc_header_line_0, proc_end_line_0)`` per subroutine.
    """
    if not common_module_bslls_cached_reuse(module_bsl_path):
        return []

    out: list[tuple[int, int, int]] = []
    for name, r0, r1 in regions:
        if not _is_public_program_interface_region(name):
            continue
        has_sub = any(r0 < ps < r1 for ps, _ in procedures)
        if not has_sub:
            continue
        if r0 < 0 or r0 >= len(lines):
            continue
        line = lines[r0]
        m = _RE_REGION_NAME_COL.match(line)
        if not m:
            continue
        c0 = m.start(1)
        c1 = m.end(1)
        out.append((r0 + 1, c0, c1))
    return out
