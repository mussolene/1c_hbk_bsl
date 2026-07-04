from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.sdbl_cst import (
    QUERY_METADATA_ROOTS,
    ancestor,
    dotted_identifier_parts,
    iter_nodes,
    nullable_join_field_uses_without_isnull,
    query_source_uses,
    query_temp_table_names,
    source_alias_name,
)

_QUERY_METADATA_ROOT_TO_KIND: dict[str, str] = {
    "бизнеспроцесс": "BusinessProcess",
    "businessprocess": "BusinessProcess",
    "документ": "Document",
    "document": "Document",
    "журналдокументов": "DocumentJournal",
    "documentjournal": "DocumentJournal",
    "справочник": "Catalog",
    "catalog": "Catalog",
    "перечисление": "Enum",
    "enum": "Enum",
    "планвидовхарактеристик": "ChartOfCharacteristicTypes",
    "chartofcharacteristictypes": "ChartOfCharacteristicTypes",
    "планывидовхарактеристик": "ChartOfCharacteristicTypes",
    "chartsofcharacteristictypes": "ChartOfCharacteristicTypes",
    "плансчетов": "ChartOfAccounts",
    "chartofaccounts": "ChartOfAccounts",
    "планысчетов": "ChartOfAccounts",
    "chartsofaccounts": "ChartOfAccounts",
    "планвидоврасчета": "ChartOfCalculationTypes",
    "chartofcalculationtypes": "ChartOfCalculationTypes",
    "регистрсведений": "InformationRegister",
    "informationregister": "InformationRegister",
    "регистрнакопления": "AccumulationRegister",
    "accumulationregister": "AccumulationRegister",
    "регистрбухгалтерии": "AccountingRegister",
    "accountingregister": "AccountingRegister",
    "регистррасчета": "CalculationRegister",
    "calculationregister": "CalculationRegister",
    "задача": "Task",
    "task": "Task",
    "планобмена": "ExchangePlan",
    "exchangeplan": "ExchangePlan",
    "внешнийисточникданных": "ExternalDataSource",
    "externaldatasource": "ExternalDataSource",
    "константа": "Constant",
    "constant": "Constant",
    "отчет": "Report",
    "report": "Report",
    "обработка": "DataProcessor",
    "dataprocessor": "DataProcessor",
}

_QUERY_METADATA_ROOT_PATTERN = "|".join(
    re.escape(root) for root in sorted(QUERY_METADATA_ROOTS, key=len, reverse=True)
)

_QUERY_METADATA_TYPE_REF_RE = re.compile(
    r"\b(?:ССЫЛКА|REFS?)\s+"
    rf"(({_QUERY_METADATA_ROOT_PATTERN})\.[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*)"
    r"|"
    r"\b(?:КАК|AS)\s+"
    rf"(({_QUERY_METADATA_ROOT_PATTERN})\.[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*)\s*\)",
    re.IGNORECASE,
)
_BSL174_REGISTER_FOLDERS: frozenset[str] = frozenset(
    {
        "InformationRegisters",
        "AccumulationRegisters",
        "AccountingRegisters",
        "CalculationRegisters",
    }
)
_BSL189_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    name.casefold()
    for name in (
        "AccountingRegister",
        "AccountingRegisters",
        "AccumulationRegister",
        "AccumulationRegisters",
        "BusinessProcess",
        "BusinessProcesses",
        "CalculationRegister",
        "CalculationRegisters",
        "Catalog",
        "Catalogs",
        "ChartOfAccounts",
        "ChartOfCalculationTypes",
        "ChartOfCharacteristicTypes",
        "ChartsOfAccounts",
        "ChartsOfCalculationTypes",
        "ChartsOfCharacteristicTypes",
        "Constant",
        "Constants",
        "Document",
        "DocumentJournal",
        "DocumentJournals",
        "Documents",
        "Enum",
        "Enums",
        "ExchangePlan",
        "ExchangePlans",
        "FilterCriteria",
        "FilterCriterion",
        "InformationRegister",
        "InformationRegisters",
        "Task",
        "Tasks",
        "БизнесПроцесс",
        "БизнесПроцессы",
        "Документ",
        "Документы",
        "ЖурналДокументов",
        "ЖурналыДокументов",
        "Задача",
        "Задачи",
        "Константа",
        "Константы",
        "КритерииОтбора",
        "КритерийОтбора",
        "Перечисление",
        "Перечисления",
        "ПланВидовРасчета",
        "ПланВидовХарактеристик",
        "ПланОбмена",
        "ПланСчетов",
        "ПланыВидовРасчета",
        "ПланыВидовХарактеристик",
        "ПланыОбмена",
        "ПланыСчетов",
        "РегистрБухгалтерии",
        "РегистрНакопления",
        "РегистрРасчета",
        "РегистрСведений",
        "РегистрыБухгалтерии",
        "РегистрыНакопления",
        "РегистрыРасчета",
        "РегистрыСведений",
        "Справочник",
        "Справочники",
    )
)


def _bsl174_owner_module_matches(path: str, object_xml: Path) -> bool:
    normalized = path.replace("\\", "/").lower()
    if "/forms/" in normalized:
        return False

    manager_module = object_xml.parent / object_xml.stem / "Ext" / "ManagerModule.bsl"
    if manager_module.exists():
        try:
            return Path(path).resolve() == manager_module.resolve()
        except OSError:
            return normalized.endswith(
                f"/{object_xml.parent.name.lower()}/{object_xml.stem.lower()}/ext/managermodule.bsl"
            )

    return normalized.endswith("/ext/managermodule.bsl") or normalized.endswith(
        "/ext/recordsetmodule.bsl"
    )


