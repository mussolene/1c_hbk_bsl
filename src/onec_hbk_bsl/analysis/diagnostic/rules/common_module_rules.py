from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from onec_hbk_bsl.analysis.diagnostics_bsl152 import bsl152_public_region_name_spans
from onec_hbk_bsl.analysis.diagnostics_bsl154 import bsl154_code_after_async_spans
from onec_hbk_bsl.analysis.diagnostics_bsl155 import bsl155_code_block_before_sub
from onec_hbk_bsl.analysis.diagnostics_bsl156 import bsl156_diagnostics
from onec_hbk_bsl.analysis.diagnostics_common_module import (
    bsl158_common_module_assign_spans,
    bsl160_common_module_missing_api,
    bsl160_module_line1_span,
    common_module_name_convention_issues,
    common_module_xml_flags_invalid,
)

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostics import _ProcInfo, _RegionInfo


def _diag_types() -> tuple[type[Any], Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag.Diagnostic, _diag.Severity


def run_bsl152_cached_public(
    path: str,
    lines: list[str],
    regions: list[_RegionInfo],
    procs: list[_ProcInfo],
) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    reg_tuples = [(r.name, r.start_idx, r.end_idx) for r in regions]
    proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
    diags: list[Any] = []
    for line_1, c0, c1 in bsl152_public_region_name_spans(path, lines, reg_tuples, proc_tuples):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.WARNING,
                code="BSL152",
                message=(
                    "Не следует размещать программный интерфейс в общем модуле "
                    "с повторным использованием возвращаемых значений "
                    "(BSLLS CachedPublic)."
                ),
            )
        )
    return diags


def run_bsl154_code_after_async(path: str, lines: list[str], procs: list[_ProcInfo]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
    diags: list[Any] = []
    for line_1, c0, c1, method in bsl154_code_after_async_spans(path, lines, proc_tuples):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.WARNING,
                code="BSL154",
                message=(
                    f"После асинхронного вызова «{method}» следует исполняемый код "
                    f"(BSLLS CodeAfterAsyncCall)."
                ),
            )
        )
    return diags


def run_bsl155_code_block_before_sub(
    path: str, lines: list[str], procs: list[_ProcInfo]
) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
    diags: list[Any] = []
    for line_1, c0, c1, msg in bsl155_code_block_before_sub(lines, proc_tuples):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.WARNING,
                code="BSL155",
                message=msg,
            )
        )
    return diags


def run_bsl156_code_out_of_region(path: str, lines: list[str], procs: list[_ProcInfo]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    triples = [(p.start_idx, p.end_idx, p.name) for p in procs]
    diags: list[Any] = []
    for line_1, c0, c1, msg in bsl156_diagnostics(path, lines, triples):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.INFORMATION,
                code="BSL156",
                message=msg,
            )
        )
    return diags


def run_bsl158_common_module_assign(path: str, lines: list[str], symbol_index: Any) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    diags: list[Any] = []
    for line_1, c0, c1, name in bsl158_common_module_assign_spans(lines, symbol_index):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.ERROR,
                code="BSL158",
                message=(
                    f"Нельзя присваивать значение объекту общего модуля «{name}» "
                    f"(BSLLS CommonModuleAssign)."
                ),
            )
        )
    return diags


