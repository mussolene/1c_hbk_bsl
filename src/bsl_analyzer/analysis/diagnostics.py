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
    "BSL018": {
        "name": "RaiseExceptionWithLiteral",
        "description": "ВызватьИсключение/Raise used with a string literal instead of an exception object",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["error-handling"],
    },
    "BSL019": {
        "name": "CyclomaticComplexity",
        "description": "Method McCabe cyclomatic complexity exceeds the allowed threshold",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL020": {
        "name": "ExcessiveNesting",
        "description": "Code block nesting depth exceeds the allowed maximum",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["brain-overload"],
    },
    "BSL021": {
        "name": "UnusedValParameter",
        "description": "Value parameter (Знач/Val) is never read inside the method body",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["unused"],
    },
    "BSL022": {
        "name": "DeprecatedMessage",
        "description": "Предупреждение()/Warning() is a deprecated modal dialog — use status bar messaging instead",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "ui"],
    },
    "BSL023": {
        "name": "UsingServiceTag",
        "description": "Service tag (TODO/FIXME/HACK/КЕЙС) found — should be resolved or linked to a ticket",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention"],
    },
    "BSL024": {
        "name": "SpaceAtStartComment",
        "description": "Comment text should start with a space after '//'",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "style"],
    },
    "BSL025": {
        "name": "MissingSemicolon",
        "description": "Statement is not terminated with a semicolon",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["syntax", "convention"],
    },
    "BSL026": {
        "name": "EmptyRegion",
        "description": "#Область/#Region block contains no executable code",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["unused"],
    },
    "BSL027": {
        "name": "UseGotoOperator",
        "description": "Перейти/Goto statement makes control flow hard to follow",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["design", "brain-overload"],
    },
    "BSL028": {
        "name": "MissingCodeTryCatch",
        "description": "Method body contains no error handling (Try/Except) for potentially risky operations",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["error-handling", "robustness"],
    },
    "BSL029": {
        "name": "MagicNumber",
        "description": "Magic number literal used directly in code — extract it to a named constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "readability"],
    },
    "BSL030": {
        "name": "LineEndsWithSemicolon",
        "description": "Procedure/function header line ends with a semicolon (not needed in BSL)",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "style"],
    },
    "BSL031": {
        "name": "NumberOfParams",
        "description": "Method has too many parameters (including required ones)",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "brain-overload"],
    },
    "BSL032": {
        "name": "FunctionReturnValue",
        "description": "Function may exit without returning a value (missing Возврат)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "design"],
    },
    "BSL033": {
        "name": "QueryInLoop",
        "description": "Query execution inside a loop — severe performance risk in 1C",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["performance", "brain-overload"],
    },
    "BSL034": {
        "name": "UnusedErrorVariable",
        "description": "ИнформацияОбОшибке()/ErrorInfo() result assigned but never used",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["unused", "error-handling"],
    },
    "BSL035": {
        "name": "DuplicateStringLiteral",
        "description": "String literal is duplicated — extract to a constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "readability"],
    },
    "BSL036": {
        "name": "ComplexCondition",
        "description": "Condition expression has too many boolean operators",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL037": {
        "name": "OverrideBuiltinMethod",
        "description": "Method name shadows a 1C platform built-in function",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "convention"],
    },
    "BSL038": {
        "name": "StringConcatenationInLoop",
        "description": "String concatenation operator '+' inside a loop — use StrTemplate or array join",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance"],
    },
    "BSL039": {
        "name": "NestedTernaryOperator",
        "description": "Nested ternary ?() expression reduces readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["brain-overload", "readability"],
    },
    "BSL040": {
        "name": "UsingThisForm",
        "description": "Direct use of ЭтаФорма/ThisForm outside event handlers is fragile",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "ui"],
    },
    "BSL041": {
        "name": "NotifyDescriptionToModalWindow",
        "description": "ОписаниеОповещения/NotifyDescription call with modal window is deprecated",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "ui"],
    },
    "BSL042": {
        "name": "EmptyExportMethod",
        "description": "Exported method has no meaningful body (empty stub)",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "api"],
    },
    "BSL043": {
        "name": "TooManyVariables",
        "description": "Method declares too many local variables (default >15)",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["brain-overload", "size"],
    },
    "BSL044": {
        "name": "FunctionNoReturnValue",
        "description": "Exported Function contains no explicit Возврат/Return with a value",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["design", "api", "suspicious"],
    },
    "BSL045": {
        "name": "MultilineStringLiteral",
        "description": "Multi-line string via repeated concatenation — use | continuation instead",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL046": {
        "name": "MissingElseBranch",
        "description": "If…ElseIf chain has no Else branch — unhandled case may hide bugs",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "defensive-programming"],
    },
    "BSL047": {
        "name": "DateTimeNow",
        "description": "ТекущаяДата()/CurrentDate() returns local server time — use CurrentUniversalDate() for UTC-safe code",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "date-time"],
    },
    "BSL048": {
        "name": "EmptyFile",
        "description": "BSL file contains no executable code (empty or comments only)",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["unused"],
    },
    "BSL049": {
        "name": "UnconditionalExceptionRaise",
        "description": "ВызватьИсключение/Raise outside a Попытка/Try block is unconditional — consider using a guard condition",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["error-handling", "defensive-programming"],
    },
    "BSL050": {
        "name": "LargeTransaction",
        "description": "НачатьТранзакцию/BeginTransaction without close-by ЗафиксироватьТранзакцию/CommitTransaction may leave transaction open",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["design", "transactions", "reliability"],
    },
    "BSL051": {
        "name": "UnreachableCode",
        "description": "Code after an unconditional Возврат/Return or ВызватьИсключение/Raise is unreachable",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "dead-code"],
    },
    "BSL052": {
        "name": "UselessCondition",
        "description": "Condition is always True or always False (literal Истина/Ложь/True/False)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "logic"],
    },
    "BSL053": {
        "name": "ExecuteDynamic",
        "description": "Выполнить()/Execute() runs dynamically constructed code — security and maintenance risk",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "design"],
    },
    "BSL054": {
        "name": "ModuleLevelVariable",
        "description": "Module-level Перем/Var declaration creates shared mutable state — prefer local variables",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "global-state"],
    },
    "BSL055": {
        "name": "ConsecutiveBlankLines",
        "description": "More than 2 consecutive blank lines reduce readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "formatting"],
    },
    "BSL056": {
        "name": "ShortMethodName",
        "description": "Method name is too short (< 3 characters) — use a descriptive name",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["naming", "readability"],
    },
    "BSL057": {
        "name": "DeprecatedInputDialog",
        "description": "ВвестиЗначение/ВвестиЧисло/ВвестиДату/ВвестиСтроку are synchronous modal dialogs deprecated in 8.3",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
    },
    "BSL058": {
        "name": "QueryWithoutWhere",
        "description": "Embedded query text has no WHERE clause — may return all rows and cause performance issues",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "sql"],
    },
    "BSL059": {
        "name": "BooleanLiteralComparison",
        "description": "Comparison to boolean literal (А = Истина / А = Ложь) — use the expression directly",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL060": {
        "name": "DoubleNegation",
        "description": "НЕ НЕ expression — double negation cancels out, use the expression directly",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability", "suspicious"],
    },
    "BSL061": {
        "name": "AbruptLoopExit",
        "description": "Прервать/Break as the last statement of a loop body — consider restructuring the condition",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "readability"],
    },
    "BSL062": {
        "name": "UnusedParameter",
        "description": "Procedure/function parameter is never referenced in the method body",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["unused", "design"],
    },
    "BSL063": {
        "name": "LargeModule",
        "description": "Module file exceeds the maximum allowed line count",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["size", "brain-overload"],
    },
    "BSL064": {
        "name": "ProcedureReturnsValue",
        "description": "Procedure (Процедура) contains 'Возврат <value>' — should be declared as Function",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "design"],
    },
}


# ---------------------------------------------------------------------------
# Fix hints — actionable one-line suggestions keyed by rule code
# ---------------------------------------------------------------------------

