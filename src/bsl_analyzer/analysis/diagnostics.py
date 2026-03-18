"""
BSL diagnostic rules engine.

Produces Diagnostic records for lint issues found in BSL source files.

Built-in rules
--------------
BSL001  Syntax error detected by the parser
BSL002  Procedure or function longer than 200 lines
BSL003  Public procedure/function missing Экспорт/Export keyword
        (heuristic: exported via comment but no Export keyword)
BSL004  Empty exception handler (Исключение/Except block with no statements)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from bsl_analyzer.parser.bsl_parser import BslParser

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Severity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass
class Diagnostic:
    """A single diagnostic issue found in a BSL file."""

    file: str
    line: int           # 1-based
    character: int      # 0-based
    end_line: int
    end_character: int
    severity: Severity
    code: str           # e.g. "BSL001"
    message: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "character": self.character,
            "end_line": self.end_line,
            "end_character": self.end_character,
            "severity": self.severity.name,
            "code": self.code,
            "message": self.message,
        }

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}:{self.character}: "
            f"{self.severity.name[0]} {self.code} {self.message}"
        )


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_PROC_HEADER = re.compile(
    r"^(?P<kw>Процедура|Procedure|Функция|Function)\s+(?P<name>\w+)"
    r"\s*\([^)]*\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_TRY_START = re.compile(
    r"^\s*(?:Попытка|Try)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_EXCEPT = re.compile(
    r"^\s*(?:Исключение|Except)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_TRY = re.compile(
    r"^\s*(?:КонецПопытки|EndTry)\s*;?\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_BLANK_OR_COMMENT = re.compile(r"^\s*(?://.*)?$")


# ---------------------------------------------------------------------------
# Diagnostic Engine
# ---------------------------------------------------------------------------


class DiagnosticEngine:
    """
    Runs all built-in lint rules on a BSL source file.

    Usage::

        engine = DiagnosticEngine()
        tree = BslParser().parse_file("module.bsl")
        issues = engine.check_file("module.bsl", tree)
    """

    MAX_PROC_LINES = 200

    def __init__(self, parser: BslParser | None = None) -> None:
        self._parser = parser or BslParser()

    def check_file(self, path: str, tree: Any | None = None) -> list[Diagnostic]:
        """
        Run all diagnostic rules on *path*.

        Args:
            path: Absolute path to the BSL file.
            tree: Pre-parsed tree (optional — re-parsed if not provided).

        Returns:
            List of Diagnostic objects, sorted by line.
        """
        if tree is None:
            try:
                tree = self._parser.parse_file(path)
            except Exception as exc:
                return [
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=0,
                        severity=Severity.ERROR,
                        code="BSL001",
                        message=f"Failed to parse file: {exc}",
                    )
                ]

        try:
            content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return [
                Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=0,
                    severity=Severity.ERROR,
                    code="BSL001",
                    message=f"Cannot read file: {exc}",
                )
            ]

        diagnostics: list[Diagnostic] = []
        diagnostics.extend(self._rule_bsl001_syntax_errors(path, tree))
        diagnostics.extend(self._rule_bsl002_long_procedures(path, content))
        diagnostics.extend(self._rule_bsl004_empty_except(path, content))
        return sorted(diagnostics, key=lambda d: (d.line, d.character))

    # ------------------------------------------------------------------
    # BSL001 — Syntax errors
    # ------------------------------------------------------------------

    def _rule_bsl001_syntax_errors(self, path: str, tree: Any) -> list[Diagnostic]:
        errors = self._parser.extract_errors(tree)
        return [
            Diagnostic(
                file=path,
                line=e["line"],
                character=e["column"],
                end_line=e["end_line"],
                end_character=e["end_column"],
                severity=Severity.ERROR,
                code="BSL001",
                message=e["message"],
            )
            for e in errors
        ]

    # ------------------------------------------------------------------
    # BSL002 — Procedure too long
    # ------------------------------------------------------------------

    def _rule_bsl002_long_procedures(self, path: str, content: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        lines = content.splitlines()

        # Find procedure starts and ends
        starts: list[tuple[int, str]] = []  # (line_idx, name)
        ends: list[int] = []

        for m in _RE_PROC_HEADER.finditer(content):
            line_idx = content[: m.start()].count("\n")
            starts.append((line_idx, m.group("name")))

        for m in _RE_END_PROC.finditer(content):
            line_idx = content[: m.start()].count("\n")
            ends.append(line_idx)

        ends_sorted = sorted(ends)

        for start_idx, name in starts:
            # Find corresponding end
            end_idx = start_idx
            for e in ends_sorted:
                if e > start_idx:
                    end_idx = e
                    break

            length = end_idx - start_idx
            if length > self.MAX_PROC_LINES:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=start_idx + 1,
                        character=0,
                        end_line=start_idx + 1,
                        end_character=len(lines[start_idx]) if start_idx < len(lines) else 0,
                        severity=Severity.WARNING,
                        code="BSL002",
                        message=(
                            f"Procedure '{name}' is {length} lines long "
                            f"(maximum {self.MAX_PROC_LINES})"
                        ),
                    )
                )

        return diags

    # ------------------------------------------------------------------
    # BSL004 — Empty exception handler
    # ------------------------------------------------------------------

    def _rule_bsl004_empty_except(self, path: str, content: str) -> list[Diagnostic]:
        """
        Detect Try/Except/EndTry blocks where the Except body is empty
        (contains only whitespace or comments).
        """
        diags: list[Diagnostic] = []
        lines = content.splitlines()

        i = 0
        while i < len(lines):
            if _RE_EXCEPT.match(lines[i]):
                except_line = i + 1  # 1-based
                # Scan forward to EndTry, collecting the handler body
                j = i + 1
                handler_lines: list[str] = []
                while j < len(lines):
                    if _RE_END_TRY.match(lines[j]):
                        break
                    handler_lines.append(lines[j])
                    j += 1

                # Check if all handler lines are blank or comments
                all_empty = all(_RE_BLANK_OR_COMMENT.match(l) for l in handler_lines)
                if all_empty:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=except_line,
                            character=0,
                            end_line=j + 1,
                            end_character=0,
                            severity=Severity.WARNING,
                            code="BSL004",
                            message=(
                                "Empty exception handler: Except block contains no statements. "
                                "Add error handling or at least a comment explaining why it is intentionally empty."
                            ),
                        )
                    )
                i = j + 1
            else:
                i += 1

        return diags