def _bsl174_owner_range_end(line_text: str) -> int:
    return max(1, min(len(line_text.rstrip()), 9))


def _metadata_owner_range_end(line_text: str) -> int:
    return max(1, min(len(line_text.rstrip()), 9))


def _bsl242_proc_body_is_empty(lines: list[str], proc: Any) -> bool:
    for idx in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        return False
    return True


def _bsl244_forbidden_form_event_name(name: str) -> bool:
    name_cf = name.strip().casefold()
    return name_cf.endswith(
        (
            "приактивизациистроки",
            "onactivaterow",
            "началовыбора",
            "onstartchoice",
        )
    )


def _bsl244_proc_has_context_server_directive(lines: list[str], proc: Any) -> bool:
    idx = proc.start_idx - 1
    while idx >= 0:
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("//"):
            idx -= 1
            continue
        if not stripped.startswith("&"):
            return False
        directive = stripped[1:].casefold().replace(" ", "")
        if directive in {"насервере", "atserver"}:
            return True
        idx -= 1
    return False


def _bsl244_call_end_character(line: str, open_paren_idx: int) -> int:
    depth = 0
    for idx in range(open_paren_idx, len(line)):
        char = line[idx]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return idx + 1
    return open_paren_idx


_BSL253_TIMEOUT_ARG_INDEXES = {
    "httpсоединение": 5,
    "httpconnection": 5,
    "ftpсоединение": 6,
    "ftpconnection": 6,
    "wsопределения": 4,
    "wsdefinitions": 4,
    "wsпрокси": 5,
    "wsproxy": 5,
    "интернетпочтовыйпрофиль": 5,
    "internetmailprofile": 5,
}


def _bsl253_first_identifier_node(_diag: Any, node: Any) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == "identifier":
            return child
    return None


def _bsl253_ancestor_of_type(node: Any, node_types: set[str]) -> Any | None:
    current = node
    while current is not None:
        if getattr(current, "type", None) in node_types:
            return current
        current = getattr(current, "parent", None)
    return None


def _bsl253_argument_presence(_diag: Any, new_expression: Any) -> list[bool]:
    args_node = _diag._ts_child_of_type(new_expression, "arguments")
    if args_node is None:
        return []
    text = _diag._ts_node_text(args_node).strip()
    if len(text) >= 2 and text[0] == "(" and text[-1] == ")":
        text = text[1:-1]
    if not text.strip():
        return []
    return [bool(part.strip()) for part in _diag._split_top_level_args(text)]


def _bsl253_assignment_lhs_text(_diag: Any, assignment: Any) -> str:
    for child in getattr(assignment, "children", []) or []:
        if getattr(child, "type", None) in {"identifier", "property_access"}:
            return _diag._ts_node_text(child).strip()
    text = _diag._ts_node_text(assignment)
    return text.split("=", 1)[0].strip() if "=" in text else ""


def _bsl253_assignment_rhs_is_number_or_variable(_diag: Any, assignment: Any) -> bool:
    seen_equals = False
    for child in getattr(assignment, "children", []) or []:
        if _diag._ts_node_text(child) == "=":
            seen_equals = True
            continue
        if not seen_equals or getattr(child, "type", None) != "expression":
            continue
        expr_text = _diag._ts_node_text(child).strip()
        return bool(re.fullmatch(r"\d+(?:[.,]\d+)?|\w+", expr_text, re.IGNORECASE))
    rhs = _diag._ts_node_text(assignment).split("=", 1)[-1].strip().rstrip(";")
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?|\w+", rhs, re.IGNORECASE))


def _bsl253_assignment_variable(_diag: Any, assignment: Any) -> str:
    lhs = _bsl253_assignment_lhs_text(_diag, assignment)
    return lhs if "." not in lhs else ""


def _bsl253_timeout_assignment_target(_diag: Any, assignment: Any) -> str:
    lhs = _bsl253_assignment_lhs_text(_diag, assignment)
    if "." not in lhs:
        return ""
    obj, prop = lhs.rsplit(".", 1)
    if prop.strip().casefold() not in {"таймаут", "timeout"}:
        return ""
    if not _bsl253_assignment_rhs_is_number_or_variable(_diag, assignment):
        return ""
    return obj.strip()


def _bsl253_proc_for_line(procs: list[Any], line_idx: int) -> Any | None:
    for proc in procs:
        if proc.start_idx <= line_idx <= proc.end_idx:
            return proc
    return None


def _bsl253_has_later_timeout_assignment(
    _diag: Any,
    *,
    assignments: list[Any],
    procs: list[Any],
    variable_name: str,
    new_expression_line_idx: int,
) -> bool:
    if not variable_name:
        return False
    proc = _bsl253_proc_for_line(procs, new_expression_line_idx)
    for assignment in assignments:
        assignment_line_idx = assignment.start_point[0] + 1
        if assignment_line_idx <= new_expression_line_idx:
            continue
        if proc is not None and not (proc.start_idx <= assignment_line_idx <= proc.end_idx):
            continue
        target = _bsl253_timeout_assignment_target(_diag, assignment)
        if target.casefold() == variable_name.casefold():
            return True
    return False


