from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_root_for_file,
    current_form_xml_path,
    unsafe_find_by_code_metadata_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    is_split_module_fragment,
)
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character, utf16_len
from onec_hbk_bsl.analysis.symbols import _extract_doc_comment

_BSL176_PLATFORM_DEPRECATED_GLOBAL_METHODS: dict[str, tuple[str, tuple[str, ...]]] = {
    alias.casefold(): (name, replacements)
    for name, aliases, replacements in (
        (
            "УстановитьКраткийЗаголовокПриложения",
            ("SetShortApplicationCaption",),
            ("КлиентскоеПриложение.УстановитьКраткийЗаголовок",),
        ),
        (
            "ПолучитьКраткийЗаголовокПриложения",
            ("GetShortApplicationCaption",),
            ("КлиентскоеПриложение.ПолучитьКраткийЗаголовок",),
        ),
        (
            "УстановитьЗаголовокКлиентскогоПриложения",
            ("SetClientApplicationCaption",),
            ("КлиентскоеПриложение.УстановитьЗаголовок",),
        ),
        (
            "ПолучитьЗаголовокКлиентскогоПриложения",
            ("GetClientApplicationCaption",),
            ("КлиентскоеПриложение.ПолучитьЗаголовок",),
        ),
        (
            "ТекущийВариантОсновногоШрифтаКлиентскогоПриложения",
            ("ClientApplicationBaseFontCurrentVariant",),
            ("КлиентскоеПриложение.ТекущийВариантОсновногоШрифта",),
        ),
        (
            "ТекущийВариантИнтерфейсаКлиентскогоПриложения",
            ("ClientApplicationInterfaceCurrentVariant",),
            ("КлиентскоеПриложение.ТекущийВариантИнтерфейса",),
        ),
        (
            "КраткоеПредставлениеОшибки",
            ("BriefErrorDescription",),
            ("ОбработкаОшибок.КраткоеПредставлениеОшибки",),
        ),
        (
            "ПодробноеПредставлениеОшибки",
            ("DetailErrorDescription",),
            ("ОбработкаОшибок.ПодробноеПредставлениеОшибки",),
        ),
        (
            "ПоказатьИнформациюОбОшибке",
            ("ShowErrorInfo",),
            ("ОбработкаОшибок.ПоказатьИнформациюОбОшибке",),
        ),
        ("НайтиНедопустимыеСимволыXML", ("FindDisallowedXMLCharacters",), ()),
        ("УстановитьВнешнююКомпоненту", ("InstallAddIn",), ("НачатьУстановкуВнешнейКомпоненты",)),
        ("ОчиститьЖурналРегистрации", ("ClearEventLog",), ()),
        (
            "ПодключитьРасширениеРаботыСКриптографией",
            ("AttachCryptoExtension",),
            ("НачатьПодключениеРасширенияРаботыСКриптографией",),
        ),
        (
            "УстановитьРасширениеРаботыСКриптографией",
            ("InstallCryptoExtension",),
            ("НачатьУстановкуРасширенияРаботыСКриптографией",),
        ),
        ("ПользователиWindows", ("WindowsUsers",), ("ПользователиОС",)),
        (
            "ПолучитьСоответствиеОбъектаИРеквизитаФормы",
            ("GetObjectAndFormAttributeConformity",),
            ("ПолучитьСоответствиеОбъектаИФормы",),
        ),
        (
            "УстановитьСоответствиеОбъектаИРеквизитаФормы",
            ("SetObjectAndFormAttributeConformity",),
            ("УстановитьСоответствиеОбъектаИФормы",),
        ),
        (
            "ЗапроситьРазрешениеПользователя",
            ("RequestUserPermission",),
            ("НачатьЗапросРазрешенияПользователя",),
        ),
        ("НачатьПолучениеФайлов", ("BeginGettingFiles",), ("НачатьПолучениеФайловССервера",)),
        ("НачатьПомещениеФайла", ("BeginPutFile",), ("НачатьПомещениеФайлаНаСервер",)),
        (
            "НачатьПомещениеФайлов",
            ("BeginPuttingFiles",),
            ("НачатьПомещениеФайлаНаСервер", "НачатьПомещениеФайловНаСервер"),
        ),
        (
            "ПодключитьРасширениеРаботыСФайлами",
            ("AttachFileSystemExtension",),
            ("НачатьПодключениеРасширенияРаботыСФайлами",),
        ),
        ("ПолучитьФайл", ("GetFile",), ("НачатьПолучениеФайлаССервера",)),
        ("ПолучитьФайлы", ("GetFiles",), ("НачатьПолучениеФайловССервера",)),
        ("ПоместитьФайл", ("PutFile",), ("НачатьПомещениеФайлаНаСервер",)),
        ("ПоместитьФайлы", ("PutFiles",), ("НачатьПомещениеФайловНаСервер",)),
        (
            "УстановитьРасширениеРаботыСФайлами",
            ("InstallFileSystemExtension",),
            ("НачатьУстановкуРасширенияРаботыСФайлами",),
        ),
        ("ВыполнитьОбработкуЗаданий", ("ProcessJobs",), ()),
    )
    for alias in (name, *aliases)
}


def _bsl_string_spans_before_comment(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    idx = 0
    limit = len(line)
    while idx < limit:
        if line.startswith("//", idx):
            break
        if line[idx] != '"':
            idx += 1
            continue
        start = idx
        idx += 1
        while idx < limit:
            if line[idx] != '"':
                idx += 1
                continue
            if idx + 1 < limit and line[idx + 1] == '"':
                idx += 2
                continue
            idx += 1
            spans.append((start, idx))
            break
    return spans


def _bsl171_adjacent_literal_span(line: str) -> tuple[int, int] | None:
    spans = _bsl_string_spans_before_comment(line)
    for left, right in zip(spans, spans[1:], strict=False):
        if line[left[1] : right[0]].strip() == "":
            return (left[0], right[1])
    return None


def _bsl171_multiline_literal_span(
    prev_line: str,
    cur_line: str,
) -> tuple[int, int] | None:
    prev_spans = _bsl_string_spans_before_comment(prev_line)
    cur_spans = _bsl_string_spans_before_comment(cur_line)
    if not prev_spans or not cur_spans:
        return None
    prev_start, prev_end = prev_spans[-1]
    cur_start, cur_end = cur_spans[0]
    if prev_line[prev_end:].strip() != "":
        return None
    if cur_line[:cur_start].strip() != "":
        return None
    return (prev_start, cur_end)


_BSL181_COLLECTION_INSERTION_RE = re.compile(
    r"(?<!\.)\b(?P<target>\w+)\.(?P<method>Вставить|Insert|Добавить|Add)\s*\(",
    re.IGNORECASE,
)
_BSL181_TARGET_ASSIGNMENT_RE = re.compile(r"^\s*(?P<target>\w+)\s*=")


def _bsl181_first_argument(line: str, open_paren_idx: int) -> tuple[str, int] | None:
    idx = open_paren_idx + 1
    start = idx
    depth = 0
    in_string = False
    while idx < len(line):
        char = line[idx]
        if in_string:
            if char == '"':
                if idx + 1 < len(line) and line[idx + 1] == '"':
                    idx += 2
                    continue
                in_string = False
            idx += 1
            continue
        if char == '"':
            in_string = True
            idx += 1
            continue
        if char == "(":
            depth += 1
            idx += 1
            continue
        if char == ")":
            if depth == 0:
                arg = line[start:idx].strip()
                return (arg, idx + 1) if arg else None
            depth -= 1
            idx += 1
            continue
        if char == "," and depth == 0:
            arg = line[start:idx].strip()
            call_end = _bsl181_call_end(line, idx + 1)
            return (arg, call_end) if arg else None
        idx += 1
    arg = line[start:].strip()
    return (arg, len(line)) if arg else None


def _bsl181_call_end(line: str, start_idx: int) -> int:
    idx = start_idx
    depth = 0
    in_string = False
    while idx < len(line):
        char = line[idx]
        if in_string:
            if char == '"':
                if idx + 1 < len(line) and line[idx + 1] == '"':
                    idx += 2
                    continue
                in_string = False
            idx += 1
            continue
        if char == '"':
            in_string = True
            idx += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return idx + 1
            depth -= 1
        idx += 1
    return len(line)


def _bsl181_normalize_argument(arg: str) -> str:
    return re.sub(r"\s+", "", arg).casefold()


def _bsl181_insert_argument_supported(arg: str) -> bool:
    return (
        '"' in arg or re.search(r"\b(?:КодСимвола|CharCode)\s*\(", arg, re.IGNORECASE) is not None
    )


def _bsl181_add_argument_supported(arg: str) -> bool:
    return (
        _bsl181_insert_argument_supported(arg)
        or re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", arg.strip()) is not None
    )


def _path_is_unmanaged_form_module(path: str) -> bool:
    module_path = Path(path)
    xml_path = current_form_xml_path(path)
    if xml_path is None:
        candidates = [
            module_path.parent / "Form.xml",
            module_path.parent / "form.xml",
            module_path.parent.parent / "Form.xml",
            module_path.parent.parent / "form.xml",
            module_path.parent.parent.with_suffix(".xml"),
        ]
    else:
        candidates = [
            xml_path,
            module_path.parent / "Form.xml",
            module_path.parent / "form.xml",
            module_path.parent.parent / "Form.xml",
            module_path.parent.parent / "form.xml",
        ]

    raw = ""
    for candidate in candidates:
        try:
            raw = candidate.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if raw:
            break
    if not raw:
        low = path.replace("\\", "/").lower()
        return "/forms/" in low and low.endswith("/ext/module.bsl")
    if re.search(r"<FormType>\s*(?:Ordinary|Обыч\w*)\s*</FormType>", raw, re.IGNORECASE):
        return True
    if re.search(r"<UseManagedForm>\s*false\s*</UseManagedForm>", raw, re.IGNORECASE):
        return True
    return bool(re.search(r"<Managed>\s*false\s*</Managed>", raw, re.IGNORECASE))


def _path_matches_bsl169_form_module(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    if "/forms/" not in low:
        return False
    return (
        low.endswith("/ext/module.bsl")
        or low.endswith("/ext/form/module.bsl")
        or "/ext/form/" in low
    )


def _path_is_split_form_layout_module(path: str) -> bool:
    current = Path(path)
    if current.suffix.lower() != ".bsl":
        return False
    normalized = current.as_posix().casefold()
    if "/forms/" not in normalized or "/ext/form/" not in normalized:
        return False
    return (current.parent / "Module.header").is_file()


def _path_matches_bsl007_module_types(path: str) -> bool:
    """Mirror BSLLS module metadata for UnusedLocalVariable."""
    low = path.replace("\\", "/").lower()
    if low.endswith(
        (
            "commandmodule.bsl",
            "managermodule.bsl",
            "sessionmodule.bsl",
            "valuemanagermodule.bsl",
        )
    ):
        return True
    if "/commonmodules/" in low and low.endswith("/ext/module.bsl"):
        return True

    if "/forms/" in low and low.endswith("/module.bsl"):
        return _path_is_unmanaged_form_module(path)
    if low.endswith(
        (
            "objectmodule.bsl",
            "recordsetmodule.bsl",
            "managedapplicationmodule.bsl",
            "ordinaryapplicationmodule.bsl",
            "externalconnectionmodule.bsl",
        )
    ):
        return False
    if low.endswith("/ext/module.bsl"):
        return False

    return low.endswith((".bsl", ".os"))


def _bsl260_access_metadata_key(access_text: str) -> tuple[str, str] | None:
    parts = [part.strip().casefold() for part in access_text.split(".") if part.strip()]
    if len(parts) != 2:
        return None
    if parts[0] not in {
        "справочники",
        "catalogs",
        "планывидовхарактеристик",
        "chartsofcharacteristictypes",
        "планысчетов",
        "chartsofaccounts",
    }:
        return None
    return parts[0], parts[1]


def _bsl260_call_access_text(method_call: Any, ts_node_text_fn) -> str:
    call_expr = getattr(method_call, "parent", None)
    if getattr(call_expr, "type", None) != "call_expression":
        return ""
    for child in getattr(call_expr, "children", ()):
        if getattr(child, "type", None) == "access":
            return ts_node_text_fn(child)
    return ""


_BSL051_IF_START_RE = re.compile(r"^\s*(?:Если|If)\b.*(?:Тогда|Then)\s*$", re.IGNORECASE)
_BSL051_ELSEIF_RE = re.compile(r"^\s*(?:ИначеЕсли|ElseIf|ElsIf)\b", re.IGNORECASE)
_BSL051_ELSE_RE = re.compile(r"^\s*(?:Иначе|Else)\b", re.IGNORECASE)
_BSL051_ENDIF_RE = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)
_BSL051_TRY_RE = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
_BSL051_ENDTRY_RE = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)


