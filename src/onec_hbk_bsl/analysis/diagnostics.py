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

# ruff: noqa: F401,I001

from __future__ import annotations

import functools
from importlib import import_module
import os
import re
import threading
from collections.abc import Callable, Iterable
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
from onec_hbk_bsl.analysis.diagnostic.rules.control_flow_rules import (
    bsl148_function_name_spans,
)
from onec_hbk_bsl.analysis.diagnostic.cst import (
    diagnostics_bsl004_from_tree,
    loop_body_line_indices_0,
    ts_elseif_then_branch_empty,
    ts_if_main_then_branch_empty,
)
from onec_hbk_bsl.analysis.diagnostic.cst import (
    ts_tree_ok_for_rules as _ts_tree_ok_for_rules,
)
from onec_hbk_bsl.analysis.diagnostic.discovery import (
    build_proc_node_map as _build_proc_node_map,
    collect_identifier_casefolds_in_proc_body as _collect_identifier_casefolds_in_proc_body,
    export_description_anchor_line_idx as _export_description_anchor_line_idx,
    find_proc_definition_node as _find_proc_definition_node,
    find_procedures as _find_procedures,
    find_procedures_from_tree as _find_procedures_from_tree,
    find_regions as _find_regions,
    find_regions_from_tree as _find_regions_from_tree,
    proc_body_start_line_idx_fallback as _proc_body_start_line_idx_fallback,
    ts_first_body_statement_line_idx as _ts_first_body_statement_line_idx,
)
from onec_hbk_bsl.analysis.diagnostic.execution import (
    execute_diagnostic_rule_tasks as _execute_diagnostic_rule_tasks,
)
from onec_hbk_bsl.analysis.diagnostic.registry import (
    build_enabled_invoke_snapshot,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states as _build_line_string_states,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    comma_missing_space_after_cols_in_line as _comma_missing_space_after_cols_in_line,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    comment_start_outside_double_quotes as _comment_start_outside_double_quotes,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    mask_double_quoted_strings_preserve_len as _mask_double_quoted_strings_preserve_len,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    span_is_inside_double_quoted_string as _span_is_inside_double_quoted_string,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    strip_inline_comment_preserve_strings as _strip_inline_comment_preserve_strings,
)
from onec_hbk_bsl.analysis.diagnostic.suppression import (
    Suppressions as _Suppressions,
)
from onec_hbk_bsl.analysis.diagnostic.suppression import (
    is_suppressed as _is_suppressed,
    parse_suppressions as _parse_suppressions,
)
from onec_hbk_bsl.analysis.document_snapshot import QueryTextBlockInfo, build_document_snapshot
from onec_hbk_bsl.analysis.parse_tree import tree_has_errors
from onec_hbk_bsl.analysis.diagnostic.helpers import proc_helpers as _proc_helpers
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    _RE_BSL275_HANDLER,
    _RE_BSL278_PROCNAME,
    _RE_XML_BOOL_SIMPLE,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    _RE_XML_DATAPATH,
    _RE_XML_DIMENSION_BLOCK,
    _RE_XML_EVENT_HANDLER,
    _RE_XML_METHOD_NAME,
    _RE_XML_PRIVILEGED,
    _RE_XML_PROTECTED,
    _RE_XML_SET_FOR_NEW_OBJECTS,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    path_is_command_module_bsl as _path_is_command_module_bsl,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_file_map as _common_module_file_map,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_index_cached as _common_module_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_privileged_map_cached as _common_module_privileged_map_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_proc_names_for_module_cached as _common_module_proc_names_for_module_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_proc_names_for_file_cached as _common_module_proc_names_for_file_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_proc_names_map_cached as _common_module_proc_names_map_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_has_protected_modules_cached as _config_has_protected_modules_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_root_for_file as _config_root_for_file,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    crawl_config_cached as _crawl_config_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    event_subscription_handlers_by_module_cached as _event_subscription_handlers_by_module_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    metadata_name_index_cached as _metadata_name_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_form_xml_path as _current_form_xml_path,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_module_xml_context as _current_module_xml_context,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_object_xml_path as _current_object_xml_path,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    read_text_cached as _read_text_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    roles_with_new_objects_cached as _roles_with_new_objects_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    scheduled_job_handlers_by_module_cached as _scheduled_job_handlers_by_module_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    is_client_notify_completion_export_handler as _is_client_notify_completion_export_handler,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    is_typical_client_command_handler as _is_typical_client_command_handler,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    proc_by_name_and_line as _proc_by_name_and_line,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    proc_containing_line as _proc_containing_line,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    proc_name_span as _proc_name_span,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    procedure_compiler_execution_context as _procedure_compiler_execution_context,
)
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character
from onec_hbk_bsl.analysis.diagnostic.models import (
    Diagnostic,
    ProcInfo,
    RegionInfo,
    Severity,
)
from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
    run_bsl152_cached_public,
    run_bsl154_code_after_async,
    run_bsl156_code_out_of_region,
    run_bsl158_common_module_assign,
    run_bsl159_common_module_invalid_type,
    run_bsl160_common_module_missing_api,
    run_bsl161_168_common_module_names,
    run_bsl172_data_exchange_loading,
    run_bsl173_deleting_collection_item,
)
from onec_hbk_bsl.analysis.diagnostic.rules.method_contract_rules import (
    run_bsl192_193_194_228_266_method_contract_diagnostics,
    run_bsl212_missed_required_parameter,
    run_bsl215_missing_parameter_description,
    run_bsl224_nested_function_in_parameters,
    run_bsl233_public_methods_description,
    run_bsl240_rewrite_method_parameter,
    run_bsl254_transferring_parameters,
)
from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
    run_bsl174_187_236_238_query_metadata_pool,
    run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool,
    run_bsl244_253_261_runtime_pool,
)
from onec_hbk_bsl.analysis.diagnostic.rules.query_runtime_rules import (
    run_bsl234_query_nested_fields_by_dot,
    run_bsl237_redundant_access_to_object,
    run_bsl245_server_side_export_form_method,
)
from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
    run_bsl191_201_query_text_diagnostics,
    run_bsl206_207_209_query_join_diagnostics,
    run_bsl220_235_269_query_text_diagnostics,
)
from onec_hbk_bsl.parser.bsl_parser import BslParser

_proc_param_name_span = _proc_helpers.proc_param_name_span
_proc_param_location = _proc_helpers.proc_param_location