def _bsl253_timeout_diagnostics_from_cst(
    path: str,
    lines: list[str],
    procs: list[Any],
    tree: Any | None,
    snapshot: Any | None,
    nodes_by_type: dict[str, list[Any]] | None = None,
) -> list[Any] | None:
    _diag = _diag_module()
    if tree is None or getattr(tree, "root_node", None) is None:
        return None
    if nodes_by_type is not None:
        nodes = {
            "new_expression": nodes_by_type.get("new_expression", []),
            "assignment_statement": nodes_by_type.get("assignment_statement", []),
        }
    elif snapshot is not None and getattr(snapshot, "tree", None) is tree:
        nodes = snapshot.ts_nodes_for_types(
            {"new_expression", "assignment_statement"},
            walker=_diag._ts_walk,
        )
    else:
        nodes = {"new_expression": [], "assignment_statement": []}
        for node in _diag._ts_walk(tree.root_node):
            node_type = getattr(node, "type", None)
            if node_type in nodes:
                nodes[node_type].append(node)
    if not nodes["new_expression"] and not nodes["assignment_statement"]:
        return None

    diags: list[Any] = []
    assignments = nodes["assignment_statement"]
    for new_expression in nodes["new_expression"]:
        type_node = _bsl253_first_identifier_node(_diag, new_expression)
        if type_node is None:
            continue
        type_name_cf = _diag._ts_node_text(type_node).casefold()
        need_idx = _BSL253_TIMEOUT_ARG_INDEXES.get(type_name_cf)
        if need_idx is None:
            continue
        args = _bsl253_argument_presence(_diag, new_expression)
        if len(args) > need_idx and args[need_idx]:
            continue
        assignment = _bsl253_ancestor_of_type(new_expression, {"assignment_statement"})
        variable_name = _bsl253_assignment_variable(_diag, assignment) if assignment else ""
        if _bsl253_has_later_timeout_assignment(
            _diag,
            assignments=assignments,
            procs=procs,
            variable_name=variable_name,
            new_expression_line_idx=new_expression.start_point[0] + 1,
        ):
            continue
        line_idx = type_node.start_point[0]
        line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
        character = _diag.utf8_byte_offset_to_lsp_character(line_text, type_node.start_point[1])
        end_character = _diag.utf8_byte_offset_to_lsp_character(line_text, type_node.end_point[1])
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=line_idx + 1,
                character=character,
                end_line=line_idx + 1,
                end_character=end_character,
                severity=_diag.Severity.ERROR,
                code="BSL253",
            )
        )
    return diags


def _bsl261_parent_of_type(node: Any, node_types: set[str]) -> Any | None:
    current = getattr(node, "parent", None)
    while current is not None:
        if getattr(current, "type", None) in node_types:
            return current
        current = getattr(current, "parent", None)
    return None


def _bsl261_enclosing_if_statement(node: Any) -> Any | None:
    current = getattr(node, "parent", None)
    while current is not None:
        if getattr(current, "type", None) == "if_statement":
            return current
        if getattr(current, "type", None) in {"procedure_definition", "function_definition"}:
            return None
        current = getattr(current, "parent", None)
    return None


def _bsl261_identifier_node(_diag: Any, method_call: Any) -> Any | None:
    return _diag._ts_child_of_type(method_call, "identifier")


def _bsl261_is_explicit_comparison(text: str) -> bool:
    return bool(re.search(r"(?:<>|<=|>=|=|(?<![<>=])[<>](?![<>=]))", text))


def _bsl261_has_bool_operator(text: str) -> bool:
    return bool(re.search(r"\b(?:И|Или|And|Or)\b", text, re.IGNORECASE))


def _bsl261_is_unsafe_safe_mode_call(_diag: Any, method_call: Any) -> bool:
    if _bsl261_enclosing_if_statement(method_call) is None:
        return False
    call_text = _diag._ts_node_text(method_call).strip()
    expression = _bsl261_parent_of_type(method_call, {"expression"})
    if expression is None:
        return False
    expression_text = _diag._ts_node_text(expression).strip()
    if expression_text == call_text:
        parent = getattr(expression, "parent", None)
        if getattr(parent, "type", None) == "unary_expression":
            return True
        if getattr(parent, "type", None) == "binary_expression":
            root_text = _diag._ts_node_text(parent)
            return _bsl261_has_bool_operator(root_text) and not _bsl261_is_explicit_comparison(
                root_text
            )
        return True

    root = expression
    while getattr(getattr(root, "parent", None), "type", None) in {
        "expression",
        "binary_expression",
        "unary_expression",
    }:
        root = root.parent
    root_text = _diag._ts_node_text(root)
    if _bsl261_is_explicit_comparison(root_text):
        return False
    return _bsl261_has_bool_operator(root_text) or getattr(root, "type", None) == "unary_expression"


