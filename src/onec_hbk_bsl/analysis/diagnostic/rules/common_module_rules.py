from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    bsl154_code_after_async_spans_cst,
    bsl156_diagnostics,
)

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostic.models import ProcInfo as _ProcInfo
    from onec_hbk_bsl.analysis.diagnostic.models import RegionInfo as _RegionInfo

_RE_SIMPLE_LHS_ASSIGN = re.compile(r"^\s*(\w+)\s*=(?!=)")
_RVR_RE = re.compile(
    r"<ReturnValuesReuse>\s*([^<]+?)\s*</ReturnValuesReuse>",
    re.IGNORECASE,
)
_API_REGION_NAMES_CF = frozenset(
    {
        "public",
        "программныйинтерфейс",
        "internal",
        "служебныйпрограммныйинтерфейс",
    }
)
_CACHED_REUSE_VALUES = frozenset({"duringrequest", "duringsession"})
_RE_REGION_NAME_COL = re.compile(r"^\s*#(?:Область|Region)\s+(\S+)", re.IGNORECASE)
_PUBLIC_REGION_NAMES = frozenset({"public", "программныйинтерфейс"})
_RE_NAME_CACHED = re.compile(r"повторноеиспользование|повтисп|cached", re.IGNORECASE)
_RE_NAME_CLIENT = re.compile(r"клиент|client", re.IGNORECASE)
_RE_NAME_CLIENT_SERVER = re.compile(r"клиентсервер|clientserver", re.IGNORECASE)
_RE_NAME_FULL_ACCESS = re.compile(r"полныеправа|fullaccess", re.IGNORECASE)
_RE_NAME_GLOBAL = re.compile(r"глобальный|global", re.IGNORECASE)
_RE_NAME_SERVER_CALL = re.compile(r"вызовсервера|servercall", re.IGNORECASE)
_RE_NAME_FORBIDDEN_WORDS = re.compile(
    r"процедуры|procedures|"
    r"функции|functions|"
    r"обработчики|handlers|"
    r"модуль|module|"
    r"функциональность|functionality",
    re.IGNORECASE,
)
_RE_XML_NAME = re.compile(r"<Name>\s*([^<]+?)\s*</Name>", re.IGNORECASE)


def _xml_bool_tag(text: str, local: str) -> bool:
    m = re.search(rf"<{local}>\s*(true|false)\s*</{local}>", text, re.IGNORECASE)
    return m is not None and m.group(1).lower() == "true"


def _execution_context_predicates(
    *,
    server_call: bool,
    server: bool,
    external_connection: bool,
    client_ordinary_application: bool,
    client_managed_application: bool,
    ordinary_app_support: bool = True,
) -> tuple[bool, bool, bool, bool]:
    oa = client_ordinary_application or not ordinary_app_support

    def _is_client_application() -> bool:
        return oa and client_managed_application

    is_client_server = (
        not server_call and server and external_connection and _is_client_application()
    )
    is_client = (
        not server_call and not server and not external_connection and _is_client_application()
    )
    is_server_call = (
        server_call
        and server
        and not external_connection
        and not client_ordinary_application
        and not client_managed_application
    )
    is_server = (
        not server_call and server and external_connection and oa and not client_managed_application
    )
    return is_server, is_server_call, is_client, is_client_server


def _bslls_common_module_invalid_type_flags(
    *,
    server_call: bool,
    server: bool,
    external_connection: bool,
    client_ordinary_application: bool,
    client_managed_application: bool,
    ordinary_app_support: bool = True,
) -> bool:
    preds = _execution_context_predicates(
        server_call=server_call,
        server=server,
        external_connection=external_connection,
        client_ordinary_application=client_ordinary_application,
        client_managed_application=client_managed_application,
        ordinary_app_support=ordinary_app_support,
    )
    return not any(preds)


def common_module_xml_flags_invalid(module_bsl_path: str) -> bool | None:
    xp = common_module_xml_for_module_bsl(module_bsl_path)
    if xp is None:
        return None
    try:
        raw = xp.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    if "<commonmodule" not in raw.casefold():
        return None
    if not re.search(
        r"<(?:Server|ServerCall|ClientOrdinaryApplication|ClientManagedApplication|"
        r"ExternalConnection|GlobalClientManagedApplication)\s*>",
        raw,
        re.IGNORECASE,
    ):
        return None
    s = _xml_bool_tag(raw, "Server")
    sc = _xml_bool_tag(raw, "ServerCall")
    coa = _xml_bool_tag(raw, "ClientOrdinaryApplication")
    cma = _xml_bool_tag(raw, "ClientManagedApplication")
    ext = _xml_bool_tag(raw, "ExternalConnection")
    return _bslls_common_module_invalid_type_flags(
        server_call=sc,
        server=s,
        external_connection=ext,
        client_ordinary_application=coa,
        client_managed_application=cma,
    )


