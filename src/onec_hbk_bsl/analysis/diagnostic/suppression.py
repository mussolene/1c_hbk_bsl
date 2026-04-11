from __future__ import annotations

from typing import Any

Suppressions = dict[int, set[str]]
BSLLS_OFF_FLAGS = frozenset({"off", "выкл"})


def parse_suppressions(lines: list[str]) -> Suppressions:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    result: Suppressions = {}
    block_all = False
    block_codes: set[str] = set()

    for idx, line in enumerate(lines):
        line_no = idx + 1
        for bm in _diag._RE_BSLLS.finditer(line):
            name = bm.group("name")
            is_off = bm.group("flag").lower() in BSLLS_OFF_FLAGS
            if name is None:
                if is_off:
                    block_all = True
                    block_codes.clear()
                else:
                    block_all = False
                    block_codes.clear()
            else:
                bsl_code = _diag._BSLLS_NAME_TO_CODE.get(name)
                if bsl_code:
                    if is_off:
                        block_codes.add(bsl_code)
                    else:
                        block_codes.discard(bsl_code)

        noqa_all = False
        noqa_codes: set[str] = set()
        m = _diag._RE_NOQA.search(line)
        if m is not None:
            codes_str = m.group("codes")
            if codes_str:
                noqa_codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
            else:
                noqa_all = True

        if block_all or noqa_all:
            result[line_no] = set()
        elif block_codes or noqa_codes:
            result[line_no] = set(block_codes) | noqa_codes

    return result


def is_suppressed(diag: Any, suppressed: Suppressions) -> bool:
    codes = suppressed.get(diag.line)
    if codes is None:
        return False
    return len(codes) == 0 or diag.code.upper() in codes
