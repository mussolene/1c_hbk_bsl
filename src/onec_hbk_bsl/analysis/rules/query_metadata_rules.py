from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl174_187_236_238_query_metadata_pool(
    path: str,
    lines: list[str],
    enabled: tuple[str, ...],
    query_blocks: list[Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    root = _diag._config_root_for_file(path)
    meta_names: set[str] = set()
    if root is not None:
        crawl = _diag._crawl_config_cached(root)
        meta_names = set(crawl["by_name"].keys())

    object_xml = _diag._current_object_xml_path(path)
    if "BSL174" in enabled_set and object_xml is not None:
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
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=_diag.Severity.WARNING,
                        code="BSL174",
                        message=(
                            f"Измерение {match.group(1)} должно запрещать незаполненные значения"
                        ),
                    )
                )

    if query_blocks is None:
        blocks = (
            list(_diag._iter_query_text_content_lines(start_idx, block_lines))
            for start_idx, block_lines in _diag._iter_query_text_blocks(lines)
        )
    else:
        blocks = (_diag._query_block_content_line_tuples(block) for block in query_blocks)

    for query_lines in blocks:
        if not query_lines:
            continue
        query_text = "\n".join(head for _ln, _base, _content, head, _end in query_lines)
        left_join_aliases: set[str] = set()
        for line_no, content_base, _content, head, _ended in query_lines:
            if "BSL236" in enabled_set:
                for match in re.finditer(
                    r"\b(?:ИЗ|FROM|СОЕДИНЕНИЕ|JOIN)\s+([A-Za-zА-Яа-яЁё_][\w]*)",
                    head,
                    re.IGNORECASE,
                ):
                    name = match.group(1)
                    if name.casefold() in {
                        "выбрать",
                        "select",
                        "как",
                        "as",
                        "левое",
                        "правое",
                        "полное",
                        "внутреннее",
                    }:
                        continue
                    if meta_names and name.casefold() not in meta_names:
                        col = content_base + match.start(1)
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=col,
                                end_line=line_no,
                                end_character=col + len(name),
                                severity=_diag.Severity.ERROR,
                                code="BSL236",
                                message=f"Запрос обращается к несуществующим метаданным {name}",
                            )
                        )
            if "BSL238" in enabled_set:
                for match in re.finditer(r"\.(?:Ссылка|Ref)\.", head, re.IGNORECASE):
                    col = content_base + match.start()
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=line_no,
                            character=col,
                            end_line=line_no,
                            end_character=col + len(match.group(0)),
                            severity=_diag.Severity.INFORMATION,
                            code="BSL238",
                            message="Избыточное использование .Ссылка в запросе",
                        )
                    )
            if "BSL187" in enabled_set:
                for join_match in re.finditer(
                    r"\b(?:ЛЕВОЕ\s+СОЕДИНЕНИЕ|LEFT\s+JOIN)\b.*?\b(?:КАК|AS)\s+([A-Za-zА-Яа-яЁё_]\w*)",
                    head,
                    re.IGNORECASE,
                ):
                    left_join_aliases.add(join_match.group(1).casefold())
        if "BSL187" in enabled_set and left_join_aliases:
            has_isnull = re.search(r"\b(?:ЕСТЬNULL|ISNULL)\s*\(", query_text, re.IGNORECASE)
            if not has_isnull:
                for line_no, content_base, _content, head, _ended in query_lines:
                    for alias in left_join_aliases:
                        match = re.search(rf"\b{re.escape(alias)}\.\w+", head, re.IGNORECASE)
                        if match is None:
                            continue
                        col = content_base + match.start()
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=col,
                                end_line=line_no,
                                end_character=col + len(match.group(0)),
                                severity=_diag.Severity.ERROR,
                                code="BSL187",
                                message="Поля из внешнего соединения должны использоваться с ЕСТЬNULL/ISNULL",
                            )
                        )
                        break
    return diags