def _bsl051_all_branch_exit_end_if_lines(
    body_lines: list[tuple[int, str]],
    *,
    re_unconditional_exit: re.Pattern[str],
) -> set[int]:
    stack: list[dict[str, Any]] = []
    result: set[int] = set()
    try_depth = 0

    def current_exits() -> bool:
        return bool(stack and stack[-1]["current_exit"])

    for abs_idx, line in body_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if _BSL051_TRY_RE.match(line):
            try_depth += 1
            continue
        if _BSL051_ENDTRY_RE.match(line):
            try_depth = max(0, try_depth - 1)
            continue

        if _BSL051_IF_START_RE.match(line):
            stack.append({"branches": [], "current_exit": False, "has_else": False})
            continue

        if not stack:
            continue

        if try_depth == 0 and re_unconditional_exit.match(line) and ";" in line:
            stack[-1]["current_exit"] = True
            continue

        if _BSL051_ELSEIF_RE.match(line):
            stack[-1]["branches"].append(current_exits())
            stack[-1]["current_exit"] = False
            continue

        if _BSL051_ELSE_RE.match(line):
            stack[-1]["branches"].append(current_exits())
            stack[-1]["current_exit"] = False
            stack[-1]["has_else"] = True
            continue

        if _BSL051_ENDIF_RE.match(line):
            finished = stack.pop()
            finished["branches"].append(finished["current_exit"])
            exits = bool(finished["has_else"] and all(finished["branches"]))
            if exits:
                result.add(abs_idx)
                if stack:
                    stack[-1]["current_exit"] = True
            continue

    return result


def _bsl051_delimiter_lines_from_text(lines: list[str]) -> set[int]:
    delimiter_re = re.compile(
        r"^\s*(?:"
        r"КонецЕсли|EndIf|"
        r"КонецЦикла|EndDo|"
        r"КонецПопытки|EndTry|"
        r"КонецФункции|EndFunction|"
        r"КонецПроцедуры|EndProcedure|"
        r"Исключение|Except|"
        r"ИначеЕсли|ElseIf|ElsIf|"
        r"Иначе|Else"
        r")\b",
        re.IGNORECASE,
    )
    return {idx for idx, line in enumerate(lines) if delimiter_re.match(line)}


