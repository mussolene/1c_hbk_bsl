from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo


@dataclass(frozen=True, slots=True)
class ModuleModel:
    path: str

    def validate_hardcoded_credentials(self, lines: list[str], *, credentials_re) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = credentials_re.search(line)
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
                    code="BSL012",
                    message=f"Possible hardcoded credential: {m.group()!r}",
                )
            )
        return diags

    def validate_commented_code(
        self,
        lines: list[str],
        *,
        commented_code_re,
        min_commented_code_block: int,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        consecutive = 0
        start_line = 0
        in_query_comment = False
        for idx, line in enumerate(lines):
            comment_text = ""
            if line.lstrip().startswith("//"):
                comment_text = line.lstrip()[2:].strip()
            is_query_comment = bool(
                comment_text
                and re.match(
                    r"^(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|ПОМЕСТИТЬ|КАК|И\b|ИЛИ\b)",
                    comment_text,
                    re.IGNORECASE,
                )
            )
            if commented_code_re.match(line) or (in_query_comment and line.lstrip().startswith("//")):
                if consecutive == 0:
                    start_line = idx
                consecutive += 1
                in_query_comment = in_query_comment or is_query_comment
            else:
                if consecutive >= min_commented_code_block:
                    report_start = start_line
                    while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                        report_start -= 1
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=report_start + 1,
                            character=1,
                            end_line=idx,
                            end_character=0,
                            severity=Severity.INFORMATION,
                            code="BSL013",
                            message="Программные модули не должны иметь закомментированных фрагментов кода",
                        )
                    )
                consecutive = 0
                in_query_comment = False
        if consecutive >= min_commented_code_block:
            report_start = start_line
            while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                report_start -= 1
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=report_start + 1,
                    character=1,
                    end_line=len(lines),
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL013",
                    message="Программные модули не должны иметь закомментированных фрагментов кода",
                )
            )
        return diags

    def validate_line_too_long(
        self,
        lines: list[str],
        *,
        max_line_length: int,
        snapshot,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        reported_lengths: list[int] | None = None
        if snapshot is not None:
            reported_lengths = []
            raw_line_source: list[str]
            if "\r" not in snapshot.content and Path(self.path).is_file():
                try:
                    raw_line_source = [
                        raw.decode("utf-8", errors="ignore")
                        for raw in Path(self.path).read_bytes().splitlines(True)
                    ]
                except OSError:
                    raw_line_source = snapshot.content.splitlines(True)
                if len(raw_line_source) != len(snapshot.content.splitlines()):
                    raw_line_source = snapshot.content.splitlines(True)
            else:
                raw_line_source = snapshot.content.splitlines(True)
            for raw in raw_line_source:
                raw_no_lf = raw.rstrip("\n")
                raw_no_eol = raw_no_lf.rstrip("\r")
                if raw_no_lf.endswith("\r"):
                    visible_len = len(raw_no_eol.rstrip("\t"))
                else:
                    visible_len = len(raw_no_eol.rstrip())
                reported_lengths.append(visible_len)
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("|"):
                content = line.lstrip()[1:].lstrip()
                if re.search(
                    r"\b(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|КАК|AS|ЗНАЧЕНИЕ|VALUE|ВЫРАЗИТЬ|CAST|СОЕДИНЕНИЕ|JOIN)\b",
                    content,
                    re.IGNORECASE,
                ):
                    continue
                if len(line.rstrip()) <= 140:
                    continue
            length = len(line.rstrip())
            reported_length = (
                reported_lengths[idx]
                if reported_lengths is not None and idx < len(reported_lengths)
                else length
            )
            if reported_length <= max_line_length:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=0,
                    end_line=idx + 1,
                    end_character=length,
                    severity=Severity.INFORMATION,
                    code="BSL014",
                    message=(
                        f"Длина строки {reported_length} превышает максимально допустимую "
                        f"{max_line_length}"
                    ),
                )
            )
        return diags

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
        for idx, line in enumerate(lines):
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
                    end_character=len(line),
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
                    end_character=m.end("names"),
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

    def validate_non_standard_regions(
        self,
        lines: list[str],
        *,
        regions: list[RegionInfo],
        standard_regions_for_path,
        is_standard_region_name_for_path,
    ) -> list[Diagnostic]:
        allowed = standard_regions_for_path(self.path)
        if not allowed or not regions:
            return []
        diags: list[Diagnostic] = []
        for region in regions:
            if is_standard_region_name_for_path(self.path, region.name):
                continue
            line_idx = region.start_idx
            line_text = lines[line_idx] if line_idx < len(lines) else ""
            start_char = 1 if line_text.startswith("#") else 0
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx + 1,
                    character=start_char,
                    end_line=line_idx + 1,
                    end_character=len(line_text),
                    severity=Severity.INFORMATION,
                    code="BSL016",
                    message=f'Нужно удалить нестандартный раздел "{region.name}"',
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

    def validate_empty_regions(
        self,
        lines: list[str],
        *,
        regions: list[RegionInfo],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        code_re = re.compile(
            r"^\s*(?!//|#(?:Область|Region|КонецОбласти|EndRegion))\S",
            re.IGNORECASE,
        )
        for region in regions:
            has_code = False
            for i in range(region.start_idx + 1, min(region.end_idx, len(lines))):
                if code_re.match(lines[i]):
                    has_code = True
                    break
            if has_code:
                continue
            line_idx = region.start_idx
            line_text = lines[line_idx] if line_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line_idx + 1,
                    character=0,
                    end_line=line_idx + 1,
                    end_character=len(line_text),
                    severity=Severity.INFORMATION,
                    code="BSL026",
                    message=f'Область "{region.name}" не содержит функций или процедур',
                )
            )
        return diags

    def validate_header_semicolon(self, lines: list[str], *, header_semicolon_re) -> list[Diagnostic]:
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
                re.fullmatch(r"(?:ЭтаФорма|ThisForm)", param, re.IGNORECASE) for param in proc.params
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

    def validate_duplicate_regions(
        self,
        lines: list[str],
        *,
        regions: list[RegionInfo],
    ) -> list[Diagnostic]:
        def normalize(name: str) -> str:
            raw = re.sub(r"\s+", "", name).casefold()
            aliases = {
                "программныйинтерфейс": "public",
                "публичный": "public",
                "public": "public",
                "служебныйпрограммныйинтерфейс": "internal",
                "служебный": "internal",
                "internal": "internal",
                "служебныепроцедурыифункции": "private",
                "приватный": "private",
                "private": "private",
                "обработчикисобытий": "eventhandlers",
                "eventhandlers": "eventhandlers",
                "обработчикисобытийформы": "formeventhandlers",
                "formeventhandlers": "formeventhandlers",
            }
            return aliases.get(raw, raw)

        standard_aliases = {
            "public",
            "internal",
            "private",
            "eventhandlers",
            "formeventhandlers",
        }

        def region_is_effectively_empty(region: RegionInfo) -> bool:
            for line_idx in range(region.start_idx + 1, min(region.end_idx, len(lines))):
                stripped = lines[line_idx].strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                    continue
                return False
            return True

        diags: list[Diagnostic] = []
        seen: dict[str, RegionInfo] = {}
        for region in regions:
            key = normalize(region.name)
            if not key:
                continue
            if key not in seen:
                seen[key] = region
                continue
            prev = seen[key]
            if key not in standard_aliases and not region_is_effectively_empty(prev):
                seen[key] = region
                continue
            line = lines[region.start_idx] if 0 <= region.start_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=region.start_idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=region.start_idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.INFORMATION,
                    code="BSL131",
                    message=f'Нужно удалить дубли раздела "{region.name}"',
                )
            )
            seen[key] = region
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
                        message="Использование ПЕРВЫЕ/TOP без УПОРЯДОЧИТЬ/ORDER BY в запросе",
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
        header_start_re = re.compile(r"^\s*(?:Процедура|Функция|Procedure|Function)\b", re.IGNORECASE)
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
                paren_balance = max(0, paren_balance + code_masked.count("(") - code_masked.count(")"))
                last_char = code_part[-1]
                if last_char in (";", ",", "(", "|", "+", "-", "*", "/", "="):
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
            if not code_part or code_part.endswith(";"):
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
        code_lines_wo_comments = snapshot.code_lines_without_comments if snapshot is not None else None
        for scope_lines in scope_line_indices_fn(lines, procs):
            counts: Counter[str] = Counter()
            positions: dict[str, list[tuple[int, int]]] = {}
            for idx in scope_lines:
                line = code_lines_wo_comments[idx] if code_lines_wo_comments is not None else lines[idx]
                if line.strip().startswith("//"):
                    continue
                for m in string_literal_re.finditer(line):
                    val = m.group(1).strip()
                    if not val:
                        continue
                    if re.search(r"\b(?:НСтр|NStr)\s*\([^)]*$", line[: m.start()], re.IGNORECASE):
                        continue
                    if re.fullmatch(r"\+\s*\w+\s*\+", val):
                        continue
                    counts[val] += 1
                    positions.setdefault(val, []).append((idx + 1, m.start()))
            for val, count in counts.items():
                if count < min_duplicate_uses:
                    continue
                pos_list = positions[val]
                if all(line_starts_with_raise_statement_fn(lines[ln - 1]) for ln, _ in pos_list):
                    continue
                line_no, col = pos_list[0]
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

    def validate_function_paths_return(self, *, tree, bsl148_function_name_spans, loops_executed_at_least_once: bool) -> list[Diagnostic]:
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
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character_fn(line_text, node.start_point[1]),
                        end_line=line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character_fn(line_text, node.end_point[1]),
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=rule_descriptions_ru["BSL171"],
                    )
                )
        if diags:
            return diags
        for idx, line in enumerate(lines):
            match = adjacent_literals_re.search(line)
            if match is not None:
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
                end_character = min(len(line.rstrip()), len(line) - len(cur) + len(cur.split('"', 2)[1]) + 2)
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

    def validate_invalid_character_in_file(self, *, lines: list[str], illegal_chars: dict[str, str]) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for line_idx, line in enumerate(lines, start=1):
            hit = next(((pos, illegal_chars[ch]) for pos, ch in enumerate(line) if ch in illegal_chars), None)
            if hit is None:
                continue
            pos, message = hit
            quote_pos = line.rfind('"', 0, pos + 1)
            anchor = quote_pos if quote_pos >= 0 else len(line) - len(line.lstrip())
            end_character = len(line.rstrip())
            closing_paren = line.rfind(")")
            if closing_paren > anchor:
                end_character = closing_paren
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

        def if_condition_chunk(idx: int) -> str | None:
            line = lines[idx]
            if line.strip().startswith("//"):
                return None
            if not re_if_or_elseif_line.match(line):
                return None
            if re_then_word.search(line):
                return line
            parts = [line]
            j = idx + 1
            max_j = min(len(lines), idx + 48)
            while j < max_j:
                parts.append(lines[j])
                if re_then_word.search(lines[j]):
                    break
                j += 1
            return "\n".join(parts)

        def line_triggers(idx: int) -> bool:
            chunk = if_condition_chunk(idx)
            if chunk is None:
                return False
            return len(bool_op_re.findall(chunk)) + 1 > max_bool_ops

        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not line_triggers(idx):
                continue
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
                    end_line=idx + 1,
                    end_character=char + 1,
                    severity=Severity.INFORMATION,
                    code="BSL036",
                    message="Выделите условие оператора Если в отдельный метод или переменную",
                )
            )
        return diags

    def validate_form_data_to_value(self, *, lines: list[str], line_comment_re, double_quoted_string_re, bsl190_form_data_re) -> list[Diagnostic]:
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
                    severity=Severity.WARNING,
                    code="BSL190",
                    message=(
                        "ДанныеФормыВЗначение()/FormDataToValue() — медленная операция; "
                        "работайте с серверными объектами напрямую"
                    ),
                )
            )
        return diags

    def validate_missing_space(
        self,
        *,
        lines: list[str],
        snapshot,
        line_comment_re,
        build_line_string_states_fn,
        mask_double_quoted_strings_preserve_len_fn,
        comment_start_outside_double_quotes_fn,
        strip_inline_comment_preserve_strings_fn,
        proc_header_re,
        any_keyword_re,
        arithmetic_missing_space_cols_in_line_fn,
        comma_missing_space_after_cols_in_line_fn,
        semicolon_nospace_re,
        left_right_keywords_re,
        left_keywords_re,
        right_keywords_re,
    ) -> list[Diagnostic]:
        comparison_ops = ("<=", ">=", "<>", "=", "<", ">")
        diags: list[Diagnostic] = []
        str_states = snapshot.line_string_states if snapshot is not None else build_line_string_states_fn(lines)
        masked_lines = (
            snapshot.masked_lines
            if snapshot is not None
            else [line if str_states[idx] else mask_double_quoted_strings_preserve_len_fn(line) for idx, line in enumerate(lines)]
        )
        comment_starts = (
            snapshot.comment_starts
            if snapshot is not None
            else [comment_start_outside_double_quotes_fn(line, str_states[idx]) for idx, line in enumerate(lines)]
        )
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [strip_inline_comment_preserve_strings_fn(line) for line in lines]
        )
        for idx, line in enumerate(lines):
            if line_comment_re.match(line):
                continue
            in_str_start = str_states[idx]
            clean_full = masked_lines[idx]
            clean = clean_full
            comment_pos = comment_starts[idx]
            if comment_pos is not None:
                clean = clean[:comment_pos]
            has_equals = "=" in clean
            has_arithmetic_ops = any(op in line for op in "+-*/%")
            code_no_comments = code_lines_wo_comments[idx]
            has_comma = "," in code_no_comments
            has_semicolon = ";" in clean
            has_keyword_candidate = bool(any_keyword_re.search(clean))
            if has_equals and not proc_header_re.match(clean):
                pos = 0
                seen_ops: set[tuple[int, str]] = set()
                while pos < len(clean):
                    op = None
                    for candidate in comparison_ops:
                        if clean.startswith(candidate, pos):
                            op = candidate
                            break
                    if op is None:
                        pos += 1
                        continue
                    start = pos
                    end = pos + len(op)
                    if op == "=" and ((start > 0 and clean[start - 1] in "<>!") or (end < len(clean) and clean[end] == "=")):
                        pos += 1
                        continue
                    left_missing = start > 0 and clean[start - 1] not in " \t"
                    right_missing = end < len(clean) and clean[end] not in " \t"
                    if left_missing or right_missing:
                        key = (start, op)
                        if key not in seen_ops:
                            seen_ops.add(key)
                            if left_missing and right_missing:
                                msg = f"Слева и справа от '{op}' не хватает пробела"
                            elif left_missing:
                                msg = f"Слева от '{op}' не хватает пробела"
                            else:
                                msg = f"Справа от '{op}' не хватает пробела"
                            diags.append(Diagnostic(file=self.path, line=idx + 1, character=start, end_line=idx + 1, end_character=end, severity=Severity.INFORMATION, code="BSL216", message=msg))
                    pos = end
            if has_arithmetic_ops:
                for col in arithmetic_missing_space_cols_in_line_fn(line, in_str_start):
                    op = line[col]
                    left_missing = col > 0 and line[col - 1] not in " \t"
                    right_missing = col + 1 < len(line) and line[col + 1] not in " \t"
                    if left_missing and right_missing:
                        msg = f"Слева и справа от '{op}' не хватает пробела"
                    elif left_missing:
                        msg = f"Слева от '{op}' не хватает пробела"
                    else:
                        msg = f"Справа от '{op}' не хватает пробела"
                    diags.append(Diagnostic(file=self.path, line=idx + 1, character=col, end_line=idx + 1, end_character=col + 1, severity=Severity.INFORMATION, code="BSL216", message=msg))
                continue
            comma_cols = comma_missing_space_after_cols_in_line_fn(code_no_comments) if has_comma else []
            if has_comma:
                extra_comma_cols = {m.start() for m in re.finditer(r",(?=\))", code_no_comments)}
                if extra_comma_cols:
                    comma_cols = sorted(set(comma_cols) | extra_comma_cols)
            if comma_cols:
                for comma_col in comma_cols:
                    diags.append(Diagnostic(file=self.path, line=idx + 1, character=comma_col, end_line=idx + 1, end_character=comma_col + 1, severity=Severity.INFORMATION, code="BSL216", message=("Справа от ',' не хватает пробела")))
                continue
            m_semicolon = semicolon_nospace_re.search(clean) if has_semicolon else None
            if m_semicolon is None and has_semicolon and comment_pos is not None and comment_pos > 0 and clean_full[comment_pos - 1] == ";" and clean_full[comment_pos : comment_pos + 2] == "//":
                semicolon_col = comment_pos - 1
                diags.append(Diagnostic(file=self.path, line=idx + 1, character=semicolon_col, end_line=idx + 1, end_character=semicolon_col + 1, severity=Severity.INFORMATION, code="BSL216", message=("Справа от ';' не хватает пробела")))
                continue
            if m_semicolon:
                diags.append(Diagnostic(file=self.path, line=idx + 1, character=m_semicolon.start(), end_line=idx + 1, end_character=m_semicolon.end(), severity=Severity.INFORMATION, code="BSL216", message=("Справа от ';' не хватает пробела")))
                continue
            if has_keyword_candidate:
                for m_kw in left_right_keywords_re.finditer(clean):
                    start = m_kw.start(1)
                    end = m_kw.end(1)
                    left_missing = start > 0 and clean[start - 1] not in " \t"
                    right_missing = end < len(clean) and clean[end] not in " \t"
                    if not left_missing and not right_missing:
                        continue
                    kw = line[start:end]
                    if left_missing and right_missing:
                        msg = f"Слева и справа от '{kw}' не хватает пробела"
                    elif left_missing:
                        msg = f"Слева от '{kw}' не хватает пробела"
                    else:
                        msg = f"Справа от '{kw}' не хватает пробела"
                    diags.append(Diagnostic(file=self.path, line=idx + 1, character=start, end_line=idx + 1, end_character=end, severity=Severity.INFORMATION, code="BSL216", message=msg))
                for m_kw in left_keywords_re.finditer(clean):
                    start = m_kw.start(1)
                    end = m_kw.end(1)
                    if start <= 0 or clean[start - 1] in " \t":
                        continue
                    kw = line[start:end]
                    diags.append(Diagnostic(file=self.path, line=idx + 1, character=start, end_line=idx + 1, end_character=end, severity=Severity.INFORMATION, code="BSL216", message=(f"Слева от '{kw}' не хватает пробела")))
                for m_kw in right_keywords_re.finditer(clean):
                    start = m_kw.start(1)
                    end = m_kw.end(1)
                    if end >= len(clean) or clean[end] in " \t":
                        continue
                    kw = line[start:end]
                    diags.append(Diagnostic(file=self.path, line=idx + 1, character=start, end_line=idx + 1, end_character=end, severity=Severity.INFORMATION, code="BSL216", message=(f"Справа от '{kw}' не хватает пробела")))
        return diags

    def validate_ternary_operator_usage(self, *, lines: list[str], tree, ternary_nodes, ts_walk_fn, utf8_byte_offset_to_lsp_character_fn, rule_descriptions_ru: dict[str, str]) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in ternary_nodes if ternary_nodes is not None else ts_walk_fn(tree.root_node):
            if getattr(node, "type", None) != "ternary_expression":
                continue
            line_idx = node.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(Diagnostic(file=self.path, line=line_idx + 1, character=utf8_byte_offset_to_lsp_character_fn(line_text, node.start_point[1]), end_line=line_idx + 1, end_character=utf8_byte_offset_to_lsp_character_fn(line_text, node.end_point[1]), severity=Severity.INFORMATION, code="BSL251", message=rule_descriptions_ru["BSL251"]))
        return diags

    def validate_this_object_assign(self, *, path: str, lines: list[str], tree, assignment_nodes, path_is_likely_form_module_bsl, common_module_path_re, ts_walk_fn, ts_child_of_type_fn, ts_node_text_fn, utf8_byte_offset_to_lsp_character_fn, rule_descriptions_ru: dict[str, str]) -> list[Diagnostic]:
        low = path.replace("\\", "/").lower()
        if not (path_is_likely_form_module_bsl(path) or common_module_path_re.search(low)):
            return []
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in assignment_nodes if assignment_nodes is not None else ts_walk_fn(tree.root_node):
            if getattr(node, "type", None) != "assignment_statement":
                continue
            ident = ts_child_of_type_fn(node, "identifier")
            if ident is None:
                continue
            if ts_node_text_fn(ident).casefold() not in {"этотобъект", "thisobject"}:
                continue
            line_idx = ident.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(Diagnostic(file=self.path, line=line_idx + 1, character=utf8_byte_offset_to_lsp_character_fn(line_text, ident.start_point[1]), end_line=line_idx + 1, end_character=utf8_byte_offset_to_lsp_character_fn(line_text, ident.end_point[1]), severity=Severity.ERROR, code="BSL252", message=rule_descriptions_ru["BSL252"]))
        return diags

    def validate_unknown_preprocessor_symbol(self, *, lines: list[str], tree, preprocessor_nodes, ts_walk_fn, ts_child_of_type_fn, ts_node_text_fn, utf8_byte_offset_to_lsp_character_fn, allowed_preproc_symbols: set[str], preproc_keywords: set[str], preproc_if_re, preproc_identifier_re) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in (preprocessor_nodes if preprocessor_nodes is not None else ts_walk_fn(tree.root_node)):
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
                    diags.append(Diagnostic(file=self.path, line=line_idx + 1, character=utf8_byte_offset_to_lsp_character_fn(line_text, child.start_point[1]), end_line=line_idx + 1, end_character=utf8_byte_offset_to_lsp_character_fn(line_text, child.end_point[1]), severity=Severity.WARNING, code="BSL259", message=f'Неизвестный символ препроцессора "{name}"'))
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
                diags.append(Diagnostic(file=self.path, line=idx + 1, character=ident.start(), end_line=idx + 1, end_character=ident.end(), severity=Severity.WARNING, code="BSL259", message=f'Неизвестный символ препроцессора "{name}"'))
        return diags

    def validate_using_find_element_by_string(self, *, lines: list[str], tree, method_call_nodes, ts_walk_fn, ts_child_of_type_fn, ts_node_text_fn, ts_method_call_arg_exprs_fn, utf8_byte_offset_to_lsp_character_fn, method_name_re, line_comment_re, mask_double_quoted_strings_preserve_len_fn) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        target_names = {"найтипонаименованию", "findbydescription", "найтипокоду", "findbycode", "найтипономеру", "findbynumber"}
        if tree is not None:
            for node in method_call_nodes if method_call_nodes is not None else ts_walk_fn(tree.root_node):
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
                    if arg_text and not ((arg_text.startswith('"') and arg_text.endswith('"')) or re.fullmatch(r"\d+(?:\.\d+)?", arg_text)):
                        continue
                line_idx = ident.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(Diagnostic(file=self.path, line=line_idx + 1, character=utf8_byte_offset_to_lsp_character_fn(line_text, ident.start_point[1]), end_line=line_idx + 1, end_character=utf8_byte_offset_to_lsp_character_fn(line_text, ident.end_point[1]), severity=Severity.WARNING, code="BSL268", message=f'Использование метода "{name}" снижает производительность поиска'))
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
            diags.append(Diagnostic(file=self.path, line=idx + 1, character=match.start("name"), end_line=idx + 1, end_character=match.end("name"), severity=Severity.WARNING, code="BSL268", message=f'Использование метода "{match.group("name")}" снижает производительность поиска'))
        return diags
