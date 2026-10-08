"""
BSL diagnostic rules engine.

Produces Diagnostic records for lint issues found in BSL source files.

Built-in rules
--------------
BSL001  ParseError              — Syntax error detected by tree-sitter
BSL002  MethodSize              — Procedure/function longer than N lines (default 200)
BSL003  NonExportMethodsInApiRegion — Method in API region without Export keyword
BSL004  EmptyCodeBlock          — Empty control-flow branch or loop body
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
All comment families support a single line and a range.  An opening marker
after code suppresses only that line; the same marker on its own line opens a
range.  ``noqa-enable``, ``bsl-enable``, or the BSLLS ``-on`` marker closes it.

Inline suppression on a specific line::

    Если Условие Тогда  // noqa: BSL004
    Исключение  // bsl-disable: BSL028
    Исключение  // BSLLS:MagicNumber-off
    Исключение  // noqa            ← suppresses ALL rules on this line

Range suppression::

    // noqa: BSL004
    ... code without BSL004 ...
    // noqa-enable: BSL004

    // bsl-disable: BSL028
    ... code without BSL028 ...
    // bsl-enable: BSL028

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
from onec_hbk_bsl.analysis.source_positions import line_start_offsets
from onec_hbk_bsl.analysis.diagnostic.rules.control_flow_rules import (
    bsl148_function_name_spans,
)
from onec_hbk_bsl.analysis.diagnostic.cst import (
    diagnostics_bsl004_from_tree,
    iter_ts_nodes,
    loop_body_line_indices_0,
    ts_elseif_then_branch_empty,
    ts_if_main_then_branch_empty,
    tree_has_errors,
)
from onec_hbk_bsl.analysis.diagnostic.cst import (
    ts_tree_ok_for_rules as _ts_tree_ok_for_rules,
)
from onec_hbk_bsl.analysis.diagnostic.discovery import (
    build_proc_node_map as _build_proc_node_map,
    collect_identifier_casefolds_in_proc_body as _collect_identifier_casefolds_in_proc_body,
    export_description_anchor_line_idx as _export_description_anchor_line_idx,
    find_proc_definition_node as _find_proc_definition_node,
    find_procedures_from_tree as _find_procedures_from_tree,
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
from onec_hbk_bsl.analysis.diagnostic.helpers import proc_helpers as _proc_helpers
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    _RE_BSL275_HANDLER,
    _RE_BSL278_PROCNAME,
    _RE_XML_BOOL_SIMPLE,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    _RE_XML_DATAPATH,
    _RE_XML_DIMENSION_BLOCK,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    path_is_command_module_bsl as _path_is_command_module_bsl,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_index_cached as _common_module_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_info_cached as _common_module_info_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_privileged_map_cached as _common_module_privileged_map_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_proc_names_for_module_cached as _common_module_proc_names_for_module_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    common_module_exported_proc_names_for_module_cached as _common_module_exported_proc_names_for_module_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_has_protected_modules_cached as _config_has_protected_modules_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_protected_module_refs_cached as _config_protected_module_refs_cached,
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
    event_subscription_handlers_cached as _event_subscription_handlers_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    split_common_module_method_path as _split_common_module_method_path,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    workspace_metadata_name_index_cached as _workspace_metadata_name_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    metadata_typed_name_index_cached as _metadata_typed_name_index_cached,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_form_xml_path as _current_form_xml_path,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_module_xml_context as _current_module_xml_context,
)
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_metadata_object_for_file_cached as _current_metadata_object_for_file_cached,
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

_proc_param_location = _proc_helpers.proc_param_location

# When a diagnostic span overlaps a "..." literal, drop the warning unless the rule
# is meant to inspect string contents (secrets, duplicates, concat, magic numbers, …).
_CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL: frozenset[str] = frozenset(
    {
        # Line-length spans the whole line; overlap with trailing string literals must not drop the rule.
        "BSL014",
        # SemicolonPresence is structural: the anchor may be a string literal when the
        # whole assignment/call/return statement misses its trailing semicolon.
        "BSL030",
        # CodeBlockBeforeSub spans the whole module-body block, including string literals.
        "BSL155",
        # Self-assignment may include string literals as index keys.
        "BSL009",
        # Duplicate operands can be string literals or expressions containing them.
        "BSL052",
        # Duplicated-branch diagnostics may span statements containing string literals.
        "BSL197",
        "BSL198",
        # Method-signature rules span the whole signature line which may contain default-value strings.
        "BSL015",
        "BSL031",
        # MissedRequiredParameter spans the full call; supplied arguments may be string literals.
        "BSL212",
        # CodeAfterAsyncCall spans the full async call; arguments may be string literals.
        "BSL154",
        # ExecuteExternalCode spans the full dangerous call; code text is commonly a string argument.
        "BSL183",
        "BSL005",
        "BSL006",
        "BSL012",
        "BSL022",
        "BSL024",
        "BSL228",
        "BSL029",
        "BSL035",
        "BSL036",
        "BSL039",
        "BSL251",
        "BSL047",
        "BSL051",
        "BSL060",
        "BSL077",
        "BSL188",
        "BSL203",
        "BSL205",
        "BSL218",
        "BSL223",
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
        "BSL004",
        "BSL255",
        "BSL179",
        "BSL181",
        "BSL182",
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
        "BSL268",
        # UsingObjectNotAvailableUnix spans the full New COMObject/Mail expression,
        # whose constructor arguments commonly contain string literals.
        "BSL271",
        "BSL272",
    }
)

# ---------------------------------------------------------------------------
# Public rule registry  (used for the ``rules`` command and machine-readable output)
# ---------------------------------------------------------------------------

RULE_METADATA: dict[str, dict] = {
    "BSL001": {
        "name": "ParseError",
        "description": "Source code parse error",
        "severity": "ERROR",
        "tags": ["syntax"],
    },
    "BSL002": {
        "name": "MethodSize",
        "description": "Method size",
        "severity": "ERROR",
        "tags": ["size", "brain-overload"],
    },
    "BSL003": {
        "name": "NonExportMethodsInApiRegion",
        "description": "Non export methods in API regions",
        "severity": "INFORMATION",
        "tags": ["design", "api"],
    },
    "BSL004": {
        "name": "EmptyCodeBlock",
        "description": "Empty code block",
        "severity": "ERROR",
        "tags": ["error-handling"],
    },
    "BSL005": {
        "name": "UsingHardcodeNetworkAddress",
        "description": "Using hardcode ip addresses in code",
        "severity": "WARNING",
        "tags": ["security", "hardware-related"],
    },
    "BSL006": {
        "name": "UsingHardcodePath",
        "description": "Using hardcode file paths in code",
        "severity": "WARNING",
        "tags": ["security", "hardware-related"],
    },
    "BSL007": {
        "name": "UnusedLocalVariable",
        "description": "Unused local variable",
        "severity": "WARNING",
        "tags": ["unused"],
    },
    "BSL008": {
        "name": "TooManyReturns",
        "description": "Methods should not have too many return statements",
        "severity": "WARNING",
        "tags": ["brain-overload"],
    },
    "BSL009": {
        "name": "SelfAssign",
        "description": "Variable is assigned to itself",
        "severity": "WARNING",
        "tags": ["suspicious"],
    },
    "BSL011": {
        "name": "CognitiveComplexity",
        "description": "Cognitive complexity",
        "severity": "WARNING",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL012": {
        "name": "UsingHardcodeSecretInformation",
        "description": "Storing confidential information in code",
        "severity": "ERROR",
        "tags": ["security", "credentials"],
    },
    "BSL013": {
        "name": "CommentedCode",
        "description": "Commented out code",
        "severity": "WARNING",
        "tags": ["unused"],
    },
    "BSL014": {
        "name": "LineLength",
        "description": "Line Length limit",
        "severity": "INFORMATION",
        "tags": ["design"],
    },
    "BSL015": {
        "name": "NumberOfOptionalParams",
        "description": "Limit number of optional parameters in method",
        "severity": "WARNING",
        "tags": ["design", "brain-overload"],
    },
    "BSL016": {
        "name": "NonStandardRegion",
        "description": "Non-standard region of module",
        "severity": "INFORMATION",
        "tags": ["convention"],
    },
    "BSL017": {
        "name": "CommandModuleExportMethods",
        "description": "Export methods in command and general command modules",
        "severity": "WARNING",
        "tags": ["design"],
    },
    "BSL019": {
        "name": "CyclomaticComplexity",
        "description": "Cyclomatic complexity",
        "severity": "WARNING",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL020": {
        "name": "NestedStatements",
        "description": "Control flow statements should not be nested too deep",
        "severity": "WARNING",
        "tags": ["brain-overload"],
    },
    "BSL022": {
        "name": "UsingModalWindows",
        "description": "Using modal windows",
        "severity": "WARNING",
        "tags": ["deprecated", "ui"],
    },
    "BSL023": {
        "name": "UsingServiceTag",
        "description": "Using service tags",
        "severity": "INFORMATION",
        "tags": ["convention"],
    },
    "BSL024": {
        "name": "SpaceAtStartComment",
        "description": "Space at the beginning of the comment",
        "severity": "INFORMATION",
        "tags": ["convention", "style"],
    },
    "BSL025": {
        "name": "EmptyStatement",
        "description": "Empty statement",
        "severity": "WARNING",
        "tags": ["syntax", "convention"],
    },
    "BSL026": {
        "name": "EmptyRegion",
        "description": "The region should not be empty",
        "severity": "INFORMATION",
        "tags": ["unused"],
    },
    "BSL027": {
        "name": "UsingGoto",
        "description": '"goto" statement should not be used',
        "severity": "WARNING",
        "tags": ["design", "brain-overload"],
    },
    "BSL028": {
        "name": "MissingCodeTryCatchEx",
        "description": 'Missing code in Raise block in "Try ... Raise ... EndTry"',
        "severity": "INFORMATION",
        "tags": ["error-handling", "robustness"],
    },
    "BSL029": {
        "name": "MagicNumber",
        "description": "Magic numbers",
        "severity": "INFORMATION",
        "tags": ["convention", "readability"],
    },
    "BSL030": {
        "name": "SemicolonPresence",
        "description": 'Statement should end with semicolon symbol ";"',
        "severity": "INFORMATION",
        "tags": ["convention", "style"],
    },
    "BSL031": {
        "name": "NumberOfParams",
        "description": "Number of parameters in method",
        "severity": "WARNING",
        "tags": ["design", "brain-overload"],
    },
    "BSL032": {
        "name": "FunctionShouldHaveReturn",
        "description": "The function should have return",
        "severity": "WARNING",
        "tags": ["suspicious", "design"],
    },
    "BSL033": {
        "name": "CreateQueryInCycle",
        "description": "Execution query on cycle",
        "severity": "WARNING",
        "tags": ["performance", "brain-overload"],
    },
    "BSL035": {
        "name": "DuplicateStringLiteral",
        "description": "Duplicate string literal",
        "severity": "INFORMATION",
        "tags": ["convention", "readability"],
    },
    "BSL036": {
        "name": "IfConditionComplexity",
        "description": 'Usage of complex expressions in the "If" condition',
        "severity": "WARNING",
        "tags": ["brain-overload", "complexity"],
    },
    "BSL039": {
        "name": "NestedTernaryOperator",
        "description": "Nested ternary operator",
        "severity": "WARNING",
        "tags": ["brain-overload", "readability"],
    },
    "BSL040": {
        "name": "UsingThisForm",
        "description": 'Using deprecated property "ThisForm"',
        "severity": "INFORMATION",
        "tags": ["design", "ui"],
    },
    "BSL041": {
        "name": "DeprecatedMessage",
        "description": 'Restriction on the use of deprecated "Message" method',
        "severity": "WARNING",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL042": {
        "name": "UnusedLocalMethod",
        "description": "Unused local method",
        "severity": "WARNING",
        "tags": ["design", "api"],
    },
    "BSL047": {
        "name": "MagicDate",
        "description": "Magic dates",
        "severity": "INFORMATION",
        "tags": ["design", "date-time"],
    },
    "BSL051": {
        "name": "UnreachableCode",
        "description": "Unreachable Code",
        "severity": "WARNING",
        "tags": ["suspicious", "dead-code"],
    },
    "BSL052": {
        "name": "IdenticalExpressions",
        "description": "There are identical sub-expressions to the left and to the right of "
        'the "foo" operator',
        "severity": "WARNING",
        "tags": ["suspicious", "logic"],
    },
    "BSL054": {
        "name": "ExportVariables",
        "description": "Ban export global module variables",
        "severity": "INFORMATION",
        "tags": ["design", "global-state"],
    },
    "BSL055": {
        "name": "ConsecutiveEmptyLines",
        "description": "Consecutive empty lines",
        "severity": "INFORMATION",
        "tags": ["style", "formatting"],
    },
    "BSL060": {
        "name": "DoubleNegatives",
        "description": "Double negatives",
        "severity": "WARNING",
        "tags": ["brainoverload", "badpractice"],
    },
    "BSL062": {
        "name": "UnusedParameters",
        "description": "Unused parameter",
        "severity": "WARNING",
        "tags": ["unused", "design"],
    },
    "BSL064": {
        "name": "ProcedureReturnsValue",
        "description": "Procedure should not return Value",
        "severity": "ERROR",
        "tags": ["correctness", "design"],
    },
    "BSL065": {
        "name": "MissingReturnedValueDescription",
        "description": "Function returned values description is missing",
        "severity": "INFORMATION",
        "tags": ["design", "documentation"],
    },
    "BSL066": {
        "name": "DeprecatedFind",
        "description": 'Using of the deprecated method "Find"',
        "severity": "WARNING",
        "tags": ["deprecated", "compatibility"],
    },
    "BSL077": {
        "name": "SelectTopWithoutOrderBy",
        "description": "Using 'SELECT TOP' without 'ORDER BY'",
        "severity": "WARNING",
        "tags": ["performance", "maintainability"],
    },
    "BSL097": {
        "name": "DeprecatedCurrentDate",
        "description": 'Using of the deprecated method "CurrentDate"',
        "severity": "WARNING",
        "tags": ["standard", "deprecated", "unpredictable"],
    },
    "BSL131": {
        "name": "DuplicateRegion",
        "description": "Duplicate regions",
        "severity": "INFORMATION",
        "tags": ["style"],
        "implemented": True,
    },
    "BSL148": {
        "name": "AllFunctionPathMustHaveReturn",
        "description": "All execution paths of a function must have a Return statement",
        "severity": "ERROR",
        "tags": ["error-handling", "correctness"],
        "implemented": True,
    },
    "BSL149": {
        "name": "AssignAliasFieldsInQuery",
        "description": "Assigning aliases to selected fields in a query",
        "severity": "INFORMATION",
        "tags": ["convention", "query"],
        "implemented": True,
    },
    "BSL150": {
        "name": "BadWords",
        "description": "Prohibited words",
        "severity": "WARNING",
        "tags": ["convention"],
        "implemented": True,
    },
    "BSL151": {
        "name": "BeginTransactionBeforeTryCatch",
        "description": "Violating transaction rules for the 'BeginTransaction' method",
        "severity": "ERROR",
        "tags": ["standard"],
        "implemented": True,
    },
    "BSL152": {
        "name": "CachedPublic",
        "description": "Cached public methods",
        "severity": "WARNING",
        "tags": ["design", "performance"],
        "implemented": True,
    },
    "BSL153": {
        "name": "CanonicalSpellingKeywords",
        "description": "Canonical keyword writing",
        "severity": "INFORMATION",
        "tags": ["convention", "style"],
        "implemented": True,
    },
    "BSL154": {
        "name": "CodeAfterAsyncCall",
        "description": "Lines of code after the asynchronous method call",
        "severity": "WARNING",
        "tags": ["async", "correctness"],
        "implemented": True,
    },
    "BSL155": {
        "name": "CodeBlockBeforeSub",
        "description": "Method definitions must be placed before the module body operators",
        "severity": "ERROR",
        "tags": ["error"],
        "implemented": True,
    },
    "BSL156": {
        "name": "CodeOutOfRegion",
        "description": "Code out of region",
        "severity": "INFORMATION",
        "tags": ["convention", "structure"],
        "implemented": True,
    },
    "BSL157": {
        "name": "CommitTransactionOutsideTryCatch",
        "description": "Violating transaction rules for the 'CommitTransaction' method",
        "severity": "ERROR",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL158": {
        "name": "CommonModuleAssign",
        "description": "CommonModuleAssign",
        "severity": "ERROR",
        "tags": ["correctness", "module"],
        "implemented": True,
    },
    "BSL159": {
        "name": "CommonModuleInvalidType",
        "description": "Common module invalid type",
        "severity": "ERROR",
        "tags": ["design", "module"],
        "implemented": True,
    },
    "BSL160": {
        "name": "CommonModuleMissingAPI",
        "description": "Common module should have a programming interface",
        "severity": "INFORMATION",
        "tags": ["design", "module", "api"],
        "implemented": True,
    },
    "BSL161": {
        "name": "CommonModuleNameCached",
        "description": 'Missed postfix "Cached"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL162": {
        "name": "CommonModuleNameClient",
        "description": 'Missed postfix "Client"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL163": {
        "name": "CommonModuleNameClientServer",
        "description": 'Missed postfix "ClientServer"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL164": {
        "name": "CommonModuleNameFullAccess",
        "description": 'Missed postfix "FullAccess"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL165": {
        "name": "CommonModuleNameGlobal",
        "description": 'Missed postfix "Global"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL166": {
        "name": "CommonModuleNameGlobalClient",
        "description": 'Global module with postfix "Client"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL167": {
        "name": "CommonModuleNameServerCall",
        "description": 'Missed postfix "ServerCall"',
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL168": {
        "name": "CommonModuleNameWords",
        "description": "Unrecommended common module name",
        "severity": "INFORMATION",
        "tags": ["convention", "naming", "module"],
        "implemented": True,
    },
    "BSL169": {
        "name": "CompilationDirectiveLost",
        "description": "Methods compilation directive",
        "severity": "ERROR",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL170": {
        "name": "CompilationDirectiveNeedLess",
        "description": "Needless compilation directive",
        "severity": "INFORMATION",
        "tags": ["redundant", "directive"],
        "implemented": True,
    },
    "BSL171": {
        "name": "CrazyMultilineString",
        "description": "Crazy multiline literals",
        "severity": "INFORMATION",
        "tags": ["style", "readability"],
        "implemented": True,
    },
    "BSL172": {
        "name": "DataExchangeLoading",
        "description": "There is no check for the attribute DataExchange.Load in the object's "
        "event handler",
        "severity": "WARNING",
        "tags": ["correctness", "data-exchange"],
        "implemented": True,
    },
    "BSL173": {
        "name": "DeletingCollectionItem",
        "description": "Deleting an item when iterating through collection using the operator "
        '"For each ... In ... Do"',
        "severity": "ERROR",
        "tags": ["correctness", "loop"],
        "implemented": True,
    },
    "BSL174": {
        "name": "DenyIncompleteValues",
        "description": "Deny incomplete values for dimensions",
        "severity": "WARNING",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL175": {
        "name": "DeprecatedAttributes8312",
        "description": "Deprecated 8.3.12 platform features.",
        "severity": "INFORMATION",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL176": {
        "name": "DeprecatedMethodCall",
        "description": "Deprecated methods should not be used",
        "severity": "INFORMATION",
        "tags": ["deprecated"],
        "implemented": True,
    },
    "BSL177": {
        "name": "DeprecatedMethods8310",
        "description": "Deprecated client application method.",
        "severity": "INFORMATION",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL178": {
        "name": "DeprecatedMethods8317",
        "description": "Using of deprecated platform 8.3.17 global methods",
        "severity": "INFORMATION",
        "tags": ["deprecated", "compatibility"],
        "implemented": True,
    },
    "BSL179": {
        "name": "DeprecatedTypeManagedForm",
        "description": "Deprecated ManagedForm type",
        "severity": "WARNING",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL180": {
        "name": "DisableSafeMode",
        "description": "Disable safe mode",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL181": {
        "name": "DuplicatedInsertionIntoCollection",
        "description": "Duplicate adding or pasting a value to a collection",
        "severity": "WARNING",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL182": {
        "name": "ExcessiveAutoTestCheck",
        "description": "Excessive AutoTest Check",
        "severity": "INFORMATION",
        "tags": ["testing"],
        "implemented": True,
    },
    "BSL183": {
        "name": "ExecuteExternalCode",
        "description": "Executing of external code on the server",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL184": {
        "name": "ExecuteExternalCodeInCommonModule",
        "description": "Executing of external code in a common module on the server",
        "severity": "WARNING",
        "tags": ["security", "module"],
        "implemented": True,
    },
    "BSL185": {
        "name": "ExternalAppStarting",
        "description": "External applications starting",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL186": {
        "name": "ExtraCommas",
        "description": "Commas without a parameter at the end of a method call",
        "severity": "WARNING",
        "tags": ["syntax", "style"],
        "implemented": True,
    },
    "BSL187": {
        "name": "FieldsFromJoinsWithoutIsNull",
        "description": "No NULL checks for fields from joined tables",
        "severity": "WARNING",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL188": {
        "name": "FileSystemAccess",
        "description": "File system access",
        "severity": "WARNING",
        "tags": ["security", "compatibility"],
        "implemented": True,
    },
    "BSL189": {
        "name": "ForbiddenMetadataName",
        "description": "Metadata object has a forbidden name",
        "severity": "WARNING",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL190": {
        "name": "FormDataToValue",
        "description": "FormDataToValue method call",
        "severity": "WARNING",
        "tags": ["performance", "ui"],
        "implemented": True,
    },
    "BSL191": {
        "name": "FullOuterJoinQuery",
        "description": 'Using of "FULL OUTER JOIN" in queries',
        "severity": "WARNING",
        "tags": ["query", "design"],
        "implemented": True,
    },
    "BSL192": {
        "name": "FunctionNameStartsWithGet",
        "description": 'Function name shouldn\'t start with "Получить"',
        "severity": "INFORMATION",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL193": {
        "name": "FunctionOutParameter",
        "description": "Out function parameter",
        "severity": "WARNING",
        "tags": ["design"],
        "implemented": True,
    },
    "BSL194": {
        "name": "FunctionReturnsSamePrimitive",
        "description": "The function always returns the same primitive value",
        "severity": "ERROR",
        "tags": ["redundant", "design"],
        "implemented": True,
    },
    "BSL195": {
        "name": "GetFormMethod",
        "description": "GetForm method call",
        "severity": "WARNING",
        "tags": ["deprecated", "ui"],
        "implemented": True,
    },
    "BSL196": {
        "name": "GlobalContextMethodCollision8312",
        "description": "Global context method names collision",
        "severity": "ERROR",
        "tags": ["correctness", "compatibility"],
        "implemented": True,
    },
    "BSL197": {
        "name": "IfElseDuplicatedCodeBlock",
        "description": "Duplicated code blocks in If...Then...ElseIf... statements",
        "severity": "WARNING",
        "tags": ["suspicious", "duplicate"],
        "implemented": True,
    },
    "BSL198": {
        "name": "IfElseDuplicatedCondition",
        "description": "Duplicated conditions in If...Then...ElseIf... statements",
        "severity": "WARNING",
        "tags": ["suspicious", "correctness"],
        "implemented": True,
    },
    "BSL199": {
        "name": "IfElseIfEndsWithElse",
        "description": "Else...The...ElseIf... statement should end with Else branch",
        "severity": "INFORMATION",
        "tags": ["design", "robustness"],
        "implemented": True,
    },
    "BSL200": {
        "name": "IncorrectLineBreak",
        "description": "Incorrect expression line break",
        "severity": "INFORMATION",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL201": {
        "name": "IncorrectUseLikeInQuery",
        "description": "Incorrect use of 'LIKE'",
        "severity": "WARNING",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL202": {
        "name": "IncorrectUseOfStrTemplate",
        "description": 'Incorrect use of "StrTemplate"',
        "severity": "ERROR",
        "tags": ["correctness"],
        "implemented": True,
    },
    "BSL203": {
        "name": "InternetAccess",
        "description": "Referring to Internet resources",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL204": {
        "name": "InvalidCharacterInFile",
        "description": "Invalid character",
        "severity": "WARNING",
        "tags": ["correctness", "encoding"],
        "implemented": True,
    },
    "BSL205": {
        "name": "IsInRoleMethod",
        "description": "IsInRole global method call",
        "severity": "WARNING",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL206": {
        "name": "JoinWithSubQuery",
        "description": "Join with sub queries",
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL207": {
        "name": "JoinWithVirtualTable",
        "description": "Join with virtual table",
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL208": {
        "name": "LatinAndCyrillicSymbolInWord",
        "description": "Mixing Latin and Cyrillic characters in one identifier",
        "severity": "WARNING",
        "tags": ["suspicious", "naming"],
        "implemented": True,
    },
    "BSL209": {
        "name": "LogicalOrInJoinQuerySection",
        "description": "Logical 'OR' in 'JOIN' query section",
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL210": {
        "name": "LogicalOrInTheWhereSectionOfQuery",
        "description": 'Using a logical "OR" in the "WHERE" section of a query',
        "severity": "WARNING",
        "tags": ["query", "performance", "standard"],
        "implemented": True,
    },
    "BSL211": {
        "name": "MetadataObjectNameLength",
        "description": "Metadata object names must not exceed the allowed length",
        "severity": "WARNING",
        "tags": ["naming", "convention"],
        "implemented": True,
    },
    "BSL212": {
        "name": "MissedRequiredParameter",
        "description": "Missed a required method parameter",
        "severity": "ERROR",
        "tags": ["correctness"],
        "implemented": True,
    },
    "BSL213": {
        "name": "MissingCommonModuleMethod",
        "description": "Referencing a missing common module method",
        "severity": "ERROR",
        "tags": ["correctness", "module"],
        "implemented": True,
    },
    "BSL214": {
        "name": "MissingEventSubscriptionHandler",
        "description": "Event subscription handler missing",
        "severity": "ERROR",
        "tags": ["correctness", "events"],
        "implemented": True,
    },
    "BSL215": {
        "name": "MissingParameterDescription",
        "description": "Method parameters description are missing",
        "severity": "INFORMATION",
        "tags": ["documentation", "api"],
        "implemented": True,
    },
    "BSL216": {
        "name": "MissingSpace",
        "description": "Missing spaces to the left or right of operators + - * / = % < > <> <= "
        ">=, keywords, and also to the right of , and ;",
        "severity": "INFORMATION",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL217": {
        "name": "MissingTempStorageDeletion",
        "description": "Missing temporary storage data deletion after using",
        "severity": "WARNING",
        "tags": ["resource-management", "memory"],
        "implemented": True,
    },
    "BSL218": {
        "name": "MissingTemporaryFileDeletion",
        "description": "Missing temporary file deletion after using",
        "severity": "WARNING",
        "tags": ["resource-management"],
        "implemented": True,
    },
    "BSL219": {
        "name": "MissingVariablesDescription",
        "description": "All variables declarations must have a description",
        "severity": "INFORMATION",
        "tags": ["documentation", "convention"],
        "implemented": True,
    },
    "BSL220": {
        "name": "MultilineStringInQuery",
        "description": "Multi-line literal in query",
        "severity": "INFORMATION",
        "tags": ["query", "style"],
        "implemented": True,
    },
    "BSL221": {
        "name": "MultilingualStringHasAllDeclaredLanguages",
        "description": "There is a localized text for all languages declared in the configuration",
        "severity": "WARNING",
        "tags": ["localization"],
        "implemented": True,
    },
    "BSL222": {
        "name": "MultilingualStringUsingWithTemplate",
        "description": "Partially localized text is used in the StrTemplate function",
        "severity": "INFORMATION",
        "tags": ["localization", "style"],
        "implemented": True,
    },
    "BSL223": {
        "name": "NestedConstructorsInStructureDeclaration",
        "description": "Nested constructors with parameters in structure declaration",
        "severity": "INFORMATION",
        "tags": ["readability", "design"],
        "implemented": True,
    },
    "BSL224": {
        "name": "NestedFunctionInParameters",
        "description": "Initialization of method and constructor parameters by calling nested "
        "methods",
        "severity": "INFORMATION",
        "tags": ["readability", "brain-overload"],
        "implemented": True,
    },
    "BSL225": {
        "name": "NumberOfValuesInStructureConstructor",
        "description": "Limit on the number of property values passed to the structure constructor",
        "severity": "INFORMATION",
        "tags": ["design", "readability"],
        "implemented": True,
    },
    "BSL226": {
        "name": "OSUsersMethod",
        "description": "Using method OSUsers",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL227": {
        "name": "OneStatementPerLine",
        "description": "One statement per line",
        "severity": "INFORMATION",
        "tags": ["style", "convention"],
        "implemented": True,
    },
    "BSL228": {
        "name": "OrderOfParams",
        "description": "Order of Parameters in method",
        "severity": "WARNING",
        "tags": ["design", "convention"],
        "implemented": True,
    },
    "BSL229": {
        "name": "OrdinaryAppSupport",
        "description": "Ordinary application support",
        "severity": "WARNING",
        "tags": ["compatibility", "ui"],
        "implemented": True,
    },
    "BSL230": {
        "name": "PairingBrokenTransaction",
        "description": 'Violation of pairing using methods "BeginTransaction()" & '
        '"CommitTransaction()" / "RollbackTransaction()"',
        "severity": "ERROR",
        "tags": ["transaction", "correctness"],
        "implemented": True,
    },
    "BSL231": {
        "name": "PrivilegedModuleMethodCall",
        "description": "Accessing privileged module methods",
        "severity": "WARNING",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL232": {
        "name": "ProtectedModule",
        "description": "Protected modules",
        "severity": "INFORMATION",
        "tags": ["design"],
        "implemented": True,
    },
    "BSL233": {
        "name": "PublicMethodsDescription",
        "description": "All public methods must have a description",
        "severity": "INFORMATION",
        "tags": ["documentation", "api"],
        "implemented": True,
    },
    "BSL234": {
        "name": "QueryNestedFieldsByDot",
        "description": "Getting objects nested fields data by dot in database query text",
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL235": {
        "name": "QueryParseError",
        "description": "Query text parsing error",
        "severity": "WARNING",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL236": {
        "name": "QueryToMissingMetadata",
        "description": "Using non-existent metadata in the query",
        "severity": "ERROR",
        "tags": ["query", "correctness"],
        "implemented": True,
    },
    "BSL237": {
        "name": "RedundantAccessToObject",
        "description": "Redundant access to an object",
        "severity": "INFORMATION",
        "tags": ["redundant", "performance"],
        "implemented": True,
    },
    "BSL238": {
        "name": "RefOveruse",
        "description": 'Overuse "Reference" in a query',
        "severity": "INFORMATION",
        "tags": ["performance", "readability"],
        "implemented": True,
    },
    "BSL239": {
        "name": "ReservedParameterNames",
        "description": "Reserved parameter names",
        "severity": "WARNING",
        "tags": ["naming", "suspicious"],
        "implemented": True,
    },
    "BSL240": {
        "name": "RewriteMethodParameter",
        "description": "Rewrite method parameter",
        "severity": "WARNING",
        "tags": ["suspicious", "correctness"],
        "implemented": True,
    },
    "BSL241": {
        "name": "SameMetadataObjectAndChildNames",
        "description": "Same metadata object and child name",
        "severity": "ERROR",
        "tags": ["naming", "design"],
        "implemented": True,
    },
    "BSL242": {
        "name": "ScheduledJobHandler",
        "description": "Scheduled job handler",
        "severity": "ERROR",
        "tags": ["correctness", "scheduled-jobs"],
        "implemented": True,
    },
    "BSL243": {
        "name": "SelfInsertion",
        "description": "Insert a collection into itself",
        "severity": "ERROR",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL244": {
        "name": "ServerCallsInFormEvents",
        "description": "Server calls in form events",
        "severity": "ERROR",
        "tags": ["correctness", "ui", "performance"],
        "implemented": True,
    },
    "BSL245": {
        "name": "ServerSideExportFormMethod",
        "description": "Server-side export form method",
        "severity": "WARNING",
        "tags": ["correctness", "ui"],
        "implemented": True,
    },
    "BSL246": {
        "name": "SetPermissionsForNewObjects",
        "description": "The check box «Set permissions for new objects» should only be "
        "selected for the FullAccess role",
        "severity": "ERROR",
        "tags": ["security", "access-control"],
        "implemented": True,
    },
    "BSL247": {
        "name": "SetPrivilegedMode",
        "description": "Using privileged mode",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL248": {
        "name": "SeveralCompilerDirectives",
        "description": "Erroneous indication of several compilation directives",
        "severity": "ERROR",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL249": {
        "name": "StyleElementConstructors",
        "description": "Style element constructor",
        "severity": "ERROR",
        "tags": ["ui", "design"],
        "implemented": True,
    },
    "BSL250": {
        "name": "TempFilesDir",
        "description": "TempFilesDir() method call",
        "severity": "WARNING",
        "tags": ["standard", "badpractice"],
        "implemented": True,
    },
    "BSL251": {
        "name": "TernaryOperatorUsage",
        "description": "Ternary operator usage",
        "severity": "INFORMATION",
        "tags": ["style", "readability"],
        "implemented": True,
    },
    "BSL252": {
        "name": "ThisObjectAssign",
        "description": "ThisObject assign",
        "severity": "ERROR",
        "tags": ["correctness", "suspicious"],
        "implemented": True,
    },
    "BSL253": {
        "name": "TimeoutsInExternalResources",
        "description": "Timeouts working with external resources",
        "severity": "WARNING",
        "tags": ["robustness", "performance"],
        "implemented": True,
    },
    "BSL254": {
        "name": "TransferringParametersBetweenClientAndServer",
        "description": "Transferring parameters between the client and the server",
        "severity": "WARNING",
        "tags": ["performance", "design"],
        "implemented": True,
    },
    "BSL255": {
        "name": "TryNumber",
        "description": "Cast to number of try catch block",
        "severity": "WARNING",
        "tags": ["error-handling", "suspicious"],
        "implemented": True,
    },
    "BSL256": {
        "name": "Typo",
        "description": "Typo",
        "severity": "INFORMATION",
        "tags": ["convention"],
        "implemented": True,
    },
    "BSL257": {
        "name": "UnaryPlusInConcatenation",
        "description": "Unary Plus sign in string concatenation",
        "severity": "ERROR",
        "tags": ["suspicious", "brainoverload"],
        "implemented": True,
    },
    "BSL258": {
        "name": "UnionAll",
        "description": 'Using keyword "UNION" in queries',
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL259": {
        "name": "UnknownPreprocessorSymbol",
        "description": "Unknown preprocessor symbol",
        "severity": "WARNING",
        "tags": ["correctness", "directive"],
        "implemented": True,
    },
    "BSL260": {
        "name": "UnsafeFindByCode",
        "description": "Unsafe FindByCode() method usage",
        "severity": "WARNING",
        "tags": ["correctness", "robustness"],
        "implemented": True,
    },
    "BSL261": {
        "name": "UnsafeSafeModeMethodCall",
        "description": "Unsafe SafeMode method call",
        "severity": "WARNING",
        "tags": ["security", "correctness"],
        "implemented": True,
    },
    "BSL262": {
        "name": "UsageWriteLogEvent",
        "description": 'Incorrect use of the method "WriteLogEvent"',
        "severity": "INFORMATION",
        "tags": ["standard", "badpractice"],
        "implemented": True,
    },
    "BSL263": {
        "name": "UseLessForEach",
        "description": "Useless collection iteration",
        "severity": "WARNING",
        "tags": ["redundant", "suspicious"],
        "implemented": True,
    },
    "BSL264": {
        "name": "UseSystemInformation",
        "description": "Use of system information",
        "severity": "WARNING",
        "tags": ["security"],
        "implemented": True,
    },
    "BSL265": {
        "name": "UselessTernaryOperator",
        "description": "Useless ternary operator",
        "severity": "INFORMATION",
        "tags": ["redundant", "readability"],
        "implemented": True,
    },
    "BSL266": {
        "name": "UsingCancelParameter",
        "description": 'Using parameter "Cancel"',
        "severity": "WARNING",
        "tags": ["correctness", "events"],
        "implemented": True,
    },
    "BSL267": {
        "name": "UsingExternalCodeTools",
        "description": "Using external code tools",
        "severity": "ERROR",
        "tags": ["standard", "design"],
        "implemented": True,
    },
    "BSL268": {
        "name": "UsingFindElementByString",
        "description": "Using FindByName, FindByCode and FindByNumber",
        "severity": "WARNING",
        "tags": ["performance"],
        "implemented": True,
    },
    "BSL269": {
        "name": "UsingLikeInQuery",
        "description": "Using 'LIKE' in query",
        "severity": "INFORMATION",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL271": {
        "name": "UsingObjectNotAvailableUnix",
        "description": "Using unavailable in Unix objects",
        "severity": "WARNING",
        "tags": ["compatibility"],
        "implemented": True,
    },
    "BSL272": {
        "name": "UsingSynchronousCalls",
        "description": "Using synchronous calls",
        "severity": "WARNING",
        "tags": ["performance", "ui"],
        "implemented": True,
    },
    "BSL273": {
        "name": "VirtualTableCallWithoutParameters",
        "description": "Virtual table call without parameters",
        "severity": "WARNING",
        "tags": ["query", "performance"],
        "implemented": True,
    },
    "BSL274": {
        "name": "WrongDataPathForFormElements",
        "description": "Form fields do not have a data path",
        "severity": "ERROR",
        "tags": ["correctness", "ui"],
        "implemented": True,
    },
    "BSL275": {
        "name": "WrongHttpServiceHandler",
        "description": "Missing handler for http service",
        "severity": "ERROR",
        "tags": ["correctness", "http"],
        "implemented": True,
    },
    "BSL276": {
        "name": "WrongUseFunctionProceedWithCall",
        "description": "Wrong use of ProceedWithCall function",
        "severity": "ERROR",
        "tags": ["correctness", "extensions"],
        "implemented": True,
    },
    "BSL277": {
        "name": "WrongUseOfRollbackTransactionMethod",
        "description": "Not recommended using of RollbackTransaction method",
        "severity": "ERROR",
        "tags": ["transaction", "error-handling"],
        "implemented": True,
    },
    "BSL278": {
        "name": "WrongWebServiceHandler",
        "description": "Wrong handler for web service",
        "severity": "ERROR",
        "tags": ["correctness", "web-service"],
        "implemented": True,
    },
    "BSL279": {
        "name": "YoLetterUsage",
        "description": 'Using Russian character "yo" ("ё") in code',
        "severity": "INFORMATION",
        "tags": ["style", "convention"],
        "implemented": True,
    },
}


# ---------------------------------------------------------------------------
# Russian descriptions (taken from BSL Language Server ru-locale)
# Keys that are absent will fall back to the English description in RULE_METADATA.
# ---------------------------------------------------------------------------

RULE_DESCRIPTIONS_RU: dict[str, str] = {
    "BSL001": "Ошибка разбора исходного кода",
    "BSL002": "Ограничение на размер метода",
    "BSL003": "Неэкспортные методы в областях ПрограммныйИнтерфейс и СлужебныйПрограммныйИнтерфейс",
    "BSL004": "Пустой блок кода",
    "BSL005": "Хранение ip-адресов в коде",
    "BSL006": "Хранение путей к файлам в коде",
    "BSL007": "Неиспользуемая локальная переменная",
    "BSL008": "Метод не должен содержать много возвратов",
    "BSL009": "Присвоение переменной самой себе",
    "BSL011": "Когнитивная сложность",
    "BSL012": "Хранение конфиденциальной информации в коде",
    "BSL013": "Закомментированный фрагмент кода",
    "BSL014": "Ограничение на длину строки",
    "BSL015": "Ограничение на количество не обязательных параметров метода",
    "BSL016": "Нестандартные разделы модуля",
    "BSL017": "Экспортные методы в модулях команд и общих команд",
    "BSL019": "Цикломатическая сложность",
    "BSL020": "Управляющие конструкции не должны быть вложены слишком глубоко",
    "BSL022": "Использование модальных окон",
    "BSL023": "Использование служебных тегов",
    "BSL024": "Пробел в начале комментария",
    "BSL025": "Пустой оператор",
    "BSL026": "Область не должна быть пустой",
    "BSL027": 'Оператор "Перейти" не должен использоваться',
    "BSL028": 'Конструкция "Попытка...Исключение...КонецПопытки" не содержит кода в исключении',
    "BSL029": "Магические числа",
    "BSL030": 'Выражение должно заканчиваться символом ";"',
    "BSL031": "Ограничение на количество параметров метода",
    "BSL032": "Функция должна содержать возврат",
    "BSL033": "Выполнение запроса в цикле",
    "BSL035": "Повторное использование строкового литерала",
    "BSL036": 'Использование сложных выражений в условии оператора "Если"',
    "BSL039": "Вложенный тернарный оператор",
    "BSL040": 'Использование устаревшего свойства "ЭтаФорма"',
    "BSL041": 'Ограничение на использование устаревшего метода "Сообщить"',
    "BSL042": "Неиспользуемый локальный метод",
    "BSL047": "Магические даты",
    "BSL051": "Недостижимый код",
    "BSL052": 'Одинаковые выражения слева и справа от "foo" оператора',
    "BSL054": "Запрет экспортных глобальных переменных модуля",
    "BSL055": "Подряд идущие пустые строки",
    "BSL060": "Двойные отрицания",
    "BSL062": "Неиспользуемый параметр",
    "BSL064": "Процедура не должна возвращать значение",
    "BSL065": "Отсутствует описание возвращаемого значения функции",
    "BSL066": 'Использование устаревшего метода "Найти"',
    "BSL077": "Использование 'ВЫБРАТЬ ПЕРВЫЕ' без 'УПОРЯДОЧИТЬ ПО'",
    "BSL097": 'Использование устаревшего метода "ТекущаяДата"',
    "BSL131": "Повторяющиеся разделы модуля",
    "BSL148": "Все возможные пути выполнения функции должны содержать оператор Возврат",
    "BSL149": "Назначение псевдонимов выбранным полям в запросе",
    "BSL150": "Запрещенные слова",
    "BSL151": "Нарушение правил работы с транзакциями для метода 'НачатьТранзакцию'",
    "BSL152": "Кеширование программного интерфейса",
    "BSL153": "Каноническое написание ключевых слов",
    "BSL154": "После вызова асинхронного метода есть строки кода",
    "BSL155": "Определения методов должны размещаться перед операторами тела модуля",
    "BSL156": "Код расположен вне области",
    "BSL157": "Нарушение правил работы с транзакциями для метода 'ЗафиксироватьТранзакцию'",
    "BSL158": "Присвоение общему модулю",
    "BSL159": "Общий модуль недопустимого типа",
    "BSL160": "Общий модуль должен иметь программный интерфейс",
    "BSL161": 'Пропущен постфикс "ПовтИсп"',
    "BSL162": 'Пропущен постфикс "Клиент"',
    "BSL163": 'Пропущен постфикс "КлиентСервер"',
    "BSL164": 'Пропущен постфикс "ПолныеПрава"',
    "BSL165": 'Пропущен постфикс "Глобальный"',
    "BSL166": 'Глобальный модуль с постфиксом "Клиент"',
    "BSL167": 'Пропущен постфикс "ВызовСервера"',
    "BSL168": "Нерекомендуемое имя общего модуля",
    "BSL169": "Директивы компиляции методов",
    "BSL170": "Лишняя директива компиляции",
    "BSL171": "Безумные многострочные литералы",
    "BSL172": "Отсутствует проверка признака ОбменДанными.Загрузка в обработчике событий объекта",
    "BSL173": 'Удаление элемента при обходе коллекции посредством оператора "Для каждого ... Из ... '
    'Цикл"',
    "BSL174": "Запрет незаполненных значений у измерений регистров",
    "BSL175": "Устаревшие объекты платформы 8.3.12",
    "BSL176": "Устаревшие методы не должны использоваться",
    "BSL177": "Использование устаревшего метода клиентского приложения",
    "BSL178": "Использование устаревших глобальных методов платформы 8.3.17",
    "BSL179": 'Устаревшее использование типа "УправляемаяФорма"',
    "BSL180": "Отключение безопасного режима",
    "BSL181": "Повторное добавление/вставка значений в коллекцию",
    "BSL182": "Избыточная проверка параметра АвтоТест",
    "BSL183": "Выполнение произвольного кода на сервере",
    "BSL184": "Выполнение произвольного кода в общем модуле на сервере",
    "BSL185": "Запуск внешних приложений",
    "BSL186": "Запятые без указания параметра в конце вызова метода",
    "BSL187": "Отсутствие проверки на NULL для полей из присоединяемых таблиц",
    "BSL188": "Доступ к файловой системе",
    "BSL189": "Объекту метаданных присвоено запрещенное имя",
    "BSL190": "Использование метода ДанныеФормыВЗначение",
    "BSL191": 'Использование конструкции "ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ" в запросах',
    "BSL192": 'Имя функции не должно начинаться с "Получить"',
    "BSL193": "Исходящий параметр функции",
    "BSL194": "Функция всегда возвращает одно и то же примитивное значение",
    "BSL195": "Использование метода ПолучитьФорму",
    "BSL196": "Конфликт имен методов с методами глобального контекста",
    "BSL197": "Повторяющиеся блоки кода в синтаксической конструкции Если...Тогда...ИначеЕсли...",
    "BSL198": "Повторяющиеся условия в синтаксической конструкции Если...Тогда...ИначеЕсли...",
    "BSL199": "Использование синтаксической конструкции Если...Тогда...ИначеЕсли...",
    "BSL200": "Неправильный перенос выражения",
    "BSL201": "Некорректное использование 'ПОДОБНО'",
    "BSL202": 'Неверное использование "СтрШаблон"',
    "BSL203": "Обращение к Интернет-ресурсам",
    "BSL204": "Недопустимый символ",
    "BSL205": "Использование метода РольДоступна",
    "BSL206": "Соединение с вложенными запросами",
    "BSL207": "Соединение с виртуальными таблицами",
    "BSL208": "Смешивание латинских и кириллических символов в одном идентификаторе",
    "BSL209": "Логическое 'ИЛИ' в соединениях запроса",
    "BSL210": 'Использование логического "ИЛИ" в секции "ГДЕ" запроса',
    "BSL211": "Имена объектов метаданных не должны превышать допустимой длины наименования",
    "BSL212": "Пропущен обязательный параметр метода",
    "BSL213": "Обращение к отсутствующему методу общего модуля",
    "BSL214": "Отсутствует обработчик подписки на событие",
    "BSL215": "Отсутствует описание параметров метода",
    "BSL216": "Пропущены пробелы слева или справа от операторов `+ - * / = % < > <> <= >=`, от "
    "ключевых слов, а так же справа от `,` и `;`",
    "BSL217": "Отсутствует удаление данных из временного хранилища после использования",
    "BSL218": "Отсутствует удаление временного файла после использования",
    "BSL219": "Все объявления переменных должны иметь описание",
    "BSL220": "Многострочный литерал в запросе",
    "BSL221": "Есть локализованный текст для всех заявленных в конфигурации языков",
    "BSL222": "Частично локализованный текст используется в функции СтрШаблон",
    "BSL223": "Использование конструкторов с параметрами при объявлении структуры",
    "BSL224": "Инициализация параметров методов и конструкторов вызовом вложенных методов",
    "BSL225": "Ограничение на количество значений свойств, передаваемых в конструктор структуры",
    "BSL226": "Использование метода ПользователиОС",
    "BSL227": "Одно выражение в одной строке",
    "BSL228": "Порядок параметров метода",
    "BSL229": "Поддержка обычного приложения",
    "BSL230": 'Нарушение парности использования методов "НачатьТранзакцию()" и '
    '"ЗафиксироватьТранзакцию()" / "ОтменитьТранзакцию()"',
    "BSL231": "Обращение к методам привилегированных модулей",
    "BSL232": "Защищенные модули",
    "BSL233": "Все методы программного интерфейса должны иметь описание",
    "BSL234": "Разыменование ссылочных полей запроса через точку",
    "BSL235": "Ошибка разбора текста запроса",
    "BSL236": "Обращение к несуществующим метаданным в запросе",
    "BSL237": "Избыточное обращение к объекту",
    "BSL238": 'Избыточное использование "Ссылка" в запросе',
    "BSL239": "Зарезервированные имена параметров",
    "BSL240": "Перезапись параметров метода",
    "BSL241": "Совпадает имя объекта метаданного и его дочернего",
    "BSL242": "Обработчик регламентного задания",
    "BSL243": "Вставка коллекции в саму себя",
    "BSL244": "Серверные вызовы в событиях форм",
    "BSL245": "Серверный экспортный метод формы",
    "BSL246": "Флажок «Устанавливать права для новых объектов» должен быть установлен только у роли "
    "ПолныеПрава",
    "BSL247": "Использование привилегированного режима",
    "BSL248": "Ошибочное указание нескольких директив компиляции",
    "BSL249": "Конструктор элемента стиля",
    "BSL250": "Вызов функции КаталогВременныхФайлов()",
    "BSL251": "Использование тернарного оператора",
    "BSL252": "Присвоение значения свойству ЭтотОбъект",
    "BSL253": "Таймауты при работе с внешними ресурсами",
    "BSL254": "Передача параметров между клиентом и сервером",
    "BSL255": "Приведение к числу в попытке",
    "BSL256": "Опечатка",
    "BSL257": "Унарный плюс в конкатенации строк",
    "BSL258": 'Использование ключевого слова "ОБЪЕДИНИТЬ" в запросах',
    "BSL259": "Неизвестный символ препроцессора",
    "BSL260": "Небезопасное использование метода НайтиПоКоду()",
    "BSL261": "Небезопасное использование функции БезопасныйРежим()",
    "BSL262": 'Неверное использование метода "ЗаписьЖурналаРегистрации"',
    "BSL263": "Бесполезный перебор коллекции",
    "BSL264": "Использование системной информации",
    "BSL265": "Бесполезный тернарный оператор",
    "BSL266": 'Работа с параметром "Отказ"',
    "BSL267": "Использование возможностей выполнения внешнего кода",
    "BSL268": 'Использование методов "НайтиПоНаименованию", "НайтиПоКоду" и "НайтиПоНомеру"',
    "BSL269": "Использование 'ПОДОБНО' в запросе",
    "BSL271": "Использование объектов недоступных в Unix системах",
    "BSL272": "Использование синхронных вызовов",
    "BSL273": "Обращение к виртуальной таблице без параметров",
    "BSL274": "У полей формы не указан путь к данным",
    "BSL275": "Неверно задан обработчик метода http-сервиса",
    "BSL276": "Некорректное использование функции ПродолжитьВызов()",
    "BSL277": "Некорректное использование метода ОтменитьТранзакцию()",
    "BSL278": "Неверно задан обработчик операции web-сервиса",
    "BSL279": 'Использование буквы "ё" в текстах модулей',
}

# Canonical BSLLS ``diagnosticMessage`` strings for rules where the message is
# more specific than the short diagnostic name. Public JSON/MCP/SARIF surfaces
# expose this next to the local, occurrence-specific ``message`` so agents can
# reason from the same rule wording as BSLLS without losing local details.
RULE_MESSAGES_RU: dict[str, str] = {
    "BSL175.deprecatedAttributeMessage": 'Атрибут "%s" устарел. Вместо него стоит использовать %s',
    "BSL175.deprecatedMethodsMessage": 'Метод "%s" устарел. Вместо него стоит использовать "%s"',
    "BSL175.deprecatedEnumNameMessage": 'Используется старое наименование "%s". Вместо него необходимо использовать "%s"',
    "BSL175.deprecatedGlobalMethodsMessage": 'Метод "%s" устарел и больше не используется',
    "BSL175": "%s",
    "BSL014": "Длина строки %s превышает максимально допустимую %s",
    "BSL022": "Вместо модального метода `%s` необходимо использовать `%s`",
    "BSL023": 'Найден служебный тег "%s"',
    "BSL026": 'Область "%s" не содержит функций или процедур',
    "BSL029": 'Создайте константу с понятным названием, присвойте ей значение "%s" и используйте эту константу вместо магического числа.',
    "BSL035": "Необходимо избавиться от многократного использования строкового литерала %s",
    "BSL047": 'Создайте переменную с понятным названием, присвойте ей значение "%s" и используйте эту константу вместо магической даты.',
    "BSL131": 'Нужно удалить дубли раздела "%s"',
    "BSL149": 'Полю "%s" не назначен псевдоним или пропущено ключевое слово КАК',
    "BSL153": 'Ключевое слово "%s" написано не канонически',
    "BSL173": 'Не следует удалять элементы коллекции "%s" при ее обходе оператором "Для каждого ... Из ... Цикл"',
    "BSL181": "Проверьте повторную вставку %s в коллекцию %s",
    "BSL216": "%s от '%s' не хватает пробела",
    "BSL221": "Добавьте строки для языков: %s",
    "BSL222": "Добавьте строки для языков: %s",
    "BSL224": 'Уберите инициализацию параметров %s "%s" вложенными методами',
    "BSL249": "Замените конструктор %s на получение элемента стиля",
    "BSL254": 'Установите модификатор "Знач" для параметра %s метода %s',
    "BSL256": 'Возможная опечатка в "%s"',
    "BSL259": 'Неизвестный символ препроцессора "%s"',
    "BSL268": 'Не следует использовать  метод "%s" и поиск по строке',
    "BSL065.isProcedure": "Удалите описание возвращаемого значения для процедуры",
    "BSL204.diagnosticMessageDash": 'Нужно исправить на правильный символ "-"',
    "BSL204.diagnosticMessageSpace": "Нужно заменить символ неразрывного пробела на обычный пробел",
    "BSL215.missingDescription": 'Необходимо добавить описание параметра "%s"',
    "BSL215.emptyDescription": 'Необходимо добавить описание типа параметра "%s"',
    "BSL215.missingInSignature": 'Необходимо удалить описания параметров "%s", отсутствующих в сигнатуре метода',
    "BSL215.wrongOrder": "Необходимо исправить порядок описаний параметров",
    "BSL224.diagnosticMessageWithoutName": "Уберите инициализацию параметров %s вложенными методами",
    "BSL262.wrongNumberMessage": "Неверное число параметров метода",
    "BSL262.noSecondParameter": 'Не указан 2й параметр с типом "УровеньЖурналаРегистрации"',
    "BSL262.noComment": 'Не указан 5й параметр "Комментарий"',
    "BSL262.noDetailErrorDescription": 'В тексте комментария нет вызова "ПодробноеПредставлениеОшибки(ИнформацияОбОшибке())"',
    "BSL262.noErrorLogLevelInsideExceptBlock": 'Нужно указывать уровень "Ошибка" при записи в журнал регистрации внутри блока Исключение-КонецПопытки',
    "BSL002": 'Длина метода "%s" равна %s, что больше установленного лимита в %s строк',
    "BSL003": 'Переместите неэкспортный метод "%s" из области "%s"',
    "BSL008": 'Сократите количество возвратов в методе "%s" с "%s" до максимально допустимого "%s"',
    "BSL011": 'Уменьшите когнитивную сложность "%s" с %s до %s',
    "BSL015": "Уменьшите количество необязательных параметров c %s до допустимого %s",
    "BSL019": 'Уменьшите цикломатическую сложность "%s" с %s до %s',
    "BSL031": "Уменьшите количество параметров c %s до допустимого %s",
    "BSL042": 'Метод "%s" не вызывается в теле модуля',
    "BSL062": 'Уберите неиспользуемый параметр "%s"',
    "BSL001": "Ошибка разбора исходного кода. %s",
    "BSL004": "Наполните блок кодом или удалите его",
    "BSL005": "Используется хранение в коде ip-адреса",
    "BSL006": "Используется хранение в коде пути к файлу",
    "BSL007": "Удалите неиспользуемую переменную %s",
    "BSL009": "Удалите бесполезное присваивание переменной самой себе",
    "BSL012": "Используется хранение конфиденциальной информации в коде",
    "BSL013": "Программные модули не должны иметь закомментированных фрагментов кода",
    "BSL017": "Не следует размещать экспортные методы в модулях команд и общих команд",
    "BSL020": "Превышен допустимый уровень вложенности управляющих конструкций",
    "BSL024": "Между символами комментария '//' и самим текстом комментария должен быть пробел.",
    "BSL025": 'Удалите ";"',
    "BSL027": 'Оператор "Перейти" не должен использоваться',
    "BSL028": 'Отсутствует код в блоке "Исключение"',
    "BSL030": "Пропущена точка с запятой в конце выражения",
    "BSL032": 'Функция не содержит "Возврат"',
    "BSL033": "Необходимо модифицировать запрос для поддержки множества значений и удалить цикл",
    "BSL036": "Выделите условие оператора Если в отдельный метод или переменную",
    "BSL039": "Не рекомендуется использовать вложенный тернарный оператор",
    "BSL040": 'Вместо устаревшего свойства "ЭтаФорма" следует использовать "ЭтотОбъект"',
    "BSL041": 'Не следует использовать устаревший метод "Сообщить"',
    "BSL051": "Исправьте алгоритм, т.к. этот код никогда не будет исполнен",
    "BSL052": 'Слева и справа от оператора "%s" находятся одинаковые подвыражения: "%s"',
    "BSL054": (
        "Не рекомендуется использовать экспортные переменные. Это может стать источником "
        "трудновоспроизводимых ошибок"
    ),
    "BSL055": "Удалите лишние последовательные пустые строки",
    "BSL060": "Использование двойных отрицаний усложняет понимание кода",
    "BSL064": 'Процедура содержит "Возврат" со значением',
    "BSL065": "Добавьте описание возвращаемого значения функции",
    "BSL066": 'Используйте "СтрНайти" вместо устаревшего "Найти"',
    "BSL077": "Нужно изменить запрос, добавив упорядочивание",
    "BSL097": 'Используйте "ТекущаяДатаСеанса" вместо устаревшего "ТекущаяДата"',
    "BSL148": "Не все пути выполнения функции возвращают значение",
    "BSL151": (
        "Метод 'НачатьТранзакцию' должен быть за пределами блока 'Попытка-Исключение' "
        "непосредственно перед оператором 'Попытка'"
    ),
    "BSL152": "Переместите методы в Служебный Программный интерфейс",
    "BSL154": "Проверьте корректность выполнения кода после асинхронного метода <%s>",
    "BSL155": "Необходимо разместить тело модуля после определения методов",
    "BSL156": "Переместите код в область",
    "BSL157": (
        "Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед "
        "оператором 'Исключение'"
    ),
    "BSL158": "Переименуйте переменную, т.к %s - это имя общего модуля",
    "BSL159": "Общий модуль недопустимого типа",
    "BSL160": (
        "Общий модуль должен иметь хотя бы один экспортный метод, а также область "
        '"ПрограммныйИнтерфейс" или "СлужебныйПрограммныйИнтерфейс".'
    ),
    "BSL161": 'Добавьте постфикс "ПовтИсп" к имени общего модуля',
    "BSL162": 'Добавьте постфикс "Клиент" к имени общего модуля',
    "BSL163": 'Добавьте постфикс "КлиентСервер" к имени общего модуля',
    "BSL164": 'Добавьте постфикс "ПолныеПрава" к имени общего модуля',
    "BSL165": 'Добавьте постфикс "Глобальный" к имени общего модуля',
    "BSL166": 'Удалите постфикс "Клиент" у глобального модуля',
    "BSL167": 'Добавьте постфикс "ВызовСервера" к имени общего модуля',
    "BSL168": "Переименуйте общий модуль",
    "BSL169": 'Укажите директиву компиляции у метода "%s"',
    "BSL170": "Удалите директиву компиляции",
    "BSL171": (
        "Воспользуйтесь 'классическим' способом создания многострочных литералов, используя "
        "`|` и `+`"
    ),
    "BSL172": "Добавьте проверку признака ОбменДанными.Загрузка в самом начале процедуры",
    "BSL174": ('Не указан флаг "Запрет незаполненных значений" у измерения "%s" метаданного "%s"'),
    "BSL176": 'Удалите обращение к устаревшему "%s".%s',
    "BSL179": 'Замените устаревшее использование типа "УправляемаяФорма"',
    "BSL180": "Проверьте отключение безопасного режима",
    "BSL182": 'Удалите проверку параметра "АвтоТест"',
    "BSL183": "Запрещено выполнение произвольного кода на сервере",
    "BSL184": (
        "Выполнение произвольного кода в общем модуле на сервере является потенциальной "
        "уязвимостью "
    ),
    "BSL185": "Проверьте запуск внешнего приложения",
    "BSL186": "Не используйте запятые для параметров по умолчанию в конце вызова метода.",
    "BSL187": (
        "Для полей из соединений добавьте проверки полей через Есть NULL или используйте "
        "приведение через ЕстьNULL или используйте внутреннее соединение"
    ),
    "BSL188": "Проверьте обращение к файловой системе",
    "BSL189": "Запрещено использовать имя `%s` для `%s`",
    "BSL190": "Не рекомендуемое использование метода ДанныеФормыВЗначение",
    "BSL191": 'Перепишите запрос без использования "ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ"',
    "BSL192": 'Уберите слово "Получить" из имени функции',
    "BSL193": "Параметр функции не должен возвращать значение",
    "BSL194": "Проверьте правильность возврата одного и того же примитивного значения в функции",
    "BSL195": "Не рекомендуемое использование метода ПолучитьФорму",
    "BSL196": 'Метод "%s" должен быть удален или переименован',
    "BSL197": (
        'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся блоки кода'
    ),
    "BSL198": (
        'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся условия'
    ),
    "BSL199": (
        'Синтаксическая конструкция вида "Если...Тогда...ИначеЕсли..." должна содержать ветвь '
        '"Иначе".'
    ),
    "BSL200": "Проверьте правильность переноса операндов, операторов и параметров",
    "BSL201": "Нужно исправить выражение в соответствии со стандартом",
    "BSL202": 'Исправьте передачу параметров при вызове метода "СтрШаблон"',
    "BSL203": "Проверьте обращение к Интернет-ресурсам",
    "BSL204": "Нужно исправить недопустимый символ",
    "BSL205": "Для проверки прав доступа в коде следует использовать метод ПравоДоступа",
    "BSL206": "Не следует использовать соединения с вложенными запросами",
    "BSL207": "Не следует использовать соединения с виртуальными таблицами",
    "BSL208": "Нельзя использовать латинские и кириллические символы в одном идентификаторе",
    "BSL209": "Обнаружен оператор 'ИЛИ' в условии соединения",
    "BSL210": 'Не следует использовать логическое "ИЛИ" в секции "ГДЕ" запроса',
    "BSL211": "Переименуйте объект конфигурации `%s` так, чтобы длина наименования была меньше %s",
    "BSL212": "Укажите обязательный параметр %s",
    "BSL213": "Метод %s общего модуля %s не существует",
    "BSL214": 'Заполните обработчик подписки на событие "%s"',
    "BSL215": "Необходимо добавить описание всех параметров метода",
    "BSL217": (
        "Нужно добавить удаление данных из временного хранилища после использования, вызвав "
        '"УдалитьИзВременногоХранилища"'
    ),
    "BSL218": "Нужно добавить удаление временного файла после использования",
    "BSL219": "Добавьте описание переменной",
    "BSL220": "Проверьте корректность многострочного литерала",
    "BSL223": "Не используйте конструкторы с параметрами при объявлении структуры",
    "BSL225": "Уменьшите количество значений свойств, передаваемых в конструктор структуры",
    "BSL226": "Проверить потенциально вредоносное использование метода ПользователиОС",
    "BSL227": "Перенесите выражение на новую строку",
    "BSL228": "Переместите необязательные параметры после обязательных",
    "BSL229": "Поддержка обычного приложения",
    "BSL231": "Проверьте обращение к методу %s привилегированного модуля",
    "BSL232": "Исходный код модуля отсутствует из-за защиты паролем. %s",
    "BSL233": "Добавьте описание метода программного интерфейса",
    "BSL234": "Обнаружено разыменование ссылочного поля",
    "BSL235": "Текст запроса должен быть корректным и открываться конструктором запросов",
    "BSL237": (
        "Избавьтесь от избыточного обращения внутри модуля через его имя или псевдоним ЭтотОбъект"
    ),
    "BSL238": 'Избавьтесь от получения поля "Ссылка" в запросе.',
    "BSL239": 'Переименуйте параметр "%s" так, чтобы он не совпадал с зарезервированным словом.',
    "BSL240": "Параметр %s перезаписывается без использования",
    "BSL241": "Измените имя `%s`, чтобы оно не совпадало с родительским `%s`",
    "BSL242": (
        'Укажите существующий обработчик вместо несуществующего "%s" у регламентного задания "%s"'
    ),
    "BSL243": "Удалите вставку коллекции в саму себя",
    "BSL244": (
        "В событиях ПриАктивизацииСтроки и НачалоВыбора не должно быть вызовов серверных "
        'процедур. Процедура "%s" выполняется на сервере, что может привести к проблемам.'
    ),
    "BSL245": "Запрещено создавать серверные экспортные методы в форме",
    "BSL246": 'У роли "%s" установлен флажок «Устанавливать права для новых объектов»',
    "BSL247": "Проверьте установку привилегированного режима",
    "BSL248": "Указано несколько директив компиляции",
    "BSL250": "Не рекомендуемый вызов функции КаталогВременныхФайлов()",
    "BSL251": "Используйте конструкцию Если-Иначе вместо тернарного оператора",
    "BSL252": "Свойство ЭтотОбъект доступно только для чтения",
    "BSL253": "Не указан таймаут при работе с внешним ресурсом",
    "BSL255": "Не следует использовать исключения для приведения значения к типу",
    "BSL257": "Унарный плюс в конкатенации строк потенциально приводит к ошибке времени выполнения",
    "BSL258": "Замените конструкцию ОБЪЕДИНИТЬ на ОБЪЕДИНИТЬ ВСЕ",
    "BSL260": "Небезопасное использование метода НайтиПоКоду()",
    "BSL261": "Используйте явное сравнение с Булево при вызове БезопасныйРежим()",
    "BSL262": 'Исправьте передачу неверных параметров в методе "ЗаписьЖурналаРегистрации"',
    "BSL263": "Итератор не используется в теле цикла",
    "BSL264": "Избавьтесь от использования объекта `СистемнаяИнформация`",
    "BSL265": "Бесполезный тернарный оператор",
    "BSL266": "Не следует присваивать параметру Отказ значение отличное от Истина",
    "BSL267": "Запрещено использование возможности выполнения внешнего кода",
    "BSL269": "Измените выражение, чтобы не использовать 'ПОДОБНО'",
    "BSL271": 'Проверить, что задействованы аналоги "%s" при работе в Unix-клиенте.',
    "BSL273": "Не следует использовать виртуальные таблицы без параметров",
    "BSL274": 'Не указан путь к данным у реквизита формы "%s". Форма "%s".',
    "BSL275": (
        'Создайте функцию-обработчик "%s" или исправьте некорректный обработчик http-сервиса "%s"'
    ),
    "BSL276": (
        "Использовать функцию ПродолжитьВызов() можно только в расширениях и только в методах "
        "с аннотацией &Вместо."
    ),
    "BSL277": "Метод ОтменитьТранзакцию() должен быть в попытке и первым методом блока исключения",
    "BSL279": 'В текстах модулях не допускается использовать букву "Ё".',
}


RULE_MESSAGES_EN: dict[str, str] = {
    "BSL199": '"If...Then...ElseIf" statement should have "Else" branch.',
    "BSL223": "Remove constructor with parameters from structure declaration",
    "BSL175.deprecatedAttributeMessage": '"%s" attribute is deprecated. You should use %s',
    "BSL175.deprecatedMethodsMessage": '"%s" method is deprecated. You should use "%s"',
    "BSL175.deprecatedEnumNameMessage": 'Deprecated enum name "%s". You should use "%s" instead.',
    "BSL175.deprecatedGlobalMethodsMessage": '"%s" global method is deprecated. You should not use it.',
    "BSL001": "Error parsing source code. %s",
    "BSL002": 'Method "%s" has %d lines, which is greater than the %d lines authorized',
    "BSL003": 'Move non export method "%s" from "%s" region',
    "BSL004": "Fill code block or remove it",
    "BSL005": "Detected storage of ip address in code",
    "BSL006": "Detected storage of file path in code",
    "BSL007": "Remove unused variable %s",
    "BSL008": 'Reduce the number of returns of "%s" method "%s", down to the maximum allowed "%s"',
    "BSL009": "Remove useless self-assignment",
    "BSL011": 'Reduce cognitive complexity of "%s" from %d to %d',
    "BSL012": "The storage of confidential information in the code is used",
    "BSL013": "Modules must not have commented out code",
    "BSL014": "String length %s exceeded maximum %s",
    "BSL015": "Reduce the number of optional parameters from %s to allowed %s",
    "BSL016": 'Delete non-standard region "%s"',
    "BSL017": "You should not place export methods in command and general command modules",
    "BSL019": 'Reduce cyclomatic complexity of "%s" from %d to %d',
    "BSL020": 'Control flow statements "if", "for", "while", "switch" and "try" should not be nested too deeply',
    "BSL022": "Instead of the modal method `%s`, use `%s`",
    "BSL023": 'Found service tag "%s"',
    "BSL024": "There must be a space between the comment characters '//' and the comment text.",
    "BSL025": 'Remove ";"',
    "BSL026": 'The region "%s" does not contain functions.',
    "BSL027": '"Goto" statement should not be used',
    "BSL028": "Missing code in Raise block",
    "BSL029": 'Assign this magic number "%s" to a well-named constant, and use the constant instead.',
    "BSL030": "Missed semicolon at the end of statement",
    "BSL031": "Reduce the number of parameters from %s to allowed %s",
    "BSL032": 'Function doesn\'t have a "Return" statement',
    "BSL033": "Modify query to support multiple values and remove cycle",
    "BSL035": "Need to get rid of reuse of string literal %s",
    "BSL036": "Extract If condition to a separate method or variable",
    "BSL039": "It is not recommended to use a nested ternary operator",
    "BSL040": 'Instead of the obsolete property "ThisForm" should use "ThisObject"',
    "BSL041": 'Don\'t use deprecated method "Message"',
    "BSL042": 'Method "%s" is not called in the module',
    "BSL047": 'Assign this magic number "%s" to a well-named constant, and use the constant instead.',
    "BSL051": "Correct the algorithm because this code will never be executed",
    "BSL052": 'There are identical sub-expressions to the left and to the right of the "%s" operator: "%s"',
    "BSL054": "It is recommended not to use global variables. They often might cause issues that cannot be easily located",
    "BSL055": "Modules must not have consecutive empty lines",
    "BSL060": "Using double negatives complicates understanding of code",
    "BSL062": 'Remove unused parameter "%s"',
    "BSL064": 'Procedure has a "Return" with a value',
    "BSL065": "Add description for returned value function",
    "BSL065.isProcedure": "Remove returned values description for procedure",
    "BSL066": 'Use "StrFind" instead of deprecated "Find"',
    "BSL077": "Modify your query by adding ordering",
    "BSL097": 'Use "CurrentSessionDate" instead of deprecated "CurrentDate"',
    "BSL131": 'Delete duplicates of region "%s"',
    "BSL148": "Not all execution paths return a value",
    "BSL149": 'The field "%s" has no alias assigned or the AS keyword is missing',
    "BSL150": "Prohibited word found <%s>.",
    "BSL151": "The 'BeginTransaction' method should be outside the 'Try-Exception' block immediately before the 'Try' statement",
    "BSL152": "Move methods to private region",
    "BSL153": 'Keyword "%s" is not written canonically',
    "BSL154": "Check the code after calling the asynchronous method <%s>",
    "BSL155": "It is necessary to place the module body after defining the methods",
    "BSL156": "Move code to region",
    "BSL157": "The 'CommitTransaction' method should be the last in the 'Try' block before the 'Exception' statement",
    "BSL158": "Rename variable, %s is a common module name",
    "BSL159": "Common module invalid type",
    "BSL160": 'A common module should have at least one export method, and "ProgramInterface" or "ServiceProgramInterface" area.',
    "BSL161": 'Add postfix "Cached" to the common module name',
    "BSL162": 'Add postfix "Client" to the common module name',
    "BSL163": 'Add postfix "ClientServer" to the common module name',
    "BSL164": 'Add postfix "FullAccess" to the common module name',
    "BSL165": 'Add postfix "Global" to the common module name',
    "BSL166": 'Remove postfix "Client"',
    "BSL167": 'Add postfix "ServerCall" to the common module name',
    "BSL168": "Rename common module",
    "BSL169": 'Add compilation directive to method "%s"',
    "BSL170": "Remove compilation directive",
    "BSL171": "Use the 'classic' way of creating multi-line literals, using `|` and `+`",
    "BSL172": "Add a check for the attribute ExchangeData.Load at the very beginning of the procedure",
    "BSL173": 'Don\'t delete elements of collection "%s" when iterating through collection using the operator "For each ... In ... Do"',
    "BSL174": 'The "Deny incomplete values" flag is not specified for the "%s" dimension of the "%s" metadata',
    "BSL175": "%s",
    "BSL176": 'Remove access to deprecated "%s".%s',
    "BSL179": "Replace deprecated ManagedForm type to ClientApplicationForm",
    "BSL180": "Check the safe mode setting",
    "BSL181": "Check the re-addition of %s to the collection with name %s ",
    "BSL182": 'Delete parameter "AutoTest" check',
    "BSL183": "It is forbidden to execute external code on the server",
    "BSL184": "Execution of external code in a common module on a server is a potential vulnerability",
    "BSL185": "Check the launch of an external application",
    "BSL186": "Do not use commas for default parameters at the end of a method call.",
    "BSL187": "For fields from connections add field checks via NULL or use conversion via ISNULL or use inner connection",
    "BSL188": "Check access to the file system",
    "BSL189": "Forbidden to use name `%s` for `%s`",
    "BSL190": "Not recommended using of method FormDataToValue",
    "BSL191": 'Rewrite query without using "FULL OUTER JOIN"',
    "BSL192": 'Remove the word "Получить" from the function name',
    "BSL193": "Function parameter shouldn't return a value",
    "BSL194": "Check that the same primitive value is returned in the function",
    "BSL195": "Not recommended using of method GetForm",
    "BSL196": 'Method "%s" needs to be removed or renamed',
    "BSL197": 'Duplicated code block in "If...Then...ElseIf" statement',
    "BSL198": 'Duplicated condition in "If...Then...ElseIf" statement',
    "BSL200": "Check for line break of operands, operators and parameters",
    "BSL201": "Correct the expression to the standard",
    "BSL202": 'Correct the parameters passing into the "StrTemplate" method',
    "BSL203": "Check the reference to Internet resources",
    "BSL204": "Correct invalid character",
    "BSL204.diagnosticMessageDash": 'Correct character to "-"',
    "BSL204.diagnosticMessageSpace": "Replace non-breaking space character with space character",
    "BSL205": "To check access rights, use AccessRight global method instead.",
    "BSL206": "Don't use a join with sub queries",
    "BSL207": "Don't use a join with virtual table",
    "BSL208": "Can't use Latin and Cyrillic characters in one identifier",
    "BSL209": "'OR' operator is detected in JOIN condition",
    "BSL210": 'Don\'t use a logical "OR" in the "WHERE" section of the query',
    "BSL211": "Rename the metadata object `%s` so that the name length is less than %s",
    "BSL212": "Specify a required parameter %s",
    "BSL213": "The method %s of %s common module does not exist",
    "BSL214": 'Fill out the "%s" event subscription',
    "BSL215": "Add description for all method parameters",
    "BSL215.emptyDescription": 'Add type description for the "%s" parameter',
    "BSL215.missingDescription": 'Add description for the "%s" parameter',
    "BSL215.missingInSignature": 'Remove description for the "%s", they are missing in the signature',
    "BSL215.wrongOrder": "Correct the order for parameter descriptions",
    "BSL216": "%s of the '%s' missing space",
    "BSL217": "You should delete used data from temporary storage",
    "BSL218": "You should delete created temporary file",
    "BSL219": "Add a description of the variable",
    "BSL220": "Check if multiline literal is correct",
    "BSL221": "Add lines for languages: %s",
    "BSL222": "Add lines for languages: %s",
    "BSL224": 'Remove parameter initialization for %s "%s" by nested methods',
    "BSL224.diagnosticMessageWithoutName": "Remove parameter initialization for %s by nested methods",
    "BSL225": "Reduce the number of values in structure constructor",
    "BSL226": "Check for a potentially dangerous OSUsers method call",
    "BSL227": "Move the expression to a new line",
    "BSL228": "Move optional params after params",
    "BSL229": "Ordinary application support",
    "BSL230": 'Missing pair call "%s" for method "%s"',
    "BSL231": "Check the %s method access of the privileged module",
    "BSL232": "The source code of the module is missing due to password protection. %s",
    "BSL233": "Add a description of the public method",
    "BSL234": "Detected access to reference data nested field by dot in database query text",
    "BSL235": "Query text must be correct",
    "BSL236": 'Correct the reference to a non-existent metadata "%s" in the query',
    "BSL237": "Get rid of redundant calls within a module via its name or alias ThisObject",
    "BSL238": 'Get rid of getting the "Reference" field in the query.',
    "BSL239": 'Rename parameter "%s" that matches one of reserved words.',
    "BSL240": "Parameter %s rewrite without use",
    "BSL241": "Change the name of `%s`, it must not be the same as parent `%s`",
    "BSL242": 'Укажите существующий обработчик вместо несуществующего "%s" у регламентного задания "%s"',
    "BSL243": "Remove the insertion of the collection into itself",
    "BSL244": 'OnActivateRow and OnStartChoice events should not contain server procedure calls. Procedure "%s" executes on server, which may cause issues.',
    "BSL245": "Cannot create server-side export methods on a form",
    "BSL246": 'The role "%s" has the check box «Set permissions for new objects»',
    "BSL247": "Check the privileged mode setting",
    "BSL248": "Several compilation directives used",
    "BSL249": "Replace constructor %s to get style element",
    "BSL250": "Not recommended TempFilesDir() call",
    "BSL251": "Use if-else instead of ternary operator",
    "BSL252": "The ThisObject property is read only",
    "BSL253": "Timeout not installed by working with an external resource",
    "BSL254": 'Set the modifier "ByValue" for the "%s" parameter of the "%s" method',
    "BSL255": "Don't use try-catch to number cast",
    "BSL256": 'Possible typo in word "%s"',
    "BSL257": "Unary plus sign in string concatenation leads to potential runtime error",
    "BSL258": "Replace UNION construct with UNION ALL",
    "BSL259": 'Unknown preprocessor symbol "%s"',
    "BSL260": "Unsafe use of FindByCode() method",
    "BSL261": "Use explicit comparison with boolean when calling SafeMode method",
    "BSL262": 'Correct the transfer of invalid parameters in the method "WriteLogEvent"',
    "BSL262.noComment": 'The 5th parameter "Comment" is missing',
    "BSL262.noDetailErrorDescription": 'There is no call to "DetailErrorDescription(ErrorInfo())" in the comment text',
    "BSL262.noErrorLogLevelInsideExceptBlock": 'It is necessary to specify the level "Error" when write into log event inside the block "Exception-EndTry"',
    "BSL262.noSecondParameter": 'The 2nd parameter with the type "EventLogLevel" is missing',
    "BSL262.wrongNumberMessage": "Incorrect number of method parameters",
    "BSL263": "The iterator is not used in the For Each loop body",
    "BSL264": "Get rid of using the `SystemInformation` object",
    "BSL265": "Useless ternary operator",
    "BSL266": "Cancel may be assign true only",
    "BSL267": "Using external code tools is prohibited",
    "BSL268": 'Don\'t use method "%s" and finding by string.',
    "BSL269": "Change the expression to not use 'LIKE'",
    "BSL271": 'Check the correct use "%s" in Linux',
    "BSL272": "Instead of the synchronous method `%s`, use `%s`",
    "BSL273": "Don't use virtual tables without parameters",
    "BSL274": 'The data path of the "%s" form field is not specified. Form "%s".',
    "BSL275": 'Create handler named "%s" or fix the invalid handler for the "%s" http service',
    "BSL276": "You should call ProceedWithCall function only in Extensions and only methods annotated with &AROUND.",
    "BSL277": "You should call RollbackTransaction method in Exception block at first, and then execute other actions if required.",
    "BSL278": 'Create handler named "%s" or fix the invalid handler for the "%s" operation for the "%s" web service',
    "BSL279": 'The letter "Ё" is not allowed in the texts of the modules.',
}

# ---------------------------------------------------------------------------
# Fix hints — actionable one-line suggestions keyed by rule code
# ---------------------------------------------------------------------------

# BSLLS v1.0.7 DiagnosticMetadata and DiagnosticInfo.computeLSPSeverity.
# Keep CLI severity policy in RULE_METADATA independent of LSP presentation.
_BSLLS_LSP_SEVERITY_BY_RULE_NAME: dict[str, Severity] = {
    **dict.fromkeys(
        (
            "ParseError",
            "UsingHardcodeNetworkAddress",
            "UsingHardcodePath",
            "SelfAssign",
            "UsingHardcodeSecretInformation",
            "MissingCodeTryCatchEx",
            "FunctionShouldHaveReturn",
            "CreateQueryInCycle",
            "UnreachableCode",
            "IdenticalExpressions",
            "ProcedureReturnsValue",
            "DeprecatedCurrentDate",
            "BeginTransactionBeforeTryCatch",
            "CodeBlockBeforeSub",
            "CommitTransactionOutsideTryCatch",
            "CommonModuleAssign",
            "CommonModuleInvalidType",
            "DataExchangeLoading",
            "DeletingCollectionItem",
            "DisableSafeMode",
            "ExecuteExternalCode",
            "FieldsFromJoinsWithoutIsNull",
            "FileSystemAccess",
            "ForbiddenMetadataName",
            "FunctionReturnsSamePrimitive",
            "GetFormMethod",
            "GlobalContextMethodCollision8312",
            "IncorrectUseLikeInQuery",
            "IncorrectUseOfStrTemplate",
            "InternetAccess",
            "InvalidCharacterInFile",
            "MetadataObjectNameLength",
            "MissedRequiredParameter",
            "MissingCommonModuleMethod",
            "MissingEventSubscriptionHandler",
            "MissingTemporaryFileDeletion",
            "MultilineStringInQuery",
            "MultilingualStringHasAllDeclaredLanguages",
            "MultilingualStringUsingWithTemplate",
            "PairingBrokenTransaction",
            "QueryToMissingMetadata",
            "SameMetadataObjectAndChildNames",
            "ScheduledJobHandler",
            "SelfInsertion",
            "ServerCallsInFormEvents",
            "ServerSideExportFormMethod",
            "SetPermissionsForNewObjects",
            "SeveralCompilerDirectives",
            "StyleElementConstructors",
            "ThisObjectAssign",
            "TimeoutsInExternalResources",
            "UnaryPlusInConcatenation",
            "UnknownPreprocessorSymbol",
            "UnsafeSafeModeMethodCall",
            "UseLessForEach",
            "UsingLikeInQuery",
            "UsingObjectNotAvailableUnix",
            "VirtualTableCallWithoutParameters",
            "WrongDataPathForFormElements",
            "WrongHttpServiceHandler",
            "WrongUseFunctionProceedWithCall",
            "WrongUseOfRollbackTransactionMethod",
            "WrongWebServiceHandler",
        ),
        Severity.ERROR,
    ),
    **dict.fromkeys(
        (
            "MethodSize",
            "NonExportMethodsInApiRegion",
            "EmptyCodeBlock",
            "UnusedLocalVariable",
            "CognitiveComplexity",
            "CyclomaticComplexity",
            "NestedStatements",
            "UsingModalWindows",
            "UsingGoto",
            "NestedTernaryOperator",
            "UnusedLocalMethod",
            "ExportVariables",
            "DoubleNegatives",
            "UnusedParameters",
            "MissingReturnedValueDescription",
            "SelectTopWithoutOrderBy",
            "AllFunctionPathMustHaveReturn",
            "AssignAliasFieldsInQuery",
            "BadWords",
            "CachedPublic",
            "CodeAfterAsyncCall",
            "CommonModuleNameCached",
            "CommonModuleNameClientServer",
            "CommonModuleNameFullAccess",
            "CommonModuleNameGlobal",
            "CommonModuleNameGlobalClient",
            "CompilationDirectiveLost",
            "CompilationDirectiveNeedLess",
            "CrazyMultilineString",
            "DenyIncompleteValues",
            "DuplicatedInsertionIntoCollection",
            "ExecuteExternalCodeInCommonModule",
            "ExternalAppStarting",
            "ExtraCommas",
            "FullOuterJoinQuery",
            "FunctionOutParameter",
            "IfElseDuplicatedCondition",
            "IfElseIfEndsWithElse",
            "IsInRoleMethod",
            "JoinWithSubQuery",
            "JoinWithVirtualTable",
            "LogicalOrInJoinQuerySection",
            "LogicalOrInTheWhereSectionOfQuery",
            "MissingParameterDescription",
            "MissingTempStorageDeletion",
            "OSUsersMethod",
            "OrderOfParams",
            "OrdinaryAppSupport",
            "PrivilegedModuleMethodCall",
            "ProtectedModule",
            "QueryNestedFieldsByDot",
            "QueryParseError",
            "RefOveruse",
            "ReservedParameterNames",
            "RewriteMethodParameter",
            "SetPrivilegedMode",
            "TempFilesDir",
            "TransferringParametersBetweenClientAndServer",
            "TryNumber",
            "UnsafeFindByCode",
            "UseSystemInformation",
            "UsingCancelParameter",
            "UsingExternalCodeTools",
            "UsingFindElementByString",
            "UsingSynchronousCalls",
        ),
        Severity.WARNING,
    ),
    **dict.fromkeys(
        (
            "TooManyReturns",
            "CommentedCode",
            "LineLength",
            "NumberOfOptionalParams",
            "MagicNumber",
            "SemicolonPresence",
            "NumberOfParams",
            "DuplicateStringLiteral",
            "IfConditionComplexity",
            "UsingThisForm",
            "DeprecatedMessage",
            "MagicDate",
            "DeprecatedFind",
            "CommonModuleMissingAPI",
            "CommonModuleNameClient",
            "CommonModuleNameServerCall",
            "DeprecatedMethodCall",
            "ExcessiveAutoTestCheck",
            "IfElseDuplicatedCodeBlock",
            "LatinAndCyrillicSymbolInWord",
            "MissingVariablesDescription",
            "NestedConstructorsInStructureDeclaration",
            "NestedFunctionInParameters",
            "NumberOfValuesInStructureConstructor",
            "OneStatementPerLine",
            "TernaryOperatorUsage",
            "UnionAll",
        ),
        Severity.INFORMATION,
    ),
    **dict.fromkeys(
        (
            "NonStandardRegion",
            "CommandModuleExportMethods",
            "UsingServiceTag",
            "SpaceAtStartComment",
            "EmptyStatement",
            "EmptyRegion",
            "ConsecutiveEmptyLines",
            "DuplicateRegion",
            "CanonicalSpellingKeywords",
            "CodeOutOfRegion",
            "CommonModuleNameWords",
            "DeprecatedAttributes8312",
            "DeprecatedTypeManagedForm",
            "FormDataToValue",
            "FunctionNameStartsWithGet",
            "IncorrectLineBreak",
            "MissingSpace",
            "PublicMethodsDescription",
            "RedundantAccessToObject",
            "Typo",
            "UsageWriteLogEvent",
            "UselessTernaryOperator",
            "YoLetterUsage",
        ),
        Severity.HINT,
    ),
}


def lsp_compat_severity(code: str, severity: Severity) -> Severity:
    """Apply the upstream LSP level without changing the internal CLI policy.

    CODE_SMELL maps INFO/MINOR/MAJOR/CRITICAL/BLOCKER to Hint/Information/
    Warning/Warning/Warning. SECURITY_HOTSPOT maps to Warning, other types
    to Error. An explicit upstream lspSeverity takes precedence.
    Unknown and removed upstream rules retain their supplied severity.
    """
    meta = RULE_METADATA.get(code, {})
    rule_name = str(meta.get("name") or code)
    return _BSLLS_LSP_SEVERITY_BY_RULE_NAME.get(rule_name, severity)


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


# ``noqa`` / ``bsl-disable`` opening marker.  Placement defines the scope:
# trailing after code means one line; a standalone marker opens a range.
_RE_NOQA = re.compile(
    r"//\s*(?P<marker>noqa|bsl-disable)"
    r"(?:\s*:\s*(?P<codes>[A-Z0-9,\s]+))?\s*$",
    re.IGNORECASE,
)

# Range-closing marker paired with the family that opened it.
_RE_INLINE_SUPPRESSION_ENABLE = re.compile(
    r"//\s*(?P<marker>noqa-enable|bsl-enable)"
    r"(?:\s*:\s*(?P<codes>[A-Z0-9,\s]+))?\s*$",
    re.IGNORECASE,
)

# BSLLS opening/closing suppression.  A trailing ``-off`` is line-only; a
# standalone ``-off`` opens a range closed by ``-on``.
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


def unknown_rule_tokens(tokens: Iterable[str] | None) -> list[str]:
    """Return unknown rule tokens after applying the same splitting as normalization."""
    if tokens is None:
        return []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        for part in s.replace(",", " ").split():
            if resolve_rule_token_to_code(part) is not None:
                continue
            folded = part.casefold()
            if folded not in seen:
                seen.add(folded)
                unknown.append(part)
    return unknown


def normalize_rule_code_set_strict(
    tokens: Iterable[str] | None,
    *,
    source: str = "rule selection",
) -> set[str] | None:
    """
    Normalize user-facing select/ignore lists and reject unknown rule tokens.

    Internal callers may use :func:`normalize_rule_code_set` when a best-effort filter
    is more appropriate (for example environment-provided LSP/MCP filters).
    """
    materialized = list(tokens) if tokens is not None else None
    unknown = unknown_rule_tokens(materialized)
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(
            f"Unknown diagnostic rule token(s) in {source}: {joined}. "
            "Use BSL### codes or rule names from `onec-hbk-bsl rules`."
        )
    return normalize_rule_code_set(materialized)


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
_RE_BSL215_PARAM_ENTRY = re.compile(r"^\s*//\s{0,4}(\w+)\s*-", re.UNICODE)
_RE_BSL215_COMMENT_LINE = re.compile(r"^\s*//")


@functools.lru_cache(maxsize=131_072)
def path_is_likely_form_module_bsl(path: str) -> bool:
    """
    True for full EDT-style form modules below ``.../Forms/<form>/Ext/...``.
    """
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    if p.suffix.lower() != ".bsl":
        return False
    normalized = p.as_posix().lower()
    if p.name.lower() != "module.bsl":
        return False
    return "/forms/" in normalized and (
        normalized.endswith("/ext/module.bsl") or normalized.endswith("/ext/form/module.bsl")
    )


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
    content = "\n".join(lines)
    try:
        cache[path] = list(build_document_snapshot(path, content=content).procedures)
    except Exception:
        cache[path] = []
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


# BSL215/BSL233 — compiler directive (e.g. &НаКлиенте) preceding a proc header
_RE_COMPILER_DIRECTIVE = re.compile(r"^\s*&\w+\s*$")
# BSL240 / write-only var assignment
_RE_ASSIGN_LHS = re.compile(r"^\s*(?P<name>\w+)\s*=(?!=)", re.IGNORECASE)
_RE_BSL192_GET = re.compile(r"^Получить.*$", re.IGNORECASE)
_RE_BSL266_CANCEL = re.compile(r"^(?:Отказ|Cancel)$", re.IGNORECASE)
_RE_QUERY_SELECT_KEYWORD = re.compile(r"\bВЫБРАТЬ\b|\bSELECT\b", re.IGNORECASE)
_RE_QUERY_UNION_KEYWORD = re.compile(r"\bОБЪЕДИНИТЬ\b|\bUNION\b", re.IGNORECASE)
_RE_QUERY_INLINE_COMMENT = re.compile(r"\s*//.*$")
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
    r"\.\w+(?:\.\w+)+\s*(?:\(|\b)",
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


def _iter_query_text_blocks(lines: list[str]):
    """Yield query-like string blocks as ``(start_idx, block_lines)``."""
    i = 0
    while i < len(lines):
        line = lines[i]
        starts_query = bool(_RE_QUERY_TEXT_START.search(line))
        if not starts_query and '"' in line:
            j_probe = i + 1
            while j_probe < len(lines) and (
                not lines[j_probe].strip() or lines[j_probe].lstrip().startswith("|")
            ):
                if re.match(r"^\s*\|\s*(?:ВЫБРАТЬ|SELECT)\b", lines[j_probe], re.IGNORECASE):
                    starts_query = True
                    break
                j_probe += 1
        if not starts_query:
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        while j < len(lines) and (
            lines[j].lstrip().startswith("|")
            or lines[j].lstrip().startswith("//")
            or not lines[j].strip()
        ):
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

        content = _RE_QUERY_INLINE_COMMENT.sub("", raw_content).rstrip().lstrip()
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


def _query_block_content_line_tuples(
    block: QueryTextBlockInfo,
) -> tuple[tuple[int, int, str, str, bool], ...]:
    cached = getattr(block, "content_line_tuples", None)
    if cached is not None:
        return cached
    return tuple(
        (
            line.line_no,
            line.content_base,
            line.content,
            line.head,
            line.ended_query,
        )
        for line in block.content_lines
    )


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


_RE_REGION_LINE = re.compile(r"^\s*#(?:Область|Region|КонецОбласти|EndRegion)\b", re.IGNORECASE)
_RE_PREPROC_LINE = re.compile(r"^\s*#", re.IGNORECASE)

# BSL007 — «read» of a simple identifier: LHS of ``Имя =`` does not count as a use.


# BSLLS allowTrailingPartsInAnotherLanguage=true (default).
_RE_BSL208_TRAILING_LANG = re.compile(
    r"^(?:[A-Z][A-Za-z]+[A-Za-z1-9_]*[А-ЯЁ][А-Яа-яЁё]+[А-Яа-я1-9Ёё_]*"
    r"|[А-ЯЁ][А-Яа-яЁё]+[А-Яа-я1-9Ёё_]*[A-Z][A-Za-z]+[A-Za-z1-9_]*)$",
    re.UNICODE,
)

_BSL208_EXCLUDE_WORDS: frozenset[str] = frozenset(
    {
        "чтениеxml",
        "чтениеjson",
        "записьxml",
        "записьjson",
        "comобъект",
        "фабрикаxdto",
        "объектxdto",
        "соединениеftp",
        "httpсоединение",
        "httpзапрос",
        "httpсервисответ",
        "smsсообщение",
        "wsпрокси",
    }
)


def _bsl208_word_is_standard_tech_name(word: str) -> bool:
    """True for the default BSLLS LatinAndCyrillicSymbolInWord excludeWords list."""
    return word.casefold() in _BSL208_EXCLUDE_WORDS


# Loop open/close for QueryInLoop detection (separate from nesting ones)
_RE_LOOP_OPEN = re.compile(
    r"^\s*(?:ДляКаждого|ForEach|Для|For|Пока|While)\b",
    re.IGNORECASE,
)
_RE_LOOP_CLOSE = re.compile(
    r"^\s*(?:КонецЦикла|EndDo)\b",
    re.IGNORECASE,
)

# String literal extractor with BSL doubled-quote escaping.
_RE_STRING_LITERAL = re.compile(r'(?<![A-Za-zА-ЯЁа-яё0-9_])"((?:[^"]|"")*)"')

# Module-level variable declaration (outside any proc/function)
# We reuse _RE_VAR_LOCAL for matching

# Query text block: "ВЫБРАТЬ ... ИЗ ..."
_RE_QUERY_TEXT_START = re.compile(
    r'"\s*(?:ВЫБРАТЬ|SELECT)\b',
    re.IGNORECASE,
)
# Unconditional exit from method body (for unreachable code detection)
_RE_UNCONDITIONAL_EXIT = re.compile(
    r"^\s*(?:Возврат|Return|ВызватьИсключение|Raise|Прервать|Break|Продолжить|Continue|"
    r"Перейти|Goto)\b",
    re.IGNORECASE,
)

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
_RE_BSL175_ATTRIBUTE = re.compile(
    r"\b(?:ОбластьПостроенияДиаграммы|ChartPlotArea|Диаграмма|Chart|"
    r"ДиаграммаГанта|GanttChart|СводнаяДиаграмма|PivotChart)\.(?P<name>\w+)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL175_METHOD = re.compile(
    r"\b(?:Диаграмма|Chart)\.(?P<name>ПолучитьПалитру|GetPalette|"
    r"УстановитьПалитру|SetPalette)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL175_CHILD_FORM_ITEMS = re.compile(
    r"\b(?:ГруппировкаПодчиненныхЭлементовФормы|ChildFormItemsGroup)\.(?P<name>\w+)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_BSL175_ENUM_NAME = re.compile(r"\b(?P<name>ОриентацияМетокДиаграммы)\b", re.IGNORECASE)


def _bsl176_doc_comment_is_deprecated(doc_comment: str) -> bool:
    for raw_line in doc_comment.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_cf = line.casefold()
        return line_cf.startswith("устарела.") or line_cf.startswith("deprecated.")
    return False


_RE_COMMON_MODULE_PATH = re.compile(r"(?:^|[/\\\\])CommonModules(?:[/\\\\])", re.IGNORECASE)
_RE_BSL171_ADJACENT_LITERALS = re.compile(r'"[^"]*"\s+"[^"]*"', re.UNICODE)
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
_RE_BSL259_IDENTIFIER = re.compile(r"\b[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*\b", re.UNICODE)
# Form / module compiler directives before procedure (&НаКлиенте, &НаСервере, …)
_RE_FORM_COMPILER_DIRECTIVE_LINE = re.compile(r"^\s*&\S+")

_RE_RETURN_SIMPLE_EXPR = re.compile(r"^\s*(?:Возврат|Return)\s+(.+?);?\s*$", re.IGNORECASE)

_RE_STRING_LITERAL = re.compile(r'(?<![A-Za-zА-ЯЁа-яё0-9_])"((?:[^"]|"")*)"')

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


def _ts_node_text(node: Any) -> str:
    """Decode tree-sitter node text to str."""
    t = getattr(node, "text", None)
    if t is None:
        return ""
    return t.decode("utf-8", errors="replace") if isinstance(t, bytes) else str(t)


def _ts_walk(node: Any):
    """Yield *node* and all descendants depth-first."""
    yield from iter_ts_nodes(node)


def _ts_child_of_type(node: Any, node_type: str) -> Any | None:
    """First direct child of *node* with ``type == node_type``."""
    child_count = getattr(node, "child_count", None)
    child_at = getattr(node, "child", None)
    children = (
        (child_at(index) for index in range(child_count))
        if isinstance(child_count, int) and callable(child_at)
        else (getattr(node, "children", []) or [])
    )
    for child in children:
        if child is None:
            continue
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
        if getattr(getattr(child, "parent", None), "type", None) in {"access", "call_expression"}:
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


_BSL033_QUERY_TYPES = frozenset(
    {
        "запрос",
        "query",
        "построительзапроса",
        "querybuilder",
        "построительотчета",
        "reportbuilder",
    }
)
_BSL033_LOOP_NODE_TYPES = frozenset({"for_each_statement", "for_statement", "while_statement"})


def _ts_parent_of_type(node: Any, node_types: set[str] | frozenset[str]) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) in node_types:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def _bsl033_assignment_target(assignment: Any) -> str:
    target = assignment.child_by_field_name("left")
    if target is None or target.type not in {"identifier", "property_access"}:
        return ""
    return "".join(_ts_node_text(target).split()).casefold()


def _bsl033_expression_query_types(expr: Any, variable_types: dict[str, set[str]]) -> set[str]:
    children = expr.named_children
    if len(children) != 1:
        return set()
    child = children[0]
    if child.type in {"new_expression", "new_expression_method"}:
        type_node = child.child_by_field_name("type")
        if type_node is None:
            return set()
        if child.type == "new_expression_method":
            while type_node.type in {"expression", "const_expression"}:
                if len(type_node.named_children) != 1:
                    return set()
                type_node = type_node.named_children[0]
            if type_node.type != "string":
                return set()
            type_name = _ts_node_text(type_node)[1:-1].casefold()
        else:
            type_name = _ts_node_text(type_node).casefold()
        return {type_name} if type_name in _BSL033_QUERY_TYPES else set()
    if child.type in {"identifier", "property_access"}:
        return set(variable_types.get("".join(_ts_node_text(child).split()).casefold(), set()))
    return set()


def _bsl033_method_name(method_call: Any) -> str:
    ident = _ts_child_of_type(method_call, "identifier")
    return _ts_node_text(ident).casefold() if ident is not None else ""


def _bsl033_receiver_name(method_call: Any) -> str:
    parent = method_call.parent
    if parent is None or parent.type not in {"access", "call_expression"}:
        return ""
    receiver_parts = []
    for child in parent.children:
        if child == method_call:
            break
        receiver_parts.append(_ts_node_text(child))
    return "".join("".join(receiver_parts).split()).rstrip(".").casefold()


def _bsl033_range_node(method_call: Any) -> Any:
    parent = getattr(method_call, "parent", None)
    if getattr(parent, "type", None) == "call_expression":
        return parent
    call_expression = getattr(parent, "parent", None)
    if getattr(call_expression, "type", None) == "call_expression":
        return call_expression
    return parent if getattr(parent, "type", None) == "access" else method_call


def _diagnostics_bsl033_from_tree(
    path: str,
    lines: list[str],
    *,
    assignment_nodes: list[Any],
    method_call_nodes: list[Any],
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    proc_nodes = sorted(
        (*assignment_nodes, *method_call_nodes),
        key=lambda node: (
            getattr(node, "start_point", (0, 0))[0],
            getattr(node, "start_point", (0, 0))[1],
            0 if getattr(node, "type", None) == "assignment_statement" else 1,
        ),
    )
    variable_types_by_scope: dict[int, dict[str, set[str]]] = {}
    for node in proc_nodes:
        if node.has_error:
            continue
        scope = _ts_parent_of_type(node, {"procedure_definition", "function_definition"})
        scope_key = scope.id if scope is not None else 0
        variable_types = variable_types_by_scope.setdefault(scope_key, {})
        loop = _ts_parent_of_type(node, _BSL033_LOOP_NODE_TYPES)
        if loop is not None and loop.type == "for_each_statement":
            do_token = _ts_child_of_type(loop, "DO_KEYWORD")
            if do_token is not None and node.start_byte < do_token.end_byte:
                loop = _ts_parent_of_type(loop, _BSL033_LOOP_NODE_TYPES)
        if node.type == "assignment_statement":
            target = _bsl033_assignment_target(node)
            expr = node.child_by_field_name("right")
            if target and expr is not None:
                types = _bsl033_expression_query_types(expr, variable_types)
                if loop is not None:
                    variable_types.setdefault(target, set()).update(types)
                else:
                    variable_types[target] = types
            continue
        if node.type != "method_call" or _bsl033_method_name(node) not in {"выполнить", "execute"}:
            continue
        if loop is None:
            continue
        receiver = _bsl033_receiver_name(node)
        if not receiver or not (variable_types.get(receiver, set()) & _BSL033_QUERY_TYPES):
            continue
        range_node = _bsl033_range_node(node)
        start_row, start_byte = range_node.start_point
        end_row, end_byte = range_node.end_point
        start_line = lines[start_row] if 0 <= start_row < len(lines) else ""
        end_line = lines[end_row] if 0 <= end_row < len(lines) else ""
        diags.append(
            Diagnostic(
                file=path,
                line=start_row + 1,
                character=utf8_byte_offset_to_lsp_character(start_line, start_byte),
                end_line=end_row + 1,
                end_character=utf8_byte_offset_to_lsp_character(end_line, end_byte),
                severity=Severity.WARNING,
                code="BSL033",
            )
        )
    return diags


# BSL051 — tree-sitter nodes that close or branch control flow (not executable body).
# Matches keyword roles in tree-sitter block statements (if/while/for/try).
_BSL051_BLOCK_DELIMITER_TYPES = frozenset(
    {
        "ENDIF_KEYWORD",
        "ENDDO_KEYWORD",
        "ENDTRY_KEYWORD",
        "ENDFUNCTION_KEYWORD",
        "ENDPROCEDURE_KEYWORD",
        "EXCEPT_KEYWORD",
        "ELSE_KEYWORD",
        "ELSIF_KEYWORD",
    }
)

# Pre-compiled patterns shared across hot-path rules (avoid per-call re.compile overhead).
_RE_LINE_COMMENT = re.compile(r"^\s*//")
_RE_DOUBLE_QUOTED_STRING = re.compile(r'"[^"]*"')


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
    Delimiter line set from the CST.

    None means the tree is not suitable for BSL051 structural analysis.
    """
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return None
    if tree_has_errors(root):
        return None
    return _collect_bsl051_delimiter_lines_from_tree(root)


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