# When a diagnostic span overlaps a "..." literal, drop the warning unless the rule
# is meant to inspect string contents (secrets, duplicates, concat, magic numbers, …).
_CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL: frozenset[str] = frozenset(
    {
        # Line-length spans the whole line; overlap with trailing string literals must not drop the rule.
        "BSL014",
        # CodeBlockBeforeSub spans the whole module-body block, including string literals.
        "BSL155",
        # Duplicated-branch diagnostics may span statements containing string literals.
        "BSL197",
        "BSL198",
        # Method-signature rules span the whole signature line which may contain default-value strings.
        "BSL015",
        "BSL031",
        "BSL005",
        "BSL006",
        "BSL012",
        "BSL022",
        "BSL024",
        "BSL029",
        "BSL035",
        "BSL036",
        "BSL039",
        "BSL047",
        "BSL051",
        "BSL060",
        "BSL077",
        "BSL188",
        "BSL203",
        "BSL205",
        "BSL218",
        "BSL264",
        "BSL225",
        "BSL221",
        "BSL222",
        "BSL148",
        "BSL150",
        "BSL200",
        "BSL173",
        "BSL171",
        "BSL204",
        "BSL179",
        "BSL253",
        "BSL260",
        "BSL265",
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
        "BSL258",
        "BSL262",
        "BSL267",
        "BSL272",
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
        "severity": "ERROR",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["size", "brain-overload"],
    },
    "BSL003": {
        "name": "NonExportMethodsInApiRegion",
        "description": "Method in public API region is not marked as Export",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["design", "api"],
    },
    "BSL004": {
        "name": "EmptyCodeBlock",
        "description": "Empty code block (exception handler, empty «Тогда» branch, …)",
        "severity": "ERROR",
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
        "severity": "WARNING",
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
        "tags": ["design"],
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
    "BSL022": {
        "name": "UsingModalWindows",
        "description": "Предупреждение()/Warning() is a deprecated modal dialog — use "
        "ПоказатьПредупреждение() instead",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["deprecated", "ui"],
    },
    "BSL023": {
        "name": "UsingServiceTag",
        "description": "Service tag (TODO/FIXME/HACK/КЕЙС) found — should be resolved or "
        "linked to a ticket",
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
        "description": "Method body contains no error handling (Try/Except) for potentially "
        "risky operations",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["error-handling", "robustness"],
    },
    "BSL029": {
        "name": "MagicNumber",
        "description": "Magic number literal used directly in code — extract it to a named "
        "constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["convention", "readability"],
    },
    "BSL030": {
        "name": "SemicolonPresence",
        "description": "SemicolonPresence (BSLLS): лишняя «;» в заголовке метода и/или "
        "пропущена в конце выражения",
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
    "BSL039": {
        "name": "NestedTernaryOperator",
        "description": "Nested ternary ?() expression reduces readability",
        "severity": "WARNING",
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
        "description": "Сообщить()/Message() is deprecated and should be replaced with "
        "structured UX or logging",
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
    "BSL047": {
        "name": "MagicDate",
        "description": "Date literal is used directly instead of a named constant",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["design", "date-time"],
    },
    "BSL051": {
        "name": "UnreachableCode",
        "description": "Code after an unconditional Возврат/Return or ВызватьИсключение/Raise "
        "is unreachable",
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
    "BSL054": {
        "name": "ExportVariables",
        "description": "Module-level Перем/Var declaration creates shared mutable state — "
        "prefer local variables",
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
    "BSL060": {
        "name": "DoubleNegatives",
        "description": "НЕ НЕ expression — double negation cancels out, use the expression "
        "directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["brainoverload", "badpractice"],
    },
    "BSL062": {
        "name": "UnusedParameters",
        "description": "Procedure/function parameter is never referenced in the method body",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["unused", "design"],
    },
    "BSL064": {
        "name": "ProcedureReturnsValue",
        "description": "Procedure (Процедура) contains 'Возврат <value>' — should be declared "
        "as Function",
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
    "BSL077": {
        "name": "SelectTopWithoutOrderBy",
        "description": "TOP/ПЕРВЫЕ is used in query text without ORDER BY/УПОРЯДОЧИТЬ",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "maintainability"],
    },
    "BSL097": {
        "name": "DeprecatedCurrentDate",
        "description": "ТекущаяДата()/CurrentDate() returns server time — use "
        "ТекущаяДатаСеанса() for session time",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["standard", "deprecated", "unpredictable"],
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
        "description": "НачатьТранзакцию/BeginTransaction must be placed immediately before a "
        "Try/Except block",
        "severity": "ERROR",
        "sonar_type": "ERROR",
        "sonar_severity": "MAJOR",
        "tags": ["standard"],
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
        "description": "Executable code appears before procedure/function definitions (module "
        "body)",
        "severity": "ERROR",
        "sonar_type": "ERROR",
        "sonar_severity": "BLOCKER",
        "tags": ["error"],
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
        "description": "ЗафиксироватьТранзакцию/CommitTransaction must be inside a Try/Except "
        "block",
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
        "description": "Full-access (privileged) common module name does not match naming "
        "convention",
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
        "description": "Compilation directive on the method is missing or differs from calling "
        "context",
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
        "description": "Modification handlers do not check "
        "ОбменДаннымиЗагрузка/DataExchangeLoad flag",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "data-exchange"],
        "implemented": True,
    },
    "BSL173": {
        "name": "DeletingCollectionItem",
        "description": "Collection item is deleted inside a Для Каждого/For Each loop — may "
        "cause errors",
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
        "description": "УстановитьБезопасныйРежим(Ложь)/SetSafeMode(False) disables security "
        "sandbox",
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
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
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
        "description": "ДанныеФормыВЗначение()/FormDataToValue() is slow — prefer working with "
        "server objects directly",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["performance", "ui"],
        "implemented": True,
    },
    "BSL191": {
        "name": "FullOuterJoinQuery",
        "description": "Full outer join (ПОЛНОЕ ВНЕШНЕЕ/FULL OUTER JOIN) in query — usually a "
        "design mistake",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "design"],
        "implemented": True,
    },
    "BSL192": {
        "name": "FunctionNameStartsWithGet",
        "description": "Function name should start with 'Получить'/'Get' to indicate it "
        "returns a value",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL193": {
        "name": "FunctionOutParameter",
        "description": "Function modifies a reference parameter (out-parameter) — use a "
        "Procedure instead",
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
        "sonar_type": "CODE_SMELL",
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
        "description": "Query join with a virtual table without parameters — may return too "
        "many rows",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL208": {
        "name": "LatinAndCyrillicSymbolInWord",
        "description": "Identifier contains both Latin and Cyrillic characters — visually "
        "ambiguous",
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
        "sonar_severity": "MAJOR",
        "tags": ["query", "performance", "standard"],
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
        "description": "НСтр() is used inside СтрШаблон() — localized strings should be "
        "composed differently",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["localization", "style"],
        "implemented": True,
    },
    "BSL223": {
        "name": "NestedConstructorsInStructureDeclaration",
        "description": "Structure constructor contains nested constructors — hard to read and "
        "maintain",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["readability", "design"],
        "implemented": True,
    },
    "BSL224": {
        "name": "NestedFunctionInParameters",
        "description": "Function call is used as an argument to another function — reduces "
        "readability",
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
        "description": "ПользователиОС()/OSUsers() is used — OS user enumeration is a security "
        "concern",
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
        "description": "НачатьТранзакцию/ЗафиксироватьТранзакцию/ОтменитьТранзакцию calls are "
        "unbalanced",
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
        "description": "Query references a metadata object that does not exist in the "
        "configuration",
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
        "description": "Metadata object and its child (attribute/tabular section) share the "
        "same name",
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
        "description": "УстановитьПривилегированныйРежим(Истина)/SetPrivilegedMode(True) "
        "elevates permissions",
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
        "description": "Style element is created with a constructor instead of using built-in "
        "styles",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["ui", "design"],
        "implemented": True,
    },
    "BSL250": {
        "name": "TempFilesDir",
        "description": "КаталогВременныхФайлов()/TempFilesDir() used instead of safer temporary "
        "file APIs",
        "severity": "WARNING",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MAJOR",
        "tags": ["standard", "badpractice"],
        "implemented": True,
    },
    "BSL251": {
        "name": "TernaryOperatorUsage",
        "description": "Ternary operator (?(cond, true, false)) reduces readability — consider "
        "If/Else",
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
        "description": "Numeric conversion inside Попытка/Try — exception obscures conversion "
        "errors",
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
        "severity": "ERROR",
        "sonar_type": "ERROR",
        "sonar_severity": "BLOCKER",
        "tags": ["suspicious", "brainoverload"],
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
        "description": "НайтиПоКоду()/FindByCode() is called without existence check — may "
        "return Undefined",
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
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["standard", "badpractice"],
        "implemented": True,
    },
    "BSL263": {
        "name": "UseLessForEach",
        "description": "Для Каждого/For Each loop body does nothing useful with the iteration "
        "variable",
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
        "description": "Ternary operator returns its condition directly — simplify to the "
        "condition",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["redundant", "readability"],
        "implemented": True,
    },
    "BSL266": {
        "name": "UsingCancelParameter",
        "description": "Параметр «Отказ»/Cancel is modified but not checked correctly in the "
        "handler",
        "severity": "WARNING",
        "sonar_type": "BUG",
        "sonar_severity": "MAJOR",
        "tags": ["correctness", "events"],
        "implemented": True,
    },
    "BSL267": {
        "name": "UsingExternalCodeTools",
        "description": "External data processor, report, or extension execution tools are used",
        "severity": "ERROR",
        "sonar_type": "SECURITY_HOTSPOT",
        "sonar_severity": "CRITICAL",
        "tags": ["standard", "design"],
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
        "description": "ПОДОБНО/LIKE operator in query — may prevent index usage and cause "
        "full scans",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "MINOR",
        "tags": ["query", "performance"],
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
        "description": "Letter «ё» used in identifiers or string literals — use «е» for "
        "consistency",
        "severity": "INFORMATION",
        "sonar_type": "CODE_SMELL",
        "sonar_severity": "INFO",
        "tags": ["style", "convention"],
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
    "BSL011": "Когнитивная сложность метода превышает допустимый порог",
    "BSL012": "Жёстко закодированные пароли или ключи",
    "BSL013": "Закомментированный код",
    "BSL014": "Строка слишком длинная",
    "BSL015": "Слишком много необязательных параметров",
    "BSL016": "Нестандартная область",
    "BSL017": "Экспортный метод в модуле команды или формы",
    "BSL019": "Цикломатическая сложность метода превышает допустимый порог",
    "BSL020": "Превышена допустимая вложенность операторов",
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
    "BSL035": "Дублированный строковый литерал",
    "BSL036": "Сложное условие",
    "BSL039": "Вложенный тернарный оператор",
    "BSL040": "Использование «ЭтаФорма» вне обработчика событий",
    "BSL041": "Использование устаревшего метода Сообщить()/Message()",
    "BSL042": "Пустой экспортный метод",
    "BSL047": "Магическая дата",
    "BSL051": "Недостижимый код",
    "BSL052": "Условие всегда истинно или всегда ложно",
    "BSL054": "Переменная на уровне модуля",
    "BSL055": "Несколько последовательных пустых строк",
    "BSL060": "Двойное отрицание",
    "BSL062": "Неиспользуемый параметр",
    "BSL064": "Процедура возвращает значение",
    "BSL065": "Экспортный метод без описания",
    "BSL066": "Устаревшая функция Найти() — используйте СтрНайти()",
    "BSL077": "Использование ПЕРВЫЕ/TOP без УПОРЯДОЧИТЬ/ORDER BY в запросе",
    "BSL097": "Использование «ТекущаяДата» — замените на «ТекущаяДатаСеанса»",
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
    "BSL265": "Бесполезный тернарный оператор",
    "BSL266": "Параметр «Отказ» изменяется некорректно",
    "BSL267": "Использование инструментов выполнения внешнего кода",
    "BSL268": "НайтиПоНаименованию() — медленный полнотекстовый поиск",
    "BSL269": "Оператор ПОДОБНО может привести к полному сканированию таблицы",
    "BSL271": "Объект или метод недоступен на Linux/Unix-сервере",
    "BSL272": "Синхронный серверный вызов в управляемом интерфейсе",
    "BSL273": "Обращение к виртуальной таблице без параметров",
    "BSL274": "Путь к данным реквизита формы не существует",
    "BSL275": "Обработчик HTTP-сервиса имеет некорректную сигнатуру",
    "BSL276": "Некорректное использование ПродолжитьВызов() в расширении",
    "BSL277": "ОтменитьТранзакцию вызвана вне блока Исключение",
    "BSL278": "Обработчик веб-сервиса имеет некорректную сигнатуру",
    "BSL279": "Использование буквы «ё» в идентификаторах",
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
    "BSL011": "Decompose into smaller methods; extract nested conditions to named variables.",
    "BSL012": "Move credentials to OS environment variables or 1C InfoBase settings.",
    "BSL013": "Delete or restore the commented-out code block.",
    "BSL014": "Break the long line using BSL | continuation or an intermediate variable.",
    "BSL015": "Reduce optional parameters or introduce a parameter struct/object.",
    "BSL022": "Replace Предупреждение() with asynchronous ShowMessageBox().",
    "BSL027": "Replace Перейти/Goto with a structured loop or conditional.",
    "BSL028": "Wrap risky operations in Попытка...Исключение...КонецПопытки.",
    "BSL033": "Move the query outside the loop; collect data first, then iterate.",
    "BSL035": "Extract the repeated string to a named constant.",
    "BSL042": "Implement the method body or remove the Export keyword.",
    "BSL047": "Extract the date literal to a named constant.",
    "BSL051": "Remove the unreachable code or restructure the control flow.",
    "BSL052": "Remove the constant condition — the branch always/never executes.",
    "BSL060": "Remove the double negation — НЕ НЕ cancels out.",
    "BSL062": "Remove the unused parameter or add a comment explaining why it is kept.",
    "BSL064": "Change 'Процедура' to 'Функция' and add the required return type handling.",
    "BSL065": "Add a // Description comment on the line before the Export method declaration.",
    "BSL066": "Replace Найти() with СтрНайти() / StrFind().",
    "BSL077": "List columns explicitly: ВЫБРАТЬ Поле1, Поле2 ИЗ instead of ВЫБРАТЬ *.",
    "BSL097": "Replace ТекущаяДата() with ТекущаяДатаСеанса() for consistent session-based time.",
    "BSL131": "Переименуйте или объедините области с одинаковым именем.",
}


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
        "Typo",
        "UsageWriteLogEvent",
        "UselessTernaryOperator",
        "UsingServiceTag",
        "YoLetterUsage",
    }
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


_ProcInfo = ProcInfo
_RegionInfo = RegionInfo


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

# Local Перем declarations
_RE_VAR_LOCAL = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+)\s*;",
    re.IGNORECASE,
)

# Module-level ``Перем Имя;`` / ``Var Name;`` (BSLLS MissingVariablesDescription)
_RE_VAR_MODULE = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+?)\s*(?:Экспорт|Export)?\s*;",
    re.IGNORECASE,
)

