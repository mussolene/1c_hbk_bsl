"""
BSL diagnostic rules engine.

Produces Diagnostic records for lint issues found in BSL source files.

Built-in rules
--------------
BSL001  ParseError              — Syntax error detected by tree-sitter
BSL002  MethodSize              — Procedure/function longer than N lines (default 200)
BSL003  NonExportMethodsInApiRegion — Method in API region without Export keyword
BSL004  EmptyCodeBlock          — Empty exception handler
BSL005  HardcodeNetworkAddress  — Hardcoded IP address or URL
BSL006  HardcodePath            — Hardcoded file system path
BSL007  UnusedLocalVariable     — Local variable declared but never referenced
BSL008  TooManyReturnStatements — More than N return statements in one method (default 3)
BSL009  SelfAssign              — Variable assigned to itself (Х = Х)
BSL010  UselessReturn           — Redundant Возврат at the end of a Procedure
BSL011  CognitiveComplexity     — Method cognitive complexity exceeds threshold (default 15)
BSL012  HardcodeCredentials     — Possible hardcoded password / token / secret
BSL013  CommentedCode           — Block of commented-out source code
BSL014  LineTooLong             — Line exceeds maximum length (default 120)
BSL015  NumberOfOptionalParams  — Too many optional parameters (default 3)
BSL016  NonStandardRegion       — Region name not in the standard BSL vocabulary
BSL017  ExportMethodsInCommandModule — Export modifier in a command or form module

Suppression
-----------
Inline suppression on a specific line::

    Исключение  // noqa: BSL004
    Исключение  // bsl-disable: BSL004
    Исключение  // noqa            ← suppresses ALL rules on this line

Engine-level rule selection::

    DiagnosticEngine(select={"BSL001", "BSL002"})   # only these rules
    DiagnosticEngine(ignore={"BSL002"})              # skip these rules
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from bsl_analyzer.parser.bsl_parser import BslParser

# ---------------------------------------------------------------------------
# Public rule registry  (used for --list-rules and SonarQube output)
# ---------------------------------------------------------------------------

RULE_METADATA: dict[str, dict] = {
    "BSL001": {
        "name": "ParseError",
        "description": "Syntax error detected by the BSL parser",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["syntax"],
    },
    "BSL002": {
        "name": "MethodSize",
        "description": "Procedure or function exceeds maximum allowed length",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["size", "brain-overload"],
    },
    "BSL003": {
        "name": "NonExportMethodsInApiRegion",
        "description": "Method in public API region is not marked as Export",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "api"],
    },
    "BSL004": {
        "name": "EmptyCodeBlock",
        "description": "Empty exception handler — errors are silently swallowed",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["error-handling"],
    },
    "BSL005": {
        "name": "HardcodeNetworkAddress",
        "description": "Hardcoded IP address or URL found in source",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "CRITICAL",
        "tags": ["security", "hardware-related"],
    },
    "BSL006": {
        "name": "HardcodePath",
        "description": "Hardcoded file-system path found in source",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "hardware-related"],
    },
    "BSL007": {
        "name": "UnusedLocalVariable",
        "description": "Local variable is declared but never referenced",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["unused"],
    },
    "BSL008": {
        "name": "TooManyReturnStatements",
        "description": "Method has more return statements than the allowed maximum",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["brain-overload"],
    },
    "BSL009": {
        "name": "SelfAssign",
        "description": "Variable is assigned to itself — likely a copy-paste error",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious"],
    },
    "BSL010": {
        "name": "UselessReturn",
        "description": "Redundant Возврат statement at the very end of a Procedure",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant"],
    },
    "BSL011": {
        "name": "CognitiveComplexity",
        "description": "Method cognitive complexity exceeds the allowed threshold",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL012": {
        "name": "HardcodeCredentials",
        "description": "Possible hardcoded password, token, or secret",
        "severity": "ERROR",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "BLOCKER",
        "tags": ["security", "credentials"],
    },
    "BSL013": {
        "name": "CommentedCode",
        "description": "Block of commented-out source code detected",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["unused"],
    },
    "BSL014": {
        "name": "LineTooLong",
        "description": "Line exceeds the maximum allowed length",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention"],
    },
    "BSL015": {
        "name": "NumberOfOptionalParams",
        "description": "Too many optional (default-value) parameters in one method",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "brain-overload"],
    },
    "BSL016": {
        "name": "NonStandardRegion",
        "description": "Region name is not in the standard BSL region vocabulary",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention"],
    },
    "BSL017": {
        "name": "ExportMethodsInCommandModule",
        "description": "Export modifier should not be used in command or form modules",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design"],
    },
}


# ---------------------------------------------------------------------------
# Core data types
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
    character: int      # 0-based column
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
# Internal analysis types
# ---------------------------------------------------------------------------


@dataclass
class _ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str               # 'procedure' | 'function'
    start_idx: int          # 0-based line index (header line)
    end_idx: int            # 0-based line index (КонецПроцедуры/КонецФункции)
    is_export: bool
    params: list[str]       # param names only (no defaults, no Val)
    optional_count: int     # count of params with default values
    header_col: int = 0     # column of the keyword (indent)


@dataclass
class _RegionInfo:
    """#Область / #Region block."""

    name: str
    start_idx: int          # 0-based
    end_idx: int            # 0-based