def run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
    path: str,
    lines: list[str],
    procs: list[Any],
    enabled: tuple[str, ...],
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    root = _diag._config_root_for_file(path)
    line_text = lines[0] if lines else ""
    object_xml = _diag._current_object_xml_path(path)
    crawl = _diag._crawl_config_cached(root) if root is not None else {"objects": [], "by_name": {}}
    module_map = _diag._common_module_file_map(root) if root is not None else {}

    forbidden_names = {
        "catalog",
        "catalogs",
        "document",
        "documents",
        "справочник",
        "справочники",
        "документ",
        "документы",
        "enum",
        "enums",
        "перечисление",
        "перечисления",
        "tasks",
        "задачи",
    }

    if object_xml is not None:
        ctx = _diag._current_module_xml_context(path)
        object_name = ctx.get("object_name", object_xml.stem)
        meta_obj = crawl["by_name"].get(object_name.casefold())
        if "BSL189" in enabled_set:
            if object_name.casefold() in forbidden_names:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=_diag.Severity.ERROR,
                        code="BSL189",
                        message=f"Запрещенное имя объекта метаданных {object_name}",
                    )
                )
            if meta_obj is not None:
                for member in meta_obj.members:
                    check_name = member.name.split(".")[-1]
                    if check_name.casefold() in forbidden_names:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=max(len(line_text.rstrip()), 1),
                                severity=_diag.Severity.ERROR,
                                code="BSL189",
                                message=f"Запрещенное имя реквизита или части {check_name}",
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
                    end_character=max(len(line_text.rstrip()), 1),
                    severity=_diag.Severity.WARNING,
                    code="BSL211",
                    message="Имя объекта метаданных превышает допустимую длину 80",
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
                            message=f"Имя дочернего объекта совпадает с именем {meta_obj.name}",
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
                            message=f"Имя реквизита совпадает с именем табличной части {raw_name[0]}",
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
                            message=f"Путь к данным элемента формы некорректен: {match.group(1)}",
                        )
                    )
                    break

    if (
        "BSL246" in enabled_set
        and path.replace("\\", "/").lower().endswith("/ext/managedapplicationmodule.bsl")
        and root is not None
    ):
        roles_dir = Path(root) / "Roles"
        for xml_file in roles_dir.glob("*.xml"):
            role_name = xml_file.stem
            if role_name in {"FullAccess", "ПолныеПрава"}:
                continue
            text = _diag._read_text_cached(str(xml_file))
            match = _diag._RE_XML_SET_FOR_NEW_OBJECTS.search(text)
            if match and match.group(1).lower() == "true":
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=_diag.Severity.ERROR,
                        code="BSL246",
                        message=f"Роль {role_name} задает права для новых объектов",
                    )
                )

    if (
        "BSL232" in enabled_set
        and path.replace("\\", "/").lower().endswith("/ext/sessionmodule.bsl")
        and root is not None
    ):
        cfg_root = Path(root)
        protected_found = False
        for xml_file in cfg_root.rglob("*.xml"):
            if xml_file.name in {"Configuration.xml", "ConfigDumpInfo.xml"}:
                continue
            if _diag._RE_XML_PROTECTED.search(_diag._read_text_cached(str(xml_file))):
                protected_found = True
                break
        if protected_found:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=max(len(line_text.rstrip()), 1),
                    severity=_diag.Severity.WARNING,
                    code="BSL232",
                    message="В конфигурации обнаружены защищенные модули",
                )
            )

    if "BSL231" in enabled_set and root is not None:
        low = path.replace("\\", "/").lower()
        current_common = ""
        if "/commonmodules/" in low:
            current_common = Path(path).parent.parent.name.casefold()
        current_privileged = bool(
            current_common and module_map.get(current_common, {}).get("privileged")
        )
        for idx, raw_line in enumerate(lines):
            line = _diag._strip_inline_comment_preserve_strings(raw_line)
            for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                mod_cf = match.group("mod").casefold()
                if mod_cf == current_common:
                    continue
                info = module_map.get(mod_cf)
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
                            message=f"Вызов метода привилегированного модуля {info['name']}",
                        )
                    )

    if (
        ({"BSL213", "BSL214", "BSL242"} & enabled_set)
        and root is not None
        and "/commonmodules/" in path.replace("\\", "/").lower()
    ):
        module_name = Path(path).parent.parent.name
        proc_names = {proc.name.casefold(): proc for proc in procs}
        root_path = Path(root)
        if "BSL213" in enabled_set:
            for idx, raw_line in enumerate(lines):
                line = _diag._strip_inline_comment_preserve_strings(raw_line)
                for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                    mod_cf = match.group("mod").casefold()
                    info = module_map.get(mod_cf)
                    if info and match.group("meth").casefold() not in info.get("proc_names", set()):
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("mod"),
                                end_line=idx + 1,
                                end_character=match.end("meth"),
                                severity=_diag.Severity.ERROR,
                                code="BSL213",
                                message=(
                                    f"Метод {match.group('meth')} отсутствует в общем модуле {info['name']}"
                                ),
                            )
                        )
        if "BSL214" in enabled_set:
            for xml_file in (root_path / "EventSubscriptions").glob("*.xml"):
                text = _diag._read_text_cached(str(xml_file))
                for match in _diag._RE_XML_EVENT_HANDLER.finditer(text):
                    handler = (match.group(1) or match.group(2) or "").strip()
                    if not handler.startswith(f"{module_name}."):
                        continue
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
                                message=f"Обработчик подписки на событие {handler} не существует",
                            )
                        )
        if "BSL242" in enabled_set:
            handlers_seen: dict[str, str] = {}
            for xml_file in (root_path / "ScheduledJobs").glob("*.xml"):
                text = _diag._read_text_cached(str(xml_file))
                for match in _diag._RE_XML_METHOD_NAME.finditer(text):
                    handler = match.group(1).strip()
                    if not handler.startswith(f"CommonModule.{module_name}."):
                        continue
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
                                message=f"Обработчик регламентного задания {handler} не найден",
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
                                message=f"Обработчик регламентного задания {handler} должен быть экспортным",
                            )
                        )
                    if proc.optional_count > 0 or proc.params:
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
                                message=f"Обработчик регламентного задания {handler} не должен принимать параметры",
                            )
                        )
                    if handler in handlers_seen and handlers_seen[handler] != xml_file.stem:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=max(len(line_text.rstrip()), 1),
                                severity=_diag.Severity.ERROR,
                                code="BSL242",
                                message=f"Один и тот же обработчик {handler} используется несколькими заданиями",
                            )
                        )
                    handlers_seen[handler] = xml_file.stem
    return diags