RULE_FIX_HINTS: dict[str, str] = {
    "BSL002": "Extract logic into smaller helper procedures/functions.",
    "BSL004": "Add error logging: Сообщить(ОписаниеОшибки()) or re-raise with context.",
    "BSL005": "Move URL/IP to a constant, configuration parameter, or InfoBase settings.",
    "BSL006": "Use relative paths or store the path in a configuration parameter.",
    "BSL007": "Remove the unused variable declaration.",
    "BSL009": "Check for copy-paste error — both sides of '=' are identical.",
    "BSL010": "Remove the redundant 'Возврат;' at the end of the Procedure.",
    "BSL011": "Decompose into smaller methods; extract nested conditions to named variables.",
    "BSL012": "Move credentials to OS environment variables or 1C InfoBase settings.",
    "BSL013": "Delete or restore the commented-out code block.",
    "BSL014": "Break the long line using BSL | continuation or an intermediate variable.",
    "BSL015": "Reduce optional parameters or introduce a parameter struct/object.",
    "BSL018": "Use 'ВызватьИсключение НовоеИсключение(\"...\");' instead of a string literal.",
    "BSL022": "Replace Предупреждение() with asynchronous ShowMessageBox().",
    "BSL027": "Replace Перейти/Goto with a structured loop or conditional.",
    "BSL028": "Wrap risky operations in Попытка...Исключение...КонецПопытки.",
    "BSL033": "Move the query outside the loop; collect data first, then iterate.",
    "BSL035": "Extract the repeated string to a named constant.",
    "BSL037": "Rename the variable — it shadows a built-in platform function.",
    "BSL038": "Build parts in an array and use СтрСоединить() at the end.",
    "BSL042": "Implement the method body or remove the Export keyword.",
    "BSL044": "Add 'Возврат <value>;' — Function callers expect a non-Undefined result.",
    "BSL046": "Add 'Иначе' branch to handle all cases explicitly.",
    "BSL047": "Use ТекущаяУниверсальнаяДата() for UTC-safe timestamps.",
    "BSL049": "Wrap in 'Если <guard> Тогда ... КонецЕсли' before raising.",
    "BSL050": "Ensure every code path ends with ЗафиксироватьТранзакцию() or ОтменитьТранзакцию().",
    "BSL051": "Remove the unreachable code or restructure the control flow.",
    "BSL052": "Remove the constant condition — the branch always/never executes.",
    "BSL053": "Replace Выполнить() with explicit method calls or a strategy pattern.",
    "BSL057": "Replace with asynchronous ПоказатьВводЗначения() or use a form.",
    "BSL058": "Add a WHERE/ГДЕ clause or use ПЕРВЫЕ N to limit returned rows.",
    "BSL059": "Use the boolean expression directly: 'Если А Тогда' instead of 'Если А = Истина Тогда'.",
    "BSL060": "Remove the double negation — НЕ НЕ cancels out.",
    "BSL061": "Refactor by moving the exit condition into the loop header.",
    "BSL062": "Remove the unused parameter or add a comment explaining why it is kept.",
    "BSL063": "Split the large module into smaller focused modules.",
    "BSL064": "Change 'Процедура' to 'Функция' and add the required return type handling.",
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
    params: list[str]       # all param names (no defaults, no Val prefix)
    val_params: list[str]   # Знач/Val param names (passed by value)
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

# ВызватьИсключение / Raise with a string literal (anti-pattern)
_RE_RAISE_LITERAL = re.compile(
    r'^\s*(?:ВызватьИсключение|Raise)\s+"',
    re.IGNORECASE | re.MULTILINE,
)

# McCabe: decision-point keywords
_RE_MCCABE_BRANCH = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf|Для|For|ДляКаждого|ForEach|Пока|While|Исключение|Except)\b",
    re.IGNORECASE,
)
# McCabe: boolean operators (each И/Or adds a path)
_RE_MCCABE_BOOL = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)

# Nesting open/close tokens (re-use _CC_OPEN/_CC_CLOSE shapes)
_RE_NEST_OPEN = re.compile(
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While|Попытка|Try)\b",
    re.IGNORECASE,
)
_RE_NEST_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)

# Inline noqa/bsl-disable
_RE_NOQA = re.compile(
    r"//\s*(?:noqa|bsl-disable)(?:\s*:\s*(?P<codes>[A-Z0-9,\s]+))?",
    re.IGNORECASE,
)

# Deprecated dialog: Предупреждение(...) / Warning(...)
_RE_DEPRECATED_MSG = re.compile(
    r"^\s*(?:Предупреждение|Warning)\s*\(",
    re.IGNORECASE,
)

# Service tags in comments
_RE_SERVICE_TAG = re.compile(
    r"//.*\b(?:TODO|FIXME|HACK|КЕЙС|WORKAROUND|UNDONE|XXX)\b",
    re.IGNORECASE,
)

# Comment without space after //  (but allow //!, ///  doc-comments)
_RE_NO_SPACE_COMMENT = re.compile(
    r"//(?![/! ])(?!\s*$)(?!noqa)(?!bsl-disable)",
    re.IGNORECASE,
)

# Statements that MUST end with ;  — simplified: lines inside procs that look
# like assignment, method call, or return, but have no trailing semicolon.
# Only used as a heuristic; BSL allows some statements without semicolons.
_RE_STMT_NO_SEMI = re.compile(
    r"^\s*(?:"
    r"(?:\w+(?:\.\w+)*)\s*\([^)]*\)"     # method call
    r"|(?:\w+(?:\.\w+)*)\s*="            # assignment
    r"|(?:Возврат|Return)\s+\S"          # return with value
    r")\s*$",
    re.IGNORECASE,
)

# Empty region: #Область...#КонецОбласти with nothing code-like inside
_RE_REGION_OPEN_CAP = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>\S+)",
    re.IGNORECASE,
)
_RE_REGION_CLOSE_BARE = re.compile(
    r"^\s*#(?:КонецОбласти|EndRegion)",
    re.IGNORECASE,
)

# Goto / Перейти operator
_RE_GOTO = re.compile(
    r"^\s*(?:Перейти|Goto)\s+~",
    re.IGNORECASE,
)

# Magic number: numeric literal not 0/1/-1, not in a comment or string
# A simplified heuristic: standalone number after =, (, or operator
_RE_MAGIC_NUMBER = re.compile(
    r"(?<![\"'\w.])"        # not preceded by string/word/dot
    r"-?(?:[2-9]\d*|\d{2,})" # 2+ digit integer OR single digit >= 2
    r"(?:\.\d+)?"           # optional decimal part
    r"(?![\w.\"])",          # not followed by word/dot/quote
)

# Procedure/function header line that erroneously ends with ;
_RE_HEADER_SEMICOLON = re.compile(
    r"^\s*(?:Процедура|Функция|Procedure|Function)\s+\w+\s*\([^)]*\)\s*"
    r"(?:(?:Экспорт|Export)\s*)?;",
    re.IGNORECASE,
)

# Query execution in loop — Запрос.Выполнить() or Выполнить() after .
_RE_QUERY_EXECUTE = re.compile(
    r"\.(?:Выполнить|Execute)\s*\(",
    re.IGNORECASE,
)

# Loop open/close for QueryInLoop detection (separate from nesting ones)
_RE_LOOP_OPEN = re.compile(
    r"^\s*(?:ДляКаждого|ForEach|Для|For|Пока|While)\b",
    re.IGNORECASE,
)
_RE_LOOP_CLOSE = re.compile(
    r"^\s*(?:КонецЦикла|EndDo)\b",
    re.IGNORECASE,
)

# ИнформацияОбОшибке() / ErrorInfo() call — result assigned to variable
_RE_ERROR_INFO_ASSIGN = re.compile(
    r"^\s*(\w+)\s*=\s*(?:ИнформацияОбОшибке|ErrorInfo)\s*\(\s*\)",
    re.IGNORECASE,
)

# String literal extractor (simplified — single-quoted not used in BSL)
_RE_STRING_LITERAL = re.compile(r'"([^"]{3,})"')

# Boolean operators count in a single condition line
_RE_BOOL_OP = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)

# String concatenation inside a loop: variable = variable + "string" or + Str(...)
_RE_STR_CONCAT = re.compile(
    r"\b\w+\s*=\s*\w+\s*\+\s*(?:\"[^\"]*\"|\w+\s*\()",
    re.IGNORECASE,
)

# Nested ternary: ?( inside a ?(
_RE_NESTED_TERNARY = re.compile(
    r"\?\s*\([^)]*\?\s*\(",
    re.IGNORECASE,
)

# ЭтаФорма / ThisForm outside a comment
_RE_THIS_FORM = re.compile(
    r"\b(?:ЭтаФорма|ThisForm)\b",
    re.IGNORECASE,
)

# ОписаниеОповещения / NotifyDescription
_RE_NOTIFY_DESCRIPTION = re.compile(
    r"\bОписаниеОповещения\s*\(|NotifyDescription\s*\(",
    re.IGNORECASE,
)