# ---------------------------------------------------------------------------
# Regex patterns — compiled once at module load for performance
# ---------------------------------------------------------------------------

# Procedure / function header (single-line params; multiline gracefully degrades)
_RE_PROC_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)

_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)

# Except / EndTry
_RE_EXCEPT = re.compile(
    r"^\s*(?:Исключение|Except)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_TRY = re.compile(
    r"^\s*(?:КонецПопытки|EndTry)\s*;?\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_BLANK_OR_COMMENT = re.compile(r"^\s*(?://.*)?$")

# Regions
_RE_REGION_OPEN = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_CLOSE = re.compile(
    r"^\s*#(?:КонецОбласти|EndRegion)",
    re.IGNORECASE | re.MULTILINE,
)

# Hardcoded network addresses
_RE_HARDCODE_NET = re.compile(
    r'"(?:'
    r'(?:https?|ftp|sftp)://[^"\s]{4,}'            # http(s)/ftp/sftp URL
    r'|(?:\d{1,3}\.){3}\d{1,3}'                    # bare IPv4
    r'|\\\\[\w\-.]{2,}\\[\w\-.]+'                  # UNC path
    r')"',
    re.IGNORECASE,
)

# Hardcoded file-system paths
_RE_HARDCODE_PATH = re.compile(
    r'"(?:'
    r'[A-Za-z]:\\[^"]{2,}'                         # Windows C:\...
    r'|/(?:home|usr|var|tmp|etc|opt|mnt|srv|app)/[^"]{2,}'  # Linux absolute
    r')"',
    re.IGNORECASE,
)

# Local Перем declarations
_RE_VAR_LOCAL = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+)\s*;",
    re.IGNORECASE,
)

# Return statements (MULTILINE so ^ matches each line in a joined block)
_RE_RETURN = re.compile(
    r"^\s*(?:Возврат|Return)\b",
    re.IGNORECASE | re.MULTILINE,
)
_RE_RETURN_EMPTY = re.compile(
    r"^\s*(?:Возврат|Return)\s*;",
    re.IGNORECASE | re.MULTILINE,
)

# Self-assign: Х = Х;
_RE_SELF_ASSIGN = re.compile(
    r"\b(\w+)\s*=\s*\1\s*;",
    re.IGNORECASE,
)

# Hardcoded credentials
_RE_CREDENTIALS = re.compile(
    r'(?:пароль|password|passwd|pwd|secret|credential(?:s)?|token'
    r'|логин|login|auth|apikey|api_key|accesskey|access_key)\s*=\s*"[^"]{2,}"',
    re.IGNORECASE,
)

