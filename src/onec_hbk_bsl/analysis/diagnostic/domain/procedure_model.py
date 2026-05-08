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