def _bsl261_diagnostics_from_cst(
    path: str,
    lines: list[str],
    tree: Any | None,
    snapshot: Any | None,
    nodes_by_type: dict[str, list[Any]] | None = None,
) -> list[Any] | None:
    _diag = _diag_module()
    if tree is None or getattr(tree, "root_node", None) is None:
        return None
    if nodes_by_type is not None:
        nodes = {"method_call": nodes_by_type.get("method_call", [])}
    elif snapshot is not None and getattr(snapshot, "tree", None) is tree:
        nodes = snapshot.ts_nodes_for_types({"method_call"}, walker=_diag._ts_walk)
    else:
        nodes = {"method_call": []}
        for node in _diag._ts_walk(tree.root_node):
            if getattr(node, "type", None) == "method_call":
                nodes["method_call"].append(node)
    if not nodes["method_call"]:
        return None

    diags: list[Any] = []
    for method_call in nodes["method_call"]:
        ident = _bsl261_identifier_node(_diag, method_call)
        if ident is None:
            continue
        if _diag._ts_node_text(ident).casefold() not in {"безопасныйрежим", "safemode"}:
            continue
        if not _bsl261_is_unsafe_safe_mode_call(_diag, method_call):
            continue
        line_idx = ident.start_point[0]
        line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
        character = _diag.utf8_byte_offset_to_lsp_character(line_text, ident.start_point[1])
        end_character = _diag.utf8_byte_offset_to_lsp_character(line_text, ident.end_point[1])
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=line_idx + 1,
                character=character,
                end_line=line_idx + 1,
                end_character=end_character,
                severity=_diag.Severity.ERROR,
                code="BSL261",
            )
        )
    return diags


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _missing_metadata_name(
    source: str,
    meta_names: set[tuple[str, str]],
) -> str | None:
    parts = source.split(".")
    if not parts:
        return None
    if len(parts) == 1:
        return None
    root = parts[0].casefold()
    kind = _QUERY_METADATA_ROOT_TO_KIND.get(root)
    if kind is None:
        return None
    object_name = parts[1]
    if (kind.casefold(), object_name.casefold()) in meta_names:
        return None
    return ".".join(parts[:2])


def _bsl238_redundant_ref_nodes(root: Any) -> list[Any]:
    query_scopes = list(iter_nodes(root, "query"))
    if not query_scopes:
        query_scopes = [root]

    out: list[Any] = []
    for scope in query_scopes:
        out.extend(_bsl238_redundant_ref_nodes_in_scope(scope))
    return out


def _bsl238_nearest_query(node: Any) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == "query":
            return parent
        parent = getattr(parent, "parent", None)
    return None


def _bsl238_same_node(left: Any | None, right: Any | None) -> bool:
    return (
        left is not None
        and right is not None
        and getattr(left, "id", None) == getattr(right, "id", None)
    )


def _bsl238_source_owner(node: Any) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) in {"table_source", "join_clause"}:
            return parent
        if getattr(parent, "type", None) in {"from_clause", "query", "source_file"}:
            return None
        parent = getattr(parent, "parent", None)
    return None


def _bsl238_redundant_ref_nodes_in_scope(scope: Any) -> list[Any]:
    simple_source_aliases: set[str] = set()
    tabular_section_aliases: set[str] = set()
    tabular_section_roots = {
        "бизнеспроцесс",
        "businessprocess",
        "документ",
        "document",
        "справочник",
        "catalog",
    }
    for source_use in query_source_uses(scope):
        if not _bsl238_same_node(_bsl238_nearest_query(source_use.node), scope):
            continue
        source_parts = source_use.source.split(".")
        source_owner = _bsl238_source_owner(source_use.node)
        alias = source_alias_name(source_owner) if source_owner is not None else None
        if not alias:
            continue
        alias_cf = alias.casefold()
        if len(source_parts) == 1:
            simple_source_aliases.add(alias_cf)
        elif len(source_parts) >= 3 and source_parts[0].casefold() in tabular_section_roots:
            tabular_section_aliases.add(alias_cf)

    out: list[Any] = []
    for dotted in iter_nodes(scope, "dotted_identifier"):
        if not _bsl238_same_node(_bsl238_nearest_query(dotted), scope):
            continue
        from_clause = ancestor(dotted, "from_clause")
        if from_clause is not None and _bsl238_same_node(_bsl238_nearest_query(from_clause), scope):
            continue
        parts = dotted_identifier_parts(dotted)
        if len(parts) < 3:
            continue
        ref_indexes = [
            idx
            for idx, part in enumerate(parts[1:], start=1)
            if part.casefold() in {"ссылка", "reference", "ref"}
        ]
        if not ref_indexes:
            continue
        root_alias = parts[0].casefold()
        last_ref_index = ref_indexes[-1]
        if root_alias in (simple_source_aliases | tabular_section_aliases) and last_ref_index == 1:
            continue
        out.append(dotted)
    return out


def _run_bsl187_on_sdbl_tree(path: str, block: Any) -> list[Any]:
    tree = getattr(block, "sdbl_tree", None)
    root = getattr(tree, "root_node", None)
    if root is None:
        return []

    _diag = _diag_module()
    diags: list[Any] = []
    seen: set[int] = set()
    for usage in nullable_join_field_uses_without_isnull(root):
        node = usage.join_node
        key = getattr(node, "id", 0)
        if key in seen:
            continue
        seen.add(key)
        start_line, start_char = block.original_lsp_position(
            node.start_point[0], node.start_point[1]
        )
        end_line, end_char = block.original_lsp_position(node.end_point[0], node.end_point[1])
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=start_line + 1,
                character=start_char,
                end_line=end_line + 1,
                end_character=end_char,
                severity=_diag.Severity.ERROR,
                code="BSL187",
            )
        )
    return diags