# Commented-out code heuristic
_RE_COMMENTED_CODE = re.compile(
    r"^\s*//\s*(?:"
    r"(?:Процедура|Функция|Если|ИначеЕсли|Для|Пока|Попытка|Возврат|Перем"
    r"|Function|Procedure|If|ElsIf|For|While|Try|Return|Var)\b"
    r"|\w+(?:\.\w+)*\s*\("        # any method call pattern
    r"|\w+\s*=\s*\w+"             # assignment
    r")",
    re.IGNORECASE,
)

# Cognitive complexity branch patterns
_CC_OPEN = re.compile(
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While|Попытка|Try)\b",
    re.IGNORECASE,
)
_CC_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)
_CC_ELSE = re.compile(
    r"^\s*(?:ИначеЕсли|ElsIf|Иначе|Else|Исключение|Except)\b",
    re.IGNORECASE,
)

# Inline noqa/bsl-disable
_RE_NOQA = re.compile(
    r"//\s*(?:noqa|bsl-disable)(?:\s*:\s*(?P<codes>[A-Z0-9,\s]+))?",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Standard region names (Russian + English)
# ---------------------------------------------------------------------------

_STANDARD_REGIONS = frozenset(
    {
        # Russian canonical names
        "программныйинтерфейс",
        "служебныйпрограммныйинтерфейс",
        "служебныепроцедурыифункции",
        "обработчикисобытий",
        "инициализация",
        "переменные",
        "описаниепеременных",
        "локальныепеременные",
        # English canonical names
        "public",
        "internal",
        "private",
        "eventhandlers",
        "initialization",
        "variables",
        "localvariables",
        # Common non-canonical but widely used
        "публичныеметоды",
        "публичные",
        "служебные",
        "helpers",
        "constants",
        "константы",
    }
)

# API region names — methods here must have Export
_API_REGION_NAMES = frozenset(
    {
        "программныйинтерфейс",
        "public",
        "служебныйпрограммныйинтерфейс",
        "internal",
    }
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_params(params_str: str) -> list[tuple[str, bool, bool]]:
    """
    Parse a procedure parameter list string.

    Returns list of (name, is_val, is_optional) tuples.
    Handles: ``Знач Param``, ``Param = "Default"``, and combinations.
    """
    result: list[tuple[str, bool, bool]] = []
    for raw in params_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        is_val = bool(re.match(r"^(?:Знач|Val)\s+", raw, re.IGNORECASE))
        clean = re.sub(r"^(?:Знач|Val)\s+", "", raw, flags=re.IGNORECASE).strip()
        is_optional = "=" in clean
        name = clean.split("=")[0].strip()
        if name and re.match(r"^\w+$", name):
            result.append((name, is_val, is_optional))
    return result


def _find_procedures(content: str) -> list[_ProcInfo]:
    """Extract all procedure/function definitions from BSL source."""
    ends: list[int] = []
    for m in _RE_END_PROC.finditer(content):
        ends.append(content[: m.start()].count("\n"))
    ends.sort()

    result: list[_ProcInfo] = []
    for m in _RE_PROC_HEADER.finditer(content):
        start_idx = content[: m.start()].count("\n")
        kw = m.group("kw").lower()
        name = m.group("name")
        params_str = m.group("params") or ""
        is_export = bool(m.group("export"))
        kind = "function" if kw in ("функция", "function") else "procedure"
        header_col = len(m.group("indent"))

        parsed = _parse_params(params_str)
        params = [p[0] for p in parsed]
        optional_count = sum(1 for p in parsed if p[2])

        # Match to closest end marker after start
        end_idx = start_idx + 5
        for e in ends:
            if e > start_idx:
                end_idx = e
                break

        result.append(
            _ProcInfo(
                name=name,
                kind=kind,
                start_idx=start_idx,
                end_idx=end_idx,
                is_export=is_export,
                params=params,
                optional_count=optional_count,
                header_col=header_col,
            )
        )

    return result


def _find_regions(content: str) -> list[_RegionInfo]:
    """Extract all #Область/#Region blocks from BSL source."""
    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    for m in _RE_REGION_OPEN.finditer(content):
        line_idx = content[: m.start()].count("\n")
        opens.append((line_idx, m.group("name")))

    for m in _RE_REGION_CLOSE.finditer(content):
        line_idx = content[: m.start()].count("\n")
        closes.append(line_idx)

    closes_sorted = sorted(closes)
    used_closes: set[int] = set()

    result: list[_RegionInfo] = []
    for start_idx, name in sorted(opens, key=lambda x: x[0]):
        end_idx = start_idx + 1
        for c in closes_sorted:
            if c > start_idx and c not in used_closes:
                end_idx = c
                used_closes.add(c)
                break
        result.append(_RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))

    return result


def _calc_cognitive_complexity(lines: list[str], start_idx: int, end_idx: int) -> int:
    """
    Calculate simplified Cognitive Complexity for a procedure body.

    Scoring (per SonarSource specification):
    - Each structural element (if/for/while/try) adds 1 + nesting level
    - Each else/elseif/except adds 1 (no nesting bonus)
    - Closing tokens decrease nesting
    """
    complexity = 0
    nesting = 0
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        if _CC_OPEN.match(line):
            complexity += 1 + nesting
            nesting += 1
        elif _CC_CLOSE.match(line):
            nesting = max(0, nesting - 1)
        elif _CC_ELSE.match(line):
            complexity += 1
    return complexity


# ---------------------------------------------------------------------------
# Diagnostic Engine
# ---------------------------------------------------------------------------


class DiagnosticEngine:
    """
    Runs all built-in lint rules on BSL source files.

    Usage::

        engine = DiagnosticEngine()
        issues = engine.check_file("module.bsl")

        # Run only specific rules:
        engine = DiagnosticEngine(select={"BSL001", "BSL011"})

        # Tune thresholds:
        engine = DiagnosticEngine(max_proc_lines=300, max_cognitive_complexity=20)
    """

    # Default thresholds (class-level — can override in __init__)
    MAX_PROC_LINES: int = 200
    MAX_RETURNS: int = 3
    MAX_COGNITIVE_COMPLEXITY: int = 15
    MAX_LINE_LENGTH: int = 120
    MAX_OPTIONAL_PARAMS: int = 3
    MIN_COMMENTED_CODE_BLOCK: int = 2

    def __init__(
        self,
        parser: BslParser | None = None,
        select: set[str] | None = None,
        ignore: set[str] | None = None,
        *,
        max_proc_lines: int = MAX_PROC_LINES,
        max_returns: int = MAX_RETURNS,
        max_cognitive_complexity: int = MAX_COGNITIVE_COMPLEXITY,
        max_line_length: int = MAX_LINE_LENGTH,
        max_optional_params: int = MAX_OPTIONAL_PARAMS,
    ) -> None:
        self._parser = parser or BslParser()
        self._select: set[str] | None = {c.upper() for c in select} if select else None
        self._ignore: set[str] = {c.upper() for c in ignore} if ignore else set()
        self.max_proc_lines = max_proc_lines
        self.max_returns = max_returns
        self.max_cognitive_complexity = max_cognitive_complexity
        self.max_line_length = max_line_length
        self.max_optional_params = max_optional_params

    def _rule_enabled(self, code: str) -> bool:
        """Return True if *code* should be executed."""
        code = code.upper()
        if self._select is not None and code not in self._select:
            return False
        return code not in self._ignore

    def check_file(self, path: str, tree: Any | None = None) -> list[Diagnostic]:
        """
        Run all enabled diagnostic rules on *path*.

        Inline ``// noqa: CODE`` and ``// bsl-disable: CODE`` annotations
        suppress matching diagnostics for their line.

        Returns list of Diagnostic objects sorted by (line, character).
        """
        if tree is None:
            try:
                tree = self._parser.parse_file(path)
            except Exception as exc:
                return [
                    Diagnostic(
                        file=path, line=1, character=0, end_line=1, end_character=0,
                        severity=Severity.ERROR, code="BSL001",
                        message=f"Failed to parse file: {exc}",
                    )
                ]

        try:
            content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return [
                Diagnostic(
                    file=path, line=1, character=0, end_line=1, end_character=0,
                    severity=Severity.ERROR, code="BSL001",
                    message=f"Cannot read file: {exc}",
                )
            ]

        lines = content.splitlines()
        suppressions = _parse_suppressions(lines)

        # Precompute structural info once (shared across rules)
        procs = _find_procedures(content)
        regions = _find_regions(content)

        diagnostics: list[Diagnostic] = []

        if self._rule_enabled("BSL001"):
            diagnostics.extend(self._rule_bsl001_syntax_errors(path, tree))
        if self._rule_enabled("BSL002"):
            diagnostics.extend(self._rule_bsl002_method_size(path, lines, procs))
        if self._rule_enabled("BSL003"):
            diagnostics.extend(self._rule_bsl003_non_export_in_api_region(path, lines, procs, regions))
        if self._rule_enabled("BSL004"):
            diagnostics.extend(self._rule_bsl004_empty_except(path, lines))
        if self._rule_enabled("BSL005"):
            diagnostics.extend(self._rule_bsl005_hardcode_network_address(path, lines))
        if self._rule_enabled("BSL006"):
            diagnostics.extend(self._rule_bsl006_hardcode_path(path, lines))
        if self._rule_enabled("BSL007"):
            diagnostics.extend(self._rule_bsl007_unused_local_variable(path, lines, procs))
        if self._rule_enabled("BSL008"):
            diagnostics.extend(self._rule_bsl008_too_many_returns(path, lines, procs))
        if self._rule_enabled("BSL009"):
            diagnostics.extend(self._rule_bsl009_self_assign(path, lines))
        if self._rule_enabled("BSL010"):
            diagnostics.extend(self._rule_bsl010_useless_return(path, lines, procs))
        if self._rule_enabled("BSL011"):
            diagnostics.extend(self._rule_bsl011_cognitive_complexity(path, lines, procs))
        if self._rule_enabled("BSL012"):
            diagnostics.extend(self._rule_bsl012_hardcode_credentials(path, lines))
        if self._rule_enabled("BSL013"):
            diagnostics.extend(self._rule_bsl013_commented_code(path, lines))
        if self._rule_enabled("BSL014"):
            diagnostics.extend(self._rule_bsl014_line_too_long(path, lines))
        if self._rule_enabled("BSL015"):
            diagnostics.extend(self._rule_bsl015_optional_params_count(path, lines, procs))
        if self._rule_enabled("BSL016"):
            diagnostics.extend(self._rule_bsl016_non_standard_region(path, lines, regions))
        if self._rule_enabled("BSL017"):
            diagnostics.extend(self._rule_bsl017_export_in_command_module(path, lines, procs))

        # Apply inline suppressions and sort
        diagnostics = [d for d in diagnostics if not _is_suppressed(d, suppressions)]
        return sorted(diagnostics, key=lambda d: (d.line, d.character))

    # ------------------------------------------------------------------
    # BSL001 — Parse errors
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
    # BSL002 — Method too long
    # ------------------------------------------------------------------

    def _rule_bsl002_method_size(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            length = proc.end_idx - proc.start_idx
            if length > self.max_proc_lines:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL002",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' is {length} lines long "
                            f"(maximum {self.max_proc_lines})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL003 — Non-export method in API region
    # ------------------------------------------------------------------

    def _rule_bsl003_non_export_in_api_region(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        regions: list[_RegionInfo],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        api_regions = [r for r in regions if r.name.lower() in _API_REGION_NAMES]
        if not api_regions:
            return diags
        for proc in procs:
            if proc.is_export:
                continue
            for region in api_regions:
                if region.start_idx < proc.start_idx < region.end_idx:
                    line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=proc.header_col,
                            end_line=proc.start_idx + 1,
                            end_character=len(line_text),
                            severity=Severity.WARNING,
                            code="BSL003",
                            message=(
                                f"{proc.kind.capitalize()} '{proc.name}' is in API region "
                                f"'{region.name}' but not marked as Export"
                            ),
                        )
                    )
                    break
        return diags

    # ------------------------------------------------------------------
    # BSL004 — Empty exception handler
    # ------------------------------------------------------------------

    def _rule_bsl004_empty_except(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_EXCEPT.match(lines[i]):
                except_line = i + 1
                j = i + 1
                handler_lines: list[str] = []
                while j < len(lines):
                    if _RE_END_TRY.match(lines[j]):
                        break
                    handler_lines.append(lines[j])
                    j += 1
                if all(_RE_BLANK_OR_COMMENT.match(ln) for ln in handler_lines):
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
                                "Add error handling or at least a comment explaining why "
                                "it is intentionally empty."
                            ),
                        )
                    )
                i = j + 1
            else:
                i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL005 — Hardcoded network address
    # ------------------------------------------------------------------

    def _rule_bsl005_hardcode_network_address(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            for m in _RE_HARDCODE_NET.finditer(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL005",
                        message=f"Hardcoded network address: {m.group()!r}",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL006 — Hardcoded file path
    # ------------------------------------------------------------------

    def _rule_bsl006_hardcode_path(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            for m in _RE_HARDCODE_PATH.finditer(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL006",
                        message=f"Hardcoded file-system path: {m.group()!r}",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL007 — Unused local variable
    # ------------------------------------------------------------------

    def _rule_bsl007_unused_local_variable(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            proc_lines = lines[proc.start_idx : proc.end_idx + 1]
            # Scan body lines (skip header)
            for rel_idx, line in enumerate(proc_lines[1:], 1):
                m = _RE_VAR_LOCAL.match(line)
                if not m:
                    continue
                # Handle multi-variable declarations: Перем А, Б, В;
                names_raw = m.group("names")
                var_names = [n.strip() for n in names_raw.split(",") if n.strip()]
                # Body is everything after this declaration line
                body = "\n".join(proc_lines[rel_idx + 1 :])
                for var_name in var_names:
                    pattern = r"\b" + re.escape(var_name) + r"\b"
                    refs = len(re.findall(pattern, body, re.IGNORECASE))
                    if refs == 0:
                        abs_idx = proc.start_idx + rel_idx
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=abs_idx + 1,
                                character=0,
                                end_line=abs_idx + 1,
                                end_character=len(line),
                                severity=Severity.WARNING,
                                code="BSL007",
                                message=f"Local variable '{var_name}' is declared but never used",
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL008 — Too many return statements
    # ------------------------------------------------------------------

    def _rule_bsl008_too_many_returns(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            proc_body = "\n".join(lines[proc.start_idx : proc.end_idx + 1])
            returns = list(_RE_RETURN.finditer(proc_body))
            if len(returns) > self.max_returns:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL008",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' has {len(returns)} "
                            f"return statements (maximum {self.max_returns})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL009 — Self-assignment
    # ------------------------------------------------------------------

    def _rule_bsl009_self_assign(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_SELF_ASSIGN.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL009",
                        message=f"Self-assignment: variable '{m.group(1)}' is assigned to itself",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL010 — Useless return at end of Procedure
    # ------------------------------------------------------------------

    def _rule_bsl010_useless_return(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "procedure":
                continue
            # Find last non-blank, non-comment line before end marker
            for i in range(proc.end_idx - 1, proc.start_idx, -1):
                if i >= len(lines):
                    continue
                stripped = lines[i].strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if _RE_RETURN_EMPTY.match(stripped):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=0,
                            end_line=i + 1,
                            end_character=len(lines[i]),
                            severity=Severity.INFORMATION,
                            code="BSL010",
                            message=(
                                "Useless return statement at the end of Procedure "
                                f"'{proc.name}' — remove it or convert to a Function"
                            ),
                        )
                    )
                break
        return diags

    # ------------------------------------------------------------------
    # BSL011 — Cognitive complexity
    # ------------------------------------------------------------------

    def _rule_bsl011_cognitive_complexity(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            cc = _calc_cognitive_complexity(lines, proc.start_idx, proc.end_idx)
            if cc > self.max_cognitive_complexity:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL011",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' has cognitive complexity "
                            f"{cc} (maximum {self.max_cognitive_complexity})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL012 — Hardcoded credentials
    # ------------------------------------------------------------------

    def _rule_bsl012_hardcode_credentials(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_CREDENTIALS.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
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

    # ------------------------------------------------------------------
    # BSL013 — Commented-out code
    # ------------------------------------------------------------------

    def _rule_bsl013_commented_code(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        consecutive = 0
        start_line = 0
        for idx, line in enumerate(lines):
            if _RE_COMMENTED_CODE.match(line):
                if consecutive == 0:
                    start_line = idx
                consecutive += 1
            else:
                if consecutive >= self.MIN_COMMENTED_CODE_BLOCK:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=start_line + 1,
                            character=0,
                            end_line=idx,
                            end_character=0,
                            severity=Severity.INFORMATION,
                            code="BSL013",
                            message=f"Commented-out code block ({consecutive} lines) — delete or restore",
                        )
                    )
                consecutive = 0
        # Flush trailing block
        if consecutive >= self.MIN_COMMENTED_CODE_BLOCK:
            diags.append(
                Diagnostic(
                    file=path,
                    line=start_line + 1,
                    character=0,
                    end_line=len(lines),
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL013",
                    message=f"Commented-out code block ({consecutive} lines) — delete or restore",
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL014 — Line too long
    # ------------------------------------------------------------------

    def _rule_bsl014_line_too_long(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            length = len(line)
            if length > self.max_line_length:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=self.max_line_length,
                        end_line=idx + 1,
                        end_character=length,
                        severity=Severity.INFORMATION,
                        code="BSL014",
                        message=f"Line is {length} characters long (maximum {self.max_line_length})",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL015 — Too many optional parameters
    # ------------------------------------------------------------------

    def _rule_bsl015_optional_params_count(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.optional_count > self.max_optional_params:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL015",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' has "
                            f"{proc.optional_count} optional parameters "
                            f"(maximum {self.max_optional_params})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL016 — Non-standard region name
    # ------------------------------------------------------------------

    def _rule_bsl016_non_standard_region(
        self,
        path: str,
        lines: list[str],
        regions: list[_RegionInfo],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for region in regions:
            if region.name.lower() not in _STANDARD_REGIONS:
                line_idx = region.start_idx
                line_text = lines[line_idx] if line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=0,
                        end_line=line_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.INFORMATION,
                        code="BSL016",
                        message=(
                            f"Non-standard region name: '{region.name}'. "
                            "Standard names: Public, Internal, Private, "
                            "EventHandlers, Initialization, Variables"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL017 — Export modifier in command/form module
    # ------------------------------------------------------------------

    def _rule_bsl017_export_in_command_module(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag Export methods if the file name indicates a command or form module.

        Command modules: *Command.bsl, ФормаКоманды.bsl
        Form modules:    *Form.bsl, Форма*.bsl
        """
        p = Path(path)
        stem_lower = p.stem.lower()
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
                    file=path,
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


# ---------------------------------------------------------------------------
# Inline suppression helpers
# ---------------------------------------------------------------------------

# Type alias: maps 1-based line → suppressed codes (empty set = all codes)
_Suppressions = dict[int, set[str]]


def _parse_suppressions(lines: list[str]) -> _Suppressions:
    """
    Scan source lines for inline suppression comments.

    Supported forms (case-insensitive)::

        // noqa                    — suppress all rules on this line
        // noqa: BSL001, BSL002    — suppress specific rules
        // bsl-disable: BSL001     — bsl-analyzer style

    Returns a dict mapping 1-based line numbers to a set of suppressed codes.
    An empty set means "suppress all rules".
    """
    result: _Suppressions = {}
    for idx, line in enumerate(lines):
        m = _RE_NOQA.search(line)
        if m is None:
            continue
        line_no = idx + 1
        codes_str = m.group("codes")
        if codes_str:
            codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
        else:
            codes = set()
        result[line_no] = codes
    return result


def _is_suppressed(diag: Diagnostic, suppressed: _Suppressions) -> bool:
    """Return True if *diag* is covered by an inline suppression."""
    codes = suppressed.get(diag.line)
    if codes is None:
        return False
    return len(codes) == 0 or diag.code.upper() in codes