# Platform built-in names (lowercase) — used for BSL037 override detection
_PLATFORM_BUILTINS: frozenset[str] = frozenset(
    {
        "сообщить", "предупреждение", "вопрос", "описаниеошибки",
        "информацияобошибке", "новоеисключение", "типзнч", "тип",
        "значениезаполнено", "стрдлина", "лев", "прав", "сред",
        "стрнайти", "стрзаменить", "нрег", "врег", "сокрл", "сокрп", "сокрлп",
        "пустаястрока", "строка", "число", "булево", "дата",
        "окр", "цел", "abs", "макс", "мин",
        "текущаядата", "началодня", "конецдня", "началомесяца", "конецмесяца",
        "добавитьмесяц", "год", "месяц", "день",
        "стрразделить", "стрсоединить", "стрсодержит",
        "стрначинаетсяс", "стрзаканчиваетсяна",
        "символ", "кодсимвола", "формат", "стршаблон",
        # English aliases
        "message", "question", "errordescription", "errorinfo",
        "typeof", "type", "valueisfilled",
        "strlen", "left", "right", "mid", "strfind", "strreplace",
        "lower", "upper", "triml", "trimr", "trimall", "isblankstring",
        "string", "number", "boolean", "round", "int", "max", "min",
        "currentdate", "begofday", "endofday", "begofmonth", "endofmonth",
        "addmonth", "year", "month", "day",
        "strsplit", "strconcat", "strcontains", "strstartswith", "strendswith",
        "char", "charcode", "format", "strtemplate",
    }
)

# Выполнить / Execute dynamic code
_RE_EXECUTE_DYNAMIC = re.compile(
    r'^\s*(?:Выполнить|Execute)\s*\(',
    re.IGNORECASE,
)

# Module-level variable declaration (outside any proc/function)
# We reuse _RE_VAR_LOCAL for matching

# Literal True/False in If condition
_RE_IF_LITERAL = re.compile(
    r'^\s*(?:Если|If)\s+(?:Истина|True|Ложь|False)\b',
    re.IGNORECASE,
)

# Boolean literal comparison: А = Истина / А = Ложь (both sides)
_RE_BOOL_LITERAL_CMP = re.compile(
    r'(?:=|<>)\s*(?:Истина|True|Ложь|False)(?=\s|;|\)|\Z)'
    r'|(?:Истина|True|Ложь|False)\s*(?:=|<>)',
    re.IGNORECASE,
)

# Double negation НЕ НЕ / Not Not
_RE_DOUBLE_NEGATION = re.compile(
    r'\b(?:НЕ|Not)\s+(?:НЕ|Not)\b',
    re.IGNORECASE,
)

# Прервать/Break as last statement before КонецЦикла
_RE_BREAK = re.compile(r'^\s*(?:Прервать|Break)\s*;?\s*$', re.IGNORECASE)

# Deprecated modal input dialogs
_RE_INPUT_DIALOG = re.compile(
    r'\b(?:ВвестиЗначение|ВвестиЧисло|ВвестиДату|ВвестиСтроку'
    r'|InputValue|InputNumber|InputDate|InputString)\s*\(',
    re.IGNORECASE,
)

# Query text block: "ВЫБРАТЬ ... ИЗ ..."
_RE_QUERY_TEXT_START = re.compile(
    r'".*(?:ВЫБРАТЬ|SELECT)\b',
    re.IGNORECASE,
)
_RE_QUERY_WHERE = re.compile(
    r'\b(?:ГДЕ|WHERE)\b',
    re.IGNORECASE,
)
_RE_QUERY_END_QUOTE = re.compile(r'[^|"]*"')

# Unconditional exit from method body (for unreachable code detection)
_RE_UNCONDITIONAL_EXIT = re.compile(
    r'^\s*(?:Возврат|Return|ВызватьИсключение|Raise)\b',
    re.IGNORECASE,
)

# String continuation line in BSL (| at the start for multiline literals)
_RE_STR_CONTINUATION = re.compile(r'^\s*\|', re.MULTILINE)

# ТекущаяДата / CurrentDate (non-UTC)
_RE_CURRENT_DATE = re.compile(
    r'\b(?:ТекущаяДата|CurrentDate)\s*\(',
    re.IGNORECASE,
)

# НачатьТранзакцию / BeginTransaction
_RE_BEGIN_TRANSACTION = re.compile(
    r'\b(?:НачатьТранзакцию|BeginTransaction)\s*\(',
    re.IGNORECASE,
)

# ЗафиксироватьТранзакцию / CommitTransaction or РоллбекТранзакции / RollbackTransaction
_RE_COMMIT_TRANSACTION = re.compile(
    r'\b(?:ЗафиксироватьТранзакцию|CommitTransaction'
    r'|ОтменитьТранзакцию|RollbackTransaction)\s*\(',
    re.IGNORECASE,
)

# ВызватьИсключение / Raise (not inside try)
_RE_RAISE = re.compile(
    r'^\s*(?:ВызватьИсключение|Raise)\b',
    re.IGNORECASE | re.MULTILINE,
)

# If/ElseIf/Else/EndIf detection (for MissingElseBranch)
_RE_IF_OPEN = re.compile(r'^\s*Если\b|^\s*If\b', re.IGNORECASE)
_RE_ELSEIF = re.compile(r'^\s*(?:ИначеЕсли|ElsIf)\b', re.IGNORECASE)
_RE_ELSE = re.compile(r'^\s*(?:Иначе|Else)\s*$|^\s*(?:Иначе|Else)\s*;?\s*$', re.IGNORECASE)
_RE_ENDIF = re.compile(r'^\s*(?:КонецЕсли|EndIf)\b', re.IGNORECASE)

