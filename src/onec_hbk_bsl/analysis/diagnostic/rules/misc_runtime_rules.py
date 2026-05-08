from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl257_unary_plus_in_concatenation(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_unary = re.compile(r'(?:"[^"]*"|\'[^\']*\'|\b\w+\b)\s*\+\s*\+', re.UNICODE)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        clean = _diag._RE_DOUBLE_QUOTED_STRING.sub('""', line)
        match = re_unary.search(clean)
        if match:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=match.start(),
                    end_line=idx + 1,
                    end_character=match.end(),
                    severity=_diag.Severity.WARNING,
                    code="BSL257",
                    message="Унарный «+» перед значением при конкатенации — вероятно опечатка",
                )
            )
    return diags