def run_bsl244_253_261_runtime_pool(
    path: str,
    lines: list[str],
    procs: list[Any],
    enabled: tuple[str, ...],
) -> list[Any]:
    _diag = _diag_module()
    enabled_set = set(enabled)
    diags: list[Any] = []
    server_proc_names = {
        proc.name.casefold()
        for proc in procs
        if _diag._procedure_compiler_execution_context(lines, proc) == "server"
    }

    if "BSL244" in enabled_set and _diag.path_is_likely_form_module_bsl(path):
        for idx, raw_line in enumerate(lines):
            line = _diag._strip_inline_comment_preserve_strings(raw_line)
            proc = _diag._proc_containing_line(procs, idx)
            if proc is None:
                continue
            name_cf = proc.name.casefold()
            is_form_event = name_cf.startswith("при") or name_cf.startswith("on")
            if not is_form_event:
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
                            message="Серверный вызов в обработчике события формы",
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
        for idx, raw_line in enumerate(lines):
            line = _diag._strip_inline_comment_preserve_strings(raw_line)
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
                    message="Внешний ресурс создается без явного таймаута",
                )
            )

    if "BSL261" in enabled_set:
        for idx, raw_line in enumerate(lines):
            line = _diag._strip_inline_comment_preserve_strings(raw_line)
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
                            message="Небезопасное использование метода безопасного режима",
                        )
                    )
    return diags