# Module-level ``Перем Имя Экспорт;`` / ``Var Name Export;`` (BSLLS ExportVariables)
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
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While|Исключение|Except)\b",
    re.IGNORECASE,
)
_CC_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)
_CC_ELSE = re.compile(
    r"^\s*(?:ИначеЕсли|ElsIf|Иначе|Else)\b",
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


def _count_mccabe_bool_ops(text: str, paren_depth: int = 0) -> tuple[int, int]:
    _ = paren_depth
    return len(_RE_MCCABE_BOOL.findall(text)), 0


def _count_cognitive_ternary_ops(text: str, control_nesting: int) -> int:
    score = 0
    ternary_depth = 0
    paren_stack: list[bool] = []
    i = 0
    while i < len(text):
        if text[i] == "?" and i + 1 < len(text) and text[i + 1] == "(":
            score += 1 + control_nesting + ternary_depth
            ternary_depth += 1
            paren_stack.append(True)
            i += 2
            continue
        if text[i] == "(":
            paren_stack.append(False)
        elif text[i] == ")" and paren_stack:
            if paren_stack.pop():
                ternary_depth = max(0, ternary_depth - 1)
        i += 1
    return score


def _line_has_self_call(line: str, proc_name: str | None) -> bool:
    if not proc_name:
        return False
    return bool(re.search(rf"(?<![.\w]){re.escape(proc_name)}\s*\(", line, re.IGNORECASE))


def _mask_strings_and_comments_for_counter(line: str, in_string_at_start: bool = False) -> str:
    if not in_string_at_start and '"' not in line and "//" not in line:
        return line
    chars = list(line)
    in_string = in_string_at_start
    i = 0
    while i < len(chars):
        ch = chars[i]
        if not in_string and ch == "/" and i + 1 < len(chars) and chars[i + 1] == "/":
            for j in range(i, len(chars)):
                chars[j] = " "
            break
        if ch == '"':
            in_string = not in_string
            i += 1
            continue
        if in_string:
            chars[i] = " "
        i += 1
    return "".join(chars)


def _count_cognitive_bool_ops(text: str, last_op: str | None = None) -> tuple[int, str | None]:
    """BSLLS/Sonar cognitive complexity counts boolean operator runs, not every token."""
    count = 0
    current = last_op
    for match in _RE_MCCABE_BOOL.finditer(text):
        op = match.group(0).casefold()
        if op in {"and", "и"}:
            op = "and"
        else:
            op = "or"
        if op != current:
            count += 1
            current = op
    return count, current


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
    "UsingObjectNotAvailableUnix": "BSL271",
    "UsingSynchronousCalls": "BSL272",
    "VirtualTableCallWithoutParameters": "BSL273",
    "WrongDataPathForFormElements": "BSL274",
    "WrongHttpServiceHandler": "BSL275",
    "WrongUseFunctionProceedWithCall": "BSL276",
    "WrongUseOfRollbackTransactionMethod": "BSL277",
    "WrongWebServiceHandler": "BSL278",
    "YoLetterUsage": "BSL279",
}