def common_module_execute_external_code_applicable(module_bsl_path: str) -> bool:
    xp = common_module_xml_for_module_bsl(module_bsl_path)
    if xp is None:
        return False
    try:
        raw = xp.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    if "<commonmodule" not in raw.casefold():
        return False
    return (
        _xml_bool_tag(raw, "Server")
        or _xml_bool_tag(raw, "ClientOrdinaryApplication")
        or _xml_bool_tag(raw, "ExternalConnection")
    )


@dataclass(frozen=True)
class _CommonModuleXmlSnapshot:
    module_name: str
    is_global: bool
    is_privileged: bool
    server_call: bool
    server: bool
    external_connection: bool
    client_ordinary_application: bool
    client_managed_application: bool
    rvr_cached: bool


def _load_common_module_xml_snapshot(module_bsl_path: str) -> _CommonModuleXmlSnapshot | None:
    xp = common_module_xml_for_module_bsl(module_bsl_path)
    if xp is None:
        return None
    try:
        raw = xp.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    if "<commonmodule" not in raw.casefold():
        return None
    mod_dir = Path(module_bsl_path).parent.parent
    m = _RE_XML_NAME.search(raw)
    module_name = m.group(1).strip() if m else mod_dir.name
    return _CommonModuleXmlSnapshot(
        module_name=module_name,
        is_global=_xml_bool_tag(raw, "Global"),
        is_privileged=_xml_bool_tag(raw, "Privileged"),
        server_call=_xml_bool_tag(raw, "ServerCall"),
        server=_xml_bool_tag(raw, "Server"),
        external_connection=_xml_bool_tag(raw, "ExternalConnection"),
        client_ordinary_application=_xml_bool_tag(raw, "ClientOrdinaryApplication"),
        client_managed_application=_xml_bool_tag(raw, "ClientManagedApplication"),
        rvr_cached=return_values_reuse_cached_from_xml_text(raw),
    )


def common_module_name_convention_issues(module_bsl_path: str) -> list[tuple[str, str]]:
    snap = _load_common_module_xml_snapshot(module_bsl_path)
    if snap is None:
        return []
    name = snap.module_name
    _, is_sc, is_cl, is_cs = _execution_context_predicates(
        server_call=snap.server_call,
        server=snap.server,
        external_connection=snap.external_connection,
        client_ordinary_application=snap.client_ordinary_application,
        client_managed_application=snap.client_managed_application,
    )
    out: list[tuple[str, str]] = []

    if snap.rvr_cached and _RE_NAME_CACHED.search(name) is None:
        out.append(
            (
                "BSL161",
                "Имя кэшируемого общего модуля должно отражать кэширование "
                "(«ПовтИсп», «Cached», …) (BSLLS CommonModuleNameCached).",
            )
        )
    if not snap.is_global and is_cl and _RE_NAME_CLIENT.search(name) is None:
        out.append(
            (
                "BSL162",
                "Имя клиентского общего модуля должно содержать «Клиент» или «Client» "
                "(BSLLS CommonModuleNameClient).",
            )
        )
    if is_cs and _RE_NAME_CLIENT_SERVER.search(name) is None:
        out.append(
            (
                "BSL163",
                "Имя клиент-серверного общего модуля должно содержать "
                "«КлиентСервер» или «ClientServer» (BSLLS CommonModuleNameClientServer).",
            )
        )
    if snap.is_privileged and _RE_NAME_FULL_ACCESS.search(name) is None:
        out.append(
            (
                "BSL164",
                "Имя привилегированного общего модуля должно содержать "
                "«ПолныеПрава» или «FullAccess» (BSLLS CommonModuleNameFullAccess).",
            )
        )
    if snap.is_global and _RE_NAME_GLOBAL.search(name) is None:
        out.append(
            (
                "BSL165",
                "Имя глобального общего модуля должно содержать "
                "«Глобальный» или «Global» (BSLLS CommonModuleNameGlobal).",
            )
        )
    if snap.is_global and is_cl and _RE_NAME_CLIENT.search(name) is None:
        out.append(
            (
                "BSL166",
                "Имя глобального клиентского общего модуля должно содержать "
                "«Клиент» или «Client» (BSLLS CommonModuleNameGlobalClient).",
            )
        )
    if is_sc and _RE_NAME_SERVER_CALL.search(name) is None:
        out.append(
            (
                "BSL167",
                "Имя модуля с вызовом сервера должно содержать "
                "«ВызовСервера» или «ServerCall» (BSLLS CommonModuleNameServerCall).",
            )
        )
    if _RE_NAME_FORBIDDEN_WORDS.search(name):
        out.append(
            (
                "BSL168",
                "В имени общего модуля не должно быть слов вроде «Процедуры», "
                "«Модуль», … (BSLLS CommonModuleNameWords).",
            )
        )
    return out


