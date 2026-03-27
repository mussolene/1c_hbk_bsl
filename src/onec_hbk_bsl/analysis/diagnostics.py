"""
BSL diagnostic rules engine.

Produces Diagnostic records for lint issues found in BSL source files.

Built-in rules
--------------
BSL001  ParseError              — Syntax error detected by tree-sitter
BSL002  MethodSize              — Procedure/function longer than N lines (default 200)
BSL003  NonExportMethodsInApiRegion — Method in API region without Export keyword
BSL004  EmptyCodeBlock          — Empty handler / empty «Тогда» branch
BSL005  UsingHardcodeNetworkAddress — Hardcoded IP address or URL (BSLLS name)
BSL006  UsingHardcodePath           — Hardcoded file system path (BSLLS name)
BSL007  UnusedLocalVariable         — Local variable declared but never referenced
BSL008  TooManyReturns              — More than N return statements in one method (default 3)
BSL009  SelfAssign                  — Variable assigned to itself (Х = Х)
BSL010  UselessReturn               — Redundant Возврат at the end of a Procedure
BSL011  CognitiveComplexity         — Method cognitive complexity exceeds threshold (default 15)
BSL012  UsingHardcodeSecretInformation — Possible hardcoded password / token / secret
BSL013  CommentedCode               — Block of commented-out source code
BSL014  LineLength                  — Line exceeds maximum length (default 120)
BSL015  NumberOfOptionalParams      — Too many optional parameters (default 3)
BSL016  NonStandardRegion           — Region name not in the standard BSL vocabulary
BSL017  CommandModuleExportMethods  — Export modifier in a command or form module

Suppression
-----------
Inline suppression on a specific line::

    Исключение  // noqa: BSL004
    Исключение  // bsl-disable: BSL004
    Исключение  // noqa            ← suppresses ALL rules on this line

BSL Language Server (BSLLS) block suppression — compatible with existing
1c-syntax/bsl-language-server annotations::

    // BSLLS:CognitiveComplexity-off   ← disable from this line onward
    ... complex code ...
    // BSLLS:CognitiveComplexity-on    ← re-enable

    // BSLLS-off    ← disable ALL diagnostics from this line onward
    // BSLLS-on     ← re-enable all

    Russian flags are also recognised::

        // BSLLS:MethodSize-выкл
        // BSLLS:MethodSize-вкл

    BSLLS diagnostic names are mapped to BSL codes via _BSLLS_NAME_TO_CODE
    (copy BSLLS rule names; add a line only when you add or alias a rule).
    Unknown names in comments are ignored.

Engine-level rule selection::

    DiagnosticEngine(select={"BSL001", "BSL002"})   # only these rules
    DiagnosticEngine(ignore={"BSL002"})              # skip these rules
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.bsl_string_regions import (
    diagnostic_overlaps_string_literal,
    double_quoted_string_ranges,
    line_start_offsets,
)
from onec_hbk_bsl.analysis.bsl_string_split import (
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.diagnostics_cst import (
    diagnostics_bsl004_from_tree,
    diagnostics_bsl018_from_tree,
    diagnostics_bsl060_from_tree,
    diagnostics_bsl061_from_tree,
    diagnostics_bsl070_from_tree,
    diagnostics_bsl085_from_tree,
    diagnostics_bsl091_from_tree,
    diagnostics_bsl092_from_tree,
    loop_body_line_indices_0,
    ts_elseif_then_branch_empty,
    ts_if_main_then_branch_empty,
)
from onec_hbk_bsl.analysis.diagnostics_cst import (
    ts_tree_ok_for_rules as _ts_tree_ok_for_rules,
)
from onec_hbk_bsl.analysis.diagnostics_rule_registry import (
    build_enabled_invoke_snapshot,
)
from onec_hbk_bsl.analysis.formatter_structural import tree_has_errors
from onec_hbk_bsl.parser.bsl_parser import BslParser

# When a diagnostic span overlaps a "..." literal, drop the warning unless the rule
# is meant to inspect string contents (secrets, duplicates, concat, magic numbers, …).
_CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL: frozenset[str] = frozenset(
    {
        # Line-length spans the whole line; overlap with trailing string literals must not drop the rule.
        "BSL014",
        "BSL005",
        "BSL006",
        "BSL012",
        "BSL018",
        "BSL022",
        "BSL029",
        "BSL035",
        "BSL038",
        "BSL045",
        "BSL049",
        "BSL051",
        "BSL053",
        "BSL058",
        "BSL071",
        "BSL072",
        "BSL077",
        "BSL090",
        "BSL100",
        "BSL106",
        "BSL110",
        "BSL119",
        "BSL132",
        "BSL142",
        "BSL145",
        "BSL148",
        "BSL235",
    }
)

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
        "description": "Empty code block (exception handler, empty «Тогда» branch, …)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["error-handling"],
    },
    "BSL005": {
        "name": "UsingHardcodeNetworkAddress",
        "description": "Hardcoded IP address or URL found in source",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "CRITICAL",
        "tags": ["security", "hardware-related"],
    },
    "BSL006": {
        "name": "UsingHardcodePath",
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
        "name": "TooManyReturns",
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
        "name": "UsingHardcodeSecretInformation",
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
        "name": "LineLength",
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
        "name": "CommandModuleExportMethods",
        "description": "Export modifier should not be used in command or form modules",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design"],
    },
    "BSL018": {
        "name": "RaiseExceptionWithLiteral",
        "description": (
            "ВызватьИсключение/Raise with only a string literal — optional extended syntax "
            "(8.3.21+) or a non-literal expression for richer error context"
        ),
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
        "name": "NestedStatements",
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
        "name": "UsingModalWindows",
        "description": "Предупреждение()/Warning() is a deprecated modal dialog — use ПоказатьПредупреждение() instead",
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
        "name": "EmptyStatement",
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
        "name": "UsingGoto",
        "description": "Перейти/Goto statement makes control flow hard to follow",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["design", "brain-overload"],
    },
    "BSL028": {
        "name": "MissingCodeTryCatchEx",
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
        "name": "SemicolonPresence",
        "description": "SemicolonPresence (BSLLS): лишняя «;» в заголовке метода и/или пропущена в конце выражения",
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
        "name": "FunctionShouldHaveReturn",
        "description": "Function may exit without returning a value (missing Возврат)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "design"],
    },
    "BSL033": {
        "name": "CreateQueryInCycle",
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
        "name": "IfConditionComplexity",
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
        "name": "UnusedLocalMethod",
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
        "name": "MagicDate",
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
        "description": (
            "ВызватьИсключение/Raise at procedure body base indent outside Попытка/Try "
            "always terminates the call — use a guard or a nested conditional block"
        ),
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
        "name": "IdenticalExpressions",
        "description": "Condition is always True or always False (literal Истина/Ложь/True/False)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "logic"],
    },
    "BSL053": {
        "name": "ExecuteExternalCode",
        "description": "Выполнить()/Execute() runs dynamically constructed code — security and maintenance risk",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "design"],
    },
    "BSL054": {
        "name": "ExportVariables",
        "description": "Module-level Перем/Var declaration creates shared mutable state — prefer local variables",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "global-state"],
    },
    "BSL055": {
        "name": "ConsecutiveEmptyLines",
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
        "name": "DoubleNegatives",
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
        "name": "UnusedParameters",
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
    "BSL065": {
        "name": "MissingReturnedValueDescription",
        "description": "Exported method has no preceding description comment (// or ///)",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "documentation"],
    },
    "BSL066": {
        "name": "DeprecatedFind",
        "description": "Call to a deprecated 1C platform method that has a modern replacement",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "compatibility"],
    },
    "BSL067": {
        "name": "VarDeclarationAfterCode",
        "description": "Перем variable declaration appears after executable code — move it to the top",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["style", "design"],
    },
    "BSL068": {
        "name": "TooManyElseIf",
        "description": "Если/ИначеЕсли chain has too many branches — consider a map or pattern",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "brain-overload"],
    },
    "BSL069": {
        "name": "InfiniteLoop",
        "description": "Пока Истина Цикл without a Прервать — potential infinite loop",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL070": {
        "name": "EmptyLoopBody",
        "description": "Loop body contains no executable statements (empty loop)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
    },
    "BSL071": {
        "name": "MagicNumber",
        "description": "Magic number literal used directly in code — extract to a named constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "maintainability"],
    },
    "BSL072": {
        "name": "StringConcatenationInLoop",
        "description": "String concatenation with '+' inside a loop — use an array and StrConcat",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance"],
    },
    "BSL073": {
        "name": "MissingElseBranch",
        "description": "Если/If statement has no Иначе/Else branch — may miss unexpected values",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "defensive-programming"],
    },
    "BSL074": {
        "name": "TodoComment",
        "description": "TODO/FIXME/HACK comment found — unresolved technical debt",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "maintenance"],
    },
    "BSL075": {
        "name": "ExportVariables",
        "description": "Method modifies a module-level variable — prefer explicit parameters/return",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "maintainability"],
    },
    "BSL076": {
        "name": "NegativeConditionFirst",
        "description": "Condition starts with НЕ/Not — prefer positive form for readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL077": {
        "name": "SelectTopWithoutOrderBy",
        "description": "SELECT */ВЫБРАТЬ * in a query — enumerate columns explicitly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "maintainability"],
    },
    "BSL078": {
        "name": "RaiseWithoutMessage",
        "description": "ВызватьИсключение/Raise without a message — provide context for the error",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "error-handling"],
    },
    "BSL079": {
        "name": "UsingGoto",
        "description": "Goto/Перейти statement found — avoid unstructured control flow",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "CRITICAL",
        "tags": ["style", "brain-overload"],
    },
    "BSL080": {
        "name": "EmptyCodeBlock",
        "description": "Exception handler ignores the error — no ИнформацияОбОшибке or re-raise",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["error-handling", "correctness"],
    },
    "BSL081": {
        "name": "LongMethodChain",
        "description": "Method call chain is too long — split into intermediate variables",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL082": {
        "name": "MissingNewlineAtEndOfFile",
        "description": "File does not end with a newline character",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style"],
    },
    "BSL083": {
        "name": "TooManyModuleVariables",
        "description": "Module has too many module-level Перем declarations — encapsulate in a structure",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["maintainability", "style"],
    },
    "BSL084": {
        "name": "FunctionShouldHaveReturn",
        "description": "Функция/Function has no Возврат with a value — should be Процедура",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness"],
    },
    "BSL085": {
        "name": "IdenticalExpressions",
        "description": "Если Истина/Ложь Тогда — constant condition always true or false",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL086": {
        "name": "HttpRequestInLoop",
        "description": "HTTP request call inside a loop — batch requests or move outside",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance"],
    },
    "BSL087": {
        "name": "ObjectCreationInLoop",
        "description": "Новый/New object creation inside a loop — consider moving outside",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["performance"],
    },
    "BSL088": {
        "name": "MissingReturnedValueDescription",
        "description": "Export method has parameters but no // Parameters: comment in header",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "documentation"],
    },
    "BSL089": {
        "name": "TransactionInLoop",
        "description": "НачатьТранзакцию/BeginTransaction called inside a loop — move outside",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "correctness"],
    },
    "BSL090": {
        "name": "UsingHardcodeSecretInformation",
        "description": "Hardcoded database connection string or DSN in source code",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "maintainability"],
    },
    "BSL091": {
        "name": "RedundantElseAfterReturn",
        "description": "Иначе/Else after Возврат/Return is redundant — remove the Else block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL092": {
        "name": "EmptyCodeBlock",
        "description": "Empty Иначе/Else block — remove it or add a comment explaining intent",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "suspicious"],
    },
    "BSL093": {
        "name": "ComparisonToNull",
        "description": "Use 'Значение = Неопределено' or 'ЗначениеЗаполнено()' instead of comparison to Null/NULL",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL094": {
        "name": "SelfAssign",
        "description": "Compound assignment where left and right sides match (А += 0, А *= 1)",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL095": {
        "name": "MultipleStatementsOnOneLine",
        "description": "Two or more executable statements on a single line — split into separate lines",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL096": {
        "name": "MissingReturnedValueDescription",
        "description": "Export method has no preceding comment block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "documentation"],
    },
    "BSL097": {
        "name": "DeprecatedCurrentDate",
        "description": "ТекущаяДата()/CurrentDate() returns server time — use ТекущаяДатаСеанса() for session time",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL098": {
        "name": "UseOfExecute",
        "description": "Выполнить()/Execute() executes code from a string — security and maintainability risk",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "suspicious"],
    },
    "BSL099": {
        "name": "NumberOfParams",
        "description": "Procedure/function has too many parameters — split into a structure or separate methods",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "complexity"],
    },
    "BSL100": {
        "name": "UsingHardcodePath",
        "description": "Hardcoded file path in a string literal — use a parameter or configuration value",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["portability", "suspicious"],
    },
    "BSL101": {
        "name": "NestedStatements",
        "description": "Code nesting depth exceeds the allowed maximum — refactor into smaller functions",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["complexity", "readability"],
    },
    "BSL102": {
        "name": "LargeModule",
        "description": "Module exceeds the maximum allowed number of lines — split into smaller modules",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "complexity"],
    },
    "BSL103": {
        "name": "UseOfEval",
        "description": "Вычислить()/Eval() evaluates a dynamic expression — security and maintainability risk",
        "severity": "WARNING",
        "sonar_type": "VULNERABILITY",
        "sonar_severity": "MAJOR",
        "tags": ["security", "suspicious"],
    },
    "BSL104": {
        "name": "MissingModuleComment",
        "description": "Module has no comment header at the top — add a description of its purpose",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "documentation"],
    },
    "BSL105": {
        "name": "UseOfSleep",
        "description": "Приостановить()/Sleep() blocks the current thread — avoid in server-side code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "suspicious"],
    },
    "BSL106": {
        "name": "CreateQueryInCycle",
        "description": "SQL query (ВЫБРАТЬ/SELECT) inside a loop — move outside the loop or use batch queries",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "correctness"],
    },
    "BSL107": {
        "name": "EmptyCodeBlock",
        "description": "Empty Тогда branch in Если statement — remove the branch or add meaningful code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL108": {
        "name": "ExportVariables",
        "description": "Module-level exported variable — avoid mutable shared state",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "suspicious"],
    },
    "BSL109": {
        "name": "NegativeConditionalReturn",
        "description": "Если НЕ ... Тогда Возврат — invert the condition to reduce nesting",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL110": {
        "name": "StringConcatInLoop",
        "description": "String concatenation inside a loop — use a list and join instead",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "correctness"],
    },
    "BSL111": {
        "name": "MixedLanguageIdentifiers",
        "description": "Identifier mixes Cyrillic and Latin characters — use one script consistently",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["style", "suspicious"],
    },
    "BSL112": {
        "name": "UnterminatedTransaction",
        "description": "НачатьТранзакцию() without matching ЗафиксироватьТранзакцию/ОтменитьТранзакцию",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "data-integrity"],
    },
    "BSL113": {
        "name": "AssignmentInCondition",
        "description": "Assignment operator inside an Если condition — likely a typo for comparison",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL114": {
        "name": "EmptyModule",
        "description": "Module contains no executable code — remove or populate it",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "suspicious"],
    },
    "BSL115": {
        "name": "DoubleNegatives",
        "description": "Double negation НЕ НЕ — simplify to the positive condition",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "readability"],
    },
    "BSL116": {
        "name": "UseOfObsoleteIterator",
        "description": "Use of obsolete iteration pattern — prefer ДляКаждого/ForEach",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL117": {
        "name": "ProcedureCalledAsFunction",
        "description": "Result of a procedure call is used in an expression — procedures do not return values",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "suspicious"],
    },
    "BSL118": {
        "name": "FunctionShouldHaveReturn",
        "description": "Функция body has no Возврат with a value — returns Неопределено implicitly",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL119": {
        "name": "LineLength",
        "description": "Line length exceeds 120 characters — split into multiple lines",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL120": {
        "name": "TrailingWhitespace",
        "description": "Line has trailing whitespace — remove for consistent diffs",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style"],
    },
    "BSL121": {
        "name": "TabIndentation",
        "description": "Tab character used for indentation — use spaces for consistent formatting",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style"],
    },
    "BSL122": {
        "name": "UnusedParameters",
        "description": "Parameter declared in the signature is never referenced in the body",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "design"],
    },
    "BSL123": {
        "name": "CommentedCode",
        "description": "Comment line appears to contain commented-out code — remove or restore",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "suspicious"],
    },
    "BSL124": {
        "name": "ShortProcedureName",
        "description": "Procedure/function name is shorter than 3 characters — use a descriptive name",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL125": {
        "name": "UseOfAbortOutsideLoop",
        "description": "Прервать/Break used outside a loop — has no effect or causes an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "suspicious"],
    },
    "BSL126": {
        "name": "UseOfContinueOutsideLoop",
        "description": "Продолжить/Continue used outside a loop — has no effect or causes an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "suspicious"],
    },
    "BSL127": {
        "name": "MultipleReturnValues",
        "description": "Multiple Возврат statements at the same nesting level — consolidate to one exit point",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL128": {
        "name": "UnreachableCode",
        "description": "Unreachable code after unconditional Возврат at the top level of a function/procedure body",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL129": {
        "name": "RecursiveCall",
        "description": "Function/procedure directly calls itself — verify that recursion is intentional and guarded",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL130": {
        "name": "LineLength",
        "description": "Comment line exceeds 120 characters — split into multiple shorter lines",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL131": {
        "name": "EmptyRegion",
        "description": "#Область/#Region immediately followed by #КонецОбласти/#EndRegion with no code inside",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style"],
    },
    "BSL132": {
        "name": "DuplicateStringLiteral",
        "description": "String literal appears 4 or more times in the file — extract to a named constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "readability"],
    },
    "BSL133": {
        "name": "RequiredParamAfterOptional",
        "description": "Required parameter appears after an optional (default-valued) parameter in the signature",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "design"],
    },
    "BSL134": {
        "name": "CyclomaticComplexity",
        "description": "Cyclomatic complexity exceeds the allowed maximum — refactor into smaller functions",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["complexity", "design"],
    },
    "BSL135": {
        "name": "NestedFunctionCalls",
        "description": "Function call result passed directly as argument to another function — extract to a variable",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL136": {
        "name": "MissingSpaceBeforeComment",
        "description": "Inline // comment is not preceded by a space — add a space for readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style"],
    },
    "BSL137": {
        "name": "UseOfFindByDescription",
        "description": "НайтиПоНаименованию/FindByDescription performs a full-table scan — use an index or НайтиПоСсылке",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "suspicious"],
    },
    "BSL138": {
        "name": "UseOfDebugOutput",
        "description": "Сообщить()/Message()/Предупреждение() debug output should not be in production code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "debug"],
    },
    "BSL139": {
        "name": "TooLongParameterName",
        "description": "Parameter name is longer than 30 characters — shorten it for readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL140": {
        "name": "UnreachableElseIf",
        "description": "ИначеЕсли/ElsIf branch appears after an unconditional Иначе/Else — it can never be reached",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL141": {
        "name": "MagicBooleanReturn",
        "description": "Function returns literal Истина/Ложь — replace with a direct boolean expression",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL142": {
        "name": "LargeParameterDefaultValue",
        "description": "Default parameter value is longer than 50 characters — move to a named constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL143": {
        "name": "DuplicateElseIfCondition",
        "description": "The same condition appears more than once in an Если/ИначеЕсли chain",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
    },
    "BSL144": {
        "name": "UnnecessaryParentheses",
        "description": "Return value is wrapped in redundant parentheses — remove them",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL145": {
        "name": "StringFormatInsteadOfConcat",
        "description": "Three or more string parts joined with '+' — use СтрШаблон()/StrTemplate() instead",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
    },
    "BSL146": {
        "name": "ModuleInitializationCode",
        "description": "Executable code at module level outside procedures — move to an Инициализация() procedure",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "correctness"],
    },
    "BSL147": {
        "name": "UseOfUICall",
        "description": "ОткрытьФорму()/OpenForm() UI calls should not appear in server-side code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "debug"],
    },
    # ── BSL148–BSL279 — BSL-LS rules not yet implemented (stubs/TODO) ──────
    "BSL148": {
        "name": "AllFunctionPathMustHaveReturn",
        "description": "Not all code paths in the function have a return statement",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["error-handling", "correctness"],
        "implemented": False,
    },
    "BSL149": {
        "name": "AssignAliasFieldsInQuery",
        "description": "Query fields should be assigned aliases for clarity",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "query"],
        "implemented": False,
    },
    "BSL150": {
        "name": "BadWords",
        "description": "Inappropriate or forbidden words found in source code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["convention"],
        "implemented": False,
    },
    "BSL151": {
        "name": "BeginTransactionBeforeTryCatch",
        "description": "НачатьТранзакцию/BeginTransaction must be placed immediately before a Try/Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": False,
    },
    "BSL152": {
        "name": "CachedPublic",
        "description": "Export method in a cached common module — caching and export conflict",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "performance"],
        "implemented": False,
    },
    "BSL153": {
        "name": "CanonicalSpellingKeywords",
        "description": "BSL keyword is not written in canonical (title-case) form",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "style"],
        "implemented": False,
    },
    "BSL154": {
        "name": "CodeAfterAsyncCall",
        "description": "Executable code follows an asynchronous call — result may be lost",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["async", "correctness"],
        "implemented": False,
    },
    "BSL155": {
        "name": "CodeBlockBeforeSub",
        "description": "Executable code appears before procedure/function definitions (module body)",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "design"],
        "implemented": False,
    },
    "BSL156": {
        "name": "CodeOutOfRegion",
        "description": "Code is located outside any #Region/#Область block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "structure"],
        "implemented": False,
    },
    "BSL157": {
        "name": "CommitTransactionOutsideTryCatch",
        "description": "ЗафиксироватьТранзакцию/CommitTransaction must be inside a Try/Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": False,
    },
    "BSL158": {
        "name": "CommonModuleAssign",
        "description": "Common module object is assigned a value — this is always an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "module"],
        "implemented": False,
    },
    "BSL159": {
        "name": "CommonModuleInvalidType",
        "description": "Common module has incompatible type flags (e.g. Global + Privileged)",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["design", "module"],
        "implemented": False,
    },
    "BSL160": {
        "name": "CommonModuleMissingAPI",
        "description": "Common module has no exported methods — consider making it non-public",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "module", "api"],
        "implemented": False,
    },
    "BSL161": {
        "name": "CommonModuleNameCached",
        "description": "Cached common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL162": {
        "name": "CommonModuleNameClient",
        "description": "Client common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL163": {
        "name": "CommonModuleNameClientServer",
        "description": "Client-server common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL164": {
        "name": "CommonModuleNameFullAccess",
        "description": "Full-access (privileged) common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL165": {
        "name": "CommonModuleNameGlobal",
        "description": "Global common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL166": {
        "name": "CommonModuleNameGlobalClient",
        "description": "Global client common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL167": {
        "name": "CommonModuleNameServerCall",
        "description": "Server-call common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL168": {
        "name": "CommonModuleNameWords",
        "description": "Common module name uses forbidden words",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": False,
    },
    "BSL169": {
        "name": "CompilationDirectiveLost",
        "description": "Compilation directive on the method is missing or differs from calling context",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "directive"],
        "implemented": False,
    },
    "BSL170": {
        "name": "CompilationDirectiveNeedLess",
        "description": "Redundant compilation directive on the method",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "directive"],
        "implemented": False,
    },
    "BSL171": {
        "name": "CrazyMultilineString",
        "description": "Multiline string literal uses inconsistent indentation",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
        "implemented": False,
    },
    "BSL172": {
        "name": "DataExchangeLoading",
        "description": "Modification handlers do not check ОбменДаннымиЗагрузка/DataExchangeLoad flag",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "data-exchange"],
        "implemented": False,
    },
    "BSL173": {
        "name": "DeletingCollectionItem",
        "description": "Collection item is deleted inside a Для Каждого/For Each loop — may cause errors",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "loop"],
        "implemented": False,
    },
    "BSL174": {
        "name": "DenyIncompleteValues",
        "description": "НачатьТранзакцию used without ОтменитьТранзакцию in error path",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["transaction", "error-handling"],
        "implemented": False,
    },
    "BSL175": {
        "name": "DeprecatedAttributes8312",
        "description": "Deprecated platform attribute used (removed in 8.3.12+)",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": False,
    },
    "BSL176": {
        "name": "DeprecatedMethodCall",
        "description": "Deprecated platform method called — use the modern replacement",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated"],
        "implemented": False,
    },
    "BSL177": {
        "name": "DeprecatedMethods8310",
        "description": "Platform method deprecated since 8.3.10",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": False,
    },
    "BSL178": {
        "name": "DeprecatedMethods8317",
        "description": "Platform method deprecated since 8.3.17",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": False,
    },
    "BSL179": {
        "name": "DeprecatedTypeManagedForm",
        "description": "Deprecated type УправляемаяФорма/ManagedForm used directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": False,
    },
    "BSL180": {
        "name": "DisableSafeMode",
        "description": "УстановитьБезопасныйРежим(Ложь)/SetSafeMode(False) disables security sandbox",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL181": {
        "name": "DuplicatedInsertionIntoCollection",
        "description": "The same element is inserted into the collection more than once",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
        "implemented": False,
    },
    "BSL182": {
        "name": "ExcessiveAutoTestCheck",
        "description": "АвтоТестПроверка check is excessive or incorrectly placed",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["testing"],
        "implemented": False,
    },
    "BSL183": {
        "name": "ExecuteExternalCode",
        "description": "Выполнить()/Execute() runs arbitrary external code — security risk",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL184": {
        "name": "ExecuteExternalCodeInCommonModule",
        "description": "Dynamic code execution (Выполнить/Execute) inside a common module",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security", "module"],
        "implemented": False,
    },
    "BSL185": {
        "name": "ExternalAppStarting",
        "description": "ЗапуститьПриложение()/StartApplication() launches external processes",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL186": {
        "name": "ExtraCommas",
        "description": "Trailing or extra comma in method call or declaration",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["syntax", "style"],
        "implemented": False,
    },
    "BSL187": {
        "name": "FieldsFromJoinsWithoutIsNull",
        "description": "Fields from outer joins used without ЕСТЬ NULL/IS NULL check",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["query", "correctness"],
        "implemented": False,
    },
    "BSL188": {
        "name": "FileSystemAccess",
        "description": "Direct file system access — may fail in web client or thin client contexts",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "compatibility"],
        "implemented": False,
    },
    "BSL189": {
        "name": "ForbiddenMetadataName",
        "description": "Metadata object name is in the list of forbidden names",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "convention"],
        "implemented": False,
    },
    "BSL190": {
        "name": "FormDataToValue",
        "description": "ДанныеФормыВЗначение()/FormDataToValue() is slow — prefer working with server objects directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "ui"],
        "implemented": False,
    },
    "BSL191": {
        "name": "FullOuterJoinQuery",
        "description": "Full outer join (ПОЛНОЕ ВНЕШНЕЕ/FULL OUTER JOIN) in query — usually a design mistake",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "design"],
        "implemented": False,
    },
    "BSL192": {
        "name": "FunctionNameStartsWithGet",
        "description": "Function name should start with 'Получить'/'Get' to indicate it returns a value",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["naming", "convention"],
        "implemented": False,
    },
    "BSL193": {
        "name": "FunctionOutParameter",
        "description": "Function modifies a reference parameter (out-parameter) — use a Procedure instead",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design"],
        "implemented": False,
    },
    "BSL194": {
        "name": "FunctionReturnsSamePrimitive",
        "description": "Function always returns the same primitive value — it may be simplified",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "design"],
        "implemented": False,
    },
    "BSL195": {
        "name": "GetFormMethod",
        "description": "ПолучитьФорму()/GetForm() usage is deprecated — open forms via OpenForm()",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": False,
    },
    "BSL196": {
        "name": "GlobalContextMethodCollision8312",
        "description": "Method name collides with a global context method added in 8.3.12",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "compatibility"],
        "implemented": False,
    },
    "BSL197": {
        "name": "IfElseDuplicatedCodeBlock",
        "description": "Identical code block appears in multiple branches of If/ElseIf",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "duplicate"],
        "implemented": False,
    },
    "BSL198": {
        "name": "IfElseDuplicatedCondition",
        "description": "Duplicate condition in If/ElseIf chain — branch is unreachable",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
        "implemented": False,
    },
    "BSL199": {
        "name": "IfElseIfEndsWithElse",
        "description": "If/ElseIf chain does not end with an Else branch",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "robustness"],
        "implemented": False,
    },
    "BSL200": {
        "name": "IncorrectLineBreak",
        "description": "Line break character used incorrectly or inconsistently",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": False,
    },
    "BSL201": {
        "name": "IncorrectUseLikeInQuery",
        "description": "ПОДОБНО/LIKE pattern in query is written incorrectly",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["query", "correctness"],
        "implemented": False,
    },
    "BSL202": {
        "name": "IncorrectUseOfStrTemplate",
        "description": "СтрШаблон()/StrTemplate() is called with mismatched argument count",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness"],
        "implemented": False,
    },
    "BSL203": {
        "name": "InternetAccess",
        "description": "Direct internet access — should be isolated or proxied for security",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL204": {
        "name": "InvalidCharacterInFile",
        "description": "File contains invalid or non-printable characters",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "encoding"],
        "implemented": False,
    },
    "BSL205": {
        "name": "IsInRoleMethod",
        "description": "РольДоступна()/IsInRole() is used — prefer permission-based access control",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": False,
    },
    "BSL206": {
        "name": "JoinWithSubQuery",
        "description": "Query join uses a subquery — may cause poor performance",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL207": {
        "name": "JoinWithVirtualTable",
        "description": "Query join with a virtual table without parameters — may return too many rows",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL208": {
        "name": "LatinAndCyrillicSymbolInWord",
        "description": "Identifier contains both Latin and Cyrillic characters — visually ambiguous",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "naming"],
        "implemented": False,
    },
    "BSL209": {
        "name": "LogicalOrInJoinQuerySection",
        "description": "Logical OR (ИЛИ/OR) in JOIN ON condition — causes performance issues",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL210": {
        "name": "LogicalOrInTheWhereSectionOfQuery",
        "description": "Logical OR (ИЛИ/OR) in WHERE clause may prevent index usage",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL211": {
        "name": "MetadataObjectNameLength",
        "description": "Metadata object name exceeds maximum allowed length",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "convention"],
        "implemented": False,
    },
    "BSL212": {
        "name": "MissedRequiredParameter",
        "description": "Required parameter is missing in method call",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness"],
        "implemented": False,
    },
    "BSL213": {
        "name": "MissingCommonModuleMethod",
        "description": "Called method does not exist in the referenced common module",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "module"],
        "implemented": False,
    },
    "BSL214": {
        "name": "MissingEventSubscriptionHandler",
        "description": "Event subscription references a handler method that does not exist",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "events"],
        "implemented": False,
    },
    "BSL215": {
        "name": "MissingParameterDescription",
        "description": "Export method parameter has no description in the comment block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["documentation", "api"],
        "implemented": False,
    },
    "BSL216": {
        "name": "MissingSpace",
        "description": "Missing space before or after an operator or keyword",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": False,
    },
    "BSL217": {
        "name": "MissingTempStorageDeletion",
        "description": "Temporary storage (УдалитьИзВременногоХранилища) is not deleted after use",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["resource-management", "memory"],
        "implemented": False,
    },
    "BSL218": {
        "name": "MissingTemporaryFileDeletion",
        "description": "Temporary file created with GetTempFileName is not deleted after use",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["resource-management"],
        "implemented": False,
    },
    "BSL219": {
        "name": "MissingVariablesDescription",
        "description": "Module-level variable declaration has no description comment",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["documentation", "convention"],
        "implemented": True,
    },
    "BSL220": {
        "name": "MultilineStringInQuery",
        "description": "Multiline string literal used inside a query text",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "style"],
        "implemented": False,
    },
    "BSL221": {
        "name": "MultilingualStringHasAllDeclaredLanguages",
        "description": "НСтр() string does not include all languages declared in the configuration",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["localization"],
        "implemented": False,
    },
    "BSL222": {
        "name": "MultilingualStringUsingWithTemplate",
        "description": "НСтр() is used inside СтрШаблон() — localized strings should be composed differently",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["localization", "style"],
        "implemented": False,
    },
    "BSL223": {
        "name": "NestedConstructorsInStructureDeclaration",
        "description": "Structure constructor contains nested constructors — hard to read and maintain",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["readability", "design"],
        "implemented": False,
    },
    "BSL224": {
        "name": "NestedFunctionInParameters",
        "description": "Function call is used as an argument to another function — reduces readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["readability", "brain-overload"],
        "implemented": False,
    },
    "BSL225": {
        "name": "NumberOfValuesInStructureConstructor",
        "description": "Структура/Structure constructor has too many initial values",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "readability"],
        "implemented": False,
    },
    "BSL226": {
        "name": "OSUsersMethod",
        "description": "ПользователиОС()/OSUsers() is used — OS user enumeration is a security concern",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL227": {
        "name": "OneStatementPerLine",
        "description": "Multiple statements on one line — reduces readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "convention"],
        "implemented": False,
    },
    "BSL228": {
        "name": "OrderOfParams",
        "description": "Method parameter order does not follow the agreed convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "convention"],
        "implemented": False,
    },
    "BSL229": {
        "name": "OrdinaryAppSupport",
        "description": "Code uses API not supported in Ordinary (thick) application mode",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["compatibility", "ui"],
        "implemented": False,
    },
    "BSL230": {
        "name": "PairingBrokenTransaction",
        "description": "НачатьТранзакцию/ЗафиксироватьТранзакцию/ОтменитьТранзакцию calls are unbalanced",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "correctness"],
        "implemented": False,
    },
    "BSL231": {
        "name": "PrivilegedModuleMethodCall",
        "description": "Method from a privileged module is called from a non-privileged context",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": False,
    },
    "BSL232": {
        "name": "ProtectedModule",
        "description": "Module is protected (ЗащищенныйМодуль) — source is not accessible",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design"],
        "implemented": False,
    },
    "BSL233": {
        "name": "PublicMethodsDescription",
        "description": "Exported method has no documentation comment",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["documentation", "api"],
        "implemented": False,
    },
    "BSL234": {
        "name": "QueryNestedFieldsByDot",
        "description": "Nested (dot-notation) field access in query text — causes implicit joins",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL235": {
        "name": "QueryParseError",
        "description": "Embedded query text has a syntax error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["query", "correctness"],
        "implemented": False,
    },
    "BSL236": {
        "name": "QueryToMissingMetadata",
        "description": "Query references a metadata object that does not exist in the configuration",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["query", "correctness"],
        "implemented": False,
    },
    "BSL237": {
        "name": "RedundantAccessToObject",
        "description": "Redundant object access — intermediate result is not used",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "performance"],
        "implemented": False,
    },
    "BSL238": {
        "name": "RefOveruse",
        "description": "Excessive use of .Ссылка/.Ref — retrieve the object once and reuse",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["performance", "readability"],
        "implemented": False,
    },
    "BSL239": {
        "name": "ReservedParameterNames",
        "description": "Parameter name shadows a built-in platform identifier",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "suspicious"],
        "implemented": False,
    },
    "BSL240": {
        "name": "RewriteMethodParameter",
        "description": "Method parameter is overwritten before being read — likely a mistake",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
        "implemented": False,
    },
    "BSL241": {
        "name": "SameMetadataObjectAndChildNames",
        "description": "Metadata object and its child (attribute/tabular section) share the same name",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "design"],
        "implemented": False,
    },
    "BSL242": {
        "name": "ScheduledJobHandler",
        "description": "Scheduled job handler method has incorrect signature or is missing",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "scheduled-jobs"],
        "implemented": False,
    },
    "BSL243": {
        "name": "SelfInsertion",
        "description": "Object is inserted into itself — causes infinite recursion or error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "suspicious"],
        "implemented": False,
    },
    "BSL244": {
        "name": "ServerCallsInFormEvents",
        "description": "Server call inside a client form event handler without &НаКлиентеНаСервере",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "ui", "performance"],
        "implemented": False,
    },
    "BSL245": {
        "name": "ServerSideExportFormMethod",
        "description": "Form module export method is marked &НаСервере — inaccessible from client",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "ui"],
        "implemented": False,
    },
    "BSL246": {
        "name": "SetPermissionsForNewObjects",
        "description": "НастройкаПравДоступаДляНовыхОбъектов is called incorrectly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": False,
    },
    "BSL247": {
        "name": "SetPrivilegedMode",
        "description": "УстановитьПривилегированныйРежим(Истина)/SetPrivilegedMode(True) elevates permissions",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL248": {
        "name": "SeveralCompilerDirectives",
        "description": "Method has multiple conflicting compilation directives",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "directive"],
        "implemented": False,
    },
    "BSL249": {
        "name": "StyleElementConstructors",
        "description": "Style element is created with a constructor instead of using built-in styles",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["ui", "design"],
        "implemented": False,
    },
    "BSL250": {
        "name": "TempFilesDir",
        "description": "КаталогВременныхФайлов()/TempFilesDir() used — may cause issues in web context",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "compatibility"],
        "implemented": False,
    },
    "BSL251": {
        "name": "TernaryOperatorUsage",
        "description": "Ternary operator (?(cond, true, false)) reduces readability — consider If/Else",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "readability"],
        "implemented": False,
    },
    "BSL252": {
        "name": "ThisObjectAssign",
        "description": "ЭтотОбъект/ThisObject is assigned a value — always an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "suspicious"],
        "implemented": False,
    },
    "BSL253": {
        "name": "TimeoutsInExternalResources",
        "description": "External resource access has no timeout set — may hang indefinitely",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["robustness", "performance"],
        "implemented": False,
    },
    "BSL254": {
        "name": "TransferringParametersBetweenClientAndServer",
        "description": "Large or non-serializable object is passed between client and server",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "design"],
        "implemented": False,
    },
    "BSL255": {
        "name": "TryNumber",
        "description": "Numeric conversion inside Попытка/Try — exception obscures conversion errors",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["error-handling", "suspicious"],
        "implemented": False,
    },
    "BSL256": {
        "name": "Typo",
        "description": "Possible spelling mistake found in comments or string literals",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention"],
        "implemented": True,
    },
    "BSL257": {
        "name": "UnaryPlusInConcatenation",
        "description": "Unary plus (+) before a value in string concatenation — usually a mistake",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
        "implemented": False,
    },
    "BSL258": {
        "name": "UnionAll",
        "description": "ОБЪЕДИНИТЬ/UNION without ALL causes implicit deduplication — use UNION ALL",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL259": {
        "name": "UnknownPreprocessorSymbol",
        "description": "Unknown preprocessor symbol used in #Если/#If directive",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "directive"],
        "implemented": False,
    },
    "BSL260": {
        "name": "UnsafeFindByCode",
        "description": "НайтиПоКоду()/FindByCode() is called without existence check — may return Undefined",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "robustness"],
        "implemented": False,
    },
    "BSL261": {
        "name": "UnsafeSafeModeMethodCall",
        "description": "Safe-mode method called in a context where it may not be available",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["security", "correctness"],
        "implemented": False,
    },
    "BSL262": {
        "name": "UsageWriteLogEvent",
        "description": "ЗаписьЖурналаРегистрации/WriteLogEvent called with incorrect parameters",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "logging"],
        "implemented": False,
    },
    "BSL263": {
        "name": "UseLessForEach",
        "description": "Для Каждого/For Each loop body does nothing useful with the iteration variable",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["redundant", "suspicious"],
        "implemented": False,
    },
    "BSL264": {
        "name": "UseSystemInformation",
        "description": "СистемнаяИнформация()/SystemInformation() exposes sensitive system data",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL265": {
        "name": "UselessTernaryOperator",
        "description": "Ternary operator returns its condition directly — simplify to the condition",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "readability"],
        "implemented": False,
    },
    "BSL266": {
        "name": "UsingCancelParameter",
        "description": "Параметр «Отказ»/Cancel is modified but not checked correctly in the handler",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "events"],
        "implemented": False,
    },
    "BSL267": {
        "name": "UsingExternalCodeTools",
        "description": "External code execution tools (AddIn, COM, WSProxy) are used",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": False,
    },
    "BSL268": {
        "name": "UsingFindElementByString",
        "description": "НайтиПоНаименованию()/FindByDescription() used — slow full-text search",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance"],
        "implemented": False,
    },
    "BSL269": {
        "name": "UsingLikeInQuery",
        "description": "ПОДОБНО/LIKE operator in query — may prevent index usage and cause full scans",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL270": {
        "name": "UsingModalWindows",
        "description": "Modal window (Предупреждение, Вопрос, ВвестиЗначение) used in managed UI",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": False,
    },
    "BSL271": {
        "name": "UsingObjectNotAvailableUnix",
        "description": "Object or method not available on Linux/Unix server",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["compatibility"],
        "implemented": False,
    },
    "BSL272": {
        "name": "UsingSynchronousCalls",
        "description": "Synchronous call to a server method — should be async in managed UI",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "ui"],
        "implemented": False,
    },
    "BSL273": {
        "name": "VirtualTableCallWithoutParameters",
        "description": "Virtual table (e.g. РегистрНакопления.Остатки) called without parameters",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": False,
    },
    "BSL274": {
        "name": "WrongDataPathForFormElements",
        "description": "Form element data path references a non-existent attribute",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "ui"],
        "implemented": False,
    },
    "BSL275": {
        "name": "WrongHttpServiceHandler",
        "description": "HTTP service handler method has incorrect signature",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "http"],
        "implemented": False,
    },
    "BSL276": {
        "name": "WrongUseFunctionProceedWithCall",
        "description": "ПродолжитьВызов()/ProceedWithCall() used incorrectly in extension method",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "extensions"],
        "implemented": False,
    },
    "BSL277": {
        "name": "WrongUseOfRollbackTransactionMethod",
        "description": "ОтменитьТранзакцию/RollbackTransaction called outside Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": False,
    },
    "BSL278": {
        "name": "WrongWebServiceHandler",
        "description": "Web service operation handler method has incorrect signature",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "web-service"],
        "implemented": False,
    },
    "BSL279": {
        "name": "YoLetterUsage",
        "description": "Letter «ё» used in identifiers or string literals — use «е» for consistency",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": False,
    },
    "BSL280": {
        "name": "UnknownMetadataObjectReference",
        "description": (
            "Metadata collection chain names an object not found in the indexed configuration export"
        ),
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["metadata", "correctness"],
        "implemented": True,
    },
}


# ---------------------------------------------------------------------------
# Russian descriptions (taken from BSL Language Server ru-locale)
# Keys that are absent will fall back to the English description in RULE_METADATA.
# ---------------------------------------------------------------------------

RULE_DESCRIPTIONS_RU: dict[str, str] = {
    "BSL001": "Синтаксическая ошибка",
    "BSL002": "Метод слишком длинный",
    "BSL003": "Неэкспортный метод в области программного интерфейса",
    "BSL004": "Пустой блок кода (обработчик исключений, ветка «Тогда», …)",
    "BSL005": "Использование жёсткого кодирования сетевых адресов",
    "BSL006": "Использование жёстко заданных путей к файлам",
    "BSL007": "Неиспользуемая локальная переменная",
    "BSL008": "Слишком много операторов «Возврат»",
    "BSL009": "Присвоение переменной самой себе",
    "BSL010": "Бессмысленный оператор «Возврат»",
    "BSL011": "Когнитивная сложность метода превышает допустимый порог",
    "BSL012": "Жёстко закодированные пароли или ключи",
    "BSL013": "Закомментированный код",
    "BSL014": "Строка слишком длинная",
    "BSL015": "Слишком много необязательных параметров",
    "BSL016": "Нестандартная область",
    "BSL017": "Экспортный метод в модуле команды или формы",
    "BSL018": "«ВызватьИсключение» только со строковым литералом",
    "BSL019": "Цикломатическая сложность метода превышает допустимый порог",
    "BSL020": "Превышена допустимая вложенность операторов",
    "BSL021": "Параметр «Знач» не используется внутри метода",
    "BSL022": "Устаревший метод «Предупреждение»",
    "BSL023": "Служебный тег в комментарии",
    "BSL024": "Комментарий без пробела после «//»",
    "BSL025": "Отсутствует точка с запятой в конце оператора",
    "BSL026": "Пустая область",
    "BSL027": "Использование оператора «Перейти»",
    "BSL028": "Код без обработки исключений",
    "BSL029": "Магическое число",
    "BSL030": "Точка с запятой в конце строки объявления процедуры",
    "BSL031": "Слишком много параметров",
    "BSL032": "Функция может не возвращать значение",
    "BSL033": "Запрос в цикле",
    "BSL034": "Переменная ИнформацияОбОшибке() не используется",
    "BSL035": "Дублированный строковый литерал",
    "BSL036": "Сложное условие",
    "BSL037": "Имя метода совпадает с именем встроенной функции платформы",
    "BSL038": "Конкатенация строк в цикле",
    "BSL039": "Вложенный тернарный оператор",
    "BSL040": "Использование «ЭтаФорма» вне обработчика событий",
    "BSL041": "Устаревший вызов с ОписаниеОповещения к модальному окну",
    "BSL042": "Пустой экспортный метод",
    "BSL043": "Слишком много локальных переменных",
    "BSL044": "Функция не возвращает значение",
    "BSL045": "Многострочная строка через конкатенацию",
    "BSL046": "Отсутствует ветка «Иначе»",
    "BSL047": "Магическая дата «ТекущаяДата»",
    "BSL048": "Пустой файл",
    "BSL049": "«ВызватьИсключение» на уровне тела метода вне Попытка",
    "BSL050": "Длинная транзакция",
    "BSL051": "Недостижимый код",
    "BSL052": "Условие всегда истинно или всегда ложно",
    "BSL053": "Использование «Выполнить» с динамическим кодом",
    "BSL054": "Переменная на уровне модуля",
    "BSL055": "Несколько последовательных пустых строк",
    "BSL056": "Слишком короткое имя метода",
    "BSL057": "Устаревшие методы ввода данных (ВвестиЗначение и т.д.)",
    "BSL058": "Запрос без условия WHERE",
    "BSL059": "Сравнение с булевым литералом",
    "BSL060": "Двойное отрицание",
    "BSL061": "Оператор «Прервать» в конце тела цикла",
    "BSL062": "Неиспользуемый параметр",
    "BSL063": "Слишком большой модуль",
    "BSL064": "Процедура возвращает значение",
    "BSL065": "Экспортный метод без описания",
    "BSL066": "Устаревшая функция Найти() — используйте СтрНайти()",
    "BSL067": "Объявление «Перем» после исполняемого кода",
    "BSL068": "Слишком много ветвей «ИначеЕсли»",
    "BSL069": "Бесконечный цикл",
    "BSL070": "Пустое тело цикла",
    "BSL077": "Запрос ВЫБРАТЬ * — перечислите колонки явно",
    "BSL097": "Использование «ТекущаяДата» — замените на «ТекущаяДатаСеанса»",
    "BSL111": "Смешение кириллицы и латиницы в имени идентификатора",
    "BSL117": "Результат вызова процедуры используется в выражении",
    "BSL125": "Оператор «Прервать» вне цикла",
    "BSL126": "Оператор «Продолжить» вне цикла",
    "BSL133": "Обязательный параметр после необязательного",
    "BSL140": "Ветка «ИначеЕсли» после безусловного «Иначе» — недостижима",
    "BSL143": "Одинаковое условие в цепочке «Если/ИначеЕсли»",
    "BSL147": "Открытие формы в серверном коде",
    # ── BSL148–BSL279 — заглушки для правил BSL-LS ──────────────────────────
    "BSL148": "Не все ветки функции возвращают значение",
    "BSL149": "Полям запроса следует назначать псевдонимы",
    "BSL150": "Нежелательные слова в исходном коде",
    "BSL151": "НачатьТранзакцию должна быть перед блоком Попытка",
    "BSL152": "Экспортный метод в кэшируемом общем модуле",
    "BSL153": "Неканоническое написание ключевого слова BSL",
    "BSL154": "Код после асинхронного вызова может не выполниться",
    "BSL155": "Исполняемый код перед определениями процедур и функций",
    "BSL156": "Код расположен вне области (#Область)",
    "BSL157": "ЗафиксироватьТранзакцию должна быть внутри блока Попытка",
    "BSL158": "Присвоение значения объекту общего модуля",
    "BSL159": "Несовместимые флаги типа общего модуля",
    "BSL160": "Общий модуль не содержит экспортных методов",
    "BSL161": "Имя кэшируемого общего модуля не соответствует соглашению",
    "BSL162": "Имя клиентского общего модуля не соответствует соглашению",
    "BSL163": "Имя клиент-серверного общего модуля не соответствует соглашению",
    "BSL164": "Имя привилегированного общего модуля не соответствует соглашению",
    "BSL165": "Имя глобального общего модуля не соответствует соглашению",
    "BSL166": "Имя глобального клиентского общего модуля не соответствует соглашению",
    "BSL167": "Имя модуля серверного вызова не соответствует соглашению",
    "BSL168": "Недопустимые слова в имени общего модуля",
    "BSL169": "Потерянная директива компиляции метода",
    "BSL170": "Лишняя директива компиляции на методе",
    "BSL171": "Многострочная строка с непоследовательными отступами",
    "BSL172": "Обработчики не проверяют флаг ОбменДаннымиЗагрузка",
    "BSL173": "Удаление элемента коллекции в цикле Для Каждого",
    "BSL174": "НачатьТранзакцию без ОтменитьТранзакцию в пути ошибки",
    "BSL175": "Устаревший атрибут платформы (удалён в 8.3.12+)",
    "BSL176": "Вызов устаревшего метода платформы",
    "BSL177": "Метод платформы устарел начиная с версии 8.3.10",
    "BSL178": "Метод платформы устарел начиная с версии 8.3.17",
    "BSL179": "Использование устаревшего типа УправляемаяФорма",
    "BSL180": "Отключение безопасного режима",
    "BSL181": "Дублирующаяся вставка в коллекцию",
    "BSL182": "Избыточная проверка АвтоТестПроверка",
    "BSL183": "Выполнение произвольного кода через Выполнить()",
    "BSL184": "Динамическое выполнение кода в общем модуле",
    "BSL185": "Запуск внешнего приложения через ЗапуститьПриложение()",
    "BSL186": "Лишние запятые в вызове или объявлении",
    "BSL187": "Поля внешних соединений без проверки ЕСТЬ NULL",
    "BSL188": "Прямой доступ к файловой системе",
    "BSL189": "Имя объекта метаданных содержится в списке запрещённых",
    "BSL190": "Использование ДанныеФормыВЗначение() — медленная операция",
    "BSL191": "Полное внешнее соединение в запросе",
    "BSL192": "Имя функции должно начинаться с «Получить»",
    "BSL193": "Функция изменяет параметр-ссылку (out-параметр)",
    "BSL194": "Функция всегда возвращает одно и то же примитивное значение",
    "BSL195": "Использование устаревшего ПолучитьФорму()",
    "BSL196": "Имя метода совпадает с методом глобального контекста 8.3.12",
    "BSL197": "Одинаковый блок кода в нескольких ветках Если/ИначеЕсли",
    "BSL198": "Дублирующееся условие в цепочке Если/ИначеЕсли",
    "BSL199": "Цепочка Если/ИначеЕсли не завершается веткой Иначе",
    "BSL200": "Некорректный перенос строки",
    "BSL201": "Некорректное использование ПОДОБНО в запросе",
    "BSL202": "Несоответствие числа аргументов в СтрШаблон()",
    "BSL203": "Прямой доступ к интернет-ресурсам",
    "BSL204": "Файл содержит недопустимые символы",
    "BSL205": "Использование РольДоступна() — предпочтительна проверка прав",
    "BSL206": "Соединение с подзапросом в запросе",
    "BSL207": "Соединение с виртуальной таблицей без параметров",
    "BSL208": "Идентификатор содержит кириллицу и латиницу одновременно",
    "BSL209": "Логическое ИЛИ в секции соединения запроса",
    "BSL210": "Логическое ИЛИ в секции ГДЕ запроса",
    "BSL211": "Имя объекта метаданных превышает допустимую длину",
    "BSL212": "Пропущен обязательный параметр в вызове метода",
    "BSL213": "Вызываемый метод отсутствует в общем модуле",
    "BSL214": "Обработчик подписки на событие не существует",
    "BSL215": "Параметр экспортного метода без описания в комментарии",
    "BSL216": "Пропущен пробел перед оператором или ключевым словом",
    "BSL217": "Временное хранилище не удаляется после использования",
    "BSL218": "Временный файл не удаляется после использования",
    "BSL219": "Переменная уровня модуля без комментария-описания",
    "BSL220": "Многострочная строка внутри текста запроса",
    "BSL221": "НСтр() не содержит всех языков, объявленных в конфигурации",
    "BSL222": "НСтр() используется внутри СтрШаблон()",
    "BSL223": "Вложенные конструкторы в объявлении структуры",
    "BSL224": "Вложенный вызов функции в параметрах другой функции",
    "BSL225": "Слишком много значений в конструкторе Структуры",
    "BSL226": "Использование ПользователиОС() — угроза безопасности",
    "BSL227": "Несколько операторов на одной строке",
    "BSL228": "Порядок параметров метода не соответствует соглашению",
    "BSL229": "Код использует API, недоступный в обычном приложении",
    "BSL230": "Несбалансированные вызовы НачатьТранзакцию/ЗафиксироватьТранзакцию/ОтменитьТранзакцию",
    "BSL231": "Вызов метода привилегированного модуля из непривилегированного контекста",
    "BSL232": "Защищённый модуль — исходный текст недоступен",
    "BSL233": "Экспортный метод без документирующего комментария",
    "BSL234": "Обращение к вложенным полям через точку в тексте запроса",
    "BSL235": "Синтаксическая ошибка в тексте встроенного запроса",
    "BSL236": "Запрос обращается к несуществующим метаданным",
    "BSL237": "Избыточное обращение к объекту — промежуточный результат не используется",
    "BSL238": "Избыточное использование .Ссылка",
    "BSL239": "Имя параметра совпадает со встроенным идентификатором платформы",
    "BSL240": "Параметр метода перезаписывается до первого использования",
    "BSL241": "Объект метаданных и его дочерний объект имеют одинаковое имя",
    "BSL242": "Обработчик регламентного задания имеет некорректную сигнатуру",
    "BSL243": "Объект вставляется сам в себя",
    "BSL244": "Серверный вызов в обработчике события формы",
    "BSL245": "Экспортный метод формы помечен &НаСервере",
    "BSL246": "Некорректный вызов НастройкаПравДоступаДляНовыхОбъектов",
    "BSL247": "Установка привилегированного режима",
    "BSL248": "Несколько конфликтующих директив компиляции на методе",
    "BSL249": "Использование конструктора элемента стиля",
    "BSL250": "Использование КаталогВременныхФайлов()",
    "BSL251": "Использование тернарного оператора снижает читаемость",
    "BSL252": "Присвоение значения ЭтотОбъект",
    "BSL253": "Обращение к внешним ресурсам без установки таймаута",
    "BSL254": "Передача несериализуемых данных между клиентом и сервером",
    "BSL255": "Числовое преобразование внутри блока Попытка",
    "BSL256": "Орфографическая ошибка в комментарии или строковом литерале",
    "BSL257": "Унарный плюс перед значением при конкатенации строк",
    "BSL258": "ОБЪЕДИНИТЬ без ВСЕХ вызывает неявную дедупликацию",
    "BSL259": "Неизвестный символ препроцессора в директиве #Если",
    "BSL260": "НайтиПоКоду() без проверки существования результата",
    "BSL261": "Вызов метода безопасного режима в недопустимом контексте",
    "BSL262": "Некорректные параметры ЗаписьЖурналаРегистрации()",
    "BSL263": "Цикл Для Каждого не использует переменную итерации",
    "BSL264": "Использование СистемнаяИнформация() раскрывает системные данные",
    "BSL265": "Тернарный оператор возвращает само условие — упростите",
    "BSL266": "Параметр «Отказ» изменяется некорректно",
    "BSL267": "Использование инструментов выполнения внешнего кода",
    "BSL268": "НайтиПоНаименованию() — медленный полнотекстовый поиск",
    "BSL269": "Оператор ПОДОБНО может привести к полному сканированию таблицы",
    "BSL270": "Использование модальных окон в управляемом UI",
    "BSL271": "Объект или метод недоступен на Linux/Unix-сервере",
    "BSL272": "Синхронный серверный вызов в управляемом интерфейсе",
    "BSL273": "Обращение к виртуальной таблице без параметров",
    "BSL274": "Путь к данным реквизита формы не существует",
    "BSL275": "Обработчик HTTP-сервиса имеет некорректную сигнатуру",
    "BSL276": "Некорректное использование ПродолжитьВызов() в расширении",
    "BSL277": "ОтменитьТранзакцию вызвана вне блока Исключение",
    "BSL278": "Обработчик веб-сервиса имеет некорректную сигнатуру",
    "BSL279": "Использование буквы «ё» в идентификаторах",
    "BSL280": "Ссылка на отсутствующий в конфигурации объект метаданных",
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
    "BSL018": "Prefer extended ВызватьИсключение(..., category, code, ...) (8.3.21+) or a variable, not a bare literal.",
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
    "BSL065": "Add a // Description comment on the line before the Export method declaration.",
    "BSL066": "Replace Найти() with СтрНайти() / StrFind().",
    "BSL067": "Move all Перем declarations to the start of the method, before any executable statements.",
    "BSL068": "Replace long ИначеЕсли chain with a dictionary/map lookup or polymorphism.",
    "BSL069": "Add a Прервать or exit condition to prevent an infinite loop.",
    "BSL070": "Add a comment or remove the empty loop body.",
    "BSL071": "Extract the number to a named constant: Конст МаксКоличество = 100;",
    "BSL072": "Use МассивСтрок = Новый Массив; and join with СтрСоединить() after the loop.",
    "BSL073": "Add an Иначе branch to handle unexpected values explicitly.",
    "BSL074": "Resolve the TODO/FIXME or create a task in your issue tracker.",
    "BSL075": "Pass the variable as a parameter or return it as a function result.",
    "BSL076": "Rewrite as a positive condition: НЕ А → use the positive predicate if available.",
    "BSL077": "List columns explicitly: ВЫБРАТЬ Поле1, Поле2 ИЗ instead of ВЫБРАТЬ *.",
    "BSL078": "Add a descriptive message: ВызватьИсключение НСтр(\"ru = 'Reason'\");",
    "BSL079": "Replace Goto with structured control flow: loops, conditions, or procedures.",
    "BSL080": "Log the error with ЗаписьЖурналаРегистрации or re-raise with ВызватьИсключение.",
    "BSL081": "Assign intermediate results to named variables to improve readability.",
    "BSL082": "Add a newline at the end of the file.",
    "BSL083": "Move module-level state into a dedicated data structure or configuration object.",
    "BSL084": "Add 'Возврат <value>;' or change 'Функция' to 'Процедура'.",
    "BSL085": "Remove the constant condition — the branch always or never executes.",
    "BSL086": "Collect IDs in a list, then make a single batched HTTP request outside the loop.",
    "BSL087": "Create the object once before the loop and reuse it, or use a factory method.",
    "BSL088": "Add a // Parameters section to the comment before the Export method.",
    "BSL089": "Move НачатьТранзакцию/ЗафиксироватьТранзакцию outside the loop.",
    "BSL090": "Move connection strings to environment variables or configuration parameters.",
    "BSL091": "Remove the Иначе keyword — the code after the Если block is only reached when the condition is false.",
    "BSL092": "Remove the empty Иначе or add a comment explaining why it is intentionally empty.",
    "BSL093": "Use ЗначениеЗаполнено() or explicit '= Неопределено' comparison instead of NULL.",
    "BSL094": "Remove the no-op assignment: += 0 or *= 1 has no effect.",
    "BSL095": "Split the line into separate statements for readability.",
    "BSL096": "Add a // Description comment block before the Export method.",
    "BSL097": "Replace ТекущаяДата() with ТекущаяДатаСеанса() for consistent session-based time.",
    "BSL098": "Refactor to avoid dynamic code execution — use explicit calls instead of Выполнить().",
    "BSL099": "Consolidate parameters into a structure (Структура) or split into separate methods.",
    "BSL100": "Replace hardcoded path with a configuration parameter or constant.",
    "BSL101": "Extract nested logic into a separate helper procedure or function.",
    "BSL102": "Split the module into smaller focused modules with clear responsibilities.",
    "BSL103": "Replace Вычислить() with explicit conditional logic or a lookup table.",
    "BSL104": "Add a // Module description comment block at the top of the file.",
    "BSL105": "Remove Приостановить() from server-side code; use asynchronous patterns instead.",
    "BSL106": "Move the query outside the loop or rewrite using batch operations.",
    "BSL107": "Remove the empty Тогда branch or add the missing logic.",
    "BSL108": "Remove the exported module variable and pass the value as a parameter instead.",
    "BSL109": "Invert the condition and remove the guard-clause nesting.",
    "BSL110": "Collect parts into a list (Массив) and use СтрСоединить() after the loop.",
    "BSL111": "Rename the identifier to use a single script (all Cyrillic or all Latin).",
    "BSL112": "Wrap the НачатьТранзакцию block in a Попытка and always call ЗафиксироватьТранзакцию or ОтменитьТранзакцию.",
    "BSL113": "Replace the assignment '=' with a comparison operator '=' inside the condition.",
    "BSL114": "Populate the module with code or delete it.",
    "BSL115": "Simplify НЕ НЕ to the positive form of the condition.",
    "BSL116": "Replace the Для i = 0 По ... pattern with ДляКаждого where applicable.",
    "BSL117": "Check whether you intended to call a Функция instead of a Процедура.",
    "BSL118": "Add an explicit Возврат <value>; statement or change Функция to Процедура.",
    "BSL119": "Break the long line into multiple lines or extract to a variable.",
    "BSL120": "Remove trailing whitespace from the line.",
    "BSL121": "Replace tab characters with spaces (4 spaces per indent level).",
    "BSL122": "Remove the unused parameter or add logic that uses it.",
    "BSL123": "Remove the commented-out code block or restore it with a comment explaining why.",
    "BSL124": "Rename to a descriptive name with at least 3 characters.",
    "BSL125": "Move Прервать inside a loop body or replace with a conditional early exit.",
    "BSL126": "Move Продолжить inside a loop body or replace with a conditional.",
    "BSL127": "Consolidate multiple top-level returns into a single exit variable pattern.",
    "BSL128": "Remove or move the dead code before the unconditional Возврат statement.",
    "BSL129": "Add a base-case guard to prevent infinite recursion, or refactor to an iterative approach.",
    "BSL130": "Split the long comment into multiple shorter lines (max 120 characters each).",
    "BSL131": "Populate the region with code or remove the empty #Область/#КонецОбласти block.",
    "BSL132": "Extract the repeated string literal to a named constant at the top of the module.",
    "BSL133": "Reorder parameters so all optional (default-valued) ones come after required ones.",
    "BSL134": "Refactor the function by extracting logic into smaller helper procedures/functions.",
    "BSL135": "Assign the inner call result to a named variable before passing it as an argument.",
    "BSL136": "Add a space before the // inline comment.",
    "BSL137": "Use НайтиПоСсылке() or filter via a query with an indexed field instead.",
    "BSL138": "Remove debug output before deploying to production.",
    "BSL139": "Shorten parameter names to improve readability.",
    "BSL140": "Remove or fix the condition — it can never be reached.",
    "BSL141": "Replace 'Если Условие Тогда Возврат Истина; КонецЕсли; Возврат Ложь;' with 'Возврат Условие;'",
    "BSL142": "Move complex default values to a named constant.",
    "BSL143": "Remove or fix the duplicate condition in the ИначеЕсли chain.",
    "BSL144": "Remove redundant parentheses from the condition or return value.",
    "BSL145": "Use СтрШаблон()/StrTemplate() for readable string interpolation.",
    "BSL146": "Move initialization code into a dedicated Инициализация() procedure.",
    "BSL147": "Remove ОткрытьФорму()/OpenForm() calls used for debugging.",
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
            d["rule_name"] = display_name_for_rule_code(self.code)
        return d

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
    optional_params: frozenset[str] = frozenset()  # names of optional params (have default value)


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


def _proc_body_base_indent(lines: list[str], proc: _ProcInfo) -> int:
    """Indent (column width) of the first non-blank, non-comment body line after the header."""
    for i in range(proc.start_idx + 1, min(proc.end_idx + 1, len(lines))):
        line = lines[i]
        if _RE_BLANK_OR_COMMENT.match(line):
            continue
        return len(line) - len(line.lstrip())
    return 0


def _line_starts_with_raise_statement(line: str) -> bool:
    """True if the line begins with ВызватьИсключение/Raise (not a // comment)."""
    if line.strip().startswith("//"):
        return False
    return bool(_RE_RAISE.match(line))


def _bsl035_scope_line_indices(lines: list[str], procs: list[_ProcInfo]) -> list[list[int]]:
    """Split the file into scopes for BSL035: each procedure/function body, then module-level."""
    n = len(lines)
    scopes: list[list[int]] = []
    for p in procs:
        lo = max(0, p.start_idx)
        hi = min(p.end_idx + 1, n)
        if lo < hi:
            scopes.append(list(range(lo, hi)))
    covered: set[int] = set()
    for p in procs:
        for i in range(max(0, p.start_idx), min(p.end_idx + 1, n)):
            covered.add(i)
    mod = [i for i in range(n) if i not in covered]
    if mod:
        scopes.append(mod)
    return scopes


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

# Module-level ``Перем Имя Экспорт;`` / ``Var Name Export;`` (BSLLS MissingVariablesDescription)
_RE_VAR_MODULE_EXPORT = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+?)\s+(?:Экспорт|Export)\s*;",
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