def run_bsl159_common_module_invalid_type(path: str, lines: list[str]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    inv = common_module_xml_flags_invalid(path)
    if inv is not True:
        return []
    span = bsl160_module_line1_span(lines)
    c0, c1 = span if span is not None else (0, 1)
    return [
        Diagnostic(
            file=path,
            line=1,
            character=c0,
            end_line=1,
            end_character=c1,
            severity=Severity.ERROR,
            code="BSL159",
            message=(
                "У общего модуля не задан контекст выполнения в метаданных "
                "(BSLLS CommonModuleInvalidType)."
            ),
        )
    ]


def run_bsl160_common_module_missing_api(
    path: str,
    lines: list[str],
    regions: list[_RegionInfo],
    procs: list[_ProcInfo],
) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    if not bsl160_common_module_missing_api(
        path,
        [r.name for r in regions],
        [p.is_export for p in procs],
    ):
        return []
    span = bsl160_module_line1_span(lines)
    if span is None:
        return []
    c0, c1 = span
    return [
        Diagnostic(
            file=path,
            line=1,
            character=c0,
            end_line=1,
            end_character=c1,
            severity=Severity.INFORMATION,
            code="BSL160",
            message=(
                "В общем модуле нет экспортных методов и/или областей "
                "программного интерфейса (Public/Internal) "
                "(BSLLS CommonModuleMissingAPI)."
            ),
        )
    ]


def run_bsl161_168_common_module_names(
    rule_enabled: Any,
    path: str,
    lines: list[str],
    codes: tuple[str, ...],
) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    issues = common_module_name_convention_issues(path)
    if not issues:
        return []
    span = bsl160_module_line1_span(lines)
    c0, c1 = span if span is not None else (0, 1)
    enabled = {c for c in codes if rule_enabled(c)}
    out: list[Any] = []
    for code, message in issues:
        if code not in enabled:
            continue
        out.append(
            Diagnostic(
                file=path,
                line=1,
                character=c0,
                end_line=1,
                end_character=c1,
                severity=Severity.INFORMATION,
                code=code,
                message=message,
            )
        )
    return out


def run_bsl172_data_exchange_loading(path: str, lines: list[str], procs: list[Any]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    diags: list[Any] = []
    low_path = path.replace("\\", "/").lower()
    if not (
        low_path.endswith("/ext/objectmodule.bsl")
        or low_path.endswith("/ext/recordsetmodule.bsl")
        or low_path.endswith("/ext/valuemanagermodule.bsl")
    ):
        return []
    re_handler = re.compile(
        r"^\s*(?:Процедура|Procedure)\s+"
        r"(?:ПередЗаписью|BeforeWrite|ПриЗаписи|OnWrite|"
        r"ПередУдалением|BeforeDelete)\s*\(",
        re.IGNORECASE | re.UNICODE,
    )
    re_exchange = re.compile(r"(?:ОбменДанными\.Загрузка|DataExchange\.Load)\b", re.IGNORECASE)
    re_if = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE | re.UNICODE)
    re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE | re.UNICODE)
    re_return = re.compile(r"^\s*(?:Возврат|Return)\b", re.IGNORECASE | re.UNICODE)

    for proc in procs:
        start = proc.start_idx
        line = lines[start] if start < len(lines) else ""
        if not re_handler.match(line):
            continue

        body_start = start + 1
        body_end = min(proc.end_idx, len(lines))
        has_check = False
        i = body_start
        while i < body_end:
            raw = lines[i]
            if not re_if.match(raw) or not re_exchange.search(raw):
                i += 1
                continue
            depth = 1
            j = i + 1
            branch_has_return = False
            while j < body_end and depth > 0:
                branch_line = lines[j]
                if re_if.match(branch_line):
                    depth += 1
                elif re_endif.match(branch_line):
                    depth -= 1
                    if depth == 0:
                        break
                if re_return.match(branch_line):
                    branch_has_return = True
                j += 1
            if branch_has_return:
                has_check = True
                break
            i = max(j, i + 1)
        if not has_check:
            name_pos = line.find(proc.name) if proc.name in line else 0
            diags.append(
                Diagnostic(
                    file=path,
                    line=start + 1,
                    character=name_pos,
                    end_line=start + 1,
                    end_character=(name_pos + len(proc.name)) if proc.name in line else len(line),
                    severity=Severity.ERROR,
                    code="BSL172",
                    message="Добавьте проверку признака ОбменДанными.Загрузка в самом начале процедуры",
                )
            )
    return diags


def run_bsl173_deleting_collection_item(path: str, lines: list[str], procs: list[Any]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    diags: list[Any] = []
    re_foreach = re.compile(
        r"^\s*(?:Для\s+Каждого|For\s+Each)\s+(\w+)\s+(?:Из|In)\s+(\w+(?:\.\w+)*)",
        re.IGNORECASE | re.UNICODE,
    )
    re_end_loop = re.compile(r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE)
    re_delete = re.compile(
        r"(\w+(?:\.\w+)*)\s*\.\s*(?:Удалить|Delete)\s*\(",
        re.IGNORECASE | re.UNICODE,
    )
    i = 0
    while i < len(lines):
        m = re_foreach.match(lines[i])
        if m:
            iter_var = m.group(1).casefold()
            collection = m.group(2).casefold()
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                bl = lines[j]
                if re_foreach.match(bl):
                    depth += 1
                elif re_end_loop.match(bl):
                    depth -= 1
                    if depth == 0:
                        break
                if depth == 1:
                    dm = re_delete.search(bl)
                    if dm:
                        obj = dm.group(1).casefold().split(".")[-1]
                        arg_start = bl.find("(", dm.end() - 1) + 1
                        arg_end = bl.find(")", arg_start) if arg_start > 0 else -1
                        arg = (
                            bl[arg_start:arg_end].strip().casefold() if arg_end > arg_start else ""
                        )
                        if obj == collection or arg == iter_var:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=dm.start(),
                                    end_line=j + 1,
                                    end_character=dm.end(),
                                    severity=Severity.ERROR,
                                    code="BSL173",
                                    message=(
                                        "Удаление элемента коллекции внутри цикла "
                                        "«Для Каждого» может привести к ошибке"
                                    ),
                                )
                            )
                j += 1
        i += 1
    return diags
