from __future__ import annotations

import re
from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo


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
        )

    def validate_param_limit(self, lines: list[str], *, max_params: int) -> list[Diagnostic]:
        total = len(self.params)
        if total <= max_params:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(line_text),
                severity=Severity.WARNING,
                code="BSL031",
                message=(
                    f"{self.kind.capitalize()} '{self.name}' has {total} parameters "
                    f"(maximum {max_params})"
                ),
            )
        ]

    def validate_optional_param_limit(
        self, lines: list[str], *, max_optional_params: int
    ) -> list[Diagnostic]:
        if self.optional_count <= max_optional_params:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(line_text),
                severity=Severity.WARNING,
                code="BSL015",
                message=(
                    f"{self.kind.capitalize()} '{self.name}' has "
                    f"{self.optional_count} optional parameters "
                    f"(maximum {max_optional_params})"
                ),
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
                message=(
                    f'Длина метода "{self.name}" равна {length}, '
                    f"что больше установленного лимита в {max_proc_lines} строк"
                ),
            )
        ]

    def validate_procedure_return_value(
        self,
        lines: list[str],
        *,
        return_value_re,
        proc_header_re,
    ) -> list[Diagnostic]:
        if self.kind != "procedure":
            return []
        header_line = lines[self.start_idx]
        match = proc_header_re.search(header_line)
        if not match:
            return []
        kw = match.group("kw").lower()
        if kw not in ("процедура", "procedure"):
            return []
        for idx in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[idx]
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            if return_value_re.match(line):
                return [
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=len(line) - len(stripped),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL064",
                        message=(
                            "Процедура contains 'Возврат <value>' — "
                            "change the declaration to 'Функция'."
                        ),
                    )
                ]
        return []

    def validate_max_returns(self, lines: list[str], *, max_returns: int, return_re) -> list[Diagnostic]:
        proc_body = "\n".join(lines[self.start_idx : self.end_idx + 1])
        returns = list(return_re.finditer(proc_body))
        if len(returns) <= max_returns:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(line_text),
                severity=Severity.WARNING,
                code="BSL008",
                message=(
                    f"{self.kind.capitalize()} '{self.name}' has {len(returns)} "
                    f"return statements (maximum {max_returns})"
                ),
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
                message='Функция не содержит "Возврат"',
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
                message=(
                    f"Exported {self.kind} '{self.name}' has no body. "
                    "Either implement it or remove the Export keyword."
                ),
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
                    message=(
                        f'Переместите неэкспортный метод "{self.name}" '
                        f'из области "{region.name}"'
                    ),
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
        if any(re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE) for cl in comment_block):
            return []

        returns_section_start = None
        for ci, cl in enumerate(comment_block):
            if re.match(
                r"^\s*//\s*(?:Возвращаемое\s+значение|Returns)\s*:?\s*$",
                cl,
                re.IGNORECASE,
            ):
                returns_section_start = ci
                break

        has_valid_return_entry = False
        if returns_section_start is not None:
            return_section_lines = comment_block[returns_section_start + 1 :]
            has_struct_fields = any(
                re.match(r"^\s*//\s+\*\s+\S", rcl) for rcl in return_section_lines
            )
            for cl in return_section_lines:
                stripped = cl.strip()
                if stripped == "//":
                    break
                if re.match(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", cl, re.IGNORECASE):
                    break
                if re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE):
                    has_valid_return_entry = True
                    break
                entry = re.match(r"^\s*//\s{1,4}(?P<text>\S.*)$", cl)
                if not entry:
                    continue
                text = entry.group("text").strip()
                if text.startswith("*"):
                    if has_struct_fields:
                        continue
                    has_valid_return_entry = True
                    break
                first_part = text.split("-", 1)[0].strip()
                if text.startswith("-") and text.rstrip().endswith("."):
                    continue
                if has_struct_fields and ":" not in first_part and "-" in text:
                    continue
                has_valid_return_entry = True
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
                    message="Удалите описание возвращаемого значения для процедуры",
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
                    message="Добавьте описание возвращаемого значения функции",
                )
            ]
        return []

    def validate_unused_parameters(
        self,
        lines: list[str],
        *,
        used_casefold: set[str] | None,
        skip_standard_params: set[str] | frozenset[str],
        is_typical_client_command_handler,
        is_client_notify_completion_export_handler,
    ) -> list[Diagnostic]:
        if not self.params or self.is_export:
            return []
        header_line = lines[self.start_idx]
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        body_text = "\n".join(body_lines)
        header_lineno = self.start_idx + 1
        diags: list[Diagnostic] = []

        for param_name in self.params:
            if not param_name:
                continue
            if param_name.startswith("_"):
                continue
            if not param_name.isidentifier():
                continue
            if param_name.casefold() in skip_standard_params:
                continue
            if param_name in self.optional_params:
                continue
            proc_info = self._to_proc_info()
            if param_name.casefold() in ("параметры", "parameters") and (
                is_typical_client_command_handler(proc_info, lines)
                or is_client_notify_completion_export_handler(proc_info, lines)
            ):
                continue
            if used_casefold is not None:
                is_used = param_name.casefold() in used_casefold
            else:
                is_used = bool(
                    re.search(
                        r"\b" + re.escape(param_name) + r"\b",
                        body_text,
                        re.IGNORECASE,
                    )
                )
            if is_used:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=header_lineno,
                    character=self.header_col,
                    end_line=header_lineno,
                    end_character=len(header_line.rstrip()),
                    severity=Severity.WARNING,
                    code="BSL062",
                    message=(f"Parameter '{param_name}' is never used in the method body."),
                )
            )
        return diags

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
                message=(
                    f'Уменьшите когнитивную сложность "{self.name}" '
                    f"с {cognitive_complexity} до {max_cognitive_complexity}"
                ),
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
                message=(
                    f'Уменьшите цикломатическую сложность "{self.name}" '
                    f"с {mccabe_complexity} до {max_mccabe_complexity}"
                ),
            )
        ]

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
        )