# ---------------------------------------------------------------------------
# Rule code normalization (BSL### and BSLLS names in select/ignore / CLI / LSP)
# ---------------------------------------------------------------------------

_RE_BSL_CODE_TOKEN = re.compile(r"^BSL\d{3}$", re.IGNORECASE)

_PUBLIC_RULE_CODES: frozenset[str] = frozenset(_BSLLS_NAME_TO_CODE.values())

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
        code = t.upper()
        return code if code in _PUBLIC_RULE_CODES else None
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
    """Return the only supported public rule profile."""
    from onec_hbk_bsl.analysis.bslls_parity import STRICT_BSLLS_PROFILE

    return STRICT_BSLLS_PROFILE


# Deprecated dialog: Предупреждение(...) / Warning(...)
_RE_DEPRECATED_MSG = re.compile(
    r"^\s*(?:Предупреждение|Warning)\s*\(",
    re.IGNORECASE,
)
_RE_BSL202_STRTEMPLATE = re.compile(r"\b(?:СтрШаблон|StrTemplate)\s*\(", re.IGNORECASE)
_BSL223_STRUCTURE_NAMES = frozenset(
    {"структура", "structure", "фиксированнаяструктура", "fixedstructure"}
)
_BSL249_STYLE_CONSTRUCTOR_NAMES = frozenset({"рамка", "border", "цвет", "color", "шрифт", "font"})
_RE_BSL221_NSTR = re.compile(r"\b(?:НСтр|NStr)\s*\(\s*\"(?P<body>[^\"]*)\"\s*\)", re.IGNORECASE)
_RE_BSL221_LANG = re.compile(r"(?:^|;)\s*(?P<lang>[A-Za-z]{2})\s*=", re.IGNORECASE)
_RE_BSL271_UNIX_UNAVAILABLE_NEW = re.compile(
    r"\b(?:Новый|New)\s+(?P<name>COMОбъект|COMObject|Почта|Mail)\b",
    re.IGNORECASE,
)
_RE_BSL271_PLATFORM_GUARD = re.compile(r"\b(?:Linux_x86|Windows|MacOS)\b", re.IGNORECASE)
# BSL215 — MissingParameterDescription: comment section headers and param entry
_RE_BSL215_PARAMS_SECTION = re.compile(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", re.IGNORECASE)
_RE_BSL215_PARAM_ENTRY = re.compile(r"^\s*//\s{1,4}(\w+)\s*-", re.UNICODE)
_RE_BSL215_COMMENT_LINE = re.compile(r"^\s*//")

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
_RE_BSL216_ANY_KEYWORD = re.compile(
    r"\b(?:"
    r"По|To|Из|In|Или|Or|И|And|"
    r"Экспорт|Export|Тогда|Then|Цикл|Do|"
    r"Если|If|ИначеЕсли|ElsIf|ElseIf|Пока|While|Для|For|Не|Not|Каждого|Each"
    r")\b",
    re.IGNORECASE,
)
# BSL215/BSL233 — compiler directive (e.g. &НаКлиенте) preceding a proc header
_RE_COMPILER_DIRECTIVE = re.compile(r"^\s*&\w+\s*$")
_RE_TRY_OPEN = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
_RE_TRY_CLOSE = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
# BSL240 / write-only var assignment
_RE_MODULE_ASSIGN = re.compile(r"^\s*(\w+)\s*=(?!=)", re.IGNORECASE)
_RE_ASSIGN_LHS = re.compile(r"^\s*(?P<name>\w+)\s*=(?!=)", re.IGNORECASE)
_RE_BSL192_GET = re.compile(r"^(?:Получить|Get)\w*$", re.IGNORECASE)
_RE_BSL266_CANCEL = re.compile(r"^(?:Отказ|Cancel)$", re.IGNORECASE)
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
_RE_BSL149_CASE_PART = re.compile(
    r"^\s*(?:ВЫБОР|CASE|КОГДА|WHEN|ТОГДА|THEN|ИНАЧЕ|ELSE|КОНЕЦ|END)\b",
    re.IGNORECASE,
)
# Query continuation line
_RE_BSL149_CONTINUATION = re.compile(r"^\s*\|")
# Inline query comment
_RE_BSL149_INLINE_COMMENT = re.compile(r"\s*//.*$")
_RE_BSL029_ANY_DIGIT = re.compile(r"\d")
_RE_BSL208_WORD = re.compile(r"\b[a-zA-ZА-ЯЁа-яё_][a-zA-ZА-ЯЁа-яё0-9_]*\b", re.UNICODE)
_RE_BSL208_HAS_LATIN = re.compile(r"[a-zA-Z]")
_RE_BSL208_HAS_CYRILLIC = re.compile(r"[А-ЯЁа-яё]")

# BSL210 — LogicalOrInTheWhereSectionOfQuery
_RE_BSL210_OR = re.compile(r"\b(?:ИЛИ|OR)\b", re.IGNORECASE)
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
_RE_QUERY_PARSE_ERROR_TAIL_KEYWORD = re.compile(
    r"\b(?:ИЗ|FROM|КАК|AS|ПО|ON|ГДЕ|WHERE|ЛЕВОЕ|LEFT|ПРАВОЕ|RIGHT|"
    r"ВНУТРЕННЕЕ|INNER|ПОЛНОЕ|FULL|СОЕДИНЕНИЕ|JOIN)\s*$",
    re.IGNORECASE,
)
_RE_QUERY_PARSE_ERROR_TAIL_OPERATOR = re.compile(
    r"(?:[=<>+\-*/]|\b(?:И|AND|ИЛИ|OR)\b)\s*$", re.IGNORECASE
)
_RE_QUERY_FIELD_REF = re.compile(r"\b(?P<alias>\w+)\.(?P<field>\w+(?:\.\w+)*)\b", re.IGNORECASE)


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
    for seg in split_commas_outside_double_quotes(field_region):
        field = seg.strip().rstrip('";')
        if not field or field == "*" or re.match(r"^\w+\.\*$", field, re.UNICODE):
            continue
        field_line_match = re.search(re.escape(field), line, re.IGNORECASE)
        if field_line_match and re.search(
            r"\b(?:КАК|AS)\b", line[field_line_match.end() :], re.IGNORECASE
        ):
            continue
        # Multi-line CASE expressions are often split by query continuation lines.
        # Skip intermediate CASE fragments; final line with alias is validated normally.
        if _RE_BSL149_CASE_PART.match(field):
            continue
        if re.search(r"\b(?:ВЫБОР|CASE)\b", field, re.IGNORECASE):
            continue
        # WHERE/JOIN condition fragments (`И ...` / `ИЛИ ...`) are not SELECT fields.
        if re.match(r"^(?:И|ИЛИ|AND|OR)\b", field, re.IGNORECASE):
            continue
        # Incomplete expression continuation (opened parenthesis not closed yet).
        if field.count("(") > field.count(")") and not _RE_BSL149_HAS_ALIAS.search(field):
            continue
        # Broken dynamic-query fragments may leave a dangling table prefix (`Таблица.`).
        # BSLLS does not report those incomplete fields.
        if field.endswith("."):
            continue
        if _RE_BSL149_SELECT.search(field):
            continue
        if not _RE_BSL149_HAS_ALIAS.search(field):
            field_for_message = re.sub(r"\s+", "", field) if field and field[0].isdigit() else field
            field_start = 0
            field_end = len(line.rstrip())
            match = field_line_match
            if match:
                field_start = match.start()
                field_end = match.end()
            else:
                pipe_pos = line.find("|")
                if pipe_pos >= 0:
                    after_pipe = line[pipe_pos + 1 :]
                    leading_ws = len(after_pipe) - len(after_pipe.lstrip())
                    field_start = pipe_pos + 1 + leading_ws
                    field_end = min(len(line.rstrip()), field_start + len(field))
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=field_start,
                    end_line=line_idx + 1,
                    end_character=field_end,
                    severity=Severity.WARNING,
                    code="BSL149",
                    message=(
                        f'Полю "{field_for_message}" не назначен псевдоним или пропущено ключевое слово КАК'
                    ),
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

        end_quote = _query_content_end_quote(content)
        ended_query = end_quote is not None
        head = content[:end_quote].rstrip() if ended_query else content
        if not head:
            if ended_query:
                break
            continue

        yield start_idx + offset + 1, content_base, content, head, ended_query
        if ended_query:
            break


def _query_content_end_quote(content: str) -> int | None:
    pos = 0
    while pos < len(content):
        if content[pos] != '"':
            pos += 1
            continue
        if pos + 1 < len(content) and content[pos + 1] == '"':
            pos += 2
            continue
        return pos
    return None


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
    """Cached per-name call regex."""
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
    """Immediately preceding line is a non-empty ``//`` or ``///`` comment."""
    j = var_line_idx - 1
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
        "BASE64",
        "PKCS",
        "PKCS7",
        "X509",
        "CNS",
        "ASCII",
        "EMAIL",
        "REPLYTO",
        "TO",
        # Misc abbreviations accepted in 1C names
        "ODATA",
        # Embedded canonical BSL keyword fragments inside identifiers
        "ELSIF",
        "ELSE",
        "TRY",
        "EXCEPT",
        "ENDTRY",
        "ENDIF",
    }
)

