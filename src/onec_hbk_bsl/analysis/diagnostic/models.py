from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass
class Diagnostic:
    """A single diagnostic issue found in a BSL file."""

    file: str
    line: int
    character: int
    end_line: int
    end_character: int
    severity: Severity
    code: str
    message: str

    def to_dict(self, *, include_rule_name: bool = False) -> dict:
        d = {
            "file": self.file,
            "line": self.line,
            "character": self.character,
            "end_line": self.end_line,
            "end_character": self.end_character,
            "severity": self.severity.name,
            "code": self.code,
            "message": self.message,
        }
        if include_rule_name:
            from onec_hbk_bsl.analysis.diagnostics import display_name_for_rule_code

            d["rule_name"] = display_name_for_rule_code(self.code)
        return d

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}:{self.character}: "
            f"{self.severity.name[0]} {self.code} {self.message}"
        )


@dataclass
class ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    params: list[str]
    val_params: list[str]
    optional_count: int
    header_col: int = 0
    optional_params: frozenset[str] = frozenset()


@dataclass
class RegionInfo:
    """#Область / #Region block."""

    name: str
    start_idx: int
    end_idx: int
