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

import functools
import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis import bslls_typo
from onec_hbk_bsl.analysis.bsl_string_regions import (
    diagnostic_overlaps_string_literal,
    double_quoted_string_ranges,
    line_start_offsets,
)
from onec_hbk_bsl.analysis.bsl_string_split import (
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.bslls_parity import merge_profile_with_select
from onec_hbk_bsl.analysis.diagnostics_bsl148 import bsl148_function_name_spans
from onec_hbk_bsl.analysis.diagnostics_bsl152 import bsl152_public_region_name_spans
from onec_hbk_bsl.analysis.diagnostics_bsl154 import bsl154_code_after_async_spans
from onec_hbk_bsl.analysis.diagnostics_bsl155 import bsl155_code_block_before_sub
from onec_hbk_bsl.analysis.diagnostics_bsl156 import bsl156_diagnostics
from onec_hbk_bsl.analysis.diagnostics_common_module import (
    bsl158_common_module_assign_spans,
    bsl160_common_module_missing_api,
    bsl160_module_line1_span,
    common_module_name_convention_issues,
    common_module_xml_flags_invalid,
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
from onec_hbk_bsl.analysis.document_snapshot import QueryTextBlockInfo, build_document_snapshot
from onec_hbk_bsl.analysis.formatter_structural import tree_has_errors
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character
from onec_hbk_bsl.analysis.passes.metadata_pass import (
    extend_metadata_rule_tasks,
)
from onec_hbk_bsl.analysis.passes.method_pass import (
    extend_method_contract_rule_tasks,
)
from onec_hbk_bsl.analysis.passes.query_pass import (
    extend_query_join_rule_tasks,
    extend_query_metadata_rule_tasks,
    extend_query_text_rule_tasks,
    extend_query_top_rule_tasks,
)
from onec_hbk_bsl.analysis.passes.security_pass import (
    extend_security_rule_tasks,
)
from onec_hbk_bsl.analysis.passes.style_pass import (
    extend_style_comment_rule_tasks,
    extend_style_spacing_rule_tasks,
    extend_style_tail_rule_tasks,
    extend_style_token_rule_tasks,
)
from onec_hbk_bsl.indexer.metadata_parser import crawl_config
from onec_hbk_bsl.indexer.metadata_registry import FOLDER_TO_KIND
from onec_hbk_bsl.parser.bsl_parser import BslParser

# When a diagnostic span overlaps a "..." literal, drop the warning unless the rule
# is meant to inspect string contents (secrets, duplicates, concat, magic numbers, …).
_CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL: frozenset[str] = frozenset(
    {
        # Line-length spans the whole line; overlap with trailing string literals must not drop the rule.
        "BSL014",
        # Method-signature rules span the whole signature line which may contain default-value strings.
        "BSL015",
        "BSL031",
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
        "BSL221",
        "BSL222",
        "BSL110",
        "BSL119",
        "BSL132",
        "BSL142",
        "BSL145",
        "BSL148",
        "BSL171",
        "BSL179",
        "BSL253",
        "BSL260",
        # BSLLS Typo checks string literal contents.
        "BSL256",
        # Query-text rules fire on continuation lines (|...) inside string literals.
        "BSL149",
        "BSL206",
        "BSL207",
        "BSL209",
        "BSL210",
        "BSL220",
        "BSL191",
        "BSL187",
        "BSL201",
        "BSL236",
        "BSL238",
        "BSL269",
        "BSL273",
        "BSL234",
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
        "name": "DeprecatedMessage",
        "description": "Сообщить()/Message() is deprecated and should be replaced with structured UX or logging",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": True,
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
        "description": "More than one consecutive blank line reduces readability (BSLLS-style)",
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
        "description": "TOP/ПЕРВЫЕ is used in query text without ORDER BY/УПОРЯДОЧИТЬ",
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
        "name": "DuplicateRegion",
        "description": "A region name is duplicated within the same module",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style"],
        "implemented": True,
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
        "implemented": True,
    },
    "BSL149": {
        "name": "AssignAliasFieldsInQuery",
        "description": "Query fields should be assigned aliases for clarity",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "query"],
        "implemented": True,
    },
    "BSL150": {
        "name": "BadWords",
        "description": "Inappropriate or forbidden words found in source code",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["convention"],
        "implemented": True,
    },
    "BSL151": {
        "name": "BeginTransactionBeforeTryCatch",
        "description": "НачатьТранзакцию/BeginTransaction must be placed immediately before a Try/Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL152": {
        "name": "CachedPublic",
        "description": "Export method in a cached common module — caching and export conflict",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "performance"],
        "implemented": True,
    },
    "BSL153": {
        "name": "CanonicalSpellingKeywords",
        "description": "BSL keyword is not written in canonical (title-case) form",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "style"],
        "implemented": True,
    },
    "BSL154": {
        "name": "CodeAfterAsyncCall",
        "description": "Executable code follows an asynchronous call — result may be lost",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["async", "correctness"],
        "implemented": True,
    },
    "BSL155": {
        "name": "CodeBlockBeforeSub",
        "description": "Executable code appears before procedure/function definitions (module body)",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "design"],
        "implemented": True,
    },
    "BSL156": {
        "name": "CodeOutOfRegion",
        "description": "Code is located outside any #Region/#Область block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["convention", "structure"],
        "implemented": True,
    },
    "BSL157": {
        "name": "CommitTransactionOutsideTryCatch",
        "description": "ЗафиксироватьТранзакцию/CommitTransaction must be inside a Try/Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL158": {
        "name": "CommonModuleAssign",
        "description": "Common module object is assigned a value — this is always an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "module"],
        "implemented": True,
    },
    "BSL159": {
        "name": "CommonModuleInvalidType",
        "description": "Common module has incompatible type flags (e.g. Global + Privileged)",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["design", "module"],
        "implemented": True,
    },
    "BSL160": {
        "name": "CommonModuleMissingAPI",
        "description": "Common module has no exported methods — consider making it non-public",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "module", "api"],
        "implemented": True,
    },
    "BSL161": {
        "name": "CommonModuleNameCached",
        "description": "Cached common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL162": {
        "name": "CommonModuleNameClient",
        "description": "Client common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL163": {
        "name": "CommonModuleNameClientServer",
        "description": "Client-server common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL164": {
        "name": "CommonModuleNameFullAccess",
        "description": "Full-access (privileged) common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL165": {
        "name": "CommonModuleNameGlobal",
        "description": "Global common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL166": {
        "name": "CommonModuleNameGlobalClient",
        "description": "Global client common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL167": {
        "name": "CommonModuleNameServerCall",
        "description": "Server-call common module name does not match naming convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL168": {
        "name": "CommonModuleNameWords",
        "description": "Common module name uses forbidden words",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL169": {
        "name": "CompilationDirectiveLost",
        "description": "Compilation directive on the method is missing or differs from calling context",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL170": {
        "name": "CompilationDirectiveNeedLess",
        "description": "Redundant compilation directive on the method",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "directive"],
        "implemented": True,
    },
    "BSL171": {
        "name": "CrazyMultilineString",
        "description": "Multiline string literal uses inconsistent indentation",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "readability"],
        "implemented": True,
    },
    "BSL172": {
        "name": "DataExchangeLoading",
        "description": "Modification handlers do not check ОбменДаннымиЗагрузка/DataExchangeLoad flag",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "data-exchange"],
        "implemented": True,
    },
    "BSL173": {
        "name": "DeletingCollectionItem",
        "description": "Collection item is deleted inside a Для Каждого/For Each loop — may cause errors",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "loop"],
        "implemented": True,
    },
    "BSL174": {
        "name": "DenyIncompleteValues",
        "description": "НачатьТранзакцию used without ОтменитьТранзакцию in error path",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL175": {
        "name": "DeprecatedAttributes8312",
        "description": "Deprecated platform attribute used (removed in 8.3.12+)",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL176": {
        "name": "DeprecatedMethodCall",
        "description": "Deprecated platform method called — use the modern replacement",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated"],
        "implemented": True,
    },
    "BSL177": {
        "name": "DeprecatedMethods8310",
        "description": "Platform method deprecated since 8.3.10",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL178": {
        "name": "DeprecatedMethods8317",
        "description": "Platform method deprecated since 8.3.17",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL179": {
        "name": "DeprecatedTypeManagedForm",
        "description": "Deprecated type УправляемаяФорма/ManagedForm used directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL180": {
        "name": "DisableSafeMode",
        "description": "УстановитьБезопасныйРежим(Ложь)/SetSafeMode(False) disables security sandbox",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL181": {
        "name": "DuplicatedInsertionIntoCollection",
        "description": "The same element is inserted into the collection more than once",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL182": {
        "name": "ExcessiveAutoTestCheck",
        "description": "АвтоТестПроверка check is excessive or incorrectly placed",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["testing"],
        "implemented": True,
    },
    "BSL183": {
        "name": "ExecuteExternalCode",
        "description": "Выполнить()/Execute() runs arbitrary external code — security risk",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL184": {
        "name": "ExecuteExternalCodeInCommonModule",
        "description": "Dynamic code execution (Выполнить/Execute) inside a common module",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security", "module"],
        "implemented": True,
    },
    "BSL185": {
        "name": "ExternalAppStarting",
        "description": "ЗапуститьПриложение()/StartApplication() launches external processes",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL186": {
        "name": "ExtraCommas",
        "description": "Trailing or extra comma in method call or declaration",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["syntax", "style"],
        "implemented": True,
    },
    "BSL187": {
        "name": "FieldsFromJoinsWithoutIsNull",
        "description": "Fields from outer joins used without ЕСТЬ NULL/IS NULL check",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL188": {
        "name": "FileSystemAccess",
        "description": "Direct file system access — may fail in web client or thin client contexts",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "compatibility"],
        "implemented": True,
    },
    "BSL189": {
        "name": "ForbiddenMetadataName",
        "description": "Metadata object name is in the list of forbidden names",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL190": {
        "name": "FormDataToValue",
        "description": "ДанныеФормыВЗначение()/FormDataToValue() is slow — prefer working with server objects directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "ui"],
        "implemented": True,
    },
    "BSL191": {
        "name": "FullOuterJoinQuery",
        "description": "Full outer join (ПОЛНОЕ ВНЕШНЕЕ/FULL OUTER JOIN) in query — usually a design mistake",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "design"],
        "implemented": True,
    },
    "BSL192": {
        "name": "FunctionNameStartsWithGet",
        "description": "Function name should start with 'Получить'/'Get' to indicate it returns a value",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL193": {
        "name": "FunctionOutParameter",
        "description": "Function modifies a reference parameter (out-parameter) — use a Procedure instead",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design"],
        "implemented": True,
    },
    "BSL194": {
        "name": "FunctionReturnsSamePrimitive",
        "description": "Function always returns the same primitive value — it may be simplified",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "design"],
        "implemented": True,
    },
    "BSL195": {
        "name": "GetFormMethod",
        "description": "ПолучитьФорму()/GetForm() usage is deprecated — open forms via OpenForm()",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL196": {
        "name": "GlobalContextMethodCollision8312",
        "description": "Method name collides with a global context method added in 8.3.12",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "compatibility"],
        "implemented": True,
    },
    "BSL197": {
        "name": "IfElseDuplicatedCodeBlock",
        "description": "Identical code block appears in multiple branches of If/ElseIf",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "duplicate"],
        "implemented": True,
    },
    "BSL198": {
        "name": "IfElseDuplicatedCondition",
        "description": "Duplicate condition in If/ElseIf chain — branch is unreachable",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
        "implemented": True,
    },
    "BSL199": {
        "name": "IfElseIfEndsWithElse",
        "description": "If/ElseIf chain does not end with an Else branch",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "robustness"],
        "implemented": True,
    },
    "BSL200": {
        "name": "IncorrectLineBreak",
        "description": "Line break character used incorrectly or inconsistently",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL201": {
        "name": "IncorrectUseLikeInQuery",
        "description": "ПОДОБНО/LIKE pattern in query is written incorrectly",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL202": {
        "name": "IncorrectUseOfStrTemplate",
        "description": "СтрШаблон()/StrTemplate() is called with mismatched argument count",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness"],
        "implemented": True,
    },
    "BSL203": {
        "name": "InternetAccess",
        "description": "Direct internet access — should be isolated or proxied for security",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL204": {
        "name": "InvalidCharacterInFile",
        "description": "File contains invalid or non-printable characters",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "encoding"],
        "implemented": True,
    },
    "BSL205": {
        "name": "IsInRoleMethod",
        "description": "РольДоступна()/IsInRole() is used — prefer permission-based access control",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL206": {
        "name": "JoinWithSubQuery",
        "description": "Query join uses a subquery — may cause poor performance",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL207": {
        "name": "JoinWithVirtualTable",
        "description": "Query join with a virtual table without parameters — may return too many rows",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL208": {
        "name": "LatinAndCyrillicSymbolInWord",
        "description": "Identifier contains both Latin and Cyrillic characters — visually ambiguous",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "naming"],
        "implemented": True,
    },
    "BSL209": {
        "name": "LogicalOrInJoinQuerySection",
        "description": "Logical OR (ИЛИ/OR) in JOIN ON condition — causes performance issues",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL210": {
        "name": "LogicalOrInTheWhereSectionOfQuery",
        "description": "Logical OR (ИЛИ/OR) in WHERE clause may prevent index usage",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL211": {
        "name": "MetadataObjectNameLength",
        "description": "Metadata object name exceeds maximum allowed length",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL212": {
        "name": "MissedRequiredParameter",
        "description": "Required parameter is missing in method call",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness"],
        "implemented": True,
    },
    "BSL213": {
        "name": "MissingCommonModuleMethod",
        "description": "Called method does not exist in the referenced common module",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "module"],
        "implemented": True,
    },
    "BSL214": {
        "name": "MissingEventSubscriptionHandler",
        "description": "Event subscription references a handler method that does not exist",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "events"],
        "implemented": True,
    },
    "BSL215": {
        "name": "MissingParameterDescription",
        "description": "Export method parameter has no description in the comment block",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["documentation", "api"],
        "implemented": True,
    },
    "BSL216": {
        "name": "MissingSpace",
        "description": "Missing space before or after an operator or keyword",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL217": {
        "name": "MissingTempStorageDeletion",
        "description": "Temporary storage (УдалитьИзВременногоХранилища) is not deleted after use",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["resource-management", "memory"],
        "implemented": True,
    },
    "BSL218": {
        "name": "MissingTemporaryFileDeletion",
        "description": "Temporary file created with GetTempFileName is not deleted after use",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["resource-management"],
        "implemented": True,
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
        "implemented": True,
    },
    "BSL221": {
        "name": "MultilingualStringHasAllDeclaredLanguages",
        "description": "НСтр() string does not include all languages declared in the configuration",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["localization"],
        "implemented": True,
    },
    "BSL222": {
        "name": "MultilingualStringUsingWithTemplate",
        "description": "НСтр() is used inside СтрШаблон() — localized strings should be composed differently",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["localization", "style"],
        "implemented": True,
    },
    "BSL223": {
        "name": "NestedConstructorsInStructureDeclaration",
        "description": "Structure constructor contains nested constructors — hard to read and maintain",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["readability", "design"],
        "implemented": True,
    },
    "BSL224": {
        "name": "NestedFunctionInParameters",
        "description": "Function call is used as an argument to another function — reduces readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["readability", "brain-overload"],
        "implemented": True,
    },
    "BSL225": {
        "name": "NumberOfValuesInStructureConstructor",
        "description": "Структура/Structure constructor has too many initial values",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "readability"],
        "implemented": True,
    },
    "BSL226": {
        "name": "OSUsersMethod",
        "description": "ПользователиОС()/OSUsers() is used — OS user enumeration is a security concern",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL227": {
        "name": "OneStatementPerLine",
        "description": "Multiple statements on one line — reduces readability",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL228": {
        "name": "OrderOfParams",
        "description": "Method parameter order does not follow the agreed convention",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "convention"],
        "implemented": True,
    },
    "BSL229": {
        "name": "OrdinaryAppSupport",
        "description": "Code uses API not supported in Ordinary (thick) application mode",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["compatibility", "ui"],
        "implemented": True,
    },
    "BSL230": {
        "name": "PairingBrokenTransaction",
        "description": "НачатьТранзакцию/ЗафиксироватьТранзакцию/ОтменитьТранзакцию calls are unbalanced",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "correctness"],
        "implemented": True,
    },
    "BSL231": {
        "name": "PrivilegedModuleMethodCall",
        "description": "Method from a privileged module is called from a non-privileged context",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL232": {
        "name": "ProtectedModule",
        "description": "Module is protected (ЗащищенныйМодуль) — source is not accessible",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design"],
        "implemented": True,
    },
    "BSL233": {
        "name": "PublicMethodsDescription",
        "description": "Exported method has no documentation comment",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["documentation", "api"],
        "implemented": True,
    },
    "BSL234": {
        "name": "QueryNestedFieldsByDot",
        "description": "Nested (dot-notation) field access in query text — causes implicit joins",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL235": {
        "name": "QueryParseError",
        "description": "Embedded query text has a syntax error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL236": {
        "name": "QueryToMissingMetadata",
        "description": "Query references a metadata object that does not exist in the configuration",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL237": {
        "name": "RedundantAccessToObject",
        "description": "Redundant object access — intermediate result is not used",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "performance"],
        "implemented": True,
    },
    "BSL238": {
        "name": "RefOveruse",
        "description": "Excessive use of .Ссылка/.Ref — retrieve the object once and reuse",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["performance", "readability"],
        "implemented": True,
    },
    "BSL239": {
        "name": "ReservedParameterNames",
        "description": "Parameter name shadows a built-in platform identifier",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "suspicious"],
        "implemented": True,
    },
    "BSL240": {
        "name": "RewriteMethodParameter",
        "description": "Method parameter is overwritten before being read — likely a mistake",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["suspicious", "correctness"],
        "implemented": True,
    },
    "BSL241": {
        "name": "SameMetadataObjectAndChildNames",
        "description": "Metadata object and its child (attribute/tabular section) share the same name",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["naming", "design"],
        "implemented": True,
    },
    "BSL242": {
        "name": "ScheduledJobHandler",
        "description": "Scheduled job handler method has incorrect signature or is missing",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "scheduled-jobs"],
        "implemented": True,
    },
    "BSL243": {
        "name": "SelfInsertion",
        "description": "Object is inserted into itself — causes infinite recursion or error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL244": {
        "name": "ServerCallsInFormEvents",
        "description": "Server call inside a client form event handler without &НаКлиентеНаСервере",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "ui", "performance"],
        "implemented": True,
    },
    "BSL245": {
        "name": "ServerSideExportFormMethod",
        "description": "Form module export method is marked &НаСервере — inaccessible from client",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "ui"],
        "implemented": True,
    },
    "BSL246": {
        "name": "SetPermissionsForNewObjects",
        "description": "НастройкаПравДоступаДляНовыхОбъектов is called incorrectly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL247": {
        "name": "SetPrivilegedMode",
        "description": "УстановитьПривилегированныйРежим(Истина)/SetPrivilegedMode(True) elevates permissions",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL248": {
        "name": "SeveralCompilerDirectives",
        "description": "Method has multiple conflicting compilation directives",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL249": {
        "name": "StyleElementConstructors",
        "description": "Style element is created with a constructor instead of using built-in styles",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["ui", "design"],
        "implemented": True,
    },
    "BSL250": {
        "name": "TempFilesDir",
        "description": "КаталогВременныхФайлов()/TempFilesDir() used — may cause issues in web context",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security", "compatibility"],
        "implemented": True,
    },
    "BSL251": {
        "name": "TernaryOperatorUsage",
        "description": "Ternary operator (?(cond, true, false)) reduces readability — consider If/Else",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "readability"],
        "implemented": True,
    },
    "BSL252": {
        "name": "ThisObjectAssign",
        "description": "ЭтотОбъект/ThisObject is assigned a value — always an error",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL253": {
        "name": "TimeoutsInExternalResources",
        "description": "External resource access has no timeout set — may hang indefinitely",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["robustness", "performance"],
        "implemented": True,
    },
    "BSL254": {
        "name": "TransferringParametersBetweenClientAndServer",
        "description": "Large or non-serializable object is passed between client and server",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "design"],
        "implemented": True,
    },
    "BSL255": {
        "name": "TryNumber",
        "description": "Numeric conversion inside Попытка/Try — exception obscures conversion errors",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["error-handling", "suspicious"],
        "implemented": True,
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
        "implemented": True,
    },
    "BSL258": {
        "name": "UnionAll",
        "description": "ОБЪЕДИНИТЬ/UNION without ALL causes implicit deduplication — use UNION ALL",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL259": {
        "name": "UnknownPreprocessorSymbol",
        "description": "Unknown preprocessor symbol used in #Если/#If directive",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL260": {
        "name": "UnsafeFindByCode",
        "description": "НайтиПоКоду()/FindByCode() is called without existence check — may return Undefined",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "robustness"],
        "implemented": True,
    },
    "BSL261": {
        "name": "UnsafeSafeModeMethodCall",
        "description": "Safe-mode method called in a context where it may not be available",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["security", "correctness"],
        "implemented": True,
    },
    "BSL262": {
        "name": "UsageWriteLogEvent",
        "description": "ЗаписьЖурналаРегистрации/WriteLogEvent called with incorrect parameters",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MINOR",
        "tags": ["correctness", "logging"],
        "implemented": True,
    },
    "BSL263": {
        "name": "UseLessForEach",
        "description": "Для Каждого/For Each loop body does nothing useful with the iteration variable",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["redundant", "suspicious"],
        "implemented": True,
    },
    "BSL264": {
        "name": "UseSystemInformation",
        "description": "СистемнаяИнформация()/SystemInformation() exposes sensitive system data",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL265": {
        "name": "UselessTernaryOperator",
        "description": "Ternary operator returns its condition directly — simplify to the condition",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "readability"],
        "implemented": True,
    },
    "BSL266": {
        "name": "UsingCancelParameter",
        "description": "Параметр «Отказ»/Cancel is modified but not checked correctly in the handler",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "events"],
        "implemented": True,
    },
    "BSL267": {
        "name": "UsingExternalCodeTools",
        "description": "External code execution tools (AddIn, COM, WSProxy) are used",
        "severity": "WARNING",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "MAJOR",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL268": {
        "name": "UsingFindElementByString",
        "description": "НайтиПоНаименованию()/FindByDescription() used — slow full-text search",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance"],
        "implemented": True,
    },
    "BSL269": {
        "name": "UsingLikeInQuery",
        "description": "ПОДОБНО/LIKE operator in query — may prevent index usage and cause full scans",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL270": {
        "name": "UsingModalWindows",
        "description": "Modal window (Предупреждение, Вопрос, ВвестиЗначение) used in managed UI",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL271": {
        "name": "UsingObjectNotAvailableUnix",
        "description": "Object or method not available on Linux/Unix server",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["compatibility"],
        "implemented": True,
    },
    "BSL272": {
        "name": "UsingSynchronousCalls",
        "description": "Synchronous call to a server method — should be async in managed UI",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "ui"],
        "implemented": True,
    },
    "BSL273": {
        "name": "VirtualTableCallWithoutParameters",
        "description": "Virtual table (e.g. РегистрНакопления.Остатки) called without parameters",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL274": {
        "name": "WrongDataPathForFormElements",
        "description": "Form element data path references a non-existent attribute",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "ui"],
        "implemented": True,
    },
    "BSL275": {
        "name": "WrongHttpServiceHandler",
        "description": "HTTP service handler method has incorrect signature",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "http"],
        "implemented": True,
    },
    "BSL276": {
        "name": "WrongUseFunctionProceedWithCall",
        "description": "ПродолжитьВызов()/ProceedWithCall() used incorrectly in extension method",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["correctness", "extensions"],
        "implemented": True,
    },
    "BSL277": {
        "name": "WrongUseOfRollbackTransactionMethod",
        "description": "ОтменитьТранзакцию/RollbackTransaction called outside Except block",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "CRITICAL",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL278": {
        "name": "WrongWebServiceHandler",
        "description": "Web service operation handler method has incorrect signature",
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "BLOCKER",
        "tags": ["correctness", "web-service"],
        "implemented": True,
    },
    "BSL279": {
        "name": "YoLetterUsage",
        "description": "Letter «ё» used in identifiers or string literals — use «е» for consistency",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
        "implemented": True,
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
    "BSL041": "Использование устаревшего метода Сообщить()/Message()",
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
    "BSL077": "Использование ПЕРВЫЕ/TOP без УПОРЯДОЧИТЬ/ORDER BY в запросе",
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
    "BSL131": "Переименуйте или объедините области с одинаковым именем.",
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


_BSLLS_LSP_HINT_RULE_NAMES: frozenset[str] = frozenset(
    {
        "CanonicalSpellingKeywords",
        "CodeOutOfRegion",
        "CommandModuleExportMethods",
        "CommonModuleNameWords",
        "ConsecutiveEmptyLines",
        "DeprecatedAttributes8312",
        "DeprecatedMethods8310",
        "DeprecatedMethods8317",
        "DeprecatedTypeManagedForm",
        "DuplicateRegion",
        "EmptyRegion",
        "EmptyStatement",
        "FormDataToValue",
        "FunctionNameStartsWithGet",
        "IncorrectLineBreak",
        "NonStandardRegion",
        "MissingSpace",
        "PublicMethodsDescription",
        "RedundantAccessToObject",
        "SpaceAtStartComment",
        "UsageWriteLogEvent",
        "UselessTernaryOperator",
        "UsingServiceTag",
        "YoLetterUsage",
    }
)


@dataclass
class Diagnostic:
    """A single diagnostic issue found in a BSL file."""

    file: str
    line: int  # 1-based
    character: int  # 0-based column
    end_line: int
    end_character: int
    severity: Severity
    code: str  # e.g. "BSL001"
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


def lsp_compat_severity(code: str, severity: Severity) -> Severity:
    """
    Map internal severities to BSLLS-like LSP-facing severities.

    BSLLS exposes ``CODE_SMELL + INFO`` as LSP ``Hint``. Internally we keep the
    original severity for CLI/text reports, but LSP-facing parity should use the
    hint level for such diagnostics.
    """
    meta = RULE_METADATA.get(code, {})
    rule_name = str(meta.get("name") or code)
    if severity == Severity.INFORMATION and rule_name in _BSLLS_LSP_HINT_RULE_NAMES:
        return Severity.HINT
    return severity


# ---------------------------------------------------------------------------
# Internal analysis types
# ---------------------------------------------------------------------------


@dataclass
class _ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str  # 'procedure' | 'function'
    start_idx: int  # 0-based line index (header line)
    end_idx: int  # 0-based line index (КонецПроцедуры/КонецФункции)
    is_export: bool
    params: list[str]  # all param names (no defaults, no Val prefix)
    val_params: list[str]  # Знач/Val param names (passed by value)
    optional_count: int  # count of params with default values
    header_col: int = 0  # column of the keyword (indent)
    optional_params: frozenset[str] = frozenset()  # names of optional params (have default value)


@dataclass
class _RegionInfo:
    """#Область / #Region block."""

    name: str
    start_idx: int  # 0-based
    end_idx: int  # 0-based


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


def _proc_name_span(lines: list[str], proc: _ProcInfo) -> tuple[int, int]:
    """Best-effort span of the procedure/function name on the header line."""
    if 0 <= proc.start_idx < len(lines):
        header_line = lines[proc.start_idx]
        try:
            start = header_line.index(proc.name)
            return start, start + len(proc.name)
        except ValueError:
            pass
    start = proc.header_col
    return start, start + len(proc.name)


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
    r"(?:\d{1,3}\.){3}\d{1,3}"  # bare IPv4
    r"|\\\\[\w\-.]{2,}\\[\w\-.]+"  # UNC path
    r')"',
    re.IGNORECASE,
)
# BSLLS: URLs (https?/ftp) are NOT flagged by BSL005 — only bare IPv4 and UNC paths.
# Popular version prefixes to skip (BSLLS searchPopularVersionExclusion).
_RE_BSL005_POPULAR_VERSION = re.compile(r"^(?:1|2|3|8\.3|11)\.")
# Context keywords that indicate a version string context (BSLLS searchWordsExclusion).
_RE_BSL005_VERSION_CONTEXT = re.compile(
    r"Верси|Version|ЗапуститьПриложение|RunApp|Пространств|Namespace|Драйвер|Driver",
    re.IGNORECASE,
)

# Hardcoded file-system paths
_RE_HARDCODE_PATH = re.compile(
    r'"(?:'
    r'[A-Za-z]:\\[^"]{2,}'  # Windows C:\...
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
    r"(?:пароль|password|passwd|pwd|secret|credential(?:s)?|token"
    r'|логин|login|auth|apikey|api_key|accesskey|access_key)\s*=\s*"[^"]{2,}"',
    re.IGNORECASE,
)

# Commented-out code heuristic — defined below (search for _RE_COMMENTED_CODE second definition)

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
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf|Иначе|Else|Для|For|ДляКаждого|ForEach|Пока|While|Исключение|Except|Перейти|Goto)\b",
    re.IGNORECASE,
)
# McCabe: boolean operators (each И/Or adds a path)
_RE_MCCABE_BOOL = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
# McCabe: ternary operator ?(
_RE_MCCABE_TERNARY = re.compile(r"\?\s*\(")

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
    "ParseError": "BSL001",
    "MethodSize": "BSL002",
    "NonExportMethodsInApiRegion": "BSL003",
    "EmptyCodeBlock": "BSL004",
    "UnusedLocalVariable": "BSL007",
    "SelfAssign": "BSL009",
    "CognitiveComplexity": "BSL011",
    "CommentedCode": "BSL013",
    "NumberOfOptionalParams": "BSL015",
    "NonStandardRegion": "BSL016",
    "CyclomaticComplexity": "BSL019",
    "UsingModalWindows": "BSL022",
    "DeprecatedMessage": "BSL041",
    "UsingServiceTag": "BSL023",
    "SpaceAtStartComment": "BSL024",
    "EmptyRegion": "BSL026",
    "MagicNumber": "BSL029",
    "NumberOfParams": "BSL031",
    "DuplicateStringLiteral": "BSL035",
    "DuplicateRegion": "BSL131",
    "NestedTernaryOperator": "BSL039",
    "UsingThisForm": "BSL040",
    "UnreachableCode": "BSL051",
    "ProcedureReturnsValue": "BSL064",
    # ── BSLLS names (RULE_METADATA["name"] matches these) ─────────────────
    "UsingHardcodeNetworkAddress": "BSL005",
    "UsingHardcodePath": "BSL006",
    "TooManyReturns": "BSL008",
    "UsingHardcodeSecretInformation": "BSL012",
    "LineLength": "BSL014",
    "CommandModuleExportMethods": "BSL017",
    "NestedStatements": "BSL020",
    "UsingGoto": "BSL027",
    "MissingCodeTryCatchEx": "BSL028",
    "FunctionShouldHaveReturn": "BSL032",
    "CreateQueryInCycle": "BSL033",
    "IfConditionComplexity": "BSL036",
    "ConsecutiveEmptyLines": "BSL055",
    "DoubleNegatives": "BSL060",
    "UnusedParameters": "BSL062",
    "MissingReturnedValueDescription": "BSL065",
    "DeprecatedFind": "BSL066",
    "MagicDate": "BSL047",
    "DeprecatedCurrentDate": "BSL097",
    "ExportVariables": "BSL054",
    "SelectTopWithoutOrderBy": "BSL077",
    "EmptyStatement": "BSL025",
    "SemicolonPresence": "BSL030",
    "IdenticalExpressions": "BSL052",
    "UnusedLocalMethod": "BSL042",
    # ── BSL148–BSL279 stub mappings ──────────────────────────────────────────
    "AllFunctionPathMustHaveReturn": "BSL148",
    "AssignAliasFieldsInQuery": "BSL149",
    "BadWords": "BSL150",
    "BeginTransactionBeforeTryCatch": "BSL151",
    "CachedPublic": "BSL152",
    "CanonicalSpellingKeywords": "BSL153",
    "CodeAfterAsyncCall": "BSL154",
    "CodeBlockBeforeSub": "BSL155",
    "CodeOutOfRegion": "BSL156",
    "CommitTransactionOutsideTryCatch": "BSL157",
    "CommonModuleAssign": "BSL158",
    "CommonModuleInvalidType": "BSL159",
    "CommonModuleMissingAPI": "BSL160",
    "CommonModuleNameCached": "BSL161",
    "CommonModuleNameClient": "BSL162",
    "CommonModuleNameClientServer": "BSL163",
    "CommonModuleNameFullAccess": "BSL164",
    "CommonModuleNameGlobal": "BSL165",
    "CommonModuleNameGlobalClient": "BSL166",
    "CommonModuleNameServerCall": "BSL167",
    "CommonModuleNameWords": "BSL168",
    "CompilationDirectiveLost": "BSL169",
    "CompilationDirectiveNeedLess": "BSL170",
    "CrazyMultilineString": "BSL171",
    "DataExchangeLoading": "BSL172",
    "DeletingCollectionItem": "BSL173",
    "DenyIncompleteValues": "BSL174",
    "DeprecatedAttributes8312": "BSL175",
    "DeprecatedMethodCall": "BSL176",
    "DeprecatedMethods8310": "BSL177",
    "DeprecatedMethods8317": "BSL178",
    "DeprecatedTypeManagedForm": "BSL179",
    "DisableSafeMode": "BSL180",
    "DuplicatedInsertionIntoCollection": "BSL181",
    "ExcessiveAutoTestCheck": "BSL182",
    "ExecuteExternalCode": "BSL183",
    "ExecuteExternalCodeInCommonModule": "BSL184",
    "ExternalAppStarting": "BSL185",
    "ExtraCommas": "BSL186",
    "FieldsFromJoinsWithoutIsNull": "BSL187",
    "FileSystemAccess": "BSL188",
    "ForbiddenMetadataName": "BSL189",
    "FormDataToValue": "BSL190",
    "FullOuterJoinQuery": "BSL191",
    "FunctionNameStartsWithGet": "BSL192",
    "FunctionOutParameter": "BSL193",
    "FunctionReturnsSamePrimitive": "BSL194",
    "GetFormMethod": "BSL195",
    "GlobalContextMethodCollision8312": "BSL196",
    "IfElseDuplicatedCodeBlock": "BSL197",
    "IfElseDuplicatedCondition": "BSL198",
    "IfElseIfEndsWithElse": "BSL199",
    "IncorrectLineBreak": "BSL200",
    "IncorrectUseLikeInQuery": "BSL201",
    "IncorrectUseOfStrTemplate": "BSL202",
    "InternetAccess": "BSL203",
    "InvalidCharacterInFile": "BSL204",
    "IsInRoleMethod": "BSL205",
    "JoinWithSubQuery": "BSL206",
    "JoinWithVirtualTable": "BSL207",
    "LatinAndCyrillicSymbolInWord": "BSL208",
    "LogicalOrInJoinQuerySection": "BSL209",
    "LogicalOrInTheWhereSectionOfQuery": "BSL210",
    "MetadataObjectNameLength": "BSL211",
    "MissedRequiredParameter": "BSL212",
    "MissingCommonModuleMethod": "BSL213",
    "MissingEventSubscriptionHandler": "BSL214",
    "MissingParameterDescription": "BSL215",
    "MissingSpace": "BSL216",
    "MissingTempStorageDeletion": "BSL217",
    "MissingTemporaryFileDeletion": "BSL218",
    "MissingVariablesDescription": "BSL219",
    "MultilineStringInQuery": "BSL220",
    "MultilingualStringHasAllDeclaredLanguages": "BSL221",
    "MultilingualStringUsingWithTemplate": "BSL222",
    "NestedConstructorsInStructureDeclaration": "BSL223",
    "NestedFunctionInParameters": "BSL224",
    "NumberOfValuesInStructureConstructor": "BSL225",
    "OSUsersMethod": "BSL226",
    "OneStatementPerLine": "BSL227",
    "OrderOfParams": "BSL228",
    "OrdinaryAppSupport": "BSL229",
    "PairingBrokenTransaction": "BSL230",
    "PrivilegedModuleMethodCall": "BSL231",
    "ProtectedModule": "BSL232",
    "PublicMethodsDescription": "BSL233",
    "QueryNestedFieldsByDot": "BSL234",
    "QueryParseError": "BSL235",
    "QueryToMissingMetadata": "BSL236",
    "RedundantAccessToObject": "BSL237",
    "RefOveruse": "BSL238",
    "ReservedParameterNames": "BSL239",
    "RewriteMethodParameter": "BSL240",
    "SameMetadataObjectAndChildNames": "BSL241",
    "ScheduledJobHandler": "BSL242",
    "SelfInsertion": "BSL243",
    "ServerCallsInFormEvents": "BSL244",
    "ServerSideExportFormMethod": "BSL245",
    "SetPermissionsForNewObjects": "BSL246",
    "SetPrivilegedMode": "BSL247",
    "SeveralCompilerDirectives": "BSL248",
    "StyleElementConstructors": "BSL249",
    "TempFilesDir": "BSL250",
    "TernaryOperatorUsage": "BSL251",
    "ThisObjectAssign": "BSL252",
    "TimeoutsInExternalResources": "BSL253",
    "TransferringParametersBetweenClientAndServer": "BSL254",
    "TryNumber": "BSL255",
    "Typo": "BSL256",
    "UnaryPlusInConcatenation": "BSL257",
    "UnionAll": "BSL258",
    "UnknownPreprocessorSymbol": "BSL259",
    "UnsafeFindByCode": "BSL260",
    "UnsafeSafeModeMethodCall": "BSL261",
    "UsageWriteLogEvent": "BSL262",
    "UseLessForEach": "BSL263",
    "UseSystemInformation": "BSL264",
    "UselessTernaryOperator": "BSL265",
    "UsingCancelParameter": "BSL266",
    "UsingExternalCodeTools": "BSL267",
    "UsingFindElementByString": "BSL268",
    "UsingLikeInQuery": "BSL269",
    # "UsingModalWindows" → BSL022 (active impl); BSL270 stub removed to avoid dict key collision
    "UsingObjectNotAvailableUnix": "BSL271",
    "UsingSynchronousCalls": "BSL272",
    "VirtualTableCallWithoutParameters": "BSL273",
    "WrongDataPathForFormElements": "BSL274",
    "WrongHttpServiceHandler": "BSL275",
    "WrongUseFunctionProceedWithCall": "BSL276",
    "WrongUseOfRollbackTransactionMethod": "BSL277",
    "WrongWebServiceHandler": "BSL278",
    "YoLetterUsage": "BSL279",
    "UnknownMetadataObjectReference": "BSL280",
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


def parse_env_rule_profile() -> str | None:
    """Read ``BSL_PROFILE`` from the environment."""
    from onec_hbk_bsl.analysis.bslls_parity import normalize_rule_profile

    return normalize_rule_profile(os.environ.get("BSL_PROFILE", ""))


# Deprecated dialog: Предупреждение(...) / Warning(...)
_RE_DEPRECATED_MSG = re.compile(
    r"^\s*(?:Предупреждение|Warning)\s*\(",
    re.IGNORECASE,
)
_RE_DEPRECATED_MESSAGE = re.compile(
    r"\b(?:Сообщить|Message)\s*\(",
    re.IGNORECASE,
)
_RE_BSL202_STRTEMPLATE = re.compile(r"\b(?:СтрШаблон|StrTemplate)\s*\(", re.IGNORECASE)
_BSL223_STRUCTURE_NAMES = frozenset(
    {"структура", "structure", "фиксированнаяструктура", "fixedstructure"}
)
_BSL249_STYLE_CONSTRUCTOR_NAMES = frozenset(
    {"цвет", "color", "шрифт", "font", "граница", "border", "рамка", "frame", "кисть", "brush"}
)
_RE_BSL221_NSTR = re.compile(r"\b(?:НСтр|NStr)\s*\(\s*\"(?P<body>[^\"]*)\"\s*\)", re.IGNORECASE)
_RE_BSL221_LANG = re.compile(r"(?:^|;)\s*(?P<lang>[A-Za-z]{2})\s*=", re.IGNORECASE)
_RE_BSL271_UNIX_UNAVAILABLE_NEW = re.compile(
    r"\b(?:Новый|New)\s+(?P<name>COMОбъект|COMObject|Почта|Mail)\b",
    re.IGNORECASE,
)
_RE_BSL271_PLATFORM_GUARD = re.compile(r"\b(?:Linux_x86|Windows|MacOS)\b", re.IGNORECASE)
_RE_BSL276_PROCEED_WITH_CALL = re.compile(
    r"\b(?:ПродолжитьВызов|ProceedWithCall)\s*\(",
    re.IGNORECASE,
)
_RE_BSL276_AROUND_ANNOTATION = re.compile(r"^\s*&(?:Вместо|Instead|Around)\b", re.IGNORECASE)
_RE_XML_BOOL_SIMPLE = r"<{tag}>\s*(true|false)\s*</{tag}>"
_RE_BSL275_HANDLER = re.compile(r"<Handler>\s*([^<]*)\s*</Handler>", re.IGNORECASE)
_RE_BSL278_PROCNAME = re.compile(r"<ProcedureName>\s*([^<]*)\s*</ProcedureName>", re.IGNORECASE)
_RE_XML_NAME_SIMPLE = re.compile(r"<Name>\s*([^<]+?)\s*</Name>", re.IGNORECASE)
_RE_XML_DIMENSION_BLOCK = re.compile(
    r"<Dimension\b.*?>.*?<Name>\s*([^<]+?)\s*</Name>.*?<DenyIncompleteValues>\s*(true|false)\s*</DenyIncompleteValues>.*?</Dimension>",
    re.IGNORECASE | re.DOTALL,
)
_RE_XML_SET_FOR_NEW_OBJECTS = re.compile(
    r"<SetForNewObjects>\s*(true|false)\s*</SetForNewObjects>",
    re.IGNORECASE,
)
_RE_XML_METHOD_NAME = re.compile(r"<MethodName>\s*([^<]+?)\s*</MethodName>", re.IGNORECASE)
_RE_XML_EVENT_HANDLER = re.compile(
    r"<Handler>\s*([^<]+?)\s*</Handler>|<Method>\s*([^<]+?)\s*</Method>",
    re.IGNORECASE,
)
_RE_XML_DATAPATH = re.compile(r"<DataPath>\s*([^<]+?)\s*</DataPath>", re.IGNORECASE)
_RE_XML_PROTECTED = re.compile(
    r"<(?:IsProtected|Protected)>\s*true\s*</(?:IsProtected|Protected)>", re.IGNORECASE
)
_RE_XML_PRIVILEGED = re.compile(r"<Privileged>\s*true\s*</Privileged>", re.IGNORECASE)


def _path_is_command_module_bsl(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    return (
        low.endswith("/ext/commandmodule.bsl") or "/commands/" in low or "/commoncommands/" in low
    )


@functools.lru_cache(maxsize=32)
def _config_root_for_file(path: str) -> str | None:
    try:
        p = Path(path).resolve()
    except OSError:
        p = Path(path)
    for parent in (p.parent, *p.parents):
        if (parent / "Configuration.xml").exists():
            return str(parent)
    return None


@functools.lru_cache(maxsize=8)
def _crawl_config_cached(config_root: str) -> dict[str, Any]:
    objects = crawl_config(config_root)
    by_name: dict[str, Any] = {}
    for obj in objects:
        by_name[obj.name.casefold()] = obj
    return {"objects": objects, "by_name": by_name}


@functools.lru_cache(maxsize=256)
def _read_text_cached(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _current_module_xml_context(path: str) -> dict[str, str]:
    low = path.replace("\\", "/")
    parts = Path(low).parts
    out: dict[str, str] = {}
    for idx, part in enumerate(parts):
        if part in FOLDER_TO_KIND:
            out["folder"] = part
            if idx + 1 < len(parts):
                out["object_name"] = parts[idx + 1]
            if "forms" in [p.casefold() for p in parts[idx + 1 :]]:
                try:
                    forms_idx = next(
                        i for i in range(idx + 1, len(parts)) if parts[i].casefold() == "forms"
                    )
                    if forms_idx + 1 < len(parts):
                        out["form_name"] = parts[forms_idx + 1]
                except StopIteration:
                    pass
            break
    return out


def _current_object_xml_path(path: str) -> Path | None:
    root = _config_root_for_file(path)
    if root is None:
        return None
    ctx = _current_module_xml_context(path)
    folder = ctx.get("folder")
    object_name = ctx.get("object_name")
    if folder and object_name:
        return Path(root) / folder / f"{object_name}.xml"
    if "/commonmodules/" in path.replace("\\", "/").lower():
        mod_name = Path(path).parent.parent.name
        return Path(root) / "CommonModules" / f"{mod_name}.xml"
    return None


def _current_form_xml_path(path: str) -> Path | None:
    root = _config_root_for_file(path)
    if root is None:
        return None
    ctx = _current_module_xml_context(path)
    folder = ctx.get("folder")
    object_name = ctx.get("object_name")
    form_name = ctx.get("form_name")
    if not (folder and object_name and form_name):
        return None
    return Path(root) / folder / object_name / "Forms" / form_name / "Ext" / "Form.xml"


@functools.lru_cache(maxsize=64)
def _common_module_file_map(config_root: str) -> dict[str, dict[str, Any]]:
    root = Path(config_root) / "CommonModules"
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for xml_file in root.glob("*.xml"):
        name = xml_file.stem
        raw = _read_text_cached(str(xml_file))
        module_file = root / name / "Ext" / "Module.bsl"
        proc_names: set[str] = set()
        if module_file.exists():
            snap = build_document_snapshot(
                str(module_file),
                content=_read_text_cached(str(module_file)),
            )
            proc_names = {proc.name.casefold() for proc in snap.procedures}
        result[name.casefold()] = {
            "name": name,
            "privileged": bool(_RE_XML_PRIVILEGED.search(raw)),
            "protected": bool(_RE_XML_PROTECTED.search(raw)),
            "proc_names": proc_names,
        }
    return result


# Service tags in comments
# Matches BSLLS UsingServiceTagDiagnostic default pattern:
# todo|fixme|!!|mrg|@|отладка|debug|для отладки|{{КОНСТРУКТОР_|}}КОНСТРУКТОР_|{{MRG|}}MRG|...
# Pattern: //\s*(tag), so tag must follow // with optional whitespace.
_RE_SERVICE_TAG = re.compile(
    r"//\s*("
    r"todo|fixme|!!|mrg|@|отладка|debug|для\s*отладки"
    r"|(?:\{\{|\}\})КОНСТРУКТОР_|(?:\{\{|\}\})MRG"
    r"|Вставить\s*содержимое\s*обработчика"
    r"|Paste\s*handler\s*content|Insert\s*handler\s*code"
    r"|Insert\s*handler\s*content|Insert\s*handler\s*contents"
    r")",
    re.IGNORECASE,
)

# BSL215 — MissingParameterDescription: comment section headers and param entry
_RE_BSL215_PARAMS_SECTION = re.compile(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", re.IGNORECASE)
_RE_BSL215_PARAM_ENTRY = re.compile(r"^\s*//\s{1,4}(\w+)\s*[-–]", re.UNICODE)
_RE_BSL215_COMMENT_LINE = re.compile(r"^\s*//")

# BSLLS SpaceAtStartCommentDiagnostic — GOOD_COMMENT_PATTERN_STRICT (develop branch):
# either "//[ \\t].*" or "//{2,}[ \\t]*" end-of-line only (///, ////, bare //).
_BSL024_BSLLS_GOOD_STRICT = re.compile(
    r"(?:(?://[ \t].*)|(?:/{2,}[ \t]*))$",
    re.IGNORECASE,
)
_BSL200_INCORRECT_START = re.compile(r"^\s*(\)|;|,\s*\S+|\);)", re.IGNORECASE)
_BSL200_INCORRECT_END = re.compile(r"\s+(ИЛИ|И|OR|AND|\+|-|/|%|\*)\s*(?://.*)?$", re.IGNORECASE)


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
    """Extra skips aligned with editor-specific service comments: ``/// ``, ``//|``, ``//!``, noqa, bsl-disable."""
    st = line.lstrip()
    if st.startswith("/// ") or st.startswith("///\t"):
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


def bsl024_find_report_comment_col(line: str) -> int | None:
    """
    Return the ``//`` column when ``SpaceAtStartComment`` / BSL024 should flag the comment token.

    Kept in sync with :meth:`DiagnosticEngine._rule_bsl024_space_at_start_comment`
    and LSP quick-fix for BSL024.
    """
    col = _comment_start_outside_double_quotes(line)
    if col is None:
        return None
    comment_text = line[col:]
    if _bsl024_matches_bslls_good_strict(line, col):
        return None
    if _bsl024_is_bslls_annotation_comment(line, col):
        return None
    if _bsl024_skip_line_bslls_alignment(comment_text):
        return None
    if _RE_COMMENTED_CODE.match(comment_text):
        return None
    if col == len(line) - len(line.lstrip()) and _bsl024_is_compiler_directive_comment(
        comment_text
    ):
        return None
    return col


def bsl024_should_report_line(line: str) -> bool:
    """Backward-compatible boolean wrapper over :func:`bsl024_find_report_comment_col`."""
    return bsl024_find_report_comment_col(line) is not None


def _comment_start_outside_double_quotes(line: str, in_str_at_start: bool = False) -> int | None:
    """Return 0-based ``//`` position outside double-quoted strings, if any."""
    in_str = in_str_at_start
    i = 0
    n = len(line)
    while i < n - 1:
        ch = line[i]
        if ch == '"':
            in_str = not in_str
            i += 1
            continue
        if not in_str and ch == "/" and line[i + 1] == "/":
            return i
        i += 1
    return None


def _span_is_inside_double_quoted_string(
    line: str,
    start: int,
    end: int,
    *,
    in_str_at_start: bool = False,
) -> bool:
    """True when ``[start, end)`` lies inside a double-quoted string on the line."""
    in_str = in_str_at_start
    segment_start: int | None = 0 if in_str else None
    for idx, ch in enumerate(line):
        if ch != '"':
            continue
        if in_str:
            if segment_start is None:
                segment_start = 0
            if segment_start <= start and idx + 1 >= end:
                return True
            in_str = False
            segment_start = None
        else:
            in_str = True
            segment_start = idx
    if in_str and segment_start is not None and segment_start <= start:
        return True
    return False


def _bsl200_query_first_prev_lines(lines: list[str]) -> set[int]:
    """
    Lines whose next line starts a query-text block.

    Mirrors BSLLS ``queryStartsAtNextLine`` skip for:
    ``Запрос.Текст =`` followed by the first query literal line.
    """
    query_prev_lines: set[int] = set()
    for start_idx, _block_lines in _iter_query_text_blocks(lines):
        if start_idx > 0:
            query_prev_lines.add(start_idx - 1)
    return query_prev_lines


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


def _redundant_access_prefix_patterns(path: str) -> list[re.Pattern[str]]:
    low = path.replace("\\", "/")
    parts = Path(low).parts
    patterns = [re.compile(r"\b(?:ЭтотОбъект|ThisObject)\.", re.IGNORECASE | re.UNICODE)]

    if len(parts) >= 3 and parts[-1].lower() == "managermodule.bsl":
        folder = parts[-3]
        object_name = parts[-2]
        collection_map = {
            "Catalogs": ("Справочники", "Catalogs"),
            "Documents": ("Документы", "Documents"),
            "AccountingRegisters": ("РегистрыБухгалтерии", "AccountingRegisters"),
            "AccumulationRegisters": ("РегистрыНакопления", "AccumulationRegisters"),
            "CalculationRegisters": ("РегистрыРасчета", "CalculationRegisters"),
            "InformationRegisters": ("РегистрыСведений", "InformationRegisters"),
        }
        prefixes = collection_map.get(folder, (object_name,))
        for prefix in prefixes:
            patterns.append(
                re.compile(
                    rf"\b{re.escape(prefix)}\.{re.escape(object_name)}\.",
                    re.IGNORECASE | re.UNICODE,
                )
            )
    return patterns


# Параметры стандартных обработчиков (команды, события форм) — BSLLS не помечает как неиспользуемые.
_BSL062_SKIP_STANDARD_COMMAND_PARAMS = frozenset(
    {
        # ── Команды ────────────────────────────────────────────────────────────
        "команда",  # Процедура ОткрытьФорму(Команда) — стандартный командный обработчик
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
        "область",  # ПолеТабличногоДокумента...Выбор(Элемент, Область, СтандартнаяОбработка)
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


def _proc_param_name_span(header_line: str, param_name: str) -> tuple[int, int] | None:
    open_paren = header_line.find("(")
    close_paren = header_line.rfind(")")
    if open_paren < 0:
        return None
    haystack = header_line[open_paren + 1 : close_paren if close_paren > open_paren else None]
    m = re.search(rf"\b{re.escape(param_name)}\b", haystack, re.IGNORECASE)
    if not m:
        return None
    start = open_paren + 1 + m.start()
    return start, open_paren + 1 + m.end()


def _proc_assigned_param_names(lines: list[str], proc: _ProcInfo) -> set[str]:
    assigned: set[str] = set()
    body_start = _proc_body_start_line_idx_fallback(lines, proc)
    for li in range(body_start, min(proc.end_idx, len(lines))):
        line = lines[li]
        if _RE_LINE_COMMENT.match(line) or not line.strip():
            continue
        am = _RE_BSL240_ASSIGN.match(line)
        if am:
            assigned.add(am.group(1).casefold())
    return assigned


def _proc_by_name_and_line(procs: list[_ProcInfo], name: str, line_1based: int) -> _ProcInfo | None:
    line_idx = max(0, line_1based - 1)
    for proc in procs:
        if proc.name.casefold() == name.casefold() and proc.start_idx <= line_idx <= proc.end_idx:
            return proc
    return None


def _load_file_lines_cached(
    path: str,
    cache: dict[str, list[str]],
) -> list[str] | None:
    if path in cache:
        return cache[path]
    try:
        cache[path] = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        cache[path] = []
    return cache[path]


def _parse_procs_cached(
    path: str,
    cache: dict[str, list[_ProcInfo]],
    file_lines_cache: dict[str, list[str]],
) -> list[_ProcInfo]:
    if path in cache:
        return cache[path]
    lines = _load_file_lines_cached(path, file_lines_cache) or []
    cache[path] = _find_procedures("\n".join(lines))
    return cache[path]


def _caller_is_client_method(
    caller_file: str,
    caller_name: str | None,
    caller_line: int,
    *,
    current_path: str,
    current_lines: list[str],
    current_procs: list[_ProcInfo],
    file_lines_cache: dict[str, list[str]],
    proc_cache: dict[str, list[_ProcInfo]],
) -> bool:
    if not caller_name:
        return False
    if caller_file == current_path:
        proc = _proc_by_name_and_line(current_procs, caller_name, caller_line)
        return (
            proc is not None
            and _procedure_compiler_execution_context(current_lines, proc) == "client"
        )
    caller_lines = _load_file_lines_cached(caller_file, file_lines_cache) or []
    caller_procs = _parse_procs_cached(caller_file, proc_cache, file_lines_cache)
    proc = _proc_by_name_and_line(caller_procs, caller_name, caller_line)
    return (
        proc is not None and _procedure_compiler_execution_context(caller_lines, proc) == "client"
    )


def _proc_containing_line(procs: list[_ProcInfo], line_idx: int) -> _ProcInfo | None:
    """Procedure/function whose body includes 0-based line index *line_idx*."""
    for p in procs:
        if p.start_idx <= line_idx <= p.end_idx:
            return p
    return None


def _comma_missing_space_after_cols_in_line(line: str) -> list[int]:
    """
    0-based column of the last ``,`` immediately followed by a token char (BSLLS MissingSpace),
    only outside ``"..."`` string literals (positions must match *line* for overlap filter).
    """
    in_str = False
    i = 0
    n = len(line)
    cols: list[int] = []
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
            # BSLLS requires a space after comma; ,, (multiple commas) are also flagged.
            # Only allow whitespace, closing bracket/paren, or end-of-line after comma.
            if nxt not in " \t\n\r)]\n":
                cols.append(i)
        i += 1
    return cols


def _mask_double_quoted_strings_preserve_len(line: str) -> str:
    """Replace string contents with spaces while preserving original offsets."""
    return _RE_DOUBLE_QUOTED_STRING.sub(lambda m: '"' + (" " * (len(m.group(0)) - 2)) + '"', line)


def _strip_inline_comment_preserve_strings(line: str) -> str:
    """Remove ``//`` comments while ignoring occurrences inside double-quoted strings."""
    masked = _mask_double_quoted_strings_preserve_len(line)
    comment_pos = masked.find("//")
    return line[:comment_pos] if comment_pos >= 0 else line


def _build_line_string_states(lines: list[str]) -> list[bool]:
    """
    Returns a list where entry[i] is True if line i *starts* inside a double-quoted string.
    Needed for multi-line string handling in BSL216 checks.
    """
    states: list[bool] = []
    in_str = False
    for line in lines:
        states.append(in_str)
        for ch in line:
            if ch == '"':
                in_str = not in_str
    return states


# BSL216 — module-level patterns (avoid re.compile inside the hot loop)
_RE_BSL216_ASSIGN_NOSPACE = re.compile(r"\b(\w+)=(\w)", re.UNICODE)
_RE_BSL216_PROC_HEADER = re.compile(
    r"^\s*(?:Процедура|Функция|Procedure|Function)\b", re.IGNORECASE
)
_RE_BSL216_BEFORE_THEN = re.compile(r"(?<=\S)(?:Тогда|Then)\b", re.IGNORECASE)
_RE_BSL216_SEMICOLON_NOSPACE = re.compile(r";(?=\S)")
_RE_BSL216_LEFT_RIGHT_KEYWORDS = re.compile(r"\b(По|To|Из|In|Или|Or|И|And)\b", re.IGNORECASE)
_RE_BSL216_LEFT_KEYWORDS = re.compile(r"\b(Экспорт|Export|Тогда|Then|Цикл|Do)\b", re.IGNORECASE)
_RE_BSL216_RIGHT_KEYWORDS = re.compile(
    r"\b(Если|If|ИначеЕсли|ElsIf|ElseIf|Пока|While|Для|For|Не|Not|Каждого|Each)\b",
    re.IGNORECASE,
)
# BSL215/BSL233 — compiler directive (e.g. &НаКлиенте) preceding a proc header
_RE_COMPILER_DIRECTIVE = re.compile(r"^\s*&\w+\s*$")
# BSL044 — function returns non-void value
_RE_BSL044_RETURN_VALUE = re.compile(r"^\s*(?:Возврат|Return)\s+\S", re.IGNORECASE | re.MULTILINE)
# BSL049 — try/catch block markers
_RE_TRY_OPEN = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
_RE_TRY_CLOSE = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
# BSL240 / write-only var assignment
_RE_MODULE_ASSIGN = re.compile(r"^\s*(\w+)\s*=(?!=)", re.IGNORECASE)
_RE_ASSIGN_LHS = re.compile(r"^\s*(?P<name>\w+)\s*=(?!=)", re.IGNORECASE)
_RE_BSL192_GET = re.compile(r"^(?:Получить|Get)\w*$", re.IGNORECASE)
_RE_BSL266_CANCEL = re.compile(r"^(?:Отказ|Cancel)$", re.IGNORECASE)
# BSL186 — trailing comma before ) or ;
_RE_BSL186_TRAILING_COMMA = re.compile(r",\s*[)\];]")
# BSL149 — AssignAliasFieldsInQuery
_RE_BSL149_SELECT = re.compile(r"\bВЫБРАТЬ\b|\bSELECT\b", re.IGNORECASE)
# Modifiers after SELECT that are not field names
_RE_BSL149_SELECT_MODIFIERS = re.compile(
    r"^\s*(?:РАЗЛИЧНЫЕ|DISTINCT|ПЕРВЫЕ|TOP)\b(?:\s+\d+)?\s*", re.IGNORECASE
)
# Clause keywords that end the SELECT field list (or signal UNION)
_RE_BSL149_CLAUSE_END = re.compile(
    r"^\s*(?:ПОМЕСТИТЬ|INTO|ИЗ|FROM|ГДЕ|WHERE|СГРУППИРОВАТЬ|GROUP\s+BY|"
    r"УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
    r"ИТОГИ|TOTALS|АВТОУПОРЯДОЧИВАНИЕ|AUTOORDER|"
    r"ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE)\b",
    re.IGNORECASE,
)
# Same keywords for one-line literals: field list may have leading spaces before clause
_RE_BSL149_CLAUSE_AFTER_FIELDS = re.compile(
    r"(?:ПОМЕСТИТЬ|INTO|ИЗ|FROM|ГДЕ|WHERE|СГРУППИРОВАТЬ|GROUP\s+BY|"
    r"УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
    r"ИТОГИ|TOTALS|АВТОУПОРЯДОЧИВАНИЕ|AUTOORDER|"
    r"ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE)\b",
    re.IGNORECASE,
)
# UNION/ОБЪЕДИНИТЬ keyword — next SELECT's fields are skipped
_RE_BSL149_UNION = re.compile(r"\bОБЪЕДИНИТЬ\b|\bUNION\b", re.IGNORECASE)
# Field has explicit alias: КАК/AS followed by identifier (end of field text)
_RE_BSL149_HAS_ALIAS = re.compile(r"\b(?:КАК|AS)\s+\w+\s*$", re.IGNORECASE)
# Query continuation line
_RE_BSL149_CONTINUATION = re.compile(r"^\s*\|")
# Inline query comment
_RE_BSL149_INLINE_COMMENT = re.compile(r"\s*//.*$")

# BSL210 — LogicalOrInTheWhereSectionOfQuery
_RE_BSL210_OR = re.compile(r"\b(?:ИЛИ|OR)\b", re.IGNORECASE)
_RE_BSL210_LINE_IS_WHERE = re.compile(r"^\s*(?:ГДЕ|WHERE)\b", re.IGNORECASE)
_RE_BSL210_LINE_ENDS_WHERE = re.compile(
    r"^\s*(?:СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
    r"ИТОГИ|TOTALS|АВТОУПРЯДОЧИВАНИЕ|AUTOORDER|"
    r"ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE)\b",
    re.IGNORECASE,
)
_RE_BSL210_POST_WHERE_KEYWORD = re.compile(
    r"\b(?:СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
    r"ИТОГИ|TOTALS|АВТОУПРЯДОЧИВАНИЕ|AUTOORDER|ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE|"
    r"ОБЪЕДИНИТЬ|UNION)\b",
    re.IGNORECASE,
)
_BSL210_MESSAGE = "Логическое ИЛИ в секции ГДЕ запроса"
_RE_QUERY_JOIN_KEYWORD = re.compile(
    r"\b(?:ЛЕВОЕ|LEFT|ПРАВОЕ|RIGHT|ВНУТРЕННЕЕ|INNER|ПОЛНОЕ|FULL)(?:\s+ВНЕШНЕЕ|\s+OUTER)?\s+"
    r"(?:СОЕДИНЕНИЕ|JOIN)\b",
    re.IGNORECASE,
)
_RE_QUERY_ON_KEYWORD = re.compile(r"\b(?:ПО|ON)\b", re.IGNORECASE)
_RE_QUERY_JOIN_END_KEYWORD = re.compile(
    r"\b(?:ГДЕ|WHERE|СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|"
    r"ИМЕЮЩИЕ|HAVING|ИТОГИ|TOTALS|ОБЪЕДИНИТЬ|UNION)\b",
    re.IGNORECASE,
)
_RE_QUERY_DATASOURCE_SUBQUERY = re.compile(r"\(\s*(?:ВЫБРАТЬ|SELECT)\b", re.IGNORECASE)
_RE_QUERY_VIRTUAL_TABLE = re.compile(
    r"\b(?:Регистр(?:Сведений|Накопления|Бухгалтерии|Расчета)|"
    r"InformationRegister|AccumulationRegister|AccountingRegister|CalculationRegister)"
    r"\.\w+(?:\.\w+)+\s*\(",
    re.IGNORECASE,
)
_RE_QUERY_COLUMN_REF = re.compile(r"\b\w+\.\w+(?:\.\w+)*\b", re.IGNORECASE)
_RE_QUERY_FULL_OUTER_JOIN = re.compile(
    r"\b(?:ПОЛНОЕ(?:\s+ВНЕШНЕЕ)?|FULL(?:\s+OUTER)?)\s+(?:СОЕДИНЕНИЕ|JOIN)\b",
    re.IGNORECASE,
)
_RE_QUERY_LIKE_OPERATOR = re.compile(r"\b(?:ПОДОБНО|LIKE)\b", re.IGNORECASE)
_RE_QUERY_LIKE_TAIL_STOP = re.compile(
    r"\b(?:КАК|AS|И|AND|ИЛИ|OR|ПО|ON|ГДЕ|WHERE|"
    r"СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|"
    r"ИМЕЮЩИЕ|HAVING|ИТОГИ|TOTALS|ОБЪЕДИНИТЬ|UNION)\b|,",
    re.IGNORECASE,
)
_QUERY_VIRTUAL_TABLE_NAME_PATTERN = (
    r"(?:Регистр(?:Сведений|Накопления|Бухгалтерии|Расчета)|"
    r"InformationRegister|AccumulationRegister|AccountingRegister|CalculationRegister)"
    r"\.\w+(?:\.\w+)+"
)
_RE_QUERY_VIRTUAL_TABLE_CALL = re.compile(
    rf"\b(?P<name>{_QUERY_VIRTUAL_TABLE_NAME_PATTERN})\s*(?P<open>\()?",
    re.IGNORECASE,
)
_RE_QUERY_PARSE_ERROR_TAIL_KEYWORD = re.compile(
    r"\b(?:ИЗ|FROM|КАК|AS|ПО|ON|ГДЕ|WHERE|ЛЕВОЕ|LEFT|ПРАВОЕ|RIGHT|"
    r"ВНУТРЕННЕЕ|INNER|ПОЛНОЕ|FULL|СОЕДИНЕНИЕ|JOIN)\s*$",
    re.IGNORECASE,
)
_RE_QUERY_PARSE_ERROR_TAIL_OPERATOR = re.compile(
    r"(?:[=<>+\-*/]|\b(?:И|AND|ИЛИ|OR)\b)\s*$", re.IGNORECASE
)
_RE_QUERY_FIELD_REF = re.compile(r"\b(?P<alias>\w+)\.(?P<field>\w+(?:\.\w+)*)\b", re.IGNORECASE)


def _bsl210_where_clause_region_bounds(lit: str, where_match: re.Match) -> tuple[int, int]:
    """Return [start, end) covering the WHERE clause starting at *where_match* (keyword inclusive)."""
    i = where_match.end()
    depth = 0
    n = len(lit)
    while i < n:
        c = lit[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                depth = 0
        if depth == 0 and i > where_match.end() and _RE_BSL210_POST_WHERE_KEYWORD.match(lit, i):
            return (where_match.start(), i)
        i += 1
    return (where_match.start(), n)


def _bsl210_or_spans_in_query_literal(lit: str) -> list[tuple[int, int]]:
    """Char spans (start, end exclusive) of ИЛИ/OR inside WHERE clauses of *lit*."""
    out: list[tuple[int, int]] = []
    pos = 0
    while True:
        m = _RE_QUERY_WHERE.search(lit, pos)
        if not m:
            break
        _, re_ = _bsl210_where_clause_region_bounds(lit, m)
        body = lit[m.end() : re_]
        base = m.end()
        for om in _RE_BSL210_OR.finditer(body):
            out.append((base + om.start(), base + om.end()))
        pos = re_
    return out


def _bsl210_iter_double_quoted_segments(line: str):
    """Yield (opening_quote_index, inner_text) for each BSL string literal on *line*."""
    i = 0
    n = len(line)
    while i < n:
        if line[i] != '"':
            i += 1
            continue
        q = i
        i += 1
        buf: list[str] = []
        while i < n:
            if line[i] == '"':
                if i + 1 < n and line[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                break
            buf.append(line[i])
            i += 1
        yield q, "".join(buf)
        i += 1


def _bsl149_strip_leading_select_modifiers(text: str) -> str:
    """Strip РАЗЛИЧНЫЕ/DISTINCT, ПЕРВЫЕ/TOP N from the start of a SELECT field list."""
    t = text.strip()
    while True:
        m = _RE_BSL149_SELECT_MODIFIERS.match(t)
        if not m:
            break
        t = t[m.end() :].lstrip()
    return t


def _bsl149_append_missing_alias_diags(
    path: str,
    line_idx: int,
    line: str,
    field_region: str,
    diags: list[Diagnostic],
) -> None:
    """Append at most one BSL149 diagnostic for *field_region* (comma-separated SELECT list)."""
    field_region = _bsl149_strip_leading_select_modifiers(field_region)
    if not field_region:
        return
    for seg in field_region.split(","):
        field = seg.strip().rstrip('";')
        if not field or field == "*":
            continue
        if _RE_BSL149_SELECT.search(field):
            continue
        if not _RE_BSL149_HAS_ALIAS.search(field):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=0,
                    end_line=line_idx + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
                    code="BSL149",
                    message="Полям запроса следует назначать псевдонимы",
                )
            )
            break


def _iter_query_text_blocks(lines: list[str]):
    """Yield query-like string blocks as ``(start_idx, block_lines)``."""
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _RE_QUERY_TEXT_START.search(line):
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        while j < len(lines) and (lines[j].lstrip().startswith("|") or not lines[j].strip()):
            block_lines.append(lines[j])
            j += 1
        yield i, block_lines
        i = j


def _iter_query_text_content_lines(start_idx: int, block_lines: list[str]):
    """Yield query text lines as ``(line_no, content_base, content, head, ended_query)``."""
    for offset, raw_line in enumerate(block_lines):
        stripped = raw_line.rstrip()
        if not stripped:
            continue

        is_first = offset == 0
        if is_first:
            quote_pos = raw_line.find('"')
            if quote_pos < 0:
                continue
            content_base = quote_pos + 1
            raw_content = raw_line[content_base:]
        else:
            pipe_pos = raw_line.find("|")
            if pipe_pos < 0:
                continue
            after_pipe = raw_line[pipe_pos + 1 :]
            leading_ws = len(after_pipe) - len(after_pipe.lstrip())
            content_base = pipe_pos + 1 + leading_ws
            raw_content = after_pipe.lstrip()

        content = _RE_BSL149_INLINE_COMMENT.sub("", raw_content).rstrip().lstrip()
        if not content:
            continue

        ended_query = '"' in content
        head = content.split('"', 1)[0].rstrip() if ended_query else content
        if not head:
            if ended_query:
                break
            continue

        yield start_idx + offset + 1, content_base, content, head, ended_query
        if ended_query:
            break


def _snapshot_query_blocks(lines: list[str], query_blocks: list[QueryTextBlockInfo] | None):
    if query_blocks is not None:
        for block in query_blocks:
            yield block.start_idx, list(block.block_lines)
        return
    yield from _iter_query_text_blocks(lines)


def _query_block_content_line_tuples(
    block: QueryTextBlockInfo,
) -> list[tuple[int, int, str, str, bool]]:
    return [
        (
            line.line_no,
            line.content_base,
            line.content,
            line.head,
            line.ended_query,
        )
        for line in block.content_lines
    ]


def _find_matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top_level_args(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    parts.append(text[start:])
    return parts


def _query_has_balanced_parens(lines: list[str]) -> bool:
    depth = 0
    for line in lines:
        for ch in line:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0


def _extract_call_argument_presence(
    content: str,
    line_starts: list[int],
    *,
    line: int,
    character: int,
    callee_name: str,
) -> list[bool] | None:
    """Return per-position argument presence for a call starting at ``line:character``."""
    if line <= 0 or line > len(line_starts):
        return None
    start = line_starts[line - 1] + character
    if start < 0 or start >= len(content):
        return None
    tail = content[start:]
    m = re.match(rf"{re.escape(callee_name)}\s*\(", tail, re.IGNORECASE)
    if not m:
        return None
    open_idx = start + m.end() - 1
    close_idx = _find_matching_paren(content, open_idx)
    if close_idx < 0:
        return None
    args_text = content[open_idx + 1 : close_idx]
    if not args_text.strip():
        return []
    return [bool(part.strip()) for part in _split_top_level_args(args_text)]


# BSL190 — FormDataToValue / ДанныеФормыВЗначение
_RE_BSL190_FORM_DATA = re.compile(r"\b(?:ДанныеФормыВЗначение|FormDataToValue)\s*\(", re.IGNORECASE)
# BSL197 — duplicate if/elseif branch detection
_RE_BSL197_IF = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE)
_RE_BSL197_ELSEIF = re.compile(r"^\s*(?:ИначеЕсли|ElseIf)\b", re.IGNORECASE)
_RE_BSL197_ELSE = re.compile(r"^\s*(?:Иначе|Else)\b", re.IGNORECASE)
_RE_BSL197_ENDIF = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)
# BSL198 — duplicate if/elseif condition (captures condition group)
_RE_BSL198_IF_COND = re.compile(
    r"^\s*(?:Если|If)\s+(.+?)\s+(?:Тогда|Then)\b", re.IGNORECASE | re.UNICODE
)
_RE_BSL198_ELSEIF_COND = re.compile(
    r"^\s*(?:ИначеЕсли|ElseIf)\s+(.+?)\s+(?:Тогда|Then)\b", re.IGNORECASE | re.UNICODE
)
# BSL-x module-level Перем / preprocessor lines
_RE_PERЕМ_LINE = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)
_RE_REGION_LINE = re.compile(r"^\s*#(?:Область|Region|КонецОбласти|EndRegion)\b", re.IGNORECASE)
_RE_PREPROC_LINE = re.compile(r"^\s*#", re.IGNORECASE)

# BSL007 — «read» of a simple identifier: LHS of ``Имя =`` does not count as a use.
_BSL007_SIMPLE_ASSIGN_AT_START = re.compile(r"^\s*(\w+)\s*=(?!=)", re.IGNORECASE)


def _bsl007_strip_double_quoted_segments(line: str) -> str:
    """Replace BSL string literals with spaces (doubled-quote escape)."""
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i] == '"':
            out.append(" ")
            j = i + 1
            while j < n:
                if line[j] == '"':
                    j += 1
                    if j < n and line[j] == '"':
                        j += 1
                    else:
                        break
                else:
                    j += 1
            i = j
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


def _bsl007_rhs_mentions_name(name: str, raw_line: str) -> bool:
    """True if *name* appears in the RHS of a leading ``name = …`` assignment on this line."""
    name_cf = name.casefold()
    code = raw_line.split("//", 1)[0]
    code_clean = _bsl007_strip_double_quoted_segments(code)
    m = _BSL007_SIMPLE_ASSIGN_AT_START.match(code_clean)
    if not m or m.group(1).casefold() != name_cf:
        return _bsl007_name_read_in_code_line(name, raw_line)
    tail = code_clean[m.end() :]
    return bool(re.search(rf"\b{re.escape(name)}\b", tail, re.IGNORECASE))


def _bsl007_name_read_in_code_line(name: str, raw_line: str) -> bool:
    """True if *name* is read on this line (not only as LHS of ``name =``)."""
    if not raw_line.strip() or raw_line.lstrip().startswith("//"):
        return False
    code = raw_line.split("//", 1)[0]
    code_clean = _bsl007_strip_double_quoted_segments(code)
    m = _BSL007_SIMPLE_ASSIGN_AT_START.match(code_clean)
    if m and m.group(1).casefold() == name.casefold():
        tail = code_clean[m.end() :]
        return bool(re.search(rf"\b{re.escape(name)}\b", tail, re.IGNORECASE))
    return bool(re.search(rf"\b{re.escape(name)}\b", code_clean, re.IGNORECASE))


def _bsl007_name_used_in_file(
    name: str,
    lines: list[str],
    *,
    assign_lhs_idx: int | None,
    lo: int,
    hi: int,
    skip_indices: set[int],
) -> bool:
    """Scan lines [lo, hi] inclusive; on *assign_lhs_idx* only the RHS of ``name =`` counts."""
    for j in range(lo, hi + 1):
        if j in skip_indices:
            continue
        ln = lines[j]
        if assign_lhs_idx is not None and j == assign_lhs_idx:
            if _bsl007_rhs_mentions_name(name, ln):
                return True
        elif _bsl007_name_read_in_code_line(name, ln):
            return True
    return False


@functools.lru_cache(maxsize=512)
def _compile_call_pattern(proc_name: str) -> re.Pattern[str]:
    """BSL129: cached per-name regex to avoid re-compile on every proc in every file."""
    return re.compile(r"(?<![.\w])" + re.escape(proc_name) + r"\s*\(", re.IGNORECASE)


def _arithmetic_missing_space_cols_in_line(line: str, in_str_at_start: bool = False) -> list[int]:
    """
    Returns 0-based columns where an arithmetic/comparison binary operator
    lacks a space on at least one side (BSLLS MissingSpace rule for +/-/*/%).
    Handles double-quoted strings and single-line comments.
    Detects unary +/- and skips them.
    """
    # Chars that indicate the previous token is a valid LHS of binary operator.
    _BINARY_LHS = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "0123456789_)]\"|'"
    )
    # Chars after which +/- is unary (not binary).
    _UNARY_AFTER = frozenset("(=[,+-*/%<>!&|~")

    # Strip comment: find // outside strings.
    stripped = line
    in_s = in_str_at_start
    for ci, ch in enumerate(line):
        if ch == '"':
            in_s = not in_s
        elif ch == "/" and not in_s and ci + 1 < len(line) and line[ci + 1] == "/":
            stripped = line[:ci]
            break

    cols: list[int] = []
    in_s = in_str_at_start
    in_sq = False  # inside single-quoted date/string literals '...'
    prev_non_space = ""
    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]
        if ch == '"' and not in_sq:
            in_s = not in_s
            prev_non_space = '"'
            i += 1
            continue
        if ch == "'" and not in_s:
            in_sq = not in_sq
            prev_non_space = "'"
            i += 1
            continue
        if in_s or in_sq:
            i += 1
            continue
        if ch in " \t":
            i += 1
            continue

        if ch in "+-*/%":
            # Check for ** (not in BSL but guard anyway).
            # Determine if binary operator.
            if ch in "+-" and prev_non_space not in _BINARY_LHS:
                # Unary.
                prev_non_space = ch
                i += 1
                continue
            # Space before: prev real char should have been a space.
            prev_ch = stripped[i - 1] if i > 0 else ""
            space_before = prev_ch in " \t"
            # Space after.
            next_ch = stripped[i + 1] if i + 1 < n else ""
            space_after = next_ch in " \t"
            if not space_before or not space_after:
                cols.append(i)
            prev_non_space = ch
            i += 1
            continue

        prev_non_space = ch
        i += 1

    return cols


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


# Standard technology acronyms used in 1C BSL identifiers — mixing Cyrillic base with a
# Latin acronym (e.g. HTTPЗапрос, JSONЗапись, XMLЧтение) is the accepted 1C platform
# convention, not a coding error.  BSLLS skips these implicitly via its built-in type
# knowledge.  We replicate the same skip with a set of known acronyms: if every
# contiguous Latin run inside a mixed-script identifier is one of these, the identifier
# is a well-known platform / technology name and should not be flagged as BSL208.
_BSL208_TECH_ACRONYMS: frozenset[str] = frozenset(
    {
        # Network protocols & data formats
        "HTTP",
        "HTTPS",
        "FTP",
        "SFTP",
        "FTPS",
        "SMTP",
        "POP",
        "IMAP",
        "TCP",
        "UDP",
        "IP",
        "TLS",
        "SSL",
        "URL",
        "URI",
        "UUID",
        "GUID",
        "REST",
        "SOAP",
        "WSDL",
        "API",
        # Data formats
        "JSON",
        "XML",
        "HTML",
        "XHTML",
        "XDTO",
        "XSL",
        "XSLT",
        "CSV",
        "ZIP",
        "PDF",
        "XLS",
        "XLSX",
        "DOCX",
        "ODT",
        "SQL",
        # Platform integration
        "COM",
        "OLE",
        "DLL",
        "EXE",
        "ADO",
        "ODP",
        # Misc abbreviations accepted in 1C names
        "ODATA",
    }
)

_RE_LATIN_RUNS = re.compile(r"[a-zA-Z]+")

# BSLLS allowTrailingPartsInAnotherLanguage=true (default):
# Words like ЮрФизЛицоID, СтавкаНДСID, МинДлинаИННпоXSD, СоздатьObjectID are allowed because
# the Latin part is only a trailing (or leading) suffix on an otherwise single-language root.
# Pattern: [Latin+][Cyrillic+] OR [Cyrillic+][Latin+], no interleaving.
_RE_BSL208_TRAILING_LANG = re.compile(
    # BSLLS allowTrailingPartsInAnotherLanguage=true: skip only ALL-CAPS abbreviation
    # suffixes/prefixes (e.g. ЮрФизЛицоID, МинДлинаИННпоXSD, HTMLОтчёт).
    # Mixed-script words like ИмяName (both parts are full words) are still flagged.
    r"^(?:[A-Z]{2,}[А-ЯЁ][А-Яа-яЁё]+[А-Яа-я0-9Ёё_]*"  # ALL-CAPS prefix + Cyrillic
    r"|[А-ЯЁ][А-Яа-яЁё]+[А-Яа-я0-9Ёё_]*[A-Z]{2,})$",  # Cyrillic + ALL-CAPS suffix
    re.UNICODE,
)


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
    r"(?:\w+(?:\.\w+)*)\s*\([^)]*\)"  # method call
    r"|(?:\w+(?:\.\w+)*)\s*="  # assignment
    r"|(?:Возврат|Return)\s+\S"  # return with value
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
    r"(?<![\"'\w.])"  # not preceded by string/word/dot
    r"-?(?:[2-9]\d*|\d{2,})"  # 2+ digit integer OR single digit >= 2
    r"(?:\.\d+)?"  # optional decimal part
    r"(?![\w.\"])",  # not followed by word/dot/quote
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
        "сообщить",
        "предупреждение",
        "вопрос",
        "описаниеошибки",
        "информацияобошибке",
        "новоеисключение",
        "типзнч",
        "тип",
        "значениезаполнено",
        "стрдлина",
        "лев",
        "прав",
        "сред",
        "стрнайти",
        "стрзаменить",
        "нрег",
        "врег",
        "сокрл",
        "сокрп",
        "сокрлп",
        "пустаястрока",
        "строка",
        "число",
        "булево",
        "дата",
        "окр",
        "цел",
        "abs",
        "макс",
        "мин",
        "текущаядата",
        "началодня",
        "конецдня",
        "началомесяца",
        "конецмесяца",
        "добавитьмесяц",
        "год",
        "месяц",
        "день",
        "стрразделить",
        "стрсоединить",
        "стрсодержит",
        "стрначинаетсяс",
        "стрзаканчиваетсяна",
        "символ",
        "кодсимвола",
        "формат",
        "стршаблон",
        # English aliases
        "message",
        "question",
        "errordescription",
        "errorinfo",
        "typeof",
        "type",
        "valueisfilled",
        "strlen",
        "left",
        "right",
        "mid",
        "strfind",
        "strreplace",
        "lower",
        "upper",
        "triml",
        "trimr",
        "trimall",
        "isblankstring",
        "string",
        "number",
        "boolean",
        "round",
        "int",
        "max",
        "min",
        "currentdate",
        "begofday",
        "endofday",
        "begofmonth",
        "endofmonth",
        "addmonth",
        "year",
        "month",
        "day",
        "strsplit",
        "strconcat",
        "strcontains",
        "strstartswith",
        "strendswith",
        "char",
        "charcode",
        "format",
        "strtemplate",
    }
)

# Выполнить / Execute dynamic code
_RE_EXECUTE_DYNAMIC = re.compile(
    r"^\s*(?:Выполнить|Execute)\s*\(",
    re.IGNORECASE,
)

# Module-level variable declaration (outside any proc/function)
# We reuse _RE_VAR_LOCAL for matching

# Literal True/False in If condition
_RE_IF_LITERAL = re.compile(
    r"^\s*(?:Если|If)\s+(?:Истина|True|Ложь|False)\b",
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
    r"\b(?:НЕ|Not)\s+(?:НЕ|Not)\b",
    re.IGNORECASE,
)

# Прервать/Break as last statement before КонецЦикла
_RE_BREAK = re.compile(r"^\s*(?:Прервать|Break)\s*;?\s*$", re.IGNORECASE)

# Deprecated modal input dialogs
_RE_INPUT_DIALOG = re.compile(
    r"\b(?:ВвестиЗначение|ВвестиЧисло|ВвестиДату|ВвестиСтроку"
    r"|InputValue|InputNumber|InputDate|InputString)\s*\(",
    re.IGNORECASE,
)

# Query text block: "ВЫБРАТЬ ... ИЗ ..."
_RE_QUERY_TEXT_START = re.compile(
    r'"\s*(?:ВЫБРАТЬ|SELECT)\b',
    re.IGNORECASE,
)
_RE_QUERY_WHERE = re.compile(
    r"\b(?:ГДЕ|WHERE)\b",
    re.IGNORECASE,
)
_RE_QUERY_TOP = re.compile(r"\b(?:ПЕРВЫЕ|TOP)\s+(\d+)\b", re.IGNORECASE)
_RE_QUERY_ORDER_BY = re.compile(r"\b(?:УПОРЯДОЧИТЬ|ORDER\s+BY)\b", re.IGNORECASE)
_RE_QUERY_UNION = re.compile(r"\b(?:ОБЪЕДИНИТЬ|UNION)\b", re.IGNORECASE)
_RE_QUERY_END_QUOTE = re.compile(r'[^|"]*"')

# Unconditional exit from method body (for unreachable code detection)
_RE_UNCONDITIONAL_EXIT = re.compile(
    r"^\s*(?:Возврат|Return|ВызватьИсключение|Raise)\b",
    re.IGNORECASE,
)

# String continuation line in BSL (| at the start for multiline literals)
_RE_STR_CONTINUATION = re.compile(r"^\s*\|", re.MULTILINE)

# ТекущаяДата / CurrentDate (non-UTC)
_RE_CURRENT_DATE = re.compile(
    r"\b(?:ТекущаяДата|CurrentDate)\s*\(",
    re.IGNORECASE,
)

# НачатьТранзакцию / BeginTransaction
_RE_BEGIN_TRANSACTION = re.compile(
    r"\b(?:НачатьТранзакцию|BeginTransaction)\s*\(",
    re.IGNORECASE,
)

# ЗафиксироватьТранзакцию / CommitTransaction or РоллбекТранзакции / RollbackTransaction
_RE_COMMIT_TRANSACTION = re.compile(
    r"\b(?:ЗафиксироватьТранзакцию|CommitTransaction"
    r"|ОтменитьТранзакцию|RollbackTransaction)\s*\(",
    re.IGNORECASE,
)

# ВызватьИсключение / Raise (not inside try)
_RE_RAISE = re.compile(
    r"^\s*(?:ВызватьИсключение|Raise)\b",
    re.IGNORECASE | re.MULTILINE,
)

# If/ElseIf/Else/EndIf detection (for MissingElseBranch)
_RE_IF_OPEN = re.compile(r"^\s*Если\b|^\s*If\b", re.IGNORECASE)
_RE_ELSEIF = re.compile(r"^\s*(?:ИначеЕсли|ElsIf)\b", re.IGNORECASE)
_RE_ELSE = re.compile(r"^\s*(?:Иначе|Else)\s*$|^\s*(?:Иначе|Else)\s*;?\s*$", re.IGNORECASE)
_RE_ENDIF = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)

# Procedure body header (BSL062/BSL064)
# Return with a value (BSL064 — Procedure returns value)
_RE_RETURN_VALUE = re.compile(
    r"^\s*(?:Возврат|Return)\s+\S",
    re.IGNORECASE | re.MULTILINE,
)

# Comment line (BSL065 — export method comment check)
_RE_COMMENT_LINE = re.compile(r"^\s*//")

_BSL175_ATTR_REPLACEMENTS: dict[str, str] = {
    "отображатьшкалу": "ОтображатьШкалы",
    "showscale": "ShowScales",
    "линиишкалы": "ЛинииШкал",
    "цветшкалы": "ЦветШкал",
    "отображатьподписишкалысерий": "ШкалаСерий.ПоложениеПодписейШкалы",
    "showseriesscalelabels": "SeriesScale.ScaleLabelLocation",
    "отображатьподписишкалыточек": "ШкалаТочек.ПоложениеПодписейШкалы",
    "showpointsscalelabels": "PointsScale.ScaleLabelLocation",
    "отображатьподписишкалызначений": "ШкалаЗначений.ПоложениеПодписейШкалы",
    "showvaluesscalelabels": "ValuesScale.ScaleLabelLocation",
    "отображатьлиниизначенийшкалы": "ШкалаЗначений.ОтображениеЛинийСетки",
    "showscalevaluelines": "ValuesScale.GridLinesShowMode",
    "форматшкалызначений": "ШкалаЗначений.ФорматПодписей",
    "valuescaleformat": "ValuesScale.LabelFormat",
    "ориентацияметок": "ШкалаТочек.ОриентацияПодписей",
    "labelsorientation": "PointsScale.LabelOrientation",
    "отображатьлегенду": (
        "одно из свойств ОбластьЛегендыДиаграммы, "
        "ОбластьЛегендыДиаграммыГанта или ОбластьЛегендыСводнойДиаграммы"
    ),
    "showlegend": (
        "one of the properties of ChartLegendArea, GanttChartLegendArea or PivotChartLegendArea"
    ),
    "отображатьзаголовок": (
        "одно из свойств ОбластьЗаголовкаДиаграммы, "
        "ОбластьЗаголовкаДиаграммыГанта или ОбластьЗаголовкаСводнойДиаграммы"
    ),
    "showtitle": (
        "one of the properties of ChartTitleArea, GanttChartTitleArea or PivotChartTitleArea"
    ),
    "палитрацветов": "ОписаниеПалитрыЦветов.ПалитраЦветов",
    "colorpalette": "ColorPaletteDescription.ColorPalette",
    "цветначалаградиентнойпалитры": "ОписаниеПалитрыЦветов.ЦветНачалаГрадиентнойПалитры",
    "gradientpalettestartcolor": "ColorPaletteDescription.GradientPaletteStartColor",
    "цветконцаградиентнойпалитры": "ОписаниеПалитрыЦветов.ЦветКонцаГрадиентнойПалитры",
    "gradientpaletteendcolor": "ColorPaletteDescription.GradientPaletteEndColor",
    "максимальноеколичествоцветовградиентнойпалитры": (
        "ОписаниеПалитрыЦветов.МаксимальноеКоличествоЦветовГрадиентнойПалитры"
    ),
    "gradientpalettemaxcolors": "ColorPaletteDescription.GradientPaletteMaxColors",
}
_BSL175_METHOD_REPLACEMENTS: dict[str, str] = {
    "получитьпалитру": "ОписаниеПалитрыЦветов.ПолучитьПалитру",
    "getpalette": "ColorPaletteDescription.GetPalette",
    "установитьпалитру": "ОписаниеПалитрыЦветов.УстановитьПалитру",
    "setpalette": "ColorPaletteDescription.SetPalette",
}
_BSL175_ENUM_REPLACEMENTS: dict[str, str] = {
    "ориентацияметокдиаграммы": "ОриентацияПодписейДиаграммы",
    "horizontal": "AlwaysHorizontal",
    "горизонтальная": "ГоризонтальнаяВсегда",
}
_BSL175_GLOBAL_METHODS = frozenset({"очиститьжурналрегистрации", "cleareventlog"})
_RE_BSL175_ATTRIBUTE = re.compile(
    r"\b(?:ОбластьПостроенияДиаграммы|ChartPlotArea|Диаграмма|Chart|"
    r"ДиаграммаГанта|GanttChart|СводнаяДиаграмма|PivotChart)\.(?P<name>\w+)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL175_CHILD_FORM_ITEMS = re.compile(
    r"\b(?:ГруппировкаПодчиненныхЭлементовФормы|ChildFormItemsGroup)\.(?P<name>\w+)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL175_GLOBAL_METHOD = re.compile(
    r"\b(?P<name>ОчиститьЖурналРегистрации|ClearEventLog)\s*\(",
    re.IGNORECASE,
)
_RE_BSL175_ENUM_NAME = re.compile(r"\b(?P<name>ОриентацияМетокДиаграммы)\b", re.IGNORECASE)

_BSL177_METHOD_REPLACEMENTS: dict[str, str] = {
    "установитькраткийзаголовокприложения": "КлиентскоеПриложение.УстановитьКраткийЗаголовок",
    "получитькраткийзаголовокприложения": "КлиентскоеПриложение.ПолучитьКраткийЗаголовок",
    "установитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.УстановитьЗаголовок",
    "получитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.ПолучитьЗаголовок",
    "текущийвариантосновногошрифтаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантОсновногоШрифта"
    ),
    "текущийвариантинтерфейсаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантИнтерфейса"
    ),
    "setshortapplicationcaption": "ClientApplication.SetShortCaption",
    "getshortapplicationcaption": "ClientApplication.GetShortCaption",
    "setclientapplicationcaption": "ClientApplication.SetCaption",
    "getclientapplicationcaption": "ClientApplication.GetCaption",
    "clientapplicationbasefontcurrentvariant": "ClientApplication.CurrentBaseFontVariant",
    "clientapplicationinterfacecurrentvariant": "ClientApplication.CurrentInterfaceVariant",
}
_RE_BSL177_GLOBAL_METHOD = re.compile(
    r"\b(?P<name>"
    r"УстановитьКраткийЗаголовокПриложения|ПолучитьКраткийЗаголовокПриложения|"
    r"УстановитьЗаголовокКлиентскогоПриложения|ПолучитьЗаголовокКлиентскогоПриложения|"
    r"ТекущийВариантОсновногоШрифтаКлиентскогоПриложения|"
    r"ТекущийВариантИнтерфейсаКлиентскогоПриложения|"
    r"SetShortApplicationCaption|GetShortApplicationCaption|"
    r"SetClientApplicationCaption|GetClientApplicationCaption|"
    r"ClientApplicationBaseFontCurrentVariant|ClientApplicationInterfaceCurrentVariant"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL179_MANAGED_FORM = re.compile(
    r"\b(?:Тип|Type)\s*\(\s*\"(?P<name>УправляемаяФорма|ManagedForm)\"\s*\)",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL195_GET_FORM = re.compile(
    r"(?P<name>ПолучитьФорму|GetForm)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL176_DEPRECATED_DOC = re.compile(
    r"(?:@deprecated\b|\bdeprecated\b|\bobsolete\b|\bустар(?:ел|ела|ело|евш\w*)\b)",
    re.IGNORECASE | re.UNICODE,
)

_RE_COMMON_MODULE_PATH = re.compile(r"(?:^|[/\\\\])CommonModules(?:[/\\\\])", re.IGNORECASE)
_RE_BSL180_DISABLE_SAFE_MODE = re.compile(
    r"\b(?P<name>"
    r"УстановитьБезопасныйРежим|SetSafeMode|"
    r"УстановитьОтключениеБезопасногоРежима|SetSafeModeDisabled"
    r")\s*\(\s*(?P<arg>[^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL184_EXECUTE_EXTERNAL_CODE = re.compile(
    r"\b(?P<name>Выполнить|Execute|Вычислить|Eval)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL185_EXTERNAL_APP = re.compile(
    r"\b(?P<name>"
    r"КомандаСистемы|System|ЗапуститьСистему|RunSystem|ЗапуститьПриложение|RunApp|"
    r"НачатьЗапускПриложения|BeginRunningApplication|ЗапуститьПриложениеАсинх|RunAppAsync|"
    r"ЗапуститьПрограмму|ОткрытьПроводник|ОткрытьФайл|ПерейтиПоНавигационнойСсылке|"
    r"GotoURL|ОткрытьНавигационнуюСсылку"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL188_FILESYSTEM_METHOD = re.compile(
    r"\b(?P<name>"
    r"ЗначениеВФайл|ValueToFile|КопироватьФайл|FileCopy|ОбъединитьФайлы|MergeFiles|"
    r"ПереместитьФайл|MoveFile|РазделитьФайл|SplitFile|СоздатьКаталог|CreateDirectory|"
    r"УдалитьФайлы|DeleteFiles|КаталогПрограммы|BinDir|КаталогВременныхФайлов|TempFilesDir|"
    r"КаталогДокументов|DocumentsDir|РабочийКаталогДанныхПользователя|UserDataWorkDir|"
    r"НачатьПодключениеРасширенияРаботыСФайлами|BeginAttachingFileSystemExtension|"
    r"НачатьУстановкуРасширенияРаботыСФайлами|BeginInstallFileSystemExtension|"
    r"УстановитьРасширениеРаботыСФайлами|InstallFileSystemExtension|"
    r"УстановитьРасширениеРаботыСФайламиАсинх|InstallFileSystemExtensionAsync|"
    r"ПодключитьРасширениеРаботыСФайламиАсинх|AttachFileSystemExtensionAsync|"
    r"КаталогВременныхФайловАсинх|TempFilesDirAsync|КаталогДокументовАсинх|DocumentsDirAsync|"
    r"НачатьПолучениеКаталогаВременныхФайлов|BeginGettingTempFilesDir|"
    r"НачатьПолучениеКаталогаДокументов|BeginGettingDocumentsDir|"
    r"НачатьПолучениеРабочегоКаталогаДанныхПользователя|BeginGettingUserDataWorkDir|"
    r"РабочийКаталогДанныхПользователяАсинх|UserDataWorkDirAsync|"
    r"КопироватьФайлАсинх|CopyFileAsync|НайтиФайлыАсинх|FindFilesAsync|"
    r"НачатьКопированиеФайла|BeginCopyingFile|НачатьПеремещениеФайла|BeginMovingFile|"
    r"НачатьПоискФайлов|BeginFindingFiles|НачатьСозданиеДвоичныхДанныхИзФайла|"
    r"BeginCreateBinaryDataFromFile|НачатьСозданиеКаталога|BeginCreatingDirectory|"
    r"НачатьУдалениеФайлов|BeginDeletingFiles|ПереместитьФайлАсинх|MoveFileAsync|"
    r"СоздатьДвоичныеДанныеИзФайлаАсинх|CreateBinaryDataFromFileAsync|"
    r"СоздатьКаталогАсинх|CreateDirectoryAsync|УдалитьФайлыАсинх|DeleteFilesAsync"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL188_FILESYSTEM_NEW = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?(?P<type>"
    r"File|Файл|xBase|HTMLWriter|ЗаписьHTML|HTMLReader|ЧтениеHTML|"
    r"FastInfosetReader|ЧтениеFastInfoset|FastInfosetWriter|ЗаписьFastInfoset|"
    r"XSLTransform|ПреобразованиеXSL|ZipFileWriter|ЗаписьZipФайла|ZipFileReader|"
    r"ЧтениеZipФайла|TextReader|ЧтениеТекста|TextWriter|ЗаписьТекста|TextExtraction|"
    r"ИзвлечениеТекста|BinaryData|ДвоичныеДанные|FileStream|ФайловыйПоток|"
    r"FileStreamsManager|МенеджерФайловыхПотоков|DataWriter|ЗаписьДанных|DataReader|ЧтениеДанных"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL203_INTERNET_NEW = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?(?P<type>"
    r"FTPСоединение|FTPConnection|HTTPСоединение|HTTPConnection|WSОпределения|WSDefinitions|"
    r"WSПрокси|WSProxy|ИнтернетПочтовыйПрофиль|InternetMailProfile|ИнтернетПочта|"
    r"InternetMail|Почта|Mail|HTTPЗапрос|HTTPRequest|ИнтернетПрокси|InternetProxy"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL226_OS_USERS = re.compile(
    r"\b(?P<name>ПользователиОС|OSUsers)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL247_SET_PRIVILEGED = re.compile(
    r"\b(?P<name>УстановитьПривилегированныйРежим|SetPrivilegedMode)\s*\(\s*(?P<arg>[^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL250_TEMPFILES = re.compile(
    r"\b(?P<name>КаталогВременныхФайлов|TempFilesDir)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL264_SYSTEM_INFO = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?(?P<type>\"СистемнаяИнформация\"|\"SystemInfo\"|СистемнаяИнформация|SystemInfo)",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL267_EXTERNAL_CODE_TOOLS = re.compile(
    r"\b(?:ВнешниеОбработки|ExternalDataProcessors|ВнешниеОтчеты|ExternalReports|"
    r"РасширенияКонфигурации|ConfigurationExtensions)\.(?P<name>Создать|Create|Подключить|Connect)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL270_MODAL_REPLACEMENTS: dict[str, str] = {
    "ВОПРОС": "ПоказатьВопрос",
    "DOQUERYBOX": "ShowQueryBox",
    "ОТКРЫТЬФОРМУМОДАЛЬНО": "ОткрытьФорму",
    "OPENFORMMODAL": "OpenForm",
    "ОТКРЫТЬЗНАЧЕНИЕ": "ПоказатьЗначение",
    "OPENVALUE": "ShowValue",
    "ПРЕДУПРЕЖДЕНИЕ": "ПоказатьПредупреждение",
    "DOMESSAGEBOX": "ShowMessageBox",
    "ВВЕСТИДАТУ": "ПоказатьВводДаты",
    "INPUTDATE": "ShowInputDate",
    "ВВЕСТИЗНАЧЕНИЕ": "ПоказатьВводЗначения",
    "INPUTVALUE": "ShowInputValue",
    "ВВЕСТИСТРОКУ": "ПоказатьВводСтроки",
    "INPUTSTRING": "ShowInputString",
    "ВВЕСТИЧИСЛО": "ПоказатьВводЧисла",
    "INPUTNUMBER": "ShowInputNumber",
    "УСТАНОВИТЬВНЕШНЮЮКОМПОНЕНТУ": "НачатьУстановкуВнешнейКомпоненты",
    "INSTALLADDIN": "BeginInstallAddIn",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьУстановкуРасширенияРаботыСФайлами",
    "INSTALLFILESYSTEMEXTENSION": "BeginInstallFileSystemExtension",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьУстановкуРасширенияРаботыСКриптографией",
    "INSTALLCRYPTOEXTENSION": "BeginInstallCryptoExtension",
    "ПОМЕСТИТЬФАЙЛ": "НачатьПомещениеФайла",
    "PUTFILE": "BeginPutFile",
}
_RE_BSL270_MODAL = re.compile(
    r"\b(?P<name>" + "|".join(re.escape(k) for k in _BSL270_MODAL_REPLACEMENTS) + r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL272_SYNC_REPLACEMENTS: dict[str, str] = {
    **_BSL270_MODAL_REPLACEMENTS,
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьПодключениеРасширенияРаботыСКриптографией",
    "ATTACHCRYPTOEXTENSION": "BeginAttachingCryptoExtension",
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьПодключениеРасширенияРаботыСФайлами",
    "ATTACHFILESYSTEMEXTENSION": "BeginAttachingFileSystemExtension",
    "КОПИРОВАТЬФАЙЛ": "НачатьКопированиеФайла",
    "FILECOPY": "BeginCopyingFile",
    "ПЕРЕМЕСТИТЬФАЙЛ": "НачатьПеремещениеФайла",
    "MOVEFILE": "BeginMovingFile",
    "НАЙТИФАЙЛЫ": "НачатьПоискФайлов",
    "FINDFILES": "BeginFindingFiles",
    "УДАЛИТЬФАЙЛЫ": "НачатьУдалениеФайлов",
    "DELETEFILES": "BeginDeletingFiles",
    "СОЗДАТЬКАТАЛОГ": "НачатьСозданиеКаталога",
    "CREATEDIRECTORY": "BeginCreatingDirectory",
    "КАТАЛОГВРЕМЕННЫХФАЙЛОВ": "НачатьПолучениеКаталогаВременныхФайлов",
    "TEMPFILESDIR": "BeginGettingTempFilesDir",
    "КАТАЛОГДОКУМЕНТОВ": "НачатьПолучениеКаталогаДокументов",
    "DOCUMENTSDIR": "BeginGettingDocumentsDir",
    "РАБОЧИЙКАТАЛОГДАННЫХПОЛЬЗОВАТЕЛЯ": "НачатьПолучениеРабочегоКаталогаДанныхПользователя",
    "USERDATAWORKDIR": "BeginGettingUserDataWorkDir",
    "ПОЛУЧИТЬФАЙЛЫ": "НачатьПолучениеФайлов",
    "GETFILES": "BeginGettingFiles",
    "ПОМЕСТИТЬФАЙЛЫ": "НачатьПомещениеФайлов",
    "PUTFILES": "BeginPuttingFiles",
    "ЗАПРОСИТЬРАЗРЕШЕНИЕПОЛЬЗОВАТЕЛЯ": "НачатьЗапросРазрешенияПользователя",
    "REQUESTUSERPERMISSION": "BeginRequestingUserPermission",
    "ЗАПУСТИТЬПРИЛОЖЕНИЕ": "НачатьЗапускПриложения",
    "RUNAPP": "BeginRunningApplication",
}
_RE_BSL272_SYNC = re.compile(
    r"\b(?P<name>" + "|".join(re.escape(k) for k in _BSL272_SYNC_REPLACEMENTS) + r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL171_ADJACENT_LITERALS = re.compile(r'"[^"]*"\s+"[^"]*"', re.UNICODE)
_RE_BSL251_TERNARY = re.compile(r"\?\s*\(", re.UNICODE)
_RE_BSL252_THIS_OBJECT_ASSIGN = re.compile(
    r"^\s*(?P<name>ЭтотОбъект|ThisObject)\s*=",
    re.IGNORECASE | re.UNICODE,
)
_BSL217_GET_FROM_TEMP_STORAGE_NAMES = frozenset(
    {"получитьизвременногохранилища", "getfromtempstorage"}
)
_BSL217_DELETE_FROM_TEMP_STORAGE_NAMES = frozenset(
    {"удалитьизвременногохранилища", "deletefromtempstorage"}
)
_RE_BSL268_FIND_BY_STRING = re.compile(
    r"\.(?P<name>НайтиПоНаименованию|FindByDescription|НайтиПоКоду|FindByCode|НайтиПоНомеру|FindByNumber)\s*\(\s*(?P<arg>\"[^\"]*\"|\d+)?",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL259_PREPROC_IF = re.compile(r"^\s*#(?:Если|If)\s+(?P<expr>.+?)\s+Тогда\s*$", re.IGNORECASE)
_BSL259_ALLOWED_PREPROC_SYMBOLS = frozenset(
    {
        "сервер",
        "клиент",
        "вебклиент",
        "webclient",
        "тонкийклиент",
        "thinclient",
        "толстыйклиент",
        "thickclient",
        "обычноеприложение",
        "ordinaryapplication",
        "управляемоеприложение",
        "managedapplication",
        "внешнеесоединение",
        "externalconnection",
        "мобильныйклиент",
        "mobileclient",
        "мобильноеустройствоклиент",
        "mobileappclient",
        "мобильныйавтономныйсервер",
        "mobileofflineserver",
        "linux",
        "windows",
        "macos",
        "debuginfo",
        "debug",
        "_",
    }
)
_BSL259_PREPROC_KEYWORDS = frozenset({"и", "или", "не", "and", "or", "not", "истина", "ложь"})
_BSL204_ILLEGAL_CHARS = {
    "\u00ad": 'Нужно исправить на правильный символ "-"',
    "\u2012": 'Нужно исправить на правильный символ "-"',
    "\u2013": 'Нужно исправить на правильный символ "-"',
    "\u2014": 'Нужно исправить на правильный символ "-"',
    "\u2015": 'Нужно исправить на правильный символ "-"',
    "\u2212": 'Нужно исправить на правильный символ "-"',
    "\u00a0": "Нужно заменить символ неразрывного пробела на обычный пробел",
}
_RE_BSL248_COMPILER_DIRECTIVE = re.compile(r"^\s*&(?:На|At)\w+", re.IGNORECASE | re.UNICODE)
_RE_BSL259_IDENTIFIER = re.compile(r"\b[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*\b", re.UNICODE)
# Form / module compiler directives before procedure (&НаКлиенте, &НаСервере, …)
_RE_FORM_COMPILER_DIRECTIVE_LINE = re.compile(r"^\s*&\S+")

# BSL066 — DeprecatedFind: only Найти() → СтрНайти() (BSLLS parity).
# Врег/НРег/СокрЛ/СокрП/СокрЛП/Символ/КодСимвола — current platform functions, NOT deprecated.
# Предупреждение/Вопрос/Сообщить — covered by UsingModalWindows / DeprecatedMessage rules.
# ВвестиЗначение/ВвестиЧисло/ВвестиДату/ВвестиСтроку — covered by BSL057 DeprecatedInputDialog.
_DEPRECATED_METHODS = frozenset(
    {
        "найти",  # Найти() for strings → СтрНайти()
        "find",  # English alias
    }
)
# Negative lookbehind for '.' excludes object method calls like Массив.Найти()
_RE_DEPRECATED_METHOD = re.compile(
    r"(?<!\.)(?<!\w)\b(?:"
    + "|".join(re.escape(m) for m in sorted(_DEPRECATED_METHODS))
    + r")\s*\(",
    re.IGNORECASE,
)

# Пока Истина Цикл / While True Do (BSL069)
_RE_WHILE_TRUE = re.compile(
    r"^\s*(?:Пока|While)\s+(?:Истина|True)\s+(?:Цикл|Do)\b",
    re.IGNORECASE,
)

# Перем declaration (BSL067)
_RE_VAR_DECL = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)
# Executable code (not comment, not blank, not Перем, not proc header)
_RE_EXECUTABLE_LINE = re.compile(
    r"^\s*(?!//|$|(?:Перем|Var)\b|(?:Процедура|Функция|Procedure|Function)\b|(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b)",
    re.IGNORECASE,
)

# Multiple statements on one line (BSL095): two assignments/calls separated by ;
# Simplified: a non-empty statement before ; and another after on the same line
_RE_MULTI_STMT = re.compile(
    r";\s*\w",  # ; followed by word char on same line
)

# ТекущаяДата() (BSL097)
_RE_CURRENT_DATE = re.compile(
    r"\b(?:ТекущаяДата|CurrentDate)\s*\(",
    re.IGNORECASE,
)

# NULL comparison (BSL093)
_RE_NULL_COMPARISON = re.compile(
    r"(?:=|<>)\s*(?:NULL|Null)\b|(?:NULL|Null)\s*(?:=|<>)",
    re.IGNORECASE,
)

# Compound no-op assignment (BSL094): += 0 or *= 1 or -= 0 or /= 1
_RE_NOOP_COMPOUND = re.compile(
    r"\w+\s*(?:\+=\s*0|-=\s*0|\*=\s*1|/=\s*1)\b",
)

# Transaction begin in loop (BSL089)
_RE_BEGIN_TRANSACTION = re.compile(
    r"\b(?:НачатьТранзакцию|BeginTransaction)\s*\(",
    re.IGNORECASE,
)

# Hardcoded connection string patterns (BSL090)
_RE_CONNECTION_STRING = re.compile(
    r"(?:Server\s*=|DSN\s*=|Driver\s*=|Database\s*=|Uid\s*=|Pwd\s*=)",
    re.IGNORECASE,
)

# Else after Return detection (BSL091)
_RE_RETURN_STMT = re.compile(r"^\s*(?:Возврат|Return)\b", re.IGNORECASE)
_RE_RETURN_SIMPLE_EXPR = re.compile(r"^\s*(?:Возврат|Return)\s+(.+?);?\s*$", re.IGNORECASE)

# HTTP request in loop (BSL086) — ПолучитьДанные, ВыполнитьЗапросHTTP, HTTPЗапрос etc.
_RE_HTTP_REQUEST = re.compile(
    r"(?:HTTPСоединение|HTTPConnection|HTTPЗапрос|HTTPRequest"
    r"|ПолучитьДанные|GetData|ОтправитьДанные|PutData"
    r"|ПолучитьСтроку|GetString|ОтправитьСтроку|PutString)\b",
    re.IGNORECASE,
)

# Новый/New object creation (BSL087)
_RE_NEW_OBJECT = re.compile(r"\bНовый\b|\bNew\b", re.IGNORECASE)

# // Parameters: comment section (BSL088)
_RE_PARAM_COMMENT = re.compile(r"//\s*(?:Параметры|Parameters)\s*:", re.IGNORECASE)

# Literal boolean in Если condition (BSL085)
_RE_LITERAL_BOOL_CONDITION = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:Истина|True|Ложь|False)\s+(?:Тогда|Then)\b",
    re.IGNORECASE,
)

# Exception block detection (BSL080)
_RE_EXCEPT_BLOCK = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
_RE_END_TRY = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
_RE_TRY_OPEN = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
_RE_ERROR_INFO = re.compile(r"(?:ИнформацияОбОшибке|ErrorInfo)\s*\(", re.IGNORECASE)

# Method chain length (BSL081): count dots in a non-comment line
_RE_DOT_CHAIN = re.compile(r"(?:\.\w+\s*\()+")

# SELECT * in query text (BSL077)
_RE_SELECT_STAR = re.compile(
    r"(?:ВЫБРАТЬ|SELECT)\s+\*",
    re.IGNORECASE,
)

# Raise without message (BSL078): ВызватьИсключение; or Raise; alone on line
_RE_RAISE_BARE = re.compile(
    r"^\s*(?:ВызватьИсключение|Raise)\s*;",
    re.IGNORECASE,
)

# Goto statement (BSL079)
_RE_GOTO = re.compile(
    r"^\s*(?:Перейти|Goto)\b",
    re.IGNORECASE,
)

# TODO/FIXME/HACK comment (BSL074)
_RE_TODO_COMMENT = re.compile(
    r"//\s*(?:TODO|FIXME|HACK|XXX)\b",
    re.IGNORECASE,
)

# Negative condition: line starts an Если/ElsIf and condition begins with НЕ/Not (BSL076)
_RE_NEGATIVE_CONDITION = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:НЕ|Not)\b",
    re.IGNORECASE,
)

# Выполнить() / Execute() — dynamic code execution (BSL098)
_RE_EXECUTE = re.compile(r"(?<!\.)(?:Выполнить|Execute)\s*\(", re.IGNORECASE)

# Exported Перем declaration (BSL108): Перем X Экспорт
_RE_EXPORTED_VAR = re.compile(
    r"^\s*(?:Перем|Var)\b[^;]*\bЭкспорт\b",
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
    r"(?:[А-ЯЁа-яё]+[A-Za-z]|[A-Za-z]+[А-ЯЁа-яё])\w*",
)

# BSL113 removed: in BSL '=' is ALWAYS a comparison operator, never assignment.
# Assignment is a statement-level construct only — there are no assignment
# expressions, so "assignment in condition" is impossible in BSL by design.

# Double negation: НЕ НЕ or Not Not (BSL115)
_RE_DOUBLE_NEGATION = re.compile(
    r"\b(?:НЕ|Not)\s+(?:НЕ|Not)\b",
    re.IGNORECASE,
)

# Прервать / Break (BSL125)
_RE_BREAK = re.compile(r"^\s*(?:Прервать|Break)\s*;", re.IGNORECASE)

# Продолжить / Continue (BSL126)
_RE_CONTINUE = re.compile(r"^\s*(?:Продолжить|Continue)\s*;", re.IGNORECASE)

# Comment that looks like commented-out code (BSL123): // contains = ; or ()
_RE_COMMENTED_CODE = re.compile(
    r"^\s*//\s*(?:"
    # BSL keywords at start of comment = commented-out control-flow code
    r"(?:Процедура|Функция|КонецПроцедуры|КонецФункции|Если|ИначеЕсли|Иначе|КонецЕсли"
    r"|Для|Пока|КонецЦикла|Попытка|Исключение|КонецПопытки|Возврат|Перем"
    r"|Function|Procedure|EndProcedure|EndFunction|If|ElsIf|Else|EndIf"
    r"|For|While|EndDo|Try|Except|EndTry|Return|Var)\b"
    # OR a line that looks like a statement (ends with ; or contains :=)
    r"|\w.*(?:;|:=)"
    r")",
    re.IGNORECASE,
)

# Hardcoded file path in string literal (BSL100)
_RE_HARDCODED_PATH = re.compile(
    r'"(?:[A-Za-z]:\\|/(?:home|usr|etc|var|opt|tmp)/)[^"]*"',
    re.IGNORECASE,
)

# Loop opening / closing for QueryInLoop and TooDeepNesting tracking
_RE_LOOP_FOR = re.compile(
    r"^\s*(?:Для|For|ДляКаждого|ForEach)\b",
    re.IGNORECASE,
)
_RE_LOOP_ENDDO = re.compile(r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE)

# SQL query start (BSL106)
_RE_SQL_SELECT = re.compile(r"(?:ВЫБРАТЬ|SELECT)\b", re.IGNORECASE)

# Вычислить() / Eval() — dynamic expression evaluation (BSL103)
_RE_EVAL = re.compile(r"\b(?:Вычислить|Eval)\s*\(", re.IGNORECASE)

# Приостановить() / Sleep() (BSL105)
_RE_SLEEP = re.compile(r"\b(?:Приостановить|Sleep)\s*\(", re.IGNORECASE)

# Тогда — Then keyword for EmptyThenBranch (BSL107)
_RE_THEN = re.compile(r"\b(?:Тогда|Then)\s*$", re.IGNORECASE)


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
_RE_COMMENT_ONLY_LINE = re.compile(r"^\s*//")

# BSL131 — EmptyRegion: #Область / #КонецОбласти markers (line-level, no name group)
_RE_REGION_OPEN_LINE = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
_RE_REGION_CLOSE_LINE = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)

# BSL132 — RepeatedStringLiteral: collect all double-quoted strings ≥ 3 chars
_RE_STRING_LITERAL = re.compile(r'"([^"]{3,})"')

# BSL133 — RequiredParamAfterOptional: detect optional params (have =)
_RE_PARAM_HAS_DEFAULT = re.compile(r"=")

# BSL134 — CyclomaticComplexity: decision-point keywords
_RE_MCCABE_BRANCH_BSL134 = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf|Пока|While|Для|For|ДляКаждого|ForEach"
    r"|Попытка|Try|Исключение|Except)\b",
    re.IGNORECASE,
)

# BSL135 — NestedFunctionCalls: word( ... word(
_RE_NESTED_CALL = re.compile(r"\w+\s*\([^)]*\w+\s*\(")

# BSL136 — MissingSpaceBeforeComment: non-whitespace immediately before //
_RE_NO_SPACE_BEFORE_COMMENT = re.compile(r"\S//")

# BSL137 — UseOfFindByDescription: slow search methods
_RE_FIND_BY_DESCRIPTION = re.compile(
    r"\b(?:НайтиПоНаименованию|FindByDescription"
    r"|НайтиПоКоду|FindByCode"
    r"|НайтиПоРеквизиту|FindByAttribute)\s*\(",
    re.IGNORECASE,
)

# BSL138 — UseOfDebugOutput: Сообщить()/Message()/Предупреждение()/Warning()
_RE_DEBUG_OUTPUT = re.compile(
    r"\b(?:Сообщить|Message|Предупреждение|Warning)\s*\(",
    re.IGNORECASE,
)

# BSL141 — MagicBooleanReturn
_RE_RETURN_TRUE = re.compile(
    r"^\s*(?:Возврат|Return)\s+(?:Истина|True)\s*;",
    re.IGNORECASE,
)
_RE_RETURN_FALSE = re.compile(
    r"^\s*(?:Возврат|Return)\s+(?:Ложь|False)\s*;",
    re.IGNORECASE,
)

# BSL143 — DuplicateElseIfCondition: extract condition text from Если/ИначеЕсли
_RE_IF_COND = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(.*?)\s+(?:Тогда|Then)\s*$",
    re.IGNORECASE,
)

# BSL144 — UnnecessaryParentheses: Возврат (expr)
_RE_RETURN_PAREN = re.compile(
    r"^\s*(?:Возврат|Return)\s+\((?!\s*(?:Новый|New)\b)",
    re.IGNORECASE,
)

# BSL145 — StringFormatInsteadOfConcat: 3+ string parts with +
_RE_MULTI_CONCAT = re.compile(r'"[^"]*"\s*\+[^+;]+\+[^+;]+\+')

# BSL147 — UseOfUICall: ОткрытьФорму()/OpenForm() etc.
_RE_UI_CALL = re.compile(
    r"\b(?:ОткрытьФорму|OpenForm|ПоказатьПредупреждение|ShowMessageBox"
    r"|ПоказатьВопрос|ShowQueryBox)\s*\(",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Standard region names (Russian + English)
# ---------------------------------------------------------------------------

_STANDARD_REGIONS_BY_KIND: dict[str, frozenset[str]] = {
    "manager": frozenset(
        {
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "обработчикисобытий",
            "инициализация",
            "public",
            "internal",
            "private",
            "eventhandlers",
            "initialize",
        }
    ),
    "object": frozenset(
        {
            "описаниепеременных",
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "обработчикисобытий",
            "инициализация",
            "variables",
            "public",
            "internal",
            "private",
            "eventhandlers",
            "initialize",
        }
    ),
    "form": frozenset(
        {
            "описаниепеременных",
            "обработчикисобытийформы",
            "обработчикисобытийэлементовшапкиформы",
            "обработчикикомандформы",
            "инициализация",
            "служебныепроцедурыифункции",
            "variables",
            "formeventhandlers",
            "formheaderitemseventhandlers",
            "formcommandseventhandlers",
            "initialize",
            "private",
        }
    ),
    "form-table-prefix": frozenset(
        {
            "обработчикисобытийэлементовтаблицыформы",
            "formtableitemseventhandlers",
        }
    ),
    "common": frozenset(
        {
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "public",
            "internal",
            "private",
        }
    ),
    "application": frozenset(
        {
            "описаниепеременных",
            "программныйинтерфейс",
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "variables",
            "public",
            "eventhandlers",
            "private",
        }
    ),
    "service": frozenset(
        {
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "eventhandlers",
            "private",
        }
    ),
    "external-connection": frozenset(
        {
            "программныйинтерфейс",
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "public",
            "eventhandlers",
            "private",
        }
    ),
}


def _standard_regions_for_path(path: str) -> frozenset[str]:
    low = path.replace("\\", "/").lower()
    if "/forms/" in low and low.endswith("/form/module.bsl"):
        return _STANDARD_REGIONS_BY_KIND["form"]
    if low.endswith("/ext/managermodule.bsl") or low.endswith("managermodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["manager"]
    if low.endswith("/ext/objectmodule.bsl") or low.endswith("objectmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["object"]
    if low.endswith("/ext/recordsetmodule.bsl") or low.endswith("recordsetmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["object"]
    if "/commonmodules/" in low:
        return _STANDARD_REGIONS_BY_KIND["common"]
    if low.endswith("applicationmodule.bsl") or low.endswith("managedapplicationmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["application"]
    if low.endswith("ordinaryapplicationmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["application"]
    if low.endswith("commandmodule.bsl") or low.endswith("sessionmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["service"]
    if low.endswith("httpservicemodule.bsl") or low.endswith("webservicemodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["service"]
    if low.endswith("externalconnectionmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["external-connection"]
    return frozenset()


def _is_standard_region_name_for_path(path: str, region_name: str) -> bool:
    name = region_name.strip().lower()
    allowed = _standard_regions_for_path(path)
    if not allowed:
        return True
    if name in allowed:
        return True
    table_prefixes = _STANDARD_REGIONS_BY_KIND["form-table-prefix"]
    return any(name.startswith(prefix) for prefix in table_prefixes)


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


def _ts_walk(node: Any):
    """Yield *node* and all descendants depth-first."""
    yield node
    for child in getattr(node, "children", []) or []:
        yield from _ts_walk(child)


def _ts_child_of_type(node: Any, node_type: str) -> Any | None:
    """First direct child of *node* with ``type == node_type``."""
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == node_type:
            return child
    return None


def _ts_method_identifier_span(node: Any, line_texts: list[str]) -> tuple[int, int, int] | None:
    """Return ``(line_1based, start_char, end_char)`` for method-call identifier."""
    ident = _ts_child_of_type(node, "identifier")
    if ident is None:
        return None
    line_idx = ident.start_point[0]
    line_text = line_texts[line_idx] if 0 <= line_idx < len(line_texts) else ""
    return (
        line_idx + 1,
        utf8_byte_offset_to_lsp_character(line_text, ident.start_point[1]),
        utf8_byte_offset_to_lsp_character(line_text, ident.end_point[1]),
    )


def _ts_global_method_calls(node: Any, line_texts: list[str]) -> list[dict[str, Any]]:
    """Collect global method calls under *node* in source order."""
    out: list[dict[str, Any]] = []
    for child in _ts_walk(node):
        if getattr(child, "type", None) != "method_call":
            continue
        if getattr(getattr(child, "parent", None), "type", None) == "call_expression":
            continue
        span = _ts_method_identifier_span(child, line_texts)
        if span is None:
            continue
        ident = _ts_child_of_type(child, "identifier")
        out.append(
            {
                "node": child,
                "name": _ts_node_text(ident),
                "line": span[0],
                "character": span[1],
                "end_character": span[2],
            }
        )
    return out


def _ts_method_call_arg_exprs(node: Any) -> list[Any]:
    """Return expression arguments for a ``method_call`` node."""
    args = _ts_child_of_type(node, "arguments")
    if args is None:
        return []
    return [child for child in getattr(args, "children", []) or [] if child.type == "expression"]


# BSL218 — BSLLS MissingTemporaryFileDeletion (global GetTempFileName + default delete methods)
_BSL218_GET_TEMP_NAMES = frozenset({"получитьимявременногофайла", "gettempfilename"})
_BSL218_DELETE_NAMES = frozenset(
    {
        "удалитьфайлы",
        "deletefiles",
        "начатьудалениефайлов",
        "begindeletingfiles",
        "переместитьфайл",
        "movefile",
    }
)
_BSL218_SKIP_PROC_CHILD = frozenset(
    {
        "PROCEDURE_KEYWORD",
        "FUNCTION_KEYWORD",
        "EXPORT_KEYWORD",
        "identifier",
        "parameters",
        "ENDPROCEDURE_KEYWORD",
        "ENDFUNCTION_KEYWORD",
    }
)


def _ts_bsl218_skip_error_ancestor(node: Any) -> Any:
    p = node
    while p is not None and getattr(p, "type", None) == "ERROR":
        p = getattr(p, "parent", None)
    return p


def _ts_assignment_lvalue_text(assign: Any) -> str | None:
    """Left-hand side source text for ``assignment_statement`` (BSLLS ``lValue``)."""
    if getattr(assign, "type", None) != "assignment_statement":
        return None
    parts: list[str] = []
    for child in getattr(assign, "children", []) or []:
        if getattr(child, "type", None) == "=":
            break
        parts.append(_ts_node_text(child))
    text = "".join(parts).strip()
    return text or None


def _ts_bsl218_if_then_branch_roots(if_node: Any) -> list[Any]:
    ch = list(getattr(if_node, "children", []) or [])
    try:
        then_i = next(i for i, c in enumerate(ch) if getattr(c, "type", None) == "THEN_KEYWORD")
    except StopIteration:
        return []
    roots: list[Any] = []
    for j in range(then_i + 1, len(ch)):
        ct = getattr(ch[j], "type", None)
        if ct in ("elseif_clause", "else_clause", "ENDIF_KEYWORD"):
            break
        roots.append(ch[j])
    return roots


def _ts_bsl218_roots_after_keyword(block_node: Any, keyword_type: str) -> list[Any]:
    ch = list(getattr(block_node, "children", []) or [])
    try:
        ki = next(i for i, c in enumerate(ch) if getattr(c, "type", None) == keyword_type)
    except StopIteration:
        return []
    return ch[ki + 1 :]


def _ts_bsl218_loop_body_roots(loop_node: Any) -> list[Any]:
    ch = list(getattr(loop_node, "children", []) or [])
    try:
        do_i = next(i for i, c in enumerate(ch) if getattr(c, "type", None) == "DO_KEYWORD")
    except StopIteration:
        return []
    try:
        end_i = next(
            i for i in range(do_i + 1, len(ch)) if getattr(ch[i], "type", None) == "ENDDO_KEYWORD"
        )
    except StopIteration:
        return []
    return ch[do_i + 1 : end_i]


def _ts_bsl218_try_body_roots(try_node: Any) -> list[Any]:
    ch = list(getattr(try_node, "children", []) or [])
    try:
        try_i = next(i for i, c in enumerate(ch) if getattr(c, "type", None) == "TRY_KEYWORD")
    except StopIteration:
        return []
    end_i = len(ch)
    for j in range(try_i + 1, len(ch)):
        if getattr(ch[j], "type", None) in ("EXCEPT_KEYWORD", "ENDTRY_KEYWORD"):
            end_i = j
            break
    return ch[try_i + 1 : end_i]


def _ts_bsl218_code_block_roots(stmt_parent: Any) -> list[Any] | None:
    """Map BSLLS ``codeBlock`` to tree-sitter subtree roots (per-branch, like BSLLS)."""
    t = getattr(stmt_parent, "type", None)
    if t in ("procedure_definition", "function_definition"):
        return [
            c
            for c in getattr(stmt_parent, "children", []) or []
            if getattr(c, "type", None) not in _BSL218_SKIP_PROC_CHILD
        ]
    if t == "source_file":
        return [
            c
            for c in getattr(stmt_parent, "children", []) or []
            if getattr(c, "type", None) != "preprocessor"
        ]
    if t == "if_statement":
        return _ts_bsl218_if_then_branch_roots(stmt_parent)
    if t == "elseif_clause":
        return _ts_bsl218_roots_after_keyword(stmt_parent, "THEN_KEYWORD")
    if t == "else_clause":
        return _ts_bsl218_roots_after_keyword(stmt_parent, "ELSE_KEYWORD")
    if t in ("while_statement", "for_statement", "for_each_statement"):
        return _ts_bsl218_loop_body_roots(stmt_parent)
    if t == "try_statement":
        return _ts_bsl218_try_body_roots(stmt_parent)
    return None


def _ts_bsl218_subtree_has_deletion_after_line(
    root: Any,
    line_texts: list[str],
    after_line_1based: int,
    var_name: str,
) -> bool:
    """True if a default BSLLS deletion global call passes *var_name* after *after_line*."""
    var_cf = var_name.casefold()
    for call in _ts_global_method_calls(root, line_texts):
        if call["line"] <= after_line_1based:
            continue
        if str(call["name"]).casefold() not in _BSL218_DELETE_NAMES:
            continue
        for expr in _ts_method_call_arg_exprs(call["node"]):
            if _ts_node_text(expr).strip().casefold() == var_cf:
                return True
    return False


def _ts_bsl218_block_has_deletion(
    roots: list[Any],
    line_texts: list[str],
    after_line_1based: int,
    var_name: str,
) -> bool:
    for r in roots:
        if _ts_bsl218_subtree_has_deletion_after_line(r, line_texts, after_line_1based, var_name):
            return True
    return False


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
_RE_BSL029_SIMPLE_ASSIGN = re.compile(r"^\s*[\w\.]+\s*=\s*-?[0-9]+(?:\.[0-9]+)?\s*;?\s*$")
# BSL029: For loop header — Для X = N По M Цикл — BSLLS does not flag loop bounds
_RE_BSL029_FOR_HEADER = re.compile(r"^\s*(?:Для|For)\b", re.IGNORECASE)
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
        cc += len(_RE_MCCABE_TERNARY.findall(line))
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
            "BSL016",  # NonStandardRegion — keep opt-in; BSLLS does not enable it in the strict parity slice
            "BSL018",  # RaiseWithLiteral — opt-in; bare literals are normal; extended syntax is optional
            "BSL038",  # StringConcatenationInLoop — no direct BSLLS equivalent (BSLLS doesn't flag this)
            "BSL058",  # QueryWithoutWhere — no BSLLS equivalent; all firings are FP vs BSLLS
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
            # "BSL148" enabled — AllFunctionPathMustHaveReturn implemented
            # "BSL149" enabled — AssignAliasFieldsInQuery implemented
            "BSL150",  # BadWords — off by default (BSLLS activatedByDefault=false); needs bad_words_pattern
            # "BSL151" enabled — BeginTransactionBeforeTryCatch implemented
            # "BSL152" enabled — CachedPublic (common module XML + Public/ПрограммныйИнтерфейс region)
            # "BSL153" enabled — CanonicalSpellingKeywords implemented
            "BSL154",  # CodeAfterAsyncCall — off by default (BSLLS activatedByDefault=false)
            # "BSL155" enabled — CodeBlockBeforeSub implemented
            # "BSL156" enabled — CodeOutOfRegion implemented
            # "BSL157" enabled — CommitTransactionOutsideTryCatch implemented
            # "BSL158" enabled — CommonModuleAssign (metadata index)
            # "BSL159" enabled — CommonModuleInvalidType (sibling module XML)
            # "BSL160" enabled — CommonModuleMissingAPI (export + Public/Internal region)
            # "BSL161"–"BSL168" enabled — CommonModuleName* (sibling module XML + name)
            "BSL169",  # CompilationDirectiveLost — TODO
            "BSL170",  # CompilationDirectiveNeedLess — TODO
            # "BSL171" enabled — CrazyMultilineString implemented
            # "BSL172" enabled — DataExchangeLoading implemented
            # "BSL173" enabled — DeletingCollectionItem implemented
            "BSL174",  # DenyIncompleteValues — TODO
            # "BSL175" enabled — DeprecatedAttributes8312 implemented
            # "BSL176" enabled — DeprecatedMethodCall implemented
            # "BSL177" enabled — DeprecatedMethods8310 implemented
            # "BSL178" enabled — DeprecatedMethods8317 implemented
            # "BSL179" enabled — DeprecatedTypeManagedForm implemented
            # "BSL180" enabled — DisableSafeMode implemented
            "BSL181",  # DuplicatedInsertionIntoCollection — TODO
            "BSL182",  # ExcessiveAutoTestCheck — TODO
            # "BSL183" enabled — ExecuteExternalCode implemented
            # "BSL184" enabled — ExecuteExternalCodeInCommonModule implemented
            # "BSL185" enabled — ExternalAppStarting implemented
            # "BSL186" enabled — ExtraCommas implemented
            "BSL187",  # FieldsFromJoinsWithoutIsNull — TODO
            "BSL188",  # FileSystemAccess implemented; off by default (BSLLS activatedByDefault=false)
            "BSL189",  # ForbiddenMetadataName — TODO
            # "BSL190" enabled — FormDataToValue implemented
            # "BSL191" enabled — FullOuterJoinQuery implemented
            # "BSL192" enabled — FunctionNameStartsWithGet implemented
            # "BSL193" enabled — FunctionOutParameter implemented
            # "BSL194" enabled — FunctionReturnsSamePrimitive implemented
            # "BSL195" enabled — GetFormMethod implemented
            "BSL196",  # GlobalContextMethodCollision8312 — TODO
            # "BSL197" enabled — IfElseDuplicatedCodeBlock implemented
            # "BSL198" enabled — IfElseDuplicatedCondition implemented
            # "BSL199" enabled — IfElseIfEndsWithElse implemented
            # "BSL200" enabled — IncorrectLineBreak implemented
            # "BSL201" enabled — IncorrectUseLikeInQuery implemented
            # "BSL202" enabled — IncorrectUseOfStrTemplate implemented
            "BSL203",  # InternetAccess implemented; off by default (BSLLS activatedByDefault=false)
            # "BSL204" enabled — InvalidCharacterInFile implemented
            # "BSL205" enabled — IsInRoleMethod implemented
            # "BSL206" enabled — JoinWithSubQuery implemented
            # "BSL207" enabled — JoinWithVirtualTable implemented
            # "BSL208" enabled — LatinAndCyrillicSymbolInWord implemented
            # "BSL209" enabled — LogicalOrInJoinQuerySection implemented
            # "BSL210" enabled — LogicalOrInTheWhereSectionOfQuery implemented
            "BSL211",  # MetadataObjectNameLength — TODO
            # "BSL212" enabled — MissedRequiredParameter implemented
            "BSL213",  # MissingCommonModuleMethod — TODO
            "BSL214",  # MissingEventSubscriptionHandler — TODO
            # "BSL215" enabled — MissingParameterDescription implemented
            # "BSL216" enabled — MissingSpace implemented
            "BSL217",  # MissingTempStorageDeletion implemented; off by default (BSLLS activatedByDefault=false)
            # "BSL218" enabled — MissingTemporaryFileDeletion implemented
            # "BSL220" enabled — MultilineStringInQuery implemented
            # "BSL221" enabled — MultilingualStringHasAllDeclaredLanguages implemented
            # "BSL222" enabled — MultilingualStringUsingWithTemplate implemented
            # "BSL223" enabled — NestedConstructorsInStructureDeclaration implemented
            # "BSL224" enabled — NestedFunctionInParameters implemented
            # "BSL225" enabled — NumberOfValuesInStructureConstructor implemented
            # "BSL226" enabled — OSUsersMethod implemented
            # "BSL227" enabled — OneStatementPerLine implemented
            # "BSL228" enabled — OrderOfParams implemented
            # "BSL229" enabled — OrdinaryAppSupport implemented
            # "BSL230" enabled — PairingBrokenTransaction implemented
            "BSL231",  # PrivilegedModuleMethodCall — TODO
            "BSL232",  # ProtectedModule — TODO
            # "BSL233" enabled — PublicMethodsDescription implemented
            # "BSL234" enabled — QueryNestedFieldsByDot implemented
            # "BSL235" enabled — QueryParseError implemented
            "BSL236",  # QueryToMissingMetadata — TODO
            # "BSL237" enabled — RedundantAccessToObject implemented
            "BSL238",  # RefOveruse — TODO
            # "BSL239" enabled — ReservedParameterNames implemented
            # "BSL240" enabled — RewriteMethodParameter implemented
            "BSL241",  # SameMetadataObjectAndChildNames — TODO
            "BSL242",  # ScheduledJobHandler — TODO
            # "BSL243" enabled — SelfInsertion implemented
            "BSL244",  # ServerCallsInFormEvents — TODO
            # "BSL245" enabled — ServerSideExportFormMethod implemented
            "BSL246",  # SetPermissionsForNewObjects — TODO
            # "BSL247" enabled — SetPrivilegedMode implemented
            # "BSL248" enabled — SeveralCompilerDirectives implemented
            # "BSL249" enabled — StyleElementConstructors implemented
            # "BSL250" enabled — TempFilesDir implemented
            "BSL251",  # TernaryOperatorUsage implemented; off by default (BSLLS activatedByDefault=false)
            # "BSL252" enabled — ThisObjectAssign implemented
            "BSL253",  # TimeoutsInExternalResources — TODO
            # "BSL254" enabled — TransferringParametersBetweenClientAndServer implemented via call index
            # "BSL255" enabled — TryNumber implemented
            # "BSL256" enabled — Typo (homoglyph Latin/Cyrillic in identifiers; BSLLS priority over BSL208)
            # "BSL257" enabled — UnaryPlusInConcatenation implemented
            # "BSL258" enabled — UnionAll implemented
            # "BSL259" enabled — UnknownPreprocessorSymbol implemented
            "BSL260",  # UnsafeFindByCode — TODO
            "BSL261",  # UnsafeSafeModeMethodCall — TODO
            # "BSL262" enabled — UsageWriteLogEvent implemented
            # "BSL263" enabled — UseLessForEach implemented
            "BSL264",  # UseSystemInformation implemented; off by default (BSLLS activatedByDefault=false)
            # "BSL265" enabled — UselessTernaryOperator implemented
            # "BSL266" enabled — UsingCancelParameter implemented
            # "BSL267" enabled — UsingExternalCodeTools implemented
            # "BSL268" enabled — UsingFindElementByString implemented
            # "BSL269" enabled — UsingLikeInQuery implemented
            # "BSL270" enabled — UsingModalWindows implemented
            # "BSL271" enabled — UsingObjectNotAvailableUnix implemented
            # "BSL272" enabled — UsingSynchronousCalls implemented
            # "BSL273" enabled — VirtualTableCallWithoutParameters implemented
            "BSL274",  # WrongDataPathForFormElements — TODO
            # "BSL275" enabled — WrongHttpServiceHandler implemented
            # "BSL276" enabled — WrongUseFunctionProceedWithCall implemented
            # "BSL277" enabled — WrongUseOfRollbackTransactionMethod implemented
            # "BSL278" enabled — WrongWebServiceHandler implemented
            # "BSL279" enabled — YoLetterUsage implemented
        }
    )

    # Default thresholds (class-level — can override in __init__)
    MAX_PROC_LINES: int = 200
    MAX_RETURNS: int = 3
    MAX_COGNITIVE_COMPLEXITY: int = 15
    MAX_MCCABE_COMPLEXITY: int = 20
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
        profile: str | None = None,
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
        bad_words_pattern: str = "",
        reserved_parameter_names_pattern: str = "",
        declared_languages: str = "ru",
        bsl148_loops_executed_at_least_once: bool = True,
    ) -> None:
        # tree_sitter.Parser is not thread-safe — one BslParser per thread unless a
        # single parser is injected (tests). Required for free-threaded CPython / LSP.
        self._injected_parser: BslParser | None = parser
        self._parser_tls = threading.local()
        self._symbol_index = symbol_index
        _user_select = normalize_rule_code_set(select) if select else None
        self._select: set[str] | None = merge_profile_with_select(
            profile,
            _user_select,
            _BSLLS_NAME_TO_CODE,
            default_disabled_codes=self.DEFAULT_DISABLED,
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
        self.bsl148_loops_executed_at_least_once = bsl148_loops_executed_at_least_once
        _bwp = bad_words_pattern.strip()
        try:
            self._bad_words_re: re.Pattern[str] | None = (
                re.compile(_bwp, re.IGNORECASE) if _bwp else None
            )
        except re.error:
            self._bad_words_re = None
        _rpp = reserved_parameter_names_pattern.strip()
        try:
            self._reserved_parameter_names_re: re.Pattern[str] | None = (
                re.compile(f"^(?:{_rpp})$", re.IGNORECASE) if _rpp else None
            )
        except re.error:
            self._reserved_parameter_names_re = None
        self._declared_languages = {
            part.strip().casefold() for part in declared_languages.split(",") if part.strip()
        } or {"ru"}

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
        self,
        path: str,
        content: str,
        *,
        symbol_index: Any | None = None,
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
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=0,
                    severity=Severity.ERROR,
                    code="BSL001",
                    message=f"Failed to parse content: {exc}",
                )
            ]
        return self._run_rules(path, content, tree, symbol_index=symbol_index)

    def check_file(
        self,
        path: str,
        tree: Any | None = None,
        *,
        symbol_index: Any | None = None,
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
        snapshot = build_document_snapshot(
            path,
            content=content,
            tree=tree,
            parser=self._get_parser(),
        )
        tree = snapshot.tree
        lines = snapshot.lines
        suppressions = _parse_suppressions(lines)

        # Precompute structural info once (shared across rules).
        # Prefer CST-based extraction (handles multi-line signatures, exact
        # boundaries); fall back to regex when tree-sitter is unavailable.
        tree_is_ts = snapshot.is_tree_sitter
        procs = snapshot.procedures
        proc_source = "ast" if tree_is_ts else "regex"
        regex_fallback_procs_used = 0 if tree_is_ts else 1
        regions = snapshot.regions
        regions_source = "ast" if tree_is_ts else "regex"
        regex_fallback_regions_used = 0 if tree_is_ts else 1
        last_metrics: dict[str, Any] = {
            "tree_is_ts": bool(tree_is_ts),
            "proc_source": proc_source,
            "regions_source": regions_source,
            "regex_fallback_procs_used": regex_fallback_procs_used,
            "regex_fallback_regions_used": regex_fallback_regions_used,
        }
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
            snapshot.proc_node_map if tree_is_ts else {}
        )
        _symbols = snapshot.symbols
        _calls = snapshot.calls
        _query_blocks = snapshot.query_text_blocks

        _rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]] = []

        if self._rule_enabled("BSL001"):
            _rule_tasks.append(("BSL001", lambda: self._rule_bsl001_syntax_errors(path, tree)))
        if self._rule_enabled("BSL002"):
            _rule_tasks.append(
                ("BSL002", lambda: self._rule_bsl002_method_size(path, lines, procs))
            )
        if self._rule_enabled("BSL003"):
            _rule_tasks.append(
                (
                    "BSL003",
                    lambda: self._rule_bsl003_non_export_in_api_region(path, lines, procs, regions),
                )
            )
        # BSL004 (EmptyCodeBlock) before BSL059: empty «Тогда» must report BSL004, not BooleanLiteralComparison.
        if self._rule_enabled("BSL004"):
            _rule_tasks.append(
                ("BSL004", lambda: self._rule_bsl004_empty_except(path, lines, tree))
            )
        if self._rule_enabled("BSL005"):
            _rule_tasks.append(
                ("BSL005", lambda: self._rule_bsl005_hardcode_network_address(path, lines))
            )
        if self._rule_enabled("BSL006"):
            _rule_tasks.append(("BSL006", lambda: self._rule_bsl006_hardcode_path(path, lines)))
        if self._rule_enabled("BSL007"):
            _rule_tasks.append(
                ("BSL007", lambda: self._rule_bsl007_unused_local_variable(path, lines, procs))
            )
        if self._rule_enabled("BSL008"):
            _rule_tasks.append(
                ("BSL008", lambda: self._rule_bsl008_too_many_returns(path, lines, procs))
            )
        if self._rule_enabled("BSL009"):
            _rule_tasks.append(("BSL009", lambda: self._rule_bsl009_self_assign(path, lines, tree)))
        if self._rule_enabled("BSL010"):
            _rule_tasks.append(
                ("BSL010", lambda: self._rule_bsl010_useless_return(path, lines, procs))
            )
        if self._rule_enabled("BSL011"):
            _rule_tasks.append(
                ("BSL011", lambda: self._rule_bsl011_cognitive_complexity(path, lines, procs))
            )
        if self._rule_enabled("BSL012"):
            _rule_tasks.append(
                ("BSL012", lambda: self._rule_bsl012_hardcode_credentials(path, lines))
            )
        if self._rule_enabled("BSL013"):
            _rule_tasks.append(("BSL013", lambda: self._rule_bsl013_commented_code(path, lines)))
        if self._rule_enabled("BSL014"):
            _rule_tasks.append(("BSL014", lambda: self._rule_bsl014_line_too_long(path, lines)))
        if self._rule_enabled("BSL015"):
            _rule_tasks.append(
                ("BSL015", lambda: self._rule_bsl015_optional_params_count(path, lines, procs))
            )
        if self._rule_enabled("BSL016"):
            _rule_tasks.append(
                ("BSL016", lambda: self._rule_bsl016_non_standard_region(path, lines, regions))
            )
        if self._rule_enabled("BSL017"):
            _rule_tasks.append(
                ("BSL017", lambda: self._rule_bsl017_export_in_command_module(path, lines, procs))
            )
        if self._rule_enabled("BSL018"):
            _rule_tasks.append(
                ("BSL018", lambda: self._rule_bsl018_raise_with_literal(path, lines, tree))
            )
        if self._rule_enabled("BSL019"):
            _rule_tasks.append(
                ("BSL019", lambda: self._rule_bsl019_cyclomatic_complexity(path, lines, procs))
            )
        if self._rule_enabled("BSL020"):
            _rule_tasks.append(
                ("BSL020", lambda: self._rule_bsl020_excessive_nesting(path, lines, procs))
            )
        if self._rule_enabled("BSL021"):
            _rule_tasks.append(
                ("BSL021", lambda: self._rule_bsl021_unused_val_parameter(path, lines, procs))
            )
        if self._rule_enabled("BSL022"):
            _rule_tasks.append(
                ("BSL022", lambda: self._rule_bsl022_deprecated_message(path, lines, procs))
            )
        if self._rule_enabled("BSL023"):
            _rule_tasks.append(("BSL023", lambda: self._rule_bsl023_service_tag(path, lines)))
        extend_style_comment_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
        )
        if self._rule_enabled("BSL025"):
            _rule_tasks.append(("BSL025", lambda: self._rule_bsl025_empty_statement(path, lines)))
        if self._rule_enabled("BSL026"):
            _rule_tasks.append(
                ("BSL026", lambda: self._rule_bsl026_empty_region(path, lines, regions))
            )
        if self._rule_enabled("BSL027"):
            _rule_tasks.append(("BSL027", lambda: self._rule_bsl027_use_goto(path, lines)))
        if self._rule_enabled("BSL028"):
            _rule_tasks.append(
                ("BSL028", lambda: self._rule_bsl028_missing_try_catch(path, lines, procs))
            )
        if self._rule_enabled("BSL029"):
            _rule_tasks.append(
                ("BSL029", lambda: self._rule_bsl029_magic_number(path, lines, procs))
            )
        if self._rule_enabled("BSL031"):
            _rule_tasks.append(
                ("BSL031", lambda: self._rule_bsl031_number_of_params(path, lines, procs))
            )
        if self._rule_enabled("BSL032"):
            _rule_tasks.append(
                ("BSL032", lambda: self._rule_bsl032_function_return_value(path, lines, procs))
            )
        if self._rule_enabled("BSL148"):
            _rule_tasks.append(
                ("BSL148", lambda: self._rule_bsl148_all_function_paths_return(path, tree))
            )
        if self._rule_enabled("BSL033"):
            _rule_tasks.append(
                ("BSL033", lambda: self._rule_bsl033_query_in_loop(path, lines, procs, tree))
            )
        if self._rule_enabled("BSL034"):
            _rule_tasks.append(
                ("BSL034", lambda: self._rule_bsl034_unused_error_variable(path, lines, procs))
            )
        if self._rule_enabled("BSL035"):
            _rule_tasks.append(
                ("BSL035", lambda: self._rule_bsl035_duplicate_string_literal(path, lines, procs))
            )
        if self._rule_enabled("BSL036"):
            _rule_tasks.append(("BSL036", lambda: self._rule_bsl036_complex_condition(path, lines)))
        if self._rule_enabled("BSL037"):
            _rule_tasks.append(
                ("BSL037", lambda: self._rule_bsl037_override_builtin(path, lines, procs))
            )
        if self._rule_enabled("BSL038"):
            _rule_tasks.append(
                (
                    "BSL038",
                    lambda: self._rule_bsl038_string_concat_in_loop(path, lines, procs, tree),
                )
            )
        if self._rule_enabled("BSL039"):
            _rule_tasks.append(("BSL039", lambda: self._rule_bsl039_nested_ternary(path, lines)))
        if self._rule_enabled("BSL040"):
            _rule_tasks.append(
                ("BSL040", lambda: self._rule_bsl040_using_this_form(path, lines, procs))
            )
        if self._rule_enabled("BSL041"):
            _rule_tasks.append(
                ("BSL041", lambda: self._rule_bsl041_deprecated_message(path, lines))
            )
        if self._rule_enabled("BSL042"):
            _rule_tasks.append(
                ("BSL042", lambda: self._rule_bsl042_empty_export_method(path, lines, procs))
            )
        if self._rule_enabled("BSL043"):
            _rule_tasks.append(
                ("BSL043", lambda: self._rule_bsl043_too_many_variables(path, lines, procs))
            )
        if self._rule_enabled("BSL044"):
            _rule_tasks.append(
                ("BSL044", lambda: self._rule_bsl044_function_no_return_value(path, lines, procs))
            )
        if self._rule_enabled("BSL045"):
            _rule_tasks.append(
                ("BSL045", lambda: self._rule_bsl045_multiline_string_literal(path, lines))
            )
        if self._rule_enabled("BSL046"):
            _rule_tasks.append(
                ("BSL046", lambda: self._rule_bsl046_missing_else_branch(path, lines, procs))
            )
        if self._rule_enabled("BSL047"):
            _rule_tasks.append(("BSL047", lambda: self._rule_bsl047_current_date(path, lines)))
        if self._rule_enabled("BSL048"):
            _rule_tasks.append(("BSL048", lambda: self._rule_bsl048_empty_file(path, lines)))
        if self._rule_enabled("BSL049"):
            _rule_tasks.append(
                ("BSL049", lambda: self._rule_bsl049_unconditional_raise(path, lines, procs))
            )
        if self._rule_enabled("BSL050"):
            _rule_tasks.append(
                ("BSL050", lambda: self._rule_bsl050_large_transaction(path, lines, procs))
            )
        if self._rule_enabled("BSL051"):
            _rule_tasks.append(
                (
                    "BSL051",
                    lambda: self._rule_bsl051_unreachable_code(path, lines, procs, tree),
                )
            )
        if self._rule_enabled("BSL052"):
            _rule_tasks.append(
                ("BSL052", lambda: self._rule_bsl052_useless_condition(path, lines, tree))
            )
        if self._rule_enabled("BSL053"):
            _rule_tasks.append(("BSL053", lambda: self._rule_bsl053_execute_dynamic(path, lines)))
        if self._rule_enabled("BSL054"):
            _rule_tasks.append(
                ("BSL054", lambda: self._rule_bsl054_module_level_variable(path, lines, procs))
            )
        if self._rule_enabled("BSL219"):
            _rule_tasks.append(
                (
                    "BSL219",
                    lambda: self._rule_bsl219_missing_variables_description(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL055"):
            _rule_tasks.append(
                ("BSL055", lambda: self._rule_bsl055_consecutive_blank_lines(path, lines))
            )
        if self._rule_enabled("BSL056"):
            _rule_tasks.append(
                ("BSL056", lambda: self._rule_bsl056_short_method_name(path, lines, procs))
            )
        if self._rule_enabled("BSL057"):
            _rule_tasks.append(
                ("BSL057", lambda: self._rule_bsl057_deprecated_input_dialog(path, lines))
            )
        if self._rule_enabled("BSL058"):
            _rule_tasks.append(
                ("BSL058", lambda: self._rule_bsl058_query_without_where(path, lines))
            )
        if self._rule_enabled("BSL059"):
            _rule_tasks.append(
                ("BSL059", lambda: self._rule_bsl059_bool_literal_comparison(path, lines, tree))
            )
        if self._rule_enabled("BSL060"):
            _rule_tasks.append(
                ("BSL060", lambda: self._rule_bsl060_double_negation(path, lines, tree))
            )
        if self._rule_enabled("BSL061"):
            _rule_tasks.append(
                ("BSL061", lambda: self._rule_bsl061_abrupt_loop_exit(path, lines, tree))
            )
        if self._rule_enabled("BSL062"):
            _rule_tasks.append(
                (
                    "BSL062",
                    lambda: self._rule_bsl062_unused_parameter(
                        path, lines, procs, tree, _proc_node_map
                    ),
                )
            )
        if self._rule_enabled("BSL063"):
            _rule_tasks.append(("BSL063", lambda: self._rule_bsl063_large_module(path, lines)))
        if self._rule_enabled("BSL064"):
            _rule_tasks.append(
                ("BSL064", lambda: self._rule_bsl064_procedure_returns_value(path, lines, procs))
            )
        if self._rule_enabled("BSL065"):
            _rule_tasks.append(
                ("BSL065", lambda: self._rule_bsl065_missing_export_comment(path, lines, procs))
            )
        if self._rule_enabled("BSL066"):
            _rule_tasks.append(
                ("BSL066", lambda: self._rule_bsl066_deprecated_platform_method(path, lines, procs))
            )
        if self._rule_enabled("BSL067"):
            _rule_tasks.append(
                ("BSL067", lambda: self._rule_bsl067_var_after_code(path, lines, procs))
            )
        if self._rule_enabled("BSL068"):
            _rule_tasks.append(("BSL068", lambda: self._rule_bsl068_too_many_elseif(path, lines)))
        if self._rule_enabled("BSL069"):
            _rule_tasks.append(("BSL069", lambda: self._rule_bsl069_infinite_loop(path, lines)))
        if self._rule_enabled("BSL070"):
            _rule_tasks.append(
                ("BSL070", lambda: self._rule_bsl070_empty_loop_body(path, lines, tree))
            )
        if self._rule_enabled("BSL071"):
            _rule_tasks.append(
                ("BSL071", lambda: self._rule_bsl071_magic_number(path, lines, procs))
            )
        if self._rule_enabled("BSL072"):
            _rule_tasks.append(
                ("BSL072", lambda: self._rule_bsl072_string_concat_in_loop(path, lines))
            )
        if self._rule_enabled("BSL073"):
            _rule_tasks.append(
                ("BSL073", lambda: self._rule_bsl073_missing_else_branch(path, lines))
            )
        if self._rule_enabled("BSL074"):
            _rule_tasks.append(("BSL074", lambda: self._rule_bsl074_todo_comment(path, lines)))
        if self._rule_enabled("BSL075"):
            _rule_tasks.append(
                (
                    "BSL075",
                    lambda: self._rule_bsl075_global_variable_modification(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL076"):
            _rule_tasks.append(
                ("BSL076", lambda: self._rule_bsl076_negative_condition_first(path, lines))
            )
        extend_query_top_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            query_blocks=_query_blocks,
        )
        if self._rule_enabled("BSL078"):
            _rule_tasks.append(
                ("BSL078", lambda: self._rule_bsl078_raise_without_message(path, lines))
            )
        if self._rule_enabled("BSL079"):
            _rule_tasks.append(("BSL079", lambda: self._rule_bsl079_using_goto(path, lines)))
        if self._rule_enabled("BSL080"):
            _rule_tasks.append(("BSL080", lambda: self._rule_bsl080_silent_catch(path, lines)))
        if self._rule_enabled("BSL081"):
            _rule_tasks.append(("BSL081", lambda: self._rule_bsl081_long_method_chain(path, lines)))
        if self._rule_enabled("BSL082"):
            _rule_tasks.append(
                ("BSL082", lambda: self._rule_bsl082_missing_newline_at_eof(path, lines))
            )
        if self._rule_enabled("BSL083"):
            _rule_tasks.append(
                ("BSL083", lambda: self._rule_bsl083_too_many_module_variables(path, lines, procs))
            )
        if self._rule_enabled("BSL084"):
            _rule_tasks.append(
                ("BSL084", lambda: self._rule_bsl084_function_with_no_return(path, lines, procs))
            )
        if self._rule_enabled("BSL085"):
            _rule_tasks.append(
                ("BSL085", lambda: self._rule_bsl085_literal_boolean_condition(path, lines, tree))
            )
        if self._rule_enabled("BSL086"):
            _rule_tasks.append(
                ("BSL086", lambda: self._rule_bsl086_http_request_in_loop(path, lines))
            )
        if self._rule_enabled("BSL087"):
            _rule_tasks.append(
                ("BSL087", lambda: self._rule_bsl087_object_creation_in_loop(path, lines))
            )
        if self._rule_enabled("BSL088"):
            _rule_tasks.append(
                ("BSL088", lambda: self._rule_bsl088_missing_parameter_comment(path, lines, procs))
            )
        if self._rule_enabled("BSL089"):
            _rule_tasks.append(
                ("BSL089", lambda: self._rule_bsl089_transaction_in_loop(path, lines))
            )
        if self._rule_enabled("BSL090"):
            _rule_tasks.append(
                ("BSL090", lambda: self._rule_bsl090_hardcoded_connection_string(path, lines))
            )
        if self._rule_enabled("BSL091"):
            _rule_tasks.append(
                (
                    "BSL091",
                    lambda: self._rule_bsl091_redundant_else_after_return(path, lines, procs, tree),
                )
            )
        if self._rule_enabled("BSL092"):
            _rule_tasks.append(
                ("BSL092", lambda: self._rule_bsl092_empty_else_block(path, lines, tree))
            )
        if self._rule_enabled("BSL093"):
            _rule_tasks.append(
                ("BSL093", lambda: self._rule_bsl093_comparison_to_null(path, lines))
            )
        if self._rule_enabled("BSL094"):
            _rule_tasks.append(("BSL094", lambda: self._rule_bsl094_noop_assignment(path, lines)))
        if self._rule_enabled("BSL095"):
            _rule_tasks.append(
                ("BSL095", lambda: self._rule_bsl095_multiple_statements_on_one_line(path, lines))
            )
        if self._rule_enabled("BSL096"):
            _rule_tasks.append(
                ("BSL096", lambda: self._rule_bsl096_undocumented_export_method(path, lines, procs))
            )
        if self._rule_enabled("BSL097"):
            _rule_tasks.append(
                ("BSL097", lambda: self._rule_bsl097_use_of_current_date(path, lines))
            )
        if self._rule_enabled("BSL098"):
            _rule_tasks.append(("BSL098", lambda: self._rule_bsl098_use_of_execute(path, lines)))
        if self._rule_enabled("BSL099"):
            _rule_tasks.append(
                ("BSL099", lambda: self._rule_bsl099_too_many_parameters(path, lines, procs))
            )
        if self._rule_enabled("BSL100"):
            _rule_tasks.append(
                ("BSL100", lambda: self._rule_bsl100_hardcoded_file_path(path, lines))
            )
        if self._rule_enabled("BSL101"):
            _rule_tasks.append(("BSL101", lambda: self._rule_bsl101_too_deep_nesting(path, lines)))
        if self._rule_enabled("BSL102"):
            _rule_tasks.append(("BSL102", lambda: self._rule_bsl102_large_module(path, lines)))
        if self._rule_enabled("BSL103"):
            _rule_tasks.append(("BSL103", lambda: self._rule_bsl103_use_of_eval(path, lines)))
        if self._rule_enabled("BSL104"):
            _rule_tasks.append(
                ("BSL104", lambda: self._rule_bsl104_missing_module_comment(path, lines))
            )
        if self._rule_enabled("BSL105"):
            _rule_tasks.append(("BSL105", lambda: self._rule_bsl105_use_of_sleep(path, lines)))
        if self._rule_enabled("BSL106"):
            _rule_tasks.append(("BSL106", lambda: self._rule_bsl106_query_in_loop(path, lines)))
        if self._rule_enabled("BSL107"):
            _rule_tasks.append(("BSL107", lambda: self._rule_bsl107_empty_then_branch(path, lines)))
        if self._rule_enabled("BSL108"):
            _rule_tasks.append(
                ("BSL108", lambda: self._rule_bsl108_use_of_global_variables(path, lines))
            )
        if self._rule_enabled("BSL109"):
            _rule_tasks.append(
                ("BSL109", lambda: self._rule_bsl109_negative_conditional_return(path, lines))
            )
        if self._rule_enabled("BSL110"):
            _rule_tasks.append(
                ("BSL110", lambda: self._rule_bsl110_string_concat_in_loop(path, lines))
            )
        if self._rule_enabled("BSL111"):
            _rule_tasks.append(
                ("BSL111", lambda: self._rule_bsl111_mixed_language_identifiers(path, lines))
            )
        if self._rule_enabled("BSL112"):
            _rule_tasks.append(
                ("BSL112", lambda: self._rule_bsl112_unterminated_transaction(path, lines))
            )
        if self._rule_enabled("BSL113"):
            _rule_tasks.append(
                ("BSL113", lambda: self._rule_bsl113_assignment_in_condition(path, lines))
            )
        if self._rule_enabled("BSL114"):
            _rule_tasks.append(("BSL114", lambda: self._rule_bsl114_empty_module(path, lines)))
        if self._rule_enabled("BSL115"):
            _rule_tasks.append(("BSL115", lambda: self._rule_bsl115_chained_negation(path, lines)))
        if self._rule_enabled("BSL116"):
            _rule_tasks.append(
                ("BSL116", lambda: self._rule_bsl116_use_of_obsolete_iterator(path, lines))
            )
        if self._rule_enabled("BSL117"):
            _rule_tasks.append(
                (
                    "BSL117",
                    lambda: self._rule_bsl117_procedure_called_as_function(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL118"):
            _rule_tasks.append(
                ("BSL118", lambda: self._rule_bsl118_function_returns_nothing(path, lines, procs))
            )
        if self._rule_enabled("BSL119"):
            _rule_tasks.append(("BSL119", lambda: self._rule_bsl119_line_too_long(path, lines)))
        if self._rule_enabled("BSL120"):
            _rule_tasks.append(
                ("BSL120", lambda: self._rule_bsl120_trailing_whitespace(path, lines))
            )
        if self._rule_enabled("BSL121"):
            _rule_tasks.append(("BSL121", lambda: self._rule_bsl121_tab_indentation(path, lines)))
        if self._rule_enabled("BSL122"):
            _rule_tasks.append(
                ("BSL122", lambda: self._rule_bsl122_unused_parameter(path, lines, procs))
            )
        if self._rule_enabled("BSL123"):
            _rule_tasks.append(
                ("BSL123", lambda: self._rule_bsl123_commented_out_code(path, lines))
            )
        if self._rule_enabled("BSL124"):
            _rule_tasks.append(
                ("BSL124", lambda: self._rule_bsl124_short_procedure_name(path, lines, procs))
            )
        if self._rule_enabled("BSL125"):
            _rule_tasks.append(
                ("BSL125", lambda: self._rule_bsl125_break_outside_loop(path, lines))
            )
        if self._rule_enabled("BSL126"):
            _rule_tasks.append(
                ("BSL126", lambda: self._rule_bsl126_continue_outside_loop(path, lines))
            )
        if self._rule_enabled("BSL127"):
            _rule_tasks.append(
                ("BSL127", lambda: self._rule_bsl127_multiple_return_values(path, lines, procs))
            )
        if self._rule_enabled("BSL128"):
            _rule_tasks.append(
                ("BSL128", lambda: self._rule_bsl128_dead_code_after_return(path, lines, procs))
            )
        if self._rule_enabled("BSL129"):
            _rule_tasks.append(
                ("BSL129", lambda: self._rule_bsl129_recursive_call(path, lines, procs))
            )
        if self._rule_enabled("BSL130"):
            _rule_tasks.append(("BSL130", lambda: self._rule_bsl130_long_comment_line(path, lines)))
        if self._rule_enabled("BSL131"):
            _rule_tasks.append(
                ("BSL131", lambda: self._rule_bsl131_duplicate_region(path, lines, regions))
            )
        if self._rule_enabled("BSL132"):
            _rule_tasks.append(
                ("BSL132", lambda: self._rule_bsl132_repeated_string_literal(path, lines, content))
            )
        if self._rule_enabled("BSL133"):
            _rule_tasks.append(
                (
                    "BSL133",
                    lambda: self._rule_bsl133_required_param_after_optional(path, lines, procs),
                )
            )
        if self._rule_enabled("BSL134"):
            _rule_tasks.append(
                ("BSL134", lambda: self._rule_bsl134_cyclomatic_complexity(path, lines, procs))
            )
        if self._rule_enabled("BSL135"):
            _rule_tasks.append(
                ("BSL135", lambda: self._rule_bsl135_nested_function_calls(path, lines))
            )
        extend_style_spacing_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
        )
        if self._rule_enabled("BSL137"):
            _rule_tasks.append(
                ("BSL137", lambda: self._rule_bsl137_use_of_find_by_description(path, lines))
            )
        if self._rule_enabled("BSL138"):
            _rule_tasks.append(
                ("BSL138", lambda: self._rule_bsl138_use_of_debug_output(path, lines))
            )
        if self._rule_enabled("BSL139"):
            _rule_tasks.append(
                ("BSL139", lambda: self._rule_bsl139_too_long_parameter_name(path, lines, procs))
            )
        if self._rule_enabled("BSL140"):
            _rule_tasks.append(
                ("BSL140", lambda: self._rule_bsl140_unreachable_elseif(path, lines))
            )
        if self._rule_enabled("BSL141"):
            _rule_tasks.append(
                ("BSL141", lambda: self._rule_bsl141_magic_boolean_return(path, lines, procs))
            )
        if self._rule_enabled("BSL142"):
            _rule_tasks.append(
                ("BSL142", lambda: self._rule_bsl142_large_param_default_value(path, lines, procs))
            )
        if self._rule_enabled("BSL143"):
            _rule_tasks.append(
                ("BSL143", lambda: self._rule_bsl143_duplicate_elseif_condition(path, lines))
            )
        if self._rule_enabled("BSL144"):
            _rule_tasks.append(
                ("BSL144", lambda: self._rule_bsl144_unnecessary_parentheses(path, lines))
            )
        if self._rule_enabled("BSL145"):
            _rule_tasks.append(
                ("BSL145", lambda: self._rule_bsl145_string_format_instead_of_concat(path, lines))
            )
        if self._rule_enabled("BSL146"):
            _rule_tasks.append(
                ("BSL146", lambda: self._rule_bsl146_module_initialization_code(path, lines, procs))
            )
        if self._rule_enabled("BSL147"):
            _rule_tasks.append(
                ("BSL147", lambda: self._rule_bsl147_use_of_ui_call(path, lines, procs))
            )
        if self._rule_enabled("BSL151"):
            _rule_tasks.append(
                ("BSL151", lambda: self._rule_bsl151_begin_transaction_before_try(path, lines))
            )
        if self._rule_enabled("BSL152"):
            _rule_tasks.append(
                ("BSL152", lambda: self._rule_bsl152_cached_public(path, lines, regions, procs))
            )
        if self._rule_enabled("BSL154"):
            _rule_tasks.append(
                ("BSL154", lambda: self._rule_bsl154_code_after_async(path, lines, procs))
            )
        if self._rule_enabled("BSL155"):
            _rule_tasks.append(
                ("BSL155", lambda: self._rule_bsl155_code_block_before_sub(path, lines, procs))
            )
        if self._rule_enabled("BSL156"):
            _rule_tasks.append(
                ("BSL156", lambda: self._rule_bsl156_code_out_of_region(path, lines, procs))
            )
        if self._rule_enabled("BSL157"):
            _rule_tasks.append(
                ("BSL157", lambda: self._rule_bsl157_commit_transaction_outside_try(path, lines))
            )
        if self._rule_enabled("BSL158") and idx is not None:
            _rule_tasks.append(
                ("BSL158", lambda: self._rule_bsl158_common_module_assign(path, lines, idx))
            )
        if self._rule_enabled("BSL159"):
            _rule_tasks.append(
                ("BSL159", lambda: self._rule_bsl159_common_module_invalid_type(path, lines))
            )
        if self._rule_enabled("BSL160"):
            _rule_tasks.append(
                (
                    "BSL160",
                    lambda: self._rule_bsl160_common_module_missing_api(
                        path, lines, regions, procs
                    ),
                )
            )
        _bsl161_168 = (
            "BSL161",
            "BSL162",
            "BSL163",
            "BSL164",
            "BSL165",
            "BSL166",
            "BSL167",
            "BSL168",
        )
        if any(self._rule_enabled(c) for c in _bsl161_168):
            _rule_tasks.append(
                (
                    "BSL161-168",
                    lambda: self._rule_bsl161_168_common_module_names(path, lines, _bsl161_168),
                )
            )
        if self._rule_enabled("BSL173"):
            _rule_tasks.append(
                ("BSL173", lambda: self._rule_bsl173_deleting_collection_item(path, lines, procs))
            )
        if self._rule_enabled("BSL257"):
            _rule_tasks.append(
                ("BSL257", lambda: self._rule_bsl257_unary_plus_in_concatenation(path, lines))
            )
        if self._rule_enabled("BSL279"):
            _rule_tasks.append(("BSL279", lambda: self._rule_bsl279_yo_letter_usage(path, lines)))
        if self._rule_enabled("BSL280") and idx is not None:

            def _task_bsl280() -> list[Diagnostic]:
                from onec_hbk_bsl.analysis.metadata_refs import diagnostics_unknown_metadata_objects

                return diagnostics_unknown_metadata_objects(path, content, idx)

            _rule_tasks.append(("BSL280", _task_bsl280))
        if self._rule_enabled("BSL172"):
            _rule_tasks.append(
                ("BSL172", lambda: self._rule_bsl172_data_exchange_loading(path, lines, procs))
            )
        if self._rule_enabled("BSL149"):
            _rule_tasks.append(
                ("BSL149", lambda: self._rule_bsl149_assign_alias_fields_in_query(path, lines))
            )
        if self._rule_enabled("BSL210"):
            _rule_tasks.append(
                ("BSL210", lambda: self._rule_bsl210_logical_or_in_where(path, lines))
            )
        if self._rule_enabled("BSL150"):
            _rule_tasks.append(("BSL150", lambda: self._rule_bsl150_bad_words(path, lines)))
        if self._rule_enabled("BSL186"):
            _rule_tasks.append(("BSL186", lambda: self._rule_bsl186_extra_commas(path, lines)))
        if self._rule_enabled("BSL190"):
            _rule_tasks.append(
                ("BSL190", lambda: self._rule_bsl190_form_data_to_value(path, lines))
            )
        if self._rule_enabled("BSL197"):
            _rule_tasks.append(
                ("BSL197", lambda: self._rule_bsl197_if_else_duplicated_code_block(path, lines))
            )
        if self._rule_enabled("BSL178"):
            _rule_tasks.append(
                ("BSL178", lambda: self._rule_bsl178_deprecated_methods_8317(path, lines, tree))
            )
        if self._rule_enabled("BSL198"):
            _rule_tasks.append(
                ("BSL198", lambda: self._rule_bsl198_if_else_duplicated_condition(path, lines))
            )
        if self._rule_enabled("BSL258"):
            _rule_tasks.append(("BSL258", lambda: self._rule_bsl258_union_without_all(path, lines)))
        if self._rule_enabled("BSL183"):
            _rule_tasks.append(
                ("BSL183", lambda: self._rule_bsl183_execute_external_code(path, lines))
            )
        if self._rule_enabled("BSL208") or self._rule_enabled("BSL256"):

            def _task_bsl208_bsl256() -> list[Diagnostic]:
                out = self._rule_bsl208_bsl256_latin_cyrillic_and_typo(path, lines, procs)
                if self._rule_enabled("BSL256"):
                    out.extend(self._rule_bsl256_bslls_typo_spellcheck(path, tree))
                return out

            _rule_tasks.append(("BSL208_BSL256", _task_bsl208_bsl256))
        if self._rule_enabled("BSL230"):
            _rule_tasks.append(
                ("BSL230", lambda: self._rule_bsl230_pairing_broken_transaction(path, tree))
            )
        if self._rule_enabled("BSL263"):
            _rule_tasks.append(
                ("BSL263", lambda: self._rule_bsl263_useless_for_each(path, lines, procs))
            )
        if self._rule_enabled("BSL265"):
            _rule_tasks.append(
                ("BSL265", lambda: self._rule_bsl265_useless_ternary_operator(path, lines))
            )
        if self._rule_enabled("BSL262"):
            _rule_tasks.append(
                ("BSL262", lambda: self._rule_bsl262_usage_write_log_event(path, tree))
            )
        extend_style_token_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
        )
        if self._rule_enabled("BSL199"):
            _rule_tasks.append(
                ("BSL199", lambda: self._rule_bsl199_if_else_if_ends_with_else(path, lines))
            )
        extend_security_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            tree=tree,
            symbols=_symbols,
            calls=_calls,
            procs=procs,
        )
        extend_query_text_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            query_blocks=_query_blocks,
        )
        extend_method_contract_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            content=content,
            lines=lines,
            procs=procs,
            tree=tree,
            calls=_calls,
            proc_node_map=_proc_node_map,
        )
        extend_metadata_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            content=content,
            lines=lines,
            tree=tree,
            procs=procs,
        )
        extend_query_join_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            query_blocks=_query_blocks,
        )
        extend_query_metadata_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            query_blocks=_query_blocks,
        )
        if self._rule_enabled("BSL225"):
            _rule_tasks.append(
                (
                    "BSL225",
                    lambda: self._rule_bsl225_number_of_values_in_structure_constructor(
                        path, lines, tree
                    ),
                )
            )
        if self._rule_enabled("BSL218"):
            _rule_tasks.append(
                (
                    "BSL218",
                    lambda: self._rule_bsl218_missing_temporary_file_deletion(path, lines, tree),
                )
            )
        if self._rule_enabled("BSL234"):
            _rule_tasks.append(
                ("BSL234", lambda: self._rule_bsl234_query_nested_fields_by_dot(path, lines))
            )
        if self._rule_enabled("BSL237"):
            _rule_tasks.append(
                ("BSL237", lambda: self._rule_bsl237_redundant_access_to_object(path, lines))
            )
        if self._rule_enabled("BSL245"):
            _rule_tasks.append(
                (
                    "BSL245",
                    lambda: self._rule_bsl245_server_side_export_form_method(path, lines, procs),
                )
            )
        extend_style_tail_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
        )
        if self._rule_enabled("BSL255"):
            _rule_tasks.append(("BSL255", lambda: self._rule_bsl255_try_number(path, lines)))
        if self._rule_enabled("BSL277"):
            _rule_tasks.append(
                ("BSL277", lambda: self._rule_bsl277_wrong_use_of_rollback_transaction(path, tree))
            )
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
            first_body = None
            last_body = None
            for idx in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                stripped = lines[idx].strip()
                if not stripped:
                    continue
                if first_body is None:
                    first_body = idx
                last_body = idx
            length = 0 if first_body is None or last_body is None else last_body - first_body
            if length > self.max_proc_lines:
                start_col, end_col = _proc_name_span(lines, proc)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=start_col,
                        end_line=proc.start_idx + 1,
                        end_character=end_col,
                        severity=Severity.WARNING,
                        code="BSL002",
                        message=(
                            f'Длина метода "{proc.name}" равна {length}, '
                            f"что больше установленного лимита в {self.max_proc_lines} строк"
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

    def _rule_bsl004_empty_except(self, path: str, lines: list[str], tree: Any) -> list[Diagnostic]:
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
            # Skip lines whose context mentions version-related keywords (BSLLS skipStatement)
            if _RE_BSL005_VERSION_CONTEXT.search(line):
                continue
            for m in _RE_HARDCODE_NET.finditer(line):
                matched = m.group().strip('"')
                # Skip popular version-like prefixes (BSLLS searchPopularVersionExclusion)
                if _RE_BSL005_POPULAR_VERSION.match(matched):
                    continue
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

    def _rule_bsl006_hardcode_path(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
        inside_proc: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside_proc.add(i)

        # --- Module-level simple assigns (BSLLS UnusedLocalVariable on top-level code) ---
        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _RE_REGION_LINE.match(line) or _RE_PREPROC_LINE.match(line):
                continue
            if _RE_COMPILER_DIRECTIVE.match(stripped):
                continue
            m = _RE_MODULE_ASSIGN.match(line)
            if not m:
                continue
            var_name = m.group(1)
            if _bsl007_name_used_in_file(
                var_name,
                lines,
                assign_lhs_idx=idx,
                lo=0,
                hi=len(lines) - 1,
                skip_indices=set(),
            ):
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=line.find(var_name) if var_name in line else 0,
                    end_line=idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.WARNING,
                    code="BSL007",
                    message=f"Удалите неиспользуемую переменную {var_name}",
                )
            )

        for proc in procs:
            proc_lines = lines[proc.start_idx : proc.end_idx + 1]
            param_cf = {p.casefold() for p in proc.params}

            # --- Pass 1: collect all Перем declarations (O(L)) ---
            declared: list[tuple[str, int]] = []  # (var_name, rel_idx in proc_lines)
            decl_rel_indices: set[int] = set()
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                m = _RE_VAR_LOCAL.match(pline)
                if not m:
                    continue
                decl_rel_indices.add(rel_idx)
                for var_name in (n.strip() for n in m.group("names").split(",") if n.strip()):
                    declared.append((var_name, rel_idx))

            declared_cf = {n.casefold() for n, _ in declared}
            body_lo = proc.start_idx + 1
            body_hi = proc.end_idx - 1

            for var_name, rel_idx in declared:
                abs_decl = proc.start_idx + rel_idx
                skip_one = {abs_decl}
                if _bsl007_name_used_in_file(
                    var_name,
                    lines,
                    assign_lhs_idx=None,
                    lo=body_lo,
                    hi=body_hi,
                    skip_indices=skip_one,
                ):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=abs_decl + 1,
                        character=lines[abs_decl].find(var_name)
                        if var_name in lines[abs_decl]
                        else 0,
                        end_line=abs_decl + 1,
                        end_character=len(lines[abs_decl].rstrip()),
                        severity=Severity.WARNING,
                        code="BSL007",
                        message=f"Удалите неиспользуемую переменную {var_name}",
                    )
                )

            # --- Implicit locals: ``Имя =`` without preceding ``Перем`` in this proc ---
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                m = _RE_MODULE_ASSIGN.match(pline)
                if not m:
                    continue
                var_name = m.group(1)
                if var_name.casefold() in param_cf:
                    continue
                if var_name.casefold() in declared_cf:
                    continue
                if rel_idx in decl_rel_indices:
                    continue
                if _bsl007_name_used_in_file(
                    var_name,
                    lines,
                    assign_lhs_idx=abs_line,
                    lo=body_lo,
                    hi=body_hi,
                    skip_indices=set(),
                ):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=abs_line + 1,
                        character=lines[abs_line].find(var_name)
                        if var_name in lines[abs_line]
                        else 0,
                        end_line=abs_line + 1,
                        end_character=len(lines[abs_line].rstrip()),
                        severity=Severity.WARNING,
                        code="BSL007",
                        message=f"Удалите неиспользуемую переменную {var_name}",
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

    def _rule_bsl009_self_assign(self, path: str, lines: list[str], tree: Any) -> list[Diagnostic]:
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
            code_lines_in_body = [
                lines[i].strip()
                for i in range(proc.start_idx + 1, proc.end_idx)
                if i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("//")
            ]
            # Skip stub procedures whose only code statement is the return itself
            if len(code_lines_in_body) <= 1:
                continue
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
                start_col, end_col = _proc_name_span(lines, proc)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=start_col,
                        end_line=proc.start_idx + 1,
                        end_character=end_col,
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

    def _rule_bsl012_hardcode_credentials(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl013_commented_code(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl014_line_too_long(self, path: str, lines: list[str]) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            # Skip query string continuation lines (|...) — BSLLS does not flag these for BSL014
            if line.lstrip().startswith("|"):
                continue
            length = len(line)
            if length > self.max_line_length:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=0,
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
        allowed = _standard_regions_for_path(path)
        if not allowed or not regions:
            return []
        diags: list[Diagnostic] = []
        for region in regions:
            if not _is_standard_region_name_for_path(path, region.name):
                line_idx = region.start_idx
                line_text = lines[line_idx] if line_idx < len(lines) else ""
                start_char = 1 if line_text.startswith("#") else 0
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=start_char,
                        end_line=line_idx + 1,
                        end_character=len(line_text),
                        severity=Severity.INFORMATION,
                        code="BSL016",
                        message=f'Нужно удалить нестандартный раздел "{region.name}"',
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
                start_col, end_col = _proc_name_span(lines, proc)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=start_col,
                        end_line=proc.start_idx + 1,
                        end_character=end_col,
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
            # Single alternation scan instead of one re.search per parameter
            combined = re.compile(
                r"\b(?:" + "|".join(re.escape(p) for p in proc.val_params) + r")\b",
                re.IGNORECASE,
            )
            referenced = {m.group().casefold() for m in combined.finditer(body)}
            line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
            for param in proc.val_params:
                if param.casefold() not in referenced:
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

    def _rule_bsl023_service_tag(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl024_space_at_start_comment(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """
        Require a space after ``//`` in single-line comments (BSLLS ``SpaceAtStartComment``).

        Mirrors BSLLS strict-good pattern, ``//@`` / ``//(c)`` / ``//©`` annotations,
        skips commented-code lines (BSLLS ``CodeRecognizer``), ``//!``, ``//|``, noqa.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            col = bsl024_find_report_comment_col(line)
            if col is None:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=col,
                    end_line=idx + 1,
                    end_character=len(line),
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
        continuation_re = re.compile(r"^\s*(?:И|Или|AND|OR)\b", re.IGNORECASE)
        end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b", re.IGNORECASE
        )
        for proc in procs:
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                stripped = line.rstrip()
                if not stripped or stripped.strip().startswith("//"):
                    continue
                code_part = stripped.split("//")[0].rstrip()
                if not code_part:
                    continue
                if end_kw_re.match(code_part) and not code_part.endswith(";"):
                    col = len(code_part) - len(code_part.lstrip())
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=col,
                            end_line=i + 1,
                            end_character=col + len(code_part.lstrip()),
                            severity=Severity.INFORMATION,
                            code="BSL030",
                            message=("Пропущена точка с запятой в конце выражения"),
                        )
                    )
                    continue
                last_char = code_part[-1]
                # «)» может завершать вызов — после него нужна «;» (BSLLS SemicolonPresence).
                if last_char in (";", ",", "(", "|", "+", "-", "*", "/", "="):
                    continue
                next_sig = None
                for j in range(i + 1, min(proc.end_idx, len(lines))):
                    nxt = lines[j].strip()
                    if not nxt or nxt.startswith("//"):
                        continue
                    next_sig = lines[j]
                    break
                if next_sig is not None and continuation_re.match(next_sig):
                    continue
                if _RE_STMT_NO_SEMI.match(code_part):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=len(code_part),
                            end_line=i + 1,
                            end_character=len(code_part),
                            severity=Severity.INFORMATION,
                            code="BSL030",
                            message=("Пропущена точка с запятой в конце выражения"),
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

    def _rule_bsl027_use_goto(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                # Mask string contents before scanning while preserving original
                # character offsets for resulting diagnostics.
                code_part = _RE_DOUBLE_QUOTED_STRING.sub(
                    lambda m: '"' + (" " * max(0, len(m.group(0)) - 2)) + '"',
                    line,
                )
                code_part = _RE_SINGLE_QUOTED_STRING.sub(
                    lambda m: "'" + (" " * max(0, len(m.group(0)) - 2)) + "'",
                    code_part,
                )
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

    def _rule_bsl030_header_semicolon(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
    # BSL148 — AllFunctionPathMustHaveReturn
    # ------------------------------------------------------------------

    def _rule_bsl148_all_function_paths_return(self, path: str, tree: Any) -> list[Diagnostic]:
        # BSLLS test modules may contain intentional parse noise; BSL148 skips ERROR subtrees per function.
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
            return []
        diags: list[Diagnostic] = []
        for sp in bsl148_function_name_spans(
            tree,
            loops_executed_at_least_once=self.bsl148_loops_executed_at_least_once,
        ):
            diags.append(
                Diagnostic(
                    file=path,
                    line=sp.line0 + 1,
                    character=sp.col0,
                    end_line=sp.line1 + 1,
                    end_character=sp.col1,
                    severity=Severity.ERROR,
                    code="BSL148",
                    message=(
                        "Не все пути выполнения функции завершаются «Возврат»/«Return» "
                        "(BSLLS AllFunctionPathMustHaveReturn)."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL150 — BadWords (pattern from ``DiagnosticEngine(bad_words_pattern=...)``)
    # ------------------------------------------------------------------

    def _rule_bsl150_bad_words(self, path: str, lines: list[str]) -> list[Diagnostic]:
        rx = self._bad_words_re
        if rx is None:
            return []
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            for m in rx.finditer(line):
                w = m.group(0)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL150",
                        message=f"Нежелательное слово в коде: {w!r} (BadWords).",
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

    _RE_IF_OR_ELSEIF_LINE = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b", re.IGNORECASE)
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
        return len(_RE_BOOL_OP.findall(chunk)) + 1 > self.max_bool_ops

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

    def _rule_bsl036_complex_condition(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
            ops = len(_RE_BOOL_OP.findall(chunk)) + 1
            char = len(line) - len(line.lstrip())
            kw = line.lstrip()
            if kw.lower().startswith("если "):
                char += len("Если ")
            elif kw.lower().startswith("if "):
                char += len("If ")
            elif kw.lower().startswith("иначеесли "):
                char += len("ИначеЕсли ")
            elif kw.lower().startswith("elsif "):
                char += len("ElsIf ")
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=char,
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
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

    def _rule_bsl039_nested_ternary(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        BSLLS parity:
        - check only form modules
        - skip procedures/functions that already accept ЭтаФорма/ThisForm as a parameter
        - report each direct token occurrence outside comments/strings
        """
        if not path_is_likely_form_module_bsl(path):
            return []

        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            proc = _proc_containing_line(procs, idx)
            if proc is not None and any(
                re.fullmatch(r"(?:ЭтаФорма|ThisForm)", param, re.IGNORECASE)
                for param in proc.params
            ):
                continue
            clean = _mask_double_quoted_strings_preserve_len(line)
            comment_col = clean.find("//")
            if comment_col >= 0:
                clean = clean[:comment_col]
            for m in _RE_THIS_FORM.finditer(clean):
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
                            "Избегайте использования ЭтаФорма/ThisForm, передавайте форму в параметрах метода"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL041 — DeprecatedMessage
    # ------------------------------------------------------------------

    def _rule_bsl041_deprecated_message(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Detect direct Сообщить()/Message() calls."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = _strip_inline_comment_preserve_strings(line)
            m = _RE_DEPRECATED_MESSAGE.search(clean)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL041",
                        message=(
                            "Метод Сообщить()/Message() устарел. "
                            "Используйте журналирование или не модальный UI API."
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
                line.strip() and not _RE_BLANK_OR_COMMENT.match(line) for line in body_lines
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
        for proc in procs:
            if proc.kind != "function" or not proc.is_export:
                continue
            body = "\n".join(lines[proc.start_idx : proc.end_idx + 1])
            if not _RE_BSL044_RETURN_VALUE.search(body):
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

    def _rule_bsl047_current_date(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl048_empty_file(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag BSL files that contain no executable code at all."""
        if not lines:
            return []  # truly empty file — no position to attach diagnostic; BSLLS skips these
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
        for proc in procs:
            body_lines = lines[proc.start_idx : proc.end_idx + 1]
            base_indent = _proc_body_base_indent(lines, proc)
            # Skip stub procs where raise is the only code statement (intentional "not implemented")
            inner_lines = lines[
                proc.start_idx + 1 : proc.end_idx
            ]  # exclude header and КонецПроцедуры
            code_stmts = [
                ln.strip() for ln in inner_lines if ln.strip() and not ln.strip().startswith("//")
            ]
            if len(code_stmts) <= 1:
                continue
            try_depth = 0
            for rel_idx, line in enumerate(body_lines):
                if _RE_TRY_OPEN.match(line):
                    try_depth += 1
                elif _RE_TRY_CLOSE.match(line):
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
            body_lines = list(
                enumerate(lines[proc.start_idx + 1 : proc.end_idx], start=proc.start_idx + 1)
            )
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
                literal_m = re.search(r"\b(Истина|True|Ложь|False)\b", line, re.IGNORECASE)
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

    def _rule_bsl053_execute_dynamic(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
    # BSL055 — Consecutive blank lines (> MAX_BLANK_LINES)
    # ------------------------------------------------------------------

    # BSLLS ConsecutiveEmptyLines: flag when more than one blank line in a row.
    MAX_BLANK_LINES: int = 1

    def _rule_bsl055_consecutive_blank_lines(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag runs of more than ``MAX_BLANK_LINES`` consecutive blank lines."""
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

    def _rule_bsl057_deprecated_input_dialog(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl058_query_without_where(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                while j < len(lines) and (
                    lines[j].lstrip().startswith("|") or not lines[j].strip()
                ):
                    query_lines.append(lines[j])
                    j += 1
                query_text = "\n".join(query_lines)
                has_where = _RE_QUERY_WHERE.search(query_text)
                has_first = re.search(r"\b(?:ПЕРВЫЕ|FIRST|TOP)\b", query_text, re.IGNORECASE)
                has_into = re.search(r"\b(?:ПОМЕСТИТЬ|INTO)\b", query_text, re.IGNORECASE)
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
                        message=(f"Parameter '{param_name}' is never used in the method body."),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL063 — Large module
    # ------------------------------------------------------------------

    def _rule_bsl063_large_module(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl068_too_many_elseif(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl069_infinite_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                body_lines = lines[loop_start + 1 : j]
                has_executable = any(
                    ln.strip() and not ln.strip().startswith("//") for ln in body_lines
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
        body_ranges: list[tuple[int, int]] = [(proc.start_idx + 1, proc.end_idx) for proc in procs]
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            # Only flag inside method bodies
            if not any(start <= idx < end for start, end in body_ranges):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            # Skip constant declarations: Конст Х = 100;
            if re.match(r"^\s*(?:Конст|Const)\b", line, re.IGNORECASE):
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

    def _rule_bsl072_string_concat_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl073_missing_else_branch(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl074_todo_comment(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                rest = lines[idx][m.end() :].rstrip().rstrip(";")
                for name in re.split(r"\s*,\s*", rest):
                    name = name.strip()
                    if name:
                        module_vars.add(name.lower())

        if not module_vars:
            return []

        diags: list[Diagnostic] = []
        for proc in procs:
            # Collect local Перем declarations within this method
            body_start = proc.start_idx + 1
            local_vars: set[str] = set()
            for idx in range(body_start, min(proc.end_idx, len(lines))):
                lm = _RE_VAR_DECL.match(lines[idx])
                if lm:
                    rest = lines[idx][lm.end() :].rstrip().rstrip(";")
                    for nm in re.split(r"\s*,\s*", rest):
                        nm = nm.strip()
                        if nm:
                            local_vars.add(nm.lower())

            # Also treat parameters as local
            param_vars: set[str] = {p.lower() for p in proc.params}

            for idx in range(body_start, min(proc.end_idx, len(lines))):
                am = _RE_MODULE_ASSIGN.match(lines[idx])
                if am:
                    var_name = am.group(1).lower()
                    if (
                        var_name in module_vars
                        and var_name not in local_vars
                        and var_name not in param_vars
                    ):
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
    # BSL077 — SelectTopWithoutOrderBy
    # ------------------------------------------------------------------

    def _rule_bsl077_select_top_without_order_by(
        self,
        path: str,
        lines: list[str],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        """Flag query text with TOP/ПЕРВЫЕ used without ORDER BY/УПОРЯДОЧИТЬ."""
        diags: list[Diagnostic] = []
        if query_blocks is None:
            blocks_iter = [
                QueryTextBlockInfo(
                    start_idx=start_idx,
                    block_lines=tuple(block_lines),
                    content_lines=tuple(),
                )
                for start_idx, block_lines in _iter_query_text_blocks(lines)
            ]
        else:
            blocks_iter = query_blocks
        for block in blocks_iter:
            start_idx = block.start_idx
            block_lines = list(block.block_lines)
            query_text = block.query_text
            top_matches = list(_RE_QUERY_TOP.finditer(query_text))
            if not top_matches:
                continue
            has_union = bool(_RE_QUERY_UNION.search(query_text))
            has_where = bool(_RE_QUERY_WHERE.search(query_text))
            if not has_union and _RE_QUERY_ORDER_BY.search(query_text):
                continue

            for top_match in top_matches:
                top_limit = top_match.group(1)
                if not has_union:
                    next_union = _RE_QUERY_UNION.search(query_text, top_match.end())
                    segment_end = next_union.start() if next_union else len(query_text)
                    segment_text = query_text[top_match.start() : segment_end]
                    if _RE_QUERY_ORDER_BY.search(segment_text):
                        continue
                if not has_union and top_limit in {"0", "1"} and has_where:
                    continue

                rel_pos = top_match.start()
                passed = 0
                line_idx = start_idx
                col = 0
                end_col = 0
                for offset, raw_line in enumerate(block_lines):
                    line_len = len(raw_line)
                    if rel_pos <= passed + line_len:
                        line_idx = start_idx + offset
                        col = max(0, rel_pos - passed)
                        local_match = _RE_QUERY_TOP.search(raw_line[col:])
                        if local_match:
                            col += local_match.start()
                            end_col = col + (local_match.end() - local_match.start())
                        else:
                            end_col = min(len(raw_line), col + len(top_match.group(0)))
                        break
                    passed += line_len + 1

                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=col,
                        end_line=line_idx + 1,
                        end_character=end_col,
                        severity=Severity.WARNING,
                        code="BSL077",
                        message="Использование ПЕРВЫЕ/TOP без УПОРЯДОЧИТЬ/ORDER BY в запросе",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL078 — ВызватьИсключение without a message
    # ------------------------------------------------------------------

    def _rule_bsl078_raise_without_message(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl079_using_goto(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl080_silent_catch(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl081_long_method_chain(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl082_missing_newline_at_eof(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                rest = lines[idx][_RE_VAR_DECL.match(lines[idx]).end() :].rstrip().rstrip(";")
                count = len([n for n in re.split(r"\s*,\s*", rest) if n.strip()])
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
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            has_return_value = any(_RE_RETURN_VALUE.match(ln) for ln in body_lines)
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

    def _rule_bsl086_http_request_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
    _ALLOWED_NEW_IN_LOOP: frozenset[str] = frozenset(
        {
            "структура",
            "соответствие",
            "массив",
            "список",
            "structure",
            "map",
            "array",
            "list",
        }
    )

    def _rule_bsl087_object_creation_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                            after = lines[j][m.end() :].strip()
                            obj_type = re.match(r"(\w+)", after)
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
            comment_block = lines[start : proc.start_idx]
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

    def _rule_bsl089_transaction_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                        elif _RE_ELSE.match(lines[j]) or _RE_ELSEIF.match(lines[j]):
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

    def _rule_bsl093_comparison_to_null(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl094_noop_assignment(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
        r"^\s*(?:Для|For|ДляКаждого|ForEach|Пока|While|#)",
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
            preceding = lines[start : proc.start_idx]
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

    def _rule_bsl097_use_of_current_date(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl098_use_of_execute(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl100_hardcoded_file_path(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
        r"^\s*(?:Если|If|"
        r"Для|For|ДляКаждого|ForEach|Пока|While|"
        r"Попытка|Try)\b",
        re.IGNORECASE,
    )
    _NESTING_CLOSE = re.compile(
        r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
        re.IGNORECASE,
    )

    def _rule_bsl101_too_deep_nesting(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl102_large_module(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl103_use_of_eval(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl104_missing_module_comment(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag modules that have no comment block in the first 5 lines."""
        if not lines:
            return []
        first_lines = lines[:5]
        has_comment = any(ln.strip().startswith("//") for ln in first_lines)
        if has_comment:
            return []
        # Skip empty files or files that start with a region
        first_non_blank = next((ln.strip() for ln in lines if ln.strip()), "")
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
                    "Module has no comment header — add a // description of the module's purpose."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL105 — Use of Приостановить() / Sleep()
    # ------------------------------------------------------------------

    def _rule_bsl105_use_of_sleep(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl106_query_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl107_empty_then_branch(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                            "Empty Тогда branch — add the missing logic or remove the branch."
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL108 — Exported module-level variable
    # ------------------------------------------------------------------

    def _rule_bsl108_use_of_global_variables(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                        message=("Guard-clause with НЕ — invert the condition to reduce nesting."),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL110 — String self-concatenation inside a loop
    # ------------------------------------------------------------------

    def _rule_bsl110_string_concat_in_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                    r"(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)",
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

    def _rule_bsl113_assignment_in_condition(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """BSLLS ``AssignmentInCondition`` — in BSL ``=`` in ``Если`` is comparison, not assignment."""
        return []

    # ------------------------------------------------------------------
    # BSL114 — Empty module
    # ------------------------------------------------------------------

    def _rule_bsl114_empty_module(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl115_chained_negation(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                        message=("Double negation НЕ НЕ — simplify to the positive condition."),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL116 — Obsolete indexed iterator (Для И = 0 По ... Цикл)
    # ------------------------------------------------------------------

    _RE_FOR_INDEX = re.compile(
        r"^\s*(?:Для|For)\s+\w+\s*=\s*\d+\s+(?:По|To)\b",
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
        procedure_names = {p.name.lower() for p in procs if p.kind == "procedure"}
        if not procedure_names:
            return []
        # Pattern: Var = ProcName(
        _re_proc_as_func = re.compile(
            r"^\s*\w+\s*=\s*(" + "|".join(re.escape(n) for n in procedure_names) + r")\s*\(",
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
            body_lines = lines[proc.start_idx : proc.end_idx + 1]
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

    def _rule_bsl119_line_too_long(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl120_trailing_whitespace(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl121_tab_indentation(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
            body_text = "\n".join(body_lines).lower()
            for param in proc.params:
                # Strip default value and leading &/Val markers
                raw = param.lstrip("&").split("=")[0].strip()
                # Remove leading Val/Значение keyword
                pname = re.sub(r"^\s*(?:Значение|Val)\s+", "", raw, flags=re.IGNORECASE).strip()
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
                                f"Parameter '{pname}' in '{proc.name}' is never used in the body."
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL123 — Commented-out code
    # ------------------------------------------------------------------

    def _rule_bsl123_commented_out_code(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl125_break_outside_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl126_continue_outside_loop(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
            body_lines = lines[proc.start_idx + 1 : proc.end_idx]
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
            pattern = _compile_call_pattern(proc.name)
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

    def _rule_bsl130_long_comment_line(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
    # BSL131 — DuplicateRegion
    # ------------------------------------------------------------------

    def _rule_bsl131_duplicate_region(
        self, path: str, lines: list[str], regions: list[_RegionInfo]
    ) -> list[Diagnostic]:
        """Detect duplicated region names, including BSLLS standard-region synonyms."""

        def normalize(name: str) -> str:
            raw = re.sub(r"\s+", "", name).casefold()
            aliases = {
                "программныйинтерфейс": "public",
                "публичный": "public",
                "public": "public",
                "служебныйпрограммныйинтерфейс": "internal",
                "служебный": "internal",
                "internal": "internal",
                "служебныепроцедурыифункции": "private",
                "приватный": "private",
                "private": "private",
                "обработчикисобытий": "eventhandlers",
                "eventhandlers": "eventhandlers",
                "обработчикисобытийформы": "formeventhandlers",
                "formeventhandlers": "formeventhandlers",
            }
            return aliases.get(raw, raw)

        diags: list[Diagnostic] = []
        seen: dict[str, _RegionInfo] = {}
        for region in regions:
            key = normalize(region.name)
            if not key:
                continue
            if key not in seen:
                seen[key] = region
                continue
            line = lines[region.start_idx] if 0 <= region.start_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=path,
                    line=region.start_idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=region.start_idx + 1,
                    end_character=len(line.rstrip()),
                    severity=Severity.INFORMATION,
                    code="BSL131",
                    message=f'Область "{region.name}" уже объявлена выше в модуле',
                )
            )
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

    def _rule_bsl135_nested_function_calls(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl138_use_of_debug_output(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl140_unreachable_elseif(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

    def _rule_bsl144_unnecessary_parentheses(self, path: str, lines: list[str]) -> list[Diagnostic]:
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

        _re_exec = re.compile(r"[А-Яа-яA-Za-z0-9_]")

        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("//"):
                continue
            if _RE_PERЕМ_LINE.match(line):
                continue
            if _RE_REGION_LINE.match(line):
                continue
            if _RE_PREPROC_LINE.match(line):
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
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=col,
                            end_line=idx + 1,
                            end_character=col + len("НачатьТранзакцию"),
                            severity=Severity.ERROR,
                            code="BSL151",
                            message=(
                                "НачатьТранзакцию() должна находиться непосредственно "
                                "перед блоком Попытка"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL152 — CachedPublic (common module + ReturnValuesReuse + Public region)
    # ------------------------------------------------------------------

    def _rule_bsl152_cached_public(
        self,
        path: str,
        lines: list[str],
        regions: list[_RegionInfo],
        procs: list[_ProcInfo],
    ) -> list[Diagnostic]:
        """BSLLS CachedPublic — program-interface region in a return-value-reuse common module."""
        reg_tuples = [(r.name, r.start_idx, r.end_idx) for r in regions]
        proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
        diags: list[Diagnostic] = []
        for line_1, c0, c1 in bsl152_public_region_name_spans(path, lines, reg_tuples, proc_tuples):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=c0,
                    end_line=line_1,
                    end_character=c1,
                    severity=Severity.WARNING,
                    code="BSL152",
                    message=(
                        "Не следует размещать программный интерфейс в общем модуле "
                        "с повторным использованием возвращаемых значений "
                        "(BSLLS CachedPublic)."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL154 — CodeAfterAsyncCall (client command / form / managed app modules)
    # ------------------------------------------------------------------

    def _rule_bsl154_code_after_async(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """BSLLS CodeAfterAsyncCall — code after async platform call (procedure-body heuristic)."""
        proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
        diags: list[Diagnostic] = []
        for line_1, c0, c1, method in bsl154_code_after_async_spans(path, lines, proc_tuples):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=c0,
                    end_line=line_1,
                    end_character=c1,
                    severity=Severity.WARNING,
                    code="BSL154",
                    message=(
                        f"После асинхронного вызова «{method}» следует исполняемый код "
                        f"(BSLLS CodeAfterAsyncCall)."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL155 — CodeBlockBeforeSub
    # ------------------------------------------------------------------

    def _rule_bsl155_code_block_before_sub(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Executable lines before the first procedure/function (BSLLS fileCodeBlockBeforeSub)."""
        proc_tuples = [(p.start_idx, p.end_idx) for p in procs]
        diags: list[Diagnostic] = []
        for line_1, c0, c1, msg in bsl155_code_block_before_sub(lines, proc_tuples):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=c0,
                    end_line=line_1,
                    end_character=c1,
                    severity=Severity.WARNING,
                    code="BSL155",
                    message=msg,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL156 — CodeOutOfRegion
    # ------------------------------------------------------------------

    def _rule_bsl156_code_out_of_region(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Module lines and procedures must lie inside #Область/#Region (BSLLS CodeOutOfRegion)."""
        triples = [(p.start_idx, p.end_idx, p.name) for p in procs]
        diags: list[Diagnostic] = []
        for line_1, c0, c1, msg in bsl156_diagnostics(path, lines, triples):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=c0,
                    end_line=line_1,
                    end_character=c1,
                    severity=Severity.INFORMATION,
                    code="BSL156",
                    message=msg,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL158 — CommonModuleAssign (indexed configuration)
    # ------------------------------------------------------------------

    def _rule_bsl158_common_module_assign(
        self, path: str, lines: list[str], symbol_index: Any
    ) -> list[Diagnostic]:
        """Assignment to a name that is a common module object (BSLLS CommonModuleAssign)."""
        diags: list[Diagnostic] = []
        for line_1, c0, c1, name in bsl158_common_module_assign_spans(lines, symbol_index):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=c0,
                    end_line=line_1,
                    end_character=c1,
                    severity=Severity.ERROR,
                    code="BSL158",
                    message=(
                        f"Нельзя присваивать значение объекту общего модуля «{name}» "
                        f"(BSLLS CommonModuleAssign)."
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL159 — CommonModuleInvalidType (sibling module XML)
    # ------------------------------------------------------------------

    def _rule_bsl159_common_module_invalid_type(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Common module descriptor has no execution context flags (BSLLS CommonModuleInvalidType)."""
        inv = common_module_xml_flags_invalid(path)
        if inv is not True:
            return []
        span = bsl160_module_line1_span(lines)
        c0, c1 = span if span is not None else (0, 1)
        return [
            Diagnostic(
                file=path,
                line=1,
                character=c0,
                end_line=1,
                end_character=c1,
                severity=Severity.ERROR,
                code="BSL159",
                message=(
                    "У общего модуля не задан контекст выполнения в метаданных "
                    "(BSLLS CommonModuleInvalidType)."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL160 — CommonModuleMissingAPI
    # ------------------------------------------------------------------

    def _rule_bsl160_common_module_missing_api(
        self,
        path: str,
        lines: list[str],
        regions: list[_RegionInfo],
        procs: list[_ProcInfo],
    ) -> list[Diagnostic]:
        """No export and/or no Public/Internal API region (BSLLS CommonModuleMissingAPI)."""
        if not bsl160_common_module_missing_api(
            path,
            [r.name for r in regions],
            [p.is_export for p in procs],
        ):
            return []
        span = bsl160_module_line1_span(lines)
        if span is None:
            return []
        c0, c1 = span
        return [
            Diagnostic(
                file=path,
                line=1,
                character=c0,
                end_line=1,
                end_character=c1,
                severity=Severity.INFORMATION,
                code="BSL160",
                message=(
                    "В общем модуле нет экспортных методов и/или областей "
                    "программного интерфейса (Public/Internal) "
                    "(BSLLS CommonModuleMissingAPI)."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # BSL161–BSL168 — CommonModuleName* (sibling module XML)
    # ------------------------------------------------------------------

    def _rule_bsl161_168_common_module_names(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        """Common module name vs metadata flags / forbidden words (BSLLS CommonModuleName*)."""
        issues = common_module_name_convention_issues(path)
        if not issues:
            return []
        span = bsl160_module_line1_span(lines)
        c0, c1 = span if span is not None else (0, 1)
        enabled = {c for c in codes if self._rule_enabled(c)}
        out: list[Diagnostic] = []
        for code, message in issues:
            if code not in enabled:
                continue
            out.append(
                Diagnostic(
                    file=path,
                    line=1,
                    character=c0,
                    end_line=1,
                    end_character=c1,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=message,
                )
            )
        return out

    # ------------------------------------------------------------------
    # BSL157 — CommitTransactionOutsideTryCatch
    # ------------------------------------------------------------------

    def _rule_bsl157_commit_transaction_outside_try(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """ЗафиксироватьТранзакцию()/CommitTransaction() must be the last statement before Except."""
        diags: list[Diagnostic] = []
        _re_commit = re.compile(
            r"^\s*(?:ЗафиксироватьТранзакцию|CommitTransaction)\s*\(",
            re.IGNORECASE,
        )
        _re_try = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
        _re_except = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
        _re_end_try = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
        _re_comment = re.compile(r"^\s*//")
        pending: tuple[int, int, int] | None = None

        for idx, line in enumerate(lines):
            if _re_comment.match(line) or not line.strip():
                continue

            if _re_try.match(line):
                if pending is not None:
                    p_line, p_col, p_end = pending
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=p_line + 1,
                            character=p_col,
                            end_line=p_line + 1,
                            end_character=p_end,
                            severity=Severity.ERROR,
                            code="BSL157",
                            message=(
                                "ЗафиксироватьТранзакцию() должна вызываться внутри блока "
                                "Попытка (перед Исключение)"
                            ),
                        )
                    )
                pending = None
                continue

            if _re_except.match(line):
                pending = None
                continue

            if _re_end_try.match(line):
                if pending is not None:
                    p_line, p_col, p_end = pending
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=p_line + 1,
                            character=p_col,
                            end_line=p_line + 1,
                            end_character=p_end,
                            severity=Severity.ERROR,
                            code="BSL157",
                            message=(
                                "ЗафиксироватьТранзакцию() должна вызываться внутри блока "
                                "Попытка (перед Исключение)"
                            ),
                        )
                    )
                pending = None
                continue

            m = _re_commit.search(line)
            if m:
                pending = (idx, len(line) - len(line.lstrip()), m.end())
                continue

            if pending is not None:
                p_line, p_col, p_end = pending
                diags.append(
                    Diagnostic(
                        file=path,
                        line=p_line + 1,
                        character=p_col,
                        end_line=p_line + 1,
                        end_character=p_end,
                        severity=Severity.ERROR,
                        code="BSL157",
                        message=(
                            "ЗафиксироватьТранзакцию() должна вызываться внутри блока "
                            "Попытка (перед Исключение)"
                        ),
                    )
                )
                pending = None
        if pending is not None:
            p_line, p_col, p_end = pending
            diags.append(
                Diagnostic(
                    file=path,
                    line=p_line + 1,
                    character=p_col,
                    end_line=p_line + 1,
                    end_character=p_end,
                    severity=Severity.ERROR,
                    code="BSL157",
                    message=(
                        "ЗафиксироватьТранзакцию() должна вызываться внутри блока "
                        "Попытка (перед Исключение)"
                    ),
                )
            )
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
        _re_end_loop = re.compile(r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE)
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
                            arg = (
                                bl[arg_start:arg_end].strip().casefold()
                                if arg_end > arg_start
                                else ""
                            )
                            if obj == collection or arg == iter_var:
                                diags.append(
                                    Diagnostic(
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
                                    )
                                )
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
        low_path = path.replace("\\", "/").lower()
        if not (
            low_path.endswith("/ext/objectmodule.bsl")
            or low_path.endswith("/ext/recordsetmodule.bsl")
            or low_path.endswith("/ext/valuemanagermodule.bsl")
        ):
            return []
        _re_handler = re.compile(
            r"^\s*(?:Процедура|Procedure)\s+"
            r"(?:ПередЗаписью|BeforeWrite|ПриЗаписи|OnWrite|"
            r"ПередУдалением|BeforeDelete)\s*\(",
            re.IGNORECASE | re.UNICODE,
        )
        _re_exchange = re.compile(
            r"(?:ОбменДанными\.Загрузка|DataExchange\.Load)\b",
            re.IGNORECASE,
        )
        _re_if = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE | re.UNICODE)
        _re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE | re.UNICODE)
        _re_return = re.compile(r"^\s*(?:Возврат|Return)\b", re.IGNORECASE | re.UNICODE)

        for proc in procs:
            start = proc.start_idx
            line = lines[start] if start < len(lines) else ""
            header_match = _re_handler.match(line)
            if not header_match:
                continue

            body_start = start + 1
            body_end = min(proc.end_idx, len(lines))
            has_check = False
            i = body_start
            while i < body_end:
                raw = lines[i]
                if not _re_if.match(raw) or not _re_exchange.search(raw):
                    i += 1
                    continue
                depth = 1
                j = i + 1
                branch_has_return = False
                while j < body_end and depth > 0:
                    branch_line = lines[j]
                    if _re_if.match(branch_line):
                        depth += 1
                    elif _re_endif.match(branch_line):
                        depth -= 1
                        if depth == 0:
                            break
                    if _re_return.match(branch_line):
                        branch_has_return = True
                    j += 1
                if branch_has_return:
                    has_check = True
                    break
                i = max(j, i + 1)
            if not has_check:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=start + 1,
                        character=line.find(proc.name) if proc.name in line else 0,
                        end_line=start + 1,
                        end_character=(
                            (line.find(proc.name) + len(proc.name))
                            if proc.name in line
                            else len(line)
                        ),
                        severity=Severity.ERROR,
                        code="BSL172",
                        message="Добавьте проверку признака ОбменДанными.Загрузка в самом начале процедуры",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL186 — ExtraCommas
    # ------------------------------------------------------------------

    def _rule_bsl186_extra_commas(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Detect trailing commas in method calls or declarations."""
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            m = _RE_BSL186_TRAILING_COMMA.search(clean)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.start() + 1,
                        severity=Severity.WARNING,
                        code="BSL186",
                        message="Лишняя запятая перед закрывающей скобкой или точкой с запятой",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL149 — AssignAliasFieldsInQuery
    # ------------------------------------------------------------------

    def _rule_bsl149_assign_alias_fields_in_query(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Flag SELECT fields in embedded queries that lack an explicit КАК/AS alias."""
        diags: list[Diagnostic] = []
        # State machine across continuation lines
        in_query = False  # inside a multi-line query string
        in_select = False  # currently collecting SELECT field lines
        skip_select = False  # next SELECT's fields are skipped (after UNION)
        paren_depth = 0  # parens depth for nested subqueries

        for idx, line in enumerate(lines):
            stripped = line.rstrip()

            # ── Non-continuation line: BSL code ──────────────────────────────
            if not _RE_BSL149_CONTINUATION.match(stripped):
                # Reset query state when BSL code line doesn't open a query
                if in_query:
                    in_query = False
                    in_select = False
                    skip_select = False
                    paren_depth = 0
                m_sel = _RE_BSL149_SELECT.search(stripped)
                if m_sel:
                    tail = stripped[m_sel.end() :]
                    m_clause = _RE_BSL149_CLAUSE_AFTER_FIELDS.search(tail)
                    if m_clause:
                        field_region = tail[: m_clause.start()]
                        qpos = field_region.find('"')
                        if qpos >= 0:
                            field_region = field_region[:qpos]
                        field_region = _RE_BSL149_INLINE_COMMENT.sub("", field_region).strip()
                        _bsl149_append_missing_alias_diags(path, idx, line, field_region, diags)
                    else:
                        # Multiline text: "ВЫБРАТЬ … then |… continuation lines
                        in_query = True
                        in_select = True
                        skip_select = False
                        paren_depth = 0
                continue

            # ── Continuation line |... ────────────────────────────────────────
            if not in_query:
                # |ВЫБРАТЬ on a continuation line starts a new query block
                # (e.g. Новый Запрос("  on the BSL line, |ВЫБРАТЬ on next)
                if _RE_BSL149_SELECT.search(stripped):
                    in_query = True
                    in_select = True
                    skip_select = False
                    paren_depth = 0
                else:
                    continue

            # Strip leading whitespace + | character
            raw_content = stripped.lstrip()
            if raw_content.startswith("|"):
                raw_content = raw_content[1:]

            # Strip inline query comment (// ...) before any processing
            content = _RE_BSL149_INLINE_COMMENT.sub("", raw_content).rstrip()

            # Query separator ; — next query in the same string starts fresh
            if ";" in content:
                in_select = False
                skip_select = False
                paren_depth = 0
                # If ВЫБРАТЬ follows the ; on the same piece, handle below
                after_semi = content[content.index(";") + 1 :].strip()
                if _RE_BSL149_SELECT.search(after_semi):
                    in_select = not skip_select
                    skip_select = False
                continue

            # String concatenation break: content still has a quote → query ended
            if '"' in content:
                in_query = False
                in_select = False
                skip_select = False
                paren_depth = 0
                continue

            # Empty line or pure comment line
            if not content:
                continue

            # UNION keyword → skip the NEXT SELECT's fields
            if _RE_BSL149_UNION.search(content):
                in_select = False
                skip_select = True
                continue

            # SELECT/ВЫБРАТЬ on a continuation line (including nested)
            if _RE_BSL149_SELECT.search(content):
                m = _RE_BSL149_SELECT.search(content)
                # Count parens before the SELECT to determine nesting level
                before_select = content[: m.start()]
                paren_depth += before_select.count("(") - before_select.count(")")
                if paren_depth > 0:
                    # Nested subquery — always check its fields (reset skip)
                    in_select = True
                else:
                    # Top-level SELECT in union chain
                    in_select = not skip_select
                    skip_select = False
                continue

            # Clause that ends the SELECT field list (FROM / WHERE / ...)
            if _RE_BSL149_CLAUSE_END.match(content):
                # Track closing parens from content before clause keyword
                paren_depth += content.count("(") - content.count(")")
                if paren_depth < 0:
                    paren_depth = 0
                in_select = False
                continue

            # Closing paren — may end a nested subquery
            if ")" in content and paren_depth > 0:
                paren_depth -= content.count(")")
                paren_depth += content.count("(")
                if paren_depth < 0:
                    paren_depth = 0
                in_select = False
                continue

            if not in_select:
                continue

            # ── Check fields on this line ─────────────────────────────────────
            _bsl149_append_missing_alias_diags(path, idx, line, content, diags)

        return diags

    # ------------------------------------------------------------------
    # BSL210 — LogicalOrInTheWhereSectionOfQuery
    # ------------------------------------------------------------------

    def _rule_bsl210_logical_or_in_where(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag ИЛИ/OR inside embedded-query WHERE sections (BSLLS parity heuristic)."""
        diags: list[Diagnostic] = []
        in_query = False
        gp = 0
        where_stack: list[int] = []

        for idx, line in enumerate(lines):
            stripped = line.rstrip()
            if not _RE_BSL149_CONTINUATION.match(stripped):
                if in_query:
                    in_query = False
                    gp = 0
                    where_stack.clear()
                diags.extend(self._bsl210_scan_line_literal_queries(path, idx, line))
                m_sel = _RE_BSL149_SELECT.search(stripped)
                if m_sel:
                    tail = stripped[m_sel.end() :]
                    if not _RE_BSL149_CLAUSE_AFTER_FIELDS.search(tail):
                        in_query = True
                        gp = 0
                        where_stack.clear()
                continue

            if not in_query:
                if _RE_BSL149_SELECT.search(stripped):
                    in_query = True
                    gp = 0
                    where_stack.clear()
                else:
                    continue

            raw_content = stripped.lstrip()
            if raw_content.startswith("|"):
                raw_content = raw_content[1:]
            content = _RE_BSL149_INLINE_COMMENT.sub("", raw_content).rstrip()
            content = content.lstrip()

            line_rs = line.rstrip()
            pipe_pos = line_rs.find("|")
            if pipe_pos < 0:
                continue
            after_pipe = line_rs[pipe_pos + 1 :]
            leading_ws = len(after_pipe) - len(after_pipe.lstrip())
            content_base = pipe_pos + 1 + leading_ws

            quote_pos = content.find('"')
            ended_query = quote_pos >= 0
            content_scan = content[:quote_pos].rstrip() if ended_query else content

            tail_has_semi = ";" in content_scan
            head = (
                content_scan[: content_scan.index(";")].rstrip() if tail_has_semi else content_scan
            )

            if tail_has_semi and not head:
                where_stack.clear()
                gp = 0
                if ended_query:
                    in_query = False
                continue

            if not head:
                if ended_query:
                    in_query = False
                    gp = 0
                    where_stack.clear()
                continue

            if _RE_BSL149_UNION.search(head):
                where_stack.clear()
                continue

            if where_stack and _RE_BSL210_LINE_ENDS_WHERE.match(head):
                if gp == where_stack[-1]:
                    where_stack.pop()

            if _RE_BSL210_LINE_IS_WHERE.match(head):
                where_stack.append(gp)

            if where_stack:
                for om in _RE_BSL210_OR.finditer(head):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=content_base + om.start(),
                            end_line=idx + 1,
                            end_character=content_base + om.end(),
                            severity=Severity.WARNING,
                            code="BSL210",
                            message=_BSL210_MESSAGE,
                        )
                    )

            gp += head.count("(") - head.count(")")
            if gp < 0:
                gp = 0
            while where_stack and gp < where_stack[-1]:
                where_stack.pop()

            if tail_has_semi:
                where_stack.clear()
                gp = 0
            if ended_query:
                in_query = False
                gp = 0
                where_stack.clear()

        return diags

    def _bsl210_scan_line_literal_queries(self, path: str, idx: int, line: str) -> list[Diagnostic]:
        """One-line (or same-line) literals: ВЫБРАТЬ ... ГДЕ ... ИЛИ ..."""
        if _RE_COMMENT_LINE.match(line):
            return []
        diags: list[Diagnostic] = []
        for quote_pos, literal in _bsl210_iter_double_quoted_segments(line):
            if not (_RE_BSL149_SELECT.search(literal) and _RE_QUERY_WHERE.search(literal)):
                continue
            offset_base = 0
            for part in literal.split(";"):
                for start, end in _bsl210_or_spans_in_query_literal(part):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=quote_pos + 1 + offset_base + start,
                            end_line=idx + 1,
                            end_character=quote_pos + 1 + offset_base + end,
                            severity=Severity.WARNING,
                            code="BSL210",
                            message=_BSL210_MESSAGE,
                        )
                    )
                offset_base += len(part) + 1
        return diags

    # ------------------------------------------------------------------
    # BSL220 / BSL235 / BSL269 / BSL273 — query text diagnostics
    # ------------------------------------------------------------------

    def _rule_bsl220_235_269_273_query_text_diagnostics(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if self._rule_enabled(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        if query_blocks is None:
            blocks_iter = None
        else:
            blocks_iter = query_blocks

        for block in blocks_iter or ():
            content_lines = _query_block_content_line_tuples(block)
            if not content_lines:
                continue

            if "BSL235" in enabled and (
                not _query_has_balanced_parens([head for _, _, _, head, _ in content_lines])
                or any(
                    _RE_QUERY_PARSE_ERROR_TAIL_KEYWORD.search(head)
                    or _RE_QUERY_PARSE_ERROR_TAIL_OPERATOR.search(head)
                    for _, _, _, head, _ in content_lines
                )
            ):
                line_no, content_base, _content, head, _ = content_lines[-1]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_no,
                        character=content_base,
                        end_line=line_no,
                        end_character=content_base + len(head),
                        severity=Severity.ERROR,
                        code="BSL235",
                        message="Синтаксическая ошибка в тексте встроенного запроса",
                    )
                )

            for line_no, content_base, content, head, _ended_query in content_lines:
                if "BSL220" in enabled:
                    multi_match = re.search(r'"{4,}', content)
                    if multi_match:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + multi_match.start(),
                                end_line=line_no,
                                end_character=content_base + multi_match.end(),
                                severity=Severity.INFORMATION,
                                code="BSL220",
                                message="Многострочная строка внутри текста запроса",
                            )
                        )

                if "BSL269" in enabled:
                    for match in _RE_QUERY_LIKE_OPERATOR.finditer(head):
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start(),
                                end_line=line_no,
                                end_character=content_base + match.end(),
                                severity=Severity.INFORMATION,
                                code="BSL269",
                                message="Оператор ПОДОБНО может привести к полному сканированию таблицы",
                            )
                        )

                if "BSL273" in enabled:
                    for match in _RE_QUERY_VIRTUAL_TABLE_CALL.finditer(head):
                        open_match = match.group("open")
                        if open_match is None:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + match.start("name"),
                                    end_line=line_no,
                                    end_character=content_base + match.end("name"),
                                    severity=Severity.WARNING,
                                    code="BSL273",
                                    message="Обращение к виртуальной таблице без параметров",
                                )
                            )
                            continue

                        open_idx = match.end("open") - 1
                        close_idx = _find_matching_paren(head, open_idx)
                        if close_idx < 0:
                            continue
                        args = head[open_idx + 1 : close_idx]
                        parts = [part.strip() for part in _split_top_level_args(args)]
                        if not parts or all(not part for part in parts):
                            is_violation = True
                        elif len(parts) == 1:
                            is_violation = False
                        else:
                            is_violation = all(not part for part in parts[1:])
                        if is_violation:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + match.start("name"),
                                    end_line=line_no,
                                    end_character=content_base + close_idx + 1,
                                    severity=Severity.WARNING,
                                    code="BSL273",
                                    message="Обращение к виртуальной таблице без параметров",
                                )
                            )
        if query_blocks is None:
            for start_idx, block_lines in _iter_query_text_blocks(lines):
                content_lines = list(_iter_query_text_content_lines(start_idx, block_lines))
                if not content_lines:
                    continue

                if "BSL235" in enabled and (
                    not _query_has_balanced_parens([head for _, _, _, head, _ in content_lines])
                    or any(
                        _RE_QUERY_PARSE_ERROR_TAIL_KEYWORD.search(head)
                        or _RE_QUERY_PARSE_ERROR_TAIL_OPERATOR.search(head)
                        for _, _, _, head, _ in content_lines
                    )
                ):
                    line_no, content_base, _content, head, _ = content_lines[-1]
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_no,
                            character=content_base,
                            end_line=line_no,
                            end_character=content_base + len(head),
                            severity=Severity.ERROR,
                            code="BSL235",
                            message="Синтаксическая ошибка в тексте встроенного запроса",
                        )
                    )

                for line_no, content_base, content, head, _ended_query in content_lines:
                    if "BSL220" in enabled:
                        multi_match = re.search(r'"{4,}', content)
                        if multi_match:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + multi_match.start(),
                                    end_line=line_no,
                                    end_character=content_base + multi_match.end(),
                                    severity=Severity.INFORMATION,
                                    code="BSL220",
                                    message="Многострочная строка внутри текста запроса",
                                )
                            )

                    if "BSL269" in enabled:
                        for match in _RE_QUERY_LIKE_OPERATOR.finditer(head):
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + match.start(),
                                    end_line=line_no,
                                    end_character=content_base + match.end(),
                                    severity=Severity.INFORMATION,
                                    code="BSL269",
                                    message="Оператор ПОДОБНО может привести к полному сканированию таблицы",
                                )
                            )

                    if "BSL273" in enabled:
                        for match in _RE_QUERY_VIRTUAL_TABLE_CALL.finditer(head):
                            open_match = match.group("open")
                            if open_match is None:
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=line_no,
                                        character=content_base + match.start("name"),
                                        end_line=line_no,
                                        end_character=content_base + match.end("name"),
                                        severity=Severity.WARNING,
                                        code="BSL273",
                                        message="Обращение к виртуальной таблице без параметров",
                                    )
                                )
                                continue

                            open_idx = match.end("open") - 1
                            close_idx = _find_matching_paren(head, open_idx)
                            if close_idx < 0:
                                continue
                            args = head[open_idx + 1 : close_idx]
                            parts = [part.strip() for part in _split_top_level_args(args)]
                            if not parts or all(not part for part in parts):
                                is_violation = True
                            elif len(parts) == 1:
                                is_violation = False
                            else:
                                is_violation = all(not part for part in parts[1:])
                            if is_violation:
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=line_no,
                                        character=content_base + match.start("name"),
                                        end_line=line_no,
                                        end_character=content_base + close_idx + 1,
                                        severity=Severity.WARNING,
                                        code="BSL273",
                                        message="Обращение к виртуальной таблице без параметров",
                                    )
                                )
        return diags

    # ------------------------------------------------------------------
    # BSL191 / BSL201 — query text diagnostics
    # ------------------------------------------------------------------

    def _rule_bsl191_201_query_text_diagnostics(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if self._rule_enabled(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        if query_blocks is None:
            blocks = (
                (
                    start_idx,
                    list(_iter_query_text_content_lines(start_idx, block_lines)),
                )
                for start_idx, block_lines in _iter_query_text_blocks(lines)
            )
        else:
            blocks = (
                (
                    block.start_idx,
                    _query_block_content_line_tuples(block),
                )
                for block in query_blocks
            )

        for _start_idx, content_lines in blocks:
            for line_no, content_base, _content, head, _ended_query in content_lines:
                if "BSL191" in enabled:
                    for match in _RE_QUERY_FULL_OUTER_JOIN.finditer(head):
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start(),
                                end_line=line_no,
                                end_character=content_base + match.end(),
                                severity=Severity.WARNING,
                                code="BSL191",
                                message="Полное внешнее соединение в запросе",
                            )
                        )

                if "BSL201" in enabled:
                    for match in _RE_QUERY_LIKE_OPERATOR.finditer(head):
                        rhs = head[match.end() :].lstrip()
                        if not rhs:
                            continue
                        stop_match = _RE_QUERY_LIKE_TAIL_STOP.search(rhs)
                        rhs = rhs[: stop_match.start()] if stop_match else rhs
                        rhs = rhs.strip()
                        if not rhs:
                            continue
                        if "&" in rhs or '"' in rhs:
                            continue
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start(),
                                end_line=line_no,
                                end_character=content_base + match.end(),
                                severity=Severity.WARNING,
                                code="BSL201",
                                message="Некорректное использование ПОДОБНО в запросе",
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL192 / BSL193 / BSL194 / BSL228 / BSL266 — method contract diagnostics
    # ------------------------------------------------------------------

    def _rule_bsl192_193_194_228_266_method_contract_diagnostics(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if self._rule_enabled(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        for proc in procs:
            start_char, end_char = _proc_name_span(lines, proc)

            if "BSL192" in enabled and proc.kind == "function" and _RE_BSL192_GET.match(proc.name):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=start_char,
                        end_line=proc.start_idx + 1,
                        end_character=end_char,
                        severity=Severity.INFORMATION,
                        code="BSL192",
                        message="Имя функции должно начинаться с «Получить»",
                    )
                )

            if "BSL228" in enabled and proc.optional_params:
                seen_optional = False
                for param in proc.params:
                    if param in proc.optional_params:
                        seen_optional = True
                        continue
                    if seen_optional:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=proc.start_idx + 1,
                                character=start_char,
                                end_line=proc.start_idx + 1,
                                end_character=end_char,
                                severity=Severity.INFORMATION,
                                code="BSL228",
                                message="Порядок параметров метода не соответствует соглашению",
                            )
                        )
                        break

            if "BSL193" in enabled and proc.kind == "function":
                ref_params = {
                    p.casefold()
                    for p in proc.params
                    if p.casefold() not in {n.casefold() for n in proc.val_params}
                }
                seen_out: set[str] = set()
                for idx in range(proc.start_idx + 1, proc.end_idx + 1):
                    code_line = lines[idx].split("//", 1)[0]
                    m_assign = _RE_ASSIGN_LHS.match(code_line)
                    if not m_assign:
                        continue
                    lhs_cf = m_assign.group("name").casefold()
                    if lhs_cf in ref_params and lhs_cf not in seen_out:
                        seen_out.add(lhs_cf)
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=m_assign.start("name"),
                                end_line=idx + 1,
                                end_character=m_assign.end("name"),
                                severity=Severity.WARNING,
                                code="BSL193",
                                message="Функция изменяет параметр-ссылку (out-параметр)",
                            )
                        )

            if (
                "BSL194" in enabled
                and proc.kind == "function"
                and not proc.name.casefold().startswith(("подключаемый_", "attachable_"))
            ):
                return_exprs: list[str] = []
                for idx in range(proc.start_idx + 1, proc.end_idx + 1):
                    code_line = lines[idx].split("//", 1)[0]
                    m_return = _RE_RETURN_SIMPLE_EXPR.match(code_line)
                    if not m_return:
                        continue
                    expr = m_return.group(1).strip()
                    if not (
                        re.fullmatch(r"-?\d+(?:\.\d+)?", expr)
                        or re.fullmatch(r'"(?:[^"]|"")*"', expr)
                        or expr.casefold()
                        in {"истина", "ложь", "true", "false", "неопределено", "undefined", "null"}
                    ):
                        return_exprs = []
                        break
                    return_exprs.append(expr.casefold())
                if len(return_exprs) > 1 and len(set(return_exprs)) == 1:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=Severity.INFORMATION,
                            code="BSL194",
                            message="Функция всегда возвращает одно и то же примитивное значение",
                        )
                    )

            if "BSL266" in enabled:
                cancel_params = {p.casefold() for p in proc.params if _RE_BSL266_CANCEL.match(p)}
                if cancel_params:
                    for idx in range(proc.start_idx + 1, proc.end_idx + 1):
                        code_line = lines[idx].split("//", 1)[0].strip()
                        m_assign = _RE_ASSIGN_LHS.match(code_line)
                        if not m_assign:
                            continue
                        lhs = m_assign.group("name")
                        lhs_cf = lhs.casefold()
                        if lhs_cf not in cancel_params:
                            continue
                        rhs = code_line[m_assign.end() :].rstrip().rstrip(";").strip()
                        rhs_cf = rhs.casefold()
                        valid = rhs_cf in {"истина", "true"} or (
                            re.search(r"\b(?:или|or)\b", rhs, re.IGNORECASE)
                            and re.search(rf"\b{re.escape(lhs)}\b", rhs, re.IGNORECASE)
                        )
                        if not valid:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=idx + 1,
                                    character=m_assign.start("name"),
                                    end_line=idx + 1,
                                    end_character=len(lines[idx].rstrip()),
                                    severity=Severity.WARNING,
                                    code="BSL266",
                                    message="Параметр «Отказ» изменяется некорректно",
                                )
                            )

        return diags

    # ------------------------------------------------------------------
    # BSL171 / BSL204 / BSL217 / BSL248 / BSL251 / BSL252 / BSL259 / BSL268
    # ------------------------------------------------------------------

    def _rule_bsl171_204_217_248_251_252_259_268_light_pool(
        self,
        path: str,
        content: str,
        lines: list[str],
        tree: Any,
        procs: list[_ProcInfo],
        codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if self._rule_enabled(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        root = getattr(tree, "root_node", None)
        tree_ok = root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))

        if "BSL171" in enabled:
            diags.extend(
                self._rule_bsl171_crazy_multiline_string(path, lines, tree if tree_ok else None)
            )
        if "BSL204" in enabled:
            diags.extend(self._rule_bsl204_invalid_character_in_file(path, content, lines))
        if "BSL217" in enabled:
            diags.extend(
                self._rule_bsl217_missing_temp_storage_deletion(
                    path, lines, tree if tree_ok else None
                )
            )
        if "BSL248" in enabled:
            diags.extend(
                self._rule_bsl248_several_compiler_directives(
                    path, lines, tree if tree_ok else None, procs
                )
            )
        if "BSL251" in enabled:
            diags.extend(
                self._rule_bsl251_ternary_operator_usage(path, lines, tree if tree_ok else None)
            )
        if "BSL252" in enabled:
            diags.extend(
                self._rule_bsl252_this_object_assign(path, lines, tree if tree_ok else None)
            )
        if "BSL259" in enabled:
            diags.extend(
                self._rule_bsl259_unknown_preprocessor_symbol(
                    path, lines, tree if tree_ok else None
                )
            )
        if "BSL268" in enabled:
            diags.extend(
                self._rule_bsl268_using_find_element_by_string(
                    path, lines, tree if tree_ok else None
                )
            )
        return diags

    def _rule_bsl171_crazy_multiline_string(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in _ts_walk(tree.root_node):
                if getattr(node, "type", None) != "ERROR":
                    continue
                text = _ts_node_text(node).strip()
                if not (text.startswith('"') and text.endswith('"')):
                    continue
                line_idx = node.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character(line_text, node.start_point[1]),
                        end_line=line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character(
                            line_text, node.end_point[1]
                        ),
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=RULE_DESCRIPTIONS_RU["BSL171"],
                    )
                )
        if diags:
            return diags

        for idx, line in enumerate(lines):
            match = _RE_BSL171_ADJACENT_LITERALS.search(line)
            if match is not None:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=match.start(),
                        end_line=idx + 1,
                        end_character=match.end(),
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=RULE_DESCRIPTIONS_RU["BSL171"],
                    )
                )
                continue
            if idx == 0:
                continue
            prev = lines[idx - 1].rstrip()
            cur = line.lstrip()
            if prev.endswith('"') and cur.startswith('"'):
                end_character = min(
                    len(line.rstrip()), len(line) - len(cur) + len(cur.split('"', 2)[1]) + 2
                )
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=len(line) - len(cur),
                        end_line=idx + 1,
                        end_character=end_character,
                        severity=Severity.INFORMATION,
                        code="BSL171",
                        message=RULE_DESCRIPTIONS_RU["BSL171"],
                    )
                )
        return diags

    def _rule_bsl204_invalid_character_in_file(
        self, path: str, content: str, lines: list[str]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for line_idx, line in enumerate(lines, start=1):
            for col, ch in enumerate(line):
                message = _BSL204_ILLEGAL_CHARS.get(ch)
                if message is None:
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx,
                        character=col,
                        end_line=line_idx,
                        end_character=col + 1,
                        severity=Severity.WARNING,
                        code="BSL204",
                        message=message,
                    )
                )
        if content and content[-1] in _BSL204_ILLEGAL_CHARS:
            col = len(lines[-1]) if lines else 0
            diags.append(
                Diagnostic(
                    file=path,
                    line=len(lines),
                    character=col,
                    end_line=len(lines),
                    end_character=col + 1,
                    severity=Severity.WARNING,
                    code="BSL204",
                    message=_BSL204_ILLEGAL_CHARS[content[-1]],
                )
            )
        return diags

    def _rule_bsl217_missing_temp_storage_deletion(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        line_texts = lines
        diags: list[Diagnostic] = []

        for call in _ts_global_method_calls(tree.root_node, line_texts):
            if str(call["name"]).casefold() not in _BSL217_GET_FROM_TEMP_STORAGE_NAMES:
                continue
            method_node = call["node"]
            assign_anc: Any | None = None
            cur: Any | None = method_node
            while cur is not None:
                if getattr(cur, "type", None) == "assignment_statement":
                    assign_anc = cur
                    break
                cur = getattr(cur, "parent", None)

            span = _ts_method_identifier_span(method_node, line_texts)
            if span is None:
                continue
            line_1, char_1, end_ch = span

            if assign_anc is None:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL217",
                        message=RULE_DESCRIPTIONS_RU["BSL217"],
                    )
                )
                continue

            var_name = _ts_assignment_lvalue_text(assign_anc)
            if not var_name:
                continue
            stmt_parent = _ts_bsl218_skip_error_ancestor(getattr(assign_anc, "parent", None))
            roots = _ts_bsl218_code_block_roots(stmt_parent) if stmt_parent is not None else None
            if not roots:
                continue
            deleted = False
            for subtree in roots:
                for later_call in _ts_global_method_calls(subtree, line_texts):
                    if later_call["line"] <= line_1:
                        continue
                    if (
                        str(later_call["name"]).casefold()
                        not in _BSL217_DELETE_FROM_TEMP_STORAGE_NAMES
                    ):
                        continue
                    for expr in _ts_method_call_arg_exprs(later_call["node"]):
                        if _ts_node_text(expr).strip().casefold() == var_name.casefold():
                            deleted = True
                            break
                    if deleted:
                        break
                if deleted:
                    break
            if deleted:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=Severity.WARNING,
                    code="BSL217",
                    message=RULE_DESCRIPTIONS_RU["BSL217"],
                )
            )
        return diags

    def _rule_bsl248_several_compiler_directives(
        self, path: str, lines: list[str], tree: Any | None, procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        root = tree.root_node
        children = list(getattr(root, "children", []) or [])
        proc_by_line = {proc.start_idx: proc for proc in procs}

        idx = 0
        while idx < len(children):
            directives: list[Any] = []
            while idx < len(children) and getattr(children[idx], "type", None) == "preprocessor":
                if _ts_node_text(children[idx]).strip().startswith("&"):
                    directives.append(children[idx])
                idx += 1
            if idx >= len(children):
                break
            node = children[idx]
            node_type = getattr(node, "type", None)
            if len(directives) > 1 and node_type in {
                "procedure_definition",
                "function_definition",
                "var_definition",
            }:
                if node_type in {"procedure_definition", "function_definition"}:
                    proc = proc_by_line.get(node.start_point[0])
                    if proc is not None:
                        start_char, end_char = _proc_name_span(lines, proc)
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=proc.start_idx + 1,
                                character=start_char,
                                end_line=proc.start_idx + 1,
                                end_character=end_char,
                                severity=Severity.ERROR,
                                code="BSL248",
                                message=RULE_DESCRIPTIONS_RU["BSL248"],
                            )
                        )
                else:
                    line_idx = node.start_point[0]
                    line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_idx + 1,
                            character=0,
                            end_line=line_idx + 1,
                            end_character=len(line_text.rstrip()),
                            severity=Severity.ERROR,
                            code="BSL248",
                            message=RULE_DESCRIPTIONS_RU["BSL248"],
                        )
                    )
            idx += 1
        return diags

    def _rule_bsl251_ternary_operator_usage(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in _ts_walk(tree.root_node):
            if getattr(node, "type", None) != "ternary_expression":
                continue
            line_idx = node.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=utf8_byte_offset_to_lsp_character(line_text, node.start_point[1]),
                    end_line=line_idx + 1,
                    end_character=utf8_byte_offset_to_lsp_character(line_text, node.end_point[1]),
                    severity=Severity.INFORMATION,
                    code="BSL251",
                    message=RULE_DESCRIPTIONS_RU["BSL251"],
                )
            )
        return diags

    def _rule_bsl252_this_object_assign(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        low = path.replace("\\", "/").lower()
        if not (path_is_likely_form_module_bsl(path) or _RE_COMMON_MODULE_PATH.search(low)):
            return []
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in _ts_walk(tree.root_node):
            if getattr(node, "type", None) != "assignment_statement":
                continue
            ident = _ts_child_of_type(node, "identifier")
            if ident is None:
                continue
            if _ts_node_text(ident).casefold() not in {"этотобъект", "thisobject"}:
                continue
            line_idx = ident.start_point[0]
            line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=utf8_byte_offset_to_lsp_character(line_text, ident.start_point[1]),
                    end_line=line_idx + 1,
                    end_character=utf8_byte_offset_to_lsp_character(line_text, ident.end_point[1]),
                    severity=Severity.ERROR,
                    code="BSL252",
                    message=RULE_DESCRIPTIONS_RU["BSL252"],
                )
            )
        return diags

    def _rule_bsl259_unknown_preprocessor_symbol(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in _ts_walk(tree.root_node):
                if getattr(node, "type", None) != "preprocessor":
                    continue
                expr = _ts_child_of_type(node, "expression")
                if expr is None:
                    continue
                for child in _ts_walk(expr):
                    if getattr(child, "type", None) != "identifier":
                        continue
                    name = _ts_node_text(child)
                    if name.casefold() in _BSL259_ALLOWED_PREPROC_SYMBOLS:
                        continue
                    line_idx = child.start_point[0]
                    line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_idx + 1,
                            character=utf8_byte_offset_to_lsp_character(
                                line_text, child.start_point[1]
                            ),
                            end_line=line_idx + 1,
                            end_character=utf8_byte_offset_to_lsp_character(
                                line_text, child.end_point[1]
                            ),
                            severity=Severity.WARNING,
                            code="BSL259",
                            message=f'Неизвестный символ препроцессора "{name}"',
                        )
                    )
            return diags

        for idx, line in enumerate(lines):
            match = _RE_BSL259_PREPROC_IF.match(line)
            if match is None:
                continue
            expr_text = match.group("expr")
            for ident in _RE_BSL259_IDENTIFIER.finditer(expr_text):
                name = ident.group(0)
                if name.casefold() in _BSL259_ALLOWED_PREPROC_SYMBOLS | _BSL259_PREPROC_KEYWORDS:
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=ident.start(),
                        end_line=idx + 1,
                        end_character=ident.end(),
                        severity=Severity.WARNING,
                        code="BSL259",
                        message=f'Неизвестный символ препроцессора "{name}"',
                    )
                )
        return diags

    def _rule_bsl268_using_find_element_by_string(
        self, path: str, lines: list[str], tree: Any | None
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        target_names = {
            "найтипонаименованию",
            "findbydescription",
            "найтипокоду",
            "findbycode",
            "найтипономеру",
            "findbynumber",
        }
        if tree is not None:
            for node in _ts_walk(tree.root_node):
                if getattr(node, "type", None) != "method_call":
                    continue
                ident = _ts_child_of_type(node, "identifier")
                if ident is None:
                    continue
                name = _ts_node_text(ident)
                if name.casefold() not in target_names:
                    continue
                args = _ts_method_call_arg_exprs(node)
                if len(args) > 1:
                    continue
                if args:
                    arg_text = _ts_node_text(args[0]).strip()
                    if arg_text and not (
                        (arg_text.startswith('"') and arg_text.endswith('"'))
                        or re.fullmatch(r"\d+(?:\.\d+)?", arg_text)
                    ):
                        continue
                line_idx = ident.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=utf8_byte_offset_to_lsp_character(
                            line_text, ident.start_point[1]
                        ),
                        end_line=line_idx + 1,
                        end_character=utf8_byte_offset_to_lsp_character(
                            line_text, ident.end_point[1]
                        ),
                        severity=Severity.WARNING,
                        code="BSL268",
                        message=f'Использование метода "{name}" снижает производительность поиска',
                    )
                )
            return diags

        for idx, line in enumerate(lines):
            match = _RE_BSL268_FIND_BY_STRING.search(line)
            if match is None:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=match.start("name"),
                    end_line=idx + 1,
                    end_character=match.end("name"),
                    severity=Severity.WARNING,
                    code="BSL268",
                    message=f'Использование метода "{match.group("name")}" снижает производительность поиска',
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL206 / BSL207 / BSL209 — join-related query diagnostics
    # ------------------------------------------------------------------

    def _rule_bsl212_missed_required_parameter(
        self,
        path: str,
        content: str,
        lines: list[str],
        procs: list[_ProcInfo],
        calls: list[Any],
    ) -> list[Diagnostic]:
        """Flag same-file calls that omit required parameters."""
        proc_by_name = {proc.name.casefold(): proc for proc in procs}
        if not proc_by_name or not calls:
            return []

        diags: list[Diagnostic] = []
        line_starts = line_start_offsets(content)
        for call in calls:
            callee = proc_by_name.get(call.callee_name.casefold())
            if callee is None:
                continue
            required_params = [p for p in callee.params if p not in callee.optional_params]
            if not required_params:
                continue
            arg_presence = _extract_call_argument_presence(
                content,
                line_starts,
                line=call.caller_line,
                character=call.caller_character,
                callee_name=call.callee_name,
            )
            if arg_presence is None:
                continue

            missed: list[str] = []
            for idx, param_name in enumerate(callee.params):
                if param_name in callee.optional_params:
                    continue
                if idx >= len(arg_presence) or not arg_presence[idx]:
                    missed.append(param_name)

            if not missed:
                continue
            line_text = (
                lines[call.caller_line - 1] if 0 <= call.caller_line - 1 < len(lines) else ""
            )
            diags.append(
                Diagnostic(
                    file=path,
                    line=call.caller_line,
                    character=call.caller_character,
                    end_line=call.caller_line,
                    end_character=len(line_text.rstrip()),
                    severity=Severity.ERROR,
                    code="BSL212",
                    message=f"Пропущен обязательный параметр в вызове метода: {', '.join(missed)}",
                )
            )
        return diags

    def _rule_bsl206_207_209_query_join_diagnostics(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        enabled = {code for code in codes if self._rule_enabled(code)}
        if not enabled:
            return []

        diags: list[Diagnostic] = []
        if query_blocks is None:
            blocks = (
                (
                    start_idx,
                    list(block_lines),
                    list(_iter_query_text_content_lines(start_idx, block_lines)),
                )
                for start_idx, block_lines in _iter_query_text_blocks(lines)
            )
        else:
            blocks = (
                (
                    block.start_idx,
                    list(block.block_lines),
                    _query_block_content_line_tuples(block),
                )
                for block in query_blocks
            )

        for _start_idx, block_lines, content_lines in blocks:
            if not any(_RE_QUERY_JOIN_KEYWORD.search(line) for line in block_lines):
                continue

            pending_datasource = False
            join_on_active = False
            join_buffer = ""

            for line_no, content_base, _content, head, _ended_query in content_lines:
                if _RE_QUERY_JOIN_END_KEYWORD.search(head):
                    join_on_active = False
                    join_buffer = ""
                    pending_datasource = False

                same_line_datasource = bool(
                    re.search(r"\b(?:ИЗ|FROM)\s*$", head, re.IGNORECASE)
                    or re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                    or _RE_QUERY_JOIN_KEYWORD.search(head)
                    or re.search(
                        r"\b(?:ИЗ|FROM)\s*(\(\s*(?:ВЫБРАТЬ|SELECT)\b)", head, re.IGNORECASE
                    )
                    or re.search(
                        r"\b(?:ИЗ|FROM)\s*(" + _RE_QUERY_VIRTUAL_TABLE.pattern + r")",
                        head,
                        re.IGNORECASE,
                    )
                )

                if pending_datasource or same_line_datasource:
                    if "BSL206" in enabled:
                        subquery_match = _RE_QUERY_DATASOURCE_SUBQUERY.search(head)
                        if subquery_match:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + subquery_match.start(),
                                    end_line=line_no,
                                    end_character=content_base + subquery_match.end(),
                                    severity=Severity.WARNING,
                                    code="BSL206",
                                    message="Соединение с подзапросом в запросе",
                                )
                            )
                    if "BSL207" in enabled:
                        virtual_match = _RE_QUERY_VIRTUAL_TABLE.search(head)
                        if virtual_match:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + virtual_match.start(),
                                    end_line=line_no,
                                    end_character=content_base + virtual_match.end(),
                                    severity=Severity.WARNING,
                                    code="BSL207",
                                    message="Соединение с виртуальной таблицей в запросе",
                                )
                            )

                pending_datasource = bool(
                    re.search(r"\b(?:ИЗ|FROM)\s*$", head, re.IGNORECASE)
                    or re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                    or _RE_QUERY_JOIN_KEYWORD.search(head)
                ) and not _RE_QUERY_ON_KEYWORD.search(head)

                on_match = _RE_QUERY_ON_KEYWORD.search(head)
                if on_match:
                    join_on_active = True
                    join_buffer = head[on_match.end() :]
                elif join_on_active:
                    if _RE_QUERY_JOIN_KEYWORD.search(head):
                        join_on_active = False
                        join_buffer = ""
                    else:
                        join_buffer += " " + head

                if join_on_active and "BSL209" in enabled:
                    fields = set(_RE_QUERY_COLUMN_REF.findall(join_buffer))
                    if len(fields) > 1:
                        for or_match in _RE_BSL210_OR.finditer(head):
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + or_match.start(),
                                    end_line=line_no,
                                    end_character=content_base + or_match.end(),
                                    severity=Severity.WARNING,
                                    code="BSL209",
                                    message="Логическое ИЛИ в секции соединения запроса",
                                )
                            )

        return diags

    # ------------------------------------------------------------------
    # BSL190 — FormDataToValue
    # ------------------------------------------------------------------

    def _rule_bsl190_form_data_to_value(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag calls to ДанныеФормыВЗначение()/FormDataToValue() — slow operation.

        BSLLS: prefer working with server objects directly instead of converting
        form data to value, which involves full serialization/deserialization.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            m = _RE_BSL190_FORM_DATA.search(clean)
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL190",
                        message=(
                            "ДанныеФормыВЗначение()/FormDataToValue() — медленная операция; "
                            "работайте с серверными объектами напрямую"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL197 — IfElseDuplicatedCodeBlock
    # ------------------------------------------------------------------

    def _rule_bsl197_if_else_duplicated_code_block(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect identical code blocks in consecutive If/ElseIf branches."""
        diags: list[Diagnostic] = []
        comment_re = re.compile(r"^\s*//")
        i = 0
        while i < len(lines):
            if not _RE_BSL197_IF.match(lines[i]):
                i += 1
                continue

            # Collect branches: list of (body_lines, (diag_line, diag_col, diag_end))
            branches: list[tuple[list[str], tuple[int, int, int] | None]] = []
            branch_start = i
            branch_header = lines[i]
            depth = 1
            j = i + 1
            current_body: list[str] = []

            def _normalize_body(body: list[str]) -> list[str]:
                return [
                    entry.strip() for entry in body if entry.strip() and not comment_re.match(entry)
                ]

            def _diag_span_for_body(
                body: list[str], start: int, header: str
            ) -> tuple[int, int, int]:
                for offset, raw in enumerate(body, start=1):
                    stripped = raw.strip()
                    if stripped and not comment_re.match(raw):
                        col = len(raw) - len(raw.lstrip())
                        return start + offset, col, len(raw.rstrip())
                col = len(header) - len(header.lstrip())
                return start, col, len(header.rstrip())

            while j < len(lines) and depth > 0:
                bl = lines[j]
                if _RE_BSL197_IF.match(bl):
                    depth += 1
                elif _RE_BSL197_ENDIF.match(bl):
                    depth -= 1
                    if depth == 0:
                        branches.append(
                            (
                                _normalize_body(current_body),
                                _diag_span_for_body(current_body, branch_start, branch_header),
                            )
                        )
                        break
                if depth == 1 and (_RE_BSL197_ELSEIF.match(bl) or _RE_BSL197_ELSE.match(bl)):
                    branches.append(
                        (
                            _normalize_body(current_body),
                            _diag_span_for_body(current_body, branch_start, branch_header),
                        )
                    )
                    current_body = []
                    branch_start = j
                    branch_header = bl
                else:
                    if depth == 1:
                        current_body.append(bl)
                j += 1

            # Align with BSLLS: report the first duplicated block rather than later aliases.
            seen: dict[str, tuple[int, int, int] | None] = {}
            reported: set[str] = set()
            for b_body, span in branches:
                key = "\n".join(b_body)
                if key and key in seen and key not in reported:
                    first_span = seen[key]
                    if first_span is None:
                        continue
                    line_no, col, end_col = first_span
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_no + 1,
                            character=col,
                            end_line=line_no + 1,
                            end_character=end_col,
                            severity=Severity.WARNING,
                            code="BSL197",
                            message="Есть повторяющийся блок кода в условном операторе",
                        )
                    )
                    reported.add(key)
                else:
                    seen[key] = span
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
        i = 0
        while i < len(lines):
            m = _RE_BSL198_IF_COND.match(lines[i])
            if not m:
                i += 1
                continue

            conditions: dict[str, int] = {m.group(1).strip().casefold(): i}
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                bl = lines[j]
                if _RE_BSL197_IF.match(bl):
                    depth += 1
                elif _RE_BSL197_ENDIF.match(bl):
                    depth -= 1
                elif depth == 1:
                    em = _RE_BSL198_ELSEIF_COND.match(bl)
                    if em:
                        cond = em.group(1).strip().casefold()
                        if cond in conditions:
                            diags.append(
                                Diagnostic(
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
                                )
                            )
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
                diags.append(
                    Diagnostic(
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
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL175 / BSL176 / BSL177 / BSL179 / BSL195 — deprecated API pool
    # ------------------------------------------------------------------

    def _rule_bsl175_176_177_179_195_deprecated_api_diagnostics(
        self,
        path: str,
        lines: list[str],
        symbols: list[Any],
        calls: list[Any],
        enabled_codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        """Batch deprecated API diagnostics sharing one lightweight source pass."""
        enabled = set(enabled_codes)
        diags: list[Diagnostic] = []

        deprecated_locals: dict[str, str] = {}
        deprecated_callers: set[str] = set()
        if "BSL176" in enabled:
            for sym in symbols:
                if getattr(sym, "kind", "") not in {"procedure", "function"}:
                    continue
                doc_comment = getattr(sym, "doc_comment", "") or ""
                if not _RE_BSL176_DEPRECATED_DOC.search(doc_comment):
                    continue
                name = getattr(sym, "name", "")
                if not name:
                    continue
                deprecated_locals[name.casefold()] = name
                deprecated_callers.add(name.casefold())

        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = _mask_double_quoted_strings_preserve_len(line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
                line = line[:comment_pos]

            if "BSL175" in enabled:
                for match in _RE_BSL175_ATTRIBUTE.finditer(clean):
                    name = match.group("name")
                    replacement = _BSL175_ATTR_REPLACEMENTS.get(name.casefold())
                    if not replacement:
                        continue
                    if name.casefold() in _BSL175_METHOD_REPLACEMENTS:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("name"),
                                end_line=idx + 1,
                                end_character=match.end("name"),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message=(
                                    f'Метод "{name}" устарел. Вместо него стоит использовать '
                                    f'"{replacement}"'
                                ),
                            )
                        )
                    else:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("name"),
                                end_line=idx + 1,
                                end_character=match.end("name"),
                                severity=Severity.INFORMATION,
                                code="BSL175",
                                message=(
                                    f'Атрибут "{name}" устарел. Вместо него стоит использовать '
                                    f"{replacement}"
                                ),
                            )
                        )
                for match in _RE_BSL175_CHILD_FORM_ITEMS.finditer(clean):
                    name = match.group("name")
                    replacement = _BSL175_ENUM_REPLACEMENTS.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=(
                                f'Используется старое наименование "{name}". Вместо него '
                                f'необходимо использовать "{replacement}"'
                            ),
                        )
                    )
                for match in _RE_BSL175_ENUM_NAME.finditer(clean):
                    name = match.group("name")
                    replacement = _BSL175_ENUM_REPLACEMENTS.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=(
                                f'Используется старое наименование "{name}". Вместо него '
                                f'необходимо использовать "{replacement}"'
                            ),
                        )
                    )
                for match in _RE_BSL175_GLOBAL_METHOD.finditer(clean):
                    name = match.group("name")
                    if name.casefold() not in _BSL175_GLOBAL_METHODS:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL175",
                            message=f'Метод "{name}" устарел и больше не используется',
                        )
                    )

            if "BSL177" in enabled:
                for match in _RE_BSL177_GLOBAL_METHOD.finditer(clean):
                    name = match.group("name")
                    replacement = _BSL177_METHOD_REPLACEMENTS.get(name.casefold())
                    if not replacement:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.INFORMATION,
                            code="BSL177",
                            message=(
                                f'Метод "{name}" устарел. Следует использовать "{replacement}".'
                            ),
                        )
                    )

            if "BSL179" in enabled:
                for match in _RE_BSL179_MANAGED_FORM.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start(),
                            end_line=idx + 1,
                            end_character=match.end(),
                            severity=Severity.INFORMATION,
                            code="BSL179",
                            message='Замените устаревшее использование типа "УправляемаяФорма"',
                        )
                    )

            if "BSL195" in enabled:
                for match in _RE_BSL195_GET_FORM.finditer(clean):
                    name = match.group("name")
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL195",
                            message="Не рекомендуемое использование метода ПолучитьФорму",
                        )
                    )

        if "BSL176" in enabled and deprecated_locals:
            for call in calls:
                callee_name = getattr(call, "callee_name", "")
                if not callee_name:
                    continue
                callee_cf = callee_name.casefold()
                if callee_cf not in deprecated_locals:
                    continue
                caller_name = getattr(call, "caller_name", None)
                if caller_name and caller_name.casefold() in deprecated_callers:
                    continue
                start_char = int(getattr(call, "caller_character", 0))
                diags.append(
                    Diagnostic(
                        file=path,
                        line=int(getattr(call, "caller_line", 1)),
                        character=start_char,
                        end_line=int(getattr(call, "caller_line", 1)),
                        end_character=start_char + len(callee_name),
                        severity=Severity.INFORMATION,
                        code="BSL176",
                        message=f'Удалите вызов устаревшего метода "{callee_name}".',
                    )
                )

        return diags

    # ------------------------------------------------------------------
    # BSL180 / BSL184 / BSL185 / BSL188 / BSL203 / BSL226 / BSL247 /
    # BSL250 / BSL264 / BSL267 / BSL270 / BSL272 — security/context API pool
    # ------------------------------------------------------------------

    def _rule_bsl180_184_185_188_203_226_247_250_264_267_270_272_api_pool(
        self,
        path: str,
        lines: list[str],
        enabled_codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled = set(enabled_codes)
        diags: list[Diagnostic] = []
        is_common_module = bool(_RE_COMMON_MODULE_PATH.search(path))

        for idx, raw_line in enumerate(lines):
            if _RE_LINE_COMMENT.match(raw_line):
                continue
            line = _strip_inline_comment_preserve_strings(raw_line)
            if not line.strip():
                continue

            if "BSL180" in enabled:
                for match in _RE_BSL180_DISABLE_SAFE_MODE.finditer(line):
                    name = match.group("name")
                    arg = match.group("arg").strip()
                    name_cf = name.casefold()
                    if name_cf in {"установитьбезопасныйрежим", "setsafemode"}:
                        if arg.casefold() in {"истина", "true"}:
                            continue
                    else:
                        if arg.casefold() in {"ложь", "false"}:
                            continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL180",
                            message="Проверьте отключение безопасного режима",
                        )
                    )

            if "BSL184" in enabled and is_common_module:
                for match in _RE_BSL184_EXECUTE_EXTERNAL_CODE.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL184",
                            message=(
                                "Выполнение произвольного кода в общем модуле на сервере "
                                "является потенциальной уязвимостью"
                            ),
                        )
                    )

            if "BSL185" in enabled:
                for match in _RE_BSL185_EXTERNAL_APP.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL185",
                            message="Проверьте запуск внешнего приложения",
                        )
                    )

            if "BSL188" in enabled:
                for match in _RE_BSL188_FILESYSTEM_METHOD.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL188",
                            message="Проверьте обращение к файловой системе",
                        )
                    )
                for match in _RE_BSL188_FILESYSTEM_NEW.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=max(0, match.start("type") - len("Новый ")),
                            end_line=idx + 1,
                            end_character=match.start("type"),
                            severity=Severity.WARNING,
                            code="BSL188",
                            message="Проверьте обращение к файловой системе",
                        )
                    )

            if "BSL203" in enabled:
                for match in _RE_BSL203_INTERNET_NEW.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=max(0, match.start("type") - len("Новый ")),
                            end_line=idx + 1,
                            end_character=match.start("type"),
                            severity=Severity.WARNING,
                            code="BSL203",
                            message="Проверьте обращение к Интернет-ресурсам",
                        )
                    )

            if "BSL226" in enabled:
                for match in _RE_BSL226_OS_USERS.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL226",
                            message="Проверить потенциально вредоносное использование метода ПользователиОС",
                        )
                    )

            if "BSL247" in enabled:
                for match in _RE_BSL247_SET_PRIVILEGED.finditer(line):
                    arg = match.group("arg").strip()
                    if arg.casefold() in {"ложь", "false"}:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL247",
                            message="Проверьте установку привилегированного режима",
                        )
                    )

            if "BSL250" in enabled:
                for match in _RE_BSL250_TEMPFILES.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL250",
                            message="Не рекомендуемый вызов функции КаталогВременныхФайлов()",
                        )
                    )

            if "BSL264" in enabled:
                for match in _RE_BSL264_SYSTEM_INFO.finditer(line):
                    anchor_start = max(0, line.rfind("Новый", 0, match.start("type") + 1))
                    anchor_end = anchor_start + len("Новый")
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=anchor_start,
                            end_line=idx + 1,
                            end_character=anchor_end,
                            severity=Severity.WARNING,
                            code="BSL264",
                            message="Избавьтесь от использования объекта `СистемнаяИнформация`",
                        )
                    )

            if "BSL267" in enabled:
                for match in _RE_BSL267_EXTERNAL_CODE_TOOLS.finditer(line):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start(),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL267",
                            message="Запрещено использование возможности выполнения внешнего кода",
                        )
                    )

            if "BSL270" in enabled:
                for match in _RE_BSL270_MODAL.finditer(line):
                    method_name = match.group("name")
                    replacement = _BSL270_MODAL_REPLACEMENTS.get(method_name.upper(), "")
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL270",
                            message=(
                                f"Вместо модального метода `{method_name}` необходимо "
                                f"использовать `{replacement}`"
                            ),
                        )
                    )

            if "BSL272" in enabled:
                for match in _RE_BSL272_SYNC.finditer(line):
                    method_name = match.group("name")
                    replacement = _BSL272_SYNC_REPLACEMENTS.get(method_name.upper(), "")
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start("name"),
                            end_line=idx + 1,
                            end_character=match.end("name"),
                            severity=Severity.WARNING,
                            code="BSL272",
                            message=(
                                f"Вместо синхронного метода `{method_name}` необходимо "
                                f"использовать `{replacement}`"
                            ),
                        )
                    )

        return diags

    # ------------------------------------------------------------------
    # BSL178 — DeprecatedMethods8317
    # ------------------------------------------------------------------

    def _rule_bsl178_deprecated_methods_8317(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Detect methods deprecated since 8.3.17."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []
        deprecated = {
            "краткоепредставлениеошибки",
            "brieferrordescription",
            "подробноепредставлениеошибки",
            "detailerrordescription",
            "показатьинформациюобошибке",
            "showerrorinfo",
        }
        diags: list[Diagnostic] = []
        for call in _ts_global_method_calls(root, lines):
            name_cf = str(call["name"]).casefold()
            if name_cf not in deprecated:
                continue
            line_text = lines[call["line"] - 1] if 0 < call["line"] <= len(lines) else ""
            exact_start = line_text.find(str(call["name"]))
            start_char = exact_start if exact_start >= 0 else call["character"]
            diags.append(
                Diagnostic(
                    file=path,
                    line=call["line"],
                    character=start_char,
                    end_line=call["line"],
                    end_character=start_char + len(str(call["name"])),
                    severity=Severity.INFORMATION,
                    code="BSL178",
                    message=(
                        f'Метод "{call["name"]}" устарел. Следует использовать одноименный '
                        "метод объекта типа МенеджерОбработкиОшибок"
                    ),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL258 — UnionAll
    # ------------------------------------------------------------------

    def _rule_bsl258_union_without_all(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                diags.append(
                    Diagnostic(
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
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL153 — CanonicalSpellingKeywords
    # ------------------------------------------------------------------

    # BSL canonical keyword forms (title case)
    _CANONICAL_KEYWORDS: dict[str, str] = {
        "если": "Если",
        "иначеесли": "ИначеЕсли",
        "иначе": "Иначе",
        "конецесли": "КонецЕсли",
        "для": "Для",
        # "каждого" omitted — BSLLS accepts both "Каждого" and "каждого" (EACH_LO variant)
        "из": "Из",
        "цикл": "Цикл",
        "конеццикла": "КонецЦикла",
        "пока": "Пока",
        "прервать": "Прервать",
        "продолжить": "Продолжить",
        "попытка": "Попытка",
        "исключение": "Исключение",
        "конецпопытки": "КонецПопытки",
        "вызватьисключение": "ВызватьИсключение",
        "возврат": "Возврат",
        "перейти": "Перейти",
        "процедура": "Процедура",
        "функция": "Функция",
        "конецпроцедуры": "КонецПроцедуры",
        "конецфункции": "КонецФункции",
        "перем": "Перем",
        "тогда": "Тогда",
        "по": "По",
        "новый": "Новый",
        "экспорт": "Экспорт",
        "знач": "Знач",
        "не": "Не",
        "и": "И",
        "или": "Или",
        "истина": "Истина",
        "ложь": "Ложь",
        "неопределено": "Неопределено",
        "null": "Null",
    }
    # Only flag words that differ in case from their canonical form
    _CANONICAL_RE = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in _CANONICAL_KEYWORDS) + r")\b",
        re.IGNORECASE | re.UNICODE,
    )

    def _rule_bsl153_canonical_spelling_keywords(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect BSL keywords not written in canonical title-case form."""
        if path_is_likely_form_module_bsl(path):
            return []
        diags: list[Diagnostic] = []
        _bsl036 = self._rule_enabled("BSL036")

        # Pre-compute BSL036-suppressed line indices once (O(n)) instead of
        # calling _line_in_triggered_bsl036_condition per line (O(n × 48²)).
        bsl036_skip: set[int] = set()
        if _bsl036:
            for start in range(len(lines)):
                chunk = self._bsl036_if_condition_chunk(lines, start)
                if chunk is None:
                    continue
                if len(_RE_BOOL_OP.findall(chunk)) <= self.max_bool_ops:
                    continue
                # Mark every line in this condition block (start … Тогда)
                j = start
                while j < len(lines):
                    bsl036_skip.add(j)
                    if self._RE_THEN_WORD.search(lines[j]):
                        break
                    j += 1

        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            if idx in bsl036_skip:
                continue
            # Remove string literals and inline comment
            clean = _mask_double_quoted_strings_preserve_len(line)
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
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=m.start(),
                            end_line=idx + 1,
                            end_character=m.end(),
                            severity=Severity.INFORMATION,
                            code="BSL153",
                            message=(f'Ключевое слово "{word}" написано не канонически'),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL215 — MissingParameterDescription
    # ------------------------------------------------------------------

    def _rule_bsl215_missing_parameter_description(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Export method parameters must be documented in the preceding comment block."""
        diags: list[Diagnostic] = []
        _re_blank_doc_line = re.compile(r"^\s*//\s*$")
        _re_doc_section = re.compile(
            r"^\s*//\s*(?:Параметры|Parameters|Возвращаемое значение|Returns?)\s*:?\s*$",
            re.IGNORECASE,
        )

        for proc in procs:
            if not proc.params:
                continue

            # Walk backward from proc header to find the comment block.
            # Skip blank lines and compiler directives (&НаКлиенте, &НаСервере...).
            block_end = proc.start_idx - 1
            while block_end >= 0 and (
                lines[block_end].strip() == "" or _RE_COMPILER_DIRECTIVE.match(lines[block_end])
            ):
                block_end -= 1
            # Check if there's a comment block above.
            if block_end < 0 or not _RE_BSL215_COMMENT_LINE.match(lines[block_end]):
                continue  # No comment block → skip (BSL011 handles missing comments)

            # Find the start of the comment block.
            block_start = block_end
            while block_start > 0 and _RE_BSL215_COMMENT_LINE.match(lines[block_start - 1]):
                block_start -= 1

            comment_block = lines[block_start : block_end + 1]

            # Section separator lines (////////...) are not method descriptions.
            _re_separator = re.compile(r"^\s*/{10,}\s*$")
            if any(_re_separator.match(cl) for cl in comment_block):
                continue

            # If the comment block contains a // См. / // See reference link, BSLLS
            # considers this sufficient documentation and skips the check entirely.
            _re_see_link = re.compile(r"^\s*//\s*(?:См\.|See)\s+\S", re.IGNORECASE)
            if any(_re_see_link.match(cl) for cl in comment_block):
                continue

            # BSLLS uses parsed method descriptions; a lone label comment like
            # "// Особенности ..." is not a method description and should be skipped.
            if not any(
                _re_blank_doc_line.match(cl) or _re_doc_section.match(cl) for cl in comment_block
            ):
                continue

            # Find "// Параметры:" section.
            params_section_start = None
            for ci, cl in enumerate(comment_block):
                if _RE_BSL215_PARAMS_SECTION.match(cl):
                    params_section_start = ci
                    break

            actual_params_cf = {p.casefold() for p in proc.params}

            if params_section_start is None:
                # No // Параметры: section — all params undocumented.
                # Flag at the method name position (method header line).
                header_line = lines[proc.start_idx]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=header_line.index(proc.name),
                        end_line=proc.start_idx + 1,
                        end_character=header_line.index(proc.name) + len(proc.name),
                        severity=Severity.WARNING,
                        code="BSL215",
                        message=(
                            f"Отсутствует описание параметров метода «{proc.name}» в комментарии"
                        ),
                    )
                )
                continue

            # Extract documented param names from the section.
            documented_cf: dict[str, str] = {}  # casefold → original name
            # Collect lines after "// Параметры:" that look like param entries.
            for cl in comment_block[params_section_start + 1 :]:
                # Stop at another section header (e.g. // Возвращаемое значение:)
                stripped = cl.strip()
                if stripped == "//" or (
                    re.match(r"^\s*//\s*\w[\w\s]*:\s*$", cl)
                    and not _RE_BSL215_PARAM_ENTRY.match(cl)
                ):
                    break
                m = _RE_BSL215_PARAM_ENTRY.match(cl)
                if m:
                    pname = m.group(1)
                    documented_cf[pname.casefold()] = pname

            # Find params from signature that are not in documentation.
            # Determine line positions of params in multi-line signatures.
            # Scan from proc.start_idx forward until we find the closing ')'.
            param_lines: dict[str, int] = {}  # casefold → 0-based line index
            scan_idx = proc.start_idx
            paren_depth = 0
            header_done = False
            while scan_idx < len(lines) and not header_done:
                sl = lines[scan_idx]
                for ch in sl:
                    if ch == "(":
                        paren_depth += 1
                    elif ch == ")":
                        paren_depth -= 1
                        if paren_depth == 0:
                            header_done = True
                            break
                # Check each param: if its name appears as a token on this line, record it.
                for pname in proc.params:
                    pcf = pname.casefold()
                    if pcf not in param_lines:
                        # Use word-boundary search to avoid false matches.
                        if re.search(r"\b" + re.escape(pname) + r"\b", sl, re.IGNORECASE):
                            param_lines[pcf] = scan_idx
                scan_idx += 1

            for pname in proc.params:
                pcf = pname.casefold()
                if pcf not in documented_cf:
                    # This parameter has no description.
                    param_line_idx = param_lines.get(pcf, proc.start_idx)
                    pl = lines[param_line_idx]
                    # Find column of param name.
                    m = re.search(r"\b" + re.escape(pname) + r"\b", pl, re.IGNORECASE)
                    col = m.start() if m else 0
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=param_line_idx + 1,
                            character=col,
                            end_line=param_line_idx + 1,
                            end_character=col + len(pname),
                            severity=Severity.WARNING,
                            code="BSL215",
                            message=(
                                f"Отсутствует описание параметра «{pname}» метода "
                                f"«{proc.name}» в комментарии"
                            ),
                        )
                    )

            # Extra documented params not in signature → flag at method name.
            extra = [v for k, v in documented_cf.items() if k not in actual_params_cf]
            if extra:
                header_line = lines[proc.start_idx]
                try:
                    col = header_line.index(proc.name)
                except ValueError:
                    col = 0
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=col,
                        end_line=proc.start_idx + 1,
                        end_character=col + len(proc.name),
                        severity=Severity.WARNING,
                        code="BSL215",
                        message=(
                            f"Параметры {', '.join(extra)!r} описаны в комментарии, "
                            f"но отсутствуют в сигнатуре «{proc.name}»"
                        ),
                    )
                )

        return diags

    # ------------------------------------------------------------------
    # BSL233 — PublicMethodsDescription
    # ------------------------------------------------------------------

    _RE_BSL233_API_REGION = re.compile(
        r"^\s*#(?:Область|Region)\s+(ПрограммныйИнтерфейс|Public)\s*$",
        re.IGNORECASE,
    )
    _RE_BSL233_REGION_START = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
    _RE_BSL233_REGION_END = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)

    def _rule_bsl233_public_methods_description(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Export methods inside #Область ПрограммныйИнтерфейс must have a description comment."""
        diags: list[Diagnostic] = []

        # Build map: proc.start_idx → root region name (the outermost #Область).
        region_stack: list[str] = []
        root_region_at: dict[int, str] = {}  # line_idx → root region

        for idx, line in enumerate(lines):
            if self._RE_BSL233_REGION_END.match(line):
                if region_stack:
                    region_stack.pop()
            elif self._RE_BSL233_REGION_START.match(line):
                m = re.match(r"^\s*#(?:Область|Region)\s+(\S+)", line, re.IGNORECASE)
                region_name = m.group(1) if m else ""
                region_stack.append(region_name)
            # Record root region for this line.
            if region_stack:
                root_region_at[idx] = region_stack[0]

        for proc in procs:
            if not proc.is_export:
                continue
            root_region = root_region_at.get(proc.start_idx, "")
            if not self._RE_BSL233_API_REGION.match(
                f"#Область {root_region}" if root_region else ""
            ):
                continue

            # Walk backward to check for a comment block.
            block_end = proc.start_idx - 1
            while block_end >= 0 and (
                lines[block_end].strip() == "" or _RE_COMPILER_DIRECTIVE.match(lines[block_end])
            ):
                block_end -= 1

            has_description = block_end >= 0 and _RE_BSL215_COMMENT_LINE.match(lines[block_end])
            # Skip section separators (////...) — not real descriptions.
            if has_description:
                blk_s = block_end
                while blk_s > 0 and _RE_BSL215_COMMENT_LINE.match(lines[blk_s - 1]):
                    blk_s -= 1
                block = lines[blk_s : block_end + 1]
                if any(re.match(r"^\s*/{10,}\s*$", cl) for cl in block):
                    has_description = False

            if not has_description:
                header_line = lines[proc.start_idx]
                try:
                    col = header_line.index(proc.name)
                except ValueError:
                    col = 0
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=col,
                        end_line=proc.start_idx + 1,
                        end_character=col + len(proc.name),
                        severity=Severity.INFORMATION,
                        code="BSL233",
                        message=(
                            f"Экспортный метод «{proc.name}» в публичном API "
                            "должен иметь описание в комментарии"
                        ),
                    )
                )

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
                # BSLLS attaches this diagnostic to the closing «КонецЕсли» line
                # at the statement indentation, not to the nested token span.
                endif_idx = j - 1
                if endif_idx >= 0 and endif_idx < len(lines):
                    el = lines[endif_idx]
                    char = len(el) - len(el.lstrip())
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=endif_idx + 1,
                            character=char,
                            end_line=endif_idx + 1,
                            end_character=len(el),
                            severity=Severity.WARNING,
                            code="BSL199",
                            message=(
                                "Цепочка «Если/ИначеЕсли» не завершается веткой «Иначе» — "
                                "добавьте обработку неожиданных значений"
                            ),
                        )
                    )
            # Advance by 1 (not to j) so nested Если blocks are also examined.
            i += 1
        return diags

    # ------------------------------------------------------------------
    # BSL200 — IncorrectLineBreak
    # ------------------------------------------------------------------

    def _rule_bsl200_incorrect_line_break(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """
        Mirror BSLLS IncorrectLineBreak as a cheap line-based pass.

        Flags:
        - lines starting with ``)``, ``;``, ``, value`` or ``);``
        - lines ending with ``И/ИЛИ/AND/OR/+/-/*//%``

        Skips:
        - matches inside string literals
        - matches inside comments
        - the line right before the first query text line
        """
        diags: list[Diagnostic] = []
        str_states = _build_line_string_states(lines)
        query_prev_lines = _bsl200_query_first_prev_lines(lines)

        for idx, line in enumerate(lines):
            if idx in query_prev_lines:
                continue

            in_str_start = str_states[idx]
            comment_start = _comment_start_outside_double_quotes(line, in_str_start)

            start_match = _BSL200_INCORRECT_START.search(line)
            if start_match:
                start = start_match.start(1)
                end = start_match.end(1)
                in_comment = comment_start is not None and end >= comment_start
                in_string = _span_is_inside_double_quoted_string(
                    line, start, end, in_str_at_start=in_str_start
                )
                if not in_comment and not in_string:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=start,
                            end_line=idx + 1,
                            end_character=end,
                            severity=Severity.INFORMATION,
                            code="BSL200",
                            message="Некорректный перенос строки",
                        )
                    )

            end_match = _BSL200_INCORRECT_END.search(line)
            if not end_match:
                continue
            start = end_match.start(1)
            end = end_match.end(1)
            in_comment = comment_start is not None and end >= comment_start
            in_string = _span_is_inside_double_quoted_string(
                line, start, end, in_str_at_start=in_str_start
            )
            if in_comment or in_string:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=start,
                    end_line=idx + 1,
                    end_character=end,
                    severity=Severity.INFORMATION,
                    code="BSL200",
                    message="Некорректный перенос строки",
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL216 — MissingSpace
    # ------------------------------------------------------------------

    def _rule_bsl216_missing_space(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Detect missing spaces around assignment and comparison operators."""
        diags: list[Diagnostic] = []
        # Build cross-line string state for multi-line string handling.
        str_states = _build_line_string_states(lines)

        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            in_str_start = str_states[idx]
            clean = _mask_double_quoted_strings_preserve_len(line) if not in_str_start else line
            comment_pos = _comment_start_outside_double_quotes(line, in_str_start)
            if comment_pos is not None:
                clean = clean[:comment_pos]
            # Skip = check on procedure/function headers — default parameter values
            # (Param = Default) use = without spaces by 1C convention; BSLLS skips these.
            m = (
                None
                if _RE_BSL216_PROC_HEADER.match(clean)
                else _RE_BSL216_ASSIGN_NOSPACE.search(clean)
            )
            if m:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=("Слева и справа от '=' не хватает пробела"),
                    )
                )
            # Arithmetic operators: +, -, *, /
            for col in _arithmetic_missing_space_cols_in_line(line, in_str_start):
                op = line[col]
                left_missing = col > 0 and line[col - 1] not in " \t"
                right_missing = col + 1 < len(line) and line[col + 1] not in " \t"
                if left_missing and right_missing:
                    msg = f"Слева и справа от '{op}' не хватает пробела"
                elif left_missing:
                    msg = f"Слева от '{op}' не хватает пробела"
                else:
                    msg = f"Справа от '{op}' не хватает пробела"
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=col,
                        end_line=idx + 1,
                        end_character=col + 1,
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=msg,
                    )
                )
                continue
            comma_cols = _comma_missing_space_after_cols_in_line(line.split("//", 1)[0])
            if comma_cols:
                for comma_col in comma_cols:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=comma_col,
                            end_line=idx + 1,
                            end_character=comma_col + 1,
                            severity=Severity.INFORMATION,
                            code="BSL216",
                            message=("Справа от ',' не хватает пробела"),
                        )
                    )
                continue
            m_semicolon = _RE_BSL216_SEMICOLON_NOSPACE.search(clean)
            if m_semicolon:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m_semicolon.start(),
                        end_line=idx + 1,
                        end_character=m_semicolon.end(),
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=("Справа от ';' не хватает пробела"),
                    )
                )
                continue
            for m_kw in _RE_BSL216_LEFT_RIGHT_KEYWORDS.finditer(clean):
                start = m_kw.start(1)
                end = m_kw.end(1)
                left_missing = start > 0 and clean[start - 1] not in " \t"
                right_missing = end < len(clean) and clean[end] not in " \t"
                if not left_missing and not right_missing:
                    continue
                kw = line[start:end]
                if left_missing and right_missing:
                    msg = f"Слева и справа от '{kw}' не хватает пробела"
                elif left_missing:
                    msg = f"Слева от '{kw}' не хватает пробела"
                else:
                    msg = f"Справа от '{kw}' не хватает пробела"
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=start,
                        end_line=idx + 1,
                        end_character=end,
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=msg,
                    )
                )
            for m_kw in _RE_BSL216_LEFT_KEYWORDS.finditer(clean):
                start = m_kw.start(1)
                end = m_kw.end(1)
                if start <= 0 or clean[start - 1] in " \t":
                    continue
                kw = line[start:end]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=start,
                        end_line=idx + 1,
                        end_character=end,
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=(f"Слева от '{kw}' не хватает пробела"),
                    )
                )
            for m_kw in _RE_BSL216_RIGHT_KEYWORDS.finditer(clean):
                start = m_kw.start(1)
                end = m_kw.end(1)
                if end >= len(clean) or clean[end] in " \t":
                    continue
                kw = line[start:end]
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=start,
                        end_line=idx + 1,
                        end_character=end,
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=(f"Справа от '{kw}' не хватает пробела"),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL254 — TransferringParametersBetweenClientAndServer
    # ------------------------------------------------------------------

    def _rule_bsl254_transferring_parameters(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        BSLLS: параметры без ``Знач`` только у серверных методов, которые
        реально вызываются из ``&НаКлиенте`` прямым вызовом.
        """
        if self._symbol_index is None:
            return []

        diags: list[Diagnostic] = []
        file_lines_cache: dict[str, list[str]] = {path: lines}
        proc_cache: dict[str, list[_ProcInfo]] = {path: procs}
        for proc in procs:
            if _procedure_compiler_execution_context(lines, proc) != "server":
                continue
            if not proc.params:
                continue
            missing_val = [
                p
                for p in proc.params
                if p and p.casefold() not in {n.casefold() for n in proc.val_params}
            ]
            if not missing_val:
                continue
            callers = getattr(self._symbol_index, "find_callers", lambda *_args, **_kwargs: [])(
                proc.name,
                limit=200,
            )
            client_callers = [
                row
                for row in callers
                if _caller_is_client_method(
                    str(row.get("caller_file") or ""),
                    row.get("caller_name"),
                    int(row.get("caller_line") or 0),
                    current_path=path,
                    current_lines=lines,
                    current_procs=procs,
                    file_lines_cache=file_lines_cache,
                    proc_cache=proc_cache,
                )
            ]
            if not client_callers:
                continue
            header_line = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
            assigned = _proc_assigned_param_names(lines, proc)
            for param_name in missing_val:
                if param_name.casefold() in assigned:
                    continue
                span = _proc_param_name_span(header_line, param_name)
                if span is None:
                    c0 = proc.header_col
                    c1 = len(header_line.rstrip())
                else:
                    c0, c1 = span
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.WARNING,
                        code="BSL254",
                        message=(
                            f'Установите модификатор "Знач" для параметра {param_name} '
                            f"метода {proc.name}"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL255 — TryNumber
    # ------------------------------------------------------------------

    def _rule_bsl255_try_number(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                    diags.append(
                        Diagnostic(
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
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL183 — ExecuteExternalCode
    # ------------------------------------------------------------------

    def _rule_bsl183_execute_external_code(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                    diags.append(
                        Diagnostic(
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
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL208 — LatinAndCyrillicSymbolInWord
    # BSL256 — Typo (BSLLS-style: pyspellchecker + pymorphy3, bundled BSLLS exceptions)
    # ------------------------------------------------------------------

    def _rule_bsl208_bsl256_latin_cyrillic_and_typo(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        """
        Mixed Latin/Cyrillic identifiers for **LatinAndCyrillicSymbolInWord** (BSL208).

        Spell-check **Typo** is implemented in :meth:`_rule_bsl256_bslls_typo_spellcheck`
        (Python-only engine; see :mod:`onec_hbk_bsl.analysis.bslls_typo`).
        """
        diags: list[Diagnostic] = []
        _re_word = re.compile(r"\b[a-zA-ZА-ЯЁа-яё_][a-zA-ZА-ЯЁа-яё0-9_]*\b", re.UNICODE)
        _re_has_latin = re.compile(r"[a-zA-Z]")
        _re_has_cyrillic = re.compile(r"[А-ЯЁа-яё]")
        _re_comment = re.compile(r"^\s*//")
        # Emit at most once per unique identifier per file (BSL LS behaviour)
        seen_bsl208: set[str] = set()

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
                # BSLLS allowTrailingPartsInAnotherLanguage=true: skip words where
                # Latin/Cyrillic appears only as a trailing or leading block (no interleaving).
                if len(word) >= 4 and _RE_BSL208_TRAILING_LANG.match(word):
                    continue
                if not (_re_has_latin.search(word) and _re_has_cyrillic.search(word)):
                    continue
                if self._rule_enabled("BSL208") and word not in seen_bsl208:
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

    def _rule_bsl256_bslls_typo_spellcheck(self, path: str, tree: Any) -> list[Diagnostic]:
        """BSLLS-style Typo: bundled ``TypoDiagnostic_ru.properties`` + Python spell/morphology."""
        if not self._rule_enabled("BSL256"):
            return []
        root = getattr(tree, "root_node", None)
        if root is None or not hasattr(root, "text"):
            return []
        if not isinstance(root.text, (bytes, bytearray)):
            return []
        rows = bslls_typo.spellcheck_typo_diagnostics(path=path, tree=tree)
        return [
            Diagnostic(
                file=d["file"],
                line=d["line"],
                character=d["character"],
                end_line=d["end_line"],
                end_character=d["end_character"],
                severity=Severity.INFORMATION,
                code=d["code"],
                message=d["message"],
            )
            for d in rows
        ]

    # ------------------------------------------------------------------
    # BSL224 — NestedFunctionInParameters
    # ------------------------------------------------------------------

    def _rule_bsl224_nested_function_in_parameters(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """Detect multiline calls with nested calls in argument list."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        allowed_names = {
            "нстр",
            "nstr",
            "предопределенноезначение",
            "predefinedvalue",
        }
        diags: list[Diagnostic] = []

        def call_name_and_args(
            node: Any,
        ) -> tuple[str, Any | None, Any | None, Any | None, Any | None]:
            if getattr(node, "type", None) == "call_expression":
                method_node = _ts_child_of_type(node, "method_call")
                if method_node is not None:
                    name, _, args, _, name_node = call_name_and_args(method_node)
                    return name, name_node, args, method_node, name_node
                return "", None, None, None, None
            ident = _ts_child_of_type(node, "identifier")
            args = _ts_child_of_type(node, "arguments")
            return _ts_node_text(ident), ident, args, node, ident

        def arg_expr_nodes(args: Any) -> list[Any]:
            return [
                child for child in getattr(args, "children", []) or [] if child.type == "expression"
            ]

        def contains_forbidden_nested_call(args: Any) -> bool:
            for child in _ts_walk(args):
                node_type = getattr(child, "type", None)
                if node_type == "call_expression":
                    return True
                if node_type == "method_call":
                    name, _, _, _, _ = call_name_and_args(child)
                    if name.casefold() not in allowed_names:
                        return True
                elif node_type == "new_expression":
                    _, _, nested_args, _, _ = call_name_and_args(child)
                    if nested_args is not None and arg_expr_nodes(nested_args):
                        return True
            return False

        for node in _ts_walk(root):
            node_type = getattr(node, "type", None)
            if node_type not in {"call_expression", "method_call", "new_expression"}:
                continue
            if (
                node_type == "method_call"
                and getattr(getattr(node, "parent", None), "type", None) == "call_expression"
            ):
                continue
            if node.start_point[0] == node.end_point[0]:
                continue

            name, anchor, args, call_node, name_node = call_name_and_args(node)
            if anchor is None or args is None or call_node is None or name_node is None:
                continue

            exprs = arg_expr_nodes(args)
            if not exprs:
                continue
            if not any(expr.start_point[0] != expr.end_point[0] for expr in exprs):
                continue
            if not contains_forbidden_nested_call(args):
                continue

            start_line_idx = anchor.start_point[0]
            end_line_idx = name_node.end_point[0]
            start_line_text = lines[start_line_idx] if start_line_idx < len(lines) else ""
            end_line_text = lines[end_line_idx] if end_line_idx < len(lines) else ""
            exact_start = start_line_text.find(name)
            start_char = (
                exact_start
                if exact_start >= 0
                else utf8_byte_offset_to_lsp_character(start_line_text, anchor.start_point[1])
            )

            diags.append(
                Diagnostic(
                    file=path,
                    line=start_line_idx + 1,
                    character=start_char,
                    end_line=end_line_idx + 1,
                    end_character=start_char + len(name)
                    if start_line_idx == end_line_idx
                    else utf8_byte_offset_to_lsp_character(end_line_text, name_node.end_point[1]),
                    severity=Severity.INFORMATION,
                    code="BSL224",
                    message=f"Вложенный вызов функции в параметрах метода «{name}»",
                )
            )

        return diags

    # ------------------------------------------------------------------
    # BSL218 — MissingTemporaryFileDeletion
    # ------------------------------------------------------------------

    def _rule_bsl218_missing_temporary_file_deletion(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """BSLLS parity: ``ПолучитьИмяВременногоФайла`` / ``GetTempFileName`` without a later delete.

        Matches BSLLS default ``searchDeleteFileMethod`` (global calls only) and scans the
        enclosing ``codeBlock`` subtree; deletion must appear on a later line with the
        same parameter text as the assignment l-value (case-insensitive).
        """
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        line_texts = lines
        diags: list[Diagnostic] = []

        for call in _ts_global_method_calls(root, line_texts):
            if str(call["name"]).casefold() not in _BSL218_GET_TEMP_NAMES:
                continue
            method_node = call["node"]
            assign_anc: Any | None = None
            cur: Any | None = method_node
            while cur is not None:
                if getattr(cur, "type", None) == "assignment_statement":
                    assign_anc = cur
                    break
                cur = getattr(cur, "parent", None)

            span = _ts_method_identifier_span(method_node, line_texts)
            if span is None:
                continue
            line_1, char_1, end_ch = span

            if assign_anc is None:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL218",
                        message=RULE_DESCRIPTIONS_RU["BSL218"],
                    )
                )
                continue

            var_name = _ts_assignment_lvalue_text(assign_anc)
            if not var_name:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL218",
                        message=RULE_DESCRIPTIONS_RU["BSL218"],
                    )
                )
                continue

            raw_parent = getattr(assign_anc, "parent", None)
            stmt_parent = _ts_bsl218_skip_error_ancestor(raw_parent)
            if stmt_parent is None:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL218",
                        message=RULE_DESCRIPTIONS_RU["BSL218"],
                    )
                )
                continue

            roots = _ts_bsl218_code_block_roots(stmt_parent)
            if not roots:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL218",
                        message=RULE_DESCRIPTIONS_RU["BSL218"],
                    )
                )
                continue

            if not _ts_bsl218_block_has_deletion(roots, line_texts, line_1, var_name):
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_1,
                        character=char_1,
                        end_line=line_1,
                        end_character=end_ch,
                        severity=Severity.WARNING,
                        code="BSL218",
                        message=RULE_DESCRIPTIONS_RU["BSL218"],
                    )
                )

        return diags

    # ------------------------------------------------------------------
    # BSL202 / BSL205 / BSL223 / BSL243 / BSL249 — lightweight call pool
    # ------------------------------------------------------------------

    def _rule_bsl202_205_223_243_249_light_call_pool(
        self, path: str, lines: list[str], tree: Any, enabled: tuple[str, ...]
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        enabled_set = set(enabled)
        diags: list[Diagnostic] = []

        def placeholder_indexes(template: str) -> set[int]:
            out: set[int] = set()
            i = 0
            while i < len(template):
                if template[i] != "%":
                    i += 1
                    continue
                if i + 1 < len(template) and template[i + 1] == "%":
                    i += 2
                    continue
                if i + 1 < len(template) and template[i + 1] == "(":
                    j = i + 2
                    digits: list[str] = []
                    while j < len(template) and template[j].isdigit():
                        digits.append(template[j])
                        j += 1
                    if digits and j < len(template) and template[j] == ")":
                        out.add(int("".join(digits)))
                        i = j + 1
                        continue
                j = i + 1
                digits = []
                while j < len(template) and template[j].isdigit():
                    digits.append(template[j])
                    j += 1
                if digits:
                    out.add(int("".join(digits)))
                    i = j
                    continue
                i += 1
            return out

        if {"BSL202", "BSL205", "BSL223"} & enabled_set:
            line_texts = lines
            for node in _ts_walk(root):
                node_type = getattr(node, "type", None)

                if "BSL223" in enabled_set and node_type == "new_expression":
                    type_node = _ts_child_of_type(node, "identifier")
                    if (
                        type_node is not None
                        and _ts_node_text(type_node).casefold() in _BSL223_STRUCTURE_NAMES
                    ):
                        args = _ts_method_call_arg_exprs(node)
                        if len(args) > 1:
                            nested = False
                            for expr in args[1:]:
                                for child in _ts_walk(expr):
                                    if getattr(child, "type", None) != "new_expression":
                                        continue
                                    nested_args = _ts_method_call_arg_exprs(child)
                                    if len(nested_args) > 1:
                                        nested = True
                                        break
                                if nested:
                                    break
                            if nested:
                                line_idx = node.start_point[0]
                                line_text = (
                                    line_texts[line_idx] if line_idx < len(line_texts) else ""
                                )
                                start_char = utf8_byte_offset_to_lsp_character(
                                    line_text, node.start_point[1]
                                )
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=line_idx + 1,
                                        character=start_char,
                                        end_line=line_idx + 1,
                                        end_character=min(
                                            len(line_text),
                                            start_char + len(_ts_node_text(type_node)),
                                        ),
                                        severity=Severity.INFORMATION,
                                        code="BSL223",
                                        message=(
                                            "Избегайте вложенных конструкторов в объявлении структуры"
                                        ),
                                    )
                                )

                if node_type != "method_call":
                    continue
                ident = _ts_child_of_type(node, "identifier")
                if ident is None:
                    continue
                name_cf = _ts_node_text(ident).casefold()
                span = _ts_method_identifier_span(node, line_texts)
                if span is None:
                    continue
                line_1, char_1, end_char = span

                if "BSL202" in enabled_set and name_cf in {"стршаблон", "strtemplate"}:
                    args = _ts_method_call_arg_exprs(node)
                    if args:
                        first = _ts_node_text(args[0]).strip()
                        if len(first) >= 2 and first[0] == '"' and first[-1] == '"':
                            template = first[1:-1].replace('""', '"')
                            indexes = placeholder_indexes(template)
                            expected = max(indexes) if indexes else 0
                            actual = max(0, len(args) - 1)
                            if expected != actual:
                                diags.append(
                                    Diagnostic(
                                        file=path,
                                        line=line_1,
                                        character=char_1,
                                        end_line=line_1,
                                        end_character=end_char,
                                        severity=Severity.ERROR,
                                        code="BSL202",
                                        message=(
                                            "Количество параметров СтрШаблон()/StrTemplate() "
                                            "не соответствует шаблону"
                                        ),
                                    )
                                )

                if "BSL205" in enabled_set and name_cf in {"рольдоступна", "isinrole"}:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_1,
                            character=char_1,
                            end_line=line_1,
                            end_character=end_char,
                            severity=Severity.WARNING,
                            code="BSL205",
                            message=(
                                "Избегайте использования РольДоступна()/IsInRole(), "
                                "проверяйте права через разрешения"
                            ),
                        )
                    )

        if {"BSL243", "BSL249"} & enabled_set:
            for idx, raw_line in enumerate(lines):
                if _RE_LINE_COMMENT.match(raw_line):
                    continue
                line = _strip_inline_comment_preserve_strings(raw_line)
                if "BSL243" in enabled_set:
                    for m in re.finditer(
                        r"\b(?P<obj>\w+)\s*\.\s*(?:Вставить|Insert|Добавить|Add)\s*\((?P<args>[^)]*)\)",
                        line,
                        re.IGNORECASE,
                    ):
                        obj = m.group("obj").casefold()
                        parts = [part.strip() for part in _split_top_level_args(m.group("args"))]
                        relevant = [part for part in parts if part]
                        if any(part.casefold() == obj for part in relevant):
                            start = m.start("obj")
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=idx + 1,
                                    character=start,
                                    end_line=idx + 1,
                                    end_character=start + len(m.group("obj")),
                                    severity=Severity.ERROR,
                                    code="BSL243",
                                    message="Нельзя вставлять объект в самого себя",
                                )
                            )
                if "BSL249" in enabled_set:
                    for m in re.finditer(r"\b(?:Новый|New)\s+(?P<name>\w+)\b", line, re.IGNORECASE):
                        if m.group("name").casefold() not in _BSL249_STYLE_CONSTRUCTOR_NAMES:
                            continue
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=m.start("name"),
                                end_line=idx + 1,
                                end_character=m.end("name"),
                                severity=Severity.INFORMATION,
                                code="BSL249",
                                message=(
                                    "Используйте встроенные элементы стиля вместо явного конструктора"
                                ),
                            )
                        )

        return diags

    # ------------------------------------------------------------------
    # BSL221 / BSL222 / BSL239 / BSL271 / BSL276 — lightweight mixed pool
    # ------------------------------------------------------------------

    def _rule_bsl221_222_239_271_276_light_pool(
        self,
        path: str,
        lines: list[str],
        tree: Any,
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []

        if {"BSL221", "BSL222"} & enabled_set:
            for idx, raw_line in enumerate(lines):
                if _RE_LINE_COMMENT.match(raw_line):
                    continue
                line = _strip_inline_comment_preserve_strings(raw_line)
                for match in _RE_BSL221_NSTR.finditer(line):
                    langs = {
                        m.group("lang").casefold()
                        for m in _RE_BSL221_LANG.finditer(match.group("body"))
                    }
                    missing = self._declared_languages - langs
                    if not missing:
                        continue
                    code = (
                        "BSL222"
                        if re.search(r"\b(?:СтрШаблон|StrTemplate)\s*\(", line, re.IGNORECASE)
                        else "BSL221"
                    )
                    if code not in enabled_set:
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=match.start(),
                            end_line=idx + 1,
                            end_character=match.end(),
                            severity=Severity.WARNING if code == "BSL222" else Severity.INFORMATION,
                            code=code,
                            message=(
                                "НСтр() не содержит все объявленные языки"
                                if code == "BSL221"
                                else "Не используйте неполную НСтр() внутри СтрШаблон()/StrTemplate()"
                            ),
                        )
                    )

        if "BSL239" in enabled_set and self._reserved_parameter_names_re is not None:
            for proc in procs:
                line_text = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                for param in proc.params:
                    if not self._reserved_parameter_names_re.fullmatch(param):
                        continue
                    col = line_text.find(param)
                    if col < 0:
                        col = proc.header_col
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=col,
                            end_line=proc.start_idx + 1,
                            end_character=col + len(param),
                            severity=Severity.WARNING,
                            code="BSL239",
                            message=f'Имя параметра "{param}" входит в список зарезервированных',
                        )
                    )

        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return diags

        line_texts = lines
        if {"BSL271", "BSL276"} & enabled_set:
            for node in _ts_walk(root):
                node_type = getattr(node, "type", None)
                if "BSL271" in enabled_set and node_type == "new_expression":
                    type_node = _ts_child_of_type(node, "identifier")
                    if type_node is None:
                        continue
                    type_name = _ts_node_text(type_node)
                    if not _RE_BSL271_UNIX_UNAVAILABLE_NEW.search(f"Новый {type_name}"):
                        continue
                    guarded = False
                    cur = getattr(node, "parent", None)
                    while cur is not None:
                        if getattr(cur, "type", None) in {
                            "if_statement",
                            "elseif_clause",
                        } and _RE_BSL271_PLATFORM_GUARD.search(_ts_node_text(cur)):
                            guarded = True
                            break
                        cur = getattr(cur, "parent", None)
                    if guarded:
                        continue
                    line_idx = node.start_point[0]
                    line_text = line_texts[line_idx] if line_idx < len(line_texts) else ""
                    start_char = utf8_byte_offset_to_lsp_character(line_text, node.start_point[1])
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_idx + 1,
                            character=start_char,
                            end_line=line_idx + 1,
                            end_character=min(len(line_text), start_char + len(type_name)),
                            severity=Severity.ERROR,
                            code="BSL271",
                            message=f'Объект "{type_name}" недоступен на Linux/Unix без платформенной проверки',
                        )
                    )

                if "BSL276" in enabled_set and node_type == "method_call":
                    ident = _ts_child_of_type(node, "identifier")
                    if ident is None:
                        continue
                    name = _ts_node_text(ident)
                    if name.casefold() not in {"продолжитьвызов", "proceedwithcall"}:
                        continue
                    line_1, char_1, end_char = _ts_method_identifier_span(node, line_texts) or (
                        0,
                        0,
                        0,
                    )
                    proc = _proc_containing_line(procs, max(0, line_1 - 1))
                    if proc is not None:
                        annotation_lines = lines[max(0, proc.start_idx - 3) : proc.start_idx + 1]
                        if any(
                            _RE_BSL276_AROUND_ANNOTATION.match(annotation_line)
                            for annotation_line in annotation_lines
                        ):
                            continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_1,
                            character=char_1,
                            end_line=line_1,
                            end_character=end_char,
                            severity=Severity.ERROR,
                            code="BSL276",
                            message="ПродолжитьВызов()/ProceedWithCall() допустим только в методах расширения с аннотацией Вместо",
                        )
                    )

        return diags

    # ------------------------------------------------------------------
    # BSL229 / BSL275 / BSL278 — local XML-backed pool
    # ------------------------------------------------------------------

    def _rule_bsl229_275_278_local_xml_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        low = path.replace("\\", "/").lower()
        file_path = Path(path)

        def _line1_span() -> tuple[int, int]:
            if lines:
                return 0, max(len(lines[0].rstrip()), 1)
            return 0, 1

        def _add_line1(code: str, message: str) -> None:
            c0, c1 = _line1_span()
            severity_name = str(RULE_METADATA.get(code, {}).get("severity", "WARNING")).upper()
            severity = getattr(Severity, severity_name, Severity.WARNING)
            diags.append(
                Diagnostic(
                    file=path,
                    line=1,
                    character=c0,
                    end_line=1,
                    end_character=c1,
                    severity=severity,
                    code=code,
                    message=message,
                )
            )

        def _find_config_root(start: Path) -> Path | None:
            for parent in (start.parent, *start.parents):
                if (parent / "Configuration.xml").exists():
                    return parent
            return None

        def _xml_bool_tag_local(xml_text: str, tag: str) -> bool | None:
            match = re.search(
                _RE_XML_BOOL_SIMPLE.format(tag=re.escape(tag)),
                xml_text,
                re.IGNORECASE,
            )
            if match is None:
                return None
            return match.group(1).lower() == "true"

        def _proc_by_name(name: str) -> _ProcInfo | None:
            target = name.casefold()
            for proc in procs:
                if proc.name.casefold() == target:
                    return proc
            return None

        if "BSL229" in enabled_set and low.endswith("/ext/sessionmodule.bsl"):
            config_root = _find_config_root(file_path)
            if config_root is not None:
                try:
                    config_text = (config_root / "Configuration.xml").read_text(
                        encoding="utf-8-sig",
                        errors="replace",
                    )
                except OSError:
                    config_text = ""
                if config_text:
                    managed_in_ordinary = _xml_bool_tag_local(
                        config_text,
                        "UseManagedFormInOrdinaryApplication",
                    )
                    ordinary_in_managed = _xml_bool_tag_local(
                        config_text,
                        "UseOrdinaryFormInManagedApplication",
                    )
                    if managed_in_ordinary is False:
                        _add_line1(
                            "BSL229",
                            "Конфигурация не поддерживает использование управляемых форм в обычном приложении",
                        )
                    if ordinary_in_managed is True:
                        _add_line1(
                            "BSL229",
                            "Конфигурация использует обычные формы в режиме управляемого приложения",
                        )

        if "BSL275" in enabled_set and low.endswith("/ext/module.bsl") and "/httpservices/" in low:
            service_dir = file_path.parent.parent
            service_xml = service_dir.parent / f"{service_dir.name}.xml"
            try:
                xml_text = service_xml.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                xml_text = ""
            for handler_match in _RE_BSL275_HANDLER.finditer(xml_text):
                handler_name = handler_match.group(1).strip()
                if not handler_name:
                    _add_line1("BSL275", "Не указан обработчик метода HTTP-сервиса")
                    continue
                proc = _proc_by_name(handler_name)
                if proc is None:
                    _add_line1("BSL275", f"Не найден обработчик HTTP-сервиса {handler_name}")
                    continue
                if len(proc.params) != 1:
                    start_char, end_char = _proc_name_span(lines, proc)
                    severity_name = str(
                        RULE_METADATA.get("BSL275", {}).get("severity", "ERROR")
                    ).upper()
                    severity = getattr(Severity, severity_name, Severity.ERROR)
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=severity,
                            code="BSL275",
                            message=(
                                f"Обработчик HTTP-сервиса {handler_name} должен принимать ровно один параметр"
                            ),
                        )
                    )

        if "BSL278" in enabled_set and low.endswith("/ext/module.bsl") and "/webservices/" in low:
            service_dir = file_path.parent.parent
            service_xml = service_dir.parent / f"{service_dir.name}.xml"
            try:
                xml_text = service_xml.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                xml_text = ""
            for proc_match in _RE_BSL278_PROCNAME.finditer(xml_text):
                handler_name = proc_match.group(1).strip()
                if not handler_name:
                    _add_line1("BSL278", "Не указан обработчик операции веб-сервиса")
                    continue
                if _proc_by_name(handler_name) is None:
                    _add_line1("BSL278", f"Не найден обработчик веб-сервиса {handler_name}")

        return diags

    def _rule_bsl169_170_181_182_196_260_light_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        is_form_or_command = path_is_likely_form_module_bsl(path) or _path_is_command_module_bsl(
            path
        )
        collision_names = {
            "проверитьбит",
            "проверитьпобитовоймаске",
            "установитьбит",
            "побитовоеи",
            "побитовоеили",
            "побитовоене",
            "побитовоеине",
            "побитовоеисключительноеили",
            "побитовыйсдвигвлево",
            "побитовыйсдвигвправо",
            "checkbit",
            "checkbybitmask",
            "setbit",
            "bitwiseand",
            "bitwiseor",
            "bitwisenot",
            "bitwiseandnot",
            "bitwisexor",
            "bitwiseshiftleft",
            "bitwiseshiftright",
        }

        for proc in procs:
            annotation_lines: list[tuple[int, str]] = []
            j = proc.start_idx - 1
            while j >= 0:
                line = lines[j]
                if not line.strip() or _RE_LINE_COMMENT.match(line):
                    j -= 1
                    continue
                if line.lstrip().startswith("&"):
                    annotation_lines.append((j, line))
                    j -= 1
                    continue
                break
            if "BSL169" in enabled_set and is_form_or_command and not annotation_lines:
                c0, c1 = _proc_name_span(lines, proc)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.WARNING,
                        code="BSL169",
                        message=f"Для метода {proc.name} потеряна директива компиляции",
                    )
                )
            if "BSL170" in enabled_set and not is_form_or_command:
                for ann_idx, ann_line in annotation_lines:
                    col = ann_line.find("&")
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=ann_idx + 1,
                            character=max(col, 0),
                            end_line=ann_idx + 1,
                            end_character=max(col, 0) + max(len(ann_line.strip()), 1),
                            severity=Severity.WARNING,
                            code="BSL170",
                            message="Директива компиляции в этом модуле избыточна",
                        )
                    )
            if "BSL182" in enabled_set:
                hits: list[tuple[int, int]] = []
                for idx in range(proc.start_idx, min(proc.end_idx + 1, len(lines))):
                    line = _strip_inline_comment_preserve_strings(lines[idx])
                    if re.search(r"\b(?:АвтоТестПроверка|AutoTestCheck)\b", line, re.IGNORECASE):
                        col = re.search(
                            r"\b(?:АвтоТестПроверка|AutoTestCheck)\b",
                            line,
                            re.IGNORECASE,
                        )
                        if col is not None:
                            hits.append((idx, col.start()))
                for idx, col in hits[1:]:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=col,
                            end_line=idx + 1,
                            end_character=col + len("АвтоТестПроверка"),
                            severity=Severity.WARNING,
                            code="BSL182",
                            message="Избыточная повторная проверка АвтоТестПроверка",
                        )
                    )
            if "BSL196" in enabled_set and proc.name.casefold() in collision_names:
                c0, c1 = _proc_name_span(lines, proc)
                diags.append(
                    Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=c0,
                        end_line=proc.start_idx + 1,
                        end_character=c1,
                        severity=Severity.ERROR,
                        code="BSL196",
                        message=f"Имя метода {proc.name} конфликтует с глобальным контекстом 8.3.12",
                    )
                )
            if "BSL181" in enabled_set:
                seen_inserts: set[tuple[str, str, str]] = set()
                for idx in range(proc.start_idx, min(proc.end_idx + 1, len(lines))):
                    line = _strip_inline_comment_preserve_strings(lines[idx])
                    for match in re.finditer(
                        r"\b(?P<target>\w+)\.(?P<method>Добавить|Add|Вставить|Insert)\s*\((?P<arg>[^)]*)\)",
                        line,
                        re.IGNORECASE,
                    ):
                        key = (
                            match.group("target").casefold(),
                            match.group("method").casefold(),
                            re.sub(r"\s+", "", match.group("arg")).casefold(),
                        )
                        if key in seen_inserts:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=idx + 1,
                                    character=match.start("target"),
                                    end_line=idx + 1,
                                    end_character=match.end("arg"),
                                    severity=Severity.WARNING,
                                    code="BSL181",
                                    message="Обнаружена дублирующаяся вставка в коллекцию",
                                )
                            )
                        else:
                            seen_inserts.add(key)
        if "BSL260" in enabled_set:
            for idx, raw_line in enumerate(lines):
                line = _strip_inline_comment_preserve_strings(raw_line)
                assign = re.search(
                    r"(?P<var>\w+)\s*=\s*(?P<expr>\w+(?:\.\w+)*\.(?:НайтиПоКоду|FindByCode)\s*\([^)]*\))",
                    line,
                    re.IGNORECASE,
                )
                if assign is None:
                    continue
                var_name = assign.group("var")
                lookahead = "\n".join(lines[idx + 1 : min(len(lines), idx + 4)])
                if re.search(
                    rf"\b(?:ЗначениеЗаполнено|ValueIsFilled)\s*\([^)]*\b{re.escape(var_name)}\b",
                    lookahead,
                    re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(var_name)}\b\s*(?:=|<>)\s*(?:Неопределено|Undefined)",
                    lookahead,
                    re.IGNORECASE,
                ):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=assign.start("expr"),
                        end_line=idx + 1,
                        end_character=assign.end("expr"),
                        severity=Severity.WARNING,
                        code="BSL260",
                        message="Использование НайтиПоКоду() небезопасно без проверки результата",
                    )
                )
        return diags

    def _rule_bsl174_187_236_238_query_metadata_pool(
        self,
        path: str,
        lines: list[str],
        enabled: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        root = _config_root_for_file(path)
        meta_names: set[str] = set()
        if root is not None:
            crawl = _crawl_config_cached(root)
            meta_names = set(crawl["by_name"].keys())

        object_xml = _current_object_xml_path(path)
        if "BSL174" in enabled_set and object_xml is not None:
            xml_text = _read_text_cached(str(object_xml))
            for match in _RE_XML_DIMENSION_BLOCK.finditer(xml_text):
                if match.group(2).lower() == "false":
                    line_text = lines[0] if lines else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=Severity.WARNING,
                            code="BSL174",
                            message=(
                                f"Измерение {match.group(1)} должно запрещать незаполненные значения"
                            ),
                        )
                    )

        if query_blocks is None:
            blocks = (
                list(_iter_query_text_content_lines(start_idx, block_lines))
                for start_idx, block_lines in _iter_query_text_blocks(lines)
            )
        else:
            blocks = (_query_block_content_line_tuples(block) for block in query_blocks)

        for query_lines in blocks:
            if not query_lines:
                continue
            query_text = "\n".join(head for _ln, _base, _content, head, _end in query_lines)
            left_join_aliases: set[str] = set()
            for line_no, content_base, _content, head, _ended in query_lines:
                if "BSL236" in enabled_set:
                    for match in re.finditer(
                        r"\b(?:ИЗ|FROM|СОЕДИНЕНИЕ|JOIN)\s+([A-Za-zА-Яа-яЁё_][\w]*)",
                        head,
                        re.IGNORECASE,
                    ):
                        name = match.group(1)
                        if name.casefold() in {
                            "выбрать",
                            "select",
                            "как",
                            "as",
                            "левое",
                            "правое",
                            "полное",
                            "внутреннее",
                        }:
                            continue
                        if meta_names and name.casefold() not in meta_names:
                            col = content_base + match.start(1)
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=col,
                                    end_line=line_no,
                                    end_character=col + len(name),
                                    severity=Severity.ERROR,
                                    code="BSL236",
                                    message=f"Запрос обращается к несуществующим метаданным {name}",
                                )
                            )
                if "BSL238" in enabled_set:
                    for match in re.finditer(r"\.(?:Ссылка|Ref)\.", head, re.IGNORECASE):
                        col = content_base + match.start()
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=line_no,
                                character=col,
                                end_line=line_no,
                                end_character=col + len(match.group(0)),
                                severity=Severity.INFORMATION,
                                code="BSL238",
                                message="Избыточное использование .Ссылка в запросе",
                            )
                        )
                if "BSL187" in enabled_set:
                    for join_match in re.finditer(
                        r"\b(?:ЛЕВОЕ\s+СОЕДИНЕНИЕ|LEFT\s+JOIN)\b.*?\b(?:КАК|AS)\s+([A-Za-zА-Яа-яЁё_]\w*)",
                        head,
                        re.IGNORECASE,
                    ):
                        left_join_aliases.add(join_match.group(1).casefold())
            if "BSL187" in enabled_set and left_join_aliases:
                has_isnull = re.search(r"\b(?:ЕСТЬNULL|ISNULL)\s*\(", query_text, re.IGNORECASE)
                if not has_isnull:
                    for line_no, content_base, _content, head, _ended in query_lines:
                        for alias in left_join_aliases:
                            match = re.search(rf"\b{re.escape(alias)}\.\w+", head, re.IGNORECASE)
                            if match is None:
                                continue
                            col = content_base + match.start()
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=col,
                                    end_line=line_no,
                                    end_character=col + len(match.group(0)),
                                    severity=Severity.ERROR,
                                    code="BSL187",
                                    message="Поля из внешнего соединения должны использоваться с ЕСТЬNULL/ISNULL",
                                )
                            )
                            break
        return diags

    def _rule_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        root = _config_root_for_file(path)
        line_text = lines[0] if lines else ""
        object_xml = _current_object_xml_path(path)
        crawl = _crawl_config_cached(root) if root is not None else {"objects": [], "by_name": {}}
        module_map = _common_module_file_map(root) if root is not None else {}

        forbidden_names = {
            "catalog",
            "catalogs",
            "document",
            "documents",
            "справочник",
            "справочники",
            "документ",
            "документы",
            "enum",
            "enums",
            "перечисление",
            "перечисления",
            "tasks",
            "задачи",
        }

        if object_xml is not None:
            ctx = _current_module_xml_context(path)
            object_name = ctx.get("object_name", object_xml.stem)
            meta_obj = crawl["by_name"].get(object_name.casefold())
            if "BSL189" in enabled_set:
                if object_name.casefold() in forbidden_names:
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=Severity.ERROR,
                            code="BSL189",
                            message=f"Запрещенное имя объекта метаданных {object_name}",
                        )
                    )
                if meta_obj is not None:
                    for member in meta_obj.members:
                        check_name = member.name.split(".")[-1]
                        if check_name.casefold() in forbidden_names:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=1,
                                    character=0,
                                    end_line=1,
                                    end_character=max(len(line_text.rstrip()), 1),
                                    severity=Severity.ERROR,
                                    code="BSL189",
                                    message=f"Запрещенное имя реквизита или части {check_name}",
                                )
                            )
                            break
            if "BSL211" in enabled_set and len(object_name) > 80:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=Severity.WARNING,
                        code="BSL211",
                        message="Имя объекта метаданных превышает допустимую длину 80",
                    )
                )
            if "BSL241" in enabled_set and meta_obj is not None:
                obj_cf = meta_obj.name.casefold()
                for member in meta_obj.members:
                    raw_name = member.name.split(".")
                    if len(raw_name) == 1 and raw_name[0].casefold() == obj_cf:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=max(len(line_text.rstrip()), 1),
                                severity=Severity.ERROR,
                                code="BSL241",
                                message=f"Имя дочернего объекта совпадает с именем {meta_obj.name}",
                            )
                        )
                        break
                    if len(raw_name) == 2 and raw_name[0].casefold() == raw_name[1].casefold():
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=max(len(line_text.rstrip()), 1),
                                severity=Severity.ERROR,
                                code="BSL241",
                                message=f"Имя реквизита совпадает с именем табличной части {raw_name[0]}",
                            )
                        )
                        break

        if "BSL274" in enabled_set and path_is_likely_form_module_bsl(path):
            form_xml = _current_form_xml_path(path)
            if form_xml is not None:
                form_text = _read_text_cached(str(form_xml))
                for match in _RE_XML_DATAPATH.finditer(form_text):
                    if match.group(1).startswith("~"):
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=1,
                                character=0,
                                end_line=1,
                                end_character=max(len(line_text.rstrip()), 1),
                                severity=Severity.ERROR,
                                code="BSL274",
                                message=f"Путь к данным элемента формы некорректен: {match.group(1)}",
                            )
                        )
                        break

        if (
            "BSL246" in enabled_set
            and path.replace("\\", "/").lower().endswith("/ext/managedapplicationmodule.bsl")
            and root is not None
        ):
            roles_dir = Path(root) / "Roles"
            for xml_file in roles_dir.glob("*.xml"):
                role_name = xml_file.stem
                if role_name in {"FullAccess", "ПолныеПрава"}:
                    continue
                text = _read_text_cached(str(xml_file))
                match = _RE_XML_SET_FOR_NEW_OBJECTS.search(text)
                if match and match.group(1).lower() == "true":
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=1,
                            character=0,
                            end_line=1,
                            end_character=max(len(line_text.rstrip()), 1),
                            severity=Severity.ERROR,
                            code="BSL246",
                            message=f"Роль {role_name} задает права для новых объектов",
                        )
                    )

        if (
            "BSL232" in enabled_set
            and path.replace("\\", "/").lower().endswith("/ext/sessionmodule.bsl")
            and root is not None
        ):
            cfg_root = Path(root)
            protected_found = False
            for xml_file in cfg_root.rglob("*.xml"):
                if xml_file.name in {"Configuration.xml", "ConfigDumpInfo.xml"}:
                    continue
                if _RE_XML_PROTECTED.search(_read_text_cached(str(xml_file))):
                    protected_found = True
                    break
            if protected_found:
                diags.append(
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=max(len(line_text.rstrip()), 1),
                        severity=Severity.WARNING,
                        code="BSL232",
                        message="В конфигурации обнаружены защищенные модули",
                    )
                )

        if "BSL231" in enabled_set and root is not None:
            low = path.replace("\\", "/").lower()
            current_common = ""
            if "/commonmodules/" in low:
                current_common = Path(path).parent.parent.name.casefold()
            current_privileged = bool(
                current_common and module_map.get(current_common, {}).get("privileged")
            )
            for idx, raw_line in enumerate(lines):
                line = _strip_inline_comment_preserve_strings(raw_line)
                for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                    mod_cf = match.group("mod").casefold()
                    if mod_cf == current_common:
                        continue
                    info = module_map.get(mod_cf)
                    if info and info.get("privileged") and not current_privileged:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("mod"),
                                end_line=idx + 1,
                                end_character=match.end("meth"),
                                severity=Severity.WARNING,
                                code="BSL231",
                                message=f"Вызов метода привилегированного модуля {info['name']}",
                            )
                        )

        if (
            ({"BSL213", "BSL214", "BSL242"} & enabled_set)
            and root is not None
            and "/commonmodules/" in path.replace("\\", "/").lower()
        ):
            module_name = Path(path).parent.parent.name
            proc_names = {proc.name.casefold(): proc for proc in procs}
            root_path = Path(root)
            if "BSL213" in enabled_set:
                for idx, raw_line in enumerate(lines):
                    line = _strip_inline_comment_preserve_strings(raw_line)
                    for match in re.finditer(r"\b(?P<mod>\w+)\.(?P<meth>\w+)\s*\(", line):
                        mod_cf = match.group("mod").casefold()
                        info = module_map.get(mod_cf)
                        if info and match.group("meth").casefold() not in info.get(
                            "proc_names", set()
                        ):
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=idx + 1,
                                    character=match.start("mod"),
                                    end_line=idx + 1,
                                    end_character=match.end("meth"),
                                    severity=Severity.ERROR,
                                    code="BSL213",
                                    message=(
                                        f"Метод {match.group('meth')} отсутствует в общем модуле {info['name']}"
                                    ),
                                )
                            )
            if "BSL214" in enabled_set:
                for xml_file in (root_path / "EventSubscriptions").glob("*.xml"):
                    text = _read_text_cached(str(xml_file))
                    for match in _RE_XML_EVENT_HANDLER.finditer(text):
                        handler = (match.group(1) or match.group(2) or "").strip()
                        if not handler.startswith(f"{module_name}."):
                            continue
                        meth = handler.split(".", 1)[1]
                        if meth.casefold() not in proc_names:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=1,
                                    character=0,
                                    end_line=1,
                                    end_character=max(len(line_text.rstrip()), 1),
                                    severity=Severity.ERROR,
                                    code="BSL214",
                                    message=f"Обработчик подписки на событие {handler} не существует",
                                )
                            )
            if "BSL242" in enabled_set:
                handlers_seen: dict[str, str] = {}
                for xml_file in (root_path / "ScheduledJobs").glob("*.xml"):
                    text = _read_text_cached(str(xml_file))
                    for match in _RE_XML_METHOD_NAME.finditer(text):
                        handler = match.group(1).strip()
                        if not handler.startswith(f"CommonModule.{module_name}."):
                            continue
                        meth = handler.split(".")[-1]
                        proc = proc_names.get(meth.casefold())
                        if proc is None:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=1,
                                    character=0,
                                    end_line=1,
                                    end_character=max(len(line_text.rstrip()), 1),
                                    severity=Severity.ERROR,
                                    code="BSL242",
                                    message=f"Обработчик регламентного задания {handler} не найден",
                                )
                            )
                            continue
                        if not proc.is_export:
                            start_char, end_char = _proc_name_span(lines, proc)
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=proc.start_idx + 1,
                                    character=start_char,
                                    end_line=proc.start_idx + 1,
                                    end_character=end_char,
                                    severity=Severity.ERROR,
                                    code="BSL242",
                                    message=f"Обработчик регламентного задания {handler} должен быть экспортным",
                                )
                            )
                        if proc.optional_count > 0 or proc.params:
                            start_char, end_char = _proc_name_span(lines, proc)
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=proc.start_idx + 1,
                                    character=start_char,
                                    end_line=proc.start_idx + 1,
                                    end_character=end_char,
                                    severity=Severity.ERROR,
                                    code="BSL242",
                                    message=f"Обработчик регламентного задания {handler} не должен принимать параметры",
                                )
                            )
                        if handler in handlers_seen and handlers_seen[handler] != xml_file.stem:
                            diags.append(
                                Diagnostic(
                                    file=path,
                                    line=1,
                                    character=0,
                                    end_line=1,
                                    end_character=max(len(line_text.rstrip()), 1),
                                    severity=Severity.ERROR,
                                    code="BSL242",
                                    message=f"Один и тот же обработчик {handler} используется несколькими заданиями",
                                )
                            )
                        handlers_seen[handler] = xml_file.stem
        return diags

    def _rule_bsl244_253_261_runtime_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        server_proc_names = {
            proc.name.casefold()
            for proc in procs
            if _procedure_compiler_execution_context(lines, proc) == "server"
        }

        if "BSL244" in enabled_set and path_is_likely_form_module_bsl(path):
            for idx, raw_line in enumerate(lines):
                line = _strip_inline_comment_preserve_strings(raw_line)
                proc = _proc_containing_line(procs, idx)
                if proc is None:
                    continue
                name_cf = proc.name.casefold()
                is_form_event = name_cf.startswith("при") or name_cf.startswith("on")
                if not is_form_event:
                    continue
                for match in re.finditer(r"\b(?P<call>\w+)\s*\(", line):
                    if match.group("call").casefold() in server_proc_names:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start("call"),
                                end_line=idx + 1,
                                end_character=match.end("call"),
                                severity=Severity.ERROR,
                                code="BSL244",
                                message="Серверный вызов в обработчике события формы",
                            )
                        )

        timeout_types = {
            "httpсоединение": 4,
            "httpconnection": 4,
            "ftpсоединение": 5,
            "ftpconnection": 5,
            "wsопределения": 3,
            "wsdefinitions": 3,
            "wsпрокси": 4,
            "wsproxy": 4,
            "интернетпочтовыйпрофиль": 5,
            "internetmailprofile": 5,
        }
        if "BSL253" in enabled_set:
            for idx, raw_line in enumerate(lines):
                line = _strip_inline_comment_preserve_strings(raw_line)
                match = re.search(
                    r"\b(?:Новый|New)\s+(?P<type>\w+)\s*\((?P<args>.*)\)", line, re.IGNORECASE
                )
                if match is None:
                    continue
                type_cf = match.group("type").casefold()
                need_idx = timeout_types.get(type_cf)
                if need_idx is None:
                    continue
                args = _split_top_level_args(match.group("args"))
                if len(args) > need_idx and args[need_idx].strip():
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=match.start("type"),
                        end_line=idx + 1,
                        end_character=match.end("args") + 1,
                        severity=Severity.ERROR,
                        code="BSL253",
                        message="Внешний ресурс создается без явного таймаута",
                    )
                )

        if "BSL261" in enabled_set:
            for idx, raw_line in enumerate(lines):
                line = _strip_inline_comment_preserve_strings(raw_line)
                if not re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE):
                    continue
                if re.search(
                    r"\b(?:Если|If)\b.*\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE
                ) or re.search(
                    r"\b(?:И|And|Или|Or)\b",
                    line,
                    re.IGNORECASE,
                ):
                    match = re.search(r"\b(?:БезопасныйРежим|SafeMode)\s*\(", line, re.IGNORECASE)
                    if match is not None:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=match.start(),
                                end_line=idx + 1,
                                end_character=match.end(),
                                severity=Severity.ERROR,
                                code="BSL261",
                                message="Небезопасное использование метода безопасного режима",
                            )
                        )
        return diags

    # ------------------------------------------------------------------
    # BSL225 — NumberOfValuesInStructureConstructor
    # ------------------------------------------------------------------

    def _rule_bsl225_number_of_values_in_structure_constructor(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        """BSLLS parity: New Structure/FixedStructure with more than 4 total arguments."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        type_names = {"структура", "structure", "фиксированнаяструктура", "fixedstructure"}
        diags: list[Diagnostic] = []

        for node in _ts_walk(root):
            if getattr(node, "type", None) != "new_expression":
                continue
            type_node = _ts_child_of_type(node, "identifier")
            if type_node is None:
                continue
            type_name = _ts_node_text(type_node).casefold()
            if type_name not in type_names:
                continue
            args = _ts_child_of_type(node, "arguments")
            if args is None:
                continue
            arg_count = len(
                [
                    child
                    for child in getattr(args, "children", []) or []
                    if child.type == "expression"
                ]
            )
            if arg_count <= 4:
                continue

            start_line_idx = node.start_point[0]
            start_line_text = lines[start_line_idx] if start_line_idx < len(lines) else ""
            start_char = utf8_byte_offset_to_lsp_character(start_line_text, node.start_point[1])
            diags.append(
                Diagnostic(
                    file=path,
                    line=start_line_idx + 1,
                    character=start_char,
                    end_line=start_line_idx + 1,
                    end_character=min(
                        len(start_line_text), start_char + len(_ts_node_text(type_node))
                    ),
                    severity=Severity.INFORMATION,
                    code="BSL225",
                    message=(
                        "Сократите количество значений, передаваемых в конструктор "
                        "Структура/Structure"
                    ),
                )
            )

        return diags

    # ------------------------------------------------------------------
    # BSL234 — QueryNestedFieldsByDot
    # ------------------------------------------------------------------

    def _rule_bsl234_query_nested_fields_by_dot(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect chained query fields like ``Alias.Field.SubField``."""
        diags: list[Diagnostic] = []
        chain_re = re.compile(r"(?<![\w.])([A-Za-zА-Яа-я_]\w*(?:\.[A-Za-zА-Яа-я_]\w*){2,})")
        value_re = re.compile(r"(?:ЗНАЧЕНИЕ|VALUE)\s*\(", re.IGNORECASE)

        def _mask_value_calls(text: str) -> str:
            chars = list(text)
            pos = 0
            while True:
                match = value_re.search(text, pos)
                if match is None:
                    break
                depth = 0
                end = match.end()
                while end < len(text):
                    ch = text[end]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        if depth == 0:
                            end += 1
                            break
                        depth -= 1
                    end += 1
                for idx in range(match.start(), min(end, len(chars))):
                    chars[idx] = " "
                pos = end
            return "".join(chars)

        for line_no, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if not stripped.startswith("|"):
                continue
            masked = _mask_value_calls(line)
            for match in chain_re.finditer(masked):
                trailing = masked[match.end(1) :]
                if re.match(r"^\s+(?:КАК|AS)\b", trailing, re.IGNORECASE):
                    continue
                if re.match(r"^\s*\(", trailing):
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_no,
                        character=match.start(1),
                        end_line=line_no,
                        end_character=match.end(1),
                        severity=Severity.WARNING,
                        code="BSL234",
                        message="Обнаружено разыменование ссылочного поля",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL237 — RedundantAccessToObject
    # ------------------------------------------------------------------

    def _rule_bsl237_redundant_access_to_object(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        """Detect redundant access through ЭтотОбъект/ThisObject or module object prefix."""
        low = path.replace("\\", "/").lower()
        supported = (
            low.endswith("/ext/objectmodule.bsl")
            or low.endswith("/ext/recordsetmodule.bsl")
            or low.endswith("/ext/managermodule.bsl")
            or path_is_likely_form_module_bsl(path)
            or low.endswith("/ext/module.bsl")
        )
        if not supported:
            return []

        diags: list[Diagnostic] = []
        patterns = _redundant_access_prefix_patterns(path)
        for line_no, line in enumerate(lines, start=1):
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = _mask_double_quoted_strings_preserve_len(line)
            comment_pos = clean.find("//")
            if comment_pos >= 0:
                clean = clean[:comment_pos]
            for pattern in patterns:
                for match in pattern.finditer(clean):
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line_no,
                            character=match.start(),
                            end_line=line_no,
                            end_character=match.end() - 1,
                            severity=Severity.INFORMATION,
                            code="BSL237",
                            message=(
                                "Избавьтесь от избыточного обращения внутри модуля "
                                "через его имя или псевдоним ЭтотОбъект"
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL245 — ServerSideExportFormMethod
    # ------------------------------------------------------------------

    def _rule_bsl245_server_side_export_form_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Detect export methods in form modules that are not client-only."""
        if not path_is_likely_form_module_bsl(path):
            return []
        diags: list[Diagnostic] = []
        for proc in procs:
            if not proc.is_export:
                continue
            if _procedure_compiler_execution_context(lines, proc) == "client":
                continue
            start_char, end_char = _proc_name_span(lines, proc)
            diags.append(
                Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=start_char,
                    end_line=proc.start_idx + 1,
                    end_character=end_char,
                    severity=Severity.WARNING,
                    code="BSL245",
                    message="Запрещено создавать серверные экспортные методы в форме",
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL230 — PairingBrokenTransaction
    # ------------------------------------------------------------------

    def _rule_bsl230_pairing_broken_transaction(self, path: str, tree: Any) -> list[Diagnostic]:
        """Detect broken Begin/Commit and Begin/Rollback pairing like BSLLS."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        line_texts = _ts_node_text(root).splitlines()
        diags: list[Diagnostic] = []
        begin_names = {"начатьтранзакцию", "begintransaction"}

        pair_specs = (
            (
                {
                    "начатьтранзакцию",
                    "begintransaction",
                    "зафиксироватьтранзакцию",
                    "committransaction",
                },
                {
                    "начатьтранзакцию": "ЗафиксироватьТранзакцию",
                    "begintransaction": "CommitTransaction",
                    "зафиксироватьтранзакцию": "НачатьТранзакцию",
                    "committransaction": "BeginTransaction",
                },
            ),
            (
                {
                    "начатьтранзакцию",
                    "begintransaction",
                    "отменитьтранзакцию",
                    "rollbacktransaction",
                },
                {
                    "начатьтранзакцию": "ОтменитьТранзакцию",
                    "begintransaction": "RollbackTransaction",
                    "отменитьтранзакцию": "НачатьТранзакцию",
                    "rollbacktransaction": "BeginTransaction",
                },
            ),
        )

        proc_nodes = [
            node
            for node in _ts_walk(root)
            if getattr(node, "type", None) in {"procedure_definition", "function_definition"}
        ]

        for proc_node in proc_nodes:
            calls = _ts_global_method_calls(proc_node, line_texts)
            if not calls:
                continue
            for allowed_names, pair_names in pair_specs:
                begin_stack: list[dict[str, Any]] = []
                for call in calls:
                    name_cf = str(call["name"]).casefold()
                    if name_cf not in allowed_names:
                        continue
                    if name_cf in begin_names:
                        begin_stack.append(call)
                    elif begin_stack:
                        begin_stack.pop()
                    else:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=call["line"],
                                character=call["character"],
                                end_line=call["line"],
                                end_character=call["end_character"],
                                severity=Severity.ERROR,
                                code="BSL230",
                                message=(
                                    f'Отсутствует парный вызов "{pair_names[name_cf]}" '
                                    f'для метода "{call["name"]}"'
                                ),
                            )
                        )
                for call in begin_stack:
                    name_cf = str(call["name"]).casefold()
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=call["line"],
                            character=call["character"],
                            end_line=call["line"],
                            end_character=call["end_character"],
                            severity=Severity.ERROR,
                            code="BSL230",
                            message=(
                                f'Отсутствует парный вызов "{pair_names[name_cf]}" '
                                f'для метода "{call["name"]}"'
                            ),
                        )
                    )
        return diags

    # ------------------------------------------------------------------
    # BSL277 — WrongUseOfRollbackTransactionMethod
    # ------------------------------------------------------------------

    def _rule_bsl277_wrong_use_of_rollback_transaction(
        self, path: str, tree: Any
    ) -> list[Diagnostic]:
        """Detect RollbackTransaction/ОтменитьТранзакцию outside except or not first there."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        line_texts = _ts_node_text(root).splitlines()
        rollback_names = {"отменитьтранзакцию", "rollbacktransaction"}
        diags: list[Diagnostic] = []
        rollback_in_except_ids: set[int] = set()

        for node in _ts_walk(root):
            if getattr(node, "type", None) != "try_statement":
                continue
            children = list(getattr(node, "children", []) or [])
            except_idx = next(
                (
                    i
                    for i, child in enumerate(children)
                    if getattr(child, "type", None) == "EXCEPT_KEYWORD"
                ),
                None,
            )
            endtry_idx = next(
                (
                    i
                    for i, child in enumerate(children)
                    if getattr(child, "type", None) == "ENDTRY_KEYWORD"
                ),
                None,
            )
            if except_idx is None:
                continue
            if endtry_idx is None:
                endtry_idx = len(children)
            except_calls: list[dict[str, Any]] = []
            for child in children[except_idx + 1 : endtry_idx]:
                except_calls.extend(_ts_global_method_calls(child, line_texts))
            if not except_calls:
                continue
            rollback_is_first = str(except_calls[0]["name"]).casefold() in rollback_names
            for call in except_calls:
                name_cf = str(call["name"]).casefold()
                if name_cf not in rollback_names:
                    continue
                rollback_in_except_ids.add(id(call["node"]))
                if rollback_is_first:
                    continue
                diags.append(
                    Diagnostic(
                        file=path,
                        line=call["line"],
                        character=call["character"],
                        end_line=call["line"],
                        end_character=call["end_character"],
                        severity=Severity.ERROR,
                        code="BSL277",
                        message=(
                            "Метод ОтменитьТранзакцию() должен быть в попытке и первым "
                            "методом блока исключения"
                        ),
                    )
                )

        for call in _ts_global_method_calls(root, line_texts):
            name_cf = str(call["name"]).casefold()
            if name_cf not in rollback_names:
                continue
            if id(call["node"]) in rollback_in_except_ids:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=call["line"],
                    character=call["character"],
                    end_line=call["line"],
                    end_character=call["end_character"],
                    severity=Severity.ERROR,
                    code="BSL277",
                    message=(
                        "Метод ОтменитьТранзакцию() должен быть в попытке и первым "
                        "методом блока исключения"
                    ),
                )
            )

        return diags

    # ------------------------------------------------------------------
    # BSL262 — UsageWriteLogEvent
    # ------------------------------------------------------------------

    def _rule_bsl262_usage_write_log_event(self, path: str, tree: Any) -> list[Diagnostic]:
        """Detect WriteLogEvent/ЗаписьЖурналаРегистрации misuse inside except blocks."""
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        line_texts = _ts_node_text(root).splitlines()
        diags: list[Diagnostic] = []
        target_names = {"записьжурналарегистрации", "writelogevent"}
        level_root_names = {"уровеньжурналарегистрации", "eventloglevel"}
        error_level_names = {"ошибка", "error"}

        def except_children(try_node: Any) -> list[Any]:
            children = list(getattr(try_node, "children", []) or [])
            except_idx = next(
                (
                    i
                    for i, child in enumerate(children)
                    if getattr(child, "type", None) == "EXCEPT_KEYWORD"
                ),
                None,
            )
            endtry_idx = next(
                (
                    i
                    for i, child in enumerate(children)
                    if getattr(child, "type", None) == "ENDTRY_KEYWORD"
                ),
                None,
            )
            if except_idx is None:
                return []
            if endtry_idx is None:
                endtry_idx = len(children)
            return children[except_idx + 1 : endtry_idx]

        def arg_is_error_level(expr: Any) -> bool:
            text = _ts_node_text(expr).casefold()
            return any(
                root_name in text and level in text
                for root_name in level_root_names
                for level in error_level_names
            )

        for node in _ts_walk(root):
            if getattr(node, "type", None) != "try_statement":
                continue
            for child in except_children(node):
                for call in _ts_global_method_calls(child, line_texts):
                    if str(call["name"]).casefold() not in target_names:
                        continue
                    args = _ts_method_call_arg_exprs(call["node"])
                    if len(args) < 2:
                        continue
                    if arg_is_error_level(args[1]):
                        continue
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=call["line"],
                            character=call["character"],
                            end_line=call["line"],
                            end_character=call["end_character"],
                            severity=Severity.INFORMATION,
                            code="BSL262",
                            message=(
                                'Нужно указывать уровень "Ошибка" при записи в журнал '
                                "регистрации внутри блока Исключение-КонецПопытки"
                            ),
                        )
                    )
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

            # BSLLS RewriteMethodParameter only fires for Знач (by-value) parameters:
            # rewriting a by-value copy is wasteful since the caller won't see the change.
            # Non-Знач params may be intentional output parameters — BSLLS doesn't flag them.
            val_cf = {n.casefold() for n in (getattr(proc, "val_params", None) or [])}
            if not val_cf:
                continue  # no Знач params → nothing to check
            # Optional Знач params (with default values) are often intentionally conditional-set
            # (e.g. "Если НаДату = Неопределено Тогда НаДату = ТекущаяДатаСеанса()") — BSLLS skip.
            opt_cf = {n.casefold() for n in (getattr(proc, "optional_params", None) or [])}
            val_cf -= opt_cf

            # Find Знач params reassigned before use in first non-blank body lines
            for li in range(body_start, min(body_start + 15, proc.end_idx)):
                if li >= len(lines):
                    break
                line = lines[li]
                if _RE_LINE_COMMENT.match(line) or not line.strip():
                    continue
                am = _RE_BSL240_ASSIGN.match(line)
                if am:
                    lhs = am.group(1).casefold()
                    if lhs in val_cf and lhs not in _BSL062_SKIP_STANDARD_COMMAND_PARAMS:
                        # Check the RHS doesn't mention the param itself
                        rhs = line[am.end() :].strip()
                        if lhs not in rhs.casefold():
                            diags.append(
                                Diagnostic(
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
                                )
                            )
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
                    if re.search(r"\b" + re.escape(iter_var) + r"\b", clean, re.IGNORECASE):
                        var_used = True
                        break

                if not var_used and body_lines:
                    diags.append(
                        Diagnostic(
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
                        )
                    )
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
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL265",
                        message=(
                            "Тернарный оператор возвращает Истина/Ложь — замените на само условие"
                        ),
                    )
                )
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
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=Severity.WARNING,
                        code="BSL257",
                        message=(
                            "Унарный «+» перед значением при конкатенации — вероятно опечатка"
                        ),
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL279 — YoLetterUsage
    # ------------------------------------------------------------------

    def _rule_bsl279_yo_letter_usage(self, path: str, lines: list[str]) -> list[Diagnostic]:
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
                diags.append(
                    Diagnostic(
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
                    )
                )
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
    block_all: bool = False  # BSLLS-off (no specific rule) is active
    block_codes: set[str] = set()  # specific BSL codes currently block-suppressed

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