_RE_LATIN_RUNS = re.compile(r"[a-zA-Z]+[0-9]*")

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
    latin_runs = list(_RE_LATIN_RUNS.finditer(word))
    if not latin_runs:
        return False
    # Keep skip conservative: embedded mixed-case tech fragments are usually
    # reported by BSLLS, but prefix/suffix fragments like Base64... and CNs...
    # are treated as platform-style names.
    for m in latin_runs:
        run = m.group()
        upper = run.upper()
        if upper not in _BSL208_TECH_ACRONYMS:
            return False
        at_edge = m.start() == 0 or m.end() == len(word)
        if not at_edge and m.start() > 0 and m.end() < len(word):
            before = word[m.start() - 1]
            after = word[m.end()]
            if _RE_BSL208_HAS_CYRILLIC.search(before) and _RE_BSL208_HAS_CYRILLIC.search(after):
                return False
        if run != upper and not at_edge:
            return False
    return True


# Statements that MUST end with ;  — simplified: lines inside procs that look
# like assignment, method call, or return, but have no trailing semicolon.
# Only used as a heuristic; BSL allows some statements without semicolons.
_RE_STMT_NO_SEMI = re.compile(
    r"^\s*(?:"
    r"(?:\w+(?:\.\w+)*)\s*\([^)]*\)"  # method call
    r"|(?:\w+(?:\.\w+)*)\s*=\s*\S.*"  # assignment with RHS
    r"|(?:Возврат|Return)\s+\S.*"  # return with value
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

# String literal extractor with BSL doubled-quote escaping.
_RE_STRING_LITERAL = re.compile(r'(?<![A-Za-zА-ЯЁа-яё0-9_])"((?:[^"]|"")*)"')

# Boolean operators count in a single condition line
_RE_BOOL_OP = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)