# Self-assign: Х = Х; (bare identifier only — not Obj.Field = Field)
_RE_SELF_ASSIGN = re.compile(
    r"^\s*(\w+)\s*=\s*\1\s*;",
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

# BSL018: only a *single* string literal then `;` (no `+` concatenation / НСтр / etc.)
_RE_RAISE_SIMPLE_STRING_ONLY = re.compile(
    r'^\s*(?:ВызватьИсключение|Raise)\s+"[^"]*"\s*;\s*(?://.*)?$',
    re.IGNORECASE,
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
    # BSLLS NestedStatements counts only control-flow branches, NOT Try/Except
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While)\b",
    re.IGNORECASE,
)
_RE_NEST_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo)\b",
    re.IGNORECASE,
)

# Inline noqa/bsl-disable
_RE_NOQA = re.compile(
    r"//\s*(?:noqa|bsl-disable)(?:\s*:\s*(?P<codes>[A-Z0-9,\s]+))?",
    re.IGNORECASE,
)

# BSL Language Server (BSLLS) block-level suppression
# Format: // BSLLS[:DiagnosticName]-off|on|выкл|вкл
_RE_BSLLS = re.compile(
    r"//\s*BSLLS(?::(?P<name>[A-Za-z]+))?-(?P<flag>off|on|выкл|вкл)\b",
    re.IGNORECASE,
)

# BSLLS diagnostic name → our BSL code (for // BSLLS:<Name>-off and Sonar rule names).
# Policy: copy names from bsl-language-server (*Diagnostic without suffix); one primary
# key per BSLLS rule. Add an extra key only if BSLLS/docs use a real alternate spelling
# and users need it in suppression comments — avoid duplicate aliases «на всякий случай».
_BSLLS_NAME_TO_CODE: dict[str, str] = {
    # ── Exact name matches ────────────────────────────────────────────────
    "ParseError":                  "BSL001",
    "MethodSize":                  "BSL002",
    "NonExportMethodsInApiRegion": "BSL003",
    "EmptyCodeBlock":              "BSL004",
    "UnusedLocalVariable":         "BSL007",
    "SelfAssign":                  "BSL009",
    "CognitiveComplexity":         "BSL011",
    "CommentedCode":               "BSL013",
    "NumberOfOptionalParams":      "BSL015",
    "NonStandardRegion":           "BSL016",
    "CyclomaticComplexity":        "BSL019",
    # NOTE: BSLLS DeprecatedMessage flags Сообщить() — not implemented; BSL022 flags Предупреждение()
    "UsingModalWindows":           "BSL022",
    "UsingServiceTag":             "BSL023",
    "SpaceAtStartComment":         "BSL024",
    "EmptyRegion":                 "BSL026",
    "MagicNumber":                 "BSL029",
    "NumberOfParams":              "BSL031",
    "DuplicateStringLiteral":      "BSL035",
    "NestedTernaryOperator":       "BSL039",
    "UsingThisForm":               "BSL040",
    "UnreachableCode":             "BSL051",
    "ProcedureReturnsValue":       "BSL064",
    # ── BSLLS names (RULE_METADATA["name"] matches these) ─────────────────
    "UsingHardcodeNetworkAddress":    "BSL005",
    "UsingHardcodePath":              "BSL006",
    "TooManyReturns":                 "BSL008",
    "UsingHardcodeSecretInformation": "BSL012",
    "LineLength":                     "BSL014",
    "CommandModuleExportMethods":     "BSL017",
    "NestedStatements":               "BSL020",
    "UsingGoto":                      "BSL027",
    "MissingCodeTryCatchEx":          "BSL028",
    "FunctionShouldHaveReturn":       "BSL032",
    "CreateQueryInCycle":             "BSL033",
    "IfConditionComplexity":          "BSL036",
    "ConsecutiveEmptyLines":          "BSL055",
    "DoubleNegatives":                "BSL060",
    "UnusedParameters":               "BSL062",
    "MissingReturnedValueDescription": "BSL065",
    "DeprecatedFind":                 "BSL066",
    "MagicDate":                      "BSL047",
    "DeprecatedCurrentDate":          "BSL097",
    "ExportVariables":                "BSL054",
    "SelectTopWithoutOrderBy":        "BSL077",
    "EmptyStatement":                 "BSL025",
    "SemicolonPresence":              "BSL030",
    "IdenticalExpressions":           "BSL052",
    "UnusedLocalMethod":              "BSL042",
    # ── BSL148–BSL279 stub mappings ──────────────────────────────────────────
    "AllFunctionPathMustHaveReturn":          "BSL148",
    "AssignAliasFieldsInQuery":               "BSL149",
    "BadWords":                               "BSL150",
    "BeginTransactionBeforeTryCatch":         "BSL151",
    "CachedPublic":                           "BSL152",
    "CanonicalSpellingKeywords":              "BSL153",
    "CodeAfterAsyncCall":                     "BSL154",
    "CodeBlockBeforeSub":                     "BSL155",
    "CodeOutOfRegion":                        "BSL156",
    "CommitTransactionOutsideTryCatch":       "BSL157",
    "CommonModuleAssign":                     "BSL158",
    "CommonModuleInvalidType":                "BSL159",
    "CommonModuleMissingAPI":                 "BSL160",
    "CommonModuleNameCached":                 "BSL161",
    "CommonModuleNameClient":                 "BSL162",
    "CommonModuleNameClientServer":           "BSL163",
    "CommonModuleNameFullAccess":             "BSL164",
    "CommonModuleNameGlobal":                 "BSL165",
    "CommonModuleNameGlobalClient":           "BSL166",
    "CommonModuleNameServerCall":             "BSL167",
    "CommonModuleNameWords":                  "BSL168",
    "CompilationDirectiveLost":               "BSL169",
    "CompilationDirectiveNeedLess":           "BSL170",
    "CrazyMultilineString":                   "BSL171",
    "DataExchangeLoading":                    "BSL172",
    "DeletingCollectionItem":                 "BSL173",
    "DenyIncompleteValues":                   "BSL174",
    "DeprecatedAttributes8312":               "BSL175",
    "DeprecatedMethodCall":                   "BSL176",
    "DeprecatedMethods8310":                  "BSL177",
    "DeprecatedMethods8317":                  "BSL178",
    "DeprecatedTypeManagedForm":              "BSL179",
    "DisableSafeMode":                        "BSL180",
    "DuplicatedInsertionIntoCollection":      "BSL181",
    "ExcessiveAutoTestCheck":                 "BSL182",
    "ExecuteExternalCode":                    "BSL183",
    "ExecuteExternalCodeInCommonModule":      "BSL184",
    "ExternalAppStarting":                    "BSL185",
    "ExtraCommas":                            "BSL186",
    "FieldsFromJoinsWithoutIsNull":           "BSL187",
    "FileSystemAccess":                       "BSL188",
    "ForbiddenMetadataName":                  "BSL189",
    "FormDataToValue":                        "BSL190",
    "FullOuterJoinQuery":                     "BSL191",
    "FunctionNameStartsWithGet":              "BSL192",
    "FunctionOutParameter":                   "BSL193",
    "FunctionReturnsSamePrimitive":           "BSL194",
    "GetFormMethod":                          "BSL195",
    "GlobalContextMethodCollision8312":       "BSL196",
    "IfElseDuplicatedCodeBlock":              "BSL197",
    "IfElseDuplicatedCondition":              "BSL198",
    "IfElseIfEndsWithElse":                   "BSL199",
    "IncorrectLineBreak":                     "BSL200",
    "IncorrectUseLikeInQuery":               "BSL201",
    "IncorrectUseOfStrTemplate":              "BSL202",
    "InternetAccess":                         "BSL203",
    "InvalidCharacterInFile":                 "BSL204",
    "IsInRoleMethod":                         "BSL205",
    "JoinWithSubQuery":                       "BSL206",
    "JoinWithVirtualTable":                   "BSL207",
    "LatinAndCyrillicSymbolInWord":           "BSL208",
    "LogicalOrInJoinQuerySection":            "BSL209",
    "LogicalOrInTheWhereSectionOfQuery":      "BSL210",
    "MetadataObjectNameLength":               "BSL211",
    "MissedRequiredParameter":               "BSL212",
    "MissingCommonModuleMethod":              "BSL213",
    "MissingEventSubscriptionHandler":        "BSL214",
    "MissingParameterDescription":            "BSL215",
    "MissingSpace":                           "BSL216",
    "MissingTempStorageDeletion":             "BSL217",
    "MissingTemporaryFileDeletion":           "BSL218",
    "MissingVariablesDescription":            "BSL219",
    "MultilineStringInQuery":                 "BSL220",
    "MultilingualStringHasAllDeclaredLanguages": "BSL221",
    "MultilingualStringUsingWithTemplate":    "BSL222",
    "NestedConstructorsInStructureDeclaration": "BSL223",
    "NestedFunctionInParameters":             "BSL224",
    "NumberOfValuesInStructureConstructor":   "BSL225",
    "OSUsersMethod":                          "BSL226",
    "OneStatementPerLine":                    "BSL227",
    "OrderOfParams":                          "BSL228",
    "OrdinaryAppSupport":                     "BSL229",
    "PairingBrokenTransaction":               "BSL230",
    "PrivilegedModuleMethodCall":             "BSL231",
    "ProtectedModule":                        "BSL232",
    "PublicMethodsDescription":               "BSL233",
    "QueryNestedFieldsByDot":                 "BSL234",
    "QueryParseError":                        "BSL235",
    "QueryToMissingMetadata":                 "BSL236",
    "RedundantAccessToObject":                "BSL237",
    "RefOveruse":                             "BSL238",
    "ReservedParameterNames":                 "BSL239",
    "RewriteMethodParameter":                 "BSL240",
    "SameMetadataObjectAndChildNames":        "BSL241",
    "ScheduledJobHandler":                    "BSL242",
    "SelfInsertion":                          "BSL243",
    "ServerCallsInFormEvents":                "BSL244",
    "ServerSideExportFormMethod":             "BSL245",
    "SetPermissionsForNewObjects":            "BSL246",
    "SetPrivilegedMode":                      "BSL247",
    "SeveralCompilerDirectives":              "BSL248",
    "StyleElementConstructors":               "BSL249",
    "TempFilesDir":                           "BSL250",
    "TernaryOperatorUsage":                   "BSL251",
    "ThisObjectAssign":                       "BSL252",
    "TimeoutsInExternalResources":            "BSL253",
    "TransferringParametersBetweenClientAndServer": "BSL254",
    "TryNumber":                              "BSL255",
    "Typo":                                   "BSL256",
    "UnaryPlusInConcatenation":               "BSL257",
    "UnionAll":                               "BSL258",
    "UnknownPreprocessorSymbol":              "BSL259",
    "UnsafeFindByCode":                       "BSL260",
    "UnsafeSafeModeMethodCall":               "BSL261",
    "UsageWriteLogEvent":                     "BSL262",
    "UseLessForEach":                         "BSL263",
    "UseSystemInformation":                   "BSL264",
    "UselessTernaryOperator":                 "BSL265",
    "UsingCancelParameter":                   "BSL266",
    "UsingExternalCodeTools":                 "BSL267",
    "UsingFindElementByString":               "BSL268",
    "UsingLikeInQuery":                       "BSL269",
    # "UsingModalWindows" → BSL022 (active impl); BSL270 stub removed to avoid dict key collision
    "UsingObjectNotAvailableUnix":            "BSL271",
    "UsingSynchronousCalls":                  "BSL272",
    "VirtualTableCallWithoutParameters":      "BSL273",
    "WrongDataPathForFormElements":           "BSL274",
    "WrongHttpServiceHandler":               "BSL275",
    "WrongUseFunctionProceedWithCall":        "BSL276",
    "WrongUseOfRollbackTransactionMethod":    "BSL277",
    "WrongWebServiceHandler":                 "BSL278",
    "YoLetterUsage":                          "BSL279",
    "UnknownMetadataObjectReference":         "BSL280",
}

