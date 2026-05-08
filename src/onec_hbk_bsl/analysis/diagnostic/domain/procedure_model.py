from __future__ import annotations

from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo


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

    def _to_proc_info(self) -> ProcInfo:
        return ProcInfo(
            name=self.name,
            kind=self.kind,
            start_idx=self.start_idx,
            end_idx=self.end_idx,
            is_export=self.is_export,
            params=list(self.params),
            val_params=[],
            optional_count=0,
            header_col=self.header_col,
            optional_params=frozenset(),
        )