# String concatenation inside a loop: variable = variable + "string" or + Str(...)
_RE_STR_CONCAT = re.compile(
    r"\b\w+\s*=\s*\w+\s*\+\s*(?:\"[^\"]*\"|\w+\s*\()",
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

_RE_BSL176_DEPRECATED_DOC = re.compile(
    r"(?:@deprecated\b|\bdeprecated\b|\bobsolete\b|\bустар(?:ел|ела|ело|евш\w*)\b)",
    re.IGNORECASE | re.UNICODE,
)

_RE_COMMON_MODULE_PATH = re.compile(r"(?:^|[/\\\\])CommonModules(?:[/\\\\])", re.IGNORECASE)
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
        "толстыйклиентобычноеприложение",
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

_RE_WHILE_TRUE = re.compile(
    r"^\s*(?:Пока|While)\s+(?:Истина|True)\s+(?:Цикл|Do)\b",
    re.IGNORECASE,
)

_RE_VAR_DECL = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)
# Executable code (not comment, not blank, not Перем, not proc header)
_RE_EXECUTABLE_LINE = re.compile(
    r"^\s*(?!//|$|(?:Перем|Var)\b|(?:Процедура|Функция|Procedure|Function)\b|(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b)",
    re.IGNORECASE,
)

# Simplified: a non-empty statement before ; and another after on the same line
_RE_MULTI_STMT = re.compile(
    r";\s*\w",  # ; followed by word char on same line
)

_RE_NULL_COMPARISON = re.compile(
    r"(?:=|<>)\s*(?:NULL|Null)\b|(?:NULL|Null)\s*(?:=|<>)",
    re.IGNORECASE,
)

_RE_NOOP_COMPOUND = re.compile(
    r"\w+\s*(?:\+=\s*0|-=\s*0|\*=\s*1|/=\s*1)\b",
)

_RE_BEGIN_TRANSACTION = re.compile(
    r"\b(?:НачатьТранзакцию|BeginTransaction)\s*\(",
    re.IGNORECASE,
)

_RE_CONNECTION_STRING = re.compile(
    r"(?:Server\s*=|DSN\s*=|Driver\s*=|Database\s*=|Uid\s*=|Pwd\s*=)",
    re.IGNORECASE,
)

_RE_RETURN_STMT = re.compile(r"^\s*(?:Возврат|Return)\b", re.IGNORECASE)
_RE_RETURN_SIMPLE_EXPR = re.compile(r"^\s*(?:Возврат|Return)\s+(.+?);?\s*$", re.IGNORECASE)

_RE_HTTP_REQUEST = re.compile(
    r"(?:HTTPСоединение|HTTPConnection|HTTPЗапрос|HTTPRequest"
    r"|ПолучитьДанные|GetData|ОтправитьДанные|PutData"
    r"|ПолучитьСтроку|GetString|ОтправитьСтроку|PutString)\b",
    re.IGNORECASE,
)

_RE_NEW_OBJECT = re.compile(r"\bНовый\b|\bNew\b", re.IGNORECASE)

_RE_PARAM_COMMENT = re.compile(r"//\s*(?:Параметры|Parameters)\s*:", re.IGNORECASE)

_RE_LITERAL_BOOL_CONDITION = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:Истина|True|Ложь|False)\s+(?:Тогда|Then)\b",
    re.IGNORECASE,
)