def _ts_node_is_under_parameters(node: Any) -> bool:
    """True if *node* is inside a ``parameters`` subtree (default values, etc.)."""
    p = getattr(node, "parent", None)
    while p is not None:
        if getattr(p, "type", None) == "parameters":
            return True
        p = getattr(p, "parent", None)
    return False


def _ts_assignment_is_self_assign(node: Any) -> bool:
    """Compare operand tokens, preserving case inside string literals."""
    if getattr(node, "type", None) != "assignment_statement" or tree_has_errors(node):
        return False
    children = [
        child
        for child in getattr(node, "children", ())
        if getattr(child, "type", None) not in {"line_comment", "comment", ";"}
    ]
    if len(children) != 3 or getattr(children[1], "type", None) != "=":
        return False
    if getattr(children[2], "type", None) != "expression":
        return False

    def tokens(operand: Any) -> tuple[str, ...]:
        result: list[str] = []
        stack = [operand]
        while stack:
            current = stack.pop()
            if getattr(current, "type", None) in {"line_comment", "comment"}:
                continue
            if getattr(current, "type", None) == "string":
                result.append(_ts_node_text(current))
                continue
            descendants = getattr(current, "children", ())
            if descendants:
                stack.extend(reversed(descendants))
            else:
                result.append(_ts_node_text(current).casefold())
        return tuple(result)

    return tokens(children[0]) == tokens(children[2])


def _diagnostics_bsl009_from_tree(
    path: str,
    root: Any,
    *,
    candidate_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    source_lines = _ts_node_text(root).splitlines()

    def check_node(node: Any) -> None:
        if (
            getattr(node, "type", None) == "assignment_statement"
            and not _ts_node_is_under_parameters(node)
            and _ts_assignment_is_self_assign(node)
        ):
            start = node.start_point
            end = node.end_point
            for child in getattr(node, "children", []) or []:
                if getattr(child, "type", None) == "expression":
                    end = child.end_point
                    break
            diags.append(
                Diagnostic(
                    file=path,
                    line=start[0] + 1,
                    character=utf8_byte_offset_to_lsp_character(source_lines[start[0]], start[1]),
                    end_line=end[0] + 1,
                    end_character=utf8_byte_offset_to_lsp_character(source_lines[end[0]], end[1]),
                    severity=Severity.ERROR,
                    code="BSL009",
                )
            )

    if candidate_nodes is not None:
        for node in candidate_nodes:
            check_node(node)
        return diags

    def walk(node: Any) -> None:
        check_node(node)
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
    return diags


DiagnosticEngine = import_module("onec_hbk_bsl.analysis.diagnostic.engine").DiagnosticEngine
