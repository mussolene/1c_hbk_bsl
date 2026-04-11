"""
BSL154 CodeAfterAsyncCall — simplified BSLLS parity.

BSLLS flags asynchronous platform calls when further statements follow in the same
procedure without an intervening ``Возврат``/``Return`` or ``Прервать``/``Break``.
Module types: command module, managed application module, form module (path heuristic).

BSLLS also walks parent blocks and uses full CST; we only analyze linear order inside
each procedure body (fewer false positives than full parent propagation).

Method list mirrors ``CodeAfterAsyncCallDiagnostic.ASYNC_METHODS`` in bsl-language-server.
"""

from __future__ import annotations

import re

# Pipe-separated names from CodeAfterAsyncCallDiagnostic.java (master, 2026)
_BSL154_ASYNC_PIPE = (
    "ПОКАЗАТЬВОПРОС|SHOWQUERYBOX|ПОКАЗАТЬЗНАЧЕНИЕ|SHOWVALUE|"
    "ПОКАЗАТЬПРЕДУПРЕЖДЕНИЕ|SHOWMESSAGEBOX|ПОКАЗАТЬВВОДДАТЫ|SHOWINPUTDATE|"
    "ПОКАЗАТЬВВОДЗНАЧЕНИЯ|SHOWINPUTVALUE|ПОКАЗАТЬВВОДСТРОКИ|SHOWINPUTSTRING|"
    "ПОКАЗАТЬВВОДЧИСЛА|SHOWINPUTNUMBER|НАЧАТЬУСТАНОВКУВНЕШНЕЙКОМПОНЕНТЫ|BEGININSTALLADDIN|"
    "НАЧАТЬУСТАНОВКУРАСШИРЕНИЯРАБОТЫСФАЙЛАМИ|BEGININSTALLFILESYSTEMEXTENSION|"
    "НАЧАТЬУСТАНОВКУРАСШИРЕНИЯРАБОТЫСКРИПТОГРАФИЕЙ|BEGININSTALLCRYPTOEXTENSION|"
    "НАЧАТЬПОДКЛЮЧЕНИЕРАСШИРЕНИЯРАБОТЫСКРИПТОГРАФИЕЙ|BEGINATTACHINGCRYPTOEXTENSION|"
    "НАЧАТЬПОДКЛЮЧЕНИЕРАСШИРЕНИЯРАБОТЫСФАЙЛАМИ|BEGINATTACHINGFILESYSTEMEXTENSION|"
    "НАЧАТЬПОМЕЩЕНИЕФАЙЛА|BEGINPUTFILE|НАЧАТЬКОПИРОВАНИЕФАЙЛА|BEGINCOPYINGFILE|"
    "НАЧАТЬПЕРЕМЕЩЕНИЕФАЙЛА|BEGINMOVINGFILE|НАЧАТЬПОИСКФАЙЛОВ|BEGINFINDINGFILES|"
    "НАЧАТЬУДАЛЕНИЕФАЙЛОВ|BEGINDELETINGFILES|НАЧАТЬСОЗДАНИЕКАТАЛОГА|BEGINCREATINGDIRECTORY|"
    "НАЧАТЬПОЛУЧЕНИЕКАТАЛОГАВРЕМЕННЫХФАЙЛОВ|BEGINGETTINGTEMPFILESDIR|"
    "НАЧАТЬПОЛУЧЕНИЕКАТАЛОГАДОКУМЕНТОВ|BEGINGETTINGDOCUMENTSDIR|"
    "НАЧАТЬПОЛУЧЕНИЕРАБОЧЕГОКАТАЛОГАДАННЫХПОЛЬЗОВАТЕЛЯ|BEGINGETTINGUSERDATAWORKDIR|"
    "НАЧАТЬПОЛУЧЕНИЕФАЙЛОВ|BEGINGETTINGFILES|НАЧАТЬПОМЕЩЕНИЕФАЙЛОВ|BEGINPUTTINGFILES|"
    "НАЧАТЬЗАПРОСРАЗРЕШЕНИЯПОЛЬЗОВАТЕЛЯ|BEGINREQUESTINGUSERPERMISSION|"
    "НАЧАТЬЗАПУСКПРИЛОЖЕНИЯ|BEGINRUNNINGAPPLICATION"
)

_ASYNC_ALT = "|".join(
    re.escape(n)
    for n in sorted(
        {x.strip() for x in _BSL154_ASYNC_PIPE.split("|") if x.strip()},
        key=len,
        reverse=True,
    )
)
_RE_BSL154_ASYNC = re.compile(rf"\b(?:{_ASYNC_ALT})\s*\(", re.IGNORECASE)

_RE_RETURN_OR_BREAK = re.compile(
    r"^\s*(?:Возврат|Return|Прервать|Break)\b",
    re.IGNORECASE,
)


def path_matches_bsl154_module_types(path: str) -> bool:
    """Roughly matches BSLLS ``ModuleType`` filter (form / command / managed app)."""
    low = path.replace("\\", "/").lower()
    if low.endswith("commandmodule.bsl"):
        return True
    if low.endswith("managedapplicationmodule.bsl"):
        return True
    if "/forms/" in low and low.endswith("/form/module.bsl"):
        return True
    return False


def _code_before_line_comment(line: str) -> str:
    if "//" not in line:
        return line
    return line.split("//", 1)[0]


def _first_sig_line_after(
    lines: list[str], start_after: int, body_end_exclusive: int
) -> tuple[int, str] | None:
    """First non-empty, non-comment, non-preproc-only line in (start_after, body_end_exclusive)."""
    j = start_after
    while j < body_end_exclusive and j < len(lines):
        raw = lines[j]
        s = _code_before_line_comment(raw).strip()
        if not s:
            j += 1
            continue
        if s.startswith("#"):
            j += 1
            continue
        return j, raw
    return None


def _has_blocking_followup(lines: list[str], async_line: int, proc_end_idx: int) -> bool:
    """
    True if the first significant line after *async_line* in the procedure body
    is not ``Возврат``/``Return``/``Прервать``/``Break`` (BSLLS ``checkNextBlocks`` subset).
    """
    first = _first_sig_line_after(lines, async_line + 1, proc_end_idx)
    if first is None:
        return False
    _li, raw = first
    stmt = _code_before_line_comment(raw).strip()
    if _RE_RETURN_OR_BREAK.match(stmt):
        return False
    return True


def bsl154_code_after_async_spans(
    path: str,
    lines: list[str],
    procedures: list[tuple[int, int]],
) -> list[tuple[int, int, int, str]]:
    """
    Return (line_1based, start_col, end_col_exclusive, method_name) per hit.

    *procedures*: ``(header_line_0, end_line_0)`` as ``_ProcInfo.start_idx/end_idx``.
    """
    if not path_matches_bsl154_module_types(path):
        return []
    out: list[tuple[int, int, int, str]] = []
    for start_idx, end_idx in procedures:
        body_start = start_idx + 1
        body_end_excl = end_idx
        if body_end_excl <= body_start:
            continue
        for li in range(body_start, body_end_excl):
            code_part = _code_before_line_comment(lines[li])
            for m in _RE_BSL154_ASYNC.finditer(code_part):
                raw_m = m.group(0)
                method = raw_m[:-1].strip() if raw_m.endswith("(") else raw_m.strip()
                if not _has_blocking_followup(lines, li, end_idx):
                    continue
                c1 = m.start() + len(method)
                out.append((li + 1, m.start(), c1, method))
    return out