def bsl158_common_module_assign_spans(
    lines: list[str],
    symbol_index: Any,
) -> list[tuple[int, int, int, str]]:
    if symbol_index is None or not getattr(symbol_index, "has_metadata", lambda: False)():
        return []
    out: list[tuple[int, int, int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        m = _RE_SIMPLE_LHS_ASSIGN.match(line)
        if not m:
            continue
        name = m.group(1)
        mo = symbol_index.find_meta_object(name)
        if mo is None or mo.get("kind") != "CommonModule":
            continue
        c0, c1 = m.start(1), m.end(1)
        out.append((i + 1, c0, c1, name))
    return out


def common_module_has_api_region(region_names: list[str]) -> bool:
    for n in region_names:
        if n.strip().casefold() in _API_REGION_NAMES_CF:
            return True
    return False


def bsl160_common_module_missing_api(
    module_bsl_path: str,
    region_names: list[str],
    procedures_export: list[bool],
) -> bool:
    if common_module_xml_for_module_bsl(module_bsl_path) is None:
        return False
    if not procedures_export:
        return False
    no_export = not any(procedures_export)
    no_api_region = not common_module_has_api_region(region_names)
    return no_export or no_api_region


def bsl160_module_line1_span(lines: list[str]) -> tuple[int, int] | None:
    if not lines:
        return None
    line = lines[0]
    c0 = len(line) - len(line.lstrip())
    c1 = len(line.rstrip())
    if c1 <= c0:
        return 0, 1
    return c0, c1


def _diag_types() -> tuple[type[Any], Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag.Diagnostic, _diag.Severity


def common_module_xml_for_module_bsl(module_bsl_path: str) -> Path | None:
    p = Path(module_bsl_path)
    lower_parts = {x.lower() for x in p.parts}
    if "commonmodules" not in lower_parts and "общиемодули" not in lower_parts:
        return None
    if p.name.lower() != "module.bsl":
        return None
    if p.parent.name.lower() != "ext":
        return None
    mod_dir = p.parent.parent
    sibling_xml = mod_dir.parent / f"{mod_dir.name}.xml"
    if sibling_xml.is_file():
        return sibling_xml
    nested_xml = mod_dir / f"{mod_dir.name}.xml"
    return nested_xml if nested_xml.is_file() else None


def return_values_reuse_cached_from_xml_text(raw: str) -> bool:
    m = _RVR_RE.search(raw)
    if not m:
        return False
    val = m.group(1).strip().casefold()
    val = val.split(":")[-1].strip()
    return val in _CACHED_REUSE_VALUES


def common_module_bslls_cached_reuse(module_bsl_path: str) -> bool:
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
            )
        )
    return diags


def run_bsl154_code_after_async(path: str, tree: object | None) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    diags: list[Any] = []
    for line_1, c0, end_line_1, c1, _method in bsl154_code_after_async_spans_cst(path, tree):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=end_line_1,
                end_character=c1,
                severity=Severity.WARNING,
                code="BSL154",
            )
        )
    return diags


def run_bsl156_code_out_of_region(path: str, lines: list[str], procs: list[_ProcInfo]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    triples = [(p.start_idx, p.end_idx, p.name) for p in procs]
    diags: list[Any] = []
    for line_1, c0, end_line_1, c1, _msg in bsl156_diagnostics(path, lines, triples):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=end_line_1,
                end_character=c1,
                severity=Severity.INFORMATION,
                code="BSL156",
            )
        )
    return diags


def run_bsl158_common_module_assign(path: str, lines: list[str], symbol_index: Any) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    diags: list[Any] = []
    for line_1, c0, c1, _name in bsl158_common_module_assign_spans(lines, symbol_index):
        diags.append(
            Diagnostic(
                file=path,
                line=line_1,
                character=c0,
                end_line=line_1,
                end_character=c1,
                severity=Severity.ERROR,
                code="BSL158",
            )
        )
    return diags


def run_bsl159_common_module_invalid_type(path: str, lines: list[str]) -> list[Any]:
    Diagnostic, Severity = _diag_types()
    inv = common_module_xml_flags_invalid(path)
    if inv is not True:
        return []
    return [
        Diagnostic(
            file=path,
            line=1,
            character=0,
            end_line=1,
            end_character=1,
            severity=Severity.ERROR,
            code="BSL159",
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
    for code, _message in issues:
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
                        if obj == collection:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=dm.start(),
                                    end_line=j + 1,
                                    end_character=dm.end(),
                                    severity=Severity.ERROR,
                                    code="BSL173",
                                )
                            )
                j += 1
        i += 1
    return diags
