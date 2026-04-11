"""
Common-module diagnostics aligned with BSLLS (BSL158–BSL168 and helpers).

BSL158 — assignment to a name that is a *common module* metadata object (needs index).
BSL159 — common module XML matches no BSLLS execution context (see ``flagsCheck`` in
``AbstractCommonModuleNameDiagnostic`` — same as raw-flag combinations, not «any tag true»).
BSL160 — common module has methods but no export and/or no Public/Internal API region.
BSL161–BSL168 — common module name vs metadata (BSLLS ``CommonModuleName*`` diagnostics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.rules.bsl152 import (
    common_module_xml_for_module_bsl,
    return_values_reuse_cached_from_xml_text,
)

_RE_SIMPLE_LHS_ASSIGN = re.compile(r"^\s*(\w+)\s*=(?!=)")
# BSLLS CommonModuleMissingAPIDiagnostic — Public / Internal API regions
_API_REGION_NAMES_CF = frozenset(
    {
        "public",
        "программныйинтерфейс",
        "internal",
        "служебныйпрограммныйинтерфейс",
    }
)

# BSLLS CommonModuleName* — same patterns as CaseInsensitivePattern in Java
_RE_NAME_CACHED = re.compile(
    r"повторноеиспользование|повтисп|cached",
    re.IGNORECASE,
)
_RE_NAME_CLIENT = re.compile(r"клиент|client", re.IGNORECASE)
_RE_NAME_CLIENT_SERVER = re.compile(r"клиентсервер|clientserver", re.IGNORECASE)
_RE_NAME_FULL_ACCESS = re.compile(r"полныеправа|fullaccess", re.IGNORECASE)
_RE_NAME_GLOBAL = re.compile(r"глобальный|global", re.IGNORECASE)
_RE_NAME_SERVER_CALL = re.compile(r"вызовсервера|servercall", re.IGNORECASE)
# CommonModuleNameWordsDiagnostic default
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
    """
    BSLLS ``AbstractCommonModuleNameDiagnostic``: ``isServer``, ``isServerCall``,
    ``isClient``, ``isClientServer``.
    """
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
    """
    Mirrors BSLLS ``CommonModuleInvalidTypeDiagnostic.flagsCheck``.

    Returns ``True`` when the module matches *no* valid context (diagnostic should fire).
    """
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
    """
    BSL159 — BSLLS ``CommonModuleInvalidType``: metadata does not describe any allowed
    execution context (server / server call / client / client-server).

    Uses the same four predicates as BSLLS on sibling ``<Name>.xml`` booleans
    (``Server``, ``ServerCall``, ``ExternalConnection``, ``ClientOrdinaryApplication``,
    ``ClientManagedApplication``). If the XML does not contain the known property tags,
    returns ``None`` (unknown / legacy layout).
    """
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


@dataclass(frozen=True)
class _CommonModuleXmlSnapshot:
    """Sibling ``CommonModule`` XML fields used by BSL161–BSL168."""

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
    """
    BSL161–BSL168 — BSLLS ``CommonModuleName*``: naming vs flags / forbidden words.

    Returns ``(code, message)`` pairs for each violated rule (may be several).
    """
    snap = _load_common_module_xml_snapshot(module_bsl_path)
    if snap is None:
        return []
    name = snap.module_name
    is_s, is_sc, is_cl, is_cs = _execution_context_predicates(
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
    """
    Return (line_1based, c0, c1, module_name) for simple ``Name =`` assignments
    where *Name* is indexed as ``CommonModule``.
    """
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
    """
    True if diagnostic should be raised (BSLLS ``CommonModuleMissingAPIDiagnostic``).

    *procedures_export*: ``is_export`` for each procedure/function in module order.
    """
    if common_module_xml_for_module_bsl(module_bsl_path) is None:
        return False
    if not procedures_export:
        return False
    no_export = not any(procedures_export)
    no_api_region = not common_module_has_api_region(region_names)
    return no_export or no_api_region


def bsl160_module_line1_span(lines: list[str]) -> tuple[int, int] | None:
    """Range on first line for whole-module diagnostic."""
    if not lines:
        return None
    line = lines[0]
    c0 = len(line) - len(line.lstrip())
    c1 = len(line.rstrip())
    if c1 <= c0:
        return 0, 1
    return c0, c1