_RE_EXCEPT_BLOCK = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
_RE_END_TRY = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
_RE_TRY_OPEN = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
_RE_ERROR_INFO = re.compile(r"(?:ИнформацияОбОшибке|ErrorInfo)\s*\(", re.IGNORECASE)

_RE_DOT_CHAIN = re.compile(r"(?:\.\w+\s*\()+")

# SELECT * in query text (BSL077)
_RE_SELECT_STAR = re.compile(
    r"(?:ВЫБРАТЬ|SELECT)\s+\*",
    re.IGNORECASE,
)

_RE_RAISE_BARE = re.compile(
    r"^\s*(?:ВызватьИсключение|Raise)\s*;",
    re.IGNORECASE,
)

_RE_TODO_COMMENT = re.compile(
    r"//\s*(?:TODO|FIXME|HACK|XXX)\b",
    re.IGNORECASE,
)

_RE_NEGATIVE_CONDITION = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(?:НЕ|Not)\b",
    re.IGNORECASE,
)

_RE_EXECUTE = re.compile(r"(?<!\.)(?:Выполнить|Execute)\s*\(", re.IGNORECASE)

_RE_EXPORTED_VAR = re.compile(
    r"^\s*(?:Перем|Var)\b[^;]*\bЭкспорт\b",
    re.IGNORECASE,
)

_RE_STR_CONCAT_SELF = re.compile(
    r'^\s*(\w+)\s*=\s*\1\s*\+\s*(?:"[^"]*"|\w)',
    re.IGNORECASE,
)

# Matches a sequence where Cyrillic and Latin characters are interleaved
_RE_MIXED_IDENT = re.compile(
    r"(?:[А-ЯЁа-яё]+[A-Za-z]|[A-Za-z]+[А-ЯЁа-яё])\w*",
)

# Assignment is a statement-level construct only — there are no assignment
# expressions, so "assignment in condition" is impossible in BSL by design.

_RE_BREAK = re.compile(r"^\s*(?:Прервать|Break)\s*;", re.IGNORECASE)

_RE_CONTINUE = re.compile(r"^\s*(?:Продолжить|Continue)\s*;", re.IGNORECASE)

_RE_COMMENTED_CODE = re.compile(
    r"^\s*//\s*(?:"
    # Strong BSL declarations / terminators; prose comments with "Если/Для"
    # are too noisy and BSLLS CodeRecognizer does not treat them as code.
    r"(?:Процедура|Функция|КонецПроцедуры|КонецФункции|Перем"
    r"|Function|Procedure|EndProcedure|EndFunction|Var)\b"
    r"|(?:ВЫБРАТЬ|SELECT)\b"
    r"|[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*\s*\("
    # OR a line that looks like a statement (ends with ; or contains :=)
    r"|\w.*(?:;|:=)"
    r")",
    re.IGNORECASE,
)

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

_RE_SQL_SELECT = re.compile(r"(?:ВЫБРАТЬ|SELECT)\b", re.IGNORECASE)

_RE_EVAL = re.compile(r"\b(?:Вычислить|Eval)\s*\(", re.IGNORECASE)

_RE_SLEEP = re.compile(r"\b(?:Приостановить|Sleep)\s*\(", re.IGNORECASE)

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


_RE_COMMENT_ONLY_LINE = re.compile(r"^\s*//")

# BSL131 — EmptyRegion: #Область / #КонецОбласти markers (line-level, no name group)
_RE_REGION_OPEN_LINE = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
_RE_REGION_CLOSE_LINE = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)

_RE_STRING_LITERAL = re.compile(r'(?<![A-Za-zА-ЯЁа-яё0-9_])"((?:[^"]|"")*)"')

_RE_PARAM_HAS_DEFAULT = re.compile(r"=")

_RE_NESTED_CALL = re.compile(r"\w+\s*\([^)]*\w+\s*\(")

_RE_NO_SPACE_BEFORE_COMMENT = re.compile(r"\S//")

_RE_FIND_BY_DESCRIPTION = re.compile(
    r"\b(?:НайтиПоНаименованию|FindByDescription"
    r"|НайтиПоКоду|FindByCode"
    r"|НайтиПоРеквизиту|FindByAttribute)\s*\(",
    re.IGNORECASE,
)

_RE_DEBUG_OUTPUT = re.compile(
    r"\b(?:Сообщить|Message|Предупреждение|Warning)\s*\(",
    re.IGNORECASE,
)

_RE_RETURN_TRUE = re.compile(
    r"^\s*(?:Возврат|Return)\s+(?:Истина|True)\s*;",
    re.IGNORECASE,
)
_RE_RETURN_FALSE = re.compile(
    r"^\s*(?:Возврат|Return)\s+(?:Ложь|False)\s*;",
    re.IGNORECASE,
)

_RE_IF_COND = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(.*?)\s+(?:Тогда|Then)\s*$",
    re.IGNORECASE,
)

_RE_RETURN_PAREN = re.compile(
    r"^\s*(?:Возврат|Return)\s+\((?!\s*(?:Новый|New)\b)",
    re.IGNORECASE,
)

_RE_MULTI_CONCAT = re.compile(r'"[^"]*"\s*\+[^+;]+\+[^+;]+\+')

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


# BSL051 — tree-sitter nodes that close or branch control flow (not executable body).
# Matches keyword roles in tree-sitter block statements (if/while/for/try).
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
_RE_BSL029_TERNARY = re.compile(r"\?\s*\((?P<condition>[^,]+),(?P<true>[^,]*),(?P<false>[^)]*)\)")
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

    header_match = _RE_PROC_HEADER.search(_ts_node_text(node))
    if header_match is not None:
        name = header_match.group("name")
        is_export = bool(header_match.group("export"))
        parsed = _parse_params(header_match.group("params") or "")
        params = [p[0] for p in parsed]
        val_params = [p[0] for p in parsed if p[1]]
        optional_count = sum(1 for p in parsed if p[2])
        optional_params_list = [p[0] for p in parsed if p[2]]

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
            for child in getattr(node, "children", []) or []:
                if getattr(child, "type", None) == "expression":
                    end = child.start_point
                    break
            diags.append(
                Diagnostic(
                    file=path,
                    line=start[0] + 1,
                    character=start[1],
                    end_line=end[0] + 1,
                    end_character=end[1],
                    severity=Severity.ERROR,
                    code="BSL009",
                    message="Удалите бесполезное присваивание переменной самой себе",
                )
            )
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
    return diags