@dataclass(frozen=True, slots=True)
class ModuleModel:
    path: str

    def validate_module_level_export_variables(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        var_module_export_re,
        clean_lines: list[str],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)
        for idx, _line in enumerate(lines):
            if idx in inside:
                continue
            m = var_module_export_re.match(clean_lines[idx])
            if not m:
                continue

            names = m.group("names")
            base = m.start("names")
            export_match = re.search(
                r"\b(?:Экспорт|Export)\b",
                clean_lines[idx][m.end("names") :],
                re.IGNORECASE,
            )
            export_end = (
                m.end("names") + export_match.end() if export_match is not None else m.end()
            )
            for part in re.finditer(r"\w+", names):
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=base + part.start(),
                        end_line=idx + 1,
                        end_character=export_end,
                        severity=Severity.WARNING,
                        code="BSL054",
                    )
                )
        return diags

    def validate_self_assign_regex_fallback(
        self, lines: list[str], *, self_assign_re
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = self_assign_re.search(line)
            if not m:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.ERROR,
                    code="BSL009",
                )
            )
        return diags

    def validate_excessive_nesting(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        max_nesting_depth: int,
    ) -> list[Diagnostic]:
        re_nest_open = re.compile(
            r"^\s*(?:Если|If|ДляКаждого|Для\s+каждого|ForEach|For\s+Each|Для|For|Пока|While|Попытка|Try)\b",
            re.IGNORECASE,
        )
        re_nest_close = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
            re.IGNORECASE,
        )
        diags: list[Diagnostic] = []

        def scan_range(start_idx: int, end_idx: int) -> None:
            nesting = 0
            pending: tuple[int, int, int, int] | None = None

            def flush_pending() -> None:
                nonlocal pending
                if pending is None:
                    return
                line_no, start_col, end_col, _level = pending
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_no,
                        character=start_col,
                        end_line=line_no,
                        end_character=end_col,
                        severity=Severity.WARNING,
                        code="BSL020",
                    )
                )
                pending = None

            for i in range(start_idx, min(end_idx, len(lines))):
                line = lines[i]
                if re_nest_close.match(line):
                    if pending is not None and nesting == pending[3]:
                        flush_pending()
                    nesting = max(0, nesting - 1)
                    continue
                if re_nest_open.match(line):
                    nesting += 1
                    if nesting > max_nesting_depth:
                        start_col = len(line) - len(line.lstrip())
                        keyword_len = len(line.lstrip().split(None, 1)[0])
                        if pending is None or nesting > pending[3]:
                            pending = (i + 1, start_col, start_col + keyword_len, nesting)
            flush_pending()

        for proc in procs:
            scan_range(proc.start_idx + 1, proc.end_idx)
        covered: list[tuple[int, int]] = sorted((p.start_idx, p.end_idx) for p in procs)
        cursor = 0
        for start, end in covered:
            if cursor < start:
                scan_range(cursor, start)
            cursor = max(cursor, end + 1)
        if cursor < len(lines):
            scan_range(cursor, len(lines))
        return diags

    def validate_duplicate_string_literal(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        snapshot,
        min_duplicate_uses: int,
        string_literal_re,
        scope_line_indices_fn,
    ) -> list[Diagnostic]:
        from collections import Counter

        diags: list[Diagnostic] = []
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments if snapshot is not None else None
        )
        for scope_lines in scope_line_indices_fn(lines, procs):
            counts: Counter[str] = Counter()
            positions: dict[str, list[tuple[int, int]]] = {}
            display_values: dict[str, str] = {}
            for idx in scope_lines:
                line = (
                    code_lines_wo_comments[idx]
                    if code_lines_wo_comments is not None
                    else lines[idx]
                )
                if line.strip().startswith("//"):
                    continue
                for m in string_literal_re.finditer(line):
                    val = m.group(1)
                    if len(val) + 2 < 5:
                        continue
                    if re.fullmatch(r"\+\s*\w+\s*\+", val):
                        continue
                    key = val.casefold()
                    counts[key] += 1
                    positions.setdefault(key, []).append((idx + 1, m.start()))
                    display_values.setdefault(key, val)
            for key, count in counts.items():
                if count < min_duplicate_uses:
                    continue
                pos_list = positions[key]
                line_no, col = pos_list[0]
                val = display_values[key]
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_no,
                        character=col,
                        end_line=line_no,
                        end_character=col + len(val) + 2,
                        severity=Severity.INFORMATION,
                        code="BSL035",
                        message_args=(f'"{val}"',),
                    )
                )
        return diags

    def validate_function_paths_return(
        self,
        *,
        tree,
        bsl148_function_name_spans,
        loops_executed_at_least_once: bool,
        function_nodes=None,
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
            return []
        diags: list[Diagnostic] = []
        for line0, col0, col1 in bsl148_function_name_spans(
            root,
            loops_executed_at_least_once=loops_executed_at_least_once,
            function_nodes=function_nodes,
        ):
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line0,
                    character=col0,
                    end_line=line0,
                    end_character=col1,
                    severity=Severity.ERROR,
                    code="BSL148",
                )
            )
        return diags

    def validate_crazy_multiline_string(
        self,
        *,
        lines: list[str],
        tree,
        error_nodes,
        ts_walk_fn,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
        adjacent_literals_re,
        rule_descriptions_ru: dict[str, str],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in error_nodes if error_nodes is not None else ts_walk_fn(tree.root_node):
                if getattr(node, "type", None) != "ERROR":
                    continue
                text = ts_node_text_fn(node).strip()
                if not (text.startswith('"') and text.endswith('"')):
                    continue
                line_idx = node.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                prev_line = lines[line_idx - 1] if line_idx > 0 else ""
                if re.search(r"\+\s*\"", line_text) or re.search(r"\"\s*\+", line_text):
                    continue
                next_line = lines[line_idx + 1] if line_idx + 1 < len(lines) else ""
                if re.match(r"^\s*\+\s*\"", next_line):
                    continue
                if re.search(r"\bНСтр\s*\(", prev_line + line_text, re.IGNORECASE) and (
                    prev_line.rstrip().endswith("+") or re.match(r"^\s*\+\s*\"", next_line)
                ):
                    continue
                start_char = utf8_byte_offset_to_lsp_character_fn(line_text, node.start_point[1])
                end_char = utf8_byte_offset_to_lsp_character_fn(line_text, node.end_point[1])
                quote_char = line_text.find('"', start_char, max(end_char, start_char + 1))
                if quote_char >= 0 and "+" in line_text[start_char:quote_char]:
                    continue
                before = line_text[: start_char if quote_char < 0 else quote_char].rstrip()
                after = line_text[end_char:].lstrip()
                if before.endswith("+") or after.startswith("+"):
                    continue
                same_line_span = _bsl171_adjacent_literal_span(line_text)
                multiline_span = _bsl171_multiline_literal_span(prev_line, line_text)
                if same_line_span is not None:
                    start_char, end_char = same_line_span
                    end_line = line_idx + 1
                elif multiline_span is not None:
                    start_char, end_char = multiline_span
                    line_idx -= 1
                    end_line = line_idx + 2
                else:
                    continue
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=start_char,
                        end_line=end_line,
                        end_character=end_char,
                        severity=Severity.INFORMATION,
                        code="BSL171",
                    )
                )
        if diags:
            return diags
        for idx, line in enumerate(lines):
            if '"' not in line:
                continue
            if re.search(r"\+\s*\"", line) or re.search(r"\"\s*\+", line):
                continue
            adjacent_span = _bsl171_adjacent_literal_span(line)
            if adjacent_span is not None:
                prev = lines[idx - 1] if idx > 0 else ""
                next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                if re.search(r"\bНСтр\s*\(", prev + line, re.IGNORECASE) and (
                    prev.rstrip().endswith("+") or re.match(r"^\s*\+\s*\"", next_line)
                ):
                    continue
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=adjacent_span[0],
                        end_line=idx + 1,
                        end_character=adjacent_span[1],
                        severity=Severity.INFORMATION,
                        code="BSL171",
                    )
                )
                continue
            if idx == 0:
                continue
            prev = lines[idx - 1].rstrip()
            cur = line.lstrip()
            if prev.endswith('"') and cur.startswith('"'):
                next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                if re.match(r"^\s*\+\s*\"", next_line):
                    continue
                if re.search(r"\bНСтр\s*\(", prev + line, re.IGNORECASE) and prev.endswith("+"):
                    continue
                multiline_span = _bsl171_multiline_literal_span(lines[idx - 1], line)
                if multiline_span is None:
                    continue
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx,
                        character=multiline_span[0],
                        end_line=idx + 1,
                        end_character=multiline_span[1],
                        severity=Severity.INFORMATION,
                        code="BSL171",
                    )
                )
        return diags

    def validate_ternary_operator_usage(
        self,
        *,
        lines: list[str],
        tree,
        ternary_nodes,
        ts_walk_fn,
        utf8_byte_offset_to_lsp_character_fn,
        rule_descriptions_ru: dict[str, str],
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in ternary_nodes if ternary_nodes is not None else ts_walk_fn(tree.root_node):
            if getattr(node, "type", None) != "ternary_expression":
                continue
            line_idx = node.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx + 1,
                    character=utf8_byte_offset_to_lsp_character_fn(line_text, node.start_point[1]),
                    end_line=line_idx + 1,
                    end_character=utf8_byte_offset_to_lsp_character_fn(
                        line_text, node.end_point[1]
                    ),
                    severity=Severity.INFORMATION,
                    code="BSL251",
                )
            )
        return diags

    def validate_this_object_assign(
        self,
        *,
        path: str,
        lines: list[str],
        tree,
        assignment_nodes,
        path_is_likely_form_module_bsl,
        common_module_path_re,
        ts_walk_fn,
        ts_child_of_type_fn,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
        rule_descriptions_ru: dict[str, str],
    ) -> list[Diagnostic]:
        low = path.replace("\\", "/").lower()
        if not (path_is_likely_form_module_bsl(path) or common_module_path_re.search(low)):
            return []
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in (
            assignment_nodes if assignment_nodes is not None else ts_walk_fn(tree.root_node)
        ):
            if getattr(node, "type", None) != "assignment_statement":
                continue
            ident = ts_child_of_type_fn(node, "identifier")
            if ident is None:
                continue
            if ts_node_text_fn(ident).casefold() not in {"этотобъект", "thisobject"}:
                continue
            line_idx = ident.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx + 1,
                    character=utf8_byte_offset_to_lsp_character_fn(line_text, ident.start_point[1]),
                    end_line=line_idx + 1,
                    end_character=utf8_byte_offset_to_lsp_character_fn(
                        line_text, ident.end_point[1]
                    ),
                    severity=Severity.ERROR,
                    code="BSL252",
                )
            )
        return diags

    def validate_unknown_preprocessor_symbol(
        self,
        *,
        lines: list[str],
        tree,
        preprocessor_nodes,
        ts_walk_fn,
        ts_child_of_type_fn,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
        allowed_preproc_symbols: set[str],
        preproc_keywords: set[str],
        preproc_if_re,
        preproc_identifier_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in (
                preprocessor_nodes if preprocessor_nodes is not None else ts_walk_fn(tree.root_node)
            ):
                if getattr(node, "type", None) != "preprocessor":
                    continue
                expr = ts_child_of_type_fn(node, "expression")
                if expr is None:
                    continue
                for child in ts_walk_fn(expr):
                    if getattr(child, "type", None) != "identifier":
                        continue
                    name = ts_node_text_fn(child)
                    if name.casefold() in allowed_preproc_symbols | preproc_keywords:
                        continue
                    line_idx = child.start_point[0]
                    line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=line_idx + 1,
                            character=utf8_byte_offset_to_lsp_character_fn(
                                line_text, child.start_point[1]
                            ),
                            end_line=line_idx + 1,
                            end_character=utf8_byte_offset_to_lsp_character_fn(
                                line_text, child.end_point[1]
                            ),
                            severity=Severity.WARNING,
                            code="BSL259",
                            message_args=(name,),
                        )
                    )
            return diags
        for idx, line in enumerate(lines):
            match = preproc_if_re.match(line)
            if match is None:
                continue
            expr_text = match.group("expr")
            for ident in preproc_identifier_re.finditer(expr_text):
                name = ident.group(0)
                if name.casefold() in allowed_preproc_symbols | preproc_keywords:
                    continue
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=ident.start(),
                        end_line=idx + 1,
                        end_character=ident.end(),
                        severity=Severity.WARNING,
                        code="BSL259",
                        message_args=(name,),
                    )
                )
        return diags

    def validate_using_find_element_by_string(
        self,
        *,
        lines: list[str],
        tree,
        method_call_nodes,
        ts_walk_fn,
        ts_child_of_type_fn,
        ts_node_text_fn,
        ts_method_call_arg_exprs_fn,
        utf8_byte_offset_to_lsp_character_fn,
        method_name_re,
        find_matching_paren_fn,
        line_comment_re,
        mask_double_quoted_strings_preserve_len_fn,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        target_names = {
            "найтипонаименованию",
            "findbydescription",
            "найтипокоду",
            "findbycode",
            "найтипономеру",
            "findbynumber",
        }
        if tree is not None:
            for node in (
                method_call_nodes if method_call_nodes is not None else ts_walk_fn(tree.root_node)
            ):
                if getattr(node, "type", None) != "method_call":
                    continue
                ident = ts_child_of_type_fn(node, "identifier")
                if ident is None:
                    continue
                name = ts_node_text_fn(ident)
                if name.casefold() not in target_names:
                    continue
                args = ts_method_call_arg_exprs_fn(node)
                if len(args) > 1:
                    continue
                if args:
                    arg_text = ts_node_text_fn(args[0]).strip()
                    if arg_text and not (
                        (arg_text.startswith('"') and arg_text.endswith('"'))
                        or re.fullmatch(r"\d+(?:\.\d+)?", arg_text)
                    ):
                        continue
                line_idx = ident.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character_fn(
                            line_text, ident.start_point[1]
                        ),
                        end_line=node.end_point[0] + 1,
                        end_character=utf8_byte_offset_to_lsp_character_fn(
                            lines[node.end_point[0]]
                            if 0 <= node.end_point[0] < len(lines)
                            else line_text,
                            node.end_point[1],
                        ),
                        severity=Severity.WARNING,
                        code="BSL268",
                        message_args=(ts_node_text_fn(ident),),
                    )
                )
            return diags
        for idx, line in enumerate(lines):
            if line_comment_re.match(line):
                continue
            clean = mask_double_quoted_strings_preserve_len_fn(line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            match = method_name_re.search(clean)
            if match is None:
                continue
            end = match.end("name")
            open_idx = match.end()
            if open_idx < len(clean) and clean[open_idx] == "(":
                close_idx = find_matching_paren_fn(clean, open_idx)
                if close_idx > match.end():
                    end = close_idx + 1
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=match.start("name"),
                    end_line=idx + 1,
                    end_character=end,
                    severity=Severity.WARNING,
                    code="BSL268",
                    message_args=(match.group("name"),),
                )
            )
        return diags

    def validate_bsl152_cached_public(
        self, *, lines: list[str], regions: list[RegionInfo], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, regions, procs)

    def validate_bsl154_code_after_async(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl156_code_out_of_region(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl158_common_module_assign(
        self, *, lines: list[str], symbol_index, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, symbol_index)

    def validate_bsl159_common_module_invalid_type(
        self, *, lines: list[str], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines)

    def validate_bsl160_common_module_missing_api(
        self, *, lines: list[str], regions: list[RegionInfo], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, regions, procs)

    def validate_bsl161_168_common_module_names(
        self, *, lines: list[str], codes: tuple[str, ...], enabled_rule_fn, runner
    ) -> list[Diagnostic]:
        return runner(enabled_rule_fn, self.path, lines, codes)

    def validate_bsl173_deleting_collection_item(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl172_data_exchange_loading(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl220_235_269_query_text_diagnostics(
        self, *, lines: list[str], codes: tuple[str, ...], query_blocks, enabled_rule_fn, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, codes, enabled_rule_fn, query_blocks)

    def validate_bsl191_201_query_text_diagnostics(
        self, *, lines: list[str], codes: tuple[str, ...], query_blocks, enabled_rule_fn, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, codes, enabled_rule_fn, query_blocks)

    def validate_bsl192_193_194_228_266_method_contract_diagnostics(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        codes: tuple[str, ...],
        enabled_rule_fn,
        runner,
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs, codes, enabled_rule_fn)

    def validate_bsl174_187_236_238_query_metadata_pool(
        self,
        *,
        lines: list[str],
        enabled: tuple[str, ...],
        enabled_rule_fn,
        query_blocks,
        code_lines_without_comments,
        runner,
    ) -> list[Diagnostic]:
        enabled_codes = tuple(code for code in enabled if enabled_rule_fn(code))
        if not enabled_codes:
            return []
        return runner(
            self.path,
            lines,
            enabled_codes,
            query_blocks,
            code_lines_without_comments,
        )

    def validate_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        enabled: tuple[str, ...],
        enabled_rule_fn,
        code_lines_without_comments,
        runner,
    ) -> list[Diagnostic]:
        enabled_codes = tuple(code for code in enabled if enabled_rule_fn(code))
        if not enabled_codes:
            return []
        return runner(
            self.path,
            lines,
            procs,
            enabled_codes,
            code_lines_without_comments,
        )

    def validate_bsl244_253_261_runtime_pool(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        enabled: tuple[str, ...],
        code_lines_without_comments,
        runner,
    ) -> list[Diagnostic]:
        return runner(
            self.path,
            lines,
            procs,
            enabled,
            code_lines_without_comments,
        )

    def validate_bsl234_query_nested_fields_by_dot(
        self, *, lines: list[str], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines)

    def validate_bsl237_redundant_access_to_object(
        self, *, lines: list[str], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines)

    def validate_bsl245_server_side_export_form_method(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl240_rewrite_method_parameter(
        self, *, lines: list[str], procs: list[Any], tree, proc_node_map, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs, tree, proc_node_map)

    def validate_bsl212_missed_required_parameter(
        self, *, content: str, lines: list[str], procs: list[ProcInfo], calls: list[Any], runner
    ) -> list[Diagnostic]:
        return runner(self.path, content, lines, procs, calls)

    def validate_bsl206_207_209_query_join_diagnostics(
        self, *, lines: list[str], codes: tuple[str, ...], enabled_rule_fn, query_blocks, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, codes, enabled_rule_fn, query_blocks)

    def validate_bsl215_missing_parameter_description(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl233_public_methods_description(
        self, *, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, procs)

    def validate_bsl254_transferring_parameters(
        self, *, symbol_index, lines: list[str], procs: list[ProcInfo], runner
    ) -> list[Diagnostic]:
        return runner(symbol_index, self.path, lines, procs)

    def validate_bsl224_nested_function_in_parameters(
        self, *, lines: list[str], tree, runner
    ) -> list[Diagnostic]:
        return runner(self.path, lines, tree)

    def validate_bsl229_275_278_local_xml_pool(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        enabled: tuple[str, ...],
        rule_metadata: dict[str, Any],
        severity_cls,
        proc_name_span_fn,
        re_xml_bool_simple: str,
        re_bsl275_handler,
        re_bsl278_procname,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        low = self.path.replace("\\", "/").lower()
        file_path = Path(self.path)

        def line1_span() -> tuple[int, int]:
            if lines:
                return 0, max(len(lines[0].rstrip()), 1)
            return 0, 1

        def add_line1(code: str, message: str) -> None:
            c0, c1 = line1_span()
            severity_name = str(rule_metadata.get(code, {}).get("severity", "WARNING")).upper()
            severity = getattr(severity_cls, severity_name, severity_cls.WARNING)
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=1,
                    character=c0,
                    end_line=1,
                    end_character=c1,
                    severity=severity,
                    code=code,
                )
            )

        def find_config_root(start: Path) -> Path | None:
            for parent in (start.parent, *start.parents):
                if (parent / "Configuration.xml").exists():
                    return parent
            return None

        def xml_bool_tag_local(xml_text: str, tag: str) -> bool | None:
            match = re.search(
                re_xml_bool_simple.format(tag=re.escape(tag)),
                xml_text,
                re.IGNORECASE,
            )
            if match is None:
                return None
            return match.group(1).lower() == "true"

        def proc_by_name(name: str) -> ProcInfo | None:
            target = name.casefold()
            for proc in procs:
                if proc.name.casefold() == target:
                    return proc
            return None

        if "BSL229" in enabled_set and low.endswith("/ext/sessionmodule.bsl"):
            config_root = find_config_root(file_path)
            if config_root is not None:
                try:
                    config_text = (config_root / "Configuration.xml").read_text(
                        encoding="utf-8-sig",
                        errors="replace",
                    )
                except OSError:
                    config_text = ""
                if config_text:
                    managed_in_ordinary = xml_bool_tag_local(
                        config_text,
                        "UseManagedFormInOrdinaryApplication",
                    )
                    ordinary_in_managed = xml_bool_tag_local(
                        config_text,
                        "UseOrdinaryFormInManagedApplication",
                    )
                    if managed_in_ordinary is False:
                        add_line1(
                            "BSL229",
                            "Конфигурация не поддерживает использование управляемых форм в обычном приложении",
                        )
                    if ordinary_in_managed is True:
                        add_line1(
                            "BSL229",
                            "Конфигурация использует обычные формы в режиме управляемого приложения",
                        )

        if "BSL275" in enabled_set and low.endswith("/ext/module.bsl") and "/httpservices/" in low:
            service_dir = file_path.parent.parent
            service_xml = service_dir.parent / f"{service_dir.name}.xml"
            try:
                xml_text = service_xml.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                xml_text = ""
            for handler_match in re_bsl275_handler.finditer(xml_text):
                handler_name = handler_match.group(1).strip()
                if not handler_name:
                    add_line1("BSL275", "Не указан обработчик метода HTTP-сервиса")
                    continue
                proc = proc_by_name(handler_name)
                if proc is None:
                    add_line1("BSL275", f"Не найден обработчик HTTP-сервиса {handler_name}")
                    continue
                if len(proc.params) != 1:
                    start_char, end_char = proc_name_span_fn(lines, proc)
                    severity_name = str(
                        rule_metadata.get("BSL275", {}).get("severity", "ERROR")
                    ).upper()
                    severity = getattr(severity_cls, severity_name, severity_cls.ERROR)
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=severity,
                            code="BSL275",
                            message_args=(handler_name, service_dir.name),
                        )
                    )
        if "BSL278" in enabled_set and low.endswith("/ext/module.bsl") and "/webservices/" in low:
            service_dir = file_path.parent.parent
            service_xml = service_dir.parent / f"{service_dir.name}.xml"
            try:
                xml_text = service_xml.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                xml_text = ""
            for proc_match in re_bsl278_procname.finditer(xml_text):
                handler_name = proc_match.group(1).strip()
                if not handler_name:
                    add_line1("BSL278", "Не указан обработчик операции веб-сервиса")
                    continue
                if proc_by_name(handler_name) is None:
                    add_line1("BSL278", f"Не найден обработчик веб-сервиса {handler_name}")

        return diags

    def validate_bsl169_170_181_182_196_260_light_pool(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        enabled: tuple[str, ...],
        snapshot,
        tree,
        ts_nodes_for_types_fn=None,
        ts_child_of_type_fn,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
        path_is_likely_form_module_bsl_fn,
        path_is_command_module_bsl_fn,
        strip_inline_comment_preserve_strings_fn,
        line_comment_re,
        proc_name_span_fn,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        is_form_module = _path_matches_bsl169_form_module(self.path)
        is_form_or_command = is_form_module or path_is_command_module_bsl_fn(self.path)
        split_module_fragment = is_split_module_fragment(self.path)
        split_form_layout = is_form_module and _path_is_split_form_layout_module(self.path)
        skip_bsl169 = is_form_module and (
            _path_is_unmanaged_form_module(self.path) or split_form_layout
        )
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [strip_inline_comment_preserve_strings_fn(line) for line in lines]
        )
        collision_names = {
            "проверитьбит",
            "проверитьпобитовоймаске",
            "установитьбит",
            "побитовоеи",
            "побитовоеили",
            "побитовоене",
            "побитовоеине",
            "побитовоеисключительноеили",
            "побитовыйсдвигвлево",
            "побитовыйсдвигвправо",
            "checkbit",
            "checkbybitmask",
            "setbit",
            "bitwiseand",
            "bitwiseor",
            "bitwisenot",
            "bitwiseandnot",
            "bitwisexor",
            "bitwiseshiftleft",
            "bitwiseshiftright",
        }

        if "BSL260" in enabled_set:
            config_root = config_root_for_file(self.path)
            unsafe_index = (
                unsafe_find_by_code_metadata_index_cached(config_root)
                if config_root is not None
                else {}
            )
            root = getattr(tree, "root_node", None)
            tree_ok = root is not None and isinstance(
                getattr(root, "text", None),
                (bytes, bytearray),
            )
            nodes_for_bsl260 = (
                ts_nodes_for_types_fn(tree, {"method_call"}).get("method_call", [])
                if unsafe_index and tree_ok
                else ()
            )
            proc_line_mask = bytearray(len(lines))
            for proc in procs:
                start = max(proc.start_idx, 0)
                end = min(proc.end_idx, len(lines) - 1)
                if start <= end:
                    proc_line_mask[start : end + 1] = b"\1" * (end - start + 1)
            for node in nodes_for_bsl260 or ():
                ident = ts_child_of_type_fn(node, "identifier")
                if ident is None:
                    continue
                name = ts_node_text_fn(ident)
                if name.casefold() not in {"найтипокоду", "findbycode"}:
                    continue
                key = _bsl260_access_metadata_key(_bsl260_call_access_text(node, ts_node_text_fn))
                if key is None or not unsafe_index.get(key, False):
                    continue
                line_idx = ident.start_point[0]
                if line_idx >= len(proc_line_mask) or not proc_line_mask[line_idx]:
                    continue
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character_fn(
                            line_text,
                            ident.start_point[1],
                        ),
                        end_line=line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character_fn(
                            line_text,
                            ident.end_point[1],
                        ),
                        severity=Severity.WARNING,
                        code="BSL260",
                    )
                )

        for proc in procs:
            annotation_lines: list[tuple[int, str]] = []
            j = proc.start_idx - 1
            while j >= 0:
                line = lines[j]
                if not line.strip() or line_comment_re.match(line):
                    j -= 1
                    continue
                if line.lstrip().startswith("&"):
                    annotation_lines.append((j, line))
                    j -= 1
                    continue
                break
            if (
                "BSL169" in enabled_set
                and is_form_or_command
                and not skip_bsl169
                and not annotation_lines
            ):
                c0, c1 = proc_name_span_fn(lines, proc)
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.ERROR,
                        code="BSL169",
                        message_args=(proc.name,),
                    )
                )
            if "BSL170" in enabled_set and not is_form_or_command and not split_module_fragment:
                for ann_idx, ann_line in annotation_lines:
                    col = ann_line.find("&")
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=ann_idx + 1,
                            character=max(col, 0),
                            end_line=ann_idx + 1,
                            end_character=max(col, 0) + max(len(ann_line.strip()), 1),
                            severity=Severity.WARNING,
                            code="BSL170",
                        )
                    )
            if "BSL182" in enabled_set:
                hits: list[tuple[int, int]] = []
                for idx in range(proc.start_idx, min(proc.end_idx + 1, len(lines))):
                    line = clean_lines[idx]
                    if re.search(r"\b(?:АвтоТестПроверка|AutoTestCheck)\b", line, re.IGNORECASE):
                        col = re.search(
                            r"\b(?:АвтоТестПроверка|AutoTestCheck)\b", line, re.IGNORECASE
                        )
                        if col is not None:
                            hits.append((idx, col.start()))
                for idx, col in hits[1:]:
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=col,
                            end_line=idx + 1,
                            end_character=col + len("АвтоТестПроверка"),
                            severity=Severity.WARNING,
                            code="BSL182",
                        )
                    )
            if "BSL196" in enabled_set and proc.name.casefold() in collision_names:
                c0, c1 = proc_name_span_fn(lines, proc)
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.ERROR,
                        code="BSL196",
                        message_args=(proc.name,),
                    )
                )
            if "BSL181" in enabled_set:
                seen_inserts: dict[tuple[str, str], str] = {}
                control_depth = 0
                for idx in range(proc.start_idx, min(proc.end_idx + 1, len(lines))):
                    line = clean_lines[idx]
                    stripped_line = line.strip()
                    assignment = _BSL181_TARGET_ASSIGNMENT_RE.match(line)
                    if assignment is not None:
                        assigned_target = assignment.group("target").casefold()
                        seen_inserts = {
                            key: value
                            for key, value in seen_inserts.items()
                            if key[0] != assigned_target and value != assigned_target
                        }
                    if re.match(
                        r"^(?:КонецЕсли|EndIf|КонецПопытки|EndTry|КонецЦикла|EndDo)\b",
                        stripped_line,
                        re.IGNORECASE,
                    ):
                        control_depth = max(0, control_depth - 1)
                    for match in _BSL181_COLLECTION_INSERTION_RE.finditer(line):
                        target = match.group("target")
                        method = match.group("method").casefold()
                        first_arg = _bsl181_first_argument(line, match.end() - 1)
                        if first_arg is None:
                            continue
                        arg, end_character = first_arg
                        if method in {
                            "вставить",
                            "insert",
                        } and not _bsl181_insert_argument_supported(arg):
                            continue
                        if method in {"добавить", "add"} and not _bsl181_add_argument_supported(
                            arg
                        ):
                            continue
                        arg_key = _bsl181_normalize_argument(arg)
                        key = (target.casefold(), arg_key)
                        if control_depth == 0 and key in seen_inserts:
                            diags.append(
                                Diagnostic(
                                    file=self.path,
                                    line=idx + 1,
                                    character=match.start("target"),
                                    end_line=idx + 1,
                                    end_character=end_character,
                                    severity=Severity.WARNING,
                                    code="BSL181",
                                    message_args=(arg, target),
                                )
                            )
                        elif control_depth == 0:
                            seen_inserts[key] = arg
                    if re.match(
                        r"^(?:Если|If|ИначеЕсли|ElseIf|ElsIf|Попытка|Try|Для|For|Пока|While)\b",
                        stripped_line,
                        re.IGNORECASE,
                    ):
                        control_depth += 1
        return diags

    def validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
        self,
        *,
        lines: list[str],
        tree: Any | None = None,
        symbols: list[Any],
        calls: list[Any],
        symbol_index: Any | None = None,
        enabled_codes: tuple[str, ...],
        ts_walk_fn=None,
        ts_node_text_fn=None,
        utf8_byte_offset_to_lsp_character_fn=None,
        line_comment_re,
        bsl176_deprecated_doc_predicate_fn,
        mask_double_quoted_strings_preserve_len_fn,
        bsl175_attribute_re,
        bsl175_attr_replacements: dict[str, str],
        bsl175_method_re,
        bsl175_method_replacements: dict[str, str],
        bsl175_child_form_items_re,
        bsl175_enum_replacements: dict[str, str],
        bsl175_enum_name_re,
    ) -> list[Diagnostic]:
        enabled = set(enabled_codes)
        diags: list[Diagnostic] = []

        deprecated_locals: dict[str, tuple[str, str]] = {}
        deprecated_callers: set[str] = set()
        if "BSL176" in enabled:
            for sym in symbols:
                if getattr(sym, "kind", "") not in {"procedure", "function"}:
                    continue
                doc_comment = _extract_doc_comment(lines, sym.line - 1)
                if not bsl176_deprecated_doc_predicate_fn(doc_comment):
                    continue
                name = getattr(sym, "name", "")
                if not name:
                    continue
                deprecation = re.search(
                    r"(?:Устарел[ао]?|Deprecated)\.[ \t]*(.*)",
                    doc_comment,
                    re.IGNORECASE | re.DOTALL,
                )
                hint = deprecation.group(1).strip() if deprecation else ""
                deprecated_locals[name.casefold()] = (name, " " + hint if hint else "")
                deprecated_callers.add(name.casefold())

        enum_ranges: dict[tuple[int, int], tuple[int, int]] = {}
        if (
            "BSL175" in enabled
            and tree is not None
            and ts_walk_fn is not None
            and any(bsl175_enum_name_re.search(line) for line in lines)
        ):
            for node in ts_walk_fn(tree.root_node):
                if getattr(node, "type", "") != "identifier":
                    continue
                line_idx = node.start_point[0]
                start_index = len(
                    lines[line_idx].encode("utf-8")[: node.start_point[1]].decode("utf-8")
                )
                if bsl175_enum_name_re.match(lines[line_idx], start_index) is None:
                    continue
                while node.parent is not None and node.parent.type in {
                    "access",
                    "property_access",
                    "method_call",
                    "index_access",
                }:
                    node = node.parent
                end_line_idx = node.end_point[0]
                enum_ranges[(line_idx, start_index)] = (
                    end_line_idx,
                    utf8_byte_offset_to_lsp_character_fn(lines[end_line_idx], node.end_point[1]),
                )

        for idx, line in enumerate(lines):
            if line_comment_re.match(line):
                continue
            clean = mask_double_quoted_strings_preserve_len_fn(line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]

            if "BSL175" in enabled:
                for match in bsl175_attribute_re.finditer(clean):
                    name = match.group("name")
                    replacement = bsl175_attr_replacements.get(name.casefold())
                    if not replacement:
                        continue
                    if name.casefold() in bsl175_method_replacements:
                        diags.append(
                            Diagnostic(
                                file=self.path,
                                line=idx + 1,
                                character=utf16_len(line[: match.start("name") - 1]),
                                end_line=idx + 1,
                                end_character=utf16_len(line[: match.end("name")]),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message_variant="deprecatedMethodsMessage",
                                message_args=(name, replacement),
                            )
                        )
                    else:
                        diags.append(
                            Diagnostic(
                                file=self.path,
                                line=idx + 1,
                                character=utf16_len(line[: match.start("name") - 1]),
                                end_line=idx + 1,
                                end_character=utf16_len(line[: match.end("name")]),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message_variant="deprecatedAttributeMessage",
                                message_args=(name, replacement),
                            )
                        )
                for match in bsl175_method_re.finditer(clean):
                    name = match.group("name")
                    replacement = bsl175_method_replacements.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=utf16_len(line[: match.start("name") - 1]),
                            end_line=idx + 1,
                            end_character=utf16_len(line[: match.end("name")]),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message_variant="deprecatedMethodsMessage",
                            message_args=(name, replacement),
                        )
                    )
                for match in bsl175_child_form_items_re.finditer(clean):
                    name = match.group("name")
                    replacement = bsl175_enum_replacements.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=utf16_len(line[: match.start("name") - 1]),
                            end_line=idx + 1,
                            end_character=utf16_len(line[: match.end("name")]),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message_variant="deprecatedAttributeMessage",
                            message_args=(name, replacement),
                        )
                    )
                for match in bsl175_enum_name_re.finditer(clean):
                    enum_end_line, enum_end_character = enum_ranges.get(
                        (idx, match.start("name")),
                        (idx, utf16_len(line[: match.end("name")])),
                    )
                    name = match.group("name")
                    replacement = bsl175_enum_replacements.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=utf16_len(line[: match.start("name")]),
                            end_line=enum_end_line + 1,
                            end_character=enum_end_character,
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message_variant="deprecatedEnumNameMessage",
                            message_args=(name, replacement),
                        )
                    )
        if "BSL176" in enabled and deprecated_locals:
            for call in calls:
                if getattr(call, "receiver", None) is not None or getattr(
                    call, "receiver_expression", None
                ):
                    continue
                caller_name = getattr(call, "caller_name", None)
                if caller_name and caller_name.casefold() in deprecated_callers:
                    continue
                callee_name = getattr(call, "callee_name", "")
                if not callee_name:
                    continue
                callee_cf = callee_name.casefold()
                if callee_cf not in deprecated_locals:
                    continue
                start_char = int(getattr(call, "caller_character", 0))
                replacement_hint = deprecated_locals[callee_cf][1]
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=int(getattr(call, "caller_line", 1)),
                        character=start_char,
                        end_line=int(getattr(call, "caller_line", 1)),
                        end_character=start_char + len(callee_name),
                        severity=Severity.INFORMATION,
                        code="BSL176",
                        message_args=(callee_name, replacement_hint),
                    )
                )

        if "BSL176" in enabled:
            seen_bsl176 = {
                (diag.line, diag.character, diag.end_line, diag.end_character)
                for diag in diags
                if diag.code == "BSL176"
            }

            for call in calls:
                if getattr(call, "receiver", None) is not None or getattr(
                    call, "receiver_expression", None
                ):
                    continue
                caller_name = getattr(call, "caller_name", None)
                if caller_name and caller_name.casefold() in deprecated_callers:
                    continue
                callee_name = getattr(call, "callee_name", "")
                if not callee_name:
                    continue
                callee_cf = callee_name.casefold()
                if callee_cf not in _BSL176_PLATFORM_DEPRECATED_GLOBAL_METHODS:
                    continue
                line_1 = int(getattr(call, "caller_line", 1))
                start_char = int(getattr(call, "caller_character", 0))
                if 0 < line_1 <= len(lines):
                    found_at = (
                        lines[line_1 - 1]
                        .casefold()
                        .find(
                            callee_name.casefold(),
                            start_char,
                        )
                    )
                    if found_at >= 0:
                        start_char = found_at
                key = (line_1, start_char, line_1, start_char + len(callee_name))
                if key in seen_bsl176:
                    continue
                seen_bsl176.add(key)
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_1,
                        character=start_char,
                        end_line=line_1,
                        end_character=start_char + len(callee_name),
                        severity=Severity.INFORMATION,
                        code="BSL176",
                        message_args=(
                            _BSL176_PLATFORM_DEPRECATED_GLOBAL_METHODS[callee_cf][0],
                            " Следует использовать: "
                            + ", ".join(_BSL176_PLATFORM_DEPRECATED_GLOBAL_METHODS[callee_cf][1])
                            if _BSL176_PLATFORM_DEPRECATED_GLOBAL_METHODS[callee_cf][1]
                            else "",
                        ),
                    )
                )

        if (
            "BSL176" in enabled
            and tree is not None
            and symbol_index is not None
            and ts_walk_fn is not None
            and ts_node_text_fn is not None
            and utf8_byte_offset_to_lsp_character_fn is not None
        ):
            diags.extend(
                self._validate_bsl176_metadata_deleted_prefix_properties(
                    lines=lines,
                    tree=tree,
                    symbol_index=symbol_index,
                    ts_walk_fn=ts_walk_fn,
                    ts_node_text_fn=ts_node_text_fn,
                    utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character_fn,
                )
            )

        return diags

    def _validate_bsl176_metadata_deleted_prefix_properties(
        self,
        *,
        lines: list[str],
        tree: Any,
        symbol_index: Any,
        ts_walk_fn,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not getattr(symbol_index, "has_metadata", lambda: False)():
            return []

        from onec_hbk_bsl.indexer.metadata_registry import (  # noqa: PLC0415
            META_COLLECTION_ALIASES,
        )

        def object_name_from_receiver(receiver_text: str) -> str | None:
            tokens = [part.strip() for part in receiver_text.split(".") if part.strip()]
            if not tokens:
                return None
            if (
                len(tokens) >= 3
                and tokens[0].casefold() == "метаданные"
                and META_COLLECTION_ALIASES.get(tokens[1].casefold())
                and symbol_index.find_meta_object(tokens[2])
            ):
                return tokens[2]
            if (
                len(tokens) >= 2
                and META_COLLECTION_ALIASES.get(tokens[0].casefold())
                and symbol_index.find_meta_object(tokens[1])
            ):
                return tokens[1]
            for token in tokens:
                if symbol_index.find_meta_object(token):
                    return token
            return None

        diags: list[Diagnostic] = []
        seen: set[tuple[int, int, int]] = set()
        for node in ts_walk_fn(root):
            if getattr(node, "type", None) != "property_access":
                continue
            receiver = None
            prop = None
            for child in getattr(node, "children", []) or []:
                child_type = getattr(child, "type", None)
                if child_type == "access":
                    receiver = child
                elif child_type == "property":
                    prop = child
            if receiver is None or prop is None:
                continue
            prop_name = ts_node_text_fn(prop)
            prop_cf = prop_name.casefold()
            if not (prop_cf.startswith("удалить") or prop_cf.startswith("delete")):
                continue
            object_name = object_name_from_receiver(ts_node_text_fn(receiver))
            if object_name is None:
                continue
            members = symbol_index.get_meta_members(object_name, prop_name)
            if not any(
                member.get("name", "").casefold() == prop_cf
                and member.get("kind", "") != "form_command"
                for member in members
            ):
                continue
            line_idx = int(prop.start_point[0])
            if line_idx < 0 or line_idx >= len(lines):
                continue
            character = utf8_byte_offset_to_lsp_character_fn(
                lines[line_idx], int(prop.start_point[1])
            )
            end_character = utf8_byte_offset_to_lsp_character_fn(
                lines[line_idx], int(prop.end_point[1])
            )
            key = (line_idx + 1, character, end_character)
            if key in seen:
                continue
            seen.add(key)
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx + 1,
                    character=character,
                    end_line=line_idx + 1,
                    end_character=end_character,
                    severity=Severity.INFORMATION,
                    code="BSL176",
                    message_args=(prop_name, ""),
                )
            )
        return diags

    def validate_bsl171_248_251_252_259_268_light_pool(
        self,
        *,
        lines: list[str],
        tree: Any,
        procs: list[ProcInfo],
        codes: tuple[str, ...],
        rule_enabled_fn,
        ts_nodes_for_types_fn=None,
        rule_bsl171_fn,
        rule_bsl248_fn,
        rule_bsl251_fn,
        rule_bsl252_fn,
        rule_bsl259_fn,
        rule_bsl268_fn,
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if rule_enabled_fn(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        tree_ok = root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))
        typed_nodes: dict[str, list[Any]] = {}
        if tree_ok:
            wanted: set[str] = set()
            if "BSL171" in enabled:
                wanted.add("ERROR")
            if "BSL251" in enabled:
                wanted.add("ternary_expression")
            if "BSL252" in enabled:
                wanted.add("assignment_statement")
            if "BSL259" in enabled:
                wanted.add("preprocessor")
            if "BSL268" in enabled:
                wanted.add("method_call")
            if wanted:
                typed_nodes = ts_nodes_for_types_fn(tree, wanted)

        if "BSL171" in enabled:
            diags.extend(
                rule_bsl171_fn(
                    self.path, lines, tree if tree_ok else None, typed_nodes.get("ERROR")
                )
            )
        if "BSL248" in enabled:
            diags.extend(rule_bsl248_fn(self.path, lines, tree if tree_ok else None, procs))
        if "BSL251" in enabled:
            diags.extend(
                rule_bsl251_fn(
                    self.path,
                    lines,
                    tree if tree_ok else None,
                    typed_nodes.get("ternary_expression"),
                )
            )
        if "BSL252" in enabled:
            diags.extend(
                rule_bsl252_fn(
                    self.path,
                    lines,
                    tree if tree_ok else None,
                    typed_nodes.get("assignment_statement"),
                )
            )
        if "BSL259" in enabled:
            diags.extend(
                rule_bsl259_fn(
                    self.path,
                    lines,
                    tree if tree_ok else None,
                    typed_nodes.get("preprocessor"),
                )
            )
        if "BSL268" in enabled:
            diags.extend(
                rule_bsl268_fn(
                    self.path,
                    lines,
                    tree if tree_ok else None,
                    typed_nodes.get("method_call") or None,
                )
            )
        return diags

    def validate_bsl208_latin_cyrillic_symbol_in_word(
        self,
        *,
        lines: list[str],
        snapshot,
        rule_enabled_fn,
        re_double_quoted_string,
        re_bsl208_has_latin,
        re_bsl208_has_cyrillic,
        re_bsl208_word,
        re_bsl208_trailing_lang,
        bsl208_word_is_standard_tech_name_fn,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        re_comment = re.compile(r"^\s*//")
        seen_bsl208: set[str] = set()

        masked_lines = snapshot.masked_lines if snapshot is not None else None
        comment_starts = snapshot.comment_starts if snapshot is not None else None
        for idx, line in enumerate(lines):
            if re_comment.match(line):
                continue
            clean = (
                masked_lines[idx]
                if masked_lines is not None
                else re_double_quoted_string.sub('""', line)
            )
            comment_pos = comment_starts[idx] if comment_starts is not None else clean.find("//")
            if comment_pos is not None and comment_pos >= 0:
                clean = clean[:comment_pos]
            if not (re_bsl208_has_latin.search(clean) and re_bsl208_has_cyrillic.search(clean)):
                continue
            for match in re_bsl208_word.finditer(clean):
                word = match.group()
                if len(word) >= 4 and re_bsl208_trailing_lang.match(word):
                    continue
                if not (re_bsl208_has_latin.search(word) and re_bsl208_has_cyrillic.search(word)):
                    continue
                if bsl208_word_is_standard_tech_name_fn(word):
                    continue
                before = clean[match.start() - 1] if match.start() > 0 else ""
                after = clean[match.end()] if match.end() < len(clean) else ""
                is_declaration = re.match(
                    r"^\s*(?:Процедура|Функция|Procedure|Function)\b",
                    clean,
                    re.IGNORECASE,
                )
                if before == "." or (after == "(" and is_declaration is None):
                    continue
                if after == ".":
                    continue
                if re.match(r"^\s*(?:Для|For)\s+(?:Каждого|Each)\b", clean, re.IGNORECASE):
                    continue
                assign_pos = clean.find("=")
                is_self_update = (
                    assign_pos >= 0
                    and match.end() <= assign_pos
                    and re.search(
                        r"\b" + re.escape(word) + r"\b", clean[assign_pos + 1 :], re.IGNORECASE
                    )
                )
                seen_key = f"{word}@{idx}" if is_self_update else word
                if rule_enabled_fn("BSL208") and seen_key not in seen_bsl208:
                    seen_bsl208.add(seen_key)
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=match.start(),
                            end_line=idx + 1,
                            end_character=match.end(),
                            severity=Severity.INFORMATION,
                            code="BSL208",
                        )
                    )
        return diags

    def validate_bsl003_non_export_in_api_region(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        regions: list[RegionInfo],
        api_region_names: set[str],
        procedure_model_from_proc_info_fn,
        proc_name_span_fn,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if not any(region.name.lower() in api_region_names for region in regions):
            return diags
        for proc in procs:
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_non_export_in_api_regions(
                    lines,
                    regions=regions,
                    api_region_names=api_region_names,
                    proc_name_span=proc_name_span_fn,
                )
            )
        return diags

    def validate_bsl004_empty_code_block(self, *, lines: list[str]) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        opener_re = re.compile(
            r"^\s*(?:Если\b.*\bТогда|If\b.*\bThen|ИначеЕсли\b.*\bТогда|ElseIf\b.*\bThen|ElsIf\b.*\bThen|Иначе\b|Else\b|Пока\b.*\bЦикл|While\b.*\bDo)",
            re.IGNORECASE,
        )
        multiline_if_start_re = re.compile(
            r"^\s*(?:Если|If|ИначеЕсли|ElseIf|ElsIf)\b", re.IGNORECASE
        )
        branch_end_token_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
        terminator_re = re.compile(
            r"^\s*(?:ИначеЕсли\b|ElseIf\b|ElsIf\b|Иначе\b|Else\b|КонецЕсли\b|EndIf\b|КонецЦикла\b|EndDo\b)",
            re.IGNORECASE,
        )

        def code_part(line: str) -> str:
            return line.split("//", 1)[0].rstrip()

        def opener_span(idx: int) -> tuple[int, int, int] | None:
            line = lines[idx]
            if opener_re.match(line):
                match = branch_end_token_re.search(code_part(line))
                if match:
                    return idx, len(line) - len(line.lstrip()), len(code_part(line))
                return idx, len(line) - len(line.lstrip()), len(code_part(line))

            if not multiline_if_start_re.match(line):
                return None
            scan_idx = idx + 1
            while scan_idx < len(lines):
                stripped = lines[scan_idx].strip()
                if not stripped or stripped.startswith("//"):
                    scan_idx += 1
                    continue
                if terminator_re.match(lines[scan_idx]):
                    return None
                match = branch_end_token_re.search(code_part(lines[scan_idx]))
                if match:
                    return scan_idx, match.start(), match.end()
                scan_idx += 1
            return None

        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            span = opener_span(idx)
            if span is None:
                continue
            anchor_idx, start_character, end_character = span
            j = anchor_idx + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("//")):
                j += 1
            if j >= len(lines) or not terminator_re.match(lines[j]):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=anchor_idx + 1,
                    character=start_character,
                    end_line=anchor_idx + 1,
                    end_character=end_character,
                    severity=Severity.WARNING,
                    code="BSL004",
                )
            )
        return diags

    def validate_bsl042_empty_export_method(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        procedure_model_from_proc_info_fn,
        blank_or_comment_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_empty_export_method(
                    lines,
                    blank_or_comment_re=blank_or_comment_re,
                )
            )
        return diags

    def validate_bsl062_unused_parameter(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        tree: Any,
        proc_node_map: dict[tuple[str, int, str], Any] | None,
        find_proc_definition_node_fn,
        collect_identifier_casefolds_in_proc_body_fn,
        procedure_model_from_proc_info_fn,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        tree_is_ts = root is not None and isinstance(
            getattr(root, "text", None), (bytes, bytearray)
        )

        for proc in procs:
            used_casefold_factory = None
            if tree_is_ts:
                key = (proc.name, proc.start_idx, proc.kind)
                proc_node = (
                    proc_node_map.get(key)
                    if proc_node_map is not None
                    else find_proc_definition_node_fn(tree, proc)
                )
                if proc_node is not None:
                    candidates = frozenset(name.casefold() for name in proc.params if name)
                    used_casefold_factory = partial(
                        collect_identifier_casefolds_in_proc_body_fn,
                        proc_node,
                        candidate_casefolds=candidates,
                    )
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_unused_parameters(
                    lines,
                    used_casefold=None,
                    used_casefold_factory=used_casefold_factory,
                )
            )
        return diags

    def validate_bsl064_procedure_returns_value(
        self,
        *,
        procs: list[ProcInfo],
        tree: Any,
        proc_node_map: dict[tuple[str, int, str], Any] | None,
        find_proc_definition_node_fn,
        ts_walk_fn,
        ts_nodes_for_types_fn=None,
        utf8_byte_offset_to_lsp_character_fn,
        lines: list[str],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []
        if ts_nodes_for_types_fn is not None:
            return_nodes = ts_nodes_for_types_fn(tree, {"return_statement"})["return_statement"]
        else:
            return_nodes = [
                node
                for node in ts_walk_fn(root)
                if getattr(node, "type", None) == "return_statement"
            ]
        for proc in procs:
            if proc.kind != "procedure":
                continue
            key = (proc.name, proc.start_idx, proc.kind)
            proc_node = (
                proc_node_map.get(key)
                if proc_node_map is not None
                else find_proc_definition_node_fn(tree, proc)
            )
            if proc_node is None:
                continue
            proc_start = int(getattr(proc_node, "start_byte", -1))
            proc_end = int(getattr(proc_node, "end_byte", -1))
            for node in return_nodes:
                node_start = int(getattr(node, "start_byte", -2))
                if node_start < proc_start or node_start >= proc_end:
                    continue
                if not any(
                    getattr(child, "type", None) == "expression"
                    for child in getattr(node, "children", []) or []
                ):
                    continue
                start_line_idx = node.start_point[0]
                end_line_idx = node.end_point[0]
                start_line_text = lines[start_line_idx] if start_line_idx < len(lines) else ""
                end_line_text = lines[end_line_idx] if end_line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=start_line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character_fn(
                            start_line_text, node.start_point[1]
                        ),
                        end_line=end_line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character_fn(
                            end_line_text, node.end_point[1]
                        ),
                        severity=Severity.ERROR,
                        code="BSL064",
                    )
                )
        return diags

    def validate_bsl007_unused_local_variable(
        self,
        *,
        lines: list[str],
        snapshot,
    ) -> list[Diagnostic]:
        if not _path_matches_bsl007_module_types(self.path):
            return []

        root = getattr(getattr(snapshot, "tree", None), "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), bytes):
            return []

        # Resolve declarations and writes before reads so that local declarations
        # shadow module variables independently of source order.
        scopes: dict[int, dict[str, tuple[Any, bool]]] = {0: {}}
        node_scopes: dict[int, int] = {}
        nodes: list[Any] = []
        stack = [(root, 0)]
        declaration_ids: set[int] = set()
        writes: list[tuple[int, Any]] = []
        parameters: dict[int, set[str]] = {0: set()}
        executable_scopes: set[int] = set()
        deleting = False
        while stack:
            node, scope = stack.pop()
            if node.type == "preprocessor":
                directive = node.text.decode("utf-8").strip().casefold()
                if directive in {"#удаление", "#delete"}:
                    deleting = True
                    continue
                elif directive in {"#конецудаления", "#enddelete"}:
                    deleting = False
                    continue
            if deleting:
                continue
            if node.type in {"procedure_definition", "function_definition"}:
                scope = node.id
                scopes[scope] = {}
                parameters[scope] = set()
            node_scopes[node.id] = scope
            nodes.append(node)
            if scope and node.type.endswith("_statement") and node.type != "var_statement":
                executable_scopes.add(scope)
            if node.type in {"var_definition", "var_statement"}:
                names = []
                for child in node.named_children:
                    if child.type == "identifier":
                        names.append(child)
                    elif child.type == "variable_spec":
                        names.extend(n for n in child.named_children if n.type == "identifier")
                for name in names:
                    declaration_ids.add(name.id)
                    exported = any(child.type == "EXPORT_KEYWORD" for child in name.parent.children)
                    if name.parent.type == "variable_spec":
                        exported = exported or (
                            name == names[-1]
                            and any(child.type == "EXPORT_KEYWORD" for child in node.children)
                        )
                    if scope not in executable_scopes:
                        scopes[scope].setdefault(
                            name.text.decode("utf-8").casefold(), (name, exported)
                        )
            elif node.type == "parameter":
                for name in node.named_children:
                    if name.type == "identifier":
                        declaration_ids.add(name.id)
                        parameters[scope].add(name.text.decode("utf-8").casefold())
            elif node.type in {"assignment_statement", "for_statement", "for_each_statement"}:
                target = next(
                    (child for child in node.named_children if child.type == "identifier"), None
                )
                if target is not None and (
                    node.type != "assignment_statement"
                    or (node.named_children[0] == target and node.children[1].type == "=")
                ):
                    declaration_ids.add(target.id)
                    # Some grammar versions accept the parameter modifier as
                    # an assignment target, although it cannot name a variable.
                    if target.text.decode("utf-8").casefold() not in {"знач", "val"}:
                        writes.append((scope, target))
            stack.extend((child, scope) for child in reversed(node.named_children))

        # Module body assignments define module symbols even when they occur
        # after a method that refers to them.
        explicit_module_names = set(scopes[0])
        for scope, target in sorted(writes, key=lambda item: (item[0] != 0, item[1].start_byte)):
            name = target.text.decode("utf-8").casefold()
            if (
                name in parameters[scope]
                or name in scopes[scope]
                or (scope and name in explicit_module_names)
            ):
                continue
            scopes[scope][name] = (target, False)

        reads: set[tuple[int, str]] = set()
        execute_builders: dict[int, set[str]] = {}
        for node in nodes:
            if node.type != "identifier" or node.id in declaration_ids:
                continue
            parent = node.parent
            if lines[node.start_point[0]].lstrip().startswith("#"):
                continue
            if parent.type in {
                "procedure_definition",
                "function_definition",
                "method_call",
                "new_expression",
                "annotation",
                "preprocessor",
                "label",
                "goto_statement",
            }:
                continue
            scope = node_scopes[node.id]
            name = node.text.decode("utf-8").casefold()
            owner = scope if name in scopes[scope] or name in parameters[scope] else 0
            reads.add((owner, name))
            ancestor = parent
            while ancestor is not None and ancestor.type not in {
                "execute_statement",
                "procedure_definition",
                "function_definition",
                "source_file",
            }:
                ancestor = ancestor.parent
            if ancestor is not None and ancestor.type == "execute_statement":
                execute_builders.setdefault(scope, set()).add(name)

        # Preserve the documented dynamic receiver recognition only in code
        # passed to Execute or in the variables building that code.
        for node in nodes:
            if node.type != "string":
                continue
            scope = node_scopes[node.id]
            ancestor = node.parent
            while ancestor is not None and ancestor.type not in {
                "assignment_statement",
                "execute_statement",
                "procedure_definition",
                "function_definition",
                "source_file",
            }:
                ancestor = ancestor.parent
            if ancestor is None:
                continue
            is_execute = ancestor.type == "execute_statement"
            if ancestor.type == "assignment_statement":
                target = ancestor.named_children[0]
                is_execute = target.type == "identifier" and target.text.decode(
                    "utf-8"
                ).casefold() in execute_builders.get(scope, set())
            if not is_execute:
                continue
            for match in re.finditer(r"\b(\w+)\s*\.", node.text.decode("utf-8")):
                name = match.group(1).casefold()
                reads.add((scope if name in scopes[scope] else 0, name))

        diags: list[Diagnostic] = []
        for scope, symbols in scopes.items():
            for name, (node, exported) in symbols.items():
                if exported or (scope, name) in reads:
                    continue
                row, byte_col = node.start_point
                end_row, end_byte_col = node.end_point
                character = utf8_byte_offset_to_lsp_character(lines[row], byte_col)
                end_character = utf8_byte_offset_to_lsp_character(lines[end_row], end_byte_col)
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=row + 1,
                        character=character,
                        end_line=end_row + 1,
                        end_character=end_character,
                        severity=Severity.WARNING,
                        code="BSL007",
                        message_args=(node.text.decode("utf-8"),),
                    )
                )
        return sorted(diags, key=lambda diag: (diag.line, diag.character))

    def validate_bsl051_unreachable_code(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        tree: Any,
        bsl051_delimiter_lines_for_tree_fn,
        re_unconditional_exit,
        re_return_statement,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        delimiter_lines = bsl051_delimiter_lines_for_tree_fn(tree)
        if delimiter_lines is None:
            delimiter_lines = _bsl051_delimiter_lines_from_text(lines)
        end_line_idxs = {proc.end_idx for proc in procs}

        for proc in procs:
            body_lines = list(
                enumerate(lines[proc.start_idx + 1 : proc.end_idx], start=proc.start_idx + 1)
            )
            emitted_lines: set[int] = set()

            def emit_unreachable(
                abs_idx: int,
                line: str,
                emitted_lines_local: set[int] = emitted_lines,
                proc_end_idx: int = proc.end_idx,
                extend_to_block_end: bool = False,
            ) -> None:
                if abs_idx in emitted_lines_local or abs_idx in end_line_idxs:
                    return
                next_indent = len(line) - len(line.lstrip())
                end_abs = abs_idx
                first_stripped = line.strip()
                if extend_to_block_end or re_return_statement.match(first_stripped):
                    for tail_abs in range(abs_idx + 1, min(proc_end_idx, len(lines))):
                        tail = lines[tail_abs]
                        stripped_tail = tail.strip()
                        if not stripped_tail or stripped_tail.startswith("//"):
                            continue
                        end_abs = tail_abs
                end_text = lines[end_abs].rstrip()
                end_character = len(end_text)
                if (
                    end_abs == abs_idx
                    and end_text.endswith(";")
                    and (re_return_statement.match(end_text) or "=" in end_text)
                ):
                    end_character -= 1

                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=abs_idx + 1,
                        character=next_indent,
                        end_line=end_abs + 1,
                        end_character=end_character,
                        severity=Severity.ERROR,
                        code="BSL051",
                    )
                )
                emitted_lines_local.add(abs_idx)

            i = 0
            while i < len(body_lines):
                abs_idx, line = body_lines[i]
                if re_unconditional_exit.match(line) and ";" in line:
                    exit_indent = len(line) - len(line.lstrip())
                    j = i + 1
                    crossed_preprocessor = False
                    while j < len(body_lines):
                        next_abs, next_line = body_lines[j]
                        stripped = next_line.strip()
                        if not stripped or stripped.startswith("//"):
                            j += 1
                            continue
                        if stripped.startswith("#"):
                            crossed_preprocessor = True
                            j += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if (
                            not crossed_preprocessor
                            and next_indent <= exit_indent
                            and next_abs not in end_line_idxs
                        ):
                            if next_abs not in delimiter_lines:
                                emit_unreachable(next_abs, next_line, extend_to_block_end=True)
                        break
                    i = j
                    continue
                i += 1

            if_exit_lines = _bsl051_all_branch_exit_end_if_lines(
                body_lines,
                re_unconditional_exit=re_unconditional_exit,
            )
            if if_exit_lines:
                for pos, (abs_idx, _line) in enumerate(body_lines):
                    if abs_idx not in if_exit_lines:
                        continue
                    end_indent = len(lines[abs_idx]) - len(lines[abs_idx].lstrip())
                    for next_abs, next_line in body_lines[pos + 1 :]:
                        stripped = next_line.strip()
                        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                            continue
                        if next_abs in end_line_idxs:
                            break
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent <= end_indent and next_abs not in delimiter_lines:
                            emit_unreachable(next_abs, next_line)
                        break
        return diags

    def validate_bsl001_syntax_errors(
        self,
        *,
        tree: Any,
        parser_extract_errors_fn,
        current_lines: list[str],
    ) -> list[Diagnostic]:
        errors = parser_extract_errors_fn(tree)
        # tree-sitter may produce nested ERROR nodes with the same start point.
        # Keep one diagnostic per location, preferring the widest span/message.
        by_start: dict[tuple[int, int], dict[str, Any]] = {}
        for err in errors:
            key = (int(err.get("line", 0)), int(err.get("column", 0)))
            prev = by_start.get(key)
            if prev is None:
                by_start[key] = err
                continue
            prev_span = (int(prev.get("end_line", 0)), int(prev.get("end_column", 0)))
            cur_span = (int(err.get("end_line", 0)), int(err.get("end_column", 0)))
            if cur_span > prev_span or len(str(err.get("message", ""))) > len(
                str(prev.get("message", ""))
            ):
                by_start[key] = err
        errors = list(by_start.values())
        diags: list[Diagnostic] = []
        for error in errors:
            line_text = ""
            if 1 <= error["line"] <= len(current_lines):
                line_text = current_lines[error["line"] - 1]
            if re.search(r"\?\s+\(", line_text):
                continue
            if re.search(r";\s*;", line_text):
                continue
            if re.match(r"^\s*(?:/|\+|-|\*|\b(?:И|ИЛИ|And|Or)\b)", line_text, re.IGNORECASE):
                continue
            if re.search(r'\+\s*","\s*\+\s*$', line_text):
                continue
            if re.search(r",\s*2\s*\)\)\s*;?\s*$", line_text):
                continue
            if re.match(
                r"^\s*(?:Для\s+Каждого|For\s+Each|Процедура|Функция|Procedure|Function)\b.*;\s*$",
                line_text,
                re.IGNORECASE,
            ):
                continue
            if re.search(r"\b(?:Окр|Round)\s*\(", line_text, re.IGNORECASE) and re.search(
                r",\s*\d+\s*\)", line_text
            ):
                continue
            if re.search(r"'\d{4}-\d{2}-\d{2}'", line_text):
                continue
            if re.search(r"\b(?:ПолучитьОбласть|GetArea)\s*\(", line_text, re.IGNORECASE):
                continue
            if re.search(r"\+\s*\([^)]*[+*/-][^)]*\)\s*", line_text):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=error["line"],
                    character=error["column"],
                    end_line=error["end_line"],
                    end_character=error["end_column"],
                    severity=Severity.ERROR,
                    code="BSL001",
                    message_args=(error["message"],),
                )
            )
        return diags

    def validate_bsl002_method_size(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        procedure_model_from_proc_info_fn,
        max_proc_lines: int,
        mask_strings_and_comments_for_counter_fn,
        proc_name_span_fn,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_method_size(
                    lines,
                    max_proc_lines=max_proc_lines,
                    mask_strings_and_comments_for_counter=mask_strings_and_comments_for_counter_fn,
                    proc_name_span=proc_name_span_fn,
                )
            )
        return diags

    def validate_bsl202_205_223_243_249_light_call_pool(
        self,
        *,
        lines: list[str],
        tree,
        enabled: tuple[str, ...],
        snapshot,
        strip_inline_comment_preserve_strings_fn,
        ts_nodes_for_types_fn,
        ts_child_of_type_fn,
        ts_node_text_fn,
        ts_method_call_arg_exprs_fn,
        ts_walk_fn,
        ts_method_identifier_span_fn,
        utf8_byte_offset_to_lsp_character_fn,
        bsl223_structure_names: set[str],
        bsl249_style_constructor_names: set[str],
        split_top_level_args_fn,
        find_matching_paren_fn,
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [strip_inline_comment_preserve_strings_fn(line) for line in lines]
        )

        def placeholder_indexes(template: str) -> set[int]:
            out: set[int] = set()
            i = 0
            while i < len(template):
                if template[i] != "%":
                    i += 1
                    continue
                if i + 1 < len(template) and template[i + 1] == "%":
                    i += 2
                    continue
                if i + 1 < len(template) and template[i + 1] == "(":
                    j = i + 2
                    digits: list[str] = []
                    while j < len(template) and template[j].isdigit():
                        digits.append(template[j])
                        j += 1
                    if digits and j < len(template) and template[j] == ")":
                        out.add(int("".join(digits)))
                        i = j + 1
                        continue
                j = i + 1
                digits = []
                while j < len(template) and template[j].isdigit():
                    digits.append(template[j])
                    j += 1
                if digits:
                    out.add(int("".join(digits)))
                    i = j
                    continue
                i += 1
            return out

        if {"BSL202", "BSL223"} & enabled_set:
            line_texts = lines
            nodes = ts_nodes_for_types_fn(tree, {"method_call", "new_expression"})

            if "BSL223" in enabled_set:
                for node in nodes["new_expression"]:
                    type_node = ts_child_of_type_fn(node, "identifier")
                    if (
                        type_node is not None
                        and ts_node_text_fn(type_node).casefold() in bsl223_structure_names
                    ):
                        args = ts_method_call_arg_exprs_fn(node)
                        if len(args) > 1:
                            nested = False
                            for expr in args[1:]:
                                for child in ts_walk_fn(expr):
                                    if getattr(child, "type", None) != "new_expression":
                                        continue
                                    nested_args = ts_method_call_arg_exprs_fn(child)
                                    if nested_args:
                                        nested = True
                                        break
                                if nested:
                                    break
                            if nested:
                                line_idx = node.start_point[0]
                                line_text = (
                                    line_texts[line_idx] if line_idx < len(line_texts) else ""
                                )
                                start_char = utf8_byte_offset_to_lsp_character_fn(
                                    line_text, node.start_point[1]
                                )
                                diags.append(
                                    Diagnostic(
                                        file=self.path,
                                        line=line_idx + 1,
                                        character=start_char,
                                        end_line=line_idx + 1,
                                        end_character=min(
                                            len(line_text),
                                            utf8_byte_offset_to_lsp_character_fn(
                                                line_text, node.end_point[1]
                                            ),
                                        ),
                                        severity=Severity.INFORMATION,
                                        code="BSL223",
                                    )
                                )

            for node in nodes["method_call"]:
                ident = ts_child_of_type_fn(node, "identifier")
                if ident is None:
                    continue
                name_cf = ts_node_text_fn(ident).casefold()
                span = ts_method_identifier_span_fn(node, line_texts)
                if span is None:
                    continue
                line_1, char_1, end_char = span

                if "BSL202" in enabled_set and name_cf in {"стршаблон", "strtemplate"}:
                    args = ts_method_call_arg_exprs_fn(node)
                    if args:
                        first = ts_node_text_fn(args[0]).strip()
                        if len(first) >= 2 and first[0] == '"' and first[-1] == '"':
                            template = first[1:-1].replace('""', '"')
                            indexes = placeholder_indexes(template)
                            expected = max(indexes) if indexes else 0
                            actual = max(0, len(args) - 1)
                            if expected != actual:
                                diags.append(
                                    Diagnostic(
                                        file=self.path,
                                        line=line_1,
                                        character=char_1,
                                        end_line=line_1,
                                        end_character=end_char,
                                        severity=Severity.ERROR,
                                        code="BSL202",
                                    )
                                )

        if {"BSL243", "BSL249"} & enabled_set:
            for idx, line in enumerate(clean_lines):
                if "BSL243" in enabled_set:
                    for m in re.finditer(
                        r"(?<![\w.])(?P<obj>\w+(?:\s*\.\s*\w+)*)\s*\.\s*"
                        r"(?:Вставить|Insert|Добавить|Add)\s*\((?P<args>[^)]*)\)",
                        line,
                        re.IGNORECASE,
                    ):
                        obj = re.sub(r"\s+", "", m.group("obj")).casefold()
                        parts = [part.strip() for part in split_top_level_args_fn(m.group("args"))]
                        relevant = [re.sub(r"\s+", "", part).casefold() for part in parts if part]
                        if any(part == obj for part in relevant):
                            start = m.start("obj")
                            end = m.end("obj")
                            diags.append(
                                Diagnostic(
                                    file=self.path,
                                    line=idx + 1,
                                    character=start,
                                    end_line=idx + 1,
                                    end_character=end,
                                    severity=Severity.ERROR,
                                    code="BSL243",
                                )
                            )
                if "BSL249" in enabled_set:
                    for m in re.finditer(
                        r"\b(?:Новый|New)\s+(?P<name>\w+)\b",
                        line,
                        re.IGNORECASE,
                    ):
                        if m.group("name").casefold() not in bsl249_style_constructor_names:
                            continue
                        end_character = m.end("name")
                        open_idx = line.find("(", m.end("name"))
                        if open_idx >= 0:
                            close_idx = find_matching_paren_fn(line, open_idx)
                            if close_idx > open_idx:
                                end_character = close_idx + 1
                        diags.append(
                            Diagnostic(
                                file=self.path,
                                line=idx + 1,
                                character=m.start(),
                                end_line=idx + 1,
                                end_character=end_character,
                                severity=Severity.ERROR,
                                code="BSL249",
                                message_args=(m.group("name"),),
                            )
                        )
        return diags

    def validate_bsl221_222_239_271_light_pool(
        self,
        *,
        lines: list[str],
        tree,
        procs: list[ProcInfo],
        enabled: tuple[str, ...],
        snapshot,
        strip_inline_comment_preserve_strings_fn,
        reserved_parameter_names_re,
        ts_walk_fn,
        ts_nodes_for_types_fn=None,
        ts_child_of_type_fn=None,
        ts_node_text_fn,
        utf8_byte_offset_to_lsp_character_fn,
        bsl221_nstr_re,
        bsl221_lang_re,
        bsl271_unix_unavailable_new_re,
        bsl271_platform_guard_re,
        proc_name_span_fn,
        declared_languages: set[str],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [strip_inline_comment_preserve_strings_fn(line) for line in lines]
        )

        if {"BSL221", "BSL222"} & enabled_set:
            for idx, line in enumerate(clean_lines):
                for match in bsl221_nstr_re.finditer(line):
                    langs = {
                        m.group("lang").casefold()
                        for m in bsl221_lang_re.finditer(match.group("body"))
                    }
                    missing = declared_languages - langs
                    if not missing:
                        continue
                    code = (
                        "BSL222"
                        if re.search(r"\b(?:СтрШаблон|StrTemplate)\s*\(", line, re.IGNORECASE)
                        else "BSL221"
                    )
                    if code not in enabled_set:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=match.start(),
                            end_line=idx + 1,
                            end_character=match.end(),
                            severity=Severity.WARNING if code == "BSL222" else Severity.INFORMATION,
                            code=code,
                            message_args=("[" + ", ".join(sorted(missing)) + "]",),
                        )
                    )

        if "BSL239" in enabled_set and reserved_parameter_names_re is not None:
            for proc in procs:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                for param in proc.params:
                    if not reserved_parameter_names_re.fullmatch(param):
                        continue
                    col = line_text.find(param)
                    if col < 0:
                        col = proc.header_col
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=proc.start_idx + 1,
                            character=col,
                            end_line=proc.start_idx + 1,
                            end_character=col + len(param),
                            severity=Severity.WARNING,
                            code="BSL239",
                            message_args=(param,),
                        )
                    )

        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return diags
        line_texts = lines
        if "BSL271" in enabled_set:
            if ts_nodes_for_types_fn is not None:
                nodes = ts_nodes_for_types_fn(tree, {"new_expression"})["new_expression"]
            else:
                nodes = [
                    node
                    for node in ts_walk_fn(root)
                    if getattr(node, "type", None) == "new_expression"
                ]
            for node in nodes:
                type_node = ts_child_of_type_fn(node, "identifier")
                if type_node is None:
                    continue
                type_name = ts_node_text_fn(type_node)
                if not bsl271_unix_unavailable_new_re.search(f"Новый {type_name}"):
                    continue
                guarded = False
                cur = getattr(node, "parent", None)
                while cur is not None:
                    if getattr(cur, "type", None) in {
                        "if_statement",
                        "elseif_clause",
                    } and bsl271_platform_guard_re.search(ts_node_text_fn(cur)):
                        guarded = True
                        break
                    cur = getattr(cur, "parent", None)
                if guarded:
                    continue
                line_idx = node.start_point[0]
                line_text = line_texts[line_idx] if line_idx < len(line_texts) else ""
                start_char = utf8_byte_offset_to_lsp_character_fn(line_text, node.start_point[1])
                end_line_idx = node.end_point[0]
                end_line_text = line_texts[end_line_idx] if end_line_idx < len(line_texts) else ""
                end_char = utf8_byte_offset_to_lsp_character_fn(end_line_text, node.end_point[1])
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=start_char,
                        end_line=end_line_idx + 1,
                        end_character=end_char,
                        severity=Severity.ERROR,
                        code="BSL271",
                        message_args=(type_name,),
                    )
                )
        return diags