# ---------------------------------------------------------------------------
# Rule code normalization (BSL### and BSLLS names in select/ignore / CLI / LSP)
# ---------------------------------------------------------------------------

_RE_BSL_CODE_TOKEN = re.compile(r"^BSL\d{3}$", re.IGNORECASE)

# casefold BSLLS name -> canonical BSL code (first registered alias wins)
_BSLLS_NAME_FOLD_TO_CODE: dict[str, str] = {}
for _bsl_name, _bsl_code in _BSLLS_NAME_TO_CODE.items():
    _fold = _bsl_name.casefold()
    if _fold not in _BSLLS_NAME_FOLD_TO_CODE:
        _BSLLS_NAME_FOLD_TO_CODE[_fold] = _bsl_code

# BSL### -> primary BSLLS name for display (first key in map order)
_CODE_TO_PRIMARY_BSLLS_NAME: dict[str, str] = {}
for _bsl_name, _bsl_code in _BSLLS_NAME_TO_CODE.items():
    if _bsl_code not in _CODE_TO_PRIMARY_BSLLS_NAME:
        _CODE_TO_PRIMARY_BSLLS_NAME[_bsl_code] = _bsl_name


def resolve_rule_token_to_code(token: str) -> str | None:
    """Map one CLI/settings token to canonical ``BSL###``, or None if unknown."""
    t = (token or "").strip()
    if not t:
        return None
    if _RE_BSL_CODE_TOKEN.match(t):
        return t.upper()
    if t in _BSLLS_NAME_TO_CODE:
        return _BSLLS_NAME_TO_CODE[t]
    folded = t.casefold()
    return _BSLLS_NAME_FOLD_TO_CODE.get(folded)


def normalize_rule_code_set(tokens: Iterable[str] | None) -> set[str] | None:
    """
    Normalize select/ignore lists: accept both ``BSL###`` and BSLLS diagnostic names.

    Unknown tokens are skipped. Returns None if the result is empty.
    """
    if tokens is None:
        return None
    out: set[str] = set()
    for raw in tokens:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        for part in s.replace(",", " ").split():
            c = resolve_rule_token_to_code(part)
            if c:
                out.add(c)
    return out if out else None


def display_name_for_rule_code(code: str) -> str:
    """Public rule name for LSP/UI: BSLLS name when known, else RULE_METADATA name, else code."""
    primary = _CODE_TO_PRIMARY_BSLLS_NAME.get(code)
    if primary:
        return primary
    meta = RULE_METADATA.get(code)
    if meta:
        return str(meta.get("name", code))
    return code


def parse_env_rule_filters() -> tuple[set[str] | None, set[str] | None]:
    """
    Read ``BSL_SELECT`` / ``BSL_IGNORE`` from the environment.

    Same semantics as the LSP server and VS Code extension (comma-separated
    ``BSL###`` or BSLLS diagnostic names).
    """
    raw_sel = os.environ.get("BSL_SELECT", "").strip()
    raw_ign = os.environ.get("BSL_IGNORE", "").strip()
    select = normalize_rule_code_set(raw_sel.split(",")) if raw_sel else None
    ignore = normalize_rule_code_set(raw_ign.split(",")) if raw_ign else None
    return select, ignore


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

# BSLLS SpaceAtStartCommentDiagnostic — GOOD_COMMENT_PATTERN_STRICT (develop branch):
# either "//[ \\t].*" or "//{2,}[ \\t]*" end-of-line only (///, ////, bare //).
_BSL024_BSLLS_GOOD_STRICT = re.compile(
    r"(?:(?://[ \t].*)|(?:/{2,}[ \t]*))$",
    re.IGNORECASE,
)


def _bsl024_matches_bslls_good_strict(line: str, comment_col: int) -> bool:
    """True if the comment suffix from ``//`` matches BSLLS strict «good» pattern."""
    if comment_col < 0 or comment_col >= len(line):
        return False
    return bool(_BSL024_BSLLS_GOOD_STRICT.match(line[comment_col:]))


def _bsl024_is_bslls_annotation_comment(line: str, comment_col: int) -> bool:
    """BSLLS ``commentsAnnotation`` default: //@, //(c), //© (case-insensitive)."""
    if comment_col + 2 > len(line):
        return False
    rest = line[comment_col + 2 :]
    s = rest.lstrip()
    if not s:
        return False
    if s.startswith("@"):
        return True
    if s.lower().startswith("(c)"):
        return True
    if s.startswith("©"):
        return True
    return False


def _bsl024_skip_line_bslls_alignment(line: str) -> bool:
    """Extra skips aligned with BSLLS / EDT: ``///``, ``//|``, ``//!``, noqa, bsl-disable."""
    st = line.lstrip()
    if st.startswith("///"):
        return True
    if st.startswith("//|"):
        return True
    if st.startswith("//!"):
        return True
    if re.match(r"//\s*noqa\b", st, re.IGNORECASE):
        return True
    if re.match(r"//\s*bsl-disable\b", st, re.IGNORECASE):
        return True
    return False


def _bsl024_is_compiler_directive_comment(line: str) -> bool:
    """``//&НаКлиенте``-style lines — BSLLS SpaceAtStartComment does not flag these."""
    st = line.lstrip()
    if not st.startswith("//"):
        return False
    rest = st[2:].lstrip()
    return rest.startswith("&")


def bsl024_should_report_line(line: str) -> bool:
    """
    True when ``SpaceAtStartComment`` / BSL024 should flag this line (full-line ``//`` comment).

    Kept in sync with :meth:`DiagnosticEngine._rule_bsl024_space_at_start_comment`
    and LSP quick-fix for BSL024.
    """
    stripped = line.strip()
    if not stripped.startswith("//"):
        return False
    col = line.index("//")
    if _bsl024_matches_bslls_good_strict(line, col):
        return False
    if _bsl024_is_bslls_annotation_comment(line, col):
        return False
    if _bsl024_skip_line_bslls_alignment(line):
        return False
    if _RE_COMMENTED_CODE.match(line):
        return False
    if _bsl024_is_compiler_directive_comment(line):
        return False
    return True


def path_is_likely_form_module_bsl(path: str) -> bool:
    """
    True for EDT-style ``.../Forms/.../Ext/Module.bsl`` or file stems containing
    ``форма`` / ending with ``form`` (модули форм — ``ЭтаФорма`` допустима).
    """
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    stem = p.stem.lower()
    if "форма" in stem or stem.endswith("form"):
        return True
    parts = [x.lower() for x in p.parts]
    if p.name.lower() == "module.bsl" and ("forms" in parts or "формы" in parts):
        return True
    return False


# Параметры стандартных обработчиков (команды, события форм) — BSLLS не помечает как неиспользуемые.
_BSL062_SKIP_STANDARD_COMMAND_PARAMS = frozenset(
    {
        # ── Команды ────────────────────────────────────────────────────────────
        "команда",          # Процедура ОткрытьФорму(Команда) — стандартный командный обработчик
        "command",
        "параметркоманды",
        "параметрывыполнениякоманды",
        "commandparameter",
        "commandexecutionparameters",
        # ── Стандартные параметры событий форм ────────────────────────────────
        "отказ",
        "cancel",
        "стандартнаяобработка",
        "standardprocessing",
        "текущийэлемент",
        "currentitem",
        "данные",
        "data",
        "поле",
        "field",
        "строка",
        "row",
        "колонка",
        "column",
        "действие",
        "action",
        "адресхранилища",
        "storageaddress",
        "параметрыформы",
        "formparameters",
        "источник",
        "source",
        "причина",
        "reason",
        "выбранноезначение",
        "selectedvalue",
        "результатвыбора",
        "selectionresult",
        "закрытьформу",
        "closeform",
        "уникальныйидентификатор",
        "uniqueid",
        # ── Параметры обработчиков завершения / оповещений ────────────────────
        # Второй параметр ОписаниеОповещения: Процедура ЗавершениеXXX(Результат, ДополнительныеПараметры)
        "дополнительныепараметры",
        "additionalparameters",
        "параметрыоповещения",
        "notificationparameters",
        "допараметры",
        "доппараметры",
        "параметрыоповещений",
        # ── Параметры событий выбора / автоподбора ────────────────────────────
        "данныевыбора",
        "choicedata",
        "параметрыполученияданных",
        "datagetparameters",
        "choicedatagetparameters",
        "ожидание",
        "ожиданиеввода",
        "waiting",
        # ── Параметры событий таблиц и списков ────────────────────────────────
        "область",          # ПолеТабличногоДокумента...Выбор(Элемент, Область, СтандартнаяОбработка)
        "area",
        "расшифровка",
        "decoding",
        "идентификаторстроки",
        "rowid",
        # ── Параметры событий перетаскивания ──────────────────────────────────
        "параметрыперетаскивания",
        "dragparameters",
        "позиция",
        "position",
        # ── Параметры события навигационной ссылки ────────────────────────────
        "навигационнаяссылка",
        "navigationlink",
        "навигационнаяссылкаформат",
        "navigationlinkformatted",
        # ── Параметры ПередЗакрытием ──────────────────────────────────────────
        "завершениеработы",
        "applicationclosing",
        "текстпредупреждения",
        "warningtext",
        # ── Параметры ПередНачаломДобавления ─────────────────────────────────
        "копирование",
        "copy",
        "родитель",
        "parent",
        "группа",
        "group",
        # ── Параметры обработчиков подписок (переопределяемые модули) ─────────
        # Первый параметр ПриОпределении..., ПриПолучении..., etc.
        "источникисобытия",
        "eventsource",
        # ── Стандартный первый параметр событий элементов формы ───────────────
        # Virtually all form element events: НажатиеКнопки(Элемент), etc.
        "элемент",
        "element",
        "item",
        # ── Параметры стандартных событий объектов (не-формовые модули) ────────
        # ОбработкаЗаполнения(ДанныеЗаполнения, ТекстЗаполнения, СтандартнаяОбработка)
        "данныезаполнения",
        "fillingdata",
        "текстзаполнения",
        "fillingtext",
        # ОбработкаПроверкиЗаполнения(Отказ, ПроверяемыеРеквизиты)
        "проверяемыереквизиты",
        "checkedattributes",
        # ПриКопировании(КопируемыйОбъект)
        "копируемыйобъект",
        "copiedobject",
        # ПриОтмене(ОтменяемоеДействие)
        "отменяемоедействие",
        "cancelledaction",
    }
)


def _procedure_compiler_execution_context(lines: list[str], proc: _ProcInfo) -> str:
    """
    ``&НаКлиенте`` / ``&НаСервере`` / ``&НаКлиентеНаСервере`` непосредственно перед объявлением метода.

    Returns one of: ``client``, ``server``, ``both``, ``none``.
    """
    j = proc.start_idx - 1
    saw_client = False
    saw_server = False
    while j >= 0:
        raw = lines[j]
        if not raw.strip():
            j -= 1
            continue
        if raw.strip().startswith("//"):
            j -= 1
            continue
        s = raw.strip()
        if not s.startswith("&"):
            break
        u = s.casefold().replace(" ", "")
        if "наклиентенасервере" in u:
            return "both"
        if "наклиенте" in u and "насервере" not in u:
            saw_client = True
        elif "насервере" in u and "наклиенте" not in u:
            saw_server = True
        j -= 1
    if saw_client and saw_server:
        return "both"
    if saw_client:
        return "client"
    if saw_server:
        return "server"
    return "none"


def _is_typical_client_command_handler(proc: _ProcInfo, lines: list[str]) -> bool:
    """
    Типовой обработчик команды: ``Процедура ОбработкаКоманды`` в клиентском (или смешанном)
    контексте компилятора. Серверный контекст исключаем — это уже не «ввод команды» на клиенте.

    Заменяет эвристику ``.../CommonCommands/.../CommandModule.bsl``: одно и то же имя метода
    встречается в общих командах и в ``Catalogs/.../Commands/.../CommandModule.bsl``.
    """
    if proc.name.strip().casefold() != "обработкакоманды":
        return False
    ctx = _procedure_compiler_execution_context(lines, proc)
    return ctx in ("client", "both", "none")


def _is_client_notify_completion_export_handler(proc: _ProcInfo, lines: list[str]) -> bool:
    """
    Экспортный клиентский обработчик завершения для «ОписаниеОповещения» (имя *Завершение / *Completion).

    Сигнатура платформенная; второй параметр «Параметры» часто не используется — это не ошибка.
    Отдельный комментарий к экспорту обычно избыточен (как в BSLLS на типовых CommandModule).
    """
    if not proc.is_export:
        return False
    ctx = _procedure_compiler_execution_context(lines, proc)
    if ctx not in ("client", "both", "none"):
        return False
    n = proc.name.strip().casefold()
    return n.endswith("завершение") or n.endswith("completion")


def _proc_containing_line(procs: list[_ProcInfo], line_idx: int) -> _ProcInfo | None:
    """Procedure/function whose body includes 0-based line index *line_idx*."""
    for p in procs:
        if p.start_idx <= line_idx <= p.end_idx:
            return p
    return None


def _comma_missing_space_after_col_in_line(line: str) -> int | None:
    """
    0-based column of ``,`` when immediately followed by a token char (BSLLS MissingSpace),
    only outside ``"..."`` string literals (positions must match *line* for overlap filter).
    """
    in_str = False
    i = 0
    n = len(line)
    while i < n - 1:
        ch = line[i]
        if ch == '"':
            in_str = not in_str
            i += 1
            continue
        if in_str:
            i += 1
            continue
        if ch == ",":
            nxt = line[i + 1]
            if nxt not in " \t\n\r," and nxt.isalpha():
                return i
        i += 1
    return None


def _module_export_var_has_preceding_description(lines: list[str], var_line_idx: int) -> bool:
    """Previous non-blank line is a non-empty ``//`` or ``///`` comment (BSLLS MissingVariablesDescription)."""
    j = var_line_idx - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0:
        return False
    s = lines[j].strip()
    if s.startswith("///"):
        return len(s) > 3
    if s.startswith("//"):
        return len(s[2:].strip()) > 0
    return False


# BSLLS: Typo (BSL256) vs LatinAndCyrillicSymbolInWord (BSL208). When every Cyrillic
# letter in an identifier is a Latin homoglyph, BSLLS reports Typo — not mixed-script.
_CYR_HOMOGLYPH_TO_LATIN: dict[str, str] = {
    "а": "a",
    "А": "A",
    "е": "e",
    "Е": "E",
    "о": "o",
    "О": "O",
    "р": "p",
    "Р": "P",
    "с": "c",
    "С": "C",
    "х": "x",
    "Х": "X",
    "м": "m",
    "М": "M",
    "т": "t",
    "Т": "T",
    "у": "y",
    "У": "Y",
    "і": "i",
    "І": "I",
    "к": "k",
    "К": "K",
    "д": "d",
    "Д": "D",
}


def _try_homoglyph_latinize_identifier(word: str) -> str | None:
    """
    If every Cyrillic character is a known Latin lookalike, return the Latin form.

    If any Cyrillic letter is not in the homoglyph map, return None (intentional
    mixed-script name → BSL208).
    """
    out: list[str] = []
    for c in word:
        if c in _CYR_HOMOGLYPH_TO_LATIN:
            out.append(_CYR_HOMOGLYPH_TO_LATIN[c])
        elif "\u0400" <= c <= "\u04ff" or c in "ёЁ":
            return None
        else:
            out.append(c)
    s = "".join(out)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
        return None
    return s


def _mixed_script_identifier_is_homoglyph_typo(word: str) -> bool:
    """True when identifier mixes scripts only via confusable Cyrillic letters (BSLLS Typo)."""
    if not re.search(r"[a-zA-Z]", word) or not re.search(r"[А-ЯЁа-яё]", word):
        return False
    return _try_homoglyph_latinize_identifier(word) is not None


# Standard technology acronyms used in 1C BSL identifiers — mixing Cyrillic base with a
# Latin acronym (e.g. HTTPЗапрос, JSONЗапись, XMLЧтение) is the accepted 1C platform
# convention, not a coding error.  BSLLS skips these implicitly via its built-in type
# knowledge.  We replicate the same skip with a set of known acronyms: if every
# contiguous Latin run inside a mixed-script identifier is one of these, the identifier
# is a well-known platform / technology name and should not be flagged as BSL208.
_BSL208_TECH_ACRONYMS: frozenset[str] = frozenset(
    {
        # Network protocols & data formats
        "HTTP", "HTTPS", "FTP", "SFTP", "FTPS",
        "SMTP", "POP", "IMAP",
        "TCP", "UDP", "IP", "TLS", "SSL",
        "URL", "URI", "UUID", "GUID",
        "REST", "SOAP", "WSDL", "API",
        # Data formats
        "JSON", "XML", "HTML", "XHTML", "XDTO", "XSL", "XSLT",
        "CSV", "ZIP", "PDF", "XLS", "XLSX", "DOCX", "ODT",
        "SQL",
        # Platform integration
        "COM", "OLE", "DLL", "EXE",
        "ADO", "ODP",
        # Misc abbreviations accepted in 1C names
        "ODATA",
    }
)

_RE_LATIN_RUNS = re.compile(r"[a-zA-Z]+")


def _bsl208_word_is_standard_tech_name(word: str) -> bool:
    """True when all Latin substrings in *word* are known technology acronyms.

    Examples that return True (skip BSL208):
        HTTPЗапрос, JSONВЗначение, ЧтениеZIP, COMОбъект, XMLЧтение, SQLЗапрос

    Examples that return False (flag BSL208):
        МойHTMLParserКласс  — "Parser" is not a tech acronym
        userIDПоле          — "user" is not a tech acronym
    """
    latin_runs = _RE_LATIN_RUNS.findall(word)
    if not latin_runs:
        return False
    return all(run.upper() in _BSL208_TECH_ACRONYMS for run in latin_runs)


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

# BSL113 — assignment (=) inside Если/ИначеЕсли condition
_RE_ASSIGN_IN_COND = re.compile(
    r"^\s*(?:Если|ИначеЕсли|ElseIf|If)\b.*(?<![<>!])=(?![=>])",
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

# Boolean literal comparison in If/ElseIf condition only (aligns with BSLLS).
_RE_BOOL_LITERAL_CMP = re.compile(
    r"^\s*(?:Если|ИначеЕсли|ElseIf|If)\b.*(?:=|<>)\s*(?:Истина|True|Ложь|False)\b"
    r"|^\s*(?:Если|ИначеЕсли|ElseIf|If)\b.*(?:Истина|True|Ложь|False)\s*(?:=|<>)",
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

# Comment line (BSL065 — export method comment check)
_RE_COMMENT_LINE = re.compile(r'^\s*//')
# Form / module compiler directives before procedure (&НаКлиенте, &НаСервере, …)
_RE_FORM_COMPILER_DIRECTIVE_LINE = re.compile(r"^\s*&\S+")

# BSL066 — DeprecatedFind: only Найти() → СтрНайти() (BSLLS parity).
# Врег/НРег/СокрЛ/СокрП/СокрЛП/Символ/КодСимвола — current platform functions, NOT deprecated.
# Предупреждение/Вопрос/Сообщить — covered by UsingModalWindows / DeprecatedMessage rules.
# ВвестиЗначение/ВвестиЧисло/ВвестиДату/ВвестиСтроку — covered by BSL057 DeprecatedInputDialog.
_DEPRECATED_METHODS = frozenset({
    "найти",   # Найти() for strings → СтрНайти()
    "find",    # English alias
})
# Negative lookbehind for '.' excludes object method calls like Массив.Найти()
_RE_DEPRECATED_METHOD = re.compile(
    r'(?<!\.)(?<!\w)\b(?:' + '|'.join(re.escape(m) for m in sorted(_DEPRECATED_METHODS)) + r')\s*\(',
    re.IGNORECASE,
)

# Пока Истина Цикл / While True Do (BSL069)
_RE_WHILE_TRUE = re.compile(
    r'^\s*(?:Пока|While)\s+(?:Истина|True)\s+(?:Цикл|Do)\b',
    re.IGNORECASE,
)

# Перем declaration (BSL067)
_RE_VAR_DECL = re.compile(r'^\s*(?:Перем|Var)\b', re.IGNORECASE)
# Executable code (not comment, not blank, not Перем, not proc header)
_RE_EXECUTABLE_LINE = re.compile(
    r'^\s*(?!//|$|(?:Перем|Var)\b|(?:Процедура|Функция|Procedure|Function)\b|(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b)',
    re.IGNORECASE,
)

# Multiple statements on one line (BSL095): two assignments/calls separated by ;
# Simplified: a non-empty statement before ; and another after on the same line
_RE_MULTI_STMT = re.compile(
    r';\s*\w',  # ; followed by word char on same line
)

# ТекущаяДата() (BSL097)
_RE_CURRENT_DATE = re.compile(
    r'\b(?:ТекущаяДата|CurrentDate)\s*\(',
    re.IGNORECASE,
)

# NULL comparison (BSL093)
_RE_NULL_COMPARISON = re.compile(
    r'(?:=|<>)\s*(?:NULL|Null)\b|(?:NULL|Null)\s*(?:=|<>)',
    re.IGNORECASE,
)

# Compound no-op assignment (BSL094): += 0 or *= 1 or -= 0 or /= 1
_RE_NOOP_COMPOUND = re.compile(
    r'\w+\s*(?:\+=\s*0|-=\s*0|\*=\s*1|/=\s*1)\b',
)

# Transaction begin in loop (BSL089)
_RE_BEGIN_TRANSACTION = re.compile(
    r'\b(?:НачатьТранзакцию|BeginTransaction)\s*\(',
    re.IGNORECASE,
)

# Hardcoded connection string patterns (BSL090)
_RE_CONNECTION_STRING = re.compile(
    r'(?:Server\s*=|DSN\s*=|Driver\s*=|Database\s*=|Uid\s*=|Pwd\s*=)',
    re.IGNORECASE,
)

# Else after Return detection (BSL091)
_RE_RETURN_STMT = re.compile(r'^\s*(?:Возврат|Return)\b', re.IGNORECASE)

# HTTP request in loop (BSL086) — ПолучитьДанные, ВыполнитьЗапросHTTP, HTTPЗапрос etc.
_RE_HTTP_REQUEST = re.compile(
    r'(?:HTTPСоединение|HTTPConnection|HTTPЗапрос|HTTPRequest'
    r'|ПолучитьДанные|GetData|ОтправитьДанные|PutData'
    r'|ПолучитьСтроку|GetString|ОтправитьСтроку|PutString)\b',
    re.IGNORECASE,
)

# Новый/New object creation (BSL087)
_RE_NEW_OBJECT = re.compile(r'\bНовый\b|\bNew\b', re.IGNORECASE)

# // Parameters: comment section (BSL088)
_RE_PARAM_COMMENT = re.compile(r'//\s*(?:Параметры|Parameters)\s*:', re.IGNORECASE)

# Literal boolean in Если condition (BSL085)
_RE_LITERAL_BOOL_CONDITION = re.compile(
    r'^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:Истина|True|Ложь|False)\s+(?:Тогда|Then)\b',
    re.IGNORECASE,
)

# Exception block detection (BSL080)
_RE_EXCEPT_BLOCK = re.compile(r'^\s*(?:Исключение|Except)\b', re.IGNORECASE)
_RE_END_TRY = re.compile(r'^\s*(?:КонецПопытки|EndTry)\b', re.IGNORECASE)
_RE_TRY_OPEN = re.compile(r'^\s*(?:Попытка|Try)\b', re.IGNORECASE)
_RE_ERROR_INFO = re.compile(r'(?:ИнформацияОбОшибке|ErrorInfo)\s*\(', re.IGNORECASE)

# Method chain length (BSL081): count dots in a non-comment line
_RE_DOT_CHAIN = re.compile(r'(?:\.\w+\s*\()+')

# SELECT * in query text (BSL077)
_RE_SELECT_STAR = re.compile(
    r'(?:ВЫБРАТЬ|SELECT)\s+\*',
    re.IGNORECASE,
)

# Raise without message (BSL078): ВызватьИсключение; or Raise; alone on line
_RE_RAISE_BARE = re.compile(
    r'^\s*(?:ВызватьИсключение|Raise)\s*;',
    re.IGNORECASE,
)

# Goto statement (BSL079)
_RE_GOTO = re.compile(
    r'^\s*(?:Перейти|Goto)\b',
    re.IGNORECASE,
)

# TODO/FIXME/HACK comment (BSL074)
_RE_TODO_COMMENT = re.compile(
    r'//\s*(?:TODO|FIXME|HACK|XXX)\b',
    re.IGNORECASE,
)

# Negative condition: line starts an Если/ElsIf and condition begins with НЕ/Not (BSL076)
_RE_NEGATIVE_CONDITION = re.compile(
    r'^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:НЕ|Not)\b',
    re.IGNORECASE,
)

# Выполнить() / Execute() — dynamic code execution (BSL098)
_RE_EXECUTE = re.compile(r'(?<!\.)(?:Выполнить|Execute)\s*\(', re.IGNORECASE)

# Exported Перем declaration (BSL108): Перем X Экспорт
_RE_EXPORTED_VAR = re.compile(
    r'^\s*(?:Перем|Var)\b[^;]*\bЭкспорт\b',
    re.IGNORECASE,
)

# String self-concatenation in loop: А = А + "..." or А = А + Б (BSL110)
_RE_STR_CONCAT_SELF = re.compile(
    r'^\s*(\w+)\s*=\s*\1\s*\+\s*(?:"[^"]*"|\w)',
    re.IGNORECASE,
)

# Mixed Cyrillic+Latin identifier (BSL111)
# Matches a sequence where Cyrillic and Latin characters are interleaved
_RE_MIXED_IDENT = re.compile(
    r'(?:[А-ЯЁа-яё]+[A-Za-z]|[A-Za-z]+[А-ЯЁа-яё])\w*',
)

# BSL113 removed: in BSL '=' is ALWAYS a comparison operator, never assignment.
# Assignment is a statement-level construct only — there are no assignment
# expressions, so "assignment in condition" is impossible in BSL by design.

# Double negation: НЕ НЕ or Not Not (BSL115)
_RE_DOUBLE_NEGATION = re.compile(
    r'\b(?:НЕ|Not)\s+(?:НЕ|Not)\b',
    re.IGNORECASE,
)

# Прервать / Break (BSL125)
_RE_BREAK = re.compile(r'^\s*(?:Прервать|Break)\s*;', re.IGNORECASE)

# Продолжить / Continue (BSL126)
_RE_CONTINUE = re.compile(r'^\s*(?:Продолжить|Continue)\s*;', re.IGNORECASE)

# Comment that looks like commented-out code (BSL123): // contains = ; or ()
_RE_COMMENTED_CODE = re.compile(
    r'^\s*//\s*\w.*(?:;|\(|\) *=|:=)',
)

# Hardcoded file path in string literal (BSL100)
_RE_HARDCODED_PATH = re.compile(
    r'"(?:[A-Za-z]:\\|/(?:home|usr|etc|var|opt|tmp)/)[^"]*"',
    re.IGNORECASE,
)

# Loop opening / closing for QueryInLoop and TooDeepNesting tracking
_RE_LOOP_FOR = re.compile(
    r'^\s*(?:Для|For|ДляКаждого|ForEach)\b',
    re.IGNORECASE,
)
_RE_LOOP_ENDDO = re.compile(r'^\s*(?:КонецЦикла|EndDo)\b', re.IGNORECASE)

# SQL query start (BSL106)
_RE_SQL_SELECT = re.compile(r'(?:ВЫБРАТЬ|SELECT)\b', re.IGNORECASE)

# Вычислить() / Eval() — dynamic expression evaluation (BSL103)
_RE_EVAL = re.compile(r'\b(?:Вычислить|Eval)\s*\(', re.IGNORECASE)

# Приостановить() / Sleep() (BSL105)
_RE_SLEEP = re.compile(r'\b(?:Приостановить|Sleep)\s*\(', re.IGNORECASE)

# Тогда — Then keyword for EmptyThenBranch (BSL107)
_RE_THEN = re.compile(r'\b(?:Тогда|Then)\s*$', re.IGNORECASE)


def _regex_line_has_empty_then_branch(lines: list[str], then_line_idx: int) -> bool:
    """True if this line ends a condition with ``Тогда`` and the branch body is empty (regex fallback)."""
    if then_line_idx < 0 or then_line_idx >= len(lines):
        return False
    line = lines[then_line_idx]
    if not _RE_THEN.search(line):
        return False
    if line.strip().startswith("//"):
        return False
    n = len(lines)
    next_idx = then_line_idx + 1
    while next_idx < n and (
        not lines[next_idx].strip() or lines[next_idx].strip().startswith("//")
    ):
        next_idx += 1
    if next_idx >= n:
        return False
    return bool(
        _RE_ENDIF.match(lines[next_idx])
        or _RE_ELSEIF.match(lines[next_idx])
        or _RE_ELSE.match(lines[next_idx])
    )


# BSL130 — LongCommentLine: comment line longer than 120 chars
_RE_COMMENT_ONLY_LINE = re.compile(r'^\s*//')

# BSL131 — EmptyRegion: #Область / #КонецОбласти markers (line-level, no name group)
_RE_REGION_OPEN_LINE = re.compile(r'^\s*#(?:Область|Region)\b', re.IGNORECASE)
_RE_REGION_CLOSE_LINE = re.compile(r'^\s*#(?:КонецОбласти|EndRegion)\b', re.IGNORECASE)

# BSL132 — RepeatedStringLiteral: collect all double-quoted strings ≥ 3 chars
_RE_STRING_LITERAL = re.compile(r'"([^"]{3,})"')

# BSL133 — RequiredParamAfterOptional: detect optional params (have =)
_RE_PARAM_HAS_DEFAULT = re.compile(r'=')

# BSL134 — CyclomaticComplexity: decision-point keywords
_RE_MCCABE_BRANCH_BSL134 = re.compile(
    r'^\s*(?:Если|If|ИначеЕсли|ElsIf|Пока|While|Для|For|ДляКаждого|ForEach'
    r'|Попытка|Try|Исключение|Except)\b',
    re.IGNORECASE,
)

# BSL135 — NestedFunctionCalls: word( ... word(
_RE_NESTED_CALL = re.compile(r'\w+\s*\([^)]*\w+\s*\(')

# BSL136 — MissingSpaceBeforeComment: non-whitespace immediately before //
_RE_NO_SPACE_BEFORE_COMMENT = re.compile(r'\S//')

# BSL137 — UseOfFindByDescription: slow search methods
_RE_FIND_BY_DESCRIPTION = re.compile(
    r'\b(?:НайтиПоНаименованию|FindByDescription'
    r'|НайтиПоКоду|FindByCode'
    r'|НайтиПоРеквизиту|FindByAttribute)\s*\(',
    re.IGNORECASE,
)

# BSL138 — UseOfDebugOutput: Сообщить()/Message()/Предупреждение()/Warning()
_RE_DEBUG_OUTPUT = re.compile(
    r'\b(?:Сообщить|Message|Предупреждение|Warning)\s*\(',
    re.IGNORECASE,
)

# BSL141 — MagicBooleanReturn
_RE_RETURN_TRUE = re.compile(
    r'^\s*(?:Возврат|Return)\s+(?:Истина|True)\s*;',
    re.IGNORECASE,
)
_RE_RETURN_FALSE = re.compile(
    r'^\s*(?:Возврат|Return)\s+(?:Ложь|False)\s*;',
    re.IGNORECASE,
)

# BSL143 — DuplicateElseIfCondition: extract condition text from Если/ИначеЕсли
_RE_IF_COND = re.compile(
    r'^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(.*?)\s+(?:Тогда|Then)\s*$',
    re.IGNORECASE,
)

# BSL144 — UnnecessaryParentheses: Возврат (expr)
_RE_RETURN_PAREN = re.compile(
    r'^\s*(?:Возврат|Return)\s+\((?!\s*(?:Новый|New)\b)',
    re.IGNORECASE,
)

# BSL145 — StringFormatInsteadOfConcat: 3+ string parts with +
_RE_MULTI_CONCAT = re.compile(r'"[^"]*"\s*\+[^+;]+\+[^+;]+\+')

# BSL147 — UseOfUICall: ОткрытьФорму()/OpenForm() etc.
_RE_UI_CALL = re.compile(
    r'\b(?:ОткрытьФорму|OpenForm|ПоказатьПредупреждение|ShowMessageBox'
    r'|ПоказатьВопрос|ShowQueryBox)\s*\(',
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
        # Compilation directive regions (form/command modules)
        "накликенте",
        "насервере",
        "накликентенасервере",
        "накликентенасервереберконтекста",
        "насервереберконтекста",
        "обработчикиподписок",
        "onclient",
        "onserver",
        "onclientandserver",
        "onclientandserverwithoutcontext",
        "onserverwithoutcontext",
        "subscriptionhandlers",
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
    for raw in split_commas_outside_double_quotes(params_str):
        raw = raw.strip()
        if not raw:
            continue
        is_val = bool(re.match(r"^(?:Знач|Val)\s+", raw, re.IGNORECASE))
        clean = strip_leading_val_keywords(raw)
        is_optional = "=" in clean
        name = clean.split("=")[0].strip()
        if name and re.match(r"^\w+$", name):
            result.append((name, is_val, is_optional))
    return result


def _ts_node_text(node: Any) -> str:
    """Decode tree-sitter node text to str."""
    t = getattr(node, "text", None)
    if t is None:
        return ""
    return t.decode("utf-8", errors="replace") if isinstance(t, bytes) else str(t)


def _find_procedures_from_tree(tree: Any) -> list[_ProcInfo]:
    """Extract procedure/function definitions from a tree-sitter CST.

    Handles multi-line signatures correctly (e.g. params on multiple lines).
    Returns empty list if *tree* is not a real tree-sitter tree.
    """
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []

    result: list[_ProcInfo] = []
    _collect_procs_from_node(root, result)
    return result


# BSL051 — tree-sitter nodes that close or branch control flow (not executable body).
# Matches keyword roles in formatter_structural (if/while/for/try).
_BSL051_BLOCK_DELIMITER_TYPES = frozenset(
    {
        "ENDIF_KEYWORD",
        "ENDDO_KEYWORD",
        "ENDTRY_KEYWORD",
        "EXCEPT_KEYWORD",
        "ELSE_KEYWORD",
        "ELSIF_KEYWORD",
    }
)

# Regex fallback when tree-sitter is unavailable (_RegexTree) or the tree has ERROR nodes.
_RE_BSL051_DELIMITER_FALLBACK = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo"
    r"|КонецПопытки|EndTry"
    r"|Исключение|Except|Иначе|Else|ИначеЕсли|ElsIf)\b",
    re.IGNORECASE,
)

# Pre-compiled patterns shared across hot-path rules (avoid per-call re.compile overhead).
_RE_LINE_COMMENT = re.compile(r"^\s*//")
_RE_DOUBLE_QUOTED_STRING = re.compile(r'"[^"]*"')
_RE_BSL240_ASSIGN = re.compile(
    r"^\s*(\w+)\s*=\s*(?!.*\b\1\b)",  # LHS = expr not containing LHS
    re.UNICODE,
)
_RE_BSL240_PARAM_HEADER = re.compile(
    r"^\s*(?:Процедура|Функция|Procedure|Function)\s+\w+\s*\(([^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL240_ZNACH = re.compile(r"^\s*(?:Знач|Val)\s+", re.IGNORECASE)
# BSL029: single-quoted date/string literals (remove before scanning for magic numbers)
_RE_SINGLE_QUOTED_STRING = re.compile(r"'[^']*'")
# BSL029: simple direct assignment Var = N; — BSLLS does not flag these
_RE_BSL029_SIMPLE_ASSIGN = re.compile(
    r"^\s*[\w\.]+\s*=\s*-?[0-9]+(?:\.[0-9]+)?\s*;?\s*$"
)
# BSL029: For loop header — Для X = N По M Цикл — BSLLS does not flag loop bounds
_RE_BSL029_FOR_HEADER = re.compile(
    r"^\s*(?:Для|For)\b", re.IGNORECASE
)
# BSL029: ternary operator ?(cond, N, M) — BSLLS does not flag numeric values in ternary
# because they are TernaryOperatorContext, not CallParamContext
_RE_BSL029_TERNARY = re.compile(r"\?\s*\([^)]*\)")
# BSL029: Structure.Вставить("key", value) — BSLLS skips second param when first is a
# string literal (confirmed Structure type). Heuristic: first param is string → structure value.
_RE_BSL029_STRUCT_INSERT = re.compile(
    r'\.(?:Вставить|Insert)\s*\(\s*(?:"[^"]*"|\'[^\']*\')\s*,\s*([^)]+)\)',
    re.IGNORECASE,
)


def _collect_bsl051_delimiter_lines_from_tree(root: Any) -> set[int]:
    """Return 0-based line indices of block delimiter keywords in the CST."""

    lines: set[int] = set()

    def _walk(node: Any) -> None:
        if node.type in _BSL051_BLOCK_DELIMITER_TYPES:
            lines.add(node.start_point[0])
        for child in node.children:
            _walk(child)

    _walk(root)
    return lines


def _bsl051_delimiter_lines_for_tree(tree: Any) -> set[int] | None:
    """
    Delimiter line set from the CST, or None to use :data:`_RE_BSL051_DELIMITER_FALLBACK`.

    None when not a tree-sitter parse or when the tree contains ERROR/missing nodes
    (structure is unreliable).
    """
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return None
    if tree_has_errors(root):
        return None
    return _collect_bsl051_delimiter_lines_from_tree(root)


# BSL052 — literal True/False in If / ElsIf condition (tree-sitter CST).
def _bsl052_literal_boolean_from_expression(expr: Any) -> str | None:
    """
    If *expr* is an ``expression`` node whose only value is a boolean literal,
    return the literal as spelled in source (Истина, Ложь, True, False).
    """
    if getattr(expr, "type", None) != "expression":
        return None
    meaningful = [c for c in expr.children if c.type not in (";",)]
    if len(meaningful) != 1:
        return None
    child = meaningful[0]
    if child.type != "const_expression":
        return None
    for c in child.children:
        if c.type != "boolean":
            continue
        for bc in c.children:
            if bc.type in ("TRUE_KEYWORD", "FALSE_KEYWORD"):
                return _ts_node_text(bc)
    return None


def _bsl052_collect_literal_if_nodes(root: Any, out: list[tuple[int, str]]) -> None:
    """Fill *out* with (0-based line of Если/ИначеЕсли, literal text) for useless conditions."""

    def _from_if_like(node: Any) -> None:
        keyword_line: int | None = None
        for c in node.children:
            if c.type in ("IF_KEYWORD", "ELSIF_KEYWORD"):
                keyword_line = c.start_point[0]
            elif c.type == "expression":
                lit = _bsl052_literal_boolean_from_expression(c)
                if lit is not None and keyword_line is not None:
                    out.append((keyword_line, lit))
                return
            elif c.type == "THEN_KEYWORD":
                break

    def walk(node: Any) -> None:
        if node.type in ("if_statement", "elseif_clause"):
            _from_if_like(node)
        for c in node.children:
            walk(c)

    walk(root)


def _collect_procs_from_node(node: Any, result: list[_ProcInfo]) -> None:
    """Recursively walk the CST collecting procedure/function definition nodes."""
    if node.type in ("procedure_definition", "function_definition"):
        proc = _ts_node_to_proc_info(node)
        if proc:
            result.append(proc)
        return  # BSL does not allow nested procedures
    for child in node.children:
        _collect_procs_from_node(child, result)


def _ts_node_to_proc_info(node: Any) -> _ProcInfo | None:
    """Convert a tree-sitter procedure/function node to _ProcInfo."""
    name = ""
    params: list[str] = []
    val_params: list[str] = []
    optional_count = 0
    is_export = False

    optional_params_list: list[str] = []
    for child in node.children:
        ct = child.type
        if ct == "identifier" and not name:
            name = _ts_node_text(child)
        elif ct == "EXPORT_KEYWORD":
            is_export = True
        elif ct == "parameters":
            for param in child.children:
                if param.type != "parameter":
                    continue
                param_name = ""
                is_val = False
                has_default = False
                for pc in param.children:
                    if pc.type == "VAL_KEYWORD":
                        is_val = True
                    elif pc.type == "identifier" and not param_name:
                        param_name = _ts_node_text(pc)
                    elif pc.type == "=":
                        has_default = True
                if param_name:
                    params.append(param_name)
                    if is_val:
                        val_params.append(param_name)
                    if has_default:
                        optional_count += 1
                        optional_params_list.append(param_name)

    if not name:
        return None

    kind = "function" if node.type == "function_definition" else "procedure"
    return _ProcInfo(
        name=name,
        kind=kind,
        start_idx=node.start_point[0],
        end_idx=node.end_point[0],
        is_export=is_export,
        params=params,
        val_params=val_params,
        optional_count=optional_count,
        header_col=node.start_point[1],
        optional_params=frozenset(optional_params_list),
    )


def _find_proc_definition_node(tree: Any, proc: _ProcInfo) -> Any | None:
    """Return the tree-sitter procedure/function node matching *proc*, or None."""
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return None

    def walk(node: Any) -> Any | None:
        if node.type in ("procedure_definition", "function_definition"):
            info = _ts_node_to_proc_info(node)
            if (
                info
                and info.name == proc.name
                and info.start_idx == proc.start_idx
                and info.kind == proc.kind
            ):
                return node
        for child in node.children:
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(root)


def _build_proc_node_map(tree: Any) -> dict[tuple[str, int, str], Any]:
    """Single tree walk → mapping (name, start_idx, kind) → tree-sitter node.

    Replaces repeated O(P × T) calls to :func:`_find_proc_definition_node` with
    a single O(T) pass followed by O(1) dict lookups.  Build once in
    ``_run_rules``; share across all rules that need per-proc CST nodes
    (currently BSL062 and BSL240).
    """
    out: dict[tuple[str, int, str], Any] = {}
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return out

    def collect(node: Any) -> None:
        if node.type in ("procedure_definition", "function_definition"):
            info = _ts_node_to_proc_info(node)
            if info:
                out[(info.name, info.start_idx, info.kind)] = node
            return  # BSL does not allow nested procedures
        for child in node.children:
            collect(child)

    collect(root)
    return out


def _ts_first_body_statement_line_idx(proc_node: Any) -> int | None:
    """First 0-based line of a body statement (after ``parameters`` and optional ``Экспорт``)."""
    seen_params = False
    for ch in proc_node.children:
        if ch.type == "parameters":
            seen_params = True
            continue
        if not seen_params:
            continue
        if ch.type == "EXPORT_KEYWORD":
            continue
        if ch.type in ("ENDPROCEDURE_KEYWORD", "ENDFUNCTION_KEYWORD"):
            return None
        return ch.start_point[0]
    return None


def _proc_body_start_line_idx_fallback(lines: list[str], proc: _ProcInfo) -> int:
    """First line after procedure/function header when CST is unavailable (paren balance)."""
    i = proc.start_idx
    depth = 0
    started = False
    while i < len(lines) and i <= proc.end_idx:
        for ch in lines[i]:
            if ch == "(":
                depth += 1
                started = True
            elif ch == ")":
                depth -= 1
        if started and depth == 0:
            return i + 1
        i += 1
    return proc.start_idx + 1


def _export_description_anchor_line_idx(lines: list[str], header_idx: int) -> int | None:
    """
    Index of the line that must be a ``//`` description for BSL065.

    Skips blank lines and form/compiler ``&...`` lines between comment and header.
    """
    j = header_idx - 1
    while j >= 0:
        raw = lines[j]
        if not raw.strip():
            j -= 1
            continue
        if _RE_FORM_COMPILER_DIRECTIVE_LINE.match(raw):
            j -= 1
            continue
        return j
    return None


def _collect_identifier_casefolds_in_proc_body(proc_node: Any) -> set[str]:
    """
    Identifier names in the method body from the CST (excluding the ``parameters`` subtree).

    Includes the procedure/function name identifier and all references in the body.
    """
    out: set[str] = set()

    def walk(n: Any) -> None:
        if n.type == "parameters":
            return
        if n.type == "identifier":
            t = _ts_node_text(n)
            if t:
                out.add(t.casefold())
        for c in n.children:
            walk(c)

    for child in proc_node.children:
        if child.type == "parameters":
            continue
        walk(child)
    return out


def _find_procedures(content: str) -> list[_ProcInfo]:
    """Extract procedure/function definitions via regex (fallback only).

    Prefer _find_procedures_from_tree() when a tree-sitter tree is available.
    This regex path is kept as a fallback for the regex-tree (_RegexTree) mode.
    """
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
        optional_params = frozenset(p[0] for p in parsed if p[2])

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
                optional_params=optional_params,
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


def _find_regions_from_tree(tree: Any) -> list[_RegionInfo]:
    """
    Extract #Область/#Region blocks from a tree-sitter CST.

    Returns an empty list if *tree* is not a real tree-sitter tree
    (fallback to regex is expected).
    """

    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), bytes):
        return []

    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) == "preprocessor":
            child_types = {getattr(c, "type", None) for c in getattr(node, "children", [])}

            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0

            if "PREPROC_REGION_KEYWORD" in child_types:
                region_name = ""
                seen_keyword = False
                for c in getattr(node, "children", []):
                    if getattr(c, "type", None) == "PREPROC_REGION_KEYWORD":
                        seen_keyword = True
                        continue
                    if seen_keyword and getattr(c, "type", None) == "identifier":
                        region_name = _ts_node_text(c)
                        break
                opens.append((start_idx, region_name))
                return

            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(node.start_point[0])
                return

        for child in getattr(node, "children", []):
            visit(child)

    visit(root)

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


