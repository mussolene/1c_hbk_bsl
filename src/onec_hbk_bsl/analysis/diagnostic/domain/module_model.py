from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo


@dataclass(frozen=True, slots=True)
class ModuleModel:
    path: str

    def validate_deprecated_warning(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        deprecated_message_re,
        proc_containing_line,
        is_typical_client_command_handler,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = deprecated_message_re.match(line)
            if not m:
                continue
            proc = proc_containing_line(procs, idx)
            if proc is not None and is_typical_client_command_handler(proc, lines):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.WARNING,
                    code="BSL022",
                    message=(
                        "Предупреждение()/Warning() is a modal dialog deprecated in managed UI. "
                        "Use ПоказатьПредупреждение() / ShowMessageBox() instead."
                    ),
                )
            )
        return diags

    def validate_useless_condition_regex_fallback(
        self,
        lines: list[str],
        *,
        if_literal_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            if not if_literal_re.match(line):
                continue
            literal_m = re.search(r"\b(Истина|True|Ложь|False)\b", line, re.IGNORECASE)
            literal = literal_m.group(1) if literal_m else "literal"
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.WARNING,
                    code="BSL052",
                    message=(
                        f"Condition is always '{literal}' — "
                        "this If branch either always or never executes."
                    ),
                )
            )
        return diags

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
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start("names"),
                    end_line=idx + 1,
                    end_character=len(clean_lines[idx].rstrip().rstrip(";").rstrip()),
                    severity=Severity.WARNING,
                    code="BSL054",
                    message="Не рекомендуется использовать экспортные переменные. Это может стать источником трудновоспроизводимых ошибок",
                )
            )
        return diags

    def validate_module_variables_description(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        var_module_re,
        clean_lines: list[str],
        has_preceding_description,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)
        for idx, _line in enumerate(lines):
            if idx in inside:
                continue
            code_part = clean_lines[idx].rstrip()
            if not code_part.strip():
                continue
            m = var_module_re.match(code_part)
            if not m:
                continue
            if has_preceding_description(lines, idx):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start("names"),
                    end_line=idx + 1,
                    end_character=len(code_part.rstrip().rstrip(";").rstrip()),
                    severity=Severity.INFORMATION,
                    code="BSL219",
                    message="Добавьте описание переменной",
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
                    message="Удалите бесполезное присваивание переменной самой себе",
                )
            )
        return diags

    def validate_export_in_command_or_form_module(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
    ) -> list[Diagnostic]:
        stem_lower = Path(self.path).stem.lower()
        is_command_or_form = (
            stem_lower.endswith("command")
            or stem_lower.endswith("команды")
            or "форма" in stem_lower
            or "form" in stem_lower
        )
        if not is_command_or_form:
            return []
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export:
                continue
            line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=proc.start_idx + 1,
                    character=proc.header_col,
                    end_line=proc.start_idx + 1,
                    end_character=len(line_text),
                    severity=Severity.WARNING,
                    code="BSL017",
                    message=(
                        f"Export modifier is not allowed in command/form modules "
                        f"({proc.kind} '{proc.name}')"
                    ),
                )
            )
        return diags

    def validate_header_semicolon(
        self, lines: list[str], *, header_semicolon_re
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if not header_semicolon_re.match(line):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=len(line.rstrip()) - 1,
                    end_line=idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.INFORMATION,
                    code="BSL030",
                    message="Procedure/function header should not end with a semicolon",
                )
            )
        return diags

    def validate_this_form_usage(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        path_is_likely_form_module_bsl,
        proc_containing_line,
        mask_double_quoted_strings_preserve_len,
        this_form_re,
    ) -> list[Diagnostic]:
        if not path_is_likely_form_module_bsl(self.path):
            return []
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            proc = proc_containing_line(procs, idx)
            if proc is not None and any(
                re.fullmatch(r"(?:ЭтаФорма|ThisForm)", param, re.IGNORECASE)
                for param in proc.params
            ):
                continue
            clean = mask_double_quoted_strings_preserve_len(line)
            comment_col = clean.find("//")
            if comment_col >= 0:
                clean = clean[:comment_col]
            for m in this_form_re.finditer(clean):
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL040",
                        message=(
                            "Избегайте использования ЭтаФорма/ThisForm, передавайте форму в параметрах метода"
                        ),
                    )
                )
        return diags

    def validate_select_top_without_order_by(
        self,
        *,
        query_blocks,
        query_top_re,
        query_union_re,
        query_where_re,
        query_order_by_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for block in query_blocks:
            start_idx = block.start_idx
            block_lines = list(block.block_lines)
            query_text = block.query_text
            top_matches = list(query_top_re.finditer(query_text))
            if not top_matches:
                continue
            has_union = bool(query_union_re.search(query_text))
            has_where = bool(query_where_re.search(query_text))
            if not has_union and query_order_by_re.search(query_text):
                continue

            for top_match in top_matches:
                top_limit = top_match.group(1)
                if not has_union:
                    next_union = query_union_re.search(query_text, top_match.end())
                    segment_end = next_union.start() if next_union else len(query_text)
                    segment_text = query_text[top_match.start() : segment_end]
                    if query_order_by_re.search(segment_text):
                        continue
                if not has_union and top_limit in {"0", "1"} and has_where:
                    continue

                rel_pos = top_match.start()
                passed = 0
                line_idx = start_idx
                col = 0
                end_col = 0
                for offset, raw_line in enumerate(block_lines):
                    line_len = len(raw_line)
                    if rel_pos <= passed + line_len:
                        line_idx = start_idx + offset
                        col = max(0, rel_pos - passed)
                        local_match = query_top_re.search(raw_line[col:])
                        if local_match:
                            col += local_match.start()
                            end_col = col + (local_match.end() - local_match.start())
                        else:
                            end_col = min(len(raw_line), col + len(top_match.group(0)))
                        break
                    passed += line_len + 1

                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=col,
                        end_line=line_idx + 1,
                        end_character=end_col,
                        severity=Severity.WARNING,
                        code="BSL077",
                        message="Нужно изменить запрос, добавив упорядочивание",
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
                        message="Превышен допустимый уровень вложенности управляющих конструкций",
                    )
                )
                pending = None

            for i in range(start_idx, min(end_idx, len(lines))):
                line = lines[i]
                if re_nest_close.match(line):
                    was_over_limit = nesting > max_nesting_depth
                    nesting = max(0, nesting - 1)
                    if was_over_limit and nesting <= max_nesting_depth:
                        flush_pending()
                    continue
                if re_nest_open.match(line):
                    nesting += 1
                    if nesting > max_nesting_depth:
                        start_col = len(line) - len(line.lstrip())
                        keyword_len = len(line.lstrip().split(None, 1)[0])
                        if pending is None or nesting >= pending[3]:
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

    def validate_statement_missing_semicolon(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        stmt_no_semi_re,
        double_quoted_string_re,
        single_quoted_string_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        continuation_re = re.compile(r"^\s*(?:И|Или|AND|OR)\b", re.IGNORECASE)
        continuation_prefix_re = re.compile(
            r"^\s*(?:[),.=]|[+\-*/%]|\b(?:И|Или|AND|OR)\b)",
            re.IGNORECASE,
        )
        header_start_re = re.compile(
            r"^\s*(?:Процедура|Функция|Procedure|Function)\b", re.IGNORECASE
        )
        end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b", re.IGNORECASE
        )
        terminal_end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry|КонецФункции|EndFunction|КонецПроцедуры|EndProcedure)\b",
            re.IGNORECASE,
        )
        control_header_start_re = re.compile(
            r"^\s*(?:Если|If|ИначеЕсли|ElseIf|Пока|While|Для(?:\s+Каждого)?|For(?:\s+Each)?)\b",
            re.IGNORECASE,
        )
        control_header_tail_re = re.compile(r"\)\s*(?:Тогда|Then|Цикл|Do)\s*$", re.IGNORECASE)

        def code_without_comments_and_strings(text: str) -> str:
            code = text.split("//", 1)[0]
            code = double_quoted_string_re.sub('""', code)
            code = single_quoted_string_re.sub("''", code)
            return code

        def missing_semicolon_anchor(code_part: str) -> int:
            m_return = re.match(r"^(\s*(?:Возврат|Return)\s+)\S", code_part, re.IGNORECASE)
            if m_return:
                return m_return.end(1)
            return max(0, len(code_part) - 1)

        header_continuation_lines: set[int] = set()
        for proc in procs:
            header_end_idx = proc.start_idx
            start_code = code_without_comments_and_strings(lines[proc.start_idx])
            if header_start_re.match(start_code):
                header_balance = start_code.count("(") - start_code.count(")")
                j = proc.start_idx
                while header_balance > 0 and j + 1 < min(proc.end_idx, len(lines)):
                    j += 1
                    header_balance += code_without_comments_and_strings(lines[j]).count("(")
                    header_balance -= code_without_comments_and_strings(lines[j]).count(")")
                header_end_idx = j
                for line_idx in range(proc.start_idx + 1, header_end_idx + 1):
                    header_continuation_lines.add(line_idx)

            paren_balance = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                if i <= header_end_idx:
                    continue
                line = lines[i]
                stripped = line.rstrip()
                if not stripped or stripped.strip().startswith("//"):
                    continue
                code_part = stripped.split("//")[0].rstrip()
                if not code_part:
                    continue
                if header_start_re.match(code_part):
                    continue
                if control_header_start_re.match(code_part) and code_part.rstrip().endswith(
                    ("Тогда", "Then", "Цикл", "Do")
                ):
                    continue
                if control_header_tail_re.search(code_part):
                    continue
                if end_kw_re.match(code_part) and not code_part.endswith(";"):
                    col = len(code_part) - len(code_part.lstrip())
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=col,
                            end_line=i + 1,
                            end_character=col + len(code_part.lstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL030",
                            message=("Пропущена точка с запятой в конце выражения"),
                        )
                    )
                    continue
                code_masked = code_without_comments_and_strings(code_part)
                starts_inside_multiline = paren_balance > 0
                paren_balance = max(
                    0, paren_balance + code_masked.count("(") - code_masked.count(")")
                )
                last_char = code_part[-1]
                if last_char in (";", ",", "(", "[", "|", "+", "-", "*", "/", "="):
                    continue
                next_sig = None
                for j in range(i + 1, min(proc.end_idx, len(lines))):
                    nxt = lines[j].strip()
                    if not nxt or nxt.startswith("//"):
                        continue
                    next_sig = lines[j]
                    break
                if starts_inside_multiline or paren_balance > 0:
                    continue
                if next_sig is not None and (
                    continuation_re.match(next_sig) or continuation_prefix_re.match(next_sig)
                ):
                    continue
                if stmt_no_semi_re.match(code_part):
                    col = missing_semicolon_anchor(code_part)
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=col,
                            end_line=i + 1,
                            end_character=col + 1,
                            severity=Severity.INFORMATION,
                            code="BSL030",
                            message=("Пропущена точка с запятой в конце выражения"),
                        )
                    )
        seen_lines = {diag.line for diag in diags}
        for idx, line in enumerate(lines):
            if idx in header_continuation_lines:
                continue
            stripped = line.rstrip()
            if not stripped or stripped.strip().startswith("//"):
                continue
            code_part = stripped.split("//")[0].rstrip()
            if not code_part or code_part.endswith((";", "[")):
                continue
            if header_start_re.match(code_part):
                continue
            if control_header_start_re.match(code_part) and code_part.rstrip().endswith(
                ("Тогда", "Then", "Цикл", "Do")
            ):
                continue
            if control_header_tail_re.search(code_part):
                continue
            code_masked = code_without_comments_and_strings(code_part)
            if code_masked.count("(") > code_masked.count(")"):
                continue
            if not stmt_no_semi_re.match(code_part):
                continue
            next_sig = None
            for j in range(idx + 1, len(lines)):
                nxt = lines[j].strip()
                if not nxt or nxt.startswith("//"):
                    continue
                next_sig = lines[j]
                break
            if next_sig is not None and continuation_prefix_re.match(next_sig):
                continue
            if next_sig is None or not terminal_end_kw_re.match(next_sig):
                continue
            if idx + 1 in seen_lines:
                continue
            col = missing_semicolon_anchor(code_part)
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=col,
                    end_line=idx + 1,
                    end_character=col + 1,
                    severity=Severity.INFORMATION,
                    code="BSL030",
                    message="Пропущена точка с запятой в конце выражения",
                )
            )
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
        line_starts_with_raise_statement_fn,
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
                if all(line_starts_with_raise_statement_fn(lines[ln - 1]) for ln, _ in pos_list):
                    continue
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
                        message=(
                            "Необходимо избавиться от многократного использования "
                            f'строкового литерала "{val}"'
                        ),
                    )
                )
        return diags

    def validate_function_paths_return(
        self, *, tree, bsl148_function_name_spans, loops_executed_at_least_once: bool
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
            return []
        diags: list[Diagnostic] = []
        for line0, col0, col1 in bsl148_function_name_spans(
            root, loops_executed_at_least_once=loops_executed_at_least_once
        ):
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line0,
                    character=col0,
                    end_line=line0,
                    end_character=col1,
                    severity=Severity.WARNING,
                    code="BSL148",
                    message="Не все пути выполнения функции возвращают значение",
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
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=start_char,
                        end_line=line_idx + 1,
                        end_character=end_char,
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=rule_descriptions_ru["BSL171"],
                    )
                )
        if diags:
            return [
                diag
                for diag in diags
                if not (
                    1 <= diag.line <= len(lines)
                    and (
                        re.search(r"\+\s*\"", lines[diag.line - 1])
                        or re.search(r"\"\s*\+", lines[diag.line - 1])
                    )
                )
            ]
        for idx, line in enumerate(lines):
            if re.search(r"\+\s*\"", line) or re.search(r"\"\s*\+", line):
                continue
            match = adjacent_literals_re.search(line)
            if match is not None:
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
                        character=match.start(),
                        end_line=idx + 1,
                        end_character=match.end(),
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=rule_descriptions_ru["BSL171"],
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
                end_character = min(
                    len(line.rstrip()), len(line) - len(cur) + len(cur.split('"', 2)[1]) + 2
                )
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=len(line) - len(cur),
                        end_line=idx + 1,
                        end_character=end_character,
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=rule_descriptions_ru["BSL171"],
                    )
                )
        return diags

    def validate_invalid_character_in_file(
        self, *, lines: list[str], illegal_chars: dict[str, str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []

        def string_literal_span_containing(line: str, pos: int) -> tuple[int, int] | None:
            idx = 0
            while idx < len(line):
                if line[idx] != '"':
                    idx += 1
                    continue
                start = idx
                idx += 1
                while idx < len(line):
                    if line[idx] == '"':
                        if idx + 1 < len(line) and line[idx + 1] == '"':
                            idx += 2
                            continue
                        end = idx + 1
                        if start <= pos < end:
                            return start, end
                        idx = end
                        break
                    idx += 1
                else:
                    if start <= pos < len(line):
                        return start, len(line.rstrip())
            return None

        for line_idx, line in enumerate(lines, start=1):
            hit = next(
                ((pos, illegal_chars[ch]) for pos, ch in enumerate(line) if ch in illegal_chars),
                None,
            )
            if hit is None:
                continue
            pos, message = hit
            string_span = string_literal_span_containing(line, pos)
            if string_span is None:
                anchor = len(line) - len(line.lstrip())
                end_character = len(line.rstrip())
            else:
                anchor, end_character = string_span
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx,
                    character=anchor,
                    end_line=line_idx,
                    end_character=end_character,
                    severity=Severity.ERROR,
                    code="BSL204",
                    message=message,
                )
            )
        return diags

    def validate_complex_condition(
        self,
        *,
        lines: list[str],
        max_bool_ops: int,
        bool_op_re,
    ) -> list[Diagnostic]:
        re_if_or_elseif_line = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b", re.IGNORECASE)
        re_then_word = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)

        def if_condition_chunk(idx: int) -> tuple[str, int, int] | None:
            line = lines[idx]
            if line.strip().startswith("//"):
                return None
            if not re_if_or_elseif_line.match(line):
                return None
            masked_line = re.sub(r"//.*", "", line)
            if re_then_word.search(masked_line):
                end_idx = idx
                then_match = re_then_word.search(masked_line)
                end_char = (
                    len(masked_line[: then_match.start()].rstrip())
                    if then_match
                    else len(masked_line.rstrip())
                )
                return masked_line, end_idx, end_char
            parts = [masked_line]
            j = idx + 1
            max_j = min(len(lines), idx + 48)
            while j < max_j:
                masked_next = re.sub(r"//.*", "", lines[j])
                parts.append(masked_next)
                then_match = re_then_word.search(masked_next)
                if then_match:
                    return "\n".join(parts), j, len(masked_next[: then_match.start()].rstrip())
                if re.match(r"^\s*(?:Тогда|Then)\b", masked_next, re.IGNORECASE):
                    break
                j += 1
            return (
                "\n".join(parts),
                j - 1,
                len(re.sub(r"//.*", "", lines[j - 1]).rstrip())
                if j > idx
                else len(masked_line.rstrip()),
            )

        def triggered_condition_span(idx: int) -> tuple[int, int] | None:
            chunk = if_condition_chunk(idx)
            if chunk is None:
                return None
            text, end_idx, end_char = chunk
            if len(bool_op_re.findall(text)) + 1 <= max_bool_ops:
                return None
            return end_idx, end_char

        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            end_span = triggered_condition_span(idx)
            if end_span is None:
                continue
            end_line_idx, end_char = end_span
            char = len(line) - len(line.lstrip())
            kw = line.lstrip()
            if kw.lower().startswith("если "):
                char += len("Если ")
            elif kw.lower().startswith("if "):
                char += len("If ")
            elif kw.lower().startswith("иначеесли "):
                char += len("ИначеЕсли ")
            elif kw.lower().startswith("elsif "):
                char += len("ElsIf ")
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=char,
                    end_line=end_line_idx + 1,
                    end_character=end_char,
                    severity=Severity.INFORMATION,
                    code="BSL036",
                    message="Выделите условие оператора Если в отдельный метод или переменную",
                )
            )
        return diags

    def validate_form_data_to_value(
        self, *, lines: list[str], line_comment_re, double_quoted_string_re, bsl190_form_data_re
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line_comment_re.match(line):
                continue
            clean = double_quoted_string_re.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            m = bsl190_form_data_re.search(clean)
            if not m:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.INFORMATION,
                    code="BSL190",
                    message="Не рекомендуемое использование метода ДанныеФормыВЗначение",
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
                    message=rule_descriptions_ru["BSL251"],
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
                    message=rule_descriptions_ru["BSL252"],
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
                            message=f'Неизвестный символ препроцессора "{name}"',
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
                        message=f'Неизвестный символ препроцессора "{name}"',
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
                        end_line=line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character_fn(
                            line_text, ident.end_point[1]
                        ),
                        severity=Severity.WARNING,
                        code="BSL268",
                        message=f'Не следует использовать  метод "{name}" и поиск по строке',
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
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=match.start("name"),
                    end_line=idx + 1,
                    end_character=match.end("name"),
                    severity=Severity.WARNING,
                    code="BSL268",
                    message=(
                        f'Не следует использовать  метод "{match.group("name")}" и поиск по строке'
                    ),
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
                    message=message,
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
                            message=f"Обработчик HTTP-сервиса {handler_name} должен принимать ровно один параметр",
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
        path_is_likely_form_module_bsl_fn,
        path_is_command_module_bsl_fn,
        strip_inline_comment_preserve_strings_fn,
        line_comment_re,
        proc_name_span_fn,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        is_form_or_command = path_is_likely_form_module_bsl_fn(
            self.path
        ) or path_is_command_module_bsl_fn(self.path)
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
            if "BSL169" in enabled_set and is_form_or_command and not annotation_lines:
                c0, c1 = proc_name_span_fn(lines, proc)
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.WARNING,
                        code="BSL169",
                        message=f"Для метода {proc.name} потеряна директива компиляции",
                    )
                )
            if "BSL170" in enabled_set and not is_form_or_command:
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
                            message="Директива компиляции в этом модуле избыточна",
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
                            message="Избыточная повторная проверка АвтоТестПроверка",
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
                        message=f"Имя метода {proc.name} конфликтует с глобальным контекстом 8.3.12",
                    )
                )
            if "BSL181" in enabled_set:
                seen_inserts: set[tuple[str, str, str]] = set()
                for idx in range(proc.start_idx, min(proc.end_idx + 1, len(lines))):
                    line = clean_lines[idx]
                    for match in re.finditer(
                        r"\b(?P<target>\w+)\.(?P<method>Добавить|Add|Вставить|Insert)\s*\((?P<arg>[^)]*)\)",
                        line,
                        re.IGNORECASE,
                    ):
                        key = (
                            match.group("target").casefold(),
                            match.group("method").casefold(),
                            re.sub(r"\s+", "", match.group("arg")).casefold(),
                        )
                        if key in seen_inserts:
                            diags.append(
                                Diagnostic(
                                    file=self.path,
                                    line=idx + 1,
                                    character=match.start("target"),
                                    end_line=idx + 1,
                                    end_character=match.end("arg"),
                                    severity=Severity.WARNING,
                                    code="BSL181",
                                    message="Обнаружена дублирующаяся вставка в коллекцию",
                                )
                            )
                        else:
                            seen_inserts.add(key)
            if "BSL260" in enabled_set:
                for idx, _raw_line in enumerate(lines):
                    line = clean_lines[idx]
                    assign = re.search(
                        r"(?P<var>\w+)\s*=\s*(?P<expr>\w+(?:\.\w+)*\.(?:НайтиПоКоду|FindByCode)\s*\([^)]*\))",
                        line,
                        re.IGNORECASE,
                    )
                    if assign is None:
                        continue
                    var_name = assign.group("var")
                    lookahead = "\n".join(lines[idx + 1 : min(len(lines), idx + 4)])
                    if re.search(
                        rf"\b(?:ЗначениеЗаполнено|ValueIsFilled)\s*\([^)]*\b{re.escape(var_name)}\b",
                        lookahead,
                        re.IGNORECASE,
                    ) or re.search(
                        rf"\b{re.escape(var_name)}\b\s*(?:=|<>)\s*(?:Неопределено|Undefined)",
                        lookahead,
                        re.IGNORECASE,
                    ):
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=assign.start("expr"),
                            end_line=idx + 1,
                            end_character=assign.end("expr"),
                            severity=Severity.WARNING,
                            code="BSL260",
                            message="Использование НайтиПоКоду() небезопасно без проверки результата",
                        )
                    )
        return diags

    def validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
        self,
        *,
        lines: list[str],
        symbols: list[Any],
        calls: list[Any],
        enabled_codes: tuple[str, ...],
        line_comment_re,
        bsl176_deprecated_doc_re,
        mask_double_quoted_strings_preserve_len_fn,
        bsl175_attribute_re,
        bsl175_attr_replacements: dict[str, str],
        bsl175_method_replacements: dict[str, str],
        bsl175_child_form_items_re,
        bsl175_enum_replacements: dict[str, str],
        bsl175_enum_name_re,
        bsl175_global_method_re,
        bsl175_global_methods: set[str],
    ) -> list[Diagnostic]:
        enabled = set(enabled_codes)
        diags: list[Diagnostic] = []

        deprecated_locals: dict[str, str] = {}
        deprecated_callers: set[str] = set()
        if "BSL176" in enabled:
            for sym in symbols:
                if getattr(sym, "kind", "") not in {"procedure", "function"}:
                    continue
                doc_comment = getattr(sym, "doc_comment", "") or ""
                if not bsl176_deprecated_doc_re.search(doc_comment):
                    continue
                name = getattr(sym, "name", "")
                if not name:
                    continue
                deprecated_locals[name.casefold()] = name
                deprecated_callers.add(name.casefold())

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
                                character=match.start("name"),
                                end_line=idx + 1,
                                end_character=match.end("name"),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message=(
                                    f'Метод "{name}" устарел. Вместо него стоит использовать '
                                    f'"{replacement}"'
                                ),
                            )
                        )
                    else:
                        diags.append(
                            Diagnostic(
                                file=self.path,
                                line=idx + 1,
                                character=match.start("name"),
                                end_line=idx + 1,
                                end_character=match.end("name"),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message=(
                                    f'Атрибут "{name}" устарел. Вместо него стоит использовать '
                                    f"{replacement}"
                                ),
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
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=(
                                f'Используется старое наименование "{name}". Вместо него '
                                f'необходимо использовать "{replacement}"'
                            ),
                        )
                    )
                for match in bsl175_enum_name_re.finditer(clean):
                    name = match.group("name")
                    replacement = bsl175_enum_replacements.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=(
                                f'Используется старое наименование "{name}". Вместо него '
                                f'необходимо использовать "{replacement}"'
                            ),
                        )
                    )
                for match in bsl175_global_method_re.finditer(clean):
                    name = match.group("name")
                    if name.casefold() not in bsl175_global_methods:
                        continue
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=f'Метод "{name}" устарел и больше не используется',
                        )
                    )

        if "BSL176" in enabled and deprecated_locals:
            for call in calls:
                callee_name = getattr(call, "callee_name", "")
                if not callee_name:
                    continue
                callee_cf = callee_name.casefold()
                if callee_cf not in deprecated_locals:
                    continue
                caller_name = getattr(call, "caller_name", None)
                if caller_name and caller_name.casefold() in deprecated_callers:
                    continue
                start_char = int(getattr(call, "caller_character", 0))
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=int(getattr(call, "caller_line", 1)),
                        character=start_char,
                        end_line=int(getattr(call, "caller_line", 1)),
                        end_character=start_char + len(callee_name),
                        severity=Severity.INFORMATION,
                        code="BSL176",
                        message=f'Удалите вызов устаревшего метода "{callee_name}".',
                    )
                )

        return diags

    def validate_bsl171_204_217_248_251_252_259_268_light_pool(
        self,
        *,
        content: str,
        lines: list[str],
        tree: Any,
        procs: list[ProcInfo],
        codes: tuple[str, ...],
        rule_enabled_fn,
        ts_nodes_for_types_fn,
        rule_bsl171_fn,
        rule_bsl204_fn,
        rule_bsl217_fn,
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
            wanted = {
                "ERROR",
                "ternary_expression",
                "assignment_statement",
                "preprocessor",
                "method_call",
            }
            typed_nodes = ts_nodes_for_types_fn(tree, wanted)

        if "BSL171" in enabled:
            diags.extend(
                rule_bsl171_fn(
                    self.path, lines, tree if tree_ok else None, typed_nodes.get("ERROR")
                )
            )
        if "BSL204" in enabled:
            diags.extend(rule_bsl204_fn(self.path, content, lines))
        if "BSL217" in enabled:
            diags.extend(
                rule_bsl217_fn(
                    self.path, lines, tree if tree_ok else None, typed_nodes.get("method_call")
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
                    typed_nodes.get("method_call"),
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
                if bsl208_word_is_standard_tech_name_fn(word):
                    continue
                if len(word) >= 4 and re_bsl208_trailing_lang.match(word):
                    continue
                if not (re_bsl208_has_latin.search(word) and re_bsl208_has_cyrillic.search(word)):
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
                            message="Нельзя использовать латинские и кириллические символы в одном идентификаторе",
                        )
                    )
        return diags

    def validate_bsl217_missing_temp_storage_deletion(
        self,
        *,
        lines: list[str],
        tree: Any | None,
        method_call_nodes: list[Any] | None,
        global_method_calls_from_nodes_fn,
        ts_global_method_calls_fn,
        bsl217_get_from_temp_storage_names: set[str],
        ts_method_identifier_span_fn,
        ts_assignment_lvalue_text_fn,
        ts_bsl218_skip_error_ancestor_fn,
        ts_bsl218_code_block_roots_fn,
        bsl217_delete_from_temp_storage_names: set[str],
        ts_method_call_arg_exprs_fn,
        ts_node_text_fn,
        rule_descriptions_ru: dict[str, str],
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        calls = (
            global_method_calls_from_nodes_fn(method_call_nodes, lines)
            if method_call_nodes is not None
            else ts_global_method_calls_fn(tree.root_node, lines)
        )
        for call in calls:
            if str(call["name"]).casefold() not in bsl217_get_from_temp_storage_names:
                continue
            method_node = call["node"]
            assign_anc: Any | None = None
            cur: Any | None = method_node
            while cur is not None:
                if getattr(cur, "type", None) == "assignment_statement":
                    assign_anc = cur
                    break
                cur = getattr(cur, "parent", None)

            span = ts_method_identifier_span_fn(method_node, lines)
            if span is None:
                continue
            line_1, char_1, end_ch = span

            if assign_anc is None:
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL217",
                        message=rule_descriptions_ru["BSL217"],
                    )
                )
                continue

            var_name = ts_assignment_lvalue_text_fn(assign_anc)
            if not var_name:
                continue
            stmt_parent = ts_bsl218_skip_error_ancestor_fn(getattr(assign_anc, "parent", None))
            roots = ts_bsl218_code_block_roots_fn(stmt_parent) if stmt_parent is not None else None
            if not roots:
                continue
            deleted = False
            for subtree in roots:
                for later_call in ts_global_method_calls_fn(subtree, lines):
                    if later_call["line"] <= line_1:
                        continue
                    if (
                        str(later_call["name"]).casefold()
                        not in bsl217_delete_from_temp_storage_names
                    ):
                        continue
                    for expr in ts_method_call_arg_exprs_fn(later_call["node"]):
                        if ts_node_text_fn(expr).strip().casefold() == var_name.casefold():
                            deleted = True
                            break
                    if deleted:
                        break
                if deleted:
                    break
            if deleted:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=Severity.WARNING,
                    code="BSL217",
                    message=rule_descriptions_ru["BSL217"],
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
        empty_msg = "Наполните блок кодом или удалите его"
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
                    message=empty_msg,
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
        path_is_likely_form_module_bsl_fn,
        find_proc_definition_node_fn,
        collect_identifier_casefolds_in_proc_body_fn,
        procedure_model_from_proc_info_fn,
        bsl062_skip_standard_command_params: set[str],
        is_typical_client_command_handler_fn,
        is_client_notify_completion_export_handler_fn,
    ) -> list[Diagnostic]:
        if path_is_likely_form_module_bsl_fn(self.path):
            return []
        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        tree_is_ts = root is not None and isinstance(
            getattr(root, "text", None), (bytes, bytearray)
        )

        for proc in procs:
            used_casefold: set[str] | None = None
            if tree_is_ts:
                key = (proc.name, proc.start_idx, proc.kind)
                proc_node = (
                    proc_node_map.get(key)
                    if proc_node_map is not None
                    else find_proc_definition_node_fn(tree, proc)
                )
                if proc_node is not None:
                    used_casefold = collect_identifier_casefolds_in_proc_body_fn(proc_node)
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_unused_parameters(
                    lines,
                    used_casefold=used_casefold,
                    skip_standard_params=bsl062_skip_standard_command_params,
                    is_typical_client_command_handler=is_typical_client_command_handler_fn,
                    is_client_notify_completion_export_handler=(
                        is_client_notify_completion_export_handler_fn
                    ),
                )
            )
        return diags

    def validate_bsl064_procedure_returns_value(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        procedure_model_from_proc_info_fn,
        return_value_re,
        proc_header_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = procedure_model_from_proc_info_fn(self.path, proc)
            diags.extend(
                model.validate_procedure_return_value(
                    lines,
                    return_value_re=return_value_re,
                    proc_header_re=proc_header_re,
                )
            )
        return diags

    def validate_bsl007_unused_local_variable(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        snapshot,
        strip_inline_comment_preserve_strings_fn,
        bsl007_strip_double_quoted_segments_fn,
        bsl007_simple_assign_at_start_re,
        var_local_re,
        region_line_re,
        preproc_line_re,
        compiler_directive_re,
        module_assign_re,
    ) -> list[Diagnostic]:
        re_for_index_header = re.compile(
            r"^\s*(?:Для\s+(?:каждого\s+)?|For\s+(?:Each\s+)?)(\w+)\s*(?:=|\b(?:Из|In)\b)",
            re.IGNORECASE,
        )
        diags: list[Diagnostic] = []
        inside_proc: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside_proc.add(i)

        code_lines = snapshot.code_lines_without_comments if snapshot is not None else lines

        def read_words_ignoring_member_access(code_fragment: str) -> set[str]:
            reads: set[str] = set()
            for match in re.finditer(r"\b\w+\b", code_fragment, re.IGNORECASE):
                if match.start() > 0 and code_fragment[match.start() - 1] == ".":
                    continue
                reads.add(match.group(0).casefold())
            return reads

        def read_names_by_line(raw_line: str) -> set[str]:
            if not raw_line.strip():
                return set()
            code_no_comments = strip_inline_comment_preserve_strings_fn(raw_line)
            code_clean = bsl007_strip_double_quoted_segments_fn(code_no_comments)
            match = bsl007_simple_assign_at_start_re.match(code_clean)
            if match:
                tail = code_clean[match.end() :]
                return read_words_ignoring_member_access(tail)
            return read_words_ignoring_member_access(code_clean)

        line_read_names = [read_names_by_line(line) for line in code_lines]
        file_read_counts: Counter[str] = Counter()
        for names in line_read_names:
            file_read_counts.update(names)

        module_declared_cf: set[str] = set()
        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            m_decl = var_local_re.match(line)
            if not m_decl:
                continue
            module_declared_cf.update(
                n.strip().casefold() for n in m_decl.group("names").split(",") if n.strip()
            )

        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if region_line_re.match(line) or preproc_line_re.match(line):
                continue
            if compiler_directive_re.match(stripped):
                continue
            match = module_assign_re.match(line)
            if not match:
                continue
            var_name = match.group(1)
            if file_read_counts.get(var_name.casefold(), 0) > 0:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=line.find(var_name) if var_name in line else 0,
                    end_line=idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.WARNING,
                    code="BSL007",
                    message=f"Удалите неиспользуемую переменную {var_name}",
                )
            )

        for proc in procs:
            proc_lines = lines[proc.start_idx : proc.end_idx + 1]
            param_cf = {p.casefold() for p in proc.params}
            emitted: set[tuple[int, str]] = set()
            declared: list[tuple[str, int]] = []
            decl_rel_indices: set[int] = set()
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                m = var_local_re.match(pline)
                if not m:
                    continue
                decl_rel_indices.add(rel_idx)
                for var_name in (n.strip() for n in m.group("names").split(",") if n.strip()):
                    declared.append((var_name, rel_idx))

            declared_cf = {n.casefold() for n, _ in declared}
            body_lo = proc.start_idx + 1
            body_hi = proc.end_idx - 1
            proc_read_counts: Counter[str] = Counter()
            for abs_idx in range(max(body_lo, 0), min(body_hi, len(lines) - 1) + 1):
                for read_name in line_read_names[abs_idx]:
                    proc_read_counts[read_name] += 1

            def emit_unused(
                abs_line: int,
                var_name: str,
                emitted_local: set[tuple[int, str]] = emitted,
            ) -> None:
                key = (abs_line, var_name.casefold())
                if key in emitted_local:
                    return
                emitted_local.add(key)
                char_pos = lines[abs_line].find(var_name) if var_name in lines[abs_line] else 0
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=abs_line + 1,
                        character=char_pos,
                        end_line=abs_line + 1,
                        end_character=char_pos + len(var_name),
                        severity=Severity.WARNING,
                        code="BSL007",
                        message=f"Удалите неиспользуемую переменную {var_name}",
                    )
                )

            for var_name, rel_idx in declared:
                abs_decl = proc.start_idx + rel_idx
                uses = proc_read_counts.get(var_name.casefold(), 0) - (
                    1 if var_name.casefold() in line_read_names[abs_decl] else 0
                )
                if uses > 0:
                    continue
                emit_unused(abs_decl, var_name)

            implicit_first_unused: dict[str, tuple[str, int]] = {}
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                match = module_assign_re.match(pline)
                if not match:
                    continue
                var_name = match.group(1)
                var_cf = var_name.casefold()
                if var_cf in param_cf or var_cf in declared_cf or var_cf in module_declared_cf:
                    continue
                if rel_idx in decl_rel_indices:
                    continue
                if proc_read_counts.get(var_cf, 0) > 0:
                    continue
                implicit_first_unused.setdefault(var_cf, (var_name, abs_line))
            for var_name, abs_line in sorted(
                implicit_first_unused.values(), key=lambda item: item[1]
            ):
                emit_unused(abs_line, var_name)

            loop_headers_by_var: dict[str, set[int]] = {}
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                m_for = re_for_index_header.match(pline)
                if m_for:
                    loop_headers_by_var.setdefault(m_for.group(1).casefold(), set()).add(abs_line)

            emitted_loop_vars: set[str] = set()
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                m_for = re_for_index_header.match(pline)
                if not m_for:
                    continue
                var_name = m_for.group(1)
                var_cf = var_name.casefold()
                if var_cf in param_cf or var_cf in emitted_loop_vars:
                    continue
                used = False
                for abs_idx in range(abs_line + 1, min(proc.end_idx, len(lines))):
                    if abs_idx in loop_headers_by_var.get(var_cf, set()):
                        continue
                    if var_cf in line_read_names[abs_idx]:
                        used = True
                        break
                if not used:
                    emit_unused(abs_line, var_name)
                    emitted_loop_vars.add(var_cf)
        return diags

    def validate_bsl051_unreachable_code(
        self,
        *,
        lines: list[str],
        procs: list[ProcInfo],
        tree: Any,
        bsl051_delimiter_lines_for_tree_fn,
        bsl051_all_branch_exit_end_if_lines_fn,
        re_unconditional_exit,
        re_bsl051_delimiter_fallback,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        delimiter_lines = bsl051_delimiter_lines_for_tree_fn(tree)
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
            ) -> None:
                if abs_idx in emitted_lines_local or abs_idx in end_line_idxs:
                    return
                next_indent = len(line) - len(line.lstrip())
                end_abs = abs_idx
                for tail_abs in range(abs_idx + 1, min(proc_end_idx, len(lines))):
                    tail = lines[tail_abs]
                    stripped_tail = tail.strip()
                    if not stripped_tail or stripped_tail.startswith("//"):
                        continue
                    end_abs = tail_abs
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=abs_idx + 1,
                        character=next_indent,
                        end_line=end_abs + 1,
                        end_character=len(lines[end_abs].rstrip()),
                        severity=Severity.ERROR,
                        code="BSL051",
                        message="Исправьте алгоритм, т.к. этот код никогда не будет исполнен",
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
                            if delimiter_lines is not None:
                                is_block_delimiter = next_abs in delimiter_lines
                            else:
                                is_block_delimiter = bool(
                                    re_bsl051_delimiter_fallback.match(next_line)
                                )
                            if not is_block_delimiter:
                                emit_unreachable(next_abs, next_line)
                        break
                    i = j
                    continue
                i += 1

            if_exit_lines = bsl051_all_branch_exit_end_if_lines_fn(body_lines)
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
                        if next_indent <= end_indent and not re_bsl051_delimiter_fallback.match(
                            next_line
                        ):
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
            if "Окр(" in line_text and ", 2)" in line_text:
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
                    message=error["message"],
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
                                    if len(nested_args) > 1:
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
                                            start_char + len(ts_node_text_fn(type_node)),
                                        ),
                                        severity=Severity.INFORMATION,
                                        code="BSL223",
                                        message=(
                                            "Избегайте вложенных конструкторов в объявлении структуры"
                                        ),
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
                                        message=(
                                            "Количество параметров СтрШаблон()/StrTemplate() "
                                            "не соответствует шаблону"
                                        ),
                                    )
                                )

        if {"BSL243", "BSL249"} & enabled_set:
            for idx, line in enumerate(clean_lines):
                if "BSL243" in enabled_set:
                    for m in re.finditer(
                        r"\b(?P<obj>\w+)\s*\.\s*(?:Вставить|Insert|Добавить|Add)\s*\((?P<args>[^)]*)\)",
                        line,
                        re.IGNORECASE,
                    ):
                        obj = m.group("obj").casefold()
                        parts = [part.strip() for part in split_top_level_args_fn(m.group("args"))]
                        relevant = [part for part in parts if part]
                        if any(part.casefold() == obj for part in relevant):
                            start = m.start("obj")
                            diags.append(
                                Diagnostic(
                                    file=self.path,
                                    line=idx + 1,
                                    character=start,
                                    end_line=idx + 1,
                                    end_character=start + len(m.group("obj")),
                                    severity=Severity.ERROR,
                                    code="BSL243",
                                    message="Нельзя вставлять объект в самого себя",
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
                        diags.append(
                            Diagnostic(
                                file=self.path,
                                line=idx + 1,
                                character=m.start(),
                                end_line=idx + 1,
                                end_character=m.end("name"),
                                severity=Severity.ERROR,
                                code="BSL249",
                                message=(
                                    f"Замените конструктор {m.group('name')} на получение элемента стиля"
                                ),
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
        ts_child_of_type_fn,
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
                            message=(
                                "НСтр() не содержит все объявленные языки"
                                if code == "BSL221"
                                else "Не используйте неполную НСтр() внутри СтрШаблон()/StrTemplate()"
                            ),
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
                            message=f'Имя параметра "{param}" входит в список зарезервированных',
                        )
                    )

        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return diags
        line_texts = lines
        if "BSL271" in enabled_set:
            for node in ts_walk_fn(root):
                if getattr(node, "type", None) != "new_expression":
                    continue
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
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=start_char,
                        end_line=line_idx + 1,
                        end_character=min(len(line_text), start_char + len(type_name)),
                        severity=Severity.ERROR,
                        code="BSL271",
                        message=f'Объект "{type_name}" недоступен на Linux/Unix без платформенной проверки',
                    )
                )
        return diags
