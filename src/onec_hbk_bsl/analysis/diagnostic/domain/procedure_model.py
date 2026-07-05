from __future__ import annotations

import re
from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo


def _bsl065_return_entry_is_valid(text: str) -> bool:
    if text.startswith("*"):
        return False
    if re.match(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*\.$", text):
        return False
    return True


@dataclass(frozen=True, slots=True)
class ProcedureModel:
    path: str
    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    header_col: int
    params: tuple[str, ...]
    optional_count: int
    optional_params: frozenset[str]
    params_start_idx: int | None = None
    params_start_character: int | None = None
    params_end_idx: int | None = None
    params_end_character: int | None = None
    param_ranges: tuple[tuple[str, int, int, int, int], ...] = ()

    @classmethod
    def from_proc_info(cls, path: str, proc: ProcInfo) -> ProcedureModel:
        return cls(
            path=path,
            name=proc.name,
            kind=proc.kind,
            start_idx=proc.start_idx,
            end_idx=proc.end_idx,
            is_export=proc.is_export,
            header_col=proc.header_col,
            params=tuple(proc.params),
            optional_count=proc.optional_count,
            optional_params=proc.optional_params,
            params_start_idx=proc.params_start_idx,
            params_start_character=proc.params_start_character,
            params_end_idx=proc.params_end_idx,
            params_end_character=proc.params_end_character,
            param_ranges=proc.param_ranges,
        )

    def _param_list_range(self, lines: list[str]) -> tuple[int, int, int, int]:
        if (
            self.params_start_idx is not None
            and self.params_start_character is not None
            and self.params_end_idx is not None
            and self.params_end_character is not None
        ):
            return (
                self.params_start_idx + 1,
                self.params_start_character,
                self.params_end_idx + 1,
                self.params_end_character,
            )
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        character = line_text.find("(")
        if character < 0:
            character = self.header_col
        else:
            character += 1
        end_character = line_text.rfind(")")
        if end_character < character:
            end_character = len(line_text.rstrip())
        return self.start_idx + 1, character, self.start_idx + 1, end_character

    def validate_param_limit(self, lines: list[str], *, max_params: int) -> list[Diagnostic]:
        total = len(self.params)
        if total <= max_params:
            return []
        line, character, end_line, end_character = self._param_list_range(lines)
        return [
            Diagnostic(
                file=self.path,
                line=line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                severity=Severity.INFORMATION,
                code="BSL031",
            )
        ]

    def validate_optional_param_limit(
        self, lines: list[str], *, max_optional_params: int
    ) -> list[Diagnostic]:
        if self.optional_count <= max_optional_params:
            return []
        line, character, end_line, end_character = self._param_list_range(lines)
        return [
            Diagnostic(
                file=self.path,
                line=line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                severity=Severity.INFORMATION,
                code="BSL015",
            )
        ]

    def validate_method_size(
        self,
        lines: list[str],
        *,
        max_proc_lines: int,
        mask_strings_and_comments_for_counter,
        proc_name_span,
    ) -> list[Diagnostic]:
        body_start_idx = self.start_idx + 1
        header_balance = 0
        for idx in range(self.start_idx, min(self.end_idx, len(lines))):
            header_part = mask_strings_and_comments_for_counter(lines[idx], False)
            header_balance += header_part.count("(") - header_part.count(")")
            if header_balance <= 0 and ")" in header_part:
                body_start_idx = idx + 1
                break
        first_body: int | None = None
        last_body: int | None = None
        for idx in range(body_start_idx, min(self.end_idx, len(lines))):
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                continue
            if first_body is None:
                first_body = idx
            last_body = idx
        length = 0 if first_body is None or last_body is None else last_body - first_body
        if length <= max_proc_lines:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL002",
            )
        ]

    def validate_max_returns(
        self, lines: list[str], *, max_returns: int, return_re, proc_name_span
    ) -> list[Diagnostic]:
        proc_body = "\n".join(lines[self.start_idx : self.end_idx + 1])
        returns = list(return_re.finditer(proc_body))
        if len(returns) <= max_returns:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col or len(line_text),
                severity=Severity.WARNING,
                code="BSL008",
            )
        ]

    def validate_function_has_return(
        self,
        lines: list[str],
        *,
        return_re,
        proc_name_span,
    ) -> list[Diagnostic]:
        if self.kind != "function":
            return []
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        has_return = any(return_re.match(line) for line in body_lines)
        if has_return:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col or len(line_text),
                severity=Severity.ERROR,
                code="BSL032",
            )
        ]

    def validate_empty_export_method(
        self,
        lines: list[str],
        *,
        blank_or_comment_re,
    ) -> list[Diagnostic]:
        if not self.is_export:
            return []
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        has_code = any(line.strip() and not blank_or_comment_re.match(line) for line in body_lines)
        if has_code:
            return []
        header = lines[self.start_idx] if self.start_idx < len(lines) else ""
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(header),
                severity=Severity.WARNING,
                code="BSL042",
            )
        ]

    def validate_non_export_in_api_regions(
        self,
        lines: list[str],
        *,
        regions: list[RegionInfo],
        api_region_names: set[str],
        proc_name_span,
    ) -> list[Diagnostic]:
        if self.is_export:
            return []
        for region in regions:
            if region.name.lower() not in api_region_names:
                continue
            if not (region.start_idx < self.start_idx < region.end_idx):
                continue
            line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
            start_char, end_char = proc_name_span(lines, self._to_proc_info())
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=start_char,
                    end_line=self.start_idx + 1,
                    end_character=end_char or len(line_text),
                    severity=Severity.WARNING,
                    code="BSL003",
                )
            ]
        return []

    def validate_missing_export_comment(
        self,
        lines: list[str],
        *,
        compiler_directive_re,
        bsl215_comment_line_re,
    ) -> list[Diagnostic]:
        block_end = self.start_idx - 1
        while block_end >= 0 and compiler_directive_re.match(lines[block_end]):
            block_end -= 1
        if block_end < 0 or not bsl215_comment_line_re.match(lines[block_end]):
            return []
        block_start = block_end
        while block_start > 0 and bsl215_comment_line_re.match(lines[block_start - 1]):
            block_start -= 1
        comment_block = lines[block_start : block_end + 1]
        legacy_doc_path = bool(re.search(r"(?:ManagerModule|ObjectModule)\.bsl$", str(self.path)))
        if legacy_doc_path:
            comment_block = [
                re.sub(r"^(\s*//)\t ?", r"\1  ", cl).replace("\t", " ") for cl in comment_block
            ]
        if any(re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE) for cl in comment_block):
            return []
        if len(comment_block) == 1:
            text = re.sub(r"^\s*//\s*", "", comment_block[0]).strip()
            if re.match(r"^(?:Конец|End)\b", text, re.IGNORECASE):
                return []

        returns_section_start = None
        inline_return_text = ""
        for ci, cl in enumerate(comment_block):
            section_match = re.match(
                r"^\s*//\s*(?:Возвращаемое\s+значение|Returns)\s*(?P<sep>:|-|–)?\s*(?P<text>.*)$",
                cl,
                re.IGNORECASE,
            )
            if section_match:
                returns_section_start = ci
                inline_return_text = section_match.group("text").strip()
                break

        has_valid_return_entry = False
        if returns_section_start is not None:
            if inline_return_text:
                has_valid_return_entry = _bsl065_return_entry_is_valid(inline_return_text)
            return_section_lines = comment_block[returns_section_start + 1 :]
            for cl in return_section_lines:
                if has_valid_return_entry:
                    break
                stripped = cl.strip()
                if stripped == "//":
                    break
                if re.match(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", cl, re.IGNORECASE):
                    break
                if re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE):
                    has_valid_return_entry = True
                    break
                entry = re.match(r"^\s*//[ \t]{1,4}(?P<text>\S.*)$", cl)
                if not entry:
                    continue
                text = entry.group("text").strip()
                has_valid_return_entry = _bsl065_return_entry_is_valid(text)
                if has_valid_return_entry:
                    break

        header_line = lines[self.start_idx] if self.start_idx < len(lines) else ""
        try:
            col = header_line.index(self.name)
        except ValueError:
            col = 0
        if self.kind == "procedure" and returns_section_start is not None:
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=col,
                    end_line=self.start_idx + 1,
                    end_character=col + len(self.name),
                    severity=Severity.WARNING,
                    code="BSL065",
                )
            ]
        if self.kind == "function" and (
            returns_section_start is None or not has_valid_return_entry
        ):
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=col,
                    end_line=self.start_idx + 1,
                    end_character=col + len(self.name),
                    severity=Severity.WARNING,
                    code="BSL065",
                )
            ]
        return []

    def validate_unused_parameters(
        self,
        lines: list[str],
        *,
        used_casefold: set[str] | None,
    ) -> list[Diagnostic]:
        if not self.params or re.fullmatch(
            r"(?:ПриСозданииОбъекта|OnObjectCreate)", self.name, re.IGNORECASE
        ):
            return []
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        if not any(line.strip() and not line.lstrip().startswith("//") for line in body_lines):
            return []
        body_text: str | None = None
        diags: list[Diagnostic] = []

        for param_name in self.params:
            if not param_name:
                continue
            if used_casefold is not None:
                is_used = param_name.casefold() in used_casefold
            else:
                if body_text is None:
                    body_text = "\n".join(body_lines)
                is_used = bool(
                    re.search(
                        r"\b" + re.escape(param_name) + r"\b",
                        body_text,
                        re.IGNORECASE,
                    )
                )
            if is_used:
                continue
            line, character, end_line, end_character = self._param_name_range(param_name, lines)
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=line,
                    character=character,
                    end_line=end_line,
                    end_character=end_character,
                    severity=Severity.WARNING,
                    code="BSL062",
                )
            )
        return diags

    def _param_name_range(self, param_name: str, lines: list[str]) -> tuple[int, int, int, int]:
        param_casefold = param_name.casefold()
        for name, start_idx, start_character, end_idx, end_character in self.param_ranges:
            if name.casefold() == param_casefold:
                return start_idx + 1, start_character, end_idx + 1, end_character
        header_line = lines[self.start_idx] if self.start_idx < len(lines) else ""
        character = header_line.lower().find(param_name.lower())
        if character < 0:
            character = self.header_col
        return (
            self.start_idx + 1,
            character,
            self.start_idx + 1,
            character + len(param_name),
        )

    def validate_cognitive_complexity(
        self,
        *,
        cognitive_complexity: int,
        max_cognitive_complexity: int,
        proc_name_span,
        lines: list[str],
    ) -> list[Diagnostic]:
        if cognitive_complexity <= max_cognitive_complexity:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL011",
            )
        ]

    def validate_mccabe_complexity(
        self,
        *,
        mccabe_complexity: int,
        max_mccabe_complexity: int,
        proc_name_span,
        lines: list[str],
    ) -> list[Diagnostic]:
        if mccabe_complexity <= max_mccabe_complexity:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL019",
            )
        ]

    def validate_query_in_loop(
        self,
        lines: list[str],
        *,
        loop_lines: set[int] | None,
        loop_open_re,
        loop_close_re,
    ) -> list[Diagnostic]:
        assignment_re = re.compile(
            r"^\s*(?P<name>[\w.]+)\s*=\s*(?P<value>.+?);?\s*$", re.IGNORECASE
        )
        new_query_re = re.compile(
            r"^\s*(?:Новый|New)\s+"
            r"(?P<type>Запрос|Query|ПостроительЗапроса|QueryBuilder|"
            r"ПостроительОтчета|ReportBuilder)\b",
            re.IGNORECASE,
        )
        execute_re = re.compile(
            r"(?P<name>[\w.]+)\.(?:Выполнить|Execute)\s*\([^)]*\)"
            r"(?:\.\w+\s*\([^)]*\))*",
            re.IGNORECASE,
        )
        query_types = {
            "запрос",
            "query",
            "построительзапроса",
            "querybuilder",
            "построительотчета",
            "reportbuilder",
        }
        variable_types: dict[str, set[str]] = {}

        def assignment_type(value: str) -> set[str]:
            new_match = new_query_re.match(value)
            if new_match:
                return {new_match.group("type").casefold()}
            inherited = variable_types.get(value.strip().rstrip(";"))
            return set(inherited or ())

        diags: list[Diagnostic] = []
        loop_depth = 0
        for i in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue

            if loop_lines is not None:
                assign_match = assignment_re.match(line)
                if assign_match:
                    variable_types[assign_match.group("name")] = assignment_type(
                        assign_match.group("value")
                    )
                if i not in loop_lines:
                    continue
                m = execute_re.search(line)
                if m and variable_types.get(m.group("name"), set()) & query_types:
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=m.start(),
                            end_line=i + 1,
                            end_character=m.end(),
                            severity=Severity.WARNING,
                            code="BSL033",
                        )
                    )
                continue
            if loop_open_re.match(line):
                loop_depth += 1
                continue
            if loop_close_re.match(line):
                loop_depth = max(0, loop_depth - 1)
                continue

            assign_match = assignment_re.match(line)
            if assign_match:
                variable_types[assign_match.group("name")] = assignment_type(
                    assign_match.group("value")
                )

            if loop_depth > 0:
                m = execute_re.search(line)
                if m and variable_types.get(m.group("name"), set()) & query_types:
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=m.start(),
                            end_line=i + 1,
                            end_character=m.end(),
                            severity=Severity.WARNING,
                            code="BSL033",
                        )
                    )
        return diags

    def _to_proc_info(self) -> ProcInfo:
        return ProcInfo(
            name=self.name,
            kind=self.kind,
            start_idx=self.start_idx,
            end_idx=self.end_idx,
            is_export=self.is_export,
            params=list(self.params),
            val_params=[],
            optional_count=self.optional_count,
            header_col=self.header_col,
            optional_params=self.optional_params,
            params_start_idx=self.params_start_idx,
            params_start_character=self.params_start_character,
            params_end_idx=self.params_end_idx,
            params_end_character=self.params_end_character,
            param_ranges=self.param_ranges,
        )
