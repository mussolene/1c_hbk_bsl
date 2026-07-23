from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

RuleLocale = Literal["ru", "en"]


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

    @property
    def message(self) -> str:
        from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule

        return get_rule(self.code).message

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
            from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule

            rule = get_rule(self.code)
            d["rule_name"] = rule.name
            d["rule_description"] = rule.description
            d["rule_message"] = rule.message
        return d

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}:{self.character}: "
            f"{self.severity.name[0]} {self.code} {self.message}"
        )


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    code: str
    name: str
    description: str
    message_template: str
    message: str
    severity: str
    tags: tuple[str, ...]
    implemented: bool
    locale: RuleLocale = "ru"


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
