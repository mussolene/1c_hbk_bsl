from __future__ import annotations

from dataclasses import dataclass, field

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity


@dataclass
class DiagnosticStorage:
    """Diagnostic collector with small compatibility add helpers."""

    path: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add_range(
        self,
        *,
        code: str,
        message: str,
        severity: Severity,
        line: int,
        character: int,
        end_line: int,
        end_character: int,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(
                file=self.path,
                line=line + 1,
                character=character,
                end_line=end_line + 1,
                end_character=end_character,
                severity=severity,
                code=code,
                message=message,
            )
        )

    def add_match(
        self,
        *,
        code: str,
        message: str,
        severity: Severity,
        line: int,
        start: int,
        end: int,
    ) -> None:
        self.add_range(
            code=code,
            message=message,
            severity=severity,
            line=line,
            character=start,
            end_line=line,
            end_character=end,
        )