# Procedure body header (BSL062/BSL064)
# Return with a value (BSL064 — Procedure returns value)
_RE_RETURN_VALUE = re.compile(
    r'^\s*(?:Возврат|Return)\s+\S',
    re.IGNORECASE | re.MULTILINE,
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
        val_params = [p[0] for p in parsed if p[1]]
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
                val_params=val_params,
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


def _calc_mccabe_complexity(lines: list[str], start_idx: int, end_idx: int) -> int:
    """
    Calculate McCabe cyclomatic complexity for a procedure body.

    CC = 1 + number of decision points.
    Decision points: Если/If, ИначеЕсли/ElsIf, Для/For, ДляКаждого/ForEach,
    Пока/While, Исключение/Except, plus each И/And and ИЛИ/Or boolean operator.
    """
    cc = 1
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if _RE_MCCABE_BRANCH.match(line):
            cc += 1
        cc += len(_RE_MCCABE_BOOL.findall(line))
    return cc


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
    MAX_MCCABE_COMPLEXITY: int = 10
    MAX_NESTING_DEPTH: int = 4
    MAX_LINE_LENGTH: int = 120
    MAX_OPTIONAL_PARAMS: int = 3
    MAX_PARAMS: int = 7
    MAX_BOOL_OPS: int = 3
    MIN_DUPLICATE_USES: int = 3
    MIN_COMMENTED_CODE_BLOCK: int = 2
    MAX_MODULE_LINES: int = 1000

    def __init__(
        self,
        parser: BslParser | None = None,
        select: set[str] | None = None,
        ignore: set[str] | None = None,
        *,
        max_proc_lines: int = MAX_PROC_LINES,
        max_returns: int = MAX_RETURNS,
        max_cognitive_complexity: int = MAX_COGNITIVE_COMPLEXITY,
        max_mccabe_complexity: int = MAX_MCCABE_COMPLEXITY,
        max_nesting_depth: int = MAX_NESTING_DEPTH,
        max_line_length: int = MAX_LINE_LENGTH,
        max_optional_params: int = MAX_OPTIONAL_PARAMS,
        max_params: int = MAX_PARAMS,
        max_bool_ops: int = MAX_BOOL_OPS,
        min_duplicate_uses: int = MIN_DUPLICATE_USES,
        max_module_lines: int = MAX_MODULE_LINES,
    ) -> None:
        self._parser = parser or BslParser()
        self._select: set[str] | None = {c.upper() for c in select} if select else None
        self._ignore: set[str] = {c.upper() for c in ignore} if ignore else set()
        self.max_proc_lines = max_proc_lines
        self.max_returns = max_returns
        self.max_cognitive_complexity = max_cognitive_complexity
        self.max_mccabe_complexity = max_mccabe_complexity
        self.max_nesting_depth = max_nesting_depth
        self.max_line_length = max_line_length
        self.max_optional_params = max_optional_params
        self.max_params = max_params
        self.max_bool_ops = max_bool_ops
        self.min_duplicate_uses = min_duplicate_uses
        self.max_module_lines = max_module_lines

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
        if self._rule_enabled("BSL018"):
            diagnostics.extend(self._rule_bsl018_raise_with_literal(path, lines))
        if self._rule_enabled("BSL019"):
            diagnostics.extend(self._rule_bsl019_cyclomatic_complexity(path, lines, procs))
        if self._rule_enabled("BSL020"):
            diagnostics.extend(self._rule_bsl020_excessive_nesting(path, lines, procs))
        if self._rule_enabled("BSL021"):
            diagnostics.extend(self._rule_bsl021_unused_val_parameter(path, lines, procs))
        if self._rule_enabled("BSL022"):
            diagnostics.extend(self._rule_bsl022_deprecated_message(path, lines))
        if self._rule_enabled("BSL023"):
            diagnostics.extend(self._rule_bsl023_service_tag(path, lines))
        if self._rule_enabled("BSL024"):
            diagnostics.extend(self._rule_bsl024_space_at_start_comment(path, lines))
        if self._rule_enabled("BSL025"):
            diagnostics.extend(self._rule_bsl025_missing_semicolon(path, lines, procs))
        if self._rule_enabled("BSL026"):
            diagnostics.extend(self._rule_bsl026_empty_region(path, lines, regions))
        if self._rule_enabled("BSL027"):
            diagnostics.extend(self._rule_bsl027_use_goto(path, lines))
        if self._rule_enabled("BSL028"):
            diagnostics.extend(self._rule_bsl028_missing_try_catch(path, lines, procs))
        if self._rule_enabled("BSL029"):
            diagnostics.extend(self._rule_bsl029_magic_number(path, lines, procs))
        if self._rule_enabled("BSL030"):
            diagnostics.extend(self._rule_bsl030_header_semicolon(path, lines))
        if self._rule_enabled("BSL031"):
            diagnostics.extend(self._rule_bsl031_number_of_params(path, lines, procs))
        if self._rule_enabled("BSL032"):
            diagnostics.extend(self._rule_bsl032_function_return_value(path, lines, procs))
        if self._rule_enabled("BSL033"):
            diagnostics.extend(self._rule_bsl033_query_in_loop(path, lines, procs))
        if self._rule_enabled("BSL034"):
            diagnostics.extend(self._rule_bsl034_unused_error_variable(path, lines, procs))
        if self._rule_enabled("BSL035"):
            diagnostics.extend(self._rule_bsl035_duplicate_string_literal(path, lines))
        if self._rule_enabled("BSL036"):
            diagnostics.extend(self._rule_bsl036_complex_condition(path, lines))
        if self._rule_enabled("BSL037"):
            diagnostics.extend(self._rule_bsl037_override_builtin(path, lines, procs))
        if self._rule_enabled("BSL038"):
            diagnostics.extend(self._rule_bsl038_string_concat_in_loop(path, lines, procs))
        if self._rule_enabled("BSL039"):
            diagnostics.extend(self._rule_bsl039_nested_ternary(path, lines))
        if self._rule_enabled("BSL040"):
            diagnostics.extend(self._rule_bsl040_using_this_form(path, lines))
        if self._rule_enabled("BSL041"):
            diagnostics.extend(self._rule_bsl041_notify_description(path, lines))
        if self._rule_enabled("BSL042"):
            diagnostics.extend(self._rule_bsl042_empty_export_method(path, lines, procs))
        if self._rule_enabled("BSL043"):
            diagnostics.extend(self._rule_bsl043_too_many_variables(path, lines, procs))
        if self._rule_enabled("BSL044"):
            diagnostics.extend(self._rule_bsl044_function_no_return_value(path, lines, procs))
        if self._rule_enabled("BSL045"):
            diagnostics.extend(self._rule_bsl045_multiline_string_literal(path, lines))
        if self._rule_enabled("BSL046"):
            diagnostics.extend(self._rule_bsl046_missing_else_branch(path, lines, procs))
        if self._rule_enabled("BSL047"):
            diagnostics.extend(self._rule_bsl047_current_date(path, lines))
        if self._rule_enabled("BSL048"):
            diagnostics.extend(self._rule_bsl048_empty_file(path, lines))
        if self._rule_enabled("BSL049"):
            diagnostics.extend(self._rule_bsl049_unconditional_raise(path, lines, procs))
        if self._rule_enabled("BSL050"):
            diagnostics.extend(self._rule_bsl050_large_transaction(path, lines, procs))
        if self._rule_enabled("BSL051"):
            diagnostics.extend(self._rule_bsl051_unreachable_code(path, lines, procs))
        if self._rule_enabled("BSL052"):
            diagnostics.extend(self._rule_bsl052_useless_condition(path, lines))
        if self._rule_enabled("BSL053"):
            diagnostics.extend(self._rule_bsl053_execute_dynamic(path, lines))
        if self._rule_enabled("BSL054"):
            diagnostics.extend(self._rule_bsl054_module_level_variable(path, lines, procs))
        if self._rule_enabled("BSL055"):
            diagnostics.extend(self._rule_bsl055_consecutive_blank_lines(path, lines))
        if self._rule_enabled("BSL056"):
            diagnostics.extend(self._rule_bsl056_short_method_name(path, lines, procs))
        if self._rule_enabled("BSL057"):
            diagnostics.extend(self._rule_bsl057_deprecated_input_dialog(path, lines))
        if self._rule_enabled("BSL058"):
            diagnostics.extend(self._rule_bsl058_query_without_where(path, lines))
        if self._rule_enabled("BSL059"):
            diagnostics.extend(self._rule_bsl059_bool_literal_comparison(path, lines))
        if self._rule_enabled("BSL060"):
            diagnostics.extend(self._rule_bsl060_double_negation(path, lines))
        if self._rule_enabled("BSL061"):
            diagnostics.extend(self._rule_bsl061_abrupt_loop_exit(path, lines))
        if self._rule_enabled("BSL062"):
            diagnostics.extend(self._rule_bsl062_unused_parameter(path, lines, procs))
        if self._rule_enabled("BSL063"):
            diagnostics.extend(self._rule_bsl063_large_module(path, lines))
        if self._rule_enabled("BSL064"):
            diagnostics.extend(self._rule_bsl064_procedure_returns_value(path, lines, procs))

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

    # ------------------------------------------------------------------
    # BSL018 — Raise exception with string literal
    # ------------------------------------------------------------------

    def _rule_bsl018_raise_with_literal(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Detect ``ВызватьИсключение "строка"`` — raising with a raw string.

        Recommended pattern is to use an exception object::

            ВызватьИсключение НовоеИсключение("Описание ошибки");
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_RAISE_LITERAL.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL018",
                        message=(
                            "ВызватьИсключение used with a string literal. "
                            "Consider using НовоеИсключение() for structured error information."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL019 — McCabe cyclomatic complexity
    # ------------------------------------------------------------------

    def _rule_bsl019_cyclomatic_complexity(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            cc = _calc_mccabe_complexity(lines, proc.start_idx, proc.end_idx)
            if cc > self.max_mccabe_complexity:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL019",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' has cyclomatic "
                            f"complexity {cc} (maximum {self.max_mccabe_complexity})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL020 — Excessive nesting depth
    # ------------------------------------------------------------------

    def _rule_bsl020_excessive_nesting(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag the first line inside a procedure where nesting exceeds max_nesting_depth."""
        diags: list[Diagnostic] = []
        for proc in procs:
            nesting = 0
            reported: set[int] = set()  # report each over-nested block once
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if _RE_NEST_OPEN.match(line):
                    nesting += 1
                    if nesting > self.max_nesting_depth and i not in reported:
                        reported.add(i)
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=i + 1,
                                character=len(line) - len(line.lstrip()),
                                end_line=i + 1,
                                end_character=len(line),
                                severity=Severity.WARNING,
                                code="BSL020",
                                message=(
                                    f"Nesting depth {nesting} exceeds maximum "
                                    f"{self.max_nesting_depth} in '{proc.name}'"
                                ),
                            )
                        )
                elif _RE_NEST_CLOSE.match(line):
                    nesting = max(0, nesting - 1)
        return diags

    # ------------------------------------------------------------------
    # BSL021 — Unused Знач/Val parameter (kept before new rules)
    # ------------------------------------------------------------------

    def _rule_bsl021_unused_val_parameter(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect ``Знач``/``Val`` parameters that are never read inside the body.

        Reference parameters (without Знач) are skipped because they may serve
        as output parameters — flagging them would produce many false positives.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.val_params:
                continue
            body = "\n".join(lines[proc.start_idx + 1 : proc.end_idx + 1])
            for param in proc.val_params:
                pattern = r"\b" + re.escape(param) + r"\b"
                if not re.search(pattern, body, re.IGNORECASE):
                    line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=proc.header_col,
                            end_line=proc.start_idx + 1,
                            end_character=len(line_text),
                            severity=Severity.WARNING,
                            code="BSL021",
                            message=(
                                f"Value parameter '{param}' (Знач) of "
                                f"{proc.kind} '{proc.name}' is never read"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL022 — Deprecated Предупреждение() / Warning()
    # ------------------------------------------------------------------

    def _rule_bsl022_deprecated_message(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag calls to Предупреждение()/Warning() — deprecated modal dialogs.

        These block execution and are not allowed in background procedures.
        Use Сообщить() or status bar notifications instead.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_DEPRECATED_MSG.match(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL022",
                        message=(
                            "Предупреждение()/Warning() is deprecated. "
                            "Use Сообщить() or status bar messaging instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL023 — Service tags (TODO/FIXME/HACK)
    # ------------------------------------------------------------------

    def _rule_bsl023_service_tag(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag TODO, FIXME, HACK, КЕЙС, WORKAROUND, UNDONE, XXX in comments.

        These should be resolved or linked to a ticket before merging.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            m = _RE_SERVICE_TAG.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.INFORMATION,
                        code="BSL023",
                        message=(
                            f"Service tag found: {line.strip()!r}. "
                            "Resolve this before merging or add a ticket reference."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL024 — No space after // in comment
    # ------------------------------------------------------------------

    def _rule_bsl024_space_at_start_comment(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Require a space after ``//`` in single-line comments.

        Exceptions: ``///`` (doc-comments), ``//!`` (region markers),
        empty comments ``//``, and suppression comments.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("//"):
                continue
            col = line.index("//")
            m = _RE_NO_SPACE_COMMENT.search(line, col)
            if m and m.start() == col:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=col + 2,
                        severity=Severity.INFORMATION,
                        code="BSL024",
                        message="Comment text should start with a space after '//'",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL025 — Missing semicolon at end of statement
    # ------------------------------------------------------------------

    def _rule_bsl025_missing_semicolon(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect statements inside methods that appear to be missing a trailing
        semicolon.

        Only flags lines that match a statement pattern (call/assignment/return)
        and do not end with ``;`` or a continuation character.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                stripped = line.rstrip()
                if not stripped or stripped.strip().startswith("//"):
                    continue
                code_part = stripped.split("//")[0].rstrip()
                if not code_part:
                    continue
                last_char = code_part[-1]
                if last_char in (";", ",", "(", ")", "|", "+", "-", "*", "/", "="):
                    continue
                if _RE_STMT_NO_SEMI.match(code_part):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=len(code_part),
                            end_line=i + 1,
                            end_character=len(code_part),
                            severity=Severity.WARNING,
                            code="BSL025",
                            message="Statement appears to be missing a trailing semicolon",
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL026 — Empty #Область / #Region block
    # ------------------------------------------------------------------

    def _rule_bsl026_empty_region(
        self,
        path: str,
        lines: list[str],
        regions: list[_RegionInfo],
    ) -> list[Diagnostic]:
        """
        Flag #Область blocks that contain no executable code.

        A region is considered empty if the only content between its open and
        close markers is blank lines, comments, or nested region markers.
        """
        diags: list[Diagnostic] = []
        _code_re = re.compile(
            r"^\s*(?!//|#(?:Область|Region|КонецОбласти|EndRegion))\S",
            re.IGNORECASE,
        )
        for region in regions:
            has_code = False
            for i in range(region.start_idx + 1, min(region.end_idx, len(lines))):
                if _code_re.match(lines[i]):
                    has_code = True
                    break
            if not has_code:
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
                        code="BSL026",
                        message=f"Region '{region.name}' contains no executable code",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL027 — UseGotoOperator
    # ------------------------------------------------------------------

    def _rule_bsl027_use_goto(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Перейти/Goto — unconditional jumps damage readability."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_GOTO.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL027",
                        message=(
                            "Перейти/Goto makes control flow unpredictable. "
                            "Refactor using structured loops or functions."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL028 — MissingCodeTryCatch (risky calls without error handling)
    # ------------------------------------------------------------------

    _RE_RISKY_CALL = re.compile(
        r"^\s*(?:"
        r"Новый\s+(?:HTTPСоединение|FTPСоединение|WSОпределения|WSПрокси)"
        r"|ПолучитьФайл|ОтправитьФайл"
        r"|Выполнить\b"
        r"|ЗагрузитьВнешнийОтчет|ЗагрузитьВнешнуюОбработку"
        r")",
        re.IGNORECASE,
    )
    _RE_TRY_BLOCK = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)

    def _rule_bsl028_missing_try_catch(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect risky API calls (network, file, Execute) outside a Try/Except block.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            in_try = False
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if self._RE_TRY_BLOCK.match(line):
                    in_try = True
                elif _RE_NEST_CLOSE.match(line) and in_try:
                    in_try = False
                if not in_try and self._RE_RISKY_CALL.match(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=i + 1,
                            end_character=len(line),
                            severity=Severity.INFORMATION,
                            code="BSL028",
                            message=(
                                "Potentially risky call outside Try/Except — "
                                "consider wrapping in error handling."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL029 — MagicNumber
    # ------------------------------------------------------------------

    def _rule_bsl029_magic_number(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect numeric literals > 1 used directly in executable code.

        Ignores:
        - 0 and 1 (universally accepted)
        - Lines that look like constant declarations (Перем Х = N)
        - Comment lines and strings
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                # Skip constant-like declarations
                if re.match(r"^\s*(?:Перем|Var)\s+\w+\s*=", line, re.IGNORECASE):
                    continue
                # Remove string contents before scanning
                code_part = re.sub(r'"[^"]*"', '""', line)
                code_part = code_part.split("//")[0]
                for m in _RE_MAGIC_NUMBER.finditer(code_part):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=m.start(),
                            end_line=i + 1,
                            end_character=m.end(),
                            severity=Severity.INFORMATION,
                            code="BSL029",
                            message=(
                                f"Magic number {m.group()!r} — "
                                "extract to a named constant for readability."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL030 — Procedure/function header ends with semicolon
    # ------------------------------------------------------------------

    def _rule_bsl030_header_semicolon(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Detect procedure/function headers that end with a semicolon.

        BSL does not require (or allow) a semicolon on the header line;
        adding one is a common copy-paste error from other languages.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_HEADER_SEMICOLON.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
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

    # ------------------------------------------------------------------
    # BSL031 — Too many parameters (total, not just optional)
    # ------------------------------------------------------------------

    def _rule_bsl031_number_of_params(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag methods with more than *max_params* parameters in total.

        Complements BSL015 (optional params only); this rule counts all params.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            total = len(proc.params)
            if total > self.max_params:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL031",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' has {total} parameters "
                            f"(maximum {self.max_params})"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL032 — Function may not return a value
    # ------------------------------------------------------------------

    def _rule_bsl032_function_return_value(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect functions that may exit without a Возврат/Return statement.

        Only flags *functions* (not procedures). A function that has no Возврат
        at all (or only inside conditional branches that may not execute) is
        likely a bug — the caller receives Неопределено unexpectedly.

        Heuristic: if the function body has no bare (non-indented) Возврат
        outside a nested Если/Для/Пока block, flag it.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            has_return = any(_RE_RETURN.match(ln) for ln in body_lines)
            if not has_return:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL032",
                        message=(
                            f"Function '{proc.name}' may exit without returning a value "
                            "(missing Возврат/Return statement)"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL033 — Query execution inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl033_query_in_loop(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect ``.Выполнить()`` / ``.Execute()`` calls inside loops.

        Executing queries inside loops is a critical performance anti-pattern
        in 1C Enterprise — it causes N database round-trips per iteration.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            loop_depth = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if _RE_LOOP_OPEN.match(line):
                    loop_depth += 1
                elif _RE_LOOP_CLOSE.match(line):
                    loop_depth = max(0, loop_depth - 1)
                elif loop_depth > 0:
                    m = _RE_QUERY_EXECUTE.search(line)
                    if m and not line.strip().startswith("//"):
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=i + 1,
                                character=m.start(),
                                end_line=i + 1,
                                end_character=m.end(),
                                severity=Severity.WARNING,
                                code="BSL033",
                                message=(
                                    "Query.Выполнить() inside a loop causes N database "
                                    "round-trips. Move the query outside the loop."
                                ),
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL034 — ИнформацияОбОшибке() assigned but not used
    # ------------------------------------------------------------------

    def _rule_bsl034_unused_error_variable(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect Перем = ИнформацияОбОшибке() where the variable is never read.

        A common pattern in catch blocks is to grab the error info but then
        not actually use it — meaning the error details are silently discarded.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                m = _RE_ERROR_INFO_ASSIGN.match(line)
                if not m:
                    continue
                var_name = m.group(1)
                # Check if the variable is used anywhere after this line in the proc
                rest = "\n".join(lines[i + 1 : proc.end_idx + 1])
                pattern = r"\b" + re.escape(var_name) + r"\b"
                if not re.search(pattern, rest, re.IGNORECASE):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=0,
                            end_line=i + 1,
                            end_character=len(line),
                            severity=Severity.WARNING,
                            code="BSL034",
                            message=(
                                f"Variable '{var_name}' holds ИнформацияОбОшибке() "
                                "but is never used — error details are discarded"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL035 — Duplicate string literal
    # ------------------------------------------------------------------

    def _rule_bsl035_duplicate_string_literal(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag string literals that appear *min_duplicate_uses* or more times.

        Only flags the second occurrence onward to guide extraction.
        Ignores short/trivial strings (less than 4 chars after stripping).
        """
        from collections import Counter

        counts: Counter[str] = Counter()
        positions: dict[str, list[tuple[int, int]]] = {}

        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            for m in _RE_STRING_LITERAL.finditer(line):
                val = m.group(1).strip()
                if not val:
                    continue
                counts[val] += 1
                positions.setdefault(val, []).append((idx + 1, m.start()))

        diags: list[Diagnostic] = []
        for val, count in counts.items():
            if count >= self.min_duplicate_uses:
                # Report second occurrence onward
                for line_no, col in positions[val][1:]:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_no,
                            character=col,
                            end_line=line_no,
                            end_character=col + len(val) + 2,
                            severity=Severity.INFORMATION,
                            code="BSL035",
                            message=(
                                f'String "{val}" is duplicated {count} times — '
                                "extract to a named constant"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL036 — Complex condition (too many boolean operators)
    # ------------------------------------------------------------------

    def _rule_bsl036_complex_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag Если/If lines with more boolean operators than *max_bool_ops*.

        A condition like ``А И Б ИЛИ В И Г`` is hard to read and should
        be refactored into named boolean variables or helper functions.
        """
        diags: list[Diagnostic] = []
        _if_line = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b", re.IGNORECASE)
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if not _if_line.match(line):
                continue
            ops = len(_RE_BOOL_OP.findall(line))
            if ops > self.max_bool_ops:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL036",
                        message=(
                            f"Condition has {ops} boolean operators "
                            f"(maximum {self.max_bool_ops}) — "
                            "extract sub-conditions into named variables"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL037 — Method name overrides a platform built-in
    # ------------------------------------------------------------------

    def _rule_bsl037_override_builtin(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag methods whose name matches a known 1C platform built-in function."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.name.lower() in _PLATFORM_BUILTINS:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.WARNING,
                        code="BSL037",
                        message=(
                            f"'{proc.name}' shadows a 1C platform built-in function. "
                            "Rename to avoid confusion."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL038 — String concatenation in loop
    # ------------------------------------------------------------------

    def _rule_bsl038_string_concat_in_loop(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag ``Переменная = Переменная + "..."`` inside a loop.

        Building a string in a loop via ``+`` is O(n²). Use a Массив + СтрСоединить
        or СтрШаблон pattern instead.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            loop_depth = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if _RE_LOOP_OPEN.match(line):
                    loop_depth += 1
                elif _RE_LOOP_CLOSE.match(line):
                    loop_depth = max(0, loop_depth - 1)
                elif loop_depth > 0 and not line.strip().startswith("//"):
                    if _RE_STR_CONCAT.search(line):
                        m = _RE_STR_CONCAT.search(line)
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=i + 1,
                                character=m.start() if m else 0,
                                end_line=i + 1,
                                end_character=len(line),
                                severity=Severity.WARNING,
                                code="BSL038",
                                message=(
                                    "String concatenation inside a loop is O(n²). "
                                    "Use Массив + СтрСоединить() instead."
                                ),
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL039 — Nested ternary operator
    # ------------------------------------------------------------------

    def _rule_bsl039_nested_ternary(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag nested ?() expressions — they are nearly unreadable."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_NESTED_TERNARY.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL039",
                        message=(
                            "Nested ternary ?() expression reduces readability. "
                            "Extract inner condition to a variable."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL040 — ЭтаФорма / ThisForm outside event handler context
    # ------------------------------------------------------------------

    def _rule_bsl040_using_this_form(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag direct use of ЭтаФорма/ThisForm.

        These are only valid in form module event handlers. Using them in
        common modules or non-handler procedures causes hard-to-debug errors.
        """
        p = Path(path)
        stem_lower = p.stem.lower()
        # Only applies if file is NOT a form module
        if "форма" in stem_lower or "form" in stem_lower:
            return []

        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_THIS_FORM.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL040",
                        message=(
                            "ЭтаФорма/ThisForm should only be used in form module handlers. "
                            "Pass the form as a parameter instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL041 — ОписаниеОповещения / NotifyDescription (deprecated modal)
    # ------------------------------------------------------------------

    def _rule_bsl041_notify_description(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag ОписаниеОповещения() usage — this API is tied to legacy modal windows.

        The modern equivalent is async handlers via background tasks or form callbacks.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_NOTIFY_DESCRIPTION.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL041",
                        message=(
                            "ОписаниеОповещения()/NotifyDescription() is linked to "
                            "deprecated modal window APIs. Use async event handlers."
                        ),
                    )
                )
        return diags


    # ------------------------------------------------------------------
    # BSL042 — Empty export method
    # ------------------------------------------------------------------

    def _rule_bsl042_empty_export_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag exported methods that have no meaningful body (only comments/blanks)."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export:
                continue
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            has_code = any(
                line.strip() and not _RE_BLANK_OR_COMMENT.match(line)
                for line in body_lines
            )
            if not has_code:
                header = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header),
                        severity=Severity.WARNING,
                        code="BSL042",
                        message=(
                            f"Exported {proc.kind} '{proc.name}' has no body. "
                            "Either implement it or remove the Export keyword."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL043 — Too many local variables
    # ------------------------------------------------------------------

    MAX_VARIABLES: int = 15

    def _rule_bsl043_too_many_variables(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag methods with more than MAX_VARIABLES local Перем declarations."""
        diags: list[Diagnostic] = []
        for proc in procs:
            body_lines = lines[proc.start_idx : proc.end_idx + 1]
            var_count = 0
            for line in body_lines:
                m = _RE_VAR_LOCAL.match(line)
                if m:
                    var_count += len([n for n in m.group("names").split(",") if n.strip()])
            if var_count > self.MAX_VARIABLES:
                header = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header),
                        severity=Severity.INFORMATION,
                        code="BSL043",
                        message=(
                            f"{proc.kind.capitalize()} '{proc.name}' declares "
                            f"{var_count} local variables (max {self.MAX_VARIABLES}). "
                            "Consider refactoring into smaller methods."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL044 — Function (Export) with no explicit return value
    # ------------------------------------------------------------------

    def _rule_bsl044_function_no_return_value(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag exported Function declarations that never return a value."""
        diags: list[Diagnostic] = []
        _re_return_value = re.compile(
            r"^\s*(?:Возврат|Return)\s+\S", re.IGNORECASE | re.MULTILINE
        )
        for proc in procs:
            if proc.kind != "function" or not proc.is_export:
                continue
            body = "\n".join(lines[proc.start_idx : proc.end_idx + 1])
            if not _re_return_value.search(body):
                header = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header),
                        severity=Severity.WARNING,
                        code="BSL044",
                        message=(
                            f"Exported Function '{proc.name}' contains no "
                            "Возврат/Return with a value — callers will receive Undefined."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL045 — Multiline string via concatenation (should use | continuation)
    # ------------------------------------------------------------------

    def _rule_bsl045_multiline_string_literal(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Detect patterns like::

            Текст = "Строка1"
                  + "Строка2";

        BSL supports | continuation syntax which is more readable.
        """
        diags: list[Diagnostic] = []
        _re_str_concat_literal = re.compile(
            r'^\s*\+\s*"[^"]*"',
            re.IGNORECASE,
        )
        for idx, line in enumerate(lines):
            if _re_str_concat_literal.match(line):
                # Check previous line ends with a string literal or another concat
                prev = lines[idx - 1].rstrip() if idx > 0 else ""
                if prev.endswith('"') or _re_str_concat_literal.match(lines[idx - 1]):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=0,
                            end_line=idx + 1,
                            end_character=len(line),
                            severity=Severity.INFORMATION,
                            code="BSL045",
                            message=(
                                "Multi-line string via concatenation — "
                                'use BSL | continuation: "Строка1"\n    |Строка2'
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL046 — If…ElseIf chain without Else branch
    # ------------------------------------------------------------------

    def _rule_bsl046_missing_else_branch(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Detect Если...ИначеЕсли...КонецЕсли chains that have no Иначе branch.
        Only reports top-level chains (depth=1) to avoid noise.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _RE_IF_OPEN.match(line):
                # Walk forward to matching EndIf
                depth = 1
                has_elseif = False
                has_else = False
                if_line = i
                j = i + 1
                while j < len(lines) and depth > 0:
                    ln = lines[j]
                    if _RE_IF_OPEN.match(ln):
                        depth += 1
                    elif _RE_ENDIF.match(ln):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        if _RE_ELSEIF.match(ln):
                            has_elseif = True
                        elif _RE_ELSE.match(ln):
                            has_else = True
                    j += 1
                if has_elseif and not has_else:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=if_line + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=if_line + 1,
                            end_character=len(line),
                            severity=Severity.INFORMATION,
                            code="BSL046",
                            message=(
                                "Если/ElseIf chain has no Иначе/Else branch — "
                                "unhandled cases may silently do nothing."
                            ),
                        )
                    )
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL047 — CurrentDate (non-UTC)
    # ------------------------------------------------------------------

    def _rule_bsl047_current_date(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag ТекущаяДата()/CurrentDate() — prefer ТекущаяУниверсальнаяДата()."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            for m in _RE_CURRENT_DATE.finditer(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL047",
                        message=(
                            "ТекущаяДата()/CurrentDate() returns local server time. "
                            "Use ТекущаяУниверсальнаяДата()/CurrentUniversalDate() "
                            "for UTC-safe code."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL048 — Empty file
    # ------------------------------------------------------------------

    def _rule_bsl048_empty_file(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag BSL files that contain no executable code at all."""
        for line in lines:
            if line.strip() and not _RE_BLANK_OR_COMMENT.match(line):
                return []
        return [
            Diagnostic(
                file=path,
                line=1,
                character=0,
                end_line=1,
                end_character=0,
                severity=Severity.INFORMATION,
                code="BSL048",
                message="File contains no executable code (empty or comments only).",
            )
        ]

    # ------------------------------------------------------------------
    # BSL049 — Unconditional raise outside Try
    # ------------------------------------------------------------------

    def _rule_bsl049_unconditional_raise(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag ВызватьИсключение/Raise statements that appear *outside* any
        Попытка...Исключение block.  These are unconditional throws that will
        always terminate the call — usually a bug or forgotten guard.
        """
        diags: list[Diagnostic] = []
        _re_try_open = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_try_close = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)

        for proc in procs:
            body_lines = lines[proc.start_idx : proc.end_idx + 1]
            try_depth = 0
            for rel_idx, line in enumerate(body_lines):
                if _re_try_open.match(line):
                    try_depth += 1
                elif _re_try_close.match(line):
                    try_depth = max(0, try_depth - 1)
                elif try_depth == 0 and _RE_RAISE.match(line):
                    abs_idx = proc.start_idx + rel_idx
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=abs_idx + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=abs_idx + 1,
                            end_character=len(line),
                            severity=Severity.INFORMATION,
                            code="BSL049",
                            message=(
                                "ВызватьИсключение/Raise outside a Попытка/Try block "
                                "is unconditional — wrap in a guard condition."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL050 — Transaction without commit
    # ------------------------------------------------------------------

    def _rule_bsl050_large_transaction(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag methods that call НачатьТранзакцию/BeginTransaction but do not
        contain a matching ЗафиксироватьТранзакцию/CommitTransaction or
        ОтменитьТранзакцию/RollbackTransaction within the same method.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            body = "\n".join(lines[proc.start_idx : proc.end_idx + 1])
            begin_matches = list(_RE_BEGIN_TRANSACTION.finditer(body))
            if not begin_matches:
                continue
            if _RE_COMMIT_TRANSACTION.search(body):
                continue
            # Found BeginTransaction but no commit/rollback in this method
            m = begin_matches[0]
            line_offset = body[: m.start()].count("\n")
            abs_line = proc.start_idx + line_offset
            ln = lines[abs_line] if abs_line < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=path,
                    line=abs_line + 1,
                    character=m.start() - body.rfind("\n", 0, m.start()) - 1,
                    end_line=abs_line + 1,
                    end_character=len(ln),
                    severity=Severity.WARNING,
                    code="BSL050",
                    message=(
                        f"Method '{proc.name}' calls НачатьТранзакцию/BeginTransaction "
                        "but contains no matching ЗафиксироватьТранзакцию/CommitTransaction "
                        "or ОтменитьТранзакцию/RollbackTransaction — transaction may remain open."
                    ),
                )
            )
        return diags


    # ------------------------------------------------------------------
    # BSL051 — Unreachable code after Return/Raise
    # ------------------------------------------------------------------

    def _rule_bsl051_unreachable_code(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag code that follows an unconditional Возврат/Return or
        ВызватьИсключение/Raise within the same scope block.

        Simple heuristic: if an unconditional exit is followed by a
        non-blank, non-comment line *at the same or lesser indentation*,
        it is unreachable.
        """
        diags: list[Diagnostic] = []
        # Track which lines are proc-end markers to avoid false positives
        end_line_idxs: set[int] = set()
        for proc in procs:
            end_line_idxs.add(proc.end_idx)

        for proc in procs:
            body_lines = list(enumerate(
                lines[proc.start_idx + 1 : proc.end_idx], start=proc.start_idx + 1
            ))
            i = 0
            while i < len(body_lines):
                abs_idx, line = body_lines[i]
                if _RE_UNCONDITIONAL_EXIT.match(line) and ";" in line:
                    exit_indent = len(line) - len(line.lstrip())
                    # Look at next non-blank, non-comment line
                    j = i + 1
                    while j < len(body_lines):
                        next_abs, next_line = body_lines[j]
                        stripped = next_line.strip()
                        if not stripped or stripped.startswith("//"):
                            j += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip())
                        # Same or lesser indent => same scope => unreachable
                        if next_indent <= exit_indent and next_abs not in end_line_idxs:
                            # Skip КонецЕсли/КонецЦикла/etc. (they close blocks)
                            if not re.match(
                                r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo"
                                r"|Исключение|Except|Иначе|Else|ИначеЕсли|ElsIf)\b",
                                next_line, re.IGNORECASE
                            ):
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=next_abs + 1,
                                        character=next_indent,
                                        end_line=next_abs + 1,
                                        end_character=len(next_line),
                                        severity=Severity.WARNING,
                                        code="BSL051",
                                        message="Unreachable code after unconditional Возврат/ВызватьИсключение.",
                                    )
                                )
                        break
                    i = j
                    continue
                i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL052 — Useless condition (literal True/False in If)
    # ------------------------------------------------------------------

    def _rule_bsl052_useless_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Если Истина/Ложь Тогда — condition is never evaluated."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_IF_LITERAL.match(line)
            if m:
                # Get the literal value
                literal_m = re.search(
                    r'\b(Истина|True|Ложь|False)\b', line, re.IGNORECASE
                )
                literal = literal_m.group(1) if literal_m else "literal"
                diags.append(
                    Diagnostic(
                        file=path,
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

    # ------------------------------------------------------------------
    # BSL053 — Execute() dynamic code
    # ------------------------------------------------------------------

    def _rule_bsl053_execute_dynamic(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Выполнить()/Execute() calls — dynamic code is a security risk."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            if _RE_EXECUTE_DYNAMIC.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL053",
                        message=(
                            "Выполнить()/Execute() executes dynamically constructed code — "
                            "potential code injection vulnerability and hard to maintain."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL054 — Module-level Перем/Var (global state)
    # ------------------------------------------------------------------

    def _rule_bsl054_module_level_variable(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag Перем/Var declarations that appear at module level
        (outside any procedure or function) — they create shared mutable state.
        """
        diags: list[Diagnostic] = []
        # Build set of line indices that are inside a proc/function
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)

        for idx, line in enumerate(lines):
            if idx in inside:
                continue
            m = _RE_VAR_LOCAL.match(line)
            if m:
                names = [n.strip() for n in m.group("names").split(",") if n.strip()]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.INFORMATION,
                        code="BSL054",
                        message=(
                            f"Module-level variable '{', '.join(names)}' creates shared "
                            "mutable state — prefer local variables inside methods."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL055 — Consecutive blank lines (> 2)
    # ------------------------------------------------------------------

    MAX_BLANK_LINES: int = 2

    def _rule_bsl055_consecutive_blank_lines(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag runs of more than 2 consecutive blank lines."""
        diags: list[Diagnostic] = []
        blank_run = 0
        run_start = 0
        for idx, line in enumerate(lines):
            if line.strip() == "":
                if blank_run == 0:
                    run_start = idx
                blank_run += 1
            else:
                if blank_run > self.MAX_BLANK_LINES:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=run_start + 1,
                            character=0,
                            end_line=run_start + blank_run,
                            end_character=0,
                            severity=Severity.INFORMATION,
                            code="BSL055",
                            message=(
                                f"{blank_run} consecutive blank lines "
                                f"(max {self.MAX_BLANK_LINES}) — remove extra blank lines."
                            ),
                        )
                    )
                blank_run = 0
        return diags


    # ------------------------------------------------------------------
    # BSL059 — Boolean literal comparison
    # ------------------------------------------------------------------

    def _rule_bsl059_bool_literal_comparison(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag А = Истина / А = Ложь — use the boolean expression directly."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_BOOL_LITERAL_CMP.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL059",
                        message=(
                            "Comparison to boolean literal — "
                            "use the expression directly: "
                            "'Если А Тогда' instead of 'Если А = Истина Тогда'."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL060 — Double negation
    # ------------------------------------------------------------------

    def _rule_bsl060_double_negation(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag НЕ НЕ / Not Not — double negation always cancels out."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_DOUBLE_NEGATION.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL060",
                        message=(
                            "Double negation 'НЕ НЕ ...' — "
                            "the two negations cancel out; use the expression directly."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL061 — Прервать as last loop body statement
    # ------------------------------------------------------------------

    def _rule_bsl061_abrupt_loop_exit(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag Прервать/Break as the very last non-blank statement before КонецЦикла.
        The loop could be rewritten with a proper loop condition instead.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                # Walk to matching КонецЦикла
                depth = 1
                loop_start = i
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                # Find last non-blank statement before j
                end_idx = j
                k = end_idx - 1
                while k > loop_start and not lines[k].strip():
                    k -= 1
                if k > loop_start and _RE_BREAK.match(lines[k]):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=k + 1,
                            character=len(lines[k]) - len(lines[k].lstrip()),
                            end_line=k + 1,
                            end_character=len(lines[k]),
                            severity=Severity.INFORMATION,
                            code="BSL061",
                            message=(
                                "Прервать/Break is the last statement of the loop body — "
                                "consider using a proper loop condition instead."
                            ),
                        )
                    )
                i = end_idx + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL056 — Short method name (< 3 chars)
    # ------------------------------------------------------------------

    MIN_METHOD_NAME_LEN: int = 3

    def _rule_bsl056_short_method_name(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag method names shorter than 3 characters."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if len(proc.name) < self.MIN_METHOD_NAME_LEN:
                header = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header),
                        severity=Severity.INFORMATION,
                        code="BSL056",
                        message=(
                            f"{proc.kind.capitalize()} name '{proc.name}' is too short "
                            f"({len(proc.name)} chars, min {self.MIN_METHOD_NAME_LEN}). "
                            "Use a descriptive name."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL057 — Deprecated input dialogs
    # ------------------------------------------------------------------

    def _rule_bsl057_deprecated_input_dialog(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag synchronous modal input dialogs deprecated in 8.3."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_INPUT_DIALOG.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL057",
                        message=(
                            f"'{m.group().rstrip('(')}' is a synchronous modal dialog "
                            "deprecated since 1C 8.3. Use asynchronous ShowInputValue() "
                            "or form-based input instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL058 — Embedded query without WHERE clause
    # ------------------------------------------------------------------

    def _rule_bsl058_query_without_where(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Detect string literals that contain a SELECT query without a WHERE clause.
        Heuristic: looks for quoted strings spanning multiple lines (BSL | continuation)
        that contain ВЫБРАТЬ/SELECT but not ГДЕ/WHERE and not ПЕРВЫЕ/FIRST/TOP.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _RE_QUERY_TEXT_START.search(line):
                # Collect all lines of this query string (| continuation)
                query_start = i
                query_lines = [line]
                j = i + 1
                while j < len(lines) and (lines[j].lstrip().startswith("|") or not lines[j].strip()):
                    query_lines.append(lines[j])
                    j += 1
                query_text = "\n".join(query_lines)
                has_where = _RE_QUERY_WHERE.search(query_text)
                has_first = re.search(r'\b(?:ПЕРВЫЕ|FIRST|TOP)\b', query_text, re.IGNORECASE)
                has_into = re.search(r'\b(?:ПОМЕСТИТЬ|INTO)\b', query_text, re.IGNORECASE)
                if not has_where and not has_first and not has_into:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=query_start + 1,
                            character=0,
                            end_line=query_start + 1,
                            end_character=len(line),
                            severity=Severity.WARNING,
                            code="BSL058",
                            message=(
                                "Query has no WHERE/ГДЕ clause and no FIRST/ПЕРВЫЕ limit — "
                                "may return all table rows and cause performance issues."
                            ),
                        )
                    )
                i = j
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL062 — Unused parameter
    # ------------------------------------------------------------------

    def _rule_bsl062_unused_parameter(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag method parameters that are never referenced in the method body.

        Heuristic: scan the body lines for the parameter name as a word token.
        Excludes parameters that start with '_' (convention for intentionally unused).
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            header_line = lines[proc.start_idx]
            m = _RE_PROC_HEADER.search(header_line)
            if not m:
                continue
            params_str = m.group("params")
            if not params_str.strip():
                continue
            # Parse parameter names (ignore default values, Val keyword)
            parsed_params: list[str] = []
            for raw_param in params_str.split(","):
                # Strip Знач/Val and default value
                token = re.sub(r'=.*$', '', raw_param, flags=re.IGNORECASE)
                token = re.sub(r'\b(?:Знач|Val)\b', '', token, flags=re.IGNORECASE).strip()
                if not token:
                    continue
                name = token.split()[0] if token.split() else ""
                if name and not name.startswith("_"):
                    parsed_params.append(name)
            # Body lines (excluding header and closing line)
            body_lines = lines[proc.start_idx + 1: proc.end_idx]
            body_text = "\n".join(body_lines)
            header_lineno = proc.start_idx + 1  # 1-based
            for param_name in parsed_params:
                if not re.search(r'\b' + re.escape(param_name) + r'\b', body_text, re.IGNORECASE):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=header_lineno,
                            character=0,
                            end_line=header_lineno,
                            end_character=len(header_line),
                            severity=Severity.WARNING,
                            code="BSL062",
                            message=f"Parameter '{param_name}' is never used in the method body.",
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL063 — Large module
    # ------------------------------------------------------------------

    def _rule_bsl063_large_module(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag files that exceed the maximum module line count."""
        total = len(lines)
        if total <= self.max_module_lines:
            return []
        return [
            Diagnostic(
                file=path,
                line=1,
                character=0,
                end_line=1,
                end_character=0,
                severity=Severity.WARNING,
                code="BSL063",
                message=(
                    f"Module has {total} lines — exceeds limit of {self.max_module_lines}. "
                    "Split into smaller focused modules."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL064 — Procedure returns value
    # ------------------------------------------------------------------

    def _rule_bsl064_procedure_returns_value(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag a Процедура body that contains 'Возврат <value>' — it should be a Функция.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            header_line = lines[proc.start_idx]
            m = _RE_PROC_HEADER.search(header_line)
            if not m:
                continue
            kind = m.group("kw").lower()
            # Only flag Процедура/Procedure, not Функция/Function
            if kind not in ("процедура", "procedure"):
                continue
            # Scan body for Возврат <value>
            for idx in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[idx]
                # Skip comments
                stripped = line.lstrip()
                if stripped.startswith("//"):
                    continue
                if _RE_RETURN_VALUE.match(line):
                    diags.append(
                        Diagnostic(
                            file=path,
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
                    )
                    break  # One diagnostic per procedure is enough
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