def _calc_cognitive_complexity(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    *,
    string_states: list[bool] | None = None,
    proc_name: str | None = None,
) -> int:
    """
    Calculate simplified Cognitive Complexity for a procedure body.

    Scoring (per SonarSource specification):
    - Each structural element (if/for/while/except/ternary) adds 1 + nesting level
    - Try itself does not add complexity; Except starts the exceptional branch
    - Each else/elseif adds 1 (no nesting bonus)
    - Closing tokens decrease nesting
    - Each logical operator (И/ИЛИ/And/Or) in non-comment code adds 1 (Sonar/BSLLS alignment)
    """
    complexity = 0
    nesting = 0
    bool_last_op: str | None = None
    bool_expr_open = False
    if string_states is None:
        string_states = _build_line_string_states(lines)
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line.lstrip().startswith("|"):
            bool_last_op = None
            bool_expr_open = False
            continue
        line_no_strings = _mask_strings_and_comments_for_counter(
            line,
            string_states[i] if i < len(string_states) else False,
        )
        starts_with_bool = bool(re.match(r"^\s*(?:И|And|ИЛИ|Or)\b", line_no_strings, re.IGNORECASE))
        line_bool_count, bool_last_op = _count_cognitive_bool_ops(
            line_no_strings,
            bool_last_op if (bool_expr_open or starts_with_bool) else None,
        )
        complexity += line_bool_count
        opens_control_expr = bool(
            re.search(r"\b(?:Если|If|ИначеЕсли|ElsIf|Пока|While)\b", line_no_strings, re.IGNORECASE)
            and not re.search(r"\b(?:Тогда|Then|Цикл|Do)\b", line_no_strings, re.IGNORECASE)
        )
        opens_assignment_expr = bool(re.search(r"[=+\-*/]\s*$", line_no_strings))
        bool_expr_open = (
            opens_control_expr
            or opens_assignment_expr
            or bool(
                (bool_expr_open or starts_with_bool)
                and not re.search(
                    r"(?:;|\b(?:Тогда|Then|Цикл|Do)\b)\s*$", line_no_strings, re.IGNORECASE
                )
            )
        )
        if not bool_expr_open:
            bool_last_op = None
        complexity += _count_cognitive_ternary_ops(line_no_strings, nesting)
        if _line_has_self_call(line_no_strings, proc_name):
            complexity += 1
        if _CC_OPEN.match(line):
            complexity += 1 + nesting
            nesting += 1
        elif _CC_CLOSE.match(line):
            nesting = max(0, nesting - 1)
        elif _CC_ELSE.match(line):
            complexity += 1
    return complexity


def _calc_mccabe_complexity(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    *,
    string_states: list[bool] | None = None,
    proc_name: str | None = None,
) -> int:
    """
    Calculate McCabe cyclomatic complexity for a procedure body.

    CC = 1 + number of decision points.
    Decision points: Если/If, ИначеЕсли/ElsIf, Для/For, ДляКаждого/ForEach,
    Пока/While, Исключение/Except, plus each И/And and ИЛИ/Or boolean operator.
    """
    cc = 1
    paren_depth = 0
    if string_states is None:
        string_states = _build_line_string_states(lines)
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line.lstrip().startswith("|"):
            paren_depth = 0
            continue
        line_no_strings = _mask_strings_and_comments_for_counter(
            line,
            string_states[i] if i < len(string_states) else False,
        )
        if _RE_MCCABE_BRANCH.match(line_no_strings):
            cc += 1
        bool_count, paren_depth = _count_mccabe_bool_ops(line_no_strings, paren_depth)
        cc += bool_count
        cc += len(_RE_MCCABE_TERNARY.findall(line_no_strings))
        if _line_has_self_call(line_no_strings, proc_name):
            cc += 1
    return cc


def _calc_complexity_metrics(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    *,
    string_states: list[bool] | None = None,
    proc_name: str | None = None,
) -> tuple[int, int]:
    """Calculate cognitive and McCabe complexity in a single pass over a procedure body."""
    cognitive = 0
    nesting = 0
    bool_last_op: str | None = None
    bool_expr_open = False
    mccabe = 1
    paren_depth = 0
    if string_states is None:
        string_states = _build_line_string_states(lines)
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line.lstrip().startswith("|"):
            bool_last_op = None
            bool_expr_open = False
            paren_depth = 0
            continue
        line_no_strings = _mask_strings_and_comments_for_counter(
            line,
            string_states[i] if i < len(string_states) else False,
        )

        starts_with_bool = bool(re.match(r"^\s*(?:И|And|ИЛИ|Or)\b", line_no_strings, re.IGNORECASE))
        line_bool_count, bool_last_op = _count_cognitive_bool_ops(
            line_no_strings,
            bool_last_op if (bool_expr_open or starts_with_bool) else None,
        )
        cognitive += line_bool_count
        opens_control_expr = bool(
            re.search(r"\b(?:Если|If|ИначеЕсли|ElsIf|Пока|While)\b", line_no_strings, re.IGNORECASE)
            and not re.search(r"\b(?:Тогда|Then|Цикл|Do)\b", line_no_strings, re.IGNORECASE)
        )
        opens_assignment_expr = bool(re.search(r"[=+\-*/]\s*$", line_no_strings))
        bool_expr_open = (
            opens_control_expr
            or opens_assignment_expr
            or bool(
                (bool_expr_open or starts_with_bool)
                and not re.search(
                    r"(?:;|\b(?:Тогда|Then|Цикл|Do)\b)\s*$", line_no_strings, re.IGNORECASE
                )
            )
        )
        if not bool_expr_open:
            bool_last_op = None
        ternary_count = len(_RE_MCCABE_TERNARY.findall(line_no_strings))
        cognitive += _count_cognitive_ternary_ops(line_no_strings, nesting)
        if _line_has_self_call(line_no_strings, proc_name):
            cognitive += 1
        if _CC_OPEN.match(line):
            cognitive += 1 + nesting
            nesting += 1
        elif _CC_CLOSE.match(line):
            nesting = max(0, nesting - 1)
        elif _CC_ELSE.match(line):
            cognitive += 1

        if _RE_MCCABE_BRANCH.match(line_no_strings):
            mccabe += 1
        bool_count, paren_depth = _count_mccabe_bool_ops(line_no_strings, paren_depth)
        mccabe += bool_count
        mccabe += ternary_count
        if _line_has_self_call(line_no_strings, proc_name):
            mccabe += 1
    return cognitive, mccabe


DiagnosticEngine = import_module("onec_hbk_bsl.analysis.diagnostic.engine").DiagnosticEngine