def applicable_bsl174_187_236_238_codes(
    path: str,
    enabled: tuple[str, ...],
    query_blocks: list[Any] | None,
) -> tuple[str, ...]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    out: list[str] = []

    if "BSL174" in enabled_set:
        object_xml = _diag._current_object_xml_path(path)
        object_context = _diag._current_module_xml_context(path)
        if (
            object_xml is not None
            and object_context.get("folder") in _BSL174_REGISTER_FOLDERS
            and _bsl174_owner_module_matches(path, object_xml)
        ):
            out.append("BSL174")

    if query_blocks and "BSL187" in enabled_set:
        out.append("BSL187")
    if query_blocks and "BSL236" in enabled_set:
        out.append("BSL236")
    if query_blocks and "BSL238" in enabled_set:
        out.append("BSL238")
    return tuple(code for code in enabled if code in out)


def run_bsl174_187_236_238_query_metadata_pool(
    path: str,
    lines: list[str],
    enabled: tuple[str, ...],
    query_blocks: list[Any] | None = None,
    cleaned_lines: list[str] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    root = _diag._config_root_for_file(path)
    meta_names: set[tuple[str, str]] = set()
    if "BSL236" in enabled_set and root is not None:
        meta_names = set(_diag._metadata_typed_name_index_cached(root))

    object_xml = _diag._current_object_xml_path(path)
    object_context = _diag._current_module_xml_context(path)
    if (
        "BSL174" in enabled_set
        and object_xml is not None
        and object_context.get("folder") in _BSL174_REGISTER_FOLDERS
        and _bsl174_owner_module_matches(path, object_xml)
    ):
        xml_text = _diag._read_text_cached(str(object_xml))
        for match in _diag._RE_XML_DIMENSION_BLOCK.finditer(xml_text):
            if match.group(2).lower() == "false":
                line_text = lines[0] if lines else ""
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=_bsl174_owner_range_end(line_text),
                        severity=_diag.Severity.WARNING,
                        code="BSL174",
                    )
                )

    if query_blocks is None:
        all_query_lines = []
    else:
        all_query_lines = [_diag._query_block_content_line_tuples(block) for block in query_blocks]
    if "BSL187" in enabled_set and query_blocks is not None:
        for block in query_blocks:
            diags.extend(_run_bsl187_on_sdbl_tree(path, block))

    temp_table_names: set[str] = set()
    if "BSL236" in enabled_set and query_blocks is not None:
        for block in query_blocks:
            root_node = getattr(getattr(block, "sdbl_tree", None), "root_node", None)
            if root_node is not None:
                temp_table_names.update(query_temp_table_names(root_node))

    for block_idx, query_lines in enumerate(all_query_lines):
        if not query_lines:
            continue
        block = query_blocks[block_idx] if query_blocks is not None else None
        root_node = getattr(getattr(block, "sdbl_tree", None), "root_node", None)
        if "BSL236" in enabled_set and root_node is not None:
            for source_use in query_source_uses(root_node):
                source = source_use.source
                if source.casefold() in temp_table_names:
                    continue
                missing_name = _missing_metadata_name(source, meta_names)
                if meta_names and missing_name is not None and block is not None:
                    start_line, start_char = block.original_lsp_position(
                        source_use.node.start_point[0],
                        source_use.node.start_point[1],
                    )
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=start_line + 1,
                            character=start_char,
                            end_line=start_line + 1,
                            end_character=start_char + len(missing_name),
                            severity=_diag.Severity.ERROR,
                            code="BSL236",
                        )
                    )
        if "BSL238" in enabled_set and root_node is not None and block is not None:
            for node in _bsl238_redundant_ref_nodes(root_node):
                start_line, start_char = block.original_lsp_position(
                    node.start_point[0], node.start_point[1]
                )
                end_line, end_char = block.original_lsp_position(
                    node.end_point[0], node.end_point[1]
                )
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=start_line + 1,
                        character=start_char,
                        end_line=end_line + 1,
                        end_character=end_char,
                        severity=_diag.Severity.WARNING,
                        code="BSL238",
                    )
                )
        for line_no, content_base, _content, head, _ended in query_lines:
            if 0 < line_no <= len(lines) and lines[line_no - 1].lstrip().startswith("//"):
                continue
            if "BSL236" in enabled_set:
                source_matches: list[tuple[str, int]] = []
                for match in _QUERY_METADATA_TYPE_REF_RE.finditer(head):
                    source = match.group(1) or match.group(3)
                    if source is None:
                        continue
                    source_start = match.start(1) if match.group(1) else match.start(3)
                    source_matches.append((source, source_start))
                for source, source_start in source_matches:
                    if source.casefold() in temp_table_names:
                        continue
                    missing_name = _missing_metadata_name(source, meta_names)
                    if meta_names and missing_name is not None:
                        col = content_base + source_start
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=col,
                                end_line=line_no,
                                end_character=col + len(missing_name),
                                severity=_diag.Severity.ERROR,
                                code="BSL236",
                            )
                        )
    return diags


def _bsl274_form_xml_has_wrong_data_path(_diag: Any, form_xml: Path) -> bool:
    form_text = _diag._read_text_cached(str(form_xml))
    return any(
        match.group(1).strip().startswith("~")
        for match in _diag._RE_XML_DATAPATH.finditer(form_text)
    )


def _bsl274_form_xmls_without_modules(config_root: str) -> list[Path]:
    root = Path(config_root)
    form_xmls = [
        *root.glob("*/**/Forms/*/Ext/Form.xml"),
        *root.glob("CommonForms/*/Ext/Form.xml"),
    ]
    result: list[Path] = []
    for form_xml in sorted(set(form_xmls)):
        if not (form_xml.parent / "Module.bsl").exists():
            result.append(form_xml)
    return result