def _ts_node_is_under_parameters(node: Any) -> bool:
    """True if *node* is inside a ``parameters`` subtree (default values, etc.)."""
    p = getattr(node, "parent", None)
    while p is not None:
        if getattr(p, "type", None) == "parameters":
            return True
        p = getattr(p, "parent", None)
    return False


def _ts_assignment_is_bare_self_assign(node: Any) -> bool:
    """``identifier = identifier`` only (not ``Obj.Field = Field``)."""
    if getattr(node, "type", None) != "assignment_statement":
        return False
    ch = getattr(node, "children", []) or []
    if not ch or getattr(ch[0], "type", None) != "identifier":
        return False
    left = _ts_node_text(ch[0])
    expr_node = None
    for c in ch:
        if getattr(c, "type", None) == "expression":
            expr_node = c
            break
    if expr_node is None:
        return False
    ech = getattr(expr_node, "children", []) or []
    if len(ech) != 1 or getattr(ech[0], "type", None) != "identifier":
        return False
    return left == _ts_node_text(ech[0])


def _ts_expr_is_boolean_literal(expr: Any) -> bool:
    """Right-hand ``Истина``/``Ложь``/``True``/``False`` as const boolean."""
    if getattr(expr, "type", None) != "expression":
        return False
    ech = getattr(expr, "children", []) or []
    if len(ech) != 1:
        return False
    ce = ech[0]
    if getattr(ce, "type", None) != "const_expression":
        return False
    for x in getattr(ce, "children", []) or []:
        if getattr(x, "type", None) != "boolean":
            continue
        for k in getattr(x, "children", []) or []:
            if getattr(k, "type", None) in ("TRUE_KEYWORD", "FALSE_KEYWORD"):
                return True
    return False


def _ts_binary_expr_is_eq_bool_literal(be: Any) -> bool:
    """``expr = Истина|Ложь|True|False`` (comparison to boolean literal)."""
    if getattr(be, "type", None) != "binary_expression":
        return False
    ch = getattr(be, "children", []) or []
    if len(ch) < 3:
        return False
    if getattr(ch[1], "type", None) != "operator":
        return False
    if _ts_node_text(ch[1]).strip() != "=":
        return False
    return _ts_expr_is_boolean_literal(ch[2])


def _ts_expr_is_bool_literal_comparison(expr: Any) -> bool:
    """Single ``binary_expression`` under ``expression``."""
    if getattr(expr, "type", None) != "expression":
        return False
    ech = getattr(expr, "children", []) or []
    if len(ech) != 1 or getattr(ech[0], "type", None) != "binary_expression":
        return False
    return _ts_binary_expr_is_eq_bool_literal(ech[0])


def _diagnostics_bsl009_from_tree(path: str, root: Any) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    def walk(node: Any) -> None:
        if (
            getattr(node, "type", None) == "assignment_statement"
            and not _ts_node_is_under_parameters(node)
            and _ts_assignment_is_bare_self_assign(node)
        ):
            start = node.start_point
            end = node.end_point
            left_t = ""
            for c in getattr(node, "children", []) or []:
                if getattr(c, "type", None) == "identifier":
                    left_t = _ts_node_text(c)
                    break
            diags.append(
                Diagnostic(
                    file=path,
                    line=start[0] + 1,
                    character=start[1],
                    end_line=end[0] + 1,
                    end_character=end[1],
                    severity=Severity.WARNING,
                    code="BSL009",
                    message=f"Self-assignment: variable '{left_t}' is assigned to itself",
                )
            )
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
    return diags


def _bsl059_collect_if_statement(node: Any, path: str, diags: list[Diagnostic]) -> None:
    """First condition + each elseif_clause ``expression`` (skip when ``Тогда`` body is empty — BSL004)."""
    ch = list(getattr(node, "children", []) or [])
    i = 0
    if i < len(ch) and getattr(ch[i], "type", None) == "IF_KEYWORD":
        i += 1
    else:
        return
    if i < len(ch) and getattr(ch[i], "type", None) == "expression":
        expr_node = ch[i]
        i += 1
    else:
        return
    if i >= len(ch) or getattr(ch[i], "type", None) != "THEN_KEYWORD":
        return
    if not ts_if_main_then_branch_empty(node):
        _append_bsl059_if_expr(expr_node, path, diags)
    for c in ch:
        if getattr(c, "type", None) != "elseif_clause":
            continue
        ech = list(getattr(c, "children", []) or [])
        j = 0
        if j < len(ech) and getattr(ech[j], "type", None) == "ELSIF_KEYWORD":
            j += 1
        eexpr = None
        if j < len(ech) and getattr(ech[j], "type", None) == "expression":
            eexpr = ech[j]
        if eexpr is None:
            continue
        if not ts_elseif_then_branch_empty(c):
            _append_bsl059_if_expr(eexpr, path, diags)


def _append_bsl059_if_expr(expr_node: Any, path: str, diags: list[Diagnostic]) -> None:
    if not _ts_expr_is_bool_literal_comparison(expr_node):
        return
    be = None
    for c in getattr(expr_node, "children", []) or []:
        if getattr(c, "type", None) == "binary_expression":
            be = c
            break
    span = be if be is not None else expr_node
    start = span.start_point
    end = span.end_point
    diags.append(
        Diagnostic(
            file=path,
            line=start[0] + 1,
            character=start[1],
            end_line=end[0] + 1,
            end_character=end[1],
            severity=Severity.INFORMATION,
            code="BSL059",
            message=(
                "In If/ElseIf condition: comparison to boolean literal — "
                "use the expression directly: "
                "'Если А Тогда' instead of 'Если А = Истина Тогда'."
            ),
        )
    )


def _diagnostics_bsl059_from_tree(path: str, root: Any) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    def walk(node: Any) -> None:
        if getattr(node, "type", None) == "if_statement":
            _bsl059_collect_if_statement(node, path, diags)
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
    return diags


def _calc_cognitive_complexity(lines: list[str], start_idx: int, end_idx: int) -> int:
    """
    Calculate simplified Cognitive Complexity for a procedure body.

    Scoring (per SonarSource specification):
    - Each structural element (if/for/while/try) adds 1 + nesting level
    - Each else/elseif/except adds 1 (no nesting bonus)
    - Closing tokens decrease nesting
    - Each logical operator (И/ИЛИ/And/Or) in non-comment code adds 1 (Sonar/BSLLS alignment)
    """
    complexity = 0
    nesting = 0
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        line_no_strings = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
        complexity += len(_RE_MCCABE_BOOL.findall(line_no_strings))
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
# Rule task execution (within one file)
# ---------------------------------------------------------------------------


