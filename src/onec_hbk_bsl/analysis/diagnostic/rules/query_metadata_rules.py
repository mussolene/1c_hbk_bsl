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


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _missing_metadata_name(
    source: str,
    meta_names: set[str],
) -> str | None:
    parts = source.split(".")
    if not parts:
        return None
    if len(parts) == 1:
        return None
    root = parts[0].casefold()
    if root not in QUERY_METADATA_ROOTS:
        return None
    object_name = parts[1]
    if object_name.casefold() in meta_names:
        return None
    return ".".join(parts[:2])


def _bsl238_redundant_ref_nodes(root: Any) -> list[Any]:
    simple_table_aliases: set[str] = set()
    tabular_section_aliases: set[str] = set()
    tabular_section_roots = {
        "бизнеспроцесс",
        "businessprocess",
        "документ",
        "document",
        "справочник",
        "catalog",
    }
    for source_use in query_source_uses(root):
        source_parts = source_use.source.split(".")
        parent = getattr(source_use.node, "parent", None)
        alias = source_alias_name(parent) if parent is not None else None
        if not alias:
            continue
        alias_cf = alias.casefold()
        if len(source_parts) == 1 and source_use.source.casefold() == alias_cf:
            simple_table_aliases.add(alias_cf)
        elif len(source_parts) >= 3 and source_parts[0].casefold() in tabular_section_roots:
            tabular_section_aliases.add(alias_cf)

    out: list[Any] = []
    for dotted in iter_nodes(root, "dotted_identifier"):
        if ancestor(dotted, "from_clause") is not None:
            continue
        parts = dotted_identifier_parts(dotted)
        if len(parts) < 3 or not any(
            part.casefold() in {"ссылка", "reference", "ref"} for part in parts[1:]
        ):
            continue
        if parts[0].casefold() in (simple_table_aliases | tabular_section_aliases) and parts[
            1
        ].casefold() in {"ссылка", "reference", "ref"}:
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
    meta_names: set[str] = set()
    if "BSL236" in enabled_set and root is not None:
        meta_names = set(_diag._workspace_metadata_name_index_cached(root))

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

    if "BSL274" in enabled_set and _diag.path_is_likely_form_module_bsl(path):
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
    if "BSL231" in enabled_set and root is not None and "." in content and "(" in content:
        out.append("BSL231")
    if root is not None and "/commonmodules/" in low_path:
        if "BSL213" in enabled_set and "." in content and "(" in content:
            out.append("BSL213")
        if "BSL242" in enabled_set and low_path.endswith("/ext/module.bsl"):
            out.append("BSL242")

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
    if object_xml is not None and root is not None and ({"BSL189", "BSL241"} & enabled_set):
        crawl = _diag._crawl_config_cached(root)
        meta_obj = crawl["by_name"].get(object_name.casefold())
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

    if "BSL274" in enabled_set and _diag.path_is_likely_form_module_bsl(path):
        form_xml = _diag._current_form_xml_path(path)
        if form_xml is not None:
            form_text = _diag._read_text_cached(str(form_xml))
            for match in _diag._RE_XML_DATAPATH.finditer(form_text):
                if match.group(1).startswith("~"):
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
                    break

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
        if _diag._config_has_protected_modules_cached(root):
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
                        all_names = _diag._common_module_proc_names_for_module_cached(root, module_cf)
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
        for idx, _raw_line in enumerate(lines):
            line = clean[idx]
            for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                mod_cf = match.group("mod").casefold()
                if mod_cf == current_common:
                    continue
                info = privileged_map.get(mod_cf)
                if info and info.get("privileged") and not current_privileged:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("mod"),
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
            if module_info and not module_info.get("server"):
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
            for handler, job_name, predefined in _diag._scheduled_job_handlers_by_module_cached(
                root
            ).get(module_name.casefold(), ()):
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
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    clean = cleaned_lines or lines
    server_proc_names = {
        proc.name.casefold()
        for proc in procs
        if _diag._procedure_compiler_execution_context(lines, proc) == "server"
    }

    if "BSL244" in enabled_set and _diag.path_is_likely_form_module_bsl(path):
        for idx, line in enumerate(clean):
            proc = _diag._proc_containing_line(procs, idx)
            if proc is None:
                continue
            name_cf = proc.name.casefold()
            is_form_event = name_cf.startswith("при") or name_cf.startswith("on")
            if not is_form_event:
                continue
            if _diag._procedure_compiler_execution_context(lines, proc) == "server":
                continue
            for match in re.finditer(r"\b(?P<call>\w+)\s*\(", line):
                if match.group("call").casefold() in server_proc_names:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("call"),
                            end_line=idx + 1,
                            end_character=match.end("call"),
                            severity=_diag.Severity.ERROR,
                            code="BSL244",
                        )
                    )

    timeout_types = {
        "httpсоединение": 4,
        "httpconnection": 4,
        "ftpсоединение": 5,
        "ftpconnection": 5,
        "wsопределения": 3,
        "wsdefinitions": 3,
        "wsпрокси": 4,
        "wsproxy": 4,
        "интернетпочтовыйпрофиль": 5,
        "internetmailprofile": 5,
    }
    if "BSL253" in enabled_set:
        for idx, line in enumerate(clean):
            match = re.search(
                r"\b(?:Новый|New)\s+(?P<type>\w+)\s*\((?P<args>.*)\)", line, re.IGNORECASE
            )
            if match is None:
                continue
            type_cf = match.group("type").casefold()
            need_idx = timeout_types.get(type_cf)
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
        for idx, line in enumerate(clean):
            if not re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE):
                continue
            if re.search(
                r"\b(?:Если|If)\b.*\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE
            ) or re.search(r"\b(?:И|And|Или|Or)\b", line, re.IGNORECASE):
                match = re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE)
                if match is not None:
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