def applicable_bsl189_211_213_214_231_232_241_242_246_274_codes(
    path: str,
    content: str,
    enabled: tuple[str, ...],
) -> tuple[str, ...]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    out: list[str] = []
    root = _diag._config_root_for_file(path)
    object_xml = _diag._current_object_xml_path(path)
    low_path = path.replace("\\", "/").lower()

    for code in ("BSL189", "BSL211", "BSL241"):
        if code in enabled_set and object_xml is not None:
            out.append(code)

    if "BSL274" in enabled_set:
        if _diag.path_is_likely_form_module_bsl(path):
            out.append("BSL274")
        elif low_path.endswith("/ext/managedapplicationmodule.bsl") and root is not None:
            out.append("BSL274")
    if "BSL246" in enabled_set and low_path.endswith("/ext/managedapplicationmodule.bsl"):
        if root is not None:
            out.append("BSL246")
    if "BSL232" in enabled_set and low_path.endswith("/ext/sessionmodule.bsl"):
        if root is not None:
            out.append("BSL232")
    if "BSL214" in enabled_set and low_path.endswith("/ext/sessionmodule.bsl"):
        if root is not None:
            out.append("BSL214")
    if root is not None and "/commonmodules/" in low_path:
        if "BSL231" in enabled_set and "(" in content:
            current_common = Path(path).parent.parent.name.casefold()
            privileged_map = _diag._common_module_privileged_map_cached(root)
            if "." in content or privileged_map.get(current_common, {}).get("privileged"):
                out.append("BSL231")
        if "BSL213" in enabled_set and "." in content and "(" in content:
            out.append("BSL213")
        if "BSL242" in enabled_set and low_path.endswith("/ext/module.bsl"):
            out.append("BSL242")
    elif "BSL231" in enabled_set and root is not None and "." in content and "(" in content:
        out.append("BSL231")

    return tuple(code for code in enabled if code in out)


