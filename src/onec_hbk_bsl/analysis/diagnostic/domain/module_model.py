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