def _execute_diagnostic_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
) -> list[Diagnostic]:
    """
    Run enabled rule callables in declaration order.

    Rules must run in the main thread: tree-sitter ``Parser`` is not thread-safe,
    and optional ``symbol_index`` backends (e.g. SQLite) are not shared across
    worker threads.
    """
    out: list[Diagnostic] = []
    for _code, fn in tasks:
        out.extend(fn())
    return out


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

    # Rules disabled by default.
    #
    # Strategy:
    #  - BSL001–BSL070: keep enabled (direct BSL-LS equivalents).
    #  - BSL071–BSL147: disabled unless they are unique critical checks with
    #    no earlier equivalent (BSL077, BSL097, BSL117, BSL125, BSL126,
    #    BSL133, BSL140, BSL143, BSL147 stay ON).
    #  - A few BSL001-BSL070 that are high-noise are also in this set.
    DEFAULT_DISABLED: frozenset[str] = frozenset(
        {
            # ── BSL001–BSL070 noise/style preferences ──────────────────────
            "BSL008",  # TooManyReturns — BSLLS disabled by default
            "BSL013",  # CommentedCode — high false-positive rate
            "BSL016",  # NonStandardRegion — BSLLS doesn't flag application-specific region names in practice
            "BSL018",  # RaiseWithLiteral — opt-in; bare literals are normal; extended syntax is optional
            "BSL038",  # StringConcatenationInLoop — no direct BSLLS equivalent (BSLLS doesn't flag this)
            "BSL041",  # NotifyDescriptionToModalWindow — no BSLLS equivalent
            "BSL042",  # EmptyExportMethod — BSLLS UnusedLocalMethod has different semantics (non-export dead methods)
            "BSL065",  # MissingExportComment — our rule checks any comment existence; BSLLS MissingReturnedValueDescription only fires when description exists but lacks return type section (30 FP, 0 TP on 30-file sample)
            "BSL059",  # BoolLiteralComparison — no direct BSLLS equivalent
            "BSL063",  # LargeModule — BSLLS analyze часто не даёт эквивалент на строке 1; включите при необходимости
            "BSL074",  # TodoComment — duplicate of BSL023
            "BSL120",  # TrailingWhitespace — noisy in diffs
            "BSL121",  # TabIndentation — style preference
            "BSL136",  # MissingSpaceBeforeComment — enforced by formatter
            # ── BSL071–BSL147 duplicates (earlier BSL-LS rule takes priority) ─
            "BSL071",  # MagicNumber — duplicate of BSL029
            "BSL072",  # StringConcatenationInLoop — duplicate of BSL038
            "BSL073",  # MissingElseBranch — duplicate of BSL046
            "BSL075",  # GlobalVariableModification — duplicate of BSL054
            "BSL076",  # NegativeConditionFirst — no BSL-LS equivalent
            "BSL078",  # RaiseWithoutMessage — duplicate of BSL018
            "BSL079",  # UsingGoto — duplicate of BSL027
            "BSL080",  # SilentCatch — duplicate of BSL004
            "BSL081",  # LongMethodChain — no BSL-LS equivalent
            "BSL082",  # MissingNewlineAtEndOfFile — no BSL-LS equivalent
            "BSL083",  # TooManyModuleVariables — duplicate of BSL043
            "BSL084",  # FunctionWithNoReturn — duplicate of BSL032
            "BSL085",  # LiteralBooleanCondition — duplicate of BSL052
            "BSL086",  # HttpRequestInLoop — no direct BSL-LS equivalent
            "BSL087",  # ObjectCreationInLoop — no BSL-LS equivalent
            "BSL088",  # MissingParameterComment — duplicate of BSL065
            "BSL089",  # TransactionInLoop — duplicate of BSL050
            "BSL090",  # HardcodedConnectionString — duplicate of BSL012
            "BSL091",  # RedundantElseAfterReturn — no BSL-LS equivalent
            "BSL092",  # EmptyElseBlock — duplicate of BSL004
            "BSL093",  # ComparisonToNull — no BSL-LS equivalent
            "BSL094",  # AssignmentToItself — duplicate of BSL009
            "BSL095",  # MultipleStatementsOnOneLine — no BSL-LS equivalent
            "BSL096",  # UndocumentedExportMethod — duplicate of BSL065
            "BSL098",  # UseOfExecute — duplicate of BSL053
            "BSL099",  # TooManyParameters — duplicate of BSL031
            "BSL100",  # HardcodedFilePath — duplicate of BSL006
            "BSL101",  # TooDeepNesting — duplicate of BSL020
            "BSL102",  # LargeModule — duplicate of BSL063
            "BSL103",  # UseOfEval — duplicate of BSL053
            "BSL104",  # MissingModuleComment — no BSL-LS equivalent
            "BSL105",  # UseOfSleep — no direct BSL-LS equivalent
            "BSL106",  # QueryInLoop — duplicate of BSL033
            "BSL107",  # EmptyThenBranch — duplicate of BSL004
            "BSL108",  # UseOfGlobalVariables — duplicate of BSL054
            "BSL109",  # NegativeConditionalReturn — no BSL-LS equivalent
            "BSL110",  # StringConcatInLoop — duplicate of BSL038
            "BSL111",  # MixedLanguageIdentifiers — duplicate of BSL208 (LatinAndCyrillicSymbolInWord / Typo family)
            "BSL112",  # UnterminatedTransaction — duplicate of BSL050
            "BSL113",  # AssignmentInCondition — semantically invalid for BSL
            "BSL114",  # EmptyModule — duplicate of BSL048
            "BSL115",  # ChainedNegation — duplicate of BSL060
            "BSL116",  # UseOfObsoleteIterator — no BSL-LS equivalent
            "BSL118",  # FunctionReturnsNothing — duplicate of BSL032
            "BSL119",  # LineTooLong — duplicate of BSL014
            "BSL122",  # UnusedParameter — duplicate of BSL062
            "BSL123",  # CommentedOutCode — duplicate of BSL013
            "BSL124",  # ShortProcedureName — duplicate of BSL056
            "BSL127",  # MultipleReturnValues — no BSL-LS equivalent
            "BSL128",  # DeadCodeAfterReturn — duplicate of BSL051
            "BSL129",  # RecursiveCall — no BSL-LS equivalent
            "BSL130",  # LongCommentLine — duplicate of BSL014
            "BSL131",  # EmptyRegion — duplicate of BSL026
            "BSL132",  # RepeatedStringLiteral — duplicate of BSL035
            "BSL134",  # CyclomaticComplexity — duplicate of BSL019
            "BSL135",  # NestedFunctionCalls — no BSL-LS equivalent
            "BSL137",  # UseOfFindByDescription — no direct BSL-LS equivalent
            "BSL138",  # UseOfDebugOutput — no BSL-LS equivalent
            "BSL139",  # TooLongParameterName — no BSL-LS equivalent
            "BSL141",  # MagicBooleanReturn — no BSL-LS equivalent
            "BSL142",  # LargeParameterDefaultValue — no BSL-LS equivalent
            "BSL144",  # UnnecessaryParentheses — no BSL-LS equivalent
            "BSL145",  # StringFormatInsteadOfConcat — no BSL-LS equivalent
            "BSL146",  # ModuleInitializationCode — no BSL-LS equivalent
            # ── BSL148–BSL279 — stubs, disabled until implemented ────────────
            "BSL148",  # AllFunctionPathMustHaveReturn — TODO
            "BSL149",  # AssignAliasFieldsInQuery — TODO
            "BSL150",  # BadWords — TODO
            # "BSL151" enabled — BeginTransactionBeforeTryCatch implemented
            "BSL152",  # CachedPublic — TODO
            # "BSL153" enabled — CanonicalSpellingKeywords implemented
            "BSL154",  # CodeAfterAsyncCall — TODO
            "BSL155",  # CodeBlockBeforeSub — TODO
            "BSL156",  # CodeOutOfRegion — TODO
            # "BSL157" enabled — CommitTransactionOutsideTryCatch implemented
            "BSL158",  # CommonModuleAssign — TODO
            "BSL159",  # CommonModuleInvalidType — TODO
            "BSL160",  # CommonModuleMissingAPI — TODO
            "BSL161",  # CommonModuleNameCached — TODO
            "BSL162",  # CommonModuleNameClient — TODO
            "BSL163",  # CommonModuleNameClientServer — TODO
            "BSL164",  # CommonModuleNameFullAccess — TODO
            "BSL165",  # CommonModuleNameGlobal — TODO
            "BSL166",  # CommonModuleNameGlobalClient — TODO
            "BSL167",  # CommonModuleNameServerCall — TODO
            "BSL168",  # CommonModuleNameWords — TODO
            "BSL169",  # CompilationDirectiveLost — TODO
            "BSL170",  # CompilationDirectiveNeedLess — TODO
            "BSL171",  # CrazyMultilineString — TODO
            # "BSL172" enabled — DataExchangeLoading implemented
            # "BSL173" enabled — DeletingCollectionItem implemented
            "BSL174",  # DenyIncompleteValues — TODO
            "BSL175",  # DeprecatedAttributes8312 — TODO
            "BSL176",  # DeprecatedMethodCall — TODO
            "BSL177",  # DeprecatedMethods8310 — TODO
            "BSL178",  # DeprecatedMethods8317 — TODO
            "BSL179",  # DeprecatedTypeManagedForm — TODO
            "BSL180",  # DisableSafeMode — TODO
            "BSL181",  # DuplicatedInsertionIntoCollection — TODO
            "BSL182",  # ExcessiveAutoTestCheck — TODO
            # "BSL183" enabled — ExecuteExternalCode implemented
            "BSL184",  # ExecuteExternalCodeInCommonModule — TODO
            "BSL185",  # ExternalAppStarting — TODO
            # "BSL186" enabled — ExtraCommas implemented
            "BSL187",  # FieldsFromJoinsWithoutIsNull — TODO
            "BSL188",  # FileSystemAccess — TODO
            "BSL189",  # ForbiddenMetadataName — TODO
            "BSL190",  # FormDataToValue — TODO
            "BSL191",  # FullOuterJoinQuery — TODO
            "BSL192",  # FunctionNameStartsWithGet — TODO
            "BSL193",  # FunctionOutParameter — TODO
            "BSL194",  # FunctionReturnsSamePrimitive — TODO
            "BSL195",  # GetFormMethod — TODO
            "BSL196",  # GlobalContextMethodCollision8312 — TODO
            # "BSL197" enabled — IfElseDuplicatedCodeBlock implemented
            # "BSL198" enabled — IfElseDuplicatedCondition implemented
            # "BSL199" enabled — IfElseIfEndsWithElse implemented
            "BSL200",  # IncorrectLineBreak — TODO
            "BSL201",  # IncorrectUseLikeInQuery — TODO
            "BSL202",  # IncorrectUseOfStrTemplate — TODO
            "BSL203",  # InternetAccess — TODO
            "BSL204",  # InvalidCharacterInFile — TODO
            "BSL205",  # IsInRoleMethod — TODO
            "BSL206",  # JoinWithSubQuery — TODO
            "BSL207",  # JoinWithVirtualTable — TODO
            # "BSL208" enabled — LatinAndCyrillicSymbolInWord implemented
            "BSL209",  # LogicalOrInJoinQuerySection — TODO
            "BSL210",  # LogicalOrInTheWhereSectionOfQuery — TODO
            "BSL211",  # MetadataObjectNameLength — TODO
            "BSL212",  # MissedRequiredParameter — TODO
            "BSL213",  # MissingCommonModuleMethod — TODO
            "BSL214",  # MissingEventSubscriptionHandler — TODO
            "BSL215",  # MissingParameterDescription — TODO
            # "BSL216" enabled — MissingSpace implemented
            "BSL217",  # MissingTempStorageDeletion — TODO
            "BSL218",  # MissingTemporaryFileDeletion — TODO
            "BSL220",  # MultilineStringInQuery — TODO
            "BSL221",  # MultilingualStringHasAllDeclaredLanguages — TODO
            "BSL222",  # MultilingualStringUsingWithTemplate — TODO
            "BSL223",  # NestedConstructorsInStructureDeclaration — TODO
            "BSL224",  # NestedFunctionInParameters — TODO
            "BSL225",  # NumberOfValuesInStructureConstructor — TODO
            "BSL226",  # OSUsersMethod — TODO
            # "BSL227" enabled — OneStatementPerLine implemented
            "BSL228",  # OrderOfParams — TODO
            "BSL229",  # OrdinaryAppSupport — TODO
            # "BSL230" enabled — PairingBrokenTransaction implemented
            "BSL231",  # PrivilegedModuleMethodCall — TODO
            "BSL232",  # ProtectedModule — TODO
            "BSL233",  # PublicMethodsDescription — TODO
            "BSL234",  # QueryNestedFieldsByDot — TODO
            "BSL235",  # QueryParseError — TODO
            "BSL236",  # QueryToMissingMetadata — TODO
            "BSL237",  # RedundantAccessToObject — TODO
            "BSL238",  # RefOveruse — TODO
            "BSL239",  # ReservedParameterNames — TODO
            # "BSL240" enabled — RewriteMethodParameter implemented
            "BSL241",  # SameMetadataObjectAndChildNames — TODO
            "BSL242",  # ScheduledJobHandler — TODO
            "BSL243",  # SelfInsertion — TODO
            "BSL244",  # ServerCallsInFormEvents — TODO
            "BSL245",  # ServerSideExportFormMethod — TODO
            "BSL246",  # SetPermissionsForNewObjects — TODO
            "BSL247",  # SetPrivilegedMode — TODO
            "BSL248",  # SeveralCompilerDirectives — TODO
            "BSL249",  # StyleElementConstructors — TODO
            "BSL250",  # TempFilesDir — TODO
            "BSL251",  # TernaryOperatorUsage — TODO
            "BSL252",  # ThisObjectAssign — TODO
            "BSL253",  # TimeoutsInExternalResources — TODO
            "BSL254",  # TransferringParametersBetweenClientAndServer — requires cross-reference analysis (which callers are &НаКлиенте); without it produces 32 FP, 0 TP on 30-file sample
            # "BSL255" enabled — TryNumber implemented
            # "BSL256" enabled — Typo (homoglyph Latin/Cyrillic in identifiers; BSLLS priority over BSL208)
            # "BSL257" enabled — UnaryPlusInConcatenation implemented
            # "BSL258" enabled — UnionAll implemented
            "BSL259",  # UnknownPreprocessorSymbol — TODO
            "BSL260",  # UnsafeFindByCode — TODO
            "BSL261",  # UnsafeSafeModeMethodCall — TODO
            "BSL262",  # UsageWriteLogEvent — TODO
            # "BSL263" enabled — UseLessForEach implemented
            "BSL264",  # UseSystemInformation — TODO
            # "BSL265" enabled — UselessTernaryOperator implemented
            "BSL266",  # UsingCancelParameter — TODO
            "BSL267",  # UsingExternalCodeTools — TODO
            "BSL268",  # UsingFindElementByString — TODO
            "BSL269",  # UsingLikeInQuery — TODO
            "BSL270",  # UsingModalWindows — TODO
            "BSL271",  # UsingObjectNotAvailableUnix — TODO
            "BSL272",  # UsingSynchronousCalls — TODO
            "BSL273",  # VirtualTableCallWithoutParameters — TODO
            "BSL274",  # WrongDataPathForFormElements — TODO
            "BSL275",  # WrongHttpServiceHandler — TODO
            "BSL276",  # WrongUseFunctionProceedWithCall — TODO
            "BSL277",  # WrongUseOfRollbackTransactionMethod — TODO
            "BSL278",  # WrongWebServiceHandler — TODO
            # "BSL279" enabled — YoLetterUsage implemented
        }
    )

    # Default thresholds (class-level — can override in __init__)
    MAX_PROC_LINES: int = 200
    MAX_RETURNS: int = 3
    MAX_COGNITIVE_COMPLEXITY: int = 15
    MAX_MCCABE_COMPLEXITY: int = 20
    MAX_NESTING_DEPTH: int = 5
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
        symbol_index: Any | None = None,
    ) -> None:
        # tree_sitter.Parser is not thread-safe — one BslParser per thread unless a
        # single parser is injected (tests). Required for free-threaded CPython / LSP.
        self._injected_parser: BslParser | None = parser
        self._parser_tls = threading.local()
        self._symbol_index = symbol_index
        self._select: set[str] | None = (
            normalize_rule_code_set(select) if select else None
        )
        # Instrumentation for benchmarks/debug: per-thread (free-threading safe).
        self._metrics_tls = threading.local()
        # Merge user ignores with DEFAULT_DISABLED; select= overrides DEFAULT_DISABLED
        _user_ignore: set[str] = normalize_rule_code_set(ignore) if ignore else set()
        _effective_defaults = self.DEFAULT_DISABLED - (self._select or set())
        self._ignore: set[str] = _user_ignore | _effective_defaults
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

    def _get_parser(self) -> BslParser:
        """Return the parser for this thread (tree-sitter Parser is not thread-safe)."""
        if self._injected_parser is not None:
            return self._injected_parser
        p: BslParser | None = getattr(self._parser_tls, "parser", None)
        if p is None:
            p = BslParser()
            self._parser_tls.parser = p
        return p

    @property
    def last_metrics(self) -> dict[str, Any]:
        """Metrics from the last completed ``check_*`` in the current thread (free-threading safe)."""
        data = getattr(self._metrics_tls, "data", None)
        return dict(data) if isinstance(data, dict) else {}

    def _rule_enabled(self, code: str) -> bool:
        """Return True if *code* should be executed."""
        code = code.upper()
        if self._select is not None and code not in self._select:
            return False
        return code not in self._ignore

    def check_content(
        self, path: str, content: str, *, symbol_index: Any | None = None,
    ) -> list[Diagnostic]:
        """
        Run all enabled diagnostic rules on *content* (pre-loaded string).

        Useful for LSP in-memory documents: avoids a second disk read and
        ensures diagnostics reflect the current editor state, not the saved file.

        *symbol_index* is optional; when set, enables metadata-aware rules (e.g. BSL280).
        """
        try:
            tree = self._get_parser().parse_content(content, file_path=path)
        except Exception as exc:
            return [
                Diagnostic(
                    file=path, line=1, character=0, end_line=1, end_character=0,
                    severity=Severity.ERROR, code="BSL001",
                    message=f"Failed to parse content: {exc}",
                )
            ]
        return self._run_rules(path, content, tree, symbol_index=symbol_index)

    def check_file(
        self, path: str, tree: Any | None = None, *, symbol_index: Any | None = None,
    ) -> list[Diagnostic]:
        """
        Run all enabled diagnostic rules on *path*.

        Inline ``// noqa: CODE`` and ``// bsl-disable: CODE`` annotations
        suppress matching diagnostics for their line.

        Returns list of Diagnostic objects sorted by (line, character).

        *symbol_index* is optional; when set, enables metadata-aware rules (e.g. BSL280).
        """
        if tree is None:
            try:
                tree = self._get_parser().parse_file(path)
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
        return self._run_rules(path, content, tree, symbol_index=symbol_index)

    def _run_rules(
        self,
        path: str,
        content: str,
        tree: Any,
        *,
        symbol_index: Any | None = None,
    ) -> list[Diagnostic]:
        """Execute all enabled rules and return filtered, sorted diagnostics."""
        idx = symbol_index if symbol_index is not None else self._symbol_index
        lines = content.splitlines()
        suppressions = _parse_suppressions(lines)

        # Precompute structural info once (shared across rules).
        # Prefer CST-based extraction (handles multi-line signatures, exact
        # boundaries); fall back to regex when tree-sitter is unavailable.
        tree_is_ts = (
            hasattr(tree, "root_node")
            and hasattr(tree.root_node, "text")
            and isinstance(tree.root_node.text, (bytes, bytearray))
        )
        procs_from_tree = _find_procedures_from_tree(tree)
        procs = procs_from_tree or _find_procedures(content)
        proc_source = "ast" if procs_from_tree else "regex"
        regex_fallback_procs_used = 0 if procs_from_tree else 1
        regions_from_tree = _find_regions_from_tree(tree) if tree_is_ts else []
        regions_source = "ast" if regions_from_tree else "regex"
        regex_fallback_regions_used = 0 if regions_from_tree else 1
        last_metrics: dict[str, Any] = {
            "tree_is_ts": bool(tree_is_ts),
            "proc_source": proc_source,
            "regions_source": regions_source,
            "regex_fallback_procs_used": regex_fallback_procs_used,
            "regex_fallback_regions_used": regex_fallback_regions_used,
        }
        regions = regions_from_tree or _find_regions(content)
        last_metrics.update(
            {
                "procs_count": len(procs),
                "regions_count": len(regions),
                "rule_invoke": build_enabled_invoke_snapshot(self, RULE_METADATA),
            }
        )
        self._metrics_tls.data = last_metrics

        # Build proc→node lookup once (single O(T) tree walk).
        # Rules BSL062 and BSL240 use this to avoid repeated O(P × T) walks.
        _proc_node_map: dict[tuple[str, int, str], Any] = (
            _build_proc_node_map(tree) if tree_is_ts else {}
        )

        _rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]] = []

        if self._rule_enabled("BSL001"):
            _rule_tasks.append(("BSL001", lambda: self._rule_bsl001_syntax_errors(path, tree)))
        if self._rule_enabled("BSL002"):
            _rule_tasks.append(("BSL002", lambda: self._rule_bsl002_method_size(path, lines, procs)))
        if self._rule_enabled("BSL003"):
            _rule_tasks.append(("BSL003", lambda: self._rule_bsl003_non_export_in_api_region(path, lines, procs, regions)))
        # BSL004 (EmptyCodeBlock) before BSL059: empty «Тогда» must report BSL004, not BooleanLiteralComparison.
        if self._rule_enabled("BSL004"):
            _rule_tasks.append(("BSL004", lambda: self._rule_bsl004_empty_except(path, lines, tree)))
        if self._rule_enabled("BSL005"):
            _rule_tasks.append(("BSL005", lambda: self._rule_bsl005_hardcode_network_address(path, lines)))
        if self._rule_enabled("BSL006"):
            _rule_tasks.append(("BSL006", lambda: self._rule_bsl006_hardcode_path(path, lines)))
        if self._rule_enabled("BSL007"):
            _rule_tasks.append(("BSL007", lambda: self._rule_bsl007_unused_local_variable(path, lines, procs)))
        if self._rule_enabled("BSL008"):
            _rule_tasks.append(("BSL008", lambda: self._rule_bsl008_too_many_returns(path, lines, procs)))
        if self._rule_enabled("BSL009"):
            _rule_tasks.append(("BSL009", lambda: self._rule_bsl009_self_assign(path, lines, tree)))
        if self._rule_enabled("BSL010"):
            _rule_tasks.append(("BSL010", lambda: self._rule_bsl010_useless_return(path, lines, procs)))
        if self._rule_enabled("BSL011"):
            _rule_tasks.append(("BSL011", lambda: self._rule_bsl011_cognitive_complexity(path, lines, procs)))
        if self._rule_enabled("BSL012"):
            _rule_tasks.append(("BSL012", lambda: self._rule_bsl012_hardcode_credentials(path, lines)))
        if self._rule_enabled("BSL013"):
            _rule_tasks.append(("BSL013", lambda: self._rule_bsl013_commented_code(path, lines)))
        if self._rule_enabled("BSL014"):
            _rule_tasks.append(("BSL014", lambda: self._rule_bsl014_line_too_long(path, lines)))
        if self._rule_enabled("BSL015"):
            _rule_tasks.append(("BSL015", lambda: self._rule_bsl015_optional_params_count(path, lines, procs)))
        if self._rule_enabled("BSL016"):
            _rule_tasks.append(("BSL016", lambda: self._rule_bsl016_non_standard_region(path, lines, regions)))
        if self._rule_enabled("BSL017"):
            _rule_tasks.append(("BSL017", lambda: self._rule_bsl017_export_in_command_module(path, lines, procs)))
        if self._rule_enabled("BSL018"):
            _rule_tasks.append(("BSL018", lambda: self._rule_bsl018_raise_with_literal(path, lines, tree)))
        if self._rule_enabled("BSL019"):
            _rule_tasks.append(("BSL019", lambda: self._rule_bsl019_cyclomatic_complexity(path, lines, procs)))
        if self._rule_enabled("BSL020"):
            _rule_tasks.append(("BSL020", lambda: self._rule_bsl020_excessive_nesting(path, lines, procs)))
        if self._rule_enabled("BSL021"):
            _rule_tasks.append(("BSL021", lambda: self._rule_bsl021_unused_val_parameter(path, lines, procs)))
        if self._rule_enabled("BSL022"):
            _rule_tasks.append(("BSL022", lambda: self._rule_bsl022_deprecated_message(path, lines, procs)))
        if self._rule_enabled("BSL023"):
            _rule_tasks.append(("BSL023", lambda: self._rule_bsl023_service_tag(path, lines)))
        if self._rule_enabled("BSL024"):
            _rule_tasks.append(("BSL024", lambda: self._rule_bsl024_space_at_start_comment(path, lines)))
        if self._rule_enabled("BSL025"):
            _rule_tasks.append(("BSL025", lambda: self._rule_bsl025_empty_statement(path, lines)))
        if self._rule_enabled("BSL026"):
            _rule_tasks.append(("BSL026", lambda: self._rule_bsl026_empty_region(path, lines, regions)))
        if self._rule_enabled("BSL027"):
            _rule_tasks.append(("BSL027", lambda: self._rule_bsl027_use_goto(path, lines)))
        if self._rule_enabled("BSL028"):
            _rule_tasks.append(("BSL028", lambda: self._rule_bsl028_missing_try_catch(path, lines, procs)))
        if self._rule_enabled("BSL029"):
            _rule_tasks.append(("BSL029", lambda: self._rule_bsl029_magic_number(path, lines, procs)))
        if self._rule_enabled("BSL030"):
            def _task_bsl030() -> list[Diagnostic]:
                a = self._rule_bsl030_header_semicolon(path, lines)
                a.extend(self._rule_bsl030_statement_missing_semicolon(path, lines, procs))
                return a
            _rule_tasks.append(("BSL030", _task_bsl030))
        if self._rule_enabled("BSL031"):
            _rule_tasks.append(("BSL031", lambda: self._rule_bsl031_number_of_params(path, lines, procs)))
        if self._rule_enabled("BSL032"):
            _rule_tasks.append(("BSL032", lambda: self._rule_bsl032_function_return_value(path, lines, procs)))
        if self._rule_enabled("BSL033"):
            _rule_tasks.append(("BSL033", lambda: self._rule_bsl033_query_in_loop(path, lines, procs, tree)))
        if self._rule_enabled("BSL034"):
            _rule_tasks.append(("BSL034", lambda: self._rule_bsl034_unused_error_variable(path, lines, procs)))
        if self._rule_enabled("BSL035"):
            _rule_tasks.append(("BSL035", lambda: self._rule_bsl035_duplicate_string_literal(path, lines, procs)))
        if self._rule_enabled("BSL036"):
            _rule_tasks.append(("BSL036", lambda: self._rule_bsl036_complex_condition(path, lines)))
        if self._rule_enabled("BSL037"):
            _rule_tasks.append(("BSL037", lambda: self._rule_bsl037_override_builtin(path, lines, procs)))
        if self._rule_enabled("BSL038"):
            _rule_tasks.append(("BSL038", lambda: self._rule_bsl038_string_concat_in_loop(path, lines, procs, tree)))
        if self._rule_enabled("BSL039"):
            _rule_tasks.append(("BSL039", lambda: self._rule_bsl039_nested_ternary(path, lines)))
        if self._rule_enabled("BSL040"):
            _rule_tasks.append(("BSL040", lambda: self._rule_bsl040_using_this_form(path, lines)))
        if self._rule_enabled("BSL041"):
            _rule_tasks.append(("BSL041", lambda: self._rule_bsl041_notify_description(path, lines, procs)))
        if self._rule_enabled("BSL042"):
            _rule_tasks.append(("BSL042", lambda: self._rule_bsl042_empty_export_method(path, lines, procs)))
        if self._rule_enabled("BSL043"):
            _rule_tasks.append(("BSL043", lambda: self._rule_bsl043_too_many_variables(path, lines, procs)))
        if self._rule_enabled("BSL044"):
            _rule_tasks.append(("BSL044", lambda: self._rule_bsl044_function_no_return_value(path, lines, procs)))
        if self._rule_enabled("BSL045"):
            _rule_tasks.append(("BSL045", lambda: self._rule_bsl045_multiline_string_literal(path, lines)))
        if self._rule_enabled("BSL046"):
            _rule_tasks.append(("BSL046", lambda: self._rule_bsl046_missing_else_branch(path, lines, procs)))
        if self._rule_enabled("BSL047"):
            _rule_tasks.append(("BSL047", lambda: self._rule_bsl047_current_date(path, lines)))
        if self._rule_enabled("BSL048"):
            _rule_tasks.append(("BSL048", lambda: self._rule_bsl048_empty_file(path, lines)))
        if self._rule_enabled("BSL049"):
            _rule_tasks.append(("BSL049", lambda: self._rule_bsl049_unconditional_raise(path, lines, procs)))
        if self._rule_enabled("BSL050"):
            _rule_tasks.append(("BSL050", lambda: self._rule_bsl050_large_transaction(path, lines, procs)))
        if self._rule_enabled("BSL051"):
            _rule_tasks.append(
                (
                    "BSL051",
                    lambda: self._rule_bsl051_unreachable_code(path, lines, procs, tree),
                )
            )
        if self._rule_enabled("BSL052"):
            _rule_tasks.append(("BSL052", lambda: self._rule_bsl052_useless_condition(path, lines, tree)))
        if self._rule_enabled("BSL053"):
            _rule_tasks.append(("BSL053", lambda: self._rule_bsl053_execute_dynamic(path, lines)))
        if self._rule_enabled("BSL054"):
            _rule_tasks.append(("BSL054", lambda: self._rule_bsl054_module_level_variable(path, lines, procs)))
        if self._rule_enabled("BSL219"):
            _rule_tasks.append(
                (
                    "BSL219",
                    lambda: self._rule_bsl219_missing_variables_description(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL055"):
            _rule_tasks.append(("BSL055", lambda: self._rule_bsl055_consecutive_blank_lines(path, lines)))
        if self._rule_enabled("BSL056"):
            _rule_tasks.append(("BSL056", lambda: self._rule_bsl056_short_method_name(path, lines, procs)))
        if self._rule_enabled("BSL057"):
            _rule_tasks.append(("BSL057", lambda: self._rule_bsl057_deprecated_input_dialog(path, lines)))
        if self._rule_enabled("BSL058"):
            _rule_tasks.append(("BSL058", lambda: self._rule_bsl058_query_without_where(path, lines)))
        if self._rule_enabled("BSL059"):
            _rule_tasks.append(("BSL059", lambda: self._rule_bsl059_bool_literal_comparison(path, lines, tree)))
        if self._rule_enabled("BSL060"):
            _rule_tasks.append(("BSL060", lambda: self._rule_bsl060_double_negation(path, lines, tree)))
        if self._rule_enabled("BSL061"):
            _rule_tasks.append(("BSL061", lambda: self._rule_bsl061_abrupt_loop_exit(path, lines, tree)))
        if self._rule_enabled("BSL062"):
            _rule_tasks.append(
                (
                    "BSL062",
                    lambda: self._rule_bsl062_unused_parameter(path, lines, procs, tree, _proc_node_map),
                )
            )
        if self._rule_enabled("BSL063"):
            _rule_tasks.append(("BSL063", lambda: self._rule_bsl063_large_module(path, lines)))
        if self._rule_enabled("BSL064"):
            _rule_tasks.append(("BSL064", lambda: self._rule_bsl064_procedure_returns_value(path, lines, procs)))
        if self._rule_enabled("BSL065"):
            _rule_tasks.append(("BSL065", lambda: self._rule_bsl065_missing_export_comment(path, lines, procs)))
        if self._rule_enabled("BSL066"):
            _rule_tasks.append(("BSL066", lambda: self._rule_bsl066_deprecated_platform_method(path, lines, procs)))
        if self._rule_enabled("BSL067"):
            _rule_tasks.append(("BSL067", lambda: self._rule_bsl067_var_after_code(path, lines, procs)))
        if self._rule_enabled("BSL068"):
            _rule_tasks.append(("BSL068", lambda: self._rule_bsl068_too_many_elseif(path, lines)))
        if self._rule_enabled("BSL069"):
            _rule_tasks.append(("BSL069", lambda: self._rule_bsl069_infinite_loop(path, lines)))
        if self._rule_enabled("BSL070"):
            _rule_tasks.append(("BSL070", lambda: self._rule_bsl070_empty_loop_body(path, lines, tree)))
        if self._rule_enabled("BSL071"):
            _rule_tasks.append(("BSL071", lambda: self._rule_bsl071_magic_number(path, lines, procs)))
        if self._rule_enabled("BSL072"):
            _rule_tasks.append(("BSL072", lambda: self._rule_bsl072_string_concat_in_loop(path, lines)))
        if self._rule_enabled("BSL073"):
            _rule_tasks.append(("BSL073", lambda: self._rule_bsl073_missing_else_branch(path, lines)))
        if self._rule_enabled("BSL074"):
            _rule_tasks.append(("BSL074", lambda: self._rule_bsl074_todo_comment(path, lines)))
        if self._rule_enabled("BSL075"):
            _rule_tasks.append(("BSL075", lambda: self._rule_bsl075_global_variable_modification(path, lines, procs)))
        if self._rule_enabled("BSL076"):
            _rule_tasks.append(("BSL076", lambda: self._rule_bsl076_negative_condition_first(path, lines)))
        if self._rule_enabled("BSL077"):
            _rule_tasks.append(("BSL077", lambda: self._rule_bsl077_select_star(path, lines)))
        if self._rule_enabled("BSL078"):
            _rule_tasks.append(("BSL078", lambda: self._rule_bsl078_raise_without_message(path, lines)))
        if self._rule_enabled("BSL079"):
            _rule_tasks.append(("BSL079", lambda: self._rule_bsl079_using_goto(path, lines)))
        if self._rule_enabled("BSL080"):
            _rule_tasks.append(("BSL080", lambda: self._rule_bsl080_silent_catch(path, lines)))
        if self._rule_enabled("BSL081"):
            _rule_tasks.append(("BSL081", lambda: self._rule_bsl081_long_method_chain(path, lines)))
        if self._rule_enabled("BSL082"):
            _rule_tasks.append(("BSL082", lambda: self._rule_bsl082_missing_newline_at_eof(path, lines)))
        if self._rule_enabled("BSL083"):
            _rule_tasks.append(("BSL083", lambda: self._rule_bsl083_too_many_module_variables(path, lines, procs)))
        if self._rule_enabled("BSL084"):
            _rule_tasks.append(("BSL084", lambda: self._rule_bsl084_function_with_no_return(path, lines, procs)))
        if self._rule_enabled("BSL085"):
            _rule_tasks.append(("BSL085", lambda: self._rule_bsl085_literal_boolean_condition(path, lines, tree)))
        if self._rule_enabled("BSL086"):
            _rule_tasks.append(("BSL086", lambda: self._rule_bsl086_http_request_in_loop(path, lines)))
        if self._rule_enabled("BSL087"):
            _rule_tasks.append(("BSL087", lambda: self._rule_bsl087_object_creation_in_loop(path, lines)))
        if self._rule_enabled("BSL088"):
            _rule_tasks.append(("BSL088", lambda: self._rule_bsl088_missing_parameter_comment(path, lines, procs)))
        if self._rule_enabled("BSL089"):
            _rule_tasks.append(("BSL089", lambda: self._rule_bsl089_transaction_in_loop(path, lines)))
        if self._rule_enabled("BSL090"):
            _rule_tasks.append(("BSL090", lambda: self._rule_bsl090_hardcoded_connection_string(path, lines)))
        if self._rule_enabled("BSL091"):
            _rule_tasks.append(("BSL091", lambda: self._rule_bsl091_redundant_else_after_return(path, lines, procs, tree)))
        if self._rule_enabled("BSL092"):
            _rule_tasks.append(("BSL092", lambda: self._rule_bsl092_empty_else_block(path, lines, tree)))
        if self._rule_enabled("BSL093"):
            _rule_tasks.append(("BSL093", lambda: self._rule_bsl093_comparison_to_null(path, lines)))
        if self._rule_enabled("BSL094"):
            _rule_tasks.append(("BSL094", lambda: self._rule_bsl094_noop_assignment(path, lines)))
        if self._rule_enabled("BSL095"):
            _rule_tasks.append(("BSL095", lambda: self._rule_bsl095_multiple_statements_on_one_line(path, lines)))
        if self._rule_enabled("BSL096"):
            _rule_tasks.append(("BSL096", lambda: self._rule_bsl096_undocumented_export_method(path, lines, procs)))
        if self._rule_enabled("BSL097"):
            _rule_tasks.append(("BSL097", lambda: self._rule_bsl097_use_of_current_date(path, lines)))
        if self._rule_enabled("BSL098"):
            _rule_tasks.append(("BSL098", lambda: self._rule_bsl098_use_of_execute(path, lines)))
        if self._rule_enabled("BSL099"):
            _rule_tasks.append(("BSL099", lambda: self._rule_bsl099_too_many_parameters(path, lines, procs)))
        if self._rule_enabled("BSL100"):
            _rule_tasks.append(("BSL100", lambda: self._rule_bsl100_hardcoded_file_path(path, lines)))
        if self._rule_enabled("BSL101"):
            _rule_tasks.append(("BSL101", lambda: self._rule_bsl101_too_deep_nesting(path, lines)))
        if self._rule_enabled("BSL102"):
            _rule_tasks.append(("BSL102", lambda: self._rule_bsl102_large_module(path, lines)))
        if self._rule_enabled("BSL103"):
            _rule_tasks.append(("BSL103", lambda: self._rule_bsl103_use_of_eval(path, lines)))
        if self._rule_enabled("BSL104"):
            _rule_tasks.append(("BSL104", lambda: self._rule_bsl104_missing_module_comment(path, lines)))
        if self._rule_enabled("BSL105"):
            _rule_tasks.append(("BSL105", lambda: self._rule_bsl105_use_of_sleep(path, lines)))
        if self._rule_enabled("BSL106"):
            _rule_tasks.append(("BSL106", lambda: self._rule_bsl106_query_in_loop(path, lines)))
        if self._rule_enabled("BSL107"):
            _rule_tasks.append(("BSL107", lambda: self._rule_bsl107_empty_then_branch(path, lines)))
        if self._rule_enabled("BSL108"):
            _rule_tasks.append(("BSL108", lambda: self._rule_bsl108_use_of_global_variables(path, lines)))
        if self._rule_enabled("BSL109"):
            _rule_tasks.append(("BSL109", lambda: self._rule_bsl109_negative_conditional_return(path, lines)))
        if self._rule_enabled("BSL110"):
            _rule_tasks.append(("BSL110", lambda: self._rule_bsl110_string_concat_in_loop(path, lines)))
        if self._rule_enabled("BSL111"):
            _rule_tasks.append(("BSL111", lambda: self._rule_bsl111_mixed_language_identifiers(path, lines)))
        if self._rule_enabled("BSL112"):
            _rule_tasks.append(("BSL112", lambda: self._rule_bsl112_unterminated_transaction(path, lines)))
        # BSL113 (AssignmentInCondition) removed — not applicable to BSL
        # where '=' is always comparison, never assignment-as-expression.
        if self._rule_enabled("BSL114"):
            _rule_tasks.append(("BSL114", lambda: self._rule_bsl114_empty_module(path, lines)))
        if self._rule_enabled("BSL115"):
            _rule_tasks.append(("BSL115", lambda: self._rule_bsl115_chained_negation(path, lines)))
        if self._rule_enabled("BSL116"):
            _rule_tasks.append(("BSL116", lambda: self._rule_bsl116_use_of_obsolete_iterator(path, lines)))
        if self._rule_enabled("BSL117"):
            _rule_tasks.append(("BSL117", lambda: self._rule_bsl117_procedure_called_as_function(path, lines, procs)))
        if self._rule_enabled("BSL118"):
            _rule_tasks.append(("BSL118", lambda: self._rule_bsl118_function_returns_nothing(path, lines, procs)))
        if self._rule_enabled("BSL119"):
            _rule_tasks.append(("BSL119", lambda: self._rule_bsl119_line_too_long(path, lines)))
        if self._rule_enabled("BSL120"):
            _rule_tasks.append(("BSL120", lambda: self._rule_bsl120_trailing_whitespace(path, lines)))
        if self._rule_enabled("BSL121"):
            _rule_tasks.append(("BSL121", lambda: self._rule_bsl121_tab_indentation(path, lines)))
        if self._rule_enabled("BSL122"):
            _rule_tasks.append(("BSL122", lambda: self._rule_bsl122_unused_parameter(path, lines, procs)))
        if self._rule_enabled("BSL123"):
            _rule_tasks.append(("BSL123", lambda: self._rule_bsl123_commented_out_code(path, lines)))
        if self._rule_enabled("BSL124"):
            _rule_tasks.append(("BSL124", lambda: self._rule_bsl124_short_procedure_name(path, lines, procs)))
        if self._rule_enabled("BSL125"):
            _rule_tasks.append(("BSL125", lambda: self._rule_bsl125_break_outside_loop(path, lines)))
        if self._rule_enabled("BSL126"):
            _rule_tasks.append(("BSL126", lambda: self._rule_bsl126_continue_outside_loop(path, lines)))
        if self._rule_enabled("BSL127"):
            _rule_tasks.append(("BSL127", lambda: self._rule_bsl127_multiple_return_values(path, lines, procs)))
        if self._rule_enabled("BSL128"):
            _rule_tasks.append(("BSL128", lambda: self._rule_bsl128_dead_code_after_return(path, lines, procs)))
        if self._rule_enabled("BSL129"):
            _rule_tasks.append(("BSL129", lambda: self._rule_bsl129_recursive_call(path, lines, procs)))
        if self._rule_enabled("BSL130"):
            _rule_tasks.append(("BSL130", lambda: self._rule_bsl130_long_comment_line(path, lines)))
        if self._rule_enabled("BSL131"):
            _rule_tasks.append(("BSL131", lambda: self._rule_bsl131_empty_region(path, lines)))
        if self._rule_enabled("BSL132"):
            _rule_tasks.append(("BSL132", lambda: self._rule_bsl132_repeated_string_literal(path, lines, content)))
        if self._rule_enabled("BSL133"):
            _rule_tasks.append(("BSL133", lambda: self._rule_bsl133_required_param_after_optional(path, lines, procs)))
        if self._rule_enabled("BSL134"):
            _rule_tasks.append(("BSL134", lambda: self._rule_bsl134_cyclomatic_complexity(path, lines, procs)))
        if self._rule_enabled("BSL135"):
            _rule_tasks.append(("BSL135", lambda: self._rule_bsl135_nested_function_calls(path, lines)))
        if self._rule_enabled("BSL136"):
            _rule_tasks.append(("BSL136", lambda: self._rule_bsl136_missing_space_before_comment(path, lines)))
        if self._rule_enabled("BSL137"):
            _rule_tasks.append(("BSL137", lambda: self._rule_bsl137_use_of_find_by_description(path, lines)))
        if self._rule_enabled("BSL138"):
            _rule_tasks.append(("BSL138", lambda: self._rule_bsl138_use_of_debug_output(path, lines)))
        if self._rule_enabled("BSL139"):
            _rule_tasks.append(("BSL139", lambda: self._rule_bsl139_too_long_parameter_name(path, lines, procs)))
        if self._rule_enabled("BSL140"):
            _rule_tasks.append(("BSL140", lambda: self._rule_bsl140_unreachable_elseif(path, lines)))
        if self._rule_enabled("BSL141"):
            _rule_tasks.append(("BSL141", lambda: self._rule_bsl141_magic_boolean_return(path, lines, procs)))
        if self._rule_enabled("BSL142"):
            _rule_tasks.append(("BSL142", lambda: self._rule_bsl142_large_param_default_value(path, lines, procs)))
        if self._rule_enabled("BSL143"):
            _rule_tasks.append(("BSL143", lambda: self._rule_bsl143_duplicate_elseif_condition(path, lines)))
        if self._rule_enabled("BSL144"):
            _rule_tasks.append(("BSL144", lambda: self._rule_bsl144_unnecessary_parentheses(path, lines)))
        if self._rule_enabled("BSL145"):
            _rule_tasks.append(("BSL145", lambda: self._rule_bsl145_string_format_instead_of_concat(path, lines)))
        if self._rule_enabled("BSL146"):
            _rule_tasks.append(("BSL146", lambda: self._rule_bsl146_module_initialization_code(path, lines, procs)))
        if self._rule_enabled("BSL147"):
            _rule_tasks.append(("BSL147", lambda: self._rule_bsl147_use_of_ui_call(path, lines, procs)))
        if self._rule_enabled("BSL151"):
            _rule_tasks.append(("BSL151", lambda: self._rule_bsl151_begin_transaction_before_try(path, lines)))
        if self._rule_enabled("BSL157"):
            _rule_tasks.append(("BSL157", lambda: self._rule_bsl157_commit_transaction_outside_try(path, lines)))
        if self._rule_enabled("BSL173"):
            _rule_tasks.append(("BSL173", lambda: self._rule_bsl173_deleting_collection_item(path, lines, procs)))
        if self._rule_enabled("BSL257"):
            _rule_tasks.append(("BSL257", lambda: self._rule_bsl257_unary_plus_in_concatenation(path, lines)))
        if self._rule_enabled("BSL279"):
            _rule_tasks.append(("BSL279", lambda: self._rule_bsl279_yo_letter_usage(path, lines)))
        if self._rule_enabled("BSL280") and idx is not None:
            def _task_bsl280() -> list[Diagnostic]:
                from onec_hbk_bsl.analysis.metadata_refs import diagnostics_unknown_metadata_objects
                return diagnostics_unknown_metadata_objects(path, content, idx)
            _rule_tasks.append(("BSL280", _task_bsl280))
        if self._rule_enabled("BSL172"):
            _rule_tasks.append(("BSL172", lambda: self._rule_bsl172_data_exchange_loading(path, lines, procs)))
        if self._rule_enabled("BSL186"):
            _rule_tasks.append(("BSL186", lambda: self._rule_bsl186_extra_commas(path, lines)))
        if self._rule_enabled("BSL197"):
            _rule_tasks.append(("BSL197", lambda: self._rule_bsl197_if_else_duplicated_code_block(path, lines)))
        if self._rule_enabled("BSL198"):
            _rule_tasks.append(("BSL198", lambda: self._rule_bsl198_if_else_duplicated_condition(path, lines)))
        if self._rule_enabled("BSL227"):
            _rule_tasks.append(("BSL227", lambda: self._rule_bsl227_one_statement_per_line(path, lines, procs)))
        if self._rule_enabled("BSL258"):
            _rule_tasks.append(("BSL258", lambda: self._rule_bsl258_union_without_all(path, lines)))
        if self._rule_enabled("BSL183"):
            _rule_tasks.append(("BSL183", lambda: self._rule_bsl183_execute_external_code(path, lines)))
        if self._rule_enabled("BSL208") or self._rule_enabled("BSL256"):
            _rule_tasks.append(
                (
                    "BSL208_BSL256",
                    lambda: self._rule_bsl208_bsl256_latin_cyrillic_and_typo(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL230"):
            _rule_tasks.append(("BSL230", lambda: self._rule_bsl230_pairing_broken_transaction(path, lines, procs)))
        if self._rule_enabled("BSL240"):
            _rule_tasks.append(("BSL240", lambda: self._rule_bsl240_rewrite_method_parameter(path, lines, procs, tree, _proc_node_map)))
        if self._rule_enabled("BSL263"):
            _rule_tasks.append(("BSL263", lambda: self._rule_bsl263_useless_for_each(path, lines, procs)))
        if self._rule_enabled("BSL265"):
            _rule_tasks.append(("BSL265", lambda: self._rule_bsl265_useless_ternary_operator(path, lines)))
        if self._rule_enabled("BSL153"):
            _rule_tasks.append(("BSL153", lambda: self._rule_bsl153_canonical_spelling_keywords(path, lines)))
        if self._rule_enabled("BSL199"):
            _rule_tasks.append(("BSL199", lambda: self._rule_bsl199_if_else_if_ends_with_else(path, lines)))
        if self._rule_enabled("BSL216"):
            _rule_tasks.append(("BSL216", lambda: self._rule_bsl216_missing_space(path, lines)))
        if self._rule_enabled("BSL254"):
            _rule_tasks.append(("BSL254", lambda: self._rule_bsl254_transferring_parameters(path, lines, procs)))
        if self._rule_enabled("BSL255"):
            _rule_tasks.append(("BSL255", lambda: self._rule_bsl255_try_number(path, lines)))
        diagnostics = _execute_diagnostic_rule_tasks(_rule_tasks)
        # Apply inline suppressions
        diagnostics = [d for d in diagnostics if not _is_suppressed(d, suppressions)]
        _str_ranges = double_quoted_string_ranges(content)
        if _str_ranges:
            _line_starts = line_start_offsets(content)
            diagnostics = [
                d
                for d in diagnostics
                if d.code in _CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL
                or not diagnostic_overlaps_string_literal(
                    content,
                    line=d.line,
                    character=d.character,
                    end_line=d.end_line,
                    end_character=d.end_character,
                    ranges=_str_ranges,
                    line_starts=_line_starts,
                )
            ]
        return sorted(diagnostics, key=lambda d: (d.line, d.character))

    # ------------------------------------------------------------------
    # BSL001 — Parse errors
    # ------------------------------------------------------------------

    def _rule_bsl001_syntax_errors(self, path: str, tree: Any) -> list[Diagnostic]:
        errors = self._get_parser().extract_errors(tree)
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl004_from_tree(path, tree.root_node)
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
        empty_then_msg = (
            "Empty code block: 'Тогда' branch contains no statements — "
            "add logic or remove the branch."
        )
        for idx, line in enumerate(lines):
            if not _RE_THEN.search(line):
                continue
            if line.strip().startswith("//"):
                continue
            if not _regex_line_has_empty_then_branch(lines, idx):
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.WARNING,
                    code="BSL004",
                    message=empty_then_msg,
                )
            )
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        if _ts_tree_ok_for_rules(tree):
            return _diagnostics_bsl009_from_tree(path, tree.root_node)
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """
        Detect ``ВызватьИсключение "строка";`` — only a string literal after the keyword.

        Richer context: extended ``ВызватьИсключение`` syntax with optional category, code,
        additional info, and cause (platform 8.3.21+), or a non-literal expression.
        """
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl018_from_tree(path, tree.root_node)
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_RAISE_SIMPLE_STRING_ONLY.match(line):
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
                            "ВызватьИсключение used with only a string literal. "
                            "For structured error data, use the extended "
                            "ВызватьИсключение(...); syntax (8.3.21+) or build the text "
                            "in a variable/expression."
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
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag calls to Предупреждение()/Warning() — deprecated modal dialogs.

        These block execution and are not allowed in background procedures.
        Use ПоказатьПредупреждение() / ShowMessageBox() instead.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_DEPRECATED_MSG.match(line)
            if m:
                proc = _proc_containing_line(procs, idx)
                if proc is not None and _is_typical_client_command_handler(proc, lines):
                    continue
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
                            "Предупреждение()/Warning() is a modal dialog deprecated in managed UI. "
                            "Use ПоказатьПредупреждение() / ShowMessageBox() instead."
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
        Require a space after ``//`` in single-line comments (BSLLS ``SpaceAtStartComment``).

        Mirrors BSLLS strict-good pattern, ``//@`` / ``//(c)`` / ``//©`` annotations,
        skips commented-code lines (BSLLS ``CodeRecognizer``), ``//!``, ``//|``, noqa.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not bsl024_should_report_line(line):
                continue
            col = line.index("//")
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
    # BSL025 — EmptyStatement (BSLLS; отдельно от SemicolonPresence / BSL030)
    # ------------------------------------------------------------------

    def _rule_bsl025_empty_statement(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Placeholder: настоящий EmptyStatement в BSLLS — иной паттерн; не смешивать с BSL030."""
        return []

    # ------------------------------------------------------------------
    # BSL030 — SemicolonPresence: «;» в конце выражения (BSLLS) + лишняя «;» в заголовке
    # ------------------------------------------------------------------

    def _rule_bsl030_statement_missing_semicolon(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        BSLLS ``SemicolonPresence``: пропущена точка с запятой в конце выражения (код BSL030).

        Ранее дублировалось как BSL025 — для паритета с BSLLS JSON используем BSL030.
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
                # «)» может завершать вызов — после него нужна «;» (BSLLS SemicolonPresence).
                if last_char in (";", ",", "(", "|", "+", "-", "*", "/", "="):
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
                            code="BSL030",
                            message=(
                                "Пропущена точка с запятой в конце выражения"
                            ),
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
    _RE_TRY_CLOSE = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)

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
                elif self._RE_TRY_CLOSE.match(line) and in_try:
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
                # Skip multi-line string continuation lines (start with |)
                if stripped.startswith("|"):
                    continue
                # Skip constant-like declarations
                if re.match(r"^\s*(?:Перем|Var)\s+\w+\s*=", line, re.IGNORECASE):
                    continue
                # Remove string contents before scanning
                code_part = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
                code_part = _RE_SINGLE_QUOTED_STRING.sub("''", code_part)
                code_part = code_part.split("//")[0]
                # Skip Для/For loop headers — BSLLS does not flag loop bounds
                if _RE_BSL029_FOR_HEADER.match(code_part):
                    continue
                # Skip simple direct assignments Var = N — BSLLS skips these
                if _RE_BSL029_SIMPLE_ASSIGN.match(code_part):
                    continue
                # Remove ternary operator args — BSLLS does not flag simple numeric
                # values in ?(cond, N, M) because they are not in CallParamContext
                code_part = _RE_BSL029_TERNARY.sub("?('',0,0)", code_part)
                # Remove Structure.Вставить("key", value) second param — BSLLS skips
                # these when it can confirm the variable is a Структура
                code_part = _RE_BSL029_STRUCT_INSERT.sub('.Вставить("",0)', code_part)
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
        self, path: str, lines: list[str], procs: list[_ProcInfo], tree: Any
    ) -> list[Diagnostic]:
        """
        Detect ``.Выполнить()`` / ``.Execute()`` calls inside loops.

        Executing queries inside loops is a critical performance anti-pattern
        in 1C Enterprise — it causes N database round-trips per iteration.
        """
        diags: list[Diagnostic] = []
        loop_lines: set[int] | None = None
        if _ts_tree_ok_for_rules(tree):
            loop_lines = loop_body_line_indices_0(tree.root_node)
        for proc in procs:
            loop_depth = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if loop_lines is not None:
                    if i not in loop_lines:
                        continue
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
                    continue
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
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag string literals that appear *min_duplicate_uses* or more times **within
        the same scope** (one procedure/function body, or module-level code).

        Counting separately per method avoids false positives when the same key
        literals (e.g. ``Вставить("СерийныйНомер", ...)``) appear in different
        functions.

        BSLLS ``DuplicateStringLiteral``: одна диагностика на литерал при достижении порога,
        с привязкой к *первой* позиции вхождения (relatedInformation в BSLLS — остальные строки).

        Ignores short/trivial strings (less than 4 chars after stripping).
        """
        from collections import Counter

        diags: list[Diagnostic] = []
        for scope_lines in _bsl035_scope_line_indices(lines, procs):
            counts: Counter[str] = Counter()
            positions: dict[str, list[tuple[int, int]]] = {}

            for idx in scope_lines:
                line = lines[idx]
                if line.strip().startswith("//"):
                    continue
                for m in _RE_STRING_LITERAL.finditer(line):
                    val = m.group(1).strip()
                    if not val:
                        continue
                    counts[val] += 1
                    positions.setdefault(val, []).append((idx + 1, m.start()))

            for val, count in counts.items():
                if count >= self.min_duplicate_uses:
                    pos_list = positions[val]
                    # Same user-facing error text repeated only on raise lines — low value to dedupe
                    if all(_line_starts_with_raise_statement(lines[ln - 1]) for ln, _ in pos_list):
                        continue
                    # BSLLS: одна диагностика на первом вхождении литерала в области видимости
                    line_no, col = pos_list[0]
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

    _RE_IF_OR_ELSEIF_LINE = re.compile(
        r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b", re.IGNORECASE
    )
    _RE_THEN_WORD = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)

    def _bsl036_if_condition_chunk(self, lines: list[str], idx: int) -> str | None:
        """
        Text of ``Если``/``ИначеЕсли`` condition through ``Тогда`` (BSLLS counts whole condition).

        Returns None if *idx* is not the first line of an If/ElseIf condition.
        """
        line = lines[idx]
        if line.strip().startswith("//"):
            return None
        if not self._RE_IF_OR_ELSEIF_LINE.match(line):
            return None
        if self._RE_THEN_WORD.search(line):
            return line
        parts = [line]
        j = idx + 1
        max_j = min(len(lines), idx + 48)
        while j < max_j:
            parts.append(lines[j])
            if self._RE_THEN_WORD.search(lines[j]):
                break
            j += 1
        return "\n".join(parts)

    def _line_triggers_bsl036(self, lines: list[str], idx: int) -> bool:
        """True when line *idx* starts a condition that exceeds *max_bool_ops* (BSLLS IfConditionComplexity)."""
        chunk = self._bsl036_if_condition_chunk(lines, idx)
        if chunk is None:
            return False
        return len(_RE_BOOL_OP.findall(chunk)) > self.max_bool_ops

    def _line_in_triggered_bsl036_condition(self, lines: list[str], idx: int) -> bool:
        """
        True if line *idx* belongs to an If/ElseIf..Тогда block whose **first** line
        triggers BSL036 — suppress BSL153 on continuation lines (BSLLS: IfConditionComplexity).
        """
        if not self._rule_enabled("BSL036"):
            return False
        for start in range(max(0, idx - 48), idx + 1):
            if self._bsl036_if_condition_chunk(lines, start) is None:
                continue
            if not self._line_triggers_bsl036(lines, start):
                continue
            j = start
            while j < len(lines):
                if self._RE_THEN_WORD.search(lines[j]):
                    return start <= idx <= j
                j += 1
        return False

    def _rule_bsl036_complex_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag Если/If lines with more boolean operators than *max_bool_ops*.

        A condition like ``А И Б ИЛИ В И Г`` is hard to read and should
        be refactored into named boolean variables or helper functions.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not self._line_triggers_bsl036(lines, idx):
                continue
            chunk = self._bsl036_if_condition_chunk(lines, idx) or line
            ops = len(_RE_BOOL_OP.findall(chunk))
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
        self, path: str, lines: list[str], procs: list[_ProcInfo], tree: Any
    ) -> list[Diagnostic]:
        """
        Flag ``Переменная = Переменная + "..."`` inside a loop.

        Building a string in a loop via ``+`` is O(n²). Use a Массив + СтрСоединить
        or СтрШаблон pattern instead.
        """
        diags: list[Diagnostic] = []
        loop_lines: set[int] | None = None
        if _ts_tree_ok_for_rules(tree):
            loop_lines = loop_body_line_indices_0(tree.root_node)
        for proc in procs:
            loop_depth = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if loop_lines is not None:
                    if i not in loop_lines or line.strip().startswith("//"):
                        continue
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
                    continue
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
        # Skip form modules (EDT ``.../Forms/.../Ext/Module.bsl``, ``*форма*``, ``*Form``).
        if path_is_likely_form_module_bsl(path):
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
        self, path: str, lines: list[str], procs: list[_ProcInfo]
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
                proc = _proc_containing_line(procs, idx)
                if proc is not None and _is_typical_client_command_handler(proc, lines):
                    continue
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
                    # BSLLS uses IfElseIfEndsWithElse (BSL199) on the closing line; avoid duplicate.
                    if not self._rule_enabled("BSL199"):
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
        Flag ВызватьИсключение/Raise at the *procedure body base* indent, outside any
        Попытка...Исключение block. Nested blocks (Если/Пока/…) use deeper indent and
        are skipped — the raise is only reached when that control flow runs.
        """
        diags: list[Diagnostic] = []
        _re_try_open = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_try_close = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)

        for proc in procs:
            body_lines = lines[proc.start_idx : proc.end_idx + 1]
            base_indent = _proc_body_base_indent(lines, proc)
            try_depth = 0
            for rel_idx, line in enumerate(body_lines):
                if _re_try_open.match(line):
                    try_depth += 1
                elif _re_try_close.match(line):
                    try_depth = max(0, try_depth - 1)
                elif try_depth == 0 and _RE_RAISE.match(line):
                    raise_indent = len(line) - len(line.lstrip())
                    if base_indent and raise_indent > base_indent:
                        continue
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
                                "ВызватьИсключение/Raise at method body level (outside "
                                "Попытка/Try) always terminates the call — add a guard "
                                "or move into a conditional/nested block."
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
        self, path: str, lines: list[str], procs: list[_ProcInfo], tree: Any
    ) -> list[Diagnostic]:
        """
        Flag code that follows an unconditional Возврат/Return or
        ВызватьИсключение/Raise within the same scope block.

        Block boundaries (КонецЕсли, КонецПопытки, Исключение, …) are taken from
        the tree-sitter CST keyword nodes when the parse is clean; otherwise
        the same tokens are matched with a regex fallback (``_RegexTree`` / ERROR).
        """
        diags: list[Diagnostic] = []
        delimiter_lines = _bsl051_delimiter_lines_for_tree(tree)

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
                            if delimiter_lines is not None:
                                is_block_delimiter = next_abs in delimiter_lines
                            else:
                                is_block_delimiter = bool(
                                    _RE_BSL051_DELIMITER_FALLBACK.match(next_line)
                                )
                            if not is_block_delimiter:
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Flag Если Истина/Ложь Тогда — condition is never evaluated."""
        root = getattr(tree, "root_node", None)
        tree_is_ts = root is not None and isinstance(
            getattr(root, "text", None), (bytes, bytearray)
        )
        if tree_is_ts and root is not None and not tree_has_errors(root):
            pairs: list[tuple[int, str]] = []
            _bsl052_collect_literal_if_nodes(root, pairs)
            diags: list[Diagnostic] = []
            for line_idx, literal in pairs:
                if line_idx >= len(lines):
                    continue
                line = lines[line_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=line_idx + 1,
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

        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_IF_LITERAL.match(line)
            if m:
                # Get the literal value
                literal_m = re.search(
                    r"\b(Истина|True|Ложь|False)\b", line, re.IGNORECASE
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
        Flag exported Перем/Var declarations at module level (BSLLS ExportVariables).

        Only flags ``Перем Name Экспорт;`` — exported module-level state that leaks
        outside the module.  Non-exported module variables are intentional and not
        flagged (matches BSLLS ExportVariables default behaviour).
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
            m = _RE_VAR_MODULE_EXPORT.match(line)
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
                            f"Exported module-level variable '{', '.join(names)}' — "
                            "module-level export state is not recommended (BSLLS ExportVariables)."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL219 — MissingVariablesDescription (exported module Перем)
    # ------------------------------------------------------------------

    def _rule_bsl219_missing_variables_description(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag module-level ``Перем … Экспорт`` without a preceding ``//`` / ``///`` description line.

        Aligns with BSLLS ``MissingVariablesDescription`` (often together with BSL054 on the same line).
        """
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)

        for idx, line in enumerate(lines):
            if idx in inside:
                continue
            code_part = line.split("//", 1)[0].rstrip()
            if not code_part.strip():
                continue
            m = _RE_VAR_MODULE_EXPORT.match(code_part)
            if not m:
                continue
            if _module_export_var_has_preceding_description(lines, idx):
                continue
            names = [n.strip() for n in m.group("names").split(",") if n.strip()]
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
                    code="BSL219",
                    message=(
                        "Add a description comment on the line before this exported module variable "
                        f"('{', '.join(names)}')."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL055 — Consecutive blank lines (> 2)
    # ------------------------------------------------------------------

    # BSLLS ConsecutiveEmptyLines: flag when more than one blank line in a row.
    MAX_BLANK_LINES: int = 1

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
        # BSLLS: лишняя пустая строка в самом конце модуля (после КонецПроцедуры / #КонецОбласти и т.п.).
        if len(lines) >= 2 and lines[-1].strip() == "" and lines[-2].strip() != "":
            diags.append(
                Diagnostic(
                    file=path,
                    line=len(lines),
                    character=0,
                    end_line=len(lines),
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL055",
                    message=(
                        "Лишняя пустая строка в конце модуля — удалите последовательные пустые строки."
                    ),
                )
            )
        return diags


    # ------------------------------------------------------------------
    # BSL059 — Boolean literal comparison
    # ------------------------------------------------------------------

    def _rule_bsl059_bool_literal_comparison(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Flag А = Истина / А = Ложь — use the boolean expression directly."""
        if _ts_tree_ok_for_rules(tree):
            return _diagnostics_bsl059_from_tree(path, tree.root_node)
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            m = _RE_BOOL_LITERAL_CMP.search(line)
            if not m:
                continue
            if _regex_line_has_empty_then_branch(lines, idx):
                continue
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
                        "In If/ElseIf condition: comparison to boolean literal — "
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Flag НЕ НЕ / Not Not — double negation always cancels out."""
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl060_from_tree(path, tree.root_node)
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
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """
        Flag Прервать/Break as the very last non-blank statement before КонецЦикла.
        The loop could be rewritten with a proper loop condition instead.
        """
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl061_from_tree(path, tree.root_node)
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
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        tree: Any,
        proc_node_map: dict[tuple[str, int, str], Any] | None = None,
    ) -> list[Diagnostic]:
        """
        Flag method parameters that are never referenced in the method body.

        Parameter names come from ``proc.params`` (tree-sitter when available). Whether a
        name is used is determined by walking the procedure body CST and collecting
        ``identifier`` nodes (excluding the ``parameters`` subtree). When tree-sitter is
        unavailable (_RegexTree), falls back to a word-boundary scan of the body text.

        Excludes parameters that start with '_' (convention for intentionally unused).
        """
        # BSLLS does not run UnusedParameters on form modules — form event handlers
        # always have platform-defined signatures that may not use all parameters.
        if path_is_likely_form_module_bsl(path):
            return []
        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        tree_is_ts = root is not None and isinstance(
            getattr(root, "text", None), (bytes, bytearray)
        )

        for proc in procs:
            if not proc.params:
                continue
            # BSLLS skips exported procedures: their signature is public API and
            # callers may pass arguments that the current implementation ignores.
            if proc.is_export:
                continue
            header_line = lines[proc.start_idx]
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            body_text = "\n".join(body_lines)
            header_lineno = proc.start_idx + 1  # 1-based

            used_casefold: set[str] | None = None
            if tree_is_ts:
                key = (proc.name, proc.start_idx, proc.kind)
                proc_node = (
                    proc_node_map.get(key)
                    if proc_node_map is not None
                    else _find_proc_definition_node(tree, proc)
                )
                if proc_node is not None:
                    used_casefold = _collect_identifier_casefolds_in_proc_body(proc_node)

            for param_name in proc.params:
                if not param_name:
                    continue
                if param_name.startswith("_"):
                    continue
                if not param_name.isidentifier():
                    continue
                if param_name.casefold() in _BSL062_SKIP_STANDARD_COMMAND_PARAMS:
                    continue
                # BSLLS does not flag optional parameters (have default values) as unused:
                # they are part of the public API signature even when not used in the body.
                if param_name in proc.optional_params:
                    continue
                if param_name.casefold() in ("параметры", "parameters") and (
                    _is_typical_client_command_handler(proc, lines)
                    or _is_client_notify_completion_export_handler(proc, lines)
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
                        file=path,
                        line=header_lineno,
                        character=proc.header_col,
                        end_line=header_lineno,
                        end_character=len(header_line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL062",
                        message=(
                            f"Parameter '{param_name}' is never used in the method body."
                        ),
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

    # ------------------------------------------------------------------
    # BSL065 — Missing export comment
    # ------------------------------------------------------------------

    def _rule_bsl065_missing_export_comment(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag exported methods that have no preceding description comment.

        The line before the declaration (skipping blanks and ``&НаКлиенте``-style
        compiler lines) must be a ``//`` or ``///`` comment.
        """
        # BSLLS: form modules use a different documentation profile; parity with
        # analyze on ``.../Forms/.../Ext/Module.bsl`` — skip (see BSL040).
        if path_is_likely_form_module_bsl(path):
            return []

        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export:
                continue
            if _is_client_notify_completion_export_handler(proc, lines):
                continue
            header_idx = proc.start_idx
            header_line = lines[header_idx]
            anchor = _export_description_anchor_line_idx(lines, header_idx)
            if anchor is None or not _RE_COMMENT_LINE.match(lines[anchor]):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=header_idx + 1,
                        character=0,
                        end_line=header_idx + 1,
                        end_character=len(header_line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL065",
                        message=(
                            f"Exported method '{proc.name}' has no preceding description comment."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL066 — Deprecated platform method call
    # ------------------------------------------------------------------

    def _rule_bsl066_deprecated_platform_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag calls to deprecated Найти() — use СтрНайти() instead (BSLLS DeprecatedFind)."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_COMMENT_LINE.match(line):
                continue
            m = _RE_DEPRECATED_METHOD.search(line)
            if m:
                method_name = m.group(0).rstrip("(").strip()
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL066",
                        message=(
                            f"'{method_name}' is deprecated — use СтрНайти() / StrFind() instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL067 — Перем declaration after executable code
    # ------------------------------------------------------------------

    def _rule_bsl067_var_after_code(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag Перем declarations that appear after any executable statement
        in the same method body. Declarations should be at the top.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            body_start = proc.start_idx + 1
            body_end = proc.end_idx
            found_executable = False
            for idx in range(body_start, min(body_end, len(lines))):
                line = lines[idx]
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if _RE_VAR_DECL.match(line):
                    if found_executable:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=len(line) - len(line.lstrip()),
                                end_line=idx + 1,
                                end_character=len(line.rstrip()),
                                severity=Severity.WARNING,
                                code="BSL067",
                                message=(
                                    "Перем/Var declaration appears after executable code — "
                                    "move declarations to the start of the method."
                                ),
                            )
                        )
                else:
                    found_executable = True
        return diags

    # ------------------------------------------------------------------
    # BSL068 — Too many ИначеЕсли / ElsIf branches
    # ------------------------------------------------------------------

    MAX_ELSEIF_BRANCHES: int = 5

    def _rule_bsl068_too_many_elseif(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag Если/If blocks that contain more than MAX_ELSEIF_BRANCHES ИначеЕсли branches.
        Long chains are hard to read and maintain — use a map or polymorphism.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_IF_OPEN.match(lines[i]):
                if_start = i
                depth = 1
                elseif_count = 0
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_IF_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_ENDIF.match(lines[j]):
                        depth -= 1
                    elif depth == 1 and _RE_ELSEIF.match(lines[j]):
                        elseif_count += 1
                    j += 1
                if elseif_count > self.MAX_ELSEIF_BRANCHES:
                    header = lines[if_start]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=if_start + 1,
                            character=len(header) - len(header.lstrip()),
                            end_line=if_start + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL068",
                            message=(
                                f"Если/If has {elseif_count} ИначеЕсли/ElsIf branches "
                                f"(max {self.MAX_ELSEIF_BRANCHES}). "
                                "Consider using a map, dispatch table, or polymorphism."
                            ),
                        )
                    )
                i = j
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL069 — Infinite loop (Пока Истина Цикл without Прервать)
    # ------------------------------------------------------------------

    def _rule_bsl069_infinite_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag 'Пока Истина Цикл' / 'While True Do' bodies that contain no
        Прервать/Break statement — this is almost certainly an infinite loop.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_WHILE_TRUE.match(lines[i]):
                loop_start = i
                depth = 1
                has_break = False
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1 and _RE_BREAK.match(lines[j]):
                        has_break = True
                    j += 1
                if not has_break:
                    header = lines[loop_start]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=loop_start + 1,
                            character=len(header) - len(header.lstrip()),
                            end_line=loop_start + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL069",
                            message=(
                                "Пока Истина Цикл/While True Do without Прервать/Break — "
                                "potential infinite loop. Add an exit condition."
                            ),
                        )
                    )
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL070 — Empty loop body
    # ------------------------------------------------------------------

    def _rule_bsl070_empty_loop_body(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """
        Flag loops whose body contains no executable statements.
        Only blank lines and comments between the loop header and КонецЦикла.
        """
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl070_from_tree(path, tree.root_node)
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                loop_start = i
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                # Check if loop body (lines between loop header and КонецЦикла) is empty
                body_lines = lines[loop_start + 1: j]
                has_executable = any(
                    ln.strip() and not ln.strip().startswith("//")
                    for ln in body_lines
                )
                if not has_executable:
                    header = lines[loop_start]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=loop_start + 1,
                            character=len(header) - len(header.lstrip()),
                            end_line=loop_start + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL070",
                            message=(
                                "Loop body contains no executable statements. "
                                "Add a comment explaining intent or remove the loop."
                            ),
                        )
                    )
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL071 — Magic number literal
    # ------------------------------------------------------------------

    # Numbers always allowed (too common/obvious to flag)
    _MAGIC_NUMBER_ALLOWED: frozenset[str] = frozenset({"0", "1", "2", "-1", "100"})

    def _rule_bsl071_magic_number(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag numeric literals (other than 0, 1, 2, 100, -1) used directly
        inside method bodies. Constants and module-level assignments are excluded.
        """
        if not procs:
            return []
        # Build a set of line ranges that are inside procedure/function bodies
        body_ranges: list[tuple[int, int]] = [
            (proc.start_idx + 1, proc.end_idx) for proc in procs
        ]
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            # Only flag inside method bodies
            if not any(start <= idx < end for start, end in body_ranges):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            # Skip constant declarations: Конст Х = 100;
            if re.match(r'^\s*(?:Конст|Const)\b', line, re.IGNORECASE):
                continue
            for m in _RE_MAGIC_NUMBER.finditer(line):
                num = m.group(0).strip()
                if num in self._MAGIC_NUMBER_ALLOWED:
                    continue
                col = m.start()
                # Skip if it looks like part of a method name or string position
                pre = line[:col]
                if pre.rstrip().endswith('"') or pre.rstrip().endswith("'"):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=col + len(num),
                        severity=Severity.INFORMATION,
                        code="BSL071",
                        message=(
                            f"Magic number '{num}' — extract to a named constant "
                            "for better readability and maintainability."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL072 — String concatenation inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl072_string_concat_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag lines inside a loop body that concatenate a variable with a string literal
        using '+'. This is an O(n²) operation — collect into an array and join instead.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        stripped = lines[j].strip()
                        if stripped and not stripped.startswith("//"):
                            if _RE_STR_CONCAT.search(lines[j]):
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=j + 1,
                                        character=len(lines[j]) - len(lines[j].lstrip()),
                                        end_line=j + 1,
                                        end_character=len(lines[j].rstrip()),
                                        severity=Severity.WARNING,
                                        code="BSL072",
                                        message=(
                                            "String concatenation with '+' inside a loop "
                                            "is O(n²). Use an array and СтрСоединить()."
                                        ),
                                    )
                                )
                    j += 1
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL073 — Если/If without Иначе/Else
    # ------------------------------------------------------------------

    MAX_IF_DEPTH_FOR_ELSE_CHECK: int = 1  # only top-level if-blocks

    def _rule_bsl073_missing_else_branch(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag top-level Если/If blocks that have at least one ИначеЕсли but no Иначе/Else.
        Pure 'Если ... Тогда ... КонецЕсли' without any ИначеЕсли are not flagged.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_IF_OPEN.match(lines[i]):
                if_start = i
                depth = 1
                has_elseif = False
                has_else = False
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_IF_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_ENDIF.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        if _RE_ELSEIF.match(lines[j]):
                            has_elseif = True
                        elif _RE_ELSE.match(lines[j]):
                            has_else = True
                    j += 1
                if has_elseif and not has_else:
                    header = lines[if_start]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=if_start + 1,
                            character=len(header) - len(header.lstrip()),
                            end_line=if_start + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL073",
                            message=(
                                "Если/If with ИначеЕсли/ElsIf branches but no Иначе/Else — "
                                "add a default Иначе branch for unexpected values."
                            ),
                        )
                    )
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL074 — TODO/FIXME/HACK comment
    # ------------------------------------------------------------------

    def _rule_bsl074_todo_comment(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag TODO, FIXME, HACK, XXX markers in comments as technical debt."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            m = _RE_TODO_COMMENT.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL074",
                        message=(
                            f"Technical debt marker '{m.group().strip()}' found — "
                            "resolve the issue or track it in an issue tracker."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL075 — Method modifies module-level variable
    # ------------------------------------------------------------------

    def _rule_bsl075_global_variable_modification(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag assignments inside a method body to variables that appear to be
        module-level (i.e., declared outside any method via Перем at module level).
        """
        if not procs:
            return []
        # Collect module-level Перем declarations
        first_proc_start = min(p.start_idx for p in procs)
        module_vars: set[str] = set()
        for idx in range(first_proc_start):
            m = _RE_VAR_DECL.match(lines[idx])
            if m:
                # Extract variable names: Перем А, Б, В;
                rest = lines[idx][m.end():].rstrip().rstrip(";")
                for name in re.split(r'\s*,\s*', rest):
                    name = name.strip()
                    if name:
                        module_vars.add(name.lower())

        if not module_vars:
            return []

        # Assignment pattern: variable = ...
        _RE_ASSIGN = re.compile(r'^\s*(\w+)\s*=(?!=)', re.IGNORECASE)
        diags: list[Diagnostic] = []
        for proc in procs:
            # Collect local Перем declarations within this method
            body_start = proc.start_idx + 1
            local_vars: set[str] = set()
            for idx in range(body_start, min(proc.end_idx, len(lines))):
                lm = _RE_VAR_DECL.match(lines[idx])
                if lm:
                    rest = lines[idx][lm.end():].rstrip().rstrip(";")
                    for nm in re.split(r'\s*,\s*', rest):
                        nm = nm.strip()
                        if nm:
                            local_vars.add(nm.lower())

            # Also treat parameters as local
            param_vars: set[str] = {p.lower() for p in proc.params}

            for idx in range(body_start, min(proc.end_idx, len(lines))):
                am = _RE_ASSIGN.match(lines[idx])
                if am:
                    var_name = am.group(1).lower()
                    if var_name in module_vars and var_name not in local_vars and var_name not in param_vars:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=len(lines[idx]) - len(lines[idx].lstrip()),
                                end_line=idx + 1,
                                end_character=am.end(),
                                severity=Severity.INFORMATION,
                                code="BSL075",
                                message=(
                                    f"Method modifies module-level variable '{am.group(1)}' — "
                                    "prefer passing it as a parameter or returning it."
                                ),
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL076 — Negative condition first
    # ------------------------------------------------------------------

    def _rule_bsl076_negative_condition_first(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Если/ИначеЕсли conditions that start with НЕ/Not."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_NEGATIVE_CONDITION.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL076",
                        message=(
                            "Condition starts with НЕ/Not — consider rewriting "
                            "as a positive condition for better readability."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL077 — SELECT * in query
    # ------------------------------------------------------------------

    def _rule_bsl077_select_star(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag ВЫБРАТЬ */SELECT * in query text strings."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            m = _RE_SELECT_STAR.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL077",
                        message=(
                            "ВЫБРАТЬ */SELECT * retrieves all columns — "
                            "list columns explicitly for better performance and maintainability."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL078 — ВызватьИсключение without a message
    # ------------------------------------------------------------------

    def _rule_bsl078_raise_without_message(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag bare ВызватьИсключение; / Raise; with no message argument."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_RAISE_BARE.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL078",
                        message=(
                            "ВызватьИсключение/Raise without a message — "
                            "provide context so callers can diagnose the error."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL079 — Goto statement
    # ------------------------------------------------------------------

    def _rule_bsl079_using_goto(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Перейти/Goto statements as unstructured control flow."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_GOTO.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL079",
                        message=(
                            "Перейти/Goto creates unstructured control flow — "
                            "replace with loops, conditions, or procedure calls."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL080 — Silent catch (exception handler ignores the error)
    # ------------------------------------------------------------------

    def _rule_bsl080_silent_catch(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag Исключение/Except blocks that contain no ИнформацияОбОшибке() call
        and no ВызватьИсключение/Raise — the error is silently swallowed.
        """
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_TRY_OPEN.match(lines[i]):
                # Find Исключение/Except block for this Попытка
                depth = 1
                j = i + 1
                except_start = None
                while j < len(lines) and depth > 0:
                    if _RE_TRY_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_END_TRY.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1 and _RE_EXCEPT_BLOCK.match(lines[j]):
                        except_start = j
                    j += 1
                if except_start is not None:
                    # Scan the exception body for ИнформацияОбОшибке or ВызватьИсключение
                    has_handling = False
                    for k in range(except_start + 1, j):
                        ln = lines[k]
                        if _RE_ERROR_INFO.search(ln) or _RE_RAISE.match(ln):
                            has_handling = True
                            break
                    if not has_handling:
                        header = lines[except_start]
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=except_start + 1,
                                character=len(header) - len(header.lstrip()),
                                end_line=except_start + 1,
                                end_character=len(header.rstrip()),
                                severity=Severity.WARNING,
                                code="BSL080",
                                message=(
                                    "Exception handler silently ignores the error — "
                                    "call ИнформацияОбОшибке() or re-raise with ВызватьИсключение."
                                ),
                            )
                        )
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL081 — Long method chain
    # ------------------------------------------------------------------

    MAX_METHOD_CHAIN_DEPTH: int = 5

    def _rule_bsl081_long_method_chain(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """
        Flag lines where a method call chain exceeds MAX_METHOD_CHAIN_DEPTH
        chained calls (e.g. A.B().C().D().E().F() has 5 calls).
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            # Count chained method calls: pattern .MethodName(
            chain_depth = len(_RE_DOT_CHAIN.findall(line))
            if chain_depth > self.MAX_METHOD_CHAIN_DEPTH:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL081",
                        message=(
                            f"Method call chain has {chain_depth} chained calls "
                            f"(max {self.MAX_METHOD_CHAIN_DEPTH}). "
                            "Split into intermediate variables."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL082 — Missing newline at end of file
    # ------------------------------------------------------------------

    def _rule_bsl082_missing_newline_at_eof(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag files that do not end with a newline character."""
        if not lines:
            return []
        # lines come from content.splitlines() — no trailing \n on each line.
        # Read the raw bytes to check the actual last byte.
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return []
        if raw and not raw.endswith((b"\n", b"\r")):
            last = lines[-1]
            return [
                Diagnostic(
                    file=path,
                    line=len(lines),
                    character=len(last),
                    end_line=len(lines),
                    end_character=len(last),
                    severity=Severity.INFORMATION,
                    code="BSL082",
                    message="File does not end with a newline. Add a trailing newline.",
                )
            ]
        return []

    # ------------------------------------------------------------------
    # BSL083 — Too many module-level variables
    # ------------------------------------------------------------------

    MAX_MODULE_VARIABLES: int = 10

    def _rule_bsl083_too_many_module_variables(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag modules with more than MAX_MODULE_VARIABLES Перем declarations
        at the module level (outside any method).
        """
        first_proc = min((p.start_idx for p in procs), default=len(lines))
        module_var_count = 0
        for idx in range(first_proc):
            if _RE_VAR_DECL.match(lines[idx]):
                # Count comma-separated names on this line
                rest = lines[idx][_RE_VAR_DECL.match(lines[idx]).end():].rstrip().rstrip(";")
                count = len([n for n in re.split(r'\s*,\s*', rest) if n.strip()])
                module_var_count += max(count, 1)
        if module_var_count > self.MAX_MODULE_VARIABLES:
            return [
                Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL083",
                    message=(
                        f"Module has {module_var_count} module-level variables "
                        f"(max {self.MAX_MODULE_VARIABLES}). "
                        "Consider encapsulating state in a structure or configuration object."
                    ),
                )
            ]
        return []

    # ------------------------------------------------------------------
    # BSL084 — Функция with no Возврат value
    # ------------------------------------------------------------------

    def _rule_bsl084_function_with_no_return(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag Функция/Function declarations where the body contains no
        'Возврат <value>' statement — such functions always return Неопределено
        and should be declared as Процедура.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            body_lines = lines[proc.start_idx + 1: proc.end_idx]
            has_return_value = any(
                _RE_RETURN_VALUE.match(ln) for ln in body_lines
            )
            if not has_return_value:
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL084",
                        message=(
                            f"Функция '{proc.name}' never returns a value — "
                            "change to Процедура or add a Возврат statement."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL085 — Literal boolean condition
    # ------------------------------------------------------------------

    def _rule_bsl085_literal_boolean_condition(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Flag Если Истина/Ложь Тогда — conditions that are always true or false."""
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl085_from_tree(path, tree.root_node, lines)
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_LITERAL_BOOL_CONDITION.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL085",
                        message=(
                            "Condition is a literal boolean — the branch always or never executes. "
                            "Remove the dead code or fix the condition."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL086 — HTTP request in a loop
    # ------------------------------------------------------------------

    def _rule_bsl086_http_request_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag HTTP-related calls inside a loop body."""
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        m = _RE_HTTP_REQUEST.search(lines[j])
                        if m:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=m.start(),
                                    end_line=j + 1,
                                    end_character=m.end(),
                                    severity=Severity.WARNING,
                                    code="BSL086",
                                    message=(
                                        f"HTTP call '{m.group()}' inside a loop — "
                                        "batch requests or move outside the loop."
                                    ),
                                )
                            )
                    j += 1
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL087 — Новый/New object creation in a loop
    # ------------------------------------------------------------------

    # Objects that are cheap/intentional to create per-iteration
    _ALLOWED_NEW_IN_LOOP: frozenset[str] = frozenset({
        "структура", "соответствие", "массив", "список",
        "structure", "map", "array", "list",
    })

    def _rule_bsl087_object_creation_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Новый/New object creation inside a loop body (potential performance issue)."""
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        m = _RE_NEW_OBJECT.search(lines[j])
                        if m:
                            # Check the object type after Новый
                            after = lines[j][m.end():].strip()
                            obj_type = re.match(r'(\w+)', after)
                            if obj_type and obj_type.group(1).lower() in self._ALLOWED_NEW_IN_LOOP:
                                j += 1
                                continue
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=m.start(),
                                    end_line=j + 1,
                                    end_character=m.end(),
                                    severity=Severity.INFORMATION,
                                    code="BSL087",
                                    message=(
                                        "Object creation with Новый/New inside a loop — "
                                        "consider moving it outside if the object can be reused."
                                    ),
                                )
                            )
                    j += 1
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL088 — Export method with parameters but no // Parameters: comment
    # ------------------------------------------------------------------

    def _rule_bsl088_missing_parameter_comment(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag Export methods that have parameters but lack a // Parameters: or
        // Параметры: comment section in the lines before the method header.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export or not proc.params:
                continue
            # Scan up to 10 lines before the header for a Parameters comment
            start = max(0, proc.start_idx - 10)
            comment_block = lines[start: proc.start_idx]
            has_param_comment = any(_RE_PARAM_COMMENT.search(ln) for ln in comment_block)
            if not has_param_comment:
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL088",
                        message=(
                            f"Export method '{proc.name}' has {len(proc.params)} parameter(s) "
                            "but no // Parameters: / // Параметры: comment section."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL089 — Transaction begun inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl089_transaction_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag НачатьТранзакцию/BeginTransaction calls inside a loop body."""
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_LOOP_OPEN.match(lines[i]):
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_LOOP_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_LOOP_CLOSE.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        m = _RE_BEGIN_TRANSACTION.search(lines[j])
                        if m:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=m.start(),
                                    end_line=j + 1,
                                    end_character=m.end(),
                                    severity=Severity.WARNING,
                                    code="BSL089",
                                    message=(
                                        "НачатьТранзакцию/BeginTransaction inside a loop — "
                                        "move the transaction outside to avoid N nested transactions."
                                    ),
                                )
                            )
                    j += 1
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL090 — Hardcoded connection string
    # ------------------------------------------------------------------

    def _rule_bsl090_hardcoded_connection_string(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag possible hardcoded database connection strings in string literals."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not line.strip() or line.strip().startswith("//"):
                continue
            # Only flag inside string literals (rough: line contains quotes)
            if '"' not in line:
                continue
            m = _RE_CONNECTION_STRING.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL090",
                        message=(
                            f"Possible hardcoded connection string parameter '{m.group().strip()}' — "
                            "move to environment variables or configuration."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL091 — Redundant Else after Return
    # ------------------------------------------------------------------

    def _rule_bsl091_redundant_else_after_return(
        self, path: str, lines: list[str], procs: list[_ProcInfo], tree: Any
    ) -> list[Diagnostic]:
        """
        Flag Иначе/Else blocks that immediately follow a Возврат/Return in the preceding
        Если/Then block — the Иначе is redundant since the Return already exits.
        """
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl091_from_tree(path, tree.root_node)
        if not procs:
            return []
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_IF_OPEN.match(lines[i]):
                depth = 1
                last_return_before_else: int | None = None
                j = i + 1
                while j < len(lines) and depth > 0:
                    if _RE_IF_OPEN.match(lines[j]):
                        depth += 1
                    elif _RE_ENDIF.match(lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1:
                        if _RE_RETURN_STMT.match(lines[j]):
                            last_return_before_else = j
                        elif (_RE_ELSE.match(lines[j]) or _RE_ELSEIF.match(lines[j])):
                            if last_return_before_else is not None:
                                # Else/ElseIf after a Return — redundant
                                if _RE_ELSE.match(lines[j]):
                                    diags.append(
                                        Diagnostic(
                                            file=path,
                                            line=j + 1,
                                            character=len(lines[j]) - len(lines[j].lstrip()),
                                            end_line=j + 1,
                                            end_character=len(lines[j].rstrip()),
                                            severity=Severity.INFORMATION,
                                            code="BSL091",
                                            message=(
                                                "Иначе/Else after Возврат/Return is redundant — "
                                                "remove Иначе and dedent the block."
                                            ),
                                        )
                                    )
                            last_return_before_else = None
                        else:
                            # Non-return, non-branch statement resets
                            stripped = lines[j].strip()
                            if stripped and not stripped.startswith("//"):
                                last_return_before_else = None
                    j += 1
                i = j + 1
                continue
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL092 — Empty Иначе block
    # ------------------------------------------------------------------

    def _rule_bsl092_empty_else_block(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Flag Иначе/Else blocks that contain no executable statements."""
        if _ts_tree_ok_for_rules(tree):
            return diagnostics_bsl092_from_tree(path, tree.root_node)
        diags: list[Diagnostic] = []
        i = 0
        while i < len(lines):
            if _RE_ELSE.match(lines[i]):
                else_idx = i
                # Scan until КонецЕсли or another ИначеЕсли
                j = i + 1
                has_executable = False
                while j < len(lines):
                    if _RE_ENDIF.match(lines[j]) or _RE_ELSEIF.match(lines[j]):
                        break
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith("//"):
                        has_executable = True
                        break
                    j += 1
                if not has_executable:
                    header = lines[else_idx]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=else_idx + 1,
                            character=len(header) - len(header.lstrip()),
                            end_line=else_idx + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL092",
                            message=(
                                "Empty Иначе/Else block — remove it or add a comment "
                                "explaining why it is intentionally empty."
                            ),
                        )
                    )
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL093 — Comparison to NULL
    # ------------------------------------------------------------------

    def _rule_bsl093_comparison_to_null(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag comparisons to SQL NULL — use Неопределено or ЗначениеЗаполнено()."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_NULL_COMPARISON.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL093",
                        message=(
                            "Comparison to NULL — use '= Неопределено' or "
                            "ЗначениеЗаполнено() instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL094 — No-op compound assignment
    # ------------------------------------------------------------------

    def _rule_bsl094_noop_assignment(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag compound assignments that have no effect (e.g. += 0, *= 1)."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_NOOP_COMPOUND.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL094",
                        message=(
                            f"No-op compound assignment '{m.group().strip()}' — "
                            "this operation has no effect."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL095 — Multiple statements on one line
    # ------------------------------------------------------------------

    # Lines that are allowed to have ; mid-line (for/each, string literals etc.)
    _MULTI_STMT_SKIP = re.compile(
        r'^\s*(?:Для|For|ДляКаждого|ForEach|Пока|While|#)',
        re.IGNORECASE,
    )

    def _rule_bsl095_multiple_statements_on_one_line(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines that appear to contain two or more executable statements."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if self._MULTI_STMT_SKIP.match(line):
                continue
            # Skip lines that are purely structural keywords
            if not _RE_MULTI_STMT.search(stripped):
                continue
            # Must have content before and after the semicolon
            parts = stripped.split(";")
            executable = [p.strip() for p in parts if p.strip() and not p.strip().startswith("//")]
            if len(executable) >= 2:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL095",
                        message=(
                            "Multiple statements on one line — "
                            "split into separate lines for readability."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL096 — Export method with no comment block
    # ------------------------------------------------------------------

    def _rule_bsl096_undocumented_export_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag Export methods that have no comment block preceding them."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export:
                continue
            # Look at up to 5 lines before the header
            start = max(0, proc.start_idx - 5)
            preceding = lines[start: proc.start_idx]
            has_comment = any(ln.strip().startswith("//") for ln in preceding)
            if not has_comment:
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL096",
                        message=(
                            f"Export method '{proc.name}' has no preceding comment block — "
                            "add a // description for API consumers."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL097 — Use of ТекущаяДата() / CurrentDate()
    # ------------------------------------------------------------------

    def _rule_bsl097_use_of_current_date(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag ТекущаяДата()/CurrentDate() — recommend ТекущаяДатаСеанса()."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_CURRENT_DATE.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL097",
                        message=(
                            f"'{m.group().rstrip('(')}' returns server time — "
                            "use ТекущаяДатаСеанса() for consistent session-based time."
                        ),
                    )
                )
        return diags


    # ------------------------------------------------------------------
    # BSL098 — Use of Выполнить() / Execute()
    # ------------------------------------------------------------------

    def _rule_bsl098_use_of_execute(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Выполнить()/Execute() — dynamic code execution."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_EXECUTE.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL098",
                        message=(
                            f"'{m.group().rstrip('(')}()' executes code from a string — "
                            "refactor to use explicit calls instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL099 — Too many parameters
    # ------------------------------------------------------------------

    _MAX_PARAMS = 7

    def _rule_bsl099_too_many_parameters(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag procedures/functions with more than MAX_PARAMS parameters."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if len(proc.params) > self._MAX_PARAMS:
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL099",
                        message=(
                            f"'{proc.name}' has {len(proc.params)} parameters "
                            f"(max {self._MAX_PARAMS}) — consolidate into a structure."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL100 — Hardcoded file path
    # ------------------------------------------------------------------

    def _rule_bsl100_hardcoded_file_path(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag string literals containing hardcoded file system paths."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_HARDCODED_PATH.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL100",
                        message=(
                            "Hardcoded file path detected — "
                            "use a configuration parameter or constant instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL101 — Too deep nesting
    # ------------------------------------------------------------------

    _MAX_NESTING_DEPTH = 6

    # Keywords that increase nesting depth
    _NESTING_OPEN = re.compile(
        r'^\s*(?:Если|If|'
        r'Для|For|ДляКаждого|ForEach|Пока|While|'
        r'Попытка|Try)\b',
        re.IGNORECASE,
    )
    _NESTING_CLOSE = re.compile(
        r'^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b',
        re.IGNORECASE,
    )

    def _rule_bsl101_too_deep_nesting(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines where the structural nesting depth exceeds the maximum."""
        diags: list[Diagnostic] = []
        depth = 0
        reported: set[int] = set()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            # Decrease depth on closing keywords before reporting
            if self._NESTING_CLOSE.match(line):
                depth = max(0, depth - 1)
            if depth > self._MAX_NESTING_DEPTH and idx not in reported:
                reported.add(idx)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL101",
                        message=(
                            f"Nesting depth {depth} exceeds maximum "
                            f"{self._MAX_NESTING_DEPTH} — extract to a helper function."
                        ),
                    )
                )
            # Increase depth on opening keywords after reporting
            if self._NESTING_OPEN.match(line):
                depth += 1
        return diags

    # ------------------------------------------------------------------
    # BSL102 — Large module
    # ------------------------------------------------------------------

    _MAX_MODULE_LINES = 500

    def _rule_bsl102_large_module(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag modules with more than MAX_MODULE_LINES non-blank lines."""
        total = len(lines)
        if total <= self._MAX_MODULE_LINES:
            return []
        return [
            Diagnostic(
                file=path,
                line=1,
                character=0,
                end_line=1,
                end_character=0,
                severity=Severity.INFORMATION,
                code="BSL102",
                message=(
                    f"Module has {total} lines "
                    f"(max {self._MAX_MODULE_LINES}) — split into smaller modules."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL103 — Use of Вычислить() / Eval()
    # ------------------------------------------------------------------

    def _rule_bsl103_use_of_eval(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Вычислить()/Eval() — dynamic expression evaluation."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_EVAL.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL103",
                        message=(
                            f"'{m.group().rstrip('(')}()' evaluates a dynamic expression — "
                            "replace with explicit conditional logic."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL104 — Missing module comment header
    # ------------------------------------------------------------------

    def _rule_bsl104_missing_module_comment(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag modules that have no comment block in the first 5 lines."""
        if not lines:
            return []
        first_lines = lines[:5]
        has_comment = any(ln.strip().startswith("//") for ln in first_lines)
        if has_comment:
            return []
        # Skip empty files or files that start with a region
        first_non_blank = next(
            (ln.strip() for ln in lines if ln.strip()), ""
        )
        if first_non_blank.startswith("#"):
            return []
        return [
            Diagnostic(
                file=path,
                line=1,
                character=0,
                end_line=1,
                end_character=0,
                severity=Severity.INFORMATION,
                code="BSL104",
                message=(
                    "Module has no comment header — "
                    "add a // description of the module's purpose."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL105 — Use of Приостановить() / Sleep()
    # ------------------------------------------------------------------

    def _rule_bsl105_use_of_sleep(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Приостановить()/Sleep() — blocks the current thread."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_SLEEP.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL105",
                        message=(
                            f"'{m.group().rstrip('(')}()' blocks the current thread — "
                            "avoid in server-side code."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL106 — Query (ВЫБРАТЬ/SELECT) inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl106_query_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag SQL queries that appear inside a Цикл/EndDo loop."""
        diags: list[Diagnostic] = []
        loop_depth = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                # Track loop depth even on blank/comment lines? No — skip
                continue
            if _RE_LOOP_OPEN.match(line) or _RE_LOOP_FOR.match(line):
                loop_depth += 1
            elif _RE_LOOP_ENDDO.match(line):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth > 0 and _RE_SQL_SELECT.search(line):
                m = _RE_SQL_SELECT.search(line)
                assert m is not None
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL106",
                        message=(
                            "SQL query inside a loop — "
                            "move outside the loop or use batch operations."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL107 — Empty Тогда branch in Если statement
    # ------------------------------------------------------------------

    def _rule_bsl107_empty_then_branch(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Если ... Тогда blocks whose body is empty (next non-blank is КонецЕсли/ИначеЕсли/Иначе)."""
        diags: list[Diagnostic] = []
        n = len(lines)
        for idx, line in enumerate(lines):
            if not _RE_THEN.search(line):
                continue
            if line.strip().startswith("//"):
                continue
            # Look ahead for the first non-blank, non-comment line
            next_idx = idx + 1
            while next_idx < n and (
                not lines[next_idx].strip() or lines[next_idx].strip().startswith("//")
            ):
                next_idx += 1
            if next_idx >= n:
                continue
            is_empty = (
                _RE_ENDIF.match(lines[next_idx])
                or _RE_ELSEIF.match(lines[next_idx])
                or _RE_ELSE.match(lines[next_idx])
            )
            if is_empty:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL107",
                        message=(
                            "Empty Тогда branch — "
                            "add the missing logic or remove the branch."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL108 — Exported module-level variable
    # ------------------------------------------------------------------

    def _rule_bsl108_use_of_global_variables(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag module-level Перем declarations that are exported."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_EXPORTED_VAR.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL108",
                        message=(
                            "Exported module variable introduces mutable shared state — "
                            "pass the value as a parameter instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL109 — Negative conditional guard return
    # ------------------------------------------------------------------

    def _rule_bsl109_negative_conditional_return(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Если НЕ ... Тогда / Возврат pattern (guard clause with inverted cond)."""
        diags: list[Diagnostic] = []
        n = len(lines)
        for idx, line in enumerate(lines):
            if not _RE_NEGATIVE_CONDITION.match(line):
                continue
            # Next non-blank non-comment line should be a bare return
            next_idx = idx + 1
            while next_idx < n and (
                not lines[next_idx].strip() or lines[next_idx].strip().startswith("//")
            ):
                next_idx += 1
            if next_idx >= n:
                continue
            if _RE_RETURN_STMT.match(lines[next_idx]):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL109",
                        message=(
                            "Guard-clause with НЕ — "
                            "invert the condition to reduce nesting."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL110 — String self-concatenation inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl110_string_concat_in_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag А = А + '...' patterns inside a loop body."""
        diags: list[Diagnostic] = []
        loop_depth = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _RE_LOOP_OPEN.match(line) or _RE_LOOP_FOR.match(line):
                loop_depth += 1
            elif _RE_LOOP_ENDDO.match(line):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth > 0:
                m = _RE_STR_CONCAT_SELF.match(line)
                if m:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=idx + 1,
                            end_character=len(line.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL110",
                            message=(
                                "String self-concatenation inside a loop — "
                                "collect parts in a list and join after the loop."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL111 — Mixed-language identifier
    # ------------------------------------------------------------------

    def _rule_bsl111_mixed_language_identifiers(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag identifiers that mix Cyrillic and Latin characters."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_MIXED_IDENT.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL111",
                        message=(
                            f"Identifier '{m.group()}' mixes Cyrillic and Latin — "
                            "use one script consistently."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL112 — Unterminated transaction
    # ------------------------------------------------------------------

    def _rule_bsl112_unterminated_transaction(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag НачатьТранзакцию() calls that have no matching commit/rollback."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if not _RE_BEGIN_TRANSACTION.search(line):
                continue
            # Scan the rest of the procedure/function for commit or rollback
            found_end = False
            for j in range(idx + 1, len(lines)):
                jline = lines[j].strip()
                if _RE_COMMIT_TRANSACTION.search(jline):
                    found_end = True
                    break
                # Stop at the end of the enclosing procedure/function
                if re.match(
                    r'(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)',
                    jline,
                    re.IGNORECASE,
                ):
                    break
            if not found_end:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL112",
                        message=(
                            "НачатьТранзакцию() has no matching "
                            "ЗафиксироватьТранзакцию()/ОтменитьТранзакцию() in the same scope."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL113 — Assignment inside Если condition
    # ------------------------------------------------------------------

    def _rule_bsl113_assignment_in_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Если/ИначеЕсли lines that look like they use = for assignment."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_ASSIGN_IN_COND.match(line):
                # Exclude lines that already contain a comparison operator (<>, >=, <=)
                if re.search(r'<>|>=|<=', line):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL113",
                        message=(
                            "Possible assignment inside condition — "
                            "use a comparison operator instead of '='."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL114 — Empty module
    # ------------------------------------------------------------------

    def _rule_bsl114_empty_module(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag modules with no executable code (only blanks/comments)."""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("//") and not stripped.startswith("#"):
                return []
        # All lines are blank/comment/region
        return [
            Diagnostic(
                file=path,
                line=1,
                character=0,
                end_line=1,
                end_character=0,
                severity=Severity.INFORMATION,
                code="BSL114",
                message="Module contains no executable code — populate or remove it.",
            )
        ]

    # ------------------------------------------------------------------
    # BSL115 — Double negation (НЕ НЕ)
    # ------------------------------------------------------------------

    def _rule_bsl115_chained_negation(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag НЕ НЕ / Not Not double negation."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
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
                        severity=Severity.WARNING,
                        code="BSL115",
                        message=(
                            "Double negation НЕ НЕ — "
                            "simplify to the positive condition."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL116 — Obsolete indexed iterator (Для И = 0 По ... Цикл)
    # ------------------------------------------------------------------

    _RE_FOR_INDEX = re.compile(
        r'^\s*(?:Для|For)\s+\w+\s*=\s*\d+\s+(?:По|To)\b',
        re.IGNORECASE,
    )

    def _rule_bsl116_use_of_obsolete_iterator(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag indexed Для loops when a ДляКаждого pattern is available."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if self._RE_FOR_INDEX.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL116",
                        message=(
                            "Indexed Для loop — "
                            "prefer ДляКаждого/ForEach when iterating collections."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL117 — Procedure called as function (result used in expression)
    # ------------------------------------------------------------------

    def _rule_bsl117_procedure_called_as_function(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag calls to known Процедура where the return value is used."""
        # Build set of procedure names (not functions)
        procedure_names = {
            p.name.lower() for p in procs if p.kind == "procedure"
        }
        if not procedure_names:
            return []
        # Pattern: Var = ProcName(
        _re_proc_as_func = re.compile(
            r'^\s*\w+\s*=\s*(' + '|'.join(re.escape(n) for n in procedure_names) + r')\s*\(',
            re.IGNORECASE,
        )
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _re_proc_as_func.match(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL117",
                        message=(
                            f"'{m.group(1)}' is a Процедура — "
                            "it does not return a value; check whether you meant a Функция."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL118 — Функция with no Возврат <value>
    # ------------------------------------------------------------------

    def _rule_bsl118_function_returns_nothing(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag Функция bodies that never reach a Возврат with a value."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            body_lines = lines[proc.start_idx: proc.end_idx + 1]
            body_text = "\n".join(body_lines)
            if not _RE_RETURN_VALUE.search(body_text):
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL118",
                        message=(
                            f"Функция '{proc.name}' has no Возврат with a value — "
                            "add an explicit return or change to Процедура."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL119 — Line too long
    # ------------------------------------------------------------------

    _MAX_LINE_LENGTH = 120

    def _rule_bsl119_line_too_long(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines longer than MAX_LINE_LENGTH characters."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            length = len(line.rstrip("\n\r"))
            if length > self._MAX_LINE_LENGTH:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=self._MAX_LINE_LENGTH,
                        end_line=idx + 1,
                        end_character=length,
                        severity=Severity.INFORMATION,
                        code="BSL119",
                        message=(
                            f"Line is {length} characters long "
                            f"(max {self._MAX_LINE_LENGTH}) — split into multiple lines."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL120 — Trailing whitespace
    # ------------------------------------------------------------------

    def _rule_bsl120_trailing_whitespace(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines that have trailing whitespace."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            stripped = line.rstrip("\n\r")
            if stripped != stripped.rstrip():
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(stripped.rstrip()),
                        end_line=idx + 1,
                        end_character=len(stripped),
                        severity=Severity.INFORMATION,
                        code="BSL120",
                        message="Trailing whitespace — remove for consistent diffs.",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL121 — Tab indentation
    # ------------------------------------------------------------------

    def _rule_bsl121_tab_indentation(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines that use tab characters for indentation."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if "\t" in line:
                col = line.index("\t")
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=col + 1,
                        severity=Severity.INFORMATION,
                        code="BSL121",
                        message="Tab character used for indentation — use 4 spaces instead.",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL122 — Unused parameter
    # ------------------------------------------------------------------

    def _rule_bsl122_unused_parameter(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag procedure/function parameters that are never referenced in the body."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.params:
                continue
            body_lines = lines[proc.start_idx + 1: proc.end_idx]
            body_text = "\n".join(body_lines).lower()
            for param in proc.params:
                # Strip default value and leading &/Val markers
                raw = param.lstrip("&").split("=")[0].strip()
                # Remove leading Val/Значение keyword
                pname = re.sub(
                    r'^\s*(?:Значение|Val)\s+', "", raw, flags=re.IGNORECASE
                ).strip()
                if not pname:
                    continue
                if pname.lower() not in body_text:
                    header = lines[proc.start_idx]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=proc.header_col,
                            end_line=proc.start_idx + 1,
                            end_character=len(header.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL122",
                            message=(
                                f"Parameter '{pname}' in '{proc.name}' "
                                "is never used in the body."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL123 — Commented-out code
    # ------------------------------------------------------------------

    def _rule_bsl123_commented_out_code(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag comment lines that appear to contain commented-out code."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_COMMENTED_CODE.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL123",
                        message=(
                            "Commented-out code detected — "
                            "remove it or restore with an explanation."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL124 — Short procedure/function name
    # ------------------------------------------------------------------

    _MIN_PROC_NAME_LEN = 3

    def _rule_bsl124_short_procedure_name(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag procedures/functions whose name is shorter than MIN_PROC_NAME_LEN."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if len(proc.name) < self._MIN_PROC_NAME_LEN:
                header = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=proc.header_col,
                        end_line=proc.start_idx + 1,
                        end_character=len(header.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL124",
                        message=(
                            f"'{proc.name}' is too short ({len(proc.name)} chars) — "
                            "use a descriptive name of at least 3 characters."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL125 — Break (Прервать) outside a loop
    # ------------------------------------------------------------------

    def _rule_bsl125_break_outside_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Прервать/Break statements that appear outside any loop."""
        diags: list[Diagnostic] = []
        loop_depth = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _RE_LOOP_OPEN.match(line) or _RE_LOOP_FOR.match(line):
                loop_depth += 1
            elif _RE_LOOP_ENDDO.match(line):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth == 0 and _RE_BREAK.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL125",
                        message="Прервать/Break outside a loop — has no effect.",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL126 — Continue (Продолжить) outside a loop
    # ------------------------------------------------------------------

    def _rule_bsl126_continue_outside_loop(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag Продолжить/Continue statements that appear outside any loop."""
        diags: list[Diagnostic] = []
        loop_depth = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _RE_LOOP_OPEN.match(line) or _RE_LOOP_FOR.match(line):
                loop_depth += 1
            elif _RE_LOOP_ENDDO.match(line):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth == 0 and _RE_CONTINUE.match(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL126",
                        message="Продолжить/Continue outside a loop — has no effect.",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL127 — Multiple top-level return statements in a function
    # ------------------------------------------------------------------

    def _rule_bsl127_multiple_return_values(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag functions with more than one top-level Возврат statement."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            body_lines = lines[proc.start_idx + 1: proc.end_idx]
            # Count top-level Возврат statements (not inside nested if/loop)
            depth = 0
            top_returns: list[int] = []
            for rel_idx, line in enumerate(body_lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if (
                    _RE_IF_OPEN.match(line)
                    or _RE_LOOP_OPEN.match(line)
                    or _RE_LOOP_FOR.match(line)
                    or _RE_TRY_OPEN.match(line)
                ):
                    depth += 1
                elif _RE_ENDIF.match(line) or _RE_LOOP_ENDDO.match(line) or _RE_END_TRY.match(line):
                    depth = max(0, depth - 1)
                elif depth == 0 and _RE_RETURN_VALUE.match(line):
                    top_returns.append(proc.start_idx + 1 + rel_idx)
            if len(top_returns) > 1:
                # Report on the second+ return
                for abs_idx in top_returns[1:]:
                    ret_line = lines[abs_idx]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=abs_idx + 1,
                            character=len(ret_line) - len(ret_line.lstrip()),
                            end_line=abs_idx + 1,
                            end_character=len(ret_line.rstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL127",
                            message=(
                                f"'{proc.name}' has multiple top-level Возврат statements — "
                                "consolidate to a single exit point."
                            ),
                        )
                    )
        return diags


    # ------------------------------------------------------------------
    # BSL128 — DeadCodeAfterReturn
    # ------------------------------------------------------------------

    def _rule_bsl128_dead_code_after_return(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag lines that are unreachable after an unconditional Возврат at depth 0."""
        diags: list[Diagnostic] = []
        for proc in procs:
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            depth = 0
            dead_from: int | None = None
            for rel_idx, line in enumerate(body_lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if (
                    _RE_IF_OPEN.match(line)
                    or _RE_LOOP_OPEN.match(line)
                    or _RE_LOOP_FOR.match(line)
                    or _RE_TRY_OPEN.match(line)
                ):
                    if dead_from is not None:
                        # Entering a new block resets — code is live again
                        dead_from = None
                    depth += 1
                elif _RE_ENDIF.match(line) or _RE_LOOP_ENDDO.match(line) or _RE_END_TRY.match(line):
                    depth = max(0, depth - 1)
                    if dead_from is not None and depth == 0:
                        dead_from = None
                elif depth == 0 and dead_from is None and _RE_RETURN_STMT.match(line):
                    # Found unconditional return at depth 0 — mark subsequent lines as dead
                    dead_from = rel_idx
                elif dead_from is not None and depth == 0:
                    abs_idx = proc.start_idx + 1 + rel_idx
                    actual_line = lines[abs_idx]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=abs_idx + 1,
                            character=len(actual_line) - len(actual_line.lstrip()),
                            end_line=abs_idx + 1,
                            end_character=len(actual_line.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL128",
                            message=(
                                f"Dead code in '{proc.name}': this line is unreachable after "
                                "an unconditional Возврат."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL129 — RecursiveCall
    # ------------------------------------------------------------------

    def _rule_bsl129_recursive_call(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag procedures/functions that directly call themselves."""
        diags: list[Diagnostic] = []
        for proc in procs:
            pattern = re.compile(
                r'(?<![.\w])' + re.escape(proc.name) + r'\s*\(',
                re.IGNORECASE,
            )
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            for rel_idx, line in enumerate(body_lines):
                if line.strip().startswith("//"):
                    continue
                if pattern.search(line):
                    abs_idx = proc.start_idx + 1 + rel_idx
                    actual_line = lines[abs_idx]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=abs_idx + 1,
                            character=len(actual_line) - len(actual_line.lstrip()),
                            end_line=abs_idx + 1,
                            end_character=len(actual_line.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL129",
                            message=(
                                f"'{proc.name}' calls itself recursively — "
                                "ensure the recursion is intentional and has a base case."
                            ),
                        )
                    )
                    break  # one diagnostic per proc is sufficient
        return diags

    # ------------------------------------------------------------------
    # BSL130 — LongCommentLine
    # ------------------------------------------------------------------

    def _rule_bsl130_long_comment_line(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag comment-only lines longer than 120 characters."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_COMMENT_ONLY_LINE.match(line) and len(line.rstrip()) > 120:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=0,
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL130",
                        message=(
                            f"Comment line is {len(line.rstrip())} characters long "
                            "(max 120) — split into shorter lines."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL131 — EmptyRegion
    # ------------------------------------------------------------------

    def _rule_bsl131_empty_region(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag #Область immediately followed by #КонецОбласти with no code in between."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not _RE_REGION_OPEN_LINE.match(line):
                continue
            # Look ahead for first non-blank line
            for j in range(idx + 1, len(lines)):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    continue
                if _RE_REGION_CLOSE_LINE.match(lines[j]):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=idx + 1,
                            end_character=len(line.rstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL131",
                            message=(
                                "Empty region: #Область is immediately followed by "
                                "#КонецОбласти with no code inside — remove or populate it."
                            ),
                        )
                    )
                break
        return diags

    # ------------------------------------------------------------------
    # BSL132 — RepeatedStringLiteral
    # ------------------------------------------------------------------

    def _rule_bsl132_repeated_string_literal(
        self, path: str, lines: list[str], content: str
    ) -> list[Diagnostic]:
        """Flag string literals that appear 4 or more times in the file."""
        diags: list[Diagnostic] = []
        all_strings = _RE_STRING_LITERAL.findall(content)
        counts: dict[str, int] = {}
        for s in all_strings:
            counts[s] = counts.get(s, 0) + 1
        repeated = {s for s, c in counts.items() if c >= 4}
        if not repeated:
            return diags
        reported: set[str] = set()
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            for m in _RE_STRING_LITERAL.finditer(line):
                s = m.group(1)
                if s in repeated and s not in reported:
                    reported.add(s)
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=m.start(),
                            end_line=idx + 1,
                            end_character=m.end(),
                            severity=Severity.INFORMATION,
                            code="BSL132",
                            message=(
                                f'String literal "{s}" appears {counts[s]} times in this file '
                                "— extract to a named constant."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL133 — RequiredParamAfterOptional
    # ------------------------------------------------------------------

    def _rule_bsl133_required_param_after_optional(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag when a required param appears after an optional (default-valued) one."""
        diags: list[Diagnostic] = []
        for proc in procs:
            header_line = lines[proc.start_idx]
            m = _RE_PROC_HEADER.search(header_line)
            if not m:
                continue
            params_str = m.group("params") or ""
            parsed = _parse_params(params_str)
            found_optional = False
            for name, _is_val, is_optional in parsed:
                if is_optional:
                    found_optional = True
                elif found_optional:
                    # Required param after optional
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=len(header_line) - len(header_line.lstrip()),
                            end_line=proc.start_idx + 1,
                            end_character=len(header_line.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL133",
                            message=(
                                f"'{proc.name}': required parameter '{name}' "
                                "appears after an optional (default-valued) parameter — "
                                "reorder so all required params come first."
                            ),
                        )
                    )
                    break  # one diagnostic per proc
        return diags

    # ------------------------------------------------------------------
    # BSL134 — CyclomaticComplexity
    # ------------------------------------------------------------------

    MAX_CYCLOMATIC_COMPLEXITY: int = 10

    def _rule_bsl134_cyclomatic_complexity(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag functions/procedures whose cyclomatic complexity exceeds the maximum."""
        diags: list[Diagnostic] = []
        max_cc = self.MAX_CYCLOMATIC_COMPLEXITY
        for proc in procs:
            cc = 1  # baseline
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if line.strip().startswith("//"):
                    continue
                if _RE_MCCABE_BRANCH_BSL134.match(line):
                    cc += 1
            if cc > max_cc:
                header_line = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=len(header_line) - len(header_line.lstrip()),
                        end_line=proc.start_idx + 1,
                        end_character=len(header_line.rstrip()),
                        severity=Severity.WARNING,
                        code="BSL134",
                        message=(
                            f"'{proc.name}' has cyclomatic complexity {cc} "
                            f"(max {max_cc}) — refactor into smaller functions."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL135 — NestedFunctionCalls
    # ------------------------------------------------------------------

    def _rule_bsl135_nested_function_calls(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines where a function call is passed directly as an argument to another."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_NESTED_CALL.search(line):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(line.lstrip()),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL135",
                        message=(
                            "Nested function call: a function's result is passed directly "
                            "as an argument — extract to a named variable for readability."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL136 — MissingSpaceBeforeComment
    # ------------------------------------------------------------------

    def _rule_bsl136_missing_space_before_comment(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines where inline // is not preceded by a space."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            m = _RE_NO_SPACE_BEFORE_COMMENT.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start() + 1,  # position of the first /
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL136",
                        message=(
                            "Missing space before inline comment '//' — "
                            "add a space between code and the comment."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL137 — UseOfFindByDescription
    # ------------------------------------------------------------------

    def _rule_bsl137_use_of_find_by_description(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag calls to НайтиПоНаименованию/FindByDescription and similar slow methods."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_FIND_BY_DESCRIPTION.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL137",
                        message=(
                            f"'{m.group().rstrip('(')}' performs a full-table scan — "
                            "use НайтиПоСсылке() or a query with an indexed field instead."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL138 — UseOfDebugOutput
    # ------------------------------------------------------------------

    def _rule_bsl138_use_of_debug_output(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag calls to Сообщить()/Message()/Предупреждение()/Warning() debug output."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_DEBUG_OUTPUT.search(line)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL138",
                        message=(
                            f"'{m.group().rstrip('(')}' is debug output — "
                            "remove before deploying to production."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL139 — TooLongParameterName
    # ------------------------------------------------------------------

    _MAX_PARAM_NAME_LEN: int = 30

    def _rule_bsl139_too_long_parameter_name(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag parameter names longer than 30 characters."""
        diags: list[Diagnostic] = []
        for proc in procs:
            for param in proc.params:
                if len(param) > self._MAX_PARAM_NAME_LEN:
                    line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                    col = line_text.find(param)
                    if col < 0:
                        col = 0
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=col,
                            end_line=proc.start_idx + 1,
                            end_character=col + len(param),
                            severity=Severity.INFORMATION,
                            code="BSL139",
                            message=(
                                f"Parameter '{param}' has {len(param)} characters — "
                                f"keep parameter names under {self._MAX_PARAM_NAME_LEN} characters."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL140 — UnreachableElseIf
    # ------------------------------------------------------------------

    def _rule_bsl140_unreachable_elseif(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag ИначеЕсли/ElsIf that immediately follows an unconditional Иначе/Else."""
        diags: list[Diagnostic] = []
        depth = 0
        after_else_at_depth0 = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if _RE_IF_OPEN.match(line):
                depth += 1
                after_else_at_depth0 = False
            elif _RE_ENDIF.match(line):
                if depth > 0:
                    depth -= 1
                after_else_at_depth0 = False
            elif depth == 1 and _RE_ELSE.match(line):
                after_else_at_depth0 = True
            elif depth == 1 and _RE_ELSEIF.match(line):
                if after_else_at_depth0:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=idx + 1,
                            end_character=len(line.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL140",
                            message=(
                                "Unreachable ИначеЕсли/ElsIf after an unconditional "
                                "Иначе/Else — this branch can never be reached."
                            ),
                        )
                    )
                after_else_at_depth0 = False
            elif stripped and not stripped.startswith("//"):
                if depth == 1 and after_else_at_depth0:
                    # We're inside the Else block — keep flag
                    pass
        return diags

    # ------------------------------------------------------------------
    # BSL141 — MagicBooleanReturn
    # ------------------------------------------------------------------

    def _rule_bsl141_magic_boolean_return(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag functions whose body contains both 'Возврат Истина' and 'Возврат Ложь'."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            body_start = proc.start_idx + 1
            body_end = min(proc.end_idx, len(lines))
            first_true_idx = None
            has_false = False
            for i in range(body_start, body_end):
                ln = lines[i]
                if _RE_RETURN_TRUE.match(ln):
                    if first_true_idx is None:
                        first_true_idx = i
                if _RE_RETURN_FALSE.match(ln):
                    has_false = True
            if first_true_idx is not None and has_false:
                ln = lines[first_true_idx]
                col = len(ln) - len(ln.lstrip())
                diags.append(
                    Diagnostic(
                        file=path,
                        line=first_true_idx + 1,
                        character=col,
                        end_line=first_true_idx + 1,
                        end_character=len(ln.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL141",
                        message=(
                            "Function returns literal Истина/Ложь — "
                            "replace with a direct boolean expression (Возврат Условие;)."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL142 — LargeParameterDefaultValue
    # ------------------------------------------------------------------

    _MAX_DEFAULT_VALUE_LEN: int = 50

    def _rule_bsl142_large_param_default_value(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag parameter default values longer than 50 characters."""
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.start_idx >= len(lines):
                continue
            header_line = lines[proc.start_idx]
            # Extract raw params string from header
            m_header = _RE_PROC_HEADER.match(header_line)
            if not m_header:
                continue
            params_str = m_header.group("params") or ""
            for raw in split_commas_outside_double_quotes(params_str):
                raw = raw.strip()
                if not raw:
                    continue
                if "=" not in raw:
                    continue
                default_part = raw.split("=", 1)[1].strip()
                if len(default_part) > self._MAX_DEFAULT_VALUE_LEN:
                    col = header_line.find(default_part)
                    if col < 0:
                        col = 0
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=col,
                            end_line=proc.start_idx + 1,
                            end_character=col + len(default_part),
                            severity=Severity.INFORMATION,
                            code="BSL142",
                            message=(
                                f"Parameter default value is {len(default_part)} characters — "
                                f"move complex defaults (>{self._MAX_DEFAULT_VALUE_LEN} chars) "
                                "to a named constant."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL143 — DuplicateElseIfCondition
    # ------------------------------------------------------------------

    def _rule_bsl143_duplicate_elseif_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag the same condition text appearing twice in an Если/ИначеЕсли chain."""
        diags: list[Diagnostic] = []
        depth = 0
        # Stack: list of (conditions_seen_set, first_line_map)
        # Each entry tracks conditions at this if-block level
        chain_stack: list[dict[str, int]] = []  # cond_lower -> first line number
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if _RE_IF_OPEN.match(line) and not _RE_ELSEIF.match(line):
                depth += 1
                chain_stack.append({})
                m = _RE_IF_COND.match(line)
                if m and chain_stack:
                    cond = m.group(1).strip().lower()
                    chain_stack[-1][cond] = idx + 1
            elif _RE_ELSEIF.match(line):
                m = _RE_IF_COND.match(line)
                if m and chain_stack:
                    cond = m.group(1).strip().lower()
                    if cond in chain_stack[-1]:
                        col = len(line) - len(line.lstrip())
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=col,
                                end_line=idx + 1,
                                end_character=len(line.rstrip()),
                                severity=Severity.WARNING,
                                code="BSL143",
                                message=(
                                    f"Duplicate condition '{m.group(1).strip()}' in "
                                    f"ИначеЕсли chain — first seen on line "
                                    f"{chain_stack[-1][cond]}."
                                ),
                            )
                        )
                    else:
                        chain_stack[-1][cond] = idx + 1
            elif _RE_ENDIF.match(line):
                if chain_stack:
                    chain_stack.pop()
                if depth > 0:
                    depth -= 1
        return diags

    # ------------------------------------------------------------------
    # BSL144 — UnnecessaryParentheses
    # ------------------------------------------------------------------

    def _rule_bsl144_unnecessary_parentheses(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag 'Возврат (expr)' where the return value is wrapped in redundant parens."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_RETURN_PAREN.search(line)
            if m:
                col = len(line) - len(line.lstrip())
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL144",
                        message=(
                            "Return value is wrapped in redundant parentheses — "
                            "remove the outer parentheses."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL145 — StringFormatInsteadOfConcat
    # ------------------------------------------------------------------

    def _rule_bsl145_string_format_instead_of_concat(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag lines with 3+ string parts joined by '+'."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_MULTI_CONCAT.search(line)
            if m:
                col = m.start()
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL145",
                        message=(
                            "Three or more string parts joined with '+' — "
                            "use СтрШаблон()/StrTemplate() for readable string interpolation."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL146 — ModuleInitializationCode
    # ------------------------------------------------------------------

    def _rule_bsl146_module_initialization_code(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag executable statements at module level outside any procedure/function."""
        diags: list[Diagnostic] = []
        # Build set of line indices that are inside a proc body
        inside_proc: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside_proc.add(i)

        _re_perем = re.compile(r'^\s*(?:Перем|Var)\b', re.IGNORECASE)
        _re_region = re.compile(r'^\s*#(?:Область|Region|КонецОбласти|EndRegion)\b', re.IGNORECASE)
        _re_preproc = re.compile(r'^\s*#', re.IGNORECASE)
        _re_exec = re.compile(r'[А-Яа-яA-Za-z0-9_]')

        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("//"):
                continue
            if _re_perем.match(line):
                continue
            if _re_region.match(line):
                continue
            if _re_preproc.match(line):
                continue
            # Must look like an executable statement (contains identifier chars)
            if _re_exec.search(stripped):
                col = len(line) - len(line.lstrip())
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.INFORMATION,
                        code="BSL146",
                        message=(
                            "Executable statement at module level — "
                            "move initialization code into a dedicated Инициализация() procedure."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL147 — UseOfUICall
    # ------------------------------------------------------------------

    def _rule_bsl147_use_of_ui_call(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag ОткрытьФорму()/OpenForm() in server-side code (BSLLS — not in ``&НаКлиенте``)."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = _RE_UI_CALL.search(line)
            if not m:
                continue
            proc = _proc_containing_line(procs, idx)
            if proc is not None:
                ctx = _procedure_compiler_execution_context(lines, proc)
                if ctx in ("client", "both"):
                    continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.WARNING,
                    code="BSL147",
                    message=(
                        f"'{m.group().rstrip('(')}' is a UI call — "
                        "remove or restrict to client-side context."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL151 — BeginTransactionBeforeTryCatch
    # ------------------------------------------------------------------

    def _rule_bsl151_begin_transaction_before_try(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """НачатьТранзакцию()/BeginTransaction() must be immediately before Попытка/Try."""
        diags: list[Diagnostic] = []
        _re_begin = re.compile(
            r"^\s*(?:НачатьТранзакцию|BeginTransaction)\s*\(",
            re.IGNORECASE,
        )
        _re_try = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_comment = re.compile(r"^\s*//")

        for idx, line in enumerate(lines):
            if _re_begin.search(line):
                # Look for Try as the next non-blank, non-comment line
                found_try = False
                for j in range(idx + 1, min(idx + 5, len(lines))):
                    nl = lines[j]
                    if _re_comment.match(nl) or not nl.strip():
                        continue
                    found_try = _re_try.match(nl) is not None
                    break
                if not found_try:
                    col = len(line) - len(line.lstrip())
                    m = _re_begin.search(line)
                    diags.append(Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start() if m else col,
                        end_line=idx + 1,
                        end_character=(m.end() if m else col + 20),
                        severity=Severity.ERROR,
                        code="BSL151",
                        message=(
                            "НачатьТранзакцию() должна находиться непосредственно "
                            "перед блоком Попытка"
                        ),
                    ))
        return diags

    # ------------------------------------------------------------------
    # BSL157 — CommitTransactionOutsideTryCatch
    # ------------------------------------------------------------------

    def _rule_bsl157_commit_transaction_outside_try(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """ЗафиксироватьТранзакцию()/CommitTransaction() must be inside a Try block."""
        diags: list[Diagnostic] = []
        _re_commit = re.compile(
            r"^\s*(?:ЗафиксироватьТранзакцию|CommitTransaction)\s*\(",
            re.IGNORECASE,
        )
        _re_try = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_except = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
        _re_end_try = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)

        for idx, line in enumerate(lines):
            if not _re_commit.search(line):
                continue
            # Check if we are inside a Попытка block by scanning backwards
            depth = 0
            inside_try = False
            for j in range(idx - 1, max(-1, idx - 200), -1):
                bl = lines[j]
                if _re_end_try.match(bl):
                    depth += 1
                elif _re_try.match(bl):
                    if depth == 0:
                        inside_try = True
                        break
                    depth -= 1
            if not inside_try:
                m = _re_commit.search(line)
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start() if m else 0,
                    end_line=idx + 1,
                    end_character=m.end() if m else len(line),
                    severity=Severity.ERROR,
                    code="BSL157",
                    message=(
                        "ЗафиксироватьТранзакцию() должна вызываться внутри блока "
                        "Попытка (перед Исключение)"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL173 — DeletingCollectionItem
    # ------------------------------------------------------------------

    def _rule_bsl173_deleting_collection_item(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """Detect deletion of a collection item inside a Для Каждого/For Each loop."""
        diags: list[Diagnostic] = []
        _re_foreach = re.compile(
            r"^\s*(?:Для\s+Каждого|For\s+Each)\s+(\w+)\s+(?:Из|In)\s+(\w+(?:\.\w+)*)",
            re.IGNORECASE | re.UNICODE,
        )
        _re_end_loop = re.compile(
            r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE
        )
        _re_delete = re.compile(
            r"(\w+(?:\.\w+)*)\s*\.\s*(?:Удалить|Delete)\s*\(",
            re.IGNORECASE | re.UNICODE,
        )

        i = 0
        while i < len(lines):
            m = _re_foreach.match(lines[i])
            if m:
                iter_var = m.group(1).casefold()
                collection = m.group(2).casefold()
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    bl = lines[j]
                    if _re_foreach.match(bl):
                        depth += 1
                    elif _re_end_loop.match(bl):
                        depth -= 1
                        if depth == 0:
                            break
                    if depth == 1:
                        dm = _re_delete.search(bl)
                        if dm:
                            # object before .Удалить must match collection
                            obj = dm.group(1).casefold().split(".")[-1]
                            arg_start = bl.find("(", dm.end() - 1) + 1
                            arg_end = bl.find(")", arg_start) if arg_start > 0 else -1
                            arg = bl[arg_start:arg_end].strip().casefold() if arg_end > arg_start else ""
                            if obj == collection or arg == iter_var:
                                diags.append(Diagnostic(
                                    file=path,
                                    line=j + 1,
                                    character=dm.start(),
                                    end_line=j + 1,
                                    end_character=dm.end(),
                                    severity=Severity.ERROR,
                                    code="BSL173",
                                    message=(
                                        "Удаление элемента коллекции внутри цикла "
                                        "«Для Каждого» может привести к ошибке"
                                    ),
                                ))
                    j += 1
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL172 — DataExchangeLoading
    # ------------------------------------------------------------------

    def _rule_bsl172_data_exchange_loading(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """Handlers ПередЗаписью/ПриЗаписи must check ОбменДаннымиЗагрузка flag."""
        diags: list[Diagnostic] = []
        _re_handler = re.compile(
            r"^\s*(?:Процедура|Procedure)\s+"
            r"(?:ПередЗаписью|BeforeWrite|ПриЗаписи|OnWrite|"
            r"ОбработкаПроверкиЗаполнения|CheckFilling)\s*\(",
            re.IGNORECASE | re.UNICODE,
        )
        _re_exchange = re.compile(
            r"(?:ОбменДаннымиЗагрузка|DataExchangeLoad)\b",
            re.IGNORECASE,
        )

        for proc in procs:
            start = proc.start_idx
            line = lines[start] if start < len(lines) else ""
            if not _re_handler.match(line):
                continue
            # Check if any line in the proc body references ОбменДаннымиЗагрузка
            body_lines = lines[start:proc.end_idx]
            has_check = any(_re_exchange.search(bl) for bl in body_lines)
            if not has_check:
                m = _re_handler.match(line)
                diags.append(Diagnostic(
                    file=path,
                    line=start + 1,
                    character=m.start() if m else 0,
                    end_line=start + 1,
                    end_character=m.end() if m else len(line),
                    severity=Severity.WARNING,
                    code="BSL172",
                    message=(
                        "Обработчик не проверяет «ОбменДаннымиЗагрузка» — "
                        "добавьте проверку в начало метода"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL186 — ExtraCommas
    # ------------------------------------------------------------------

    def _rule_bsl186_extra_commas(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect trailing commas in method calls or declarations."""
        diags: list[Diagnostic] = []
        # Trailing comma before ) or ; is suspicious
        _re_trailing = re.compile(r",\s*[)\];]")
        _re_comment = re.compile(r"^\s*//")

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            m = _re_trailing.search(clean)
            if m:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.start() + 1,
                    severity=Severity.WARNING,
                    code="BSL186",
                    message="Лишняя запятая перед закрывающей скобкой или точкой с запятой",
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL197 — IfElseDuplicatedCodeBlock
    # ------------------------------------------------------------------

    def _rule_bsl197_if_else_duplicated_code_block(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect identical code blocks in consecutive If/ElseIf branches."""
        diags: list[Diagnostic] = []
        _re_if = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE)
        _re_elseif = re.compile(r"^\s*(?:ИначеЕсли|ElseIf)\b", re.IGNORECASE)
        _re_else = re.compile(r"^\s*(?:Иначе|Else)\b", re.IGNORECASE)
        _re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)

        i = 0
        while i < len(lines):
            if not _re_if.match(lines[i]):
                i += 1
                continue

            # Collect branches: list of (start_line, list_of_body_lines)
            branches: list[tuple[int, list[str]]] = []
            branch_start = i
            depth = 1
            j = i + 1
            current_body: list[str] = []

            while j < len(lines) and depth > 0:
                bl = lines[j]
                if _re_if.match(bl):
                    depth += 1
                elif _re_endif.match(bl):
                    depth -= 1
                    if depth == 0:
                        branches.append((branch_start, current_body[:]))
                        break
                if depth == 1 and (_re_elseif.match(bl) or _re_else.match(bl)):
                    branches.append((branch_start, current_body[:]))
                    current_body = []
                    branch_start = j
                else:
                    if depth == 1:
                        current_body.append(bl.strip())
                j += 1

            # Check for duplicate bodies (normalize whitespace)
            seen: dict[str, int] = {}
            for b_start, b_body in branches:
                key = "\n".join(b_body)
                if len(b_body) >= 1 and key and key in seen:
                    diags.append(Diagnostic(
                        file=path,
                        line=b_start + 1,
                        character=0,
                        end_line=b_start + 1,
                        end_character=len(lines[b_start]),
                        severity=Severity.WARNING,
                        code="BSL197",
                        message=(
                            "Тело этой ветки «ИначеЕсли/Иначе» идентично "
                            f"телу ветки на строке {seen[key] + 1}"
                        ),
                    ))
                else:
                    seen[key] = b_start
            i = j + 1
        return diags

    # ------------------------------------------------------------------
    # BSL198 — IfElseDuplicatedCondition
    # ------------------------------------------------------------------

    def _rule_bsl198_if_else_duplicated_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect duplicate conditions in If/ElseIf chain."""
        diags: list[Diagnostic] = []
        _re_if = re.compile(
            r"^\s*(?:Если|If)\s+(.+?)\s+(?:Тогда|Then)\b",
            re.IGNORECASE | re.UNICODE,
        )
        _re_elseif = re.compile(
            r"^\s*(?:ИначеЕсли|ElseIf)\s+(.+?)\s+(?:Тогда|Then)\b",
            re.IGNORECASE | re.UNICODE,
        )
        _re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)

        i = 0
        while i < len(lines):
            m = _re_if.match(lines[i])
            if not m:
                i += 1
                continue

            conditions: dict[str, int] = {m.group(1).strip().casefold(): i}
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                bl = lines[j]
                if _re_if.match(bl):
                    depth += 1
                elif _re_endif.match(bl):
                    depth -= 1
                elif depth == 1:
                    em = _re_elseif.match(bl)
                    if em:
                        cond = em.group(1).strip().casefold()
                        if cond in conditions:
                            diags.append(Diagnostic(
                                file=path,
                                line=j + 1,
                                character=0,
                                end_line=j + 1,
                                end_character=len(bl),
                                severity=Severity.WARNING,
                                code="BSL198",
                                message=(
                                    f"Условие «ИначеЕсли» совпадает с условием "
                                    f"на строке {conditions[cond] + 1} — ветка недостижима"
                                ),
                            ))
                        else:
                            conditions[cond] = j
                j += 1
            i = j + 1
        return diags

    # ------------------------------------------------------------------
    # BSL227 — OneStatementPerLine
    # ------------------------------------------------------------------

    def _rule_bsl227_one_statement_per_line(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """Detect multiple statements (semicolons) on one line inside procedures."""
        diags: list[Diagnostic] = []
        _re_comment = re.compile(r"^\s*//")
        _re_header = re.compile(
            r"^\s*(?:Процедура|Функция|Procedure|Function|"
            r"КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b",
            re.IGNORECASE,
        )

        # Build set of lines that are inside procedure bodies
        proc_lines: set[int] = set()
        for proc in procs:
            for li in range(proc.start_idx + 1, proc.end_idx):
                proc_lines.add(li)

        for idx, line in enumerate(lines):
            if idx not in proc_lines:
                continue
            if _re_comment.match(line) or _re_header.match(line):
                continue
            # Remove string literals and count semicolons
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            # Count semicolons not inside parentheses
            depth = 0
            semi_count = 0
            for ch in clean:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == ";" and depth == 0:
                    semi_count += 1
            if semi_count >= 2:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=0,
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
                    code="BSL227",
                    message=(
                        "Несколько операторов на одной строке "
                        "— разместите каждый на отдельной строке"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL258 — UnionAll
    # ------------------------------------------------------------------

    def _rule_bsl258_union_without_all(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect ОБЪЕДИНИТЬ/UNION without ALL in query strings."""
        diags: list[Diagnostic] = []
        # ОБЪЕДИНИТЬ not followed by ВСЕ (after optional whitespace)
        _re_union = re.compile(
            r"\b(?:ОБЪЕДИНИТЬ|UNION)\b(?!\s+(?:ВСЕ|ALL)\b)",
            re.IGNORECASE,
        )
        in_query = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            # Detect query string start/end heuristic
            if '|"' in line or line.strip().startswith("|"):
                in_query = True
            if stripped.endswith('";') or (stripped.endswith('"') and "ВЫБРАТЬ" not in stripped):
                in_query = False

            # Check for UNION/ОБЪЕДИНИТЬ
            check_line = line if in_query else line
            m = _re_union.search(check_line)
            if m:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.WARNING,
                    code="BSL258",
                    message=(
                        "«ОБЪЕДИНИТЬ» без «ВСЕ» выполняет дедупликацию — "
                        "используйте «ОБЪЕДИНИТЬ ВСЕ» если дубли допустимы"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL153 — CanonicalSpellingKeywords
    # ------------------------------------------------------------------

    # BSL canonical keyword forms (title case)
    _CANONICAL_KEYWORDS: dict[str, str] = {
        "если": "Если", "иначеесли": "ИначеЕсли", "иначе": "Иначе",
        "конецесли": "КонецЕсли", "для": "Для",
        # "каждого" omitted — BSLLS accepts both "Каждого" and "каждого" (EACH_LO variant)
        "из": "Из", "цикл": "Цикл", "конеццикла": "КонецЦикла",
        "пока": "Пока", "прервать": "Прервать", "продолжить": "Продолжить",
        "попытка": "Попытка", "исключение": "Исключение",
        "конецпопытки": "КонецПопытки", "вызватьисключение": "ВызватьИсключение",
        "возврат": "Возврат", "перейти": "Перейти",
        "процедура": "Процедура", "функция": "Функция",
        "конецпроцедуры": "КонецПроцедуры", "конецфункции": "КонецФункции",
        "перем": "Перем", "тогда": "Тогда", "по": "По", "новый": "Новый",
        "экспорт": "Экспорт", "знач": "Знач", "не": "Не", "и": "И",
        "или": "Или", "истина": "Истина", "ложь": "Ложь",
        "неопределено": "Неопределено", "null": "Null",
    }
    # Only flag words that differ in case from their canonical form
    _CANONICAL_RE = re.compile(
        r'\b(?:' + '|'.join(re.escape(k) for k in _CANONICAL_KEYWORDS) + r')\b',
        re.IGNORECASE | re.UNICODE,
    )

    def _rule_bsl153_canonical_spelling_keywords(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect BSL keywords not written in canonical title-case form."""
        if path_is_likely_form_module_bsl(path):
            return []
        diags: list[Diagnostic] = []
        # Cache rule-enabled flag to avoid O(n) set lookups inside the hot loop.
        _bsl036 = self._rule_enabled("BSL036")

        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            if _bsl036 and self._line_triggers_bsl036(lines, idx):
                continue
            if _bsl036 and self._line_in_triggered_bsl036_condition(lines, idx):
                continue
            # Remove string literals
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]

            for m in self._CANONICAL_RE.finditer(clean):
                word = m.group()
                canonical = self._CANONICAL_KEYWORDS.get(word.lower())
                if canonical and word != canonical:
                    # BSLLS does not flag ALL-CAPS keywords (e.g. ИЛИ, НЕ, ЕСЛИ).
                    # All-caps is an intentional style used for boolean operators
                    # in multi-line expressions and is not considered an error.
                    if word.upper() == word:
                        continue
                    diags.append(Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL153",
                        message=(
                            f"Ключевое слово «{word}» должно быть «{canonical}»"
                        ),
                    ))
        return diags

    # ------------------------------------------------------------------
    # BSL199 — IfElseIfEndsWithElse
    # ------------------------------------------------------------------

    def _rule_bsl199_if_else_if_ends_with_else(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """If/ElseIf chain must end with an Else branch."""
        diags: list[Diagnostic] = []
        _re_if = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE)
        _re_elseif = re.compile(r"^\s*(?:ИначеЕсли|ElseIf)\b", re.IGNORECASE)
        _re_else = re.compile(r"^\s*(?:Иначе|Else)\b(?!\s*(?:Если|If)\b)", re.IGNORECASE)
        _re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)

        i = 0
        while i < len(lines):
            if not _re_if.match(lines[i]):
                i += 1
                continue

            has_elseif = False
            has_else = False
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                bl = lines[j]
                if _re_if.match(bl):
                    depth += 1
                elif _re_endif.match(bl):
                    depth -= 1
                elif depth == 1:
                    if _re_elseif.match(bl):
                        has_elseif = True
                    elif _re_else.match(bl):
                        has_else = True
                j += 1

            if has_elseif and not has_else:
                # BSLLS attaches this diagnostic to the closing «КонецЕсли» line.
                endif_idx = j - 1
                if endif_idx >= 0 and endif_idx < len(lines):
                    el = lines[endif_idx]
                    diags.append(Diagnostic(
                        file=path,
                        line=endif_idx + 1,
                        character=0,
                        end_line=endif_idx + 1,
                        end_character=len(el),
                        severity=Severity.INFORMATION,
                        code="BSL199",
                        message=(
                            "Цепочка «Если/ИначеЕсли» не завершается веткой «Иначе» — "
                            "добавьте обработку неожиданных значений"
                        ),
                    ))
            i = j
        return diags

    # ------------------------------------------------------------------
    # BSL216 — MissingSpace
    # ------------------------------------------------------------------

    def _rule_bsl216_missing_space(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect missing spaces around assignment and comparison operators."""
        diags: list[Diagnostic] = []
        _re_comment = re.compile(r"^\s*//")
        # Pattern: identifier=expression without spaces (but not ==, :=, >=, <=, !=)
        _re_no_space = re.compile(
            r"(?<=[а-яёА-ЯЁa-zA-Z0-9_\)])=(?!=)(?=[а-яёА-ЯЁa-zA-Z0-9_\"'(])"
            r"|(?<=[а-яёА-ЯЁa-zA-Z0-9_\)])(?<![<>!])=(?!=)|"
            r"(?<![<>=!])=(?!=)(?=[а-яёА-ЯЁa-zA-Z])",
            re.UNICODE,
        )
        # Simpler: detect Var=Value without spaces (assignment without space)
        _re_assign_nospace = re.compile(
            r"\b(\w+)=(\w)",
            re.UNICODE,
        )

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            # Skip procedure/function headers
            if re.match(r"^\s*(?:Процедура|Функция|Procedure|Function)\b", clean, re.IGNORECASE):
                continue
            m = _re_assign_nospace.search(clean)
            if m:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.INFORMATION,
                    code="BSL216",
                    message=(
                        "Пропущен пробел вокруг оператора «=» — "
                        "добавьте пробелы для читаемости"
                    ),
                ))
                continue
            comma_col = _comma_missing_space_after_col_in_line(line.split("//", 1)[0])
            if comma_col is not None:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=comma_col,
                    end_line=idx + 1,
                    end_character=comma_col + 1,
                    severity=Severity.INFORMATION,
                    code="BSL216",
                    message=(
                        "Пропущен пробел после запятой — "
                        "добавьте пробел для читаемости"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL254 — TransferringParametersBetweenClientAndServer
    # ------------------------------------------------------------------

    def _rule_bsl254_transferring_parameters(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        BSLLS: параметры без ``Знач`` при вызовах клиент/сервер в общих командах.

        Ограничение: только серверные процедуры/функции (см. ``_procedure_compiler_execution_context``).
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if _procedure_compiler_execution_context(lines, proc) != "server":
                continue
            if not proc.params:
                continue
            missing_val = [p for p in proc.params if p and p not in proc.val_params]
            if not missing_val:
                continue
            header_line = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=proc.header_col,
                    end_line=proc.start_idx + 1,
                    end_character=len(header_line.rstrip()),
                    severity=Severity.INFORMATION,
                    code="BSL254",
                    message=(
                        "Установите модификатор «Знач» для параметров, передаваемых между клиентом и сервером "
                        f"({', '.join(missing_val)})"
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL255 — TryNumber
    # ------------------------------------------------------------------

    def _rule_bsl255_try_number(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect Число()/Number() conversions inside Try/Except blocks."""
        diags: list[Diagnostic] = []
        _re_try = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_endtry = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
        _re_except = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
        _re_number = re.compile(r"\b(?:Число|Number)\s*\(", re.IGNORECASE)

        in_try_body = False
        for idx, line in enumerate(lines):
            if _re_try.match(line):
                in_try_body = True
            elif _re_except.match(line) or _re_endtry.match(line):
                in_try_body = False

            if in_try_body:
                m = _re_number.search(line)
                if m:
                    diags.append(Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL255",
                        message=(
                            "«Число()» внутри блока «Попытка» — "
                            "используйте проверку перед конвертацией"
                        ),
                    ))
        return diags

    # ------------------------------------------------------------------
    # BSL183 — ExecuteExternalCode
    # ------------------------------------------------------------------

    def _rule_bsl183_execute_external_code(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect Выполнить()/Execute() with non-literal arguments."""
        diags: list[Diagnostic] = []
        # Выполнить("literal") is less dangerous; Выполнить(var) is suspicious
        _re_exec = re.compile(
            r"(?<![.\w])(?:Выполнить|Execute)\s*\((.{0,80})\)",
            re.IGNORECASE | re.UNICODE,
        )
        _re_literal = re.compile(r'^\s*"[^"]*"\s*$')
        _re_comment = re.compile(r"^\s*//")

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            for m in _re_exec.finditer(line):
                arg = m.group(1).strip()
                if not _re_literal.match(arg):  # non-literal argument
                    diags.append(Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL183",
                        message=(
                            "«Выполнить()» с динамическим аргументом — "
                            "потенциальная угроза безопасности"
                        ),
                    ))
        return diags

    # ------------------------------------------------------------------
    # BSL208 — LatinAndCyrillicSymbolInWord
    # BSL256 — Typo (homoglyph Cyrillic in Latin-looking identifier; BSLLS priority)
    # ------------------------------------------------------------------

    def _rule_bsl208_bsl256_latin_cyrillic_and_typo(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """
        Mixed Latin/Cyrillic identifiers: BSLLS often reports **Typo** (BSL256) when
        Cyrillic letters are Latin homoglyphs in an otherwise Latin name; intentional
        mixed-script names get **LatinAndCyrillicSymbolInWord** (BSL208).
        """
        diags: list[Diagnostic] = []
        _re_word = re.compile(r"\b[a-zA-ZА-ЯЁа-яё_][a-zA-ZА-ЯЁа-яё0-9_]*\b", re.UNICODE)
        _re_has_latin = re.compile(r"[a-zA-Z]")
        _re_has_cyrillic = re.compile(r"[А-ЯЁа-яё]")
        _re_comment = re.compile(r"^\s*//")
        # Emit at most once per unique identifier per file (BSL LS behaviour)
        seen_bsl208: set[str] = set()
        seen_bsl256: set[str] = set()

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            for m in _re_word.finditer(clean):
                word = m.group()
                # Skip well-known 1C platform names where Latin substrings are
                # all recognised technology acronyms (e.g. HTTPЗапрос, JSONЗапись).
                if _bsl208_word_is_standard_tech_name(word):
                    continue
                if not (
                    _re_has_latin.search(word) and _re_has_cyrillic.search(word)
                ):
                    continue
                if _mixed_script_identifier_is_homoglyph_typo(word):
                    if self._rule_enabled("BSL256") and word not in seen_bsl256:
                        seen_bsl256.add(word)
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=m.start(),
                                end_line=idx + 1,
                                end_character=m.end(),
                                severity=Severity.INFORMATION,
                                code="BSL256",
                                message=(
                                    f"В идентификаторе «{word}» буквы, похожие на латиницу "
                                    "(возможная опечатка — смешение алфавитов)"
                                ),
                            )
                        )
                elif self._rule_enabled("BSL208") and word not in seen_bsl208:
                    seen_bsl208.add(word)
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=m.start(),
                            end_line=idx + 1,
                            end_character=m.end(),
                            severity=Severity.WARNING,
                            code="BSL208",
                            message=(
                                f"Идентификатор «{word}» содержит кириллицу и латиницу "
                                "одновременно — визуально неотличимо от другого имени"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL230 — PairingBrokenTransaction
    # ------------------------------------------------------------------

    def _rule_bsl230_pairing_broken_transaction(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """Detect unbalanced Begin/Commit/Rollback transaction calls."""
        diags: list[Diagnostic] = []
        _re_begin = re.compile(r"\b(?:НачатьТранзакцию|BeginTransaction)\s*\(", re.IGNORECASE)
        _re_commit = re.compile(r"\b(?:ЗафиксироватьТранзакцию|CommitTransaction)\s*\(", re.IGNORECASE)
        _re_rollback = re.compile(r"\b(?:ОтменитьТранзакцию|RollbackTransaction)\s*\(", re.IGNORECASE)
        _re_comment = re.compile(r"^\s*//")

        for proc in procs:
            begin_count = 0
            commit_count = 0
            rollback_count = 0
            begin_line = None

            for li in range(proc.start_idx, proc.end_idx):
                if li >= len(lines):
                    break
                line = lines[li]
                if _re_comment.match(line):
                    continue
                if _re_begin.search(line):
                    begin_count += 1
                    if begin_line is None:
                        begin_line = li
                if _re_commit.search(line):
                    commit_count += 1
                if _re_rollback.search(line):
                    rollback_count += 1

            if begin_count > 0 and commit_count == 0 and rollback_count == 0:
                diags.append(Diagnostic(
                    file=path,
                    line=(begin_line or proc.start_idx) + 1,
                    character=0,
                    end_line=(begin_line or proc.start_idx) + 1,
                    end_character=len(lines[begin_line or proc.start_idx]),
                    severity=Severity.ERROR,
                    code="BSL230",
                    message=(
                        "НачатьТранзакцию() без соответствующего "
                        "ЗафиксироватьТранзакцию() или ОтменитьТранзакцию()"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL240 — RewriteMethodParameter
    # ------------------------------------------------------------------

    def _rule_bsl240_rewrite_method_parameter(
        self,
        path: str,
        lines: list[str],
        procs: list[Any],
        tree: Any,
        proc_node_map: dict[tuple[str, int, str], Any] | None = None,
    ) -> list[Diagnostic]:
        """Detect parameter overwritten before being read."""
        # BSLLS does not run RewriteMethodParameter on form modules — form event
        # handlers often intentionally write to parameters (e.g. output params).
        if path_is_likely_form_module_bsl(path):
            return []
        diags: list[Diagnostic] = []
        # Pre-check tree validity once — avoids O(P × T) repeated full-tree walks.
        _tree_ok = _ts_tree_ok_for_rules(tree)

        for proc in procs:
            header_line = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
            param_names: set[str] = set()
            proc_params = getattr(proc, "params", None)
            if proc_params:
                param_names = {n.casefold() for n in proc_params if n}
            else:
                hm = _RE_BSL240_PARAM_HEADER.match(header_line)
                if not hm:
                    continue
                raw_params = hm.group(1)
                for part in split_commas_outside_double_quotes(raw_params):
                    part = part.strip()
                    part = _RE_BSL240_ZNACH.sub("", part)
                    name = part.split("=")[0].strip()
                    if name:
                        param_names.add(name.casefold())

            if not param_names:
                continue

            body_start = proc.start_idx + 1
            if _tree_ok:
                key = (proc.name, proc.start_idx, getattr(proc, "kind", "procedure"))
                pnode = (
                    proc_node_map.get(key)
                    if proc_node_map is not None
                    else _find_proc_definition_node(tree, proc)
                )
                if pnode is not None:
                    bl = _ts_first_body_statement_line_idx(pnode)
                    if bl is not None:
                        body_start = bl
                    else:
                        body_start = _proc_body_start_line_idx_fallback(lines, proc)
                else:
                    body_start = _proc_body_start_line_idx_fallback(lines, proc)
            else:
                body_start = _proc_body_start_line_idx_fallback(lines, proc)

            if body_start >= proc.end_idx:
                continue

            # Знач (by-value) parameters are local copies — reassigning is fine.
            val_cf = {n.casefold() for n in (getattr(proc, "val_params", None) or [])}
            # Optional parameters (with default values) are often intentionally used
            # as output parameters in 1C — skip them (BSLLS parity).
            opt_cf = {n.casefold() for n in (getattr(proc, "optional_params", None) or [])}

            # Find params reassigned before use in first non-blank body lines
            for li in range(body_start, min(body_start + 15, proc.end_idx)):
                if li >= len(lines):
                    break
                line = lines[li]
                if _RE_LINE_COMMENT.match(line) or not line.strip():
                    continue
                am = _RE_BSL240_ASSIGN.match(line)
                if am:
                    lhs = am.group(1).casefold()
                    if (lhs in param_names
                            and lhs not in val_cf
                            and lhs not in opt_cf
                            and lhs not in _BSL062_SKIP_STANDARD_COMMAND_PARAMS):
                        # Check the RHS doesn't mention the param itself
                        rhs = line[am.end():].strip()
                        if lhs not in rhs.casefold():
                            diags.append(Diagnostic(
                                file=path,
                                line=li + 1,
                                character=am.start(),
                                end_line=li + 1,
                                end_character=am.end(),
                                severity=Severity.WARNING,
                                code="BSL240",
                                message=(
                                    f"Параметр «{am.group(1)}» перезаписывается "
                                    "до первого использования — вероятно ошибка"
                                ),
                            ))
                            param_names.discard(lhs)
        return diags

    # ------------------------------------------------------------------
    # BSL263 — UseLessForEach
    # ------------------------------------------------------------------

    def _rule_bsl263_useless_for_each(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """Detect For Each loops where the iteration variable is never used in the body."""
        diags: list[Diagnostic] = []
        _re_foreach = re.compile(
            r"^\s*(?:Для\s+Каждого|For\s+Each)\s+(\w+)\s+(?:Из|In)\b",
            re.IGNORECASE | re.UNICODE,
        )
        _re_end_loop = re.compile(r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE)
        _re_comment = re.compile(r"^\s*//")

        i = 0
        while i < len(lines):
            m = _re_foreach.match(lines[i])
            if m:
                iter_var = m.group(1).casefold()
                body_lines: list[str] = []
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    bl = lines[j]
                    if _re_foreach.match(bl):
                        depth += 1
                    elif _re_end_loop.match(bl):
                        depth -= 1
                    if depth >= 1:
                        body_lines.append(bl)
                    j += 1

                # Check if iter_var is used in body
                var_used = False
                for bl in body_lines:
                    if _re_comment.match(bl):
                        continue
                    clean = re.sub(r'"[^"]*"', '""', bl)
                    if re.search(r'\b' + re.escape(iter_var) + r'\b', clean, re.IGNORECASE):
                        var_used = True
                        break

                if not var_used and body_lines:
                    diags.append(Diagnostic(
                        file=path,
                        line=i + 1,
                        character=0,
                        end_line=i + 1,
                        end_character=len(lines[i]),
                        severity=Severity.WARNING,
                        code="BSL263",
                        message=(
                            f"Переменная «{m.group(1)}» в «Для Каждого» "
                            "нигде не используется в теле цикла"
                        ),
                    ))
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL265 — UselessTernaryOperator
    # ------------------------------------------------------------------

    def _rule_bsl265_useless_ternary_operator(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect ?(cond, Истина, Ложь) or ?(cond, Ложь, Истина) — return condition directly."""
        diags: list[Diagnostic] = []
        # ?(cond, Истина, Ложь) → return cond; ?(cond, Ложь, Истина) → return НЕ cond
        _re_ternary = re.compile(
            r"\?\s*\([^,]+,\s*(?:Истина|True|Ложь|False)\s*,\s*(?:Истина|True|Ложь|False)\s*\)",
            re.IGNORECASE | re.UNICODE,
        )
        _re_comment = re.compile(r"^\s*//")

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            m = _re_ternary.search(line)
            if m:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.WARNING,
                    code="BSL265",
                    message=(
                        "Тернарный оператор возвращает Истина/Ложь — "
                        "замените на само условие"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL257 — UnaryPlusInConcatenation
    # ------------------------------------------------------------------

    def _rule_bsl257_unary_plus_in_concatenation(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect unary + used as concatenation operator (likely a mistake)."""
        diags: list[Diagnostic] = []
        # Pattern: string literal or identifier followed by +identifier (no spaces make it look unary)
        # The typical mistake: "Text" +Переменная  or  Str + +Value
        _re_unary = re.compile(
            r'(?:"[^"]*"|\'[^\']*\'|\b\w+\b)\s*\+\s*\+',
            re.UNICODE,
        )
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            # Remove string literals before checking to avoid false positives
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            m = _re_unary.search(clean)
            if m:
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.WARNING,
                    code="BSL257",
                    message=(
                        "Унарный «+» перед значением при конкатенации — "
                        "вероятно опечатка"
                    ),
                ))
        return diags

    # ------------------------------------------------------------------
    # BSL279 — YoLetterUsage
    # ------------------------------------------------------------------

    def _rule_bsl279_yo_letter_usage(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect use of letter «ё» in identifiers (BSL convention: use «е»)."""
        diags: list[Diagnostic] = []
        _re_yo = re.compile(r"[ёЁ]", re.UNICODE)
        _re_comment = re.compile(r"^\s*//")
        # Pattern to match identifiers (words) containing ё
        _re_id_yo = re.compile(r"\b\w*[ёЁ]\w*\b", re.UNICODE)

        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            # Remove string literals
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            # Remove inline comments
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            for m in _re_id_yo.finditer(clean):
                diags.append(Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.INFORMATION,
                    code="BSL279",
                    message=(
                        f"Идентификатор «{m.group()}» содержит букву «ё» — "
                        "используйте «е» для совместимости"
                    ),
                ))
        return diags


# ---------------------------------------------------------------------------
# Inline suppression helpers
# ---------------------------------------------------------------------------

# Type alias: maps 1-based line → suppressed codes (empty set = all codes)
_Suppressions = dict[int, set[str]]


_BSLLS_OFF_FLAGS = frozenset({"off", "выкл"})


def _parse_suppressions(lines: list[str]) -> _Suppressions:
    """
    Scan source lines for inline and block suppression comments.

    Supported forms (case-insensitive):

    Line-level (suppress only the annotated line)::

        // noqa                    — suppress all rules on this line
        // noqa: BSL001, BSL002    — suppress specific rules
        // bsl-disable: BSL001     — onec-hbk-bsl style

    Block-level BSLLS (compatible with 1c-syntax/bsl-language-server)::

        // BSLLS-off               — disable ALL rules from this line onward
        // BSLLS-on                — re-enable all rules
        // BSLLS:CognitiveComplexity-off   — disable specific rule from this line
        // BSLLS:CognitiveComplexity-on    — re-enable specific rule
        // BSLLS:MethodSize-выкл   — Russian flags also accepted
        // BSLLS:MethodSize-вкл

    Block suppression affects the comment line itself AND all subsequent lines
    until the matching ``-on`` / ``-вкл`` comment.  Multiple rules can be
    independently nested and toggled.

    Returns a dict mapping 1-based line numbers to a set of suppressed codes.
    An empty set means "suppress ALL rules on that line".
    """
    result: _Suppressions = {}

    # Block-level BSLLS state tracked across lines
    block_all: bool = False       # BSLLS-off (no specific rule) is active
    block_codes: set[str] = set() # specific BSL codes currently block-suppressed

    for idx, line in enumerate(lines):
        line_no = idx + 1

        # ── Step 1: update block state from BSLLS comments ───────────────
        # Changes take effect ON the line where the comment appears.
        for bm in _RE_BSLLS.finditer(line):
            name = bm.group("name")
            is_off = bm.group("flag").lower() in _BSLLS_OFF_FLAGS

            if name is None:
                # // BSLLS-off / // BSLLS-on  — affects all rules
                if is_off:
                    block_all = True
                    block_codes.clear()  # individual tracking subsumed
                else:
                    block_all = False
                    block_codes.clear()
            else:
                # // BSLLS:RuleName-off/on
                bsl_code = _BSLLS_NAME_TO_CODE.get(name)
                if bsl_code:
                    if is_off:
                        block_codes.add(bsl_code)
                    else:
                        block_codes.discard(bsl_code)
                # Names not in the mapping are silently ignored

        # ── Step 2: collect line-level noqa/bsl-disable comment ──────────
        noqa_all = False
        noqa_codes: set[str] = set()
        m = _RE_NOQA.search(line)
        if m is not None:
            codes_str = m.group("codes")
            if codes_str:
                noqa_codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
            else:
                noqa_all = True

        # ── Step 3: merge into result for this line ───────────────────────
        if block_all or noqa_all:
            result[line_no] = set()  # suppress ALL
        elif block_codes or noqa_codes:
            result[line_no] = set(block_codes) | noqa_codes

    return result


def _is_suppressed(diag: Diagnostic, suppressed: _Suppressions) -> bool:
    """Return True if *diag* is covered by an inline suppression."""
    codes = suppressed.get(diag.line)
    if codes is None:
        return False
    return len(codes) == 0 or diag.code.upper() in codes