def run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
    path: str,
    lines: list[str],
    procs: list[Any],
    enabled: tuple[str, ...],
    cleaned_lines: list[str] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    root = _diag._config_root_for_file(path)
    line_text = lines[0] if lines else ""
    object_xml = _diag._current_object_xml_path(path)
    clean = cleaned_lines or lines
    low_path = path.replace("\\", "/").lower()
    current_ctx = _diag._current_module_xml_context(path) if object_xml is not None else {}
    object_name = current_ctx.get("object_name", object_xml.stem) if object_xml is not None else ""
    meta_obj: Any | None = None
    if object_xml is not None and ({"BSL189", "BSL241"} & enabled_set):
        meta_obj = _diag._current_metadata_object_for_file_cached(path)
    privileged_map = (
        _diag._common_module_privileged_map_cached(root)
        if root is not None and "BSL231" in enabled_set
        else {}
    )
    common_module_index = (
        _diag._common_module_index_cached(root)
        if root is not None and ({"BSL213", "BSL214", "BSL242"} & enabled_set)
        else {}
    )

    bsl189_storage_member_kinds = {"attribute", "tabular_section"}

    if object_xml is not None:
        if "BSL189" in enabled_set:
            if object_name.casefold() in _BSL189_FORBIDDEN_NAMES:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=_metadata_owner_range_end(line_text),
                        severity=_diag.Severity.ERROR,
                        code="BSL189",
                    )
                )
            if meta_obj is not None:
                for member in meta_obj.members:
                    if (
                        member.kind not in bsl189_storage_member_kinds
                        or member.parent_kind == "Enum"
                    ):
                        continue
                    check_name = member.name.split(".")[-1]
                    if check_name.casefold() in _BSL189_FORBIDDEN_NAMES:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=_metadata_owner_range_end(line_text),
                                severity=_diag.Severity.ERROR,
                                code="BSL189",
                            )
                        )
                        break
        if "BSL211" in enabled_set and len(object_name) > 80:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=_metadata_owner_range_end(line_text),
                    severity=_diag.Severity.WARNING,
                    code="BSL211",
                )
            )
        if "BSL241" in enabled_set and meta_obj is not None:
            obj_cf = meta_obj.name.casefold()
            for member in meta_obj.members:
                if member.kind not in {"attribute", "tabular_section", "ts_attribute"}:
                    continue
                raw_name = member.name.split(".")
                if len(raw_name) == 1 and raw_name[0].casefold() == obj_cf:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=_diag.Severity.ERROR,
                            code="BSL241",
                        )
                    )
                    break
                if len(raw_name) == 2 and raw_name[0].casefold() == raw_name[1].casefold():
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=_diag.Severity.ERROR,
                            code="BSL241",
                        )
                    )
                    break

    if "BSL274" in enabled_set:
        has_wrong_data_path = False
        if _diag.path_is_likely_form_module_bsl(path):
            form_xml = _diag._current_form_xml_path(path)
            has_wrong_data_path = form_xml is not None and _bsl274_form_xml_has_wrong_data_path(
                _diag, form_xml
            )
        elif low_path.endswith("/ext/managedapplicationmodule.bsl") and root is not None:
            has_wrong_data_path = any(
                _bsl274_form_xml_has_wrong_data_path(_diag, form_xml)
                for form_xml in _bsl274_form_xmls_without_modules(root)
            )
        if has_wrong_data_path:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=max(len(line_text.rstrip()), 1),
                    severity=_diag.Severity.ERROR,
                    code="BSL274",
                )
            )

    if (
        "BSL246" in enabled_set
        and low_path.endswith("/ext/managedapplicationmodule.bsl")
        and root is not None
    ):
        for _role_name in _diag._roles_with_new_objects_cached(root):
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=max(len(line_text.rstrip()), 1),
                    severity=_diag.Severity.ERROR,
                    code="BSL246",
                )
            )

    if "BSL232" in enabled_set and low_path.endswith("/ext/sessionmodule.bsl") and root is not None:
        for _protected_ref in _diag._config_protected_module_refs_cached(root):
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=max(len(line_text.rstrip()), 1),
                    severity=_diag.Severity.WARNING,
                    code="BSL232",
                )
            )
    if "BSL214" in enabled_set and low_path.endswith("/ext/sessionmodule.bsl") and root is not None:
        proc_names_by_module: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        for _subscription_name, handler in _diag._event_subscription_handlers_cached(root):
            invalid = False
            split = _diag._split_common_module_method_path(handler)
            if split is None:
                invalid = True
            else:
                module_name, meth = split
                module_cf = module_name.casefold()
                module_info = common_module_index.get(module_cf)
                if not module_info:
                    invalid = True
                else:
                    if not module_info.get("server"):
                        invalid = True
                    proc_sets = proc_names_by_module.get(module_cf)
                    if proc_sets is None:
                        all_names = _diag._common_module_proc_names_for_module_cached(
                            root, module_cf
                        )
                        exported_names = _diag._common_module_exported_proc_names_for_module_cached(
                            root, module_cf
                        )
                        proc_sets = (all_names, exported_names)
                        proc_names_by_module[module_cf] = proc_sets
                    all_names, exported_names = proc_sets
                    meth_cf = meth.casefold()
                    if meth_cf not in all_names or meth_cf not in exported_names:
                        invalid = True
            if invalid:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=_metadata_owner_range_end(line_text),
                        severity=_diag.Severity.ERROR,
                        code="BSL214",
                    )
                )
    if "BSL231" in enabled_set and root is not None:
        current_common = ""
        if "/commonmodules/" in low_path:
            current_common = Path(path).parent.parent.name.casefold()
        current_privileged = bool(
            current_common and privileged_map.get(current_common, {}).get("privileged")
        )
        exported_names_by_module: dict[str, frozenset[str]] = {}

        def exported_names(module_cf: str) -> frozenset[str]:
            cached = exported_names_by_module.get(module_cf)
            if cached is None:
                cached = _diag._common_module_exported_proc_names_for_module_cached(root, module_cf)
                exported_names_by_module[module_cf] = cached
            return cached

        for idx, _raw_line in enumerate(lines):
            line = clean[idx]
            for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                mod_cf = match.group("mod").casefold()
                meth_cf = match.group("meth").casefold()
                info = privileged_map.get(mod_cf)
                if info and info.get("privileged") and meth_cf in exported_names(mod_cf):
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("meth"),
                            end_line=idx + 1,
                            end_character=match.end("meth"),
                            severity=_diag.Severity.WARNING,
                            code="BSL231",
                        )
                    )
            if current_privileged and current_common:
                if re.match(r"\s*(?:Процедура|Функция|Procedure|Function)\b", line, re.IGNORECASE):
                    continue
                for match in re.finditer(r"(?<!\.)\b(?P<meth>\w+)\s*\(", line):
                    meth_cf = match.group("meth").casefold()
                    if meth_cf not in exported_names(current_common):
                        continue
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("meth"),
                            end_line=idx + 1,
                            end_character=match.end("meth"),
                            severity=_diag.Severity.WARNING,
                            code="BSL231",
                        )
                    )

    if (
        ({"BSL213", "BSL214", "BSL242"} & enabled_set)
        and root is not None
        and "/commonmodules/" in low_path
    ):
        module_name = Path(path).parent.parent.name
        proc_names = {proc.name.casefold(): proc for proc in procs}
        if "BSL213" in enabled_set:
            proc_names_by_module: dict[str, frozenset[str]] = {}
            for idx, _raw_line in enumerate(lines):
                line = clean[idx]
                for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                    mod_cf = match.group("mod").casefold()
                    if mod_cf not in common_module_index:
                        continue
                    info = proc_names_by_module.get(mod_cf)
                    if info is None:
                        if mod_cf == module_name.casefold():
                            info = _diag._common_module_proc_names_for_module_cached(root, mod_cf)
                        else:
                            info = _diag._common_module_exported_proc_names_for_module_cached(
                                root, mod_cf
                            )
                        proc_names_by_module[mod_cf] = info
                    if match.group("meth").casefold() not in info:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("mod"),
                                end_line=idx + 1,
                                end_character=match.end("meth"),
                                severity=_diag.Severity.ERROR,
                                code="BSL213",
                            )
                        )
        if "BSL214" in enabled_set:
            for handler in _diag._event_subscription_handlers_by_module_cached(root).get(
                module_name.casefold(), ()
            ):
                meth = handler.split(".", 1)[1]
                if meth.casefold() not in proc_names:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=_diag.Severity.ERROR,
                            code="BSL214",
                        )
                    )
        if "BSL242" in enabled_set and low_path.endswith("/ext/module.bsl"):
            handlers_seen: dict[str, str] = {}
            module_info = common_module_index.get(module_name.casefold()) or {}
            module_handlers = _diag._scheduled_job_handlers_by_module_cached(root).get(
                module_name.casefold(), ()
            )
            if module_handlers and module_info and not module_info.get("server"):
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=_diag.Severity.ERROR,
                        code="BSL242",
                    )
                )
            for handler, job_name, predefined in module_handlers:
                meth = handler.split(".")[-1]
                proc = proc_names.get(meth.casefold())
                if proc is None:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=_diag.Severity.ERROR,
                            code="BSL242",
                        )
                    )
                    continue
                if not proc.is_export:
                    start_char, end_char = _diag._proc_name_span(lines, proc)
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=_diag.Severity.ERROR,
                            code="BSL242",
                        )
                    )
                if predefined and (proc.optional_count > 0 or proc.params):
                    start_char, end_char = _diag._proc_name_span(lines, proc)
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=_diag.Severity.ERROR,
                            code="BSL242",
                        )
                    )
                if _bsl242_proc_body_is_empty(lines, proc):
                    start_char, end_char = _diag._proc_name_span(lines, proc)
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=_diag.Severity.ERROR,
                            code="BSL242",
                        )
                    )
                if handler in handlers_seen and handlers_seen[handler] != job_name:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=_diag.Severity.ERROR,
                            code="BSL242",
                        )
                    )
                handlers_seen[handler] = job_name
    return diags


def run_bsl244_253_261_runtime_pool(
    path: str,
    lines: list[str],
    procs: list[Any],
    enabled: tuple[str, ...],
    cleaned_lines: list[str] | None = None,
    *,
    tree: Any | None = None,
    snapshot: Any | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    clean = cleaned_lines or lines
    cst_nodes_by_type: dict[str, list[Any]] | None = None
    if tree is not None and snapshot is not None and getattr(snapshot, "tree", None) is tree:
        wanted_cst_nodes: set[str] = set()
        if "BSL253" in enabled_set:
            wanted_cst_nodes.update({"new_expression", "assignment_statement"})
        if "BSL261" in enabled_set:
            wanted_cst_nodes.add("method_call")
        if wanted_cst_nodes:
            cst_nodes_by_type = snapshot.ts_nodes_for_types(wanted_cst_nodes, walker=_diag._ts_walk)

    if "BSL244" in enabled_set and _diag.path_is_likely_form_module_bsl(path):
        server_proc_names = {
            proc.name.casefold()
            for proc in procs
            if _bsl244_proc_has_context_server_directive(lines, proc)
        }
        if server_proc_names:
            for proc in procs:
                if not _bsl244_forbidden_form_event_name(proc.name):
                    continue
                end_idx = min(proc.end_idx, len(clean) - 1)
                for idx in range(proc.start_idx, end_idx + 1):
                    line = clean[idx]
                    line_cf = line.lstrip().casefold()
                    if line_cf.startswith(("процедура ", "функция ", "procedure ", "function ")):
                        continue
                    for match in re.finditer(r"\b(?P<call>\w+)\s*\(", line):
                        if match.start("call") > 0 and line[match.start("call") - 1] == ".":
                            continue
                        if match.group("call").casefold() in server_proc_names:
                            open_paren_idx = match.end() - 1
                            diags.append(
                                _diag.Diagnostic(
                                    file=path,
                                    line=idx + 1,
                                    character=match.start("call"),
                                    end_line=idx + 1,
                                    end_character=_bsl244_call_end_character(line, open_paren_idx),
                                    severity=_diag.Severity.ERROR,
                                    code="BSL244",
                                )
                            )

    if "BSL253" in enabled_set:
        cst_diags = _bsl253_timeout_diagnostics_from_cst(
            path,
            lines,
            procs,
            tree,
            snapshot,
            cst_nodes_by_type,
        )
        if cst_diags is not None:
            diags.extend(cst_diags)
        else:
            for idx, line in enumerate(clean):
                match = re.search(
                    r"\b(?:Новый|New)\s+(?P<type>\w+)\s*\((?P<args>.*)\)",
                    line,
                    re.IGNORECASE,
                )
                if match is None:
                    continue
                type_cf = match.group("type").casefold()
                need_idx = _BSL253_TIMEOUT_ARG_INDEXES.get(type_cf)
                if need_idx is None:
                    continue
                args = _diag._split_top_level_args(match.group("args"))
                if len(args) > need_idx and args[need_idx].strip():
                    continue
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=match.start("type"),
                        end_line=idx + 1,
                        end_character=match.end("args") + 1,
                        severity=_diag.Severity.ERROR,
                        code="BSL253",
                    )
                )
    if "BSL261" in enabled_set:
        cst_diags = _bsl261_diagnostics_from_cst(path, lines, tree, snapshot, cst_nodes_by_type)
        if cst_diags is not None:
            diags.extend(cst_diags)
        else:
            for idx, line in enumerate(clean):
                if not re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE):
                    continue
                if re.search(
                    r"\b(?:Если|If|Не|Not)\b.*\b(?:БезопасныйРежим|SafeMode)\s*\(",
                    line,
                    re.IGNORECASE,
                ) or re.search(r"\b(?:И|And|Или|Or)\b", line, re.IGNORECASE):
                    match = re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE)
                    if match is not None and not re.search(r"(?:<>|<=|>=|=)", line):
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start(),
                                end_line=idx + 1,
                                end_character=match.end(),
                                severity=_diag.Severity.ERROR,
                                code="BSL261",
                            )
                        )
    return diags
