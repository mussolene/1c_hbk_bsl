from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any

from onec_hbk_bsl.analysis.bsl_typo.candidates import collect_spell_candidates
from onec_hbk_bsl.analysis.bsl_typo.models import SpellCandidate
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.context import DiagnosticDocumentContext
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import (
    AssignAliasFieldsInQueryRule,
    BadWordsRule,
    BeginTransactionBeforeTryCatchRule,
    CanonicalSpellingKeywordsRule,
    CodeBlockBeforeSubRule,
    CommitTransactionOutsideTryCatchRule,
    CommonModuleDiagnosticsRule,
    ConsecutiveEmptyLinesRule,
    CoreDiagnosticsRule,
    DeprecatedApiDiagnosticsRule,
    DeprecatedCurrentDateRule,
    DeprecatedFindRule,
    DeprecatedMessageRule,
    DeprecatedMethods8310Rule,
    DeprecatedMethods8317Rule,
    DeprecatedTypeManagedFormRule,
    DiagnosticRuntimeRule,
    DisableSafeModeRule,
    DoubleNegativesRule,
    EmptyStatementRule,
    ExcessiveAutoTestCheckRule,
    ExecuteExternalCodeInCommonModuleRule,
    ExecuteExternalCodeRule,
    ExternalAppStartingRule,
    ExtraCommasRule,
    FileSystemAccessRule,
    FormDataToValueRule,
    GetFormMethodRule,
    IfElseDuplicatedCodeBlockRule,
    IfElseDuplicatedConditionRule,
    IfElseIfEndsWithElseRule,
    IncorrectLineBreakRule,
    InternetAccessRule,
    IsInRoleMethodRule,
    LatinCyrillicRuntimeRule,
    LightPoolDiagnosticsRule,
    LocalXmlDiagnosticsRule,
    LogicalOrInTheWhereSectionOfQueryRule,
    MagicDateRule,
    MagicNumberRule,
    MethodContractDiagnosticsRule,
    MissingCodeTryCatchRule,
    MissingSpaceRuntimeRule,
    MissingTemporaryFileDeletionRule,
    MissingTempStorageDeletionRule,
    MissingVariablesDescriptionRule,
    NestedTernaryOperatorRule,
    NumberOfValuesInStructureConstructorRule,
    OneStatementPerLineRule,
    OSUsersMethodRule,
    PairingBrokenTransactionRule,
    QueryJoinDiagnosticsRule,
    QueryMetadataDiagnosticsRule,
    QueryRuntimeDiagnosticsRule,
    QueryTextDiagnosticsRule,
    SetPrivilegedModeRule,
    SpaceAtStartCommentRule,
    TempFilesDirRule,
    TryNumberRule,
    TypoRuntimeRule,
    UnaryPlusInConcatenationRule,
    UnionAllRule,
    UsageWriteLogEventRule,
    UseLessForEachRule,
    UselessTernaryOperatorRule,
    UseSystemInformationRule,
    UsingExternalCodeToolsRule,
    UsingGotoRule,
    UsingHardcodeNetworkAddressRule,
    UsingHardcodePathRule,
    UsingServiceTagRule,
    UsingSynchronousCallsRule,
    VirtualTableCallWithoutParametersRule,
    WrongUseFunctionProceedWithCallRule,
    WrongUseOfRollbackTransactionMethodRule,
    YoLetterUsageRule,
    _path_is_split_module_fragment,
)
from onec_hbk_bsl.analysis.diagnostic.execution import make_diagnostic_rule_task
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity

_RULES: tuple[DiagnosticRuntimeRule, ...] = (
    CoreDiagnosticsRule("BSL001"),
    CoreDiagnosticsRule("BSL002"),
    CoreDiagnosticsRule("BSL003"),
    CoreDiagnosticsRule("BSL004"),
    CoreDiagnosticsRule("BSL007"),
    CoreDiagnosticsRule("BSL008"),
    CoreDiagnosticsRule("BSL009"),
    CoreDiagnosticsRule("BSL011"),
    CoreDiagnosticsRule("BSL012"),
    CoreDiagnosticsRule("BSL013"),
    CoreDiagnosticsRule("BSL014"),
    CoreDiagnosticsRule("BSL015"),
    CoreDiagnosticsRule("BSL016"),
    CoreDiagnosticsRule("BSL017"),
    CoreDiagnosticsRule("BSL019"),
    CoreDiagnosticsRule("BSL020"),
    CoreDiagnosticsRule("BSL022"),
    CoreDiagnosticsRule("BSL026"),
    MissingCodeTryCatchRule(),
    MagicNumberRule(),
    CoreDiagnosticsRule("BSL030"),
    CoreDiagnosticsRule("BSL031"),
    CoreDiagnosticsRule("BSL032"),
    CoreDiagnosticsRule("BSL033"),
    CoreDiagnosticsRule("BSL035"),
    CoreDiagnosticsRule("BSL036"),
    CoreDiagnosticsRule("BSL040"),
    CoreDiagnosticsRule("BSL042"),
    CoreDiagnosticsRule("BSL051"),
    CoreDiagnosticsRule("BSL052"),
    CoreDiagnosticsRule("BSL054"),
    CoreDiagnosticsRule("BSL062"),
    CoreDiagnosticsRule("BSL064"),
    CoreDiagnosticsRule("BSL065"),
    CoreDiagnosticsRule("BSL077"),
    CoreDiagnosticsRule("BSL131"),
    CoreDiagnosticsRule("BSL148"),
    CommonModuleDiagnosticsRule("BSL152"),
    CommonModuleDiagnosticsRule("BSL154"),
    CommonModuleDiagnosticsRule("BSL156"),
    CommonModuleDiagnosticsRule("BSL158"),
    CommonModuleDiagnosticsRule("BSL159"),
    CommonModuleDiagnosticsRule("BSL160"),
    CommonModuleDiagnosticsRule("BSL161"),
    CommonModuleDiagnosticsRule("BSL162"),
    CommonModuleDiagnosticsRule("BSL163"),
    CommonModuleDiagnosticsRule("BSL164"),
    CommonModuleDiagnosticsRule("BSL165"),
    CommonModuleDiagnosticsRule("BSL166"),
    CommonModuleDiagnosticsRule("BSL167"),
    CommonModuleDiagnosticsRule("BSL168"),
    LightPoolDiagnosticsRule("BSL171"),
    CommonModuleDiagnosticsRule("BSL172"),
    CommonModuleDiagnosticsRule("BSL173"),
    LightPoolDiagnosticsRule("BSL169"),
    LightPoolDiagnosticsRule("BSL170"),
    LightPoolDiagnosticsRule("BSL181"),
    ExcessiveAutoTestCheckRule(),
    LightPoolDiagnosticsRule("BSL196"),
    LightPoolDiagnosticsRule("BSL260"),
    QueryMetadataDiagnosticsRule("BSL174"),
    DeprecatedApiDiagnosticsRule("BSL175"),
    DeprecatedApiDiagnosticsRule("BSL176"),
    QueryMetadataDiagnosticsRule("BSL187"),
    QueryMetadataDiagnosticsRule("BSL189"),
    FormDataToValueRule(),
    QueryTextDiagnosticsRule("BSL191"),
    MethodContractDiagnosticsRule("BSL192"),
    MethodContractDiagnosticsRule("BSL193"),
    MethodContractDiagnosticsRule("BSL194"),
    QueryTextDiagnosticsRule("BSL201"),
    LightPoolDiagnosticsRule("BSL202"),
    LightPoolDiagnosticsRule("BSL204"),
    QueryJoinDiagnosticsRule("BSL206"),
    QueryJoinDiagnosticsRule("BSL207"),
    LatinCyrillicRuntimeRule(),
    QueryJoinDiagnosticsRule("BSL209"),
    QueryMetadataDiagnosticsRule("BSL211"),
    QueryMetadataDiagnosticsRule("BSL213"),
    QueryMetadataDiagnosticsRule("BSL214"),
    MethodContractDiagnosticsRule("BSL212"),
    MethodContractDiagnosticsRule("BSL215"),
    MissingSpaceRuntimeRule(),
    MissingTempStorageDeletionRule(),
    MissingVariablesDescriptionRule(),
    QueryTextDiagnosticsRule("BSL220"),
    LightPoolDiagnosticsRule("BSL221"),
    LightPoolDiagnosticsRule("BSL222"),
    LightPoolDiagnosticsRule("BSL223"),
    MethodContractDiagnosticsRule("BSL224"),
    MethodContractDiagnosticsRule("BSL228"),
    LocalXmlDiagnosticsRule("BSL229"),
    QueryMetadataDiagnosticsRule("BSL231"),
    QueryMetadataDiagnosticsRule("BSL232"),
    MethodContractDiagnosticsRule("BSL233"),
    QueryRuntimeDiagnosticsRule("BSL234"),
    QueryTextDiagnosticsRule("BSL235"),
    QueryMetadataDiagnosticsRule("BSL236"),
    QueryRuntimeDiagnosticsRule("BSL237"),
    QueryMetadataDiagnosticsRule("BSL238"),
    LightPoolDiagnosticsRule("BSL239"),
    MethodContractDiagnosticsRule("BSL240"),
    QueryMetadataDiagnosticsRule("BSL241"),
    QueryMetadataDiagnosticsRule("BSL242"),
    LightPoolDiagnosticsRule("BSL243"),
    QueryMetadataDiagnosticsRule("BSL244"),
    QueryRuntimeDiagnosticsRule("BSL245"),
    QueryMetadataDiagnosticsRule("BSL246"),
    LightPoolDiagnosticsRule("BSL248"),
    LightPoolDiagnosticsRule("BSL249"),
    LightPoolDiagnosticsRule("BSL251"),
    LightPoolDiagnosticsRule("BSL252"),
    QueryMetadataDiagnosticsRule("BSL253"),
    MethodContractDiagnosticsRule("BSL254"),
    TypoRuntimeRule(),
    QueryMetadataDiagnosticsRule("BSL261"),
    LightPoolDiagnosticsRule("BSL259"),
    MethodContractDiagnosticsRule("BSL266"),
    LightPoolDiagnosticsRule("BSL268"),
    QueryTextDiagnosticsRule("BSL269"),
    QueryMetadataDiagnosticsRule("BSL274"),
    LightPoolDiagnosticsRule("BSL271"),
    LocalXmlDiagnosticsRule("BSL275"),
    LocalXmlDiagnosticsRule("BSL278"),
    UsingHardcodeNetworkAddressRule(),
    UsingHardcodePathRule(),
    UsingServiceTagRule(),
    BadWordsRule(),
    AssignAliasFieldsInQueryRule(),
    BeginTransactionBeforeTryCatchRule(),
    CodeBlockBeforeSubRule(),
    SpaceAtStartCommentRule(),
    EmptyStatementRule(),
    UsingGotoRule(),
    DoubleNegativesRule(),
    CanonicalSpellingKeywordsRule(),
    DeprecatedMessageRule(),
    NestedTernaryOperatorRule(),
    MagicDateRule(),
    ConsecutiveEmptyLinesRule(),
    DeprecatedFindRule(),
    DeprecatedCurrentDateRule(),
    DeprecatedMethods8310Rule(),
    DeprecatedMethods8317Rule(),
    GetFormMethodRule(),
    DeprecatedTypeManagedFormRule(),
    DisableSafeModeRule(),
    IfElseDuplicatedCodeBlockRule(),
    IfElseDuplicatedConditionRule(),
    IfElseIfEndsWithElseRule(),
    ExecuteExternalCodeRule(),
    ExecuteExternalCodeInCommonModuleRule(),
    ExternalAppStartingRule(),
    IncorrectLineBreakRule(),
    FileSystemAccessRule(),
    InternetAccessRule(),
    IsInRoleMethodRule(),
    UseSystemInformationRule(),
    OSUsersMethodRule(),
    SetPrivilegedModeRule(),
    TempFilesDirRule(),
    UsingExternalCodeToolsRule(),
    UsingSynchronousCallsRule(),
    LogicalOrInTheWhereSectionOfQueryRule(),
    CommitTransactionOutsideTryCatchRule(),
    UseLessForEachRule(),
    VirtualTableCallWithoutParametersRule(),
    NumberOfValuesInStructureConstructorRule(),
    OneStatementPerLineRule(),
    MissingTemporaryFileDeletionRule(),
    PairingBrokenTransactionRule(),
    TryNumberRule(),
    UnaryPlusInConcatenationRule(),
    UnionAllRule(),
    UsageWriteLogEventRule(),
    WrongUseFunctionProceedWithCallRule(),
    WrongUseOfRollbackTransactionMethodRule(),
    ExtraCommasRule(),
    UselessTernaryOperatorRule(),
    YoLetterUsageRule(),
)
DIAGNOSTIC_RUNTIME_RULE_CODES: frozenset[str] = frozenset(rule.code for rule in _RULES)

_QUERY_TEXT_191_201_CODES: tuple[str, ...] = ("BSL191", "BSL201")
_QUERY_TEXT_220_235_269_CODES: tuple[str, ...] = ("BSL220", "BSL235", "BSL269")
_QUERY_JOIN_CODES: tuple[str, ...] = ("BSL206", "BSL207", "BSL209")
_QUERY_METADATA_CODES: tuple[str, ...] = ("BSL174", "BSL187", "BSL236", "BSL238")
_METADATA_POOL_CODES: tuple[str, ...] = (
    "BSL189",
    "BSL211",
    "BSL213",
    "BSL214",
    "BSL231",
    "BSL232",
    "BSL241",
    "BSL242",
    "BSL246",
    "BSL274",
)
_METADATA_RUNTIME_CODES: tuple[str, ...] = ("BSL244", "BSL253", "BSL261")
_LIGHT_POOL_169_170_181_196_260_CODES: tuple[str, ...] = (
    "BSL169",
    "BSL170",
    "BSL181",
    "BSL196",
    "BSL260",
)
_LIGHT_POOL_171_248_252_259_268_CODES: tuple[str, ...] = (
    "BSL171",
    "BSL248",
    "BSL252",
    "BSL259",
    "BSL268",
)
_LIGHT_CALL_POOL_202_223_243_249_CODES: tuple[str, ...] = (
    "BSL202",
    "BSL223",
    "BSL243",
    "BSL249",
)
_ACCESS_POOL_188_203_264_CODES: tuple[str, ...] = ("BSL188", "BSL203", "BSL264")
_LIGHT_POOL_221_222_239_271_CODES: tuple[str, ...] = (
    "BSL221",
    "BSL222",
    "BSL239",
    "BSL271",
)
_DEPRECATED_API_POOL_CODES: tuple[str, ...] = ("BSL175", "BSL176")
_AGGREGATED_RULE_CODES: frozenset[str] = frozenset(
    _QUERY_TEXT_191_201_CODES
    + _QUERY_TEXT_220_235_269_CODES
    + _QUERY_JOIN_CODES
    + _QUERY_METADATA_CODES
    + _METADATA_POOL_CODES
    + _METADATA_RUNTIME_CODES
    + _LIGHT_POOL_169_170_181_196_260_CODES
    + _LIGHT_POOL_171_248_252_259_268_CODES
    + _LIGHT_CALL_POOL_202_223_243_249_CODES
    + _ACCESS_POOL_188_203_264_CODES
    + _LIGHT_POOL_221_222_239_271_CODES
)
_PROCESS_TYPO_MIN_LINES = 5_000
_PROCESS_TYPO_MIN_CANDIDATES = 200
_PROCESS_HEAVY_GROUP_MIN_LINES = 5_000
_PROCESS_FORK_RULE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("BSL224",),
    ("BSL197",),
    ("BSL060",),
    ("BSL263",),
    ("BSL005",),
    ("BSL039",),
    ("BSL171",),
    ("BSL271",),
    ("BSL020",),
    ("BSL029",),
    ("BSL007",),
    ("BSL153",),
    ("BSL148",),
    ("BSL212",),
    ("BSL001",),
    ("BSL210",),
    ("BSL227", "BSL265"),
    ("BSL173", "BSL186", "BSL181"),
    ("BSL030", "BSL243"),
    ("BSL230", "BSL202", "BSL218", "BSL223"),
    ("BSL035", "BSL027", "BSL267", "BSL066"),
    ("BSL180", "BSL200", "BSL178", "BSL279"),
    ("BSL097", "BSL250", "BSL205", "BSL185"),
)
_RUNTIME_CST_NODE_TYPES_BY_CODE: dict[str, frozenset[str]] = {
    "BSL029": frozenset({"assignment_statement", "number"}),
    "BSL060": frozenset({"binary_expression", "unary_expression"}),
    "BSL066": frozenset({"method_call"}),
    "BSL097": frozenset({"method_call"}),
    "BSL151": frozenset(
        {
            "assignment_statement",
            "break_statement",
            "call_statement",
            "continue_statement",
            "for_each_statement",
            "for_statement",
            "goto_statement",
            "if_statement",
            "return_statement",
            "rise_error_statement",
            "try_statement",
            "var_statement",
            "while_statement",
        }
    ),
    "BSL171": frozenset({"ERROR"}),
    "BSL173": frozenset({"for_each_statement"}),
    "BSL182": frozenset({"if_statement"}),
    "BSL188": frozenset({"method_call", "new_expression", "new_expression_method"}),
    "BSL197": frozenset({"if_statement"}),
    "BSL198": frozenset({"if_statement"}),
    "BSL199": frozenset({"if_statement"}),
    "BSL202": frozenset({"method_call", "new_expression"}),
    "BSL203": frozenset({"method_call", "new_expression", "new_expression_method"}),
    "BSL215": frozenset({"line_comment"}),
    "BSL217": frozenset({"method_call"}),
    "BSL218": frozenset({"method_call"}),
    "BSL223": frozenset({"method_call", "new_expression"}),
    "BSL224": frozenset({"call_expression", "method_call", "new_expression"}),
    "BSL225": frozenset({"new_expression"}),
    "BSL230": frozenset(
        {"method_call", "procedure_definition", "function_definition", "try_statement"}
    ),
    "BSL251": frozenset({"ternary_expression"}),
    "BSL252": frozenset({"assignment_statement"}),
    "BSL255": frozenset({"try_statement"}),
    "BSL257": frozenset({"unary_expression"}),
    "BSL259": frozenset({"preprocessor"}),
    "BSL260": frozenset({"method_call"}),
    "BSL263": frozenset({"for_each_statement"}),
    "BSL264": frozenset({"method_call", "new_expression", "new_expression_method"}),
    "BSL268": frozenset({"method_call"}),
    "BSL276": frozenset(
        {"method_call", "procedure_definition", "function_definition", "try_statement"}
    ),
    "BSL277": frozenset(
        {"method_call", "procedure_definition", "function_definition", "try_statement"}
    ),
}
_PROCESS_FACT_GROUP_011_175: tuple[str, ...] = ("BSL011", "BSL175")
_PROCESS_CORE_FACT_CODES: tuple[str, ...] = (
    "BSL011",
    "BSL012",
    "BSL013",
    "BSL014",
    "BSL016",
    "BSL017",
    "BSL019",
    "BSL022",
    "BSL026",
    "BSL036",
    "BSL040",
    "BSL077",
    "BSL131",
    "BSL190",
    "BSL204",
    "BSL216",
    "BSL219",
)
_PROCESS_CORE_FACT_CODE_SET: frozenset[str] = frozenset(_PROCESS_CORE_FACT_CODES)
_SPLIT_FRAGMENT_CORE_FACT_CODES: frozenset[str] = frozenset({"BSL017", "BSL026", "BSL040"})
_FORK_CONTEXT: DiagnosticDocumentContext | None = None
_FORK_RULE_BY_CODE: dict[str, DiagnosticRuntimeRule] = {}


def _parallel_rule_tasks_enabled() -> bool:
    value = os.environ.get("BSL_DIAG_PARALLEL_RULES", "1").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _process_rule_tasks_enabled() -> bool:
    value = os.environ.get("BSL_DIAG_PROCESS_RULES", "1").strip().casefold()
    return _parallel_rule_tasks_enabled() and value not in {"0", "false", "no", "off"}


def _process_rule_workers(group_count: int) -> int:
    try:
        configured = int(os.environ.get("BSL_DIAG_PARALLEL_WORKERS", "0") or "0")
    except ValueError:
        configured = 0
    if configured <= 0:
        configured = min(8, (os.cpu_count() or 2))
    return max(1, min(configured, group_count))


def _runtime_cst_node_types_for_codes(codes: set[str] | frozenset[str]) -> set[str]:
    node_types: set[str] = set()
    for code in codes:
        node_types.update(_RUNTIME_CST_NODE_TYPES_BY_CODE.get(code, ()))
    return node_types


def _run_forked_runtime_rule_group(codes: tuple[str, ...]) -> list[Diagnostic]:
    if _FORK_CONTEXT is None:
        return []
    out: list[Diagnostic] = []
    for code in codes:
        rule = _FORK_RULE_BY_CODE.get(code)
        if rule is not None:
            out.extend(rule.run(_FORK_CONTEXT))
    return out


def _run_forked_runtime_rule_groups(
    *,
    context: DiagnosticDocumentContext,
    rule_by_code: dict[str, DiagnosticRuntimeRule],
    groups: tuple[tuple[str, ...], ...],
) -> list[Diagnostic]:
    if not groups:
        return []
    if "fork" not in mp.get_all_start_methods():
        return [
            diag
            for group in groups
            for diag in _run_runtime_rule_group_local(context, rule_by_code, group)
        ]

    global _FORK_CONTEXT, _FORK_RULE_BY_CODE
    _FORK_CONTEXT = context
    _FORK_RULE_BY_CODE = rule_by_code
    try:
        workers = _process_rule_workers(len(groups))
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("fork")) as pool:
            future_to_group = {
                pool.submit(_run_forked_runtime_rule_group, group): group for group in groups
            }
            out: list[Diagnostic] = []
            for future, group in future_to_group.items():
                try:
                    out.extend(future.result())
                except Exception:
                    out.extend(_run_runtime_rule_group_local(context, rule_by_code, group))
            return out
    finally:
        _FORK_CONTEXT = None
        _FORK_RULE_BY_CODE = {}


def _run_runtime_rule_group_local(
    context: DiagnosticDocumentContext,
    rule_by_code: dict[str, DiagnosticRuntimeRule],
    codes: tuple[str, ...],
) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for code in codes:
        rule = rule_by_code.get(code)
        if rule is not None:
            out.extend(rule.run(context))
    return out


def _run_bsl011_175_snapshot_facts(
    *,
    path: str,
    lines: list[str],
    procs: list[Any],
    complexity_metrics: list[tuple[int, int]],
    module_body_cognitive_facts: list[Any],
    symbols: list[Any],
    calls: list[Any],
    enabled_codes: tuple[str, ...],
    max_cognitive_complexity: int,
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis import diagnostics as _diag
    from onec_hbk_bsl.analysis.diagnostic.domain import ModuleModel, ProcedureModel

    enabled = set(enabled_codes)
    out: list[Diagnostic] = []
    if "BSL011" in enabled:
        for proc, (cognitive, _mccabe) in zip(procs, complexity_metrics, strict=False):
            proc_model = ProcedureModel.from_proc_info(path, proc)
            out.extend(
                proc_model.validate_cognitive_complexity(
                    cognitive_complexity=cognitive,
                    max_cognitive_complexity=max_cognitive_complexity,
                    proc_name_span=_diag._proc_name_span,
                    lines=lines,
                )
            )
        out.extend(
            Diagnostic(
                file=path,
                line=fact.line_idx + 1,
                character=fact.character,
                end_line=fact.line_idx + 1,
                end_character=fact.end_character,
                severity=Severity.WARNING,
                code="BSL011",
            )
            for fact in module_body_cognitive_facts
        )
    if "BSL175" in enabled:
        model = ModuleModel(path=path)
        out.extend(
            diag
            for diag in model.validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
                lines=lines,
                symbols=symbols,
                calls=calls,
                enabled_codes=("BSL175",),
                line_comment_re=_diag._RE_LINE_COMMENT,
                bsl176_deprecated_doc_predicate_fn=_diag._bsl176_doc_comment_is_deprecated,
                mask_double_quoted_strings_preserve_len_fn=(
                    _diag._mask_double_quoted_strings_preserve_len
                ),
                bsl175_attribute_re=_diag._RE_BSL175_ATTRIBUTE,
                bsl175_attr_replacements=_diag._BSL175_ATTR_REPLACEMENTS,
                bsl175_method_re=_diag._RE_BSL175_METHOD,
                bsl175_method_replacements=_diag._BSL175_METHOD_REPLACEMENTS,
                bsl175_child_form_items_re=_diag._RE_BSL175_CHILD_FORM_ITEMS,
                bsl175_enum_replacements=_diag._BSL175_ENUM_REPLACEMENTS,
                bsl175_enum_name_re=_diag._RE_BSL175_ENUM_NAME,
                bsl175_global_method_re=_diag._RE_BSL175_GLOBAL_METHOD,
                bsl175_global_methods=_diag._BSL175_GLOBAL_METHODS,
            )
            if diag.code == "BSL175"
        )
    return out


def _run_deprecated_api_pool(
    context: DiagnosticDocumentContext,
    enabled_codes: tuple[str, ...],
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    snapshot = context.snapshot
    symbols = list(getattr(snapshot, "symbols", []) or [])
    calls = list(getattr(snapshot, "calls", []) or [])
    return context.module_model.validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
        lines=context.lines,
        tree=context.tree,
        symbols=symbols,
        calls=calls,
        symbol_index=getattr(context.diagnostics_engine, "_symbol_index", None),
        enabled_codes=enabled_codes,
        ts_walk_fn=_diag._ts_walk,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=_diag.utf8_byte_offset_to_lsp_character,
        line_comment_re=_diag._RE_LINE_COMMENT,
        bsl176_deprecated_doc_predicate_fn=_diag._bsl176_doc_comment_is_deprecated,
        mask_double_quoted_strings_preserve_len_fn=(_diag._mask_double_quoted_strings_preserve_len),
        bsl175_attribute_re=_diag._RE_BSL175_ATTRIBUTE,
        bsl175_attr_replacements=_diag._BSL175_ATTR_REPLACEMENTS,
        bsl175_method_re=_diag._RE_BSL175_METHOD,
        bsl175_method_replacements=_diag._BSL175_METHOD_REPLACEMENTS,
        bsl175_child_form_items_re=_diag._RE_BSL175_CHILD_FORM_ITEMS,
        bsl175_enum_replacements=_diag._BSL175_ENUM_REPLACEMENTS,
        bsl175_enum_name_re=_diag._RE_BSL175_ENUM_NAME,
        bsl175_global_method_re=_diag._RE_BSL175_GLOBAL_METHOD,
        bsl175_global_methods=_diag._BSL175_GLOBAL_METHODS,
    )


def _run_light_pool_169_170_181_196_260(
    context: DiagnosticDocumentContext,
    enabled_codes: tuple[str, ...],
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    engine = context.diagnostics_engine
    return context.module_model.validate_bsl169_170_181_182_196_260_light_pool(
        lines=context.lines,
        procs=context.procedures,
        enabled=enabled_codes,
        snapshot=context.snapshot,
        tree=context.tree,
        ts_nodes_for_types_fn=engine._ts_nodes_for_types,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=_diag.utf8_byte_offset_to_lsp_character,
        path_is_likely_form_module_bsl_fn=_diag.path_is_likely_form_module_bsl,
        path_is_command_module_bsl_fn=_diag._path_is_command_module_bsl,
        strip_inline_comment_preserve_strings_fn=_diag._strip_inline_comment_preserve_strings,
        line_comment_re=_diag._RE_LINE_COMMENT,
        proc_name_span_fn=_diag._proc_name_span,
    )


def _run_light_pool_171_248_252_259_268(
    context: DiagnosticDocumentContext,
    enabled_codes: tuple[str, ...],
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import rules as runtime_rules

    engine = context.diagnostics_engine
    return context.module_model.validate_bsl171_248_251_252_259_268_light_pool(
        lines=context.lines,
        tree=context.tree,
        procs=context.procedures,
        codes=enabled_codes,
        rule_enabled_fn=engine._rule_enabled,
        ts_nodes_for_types_fn=engine._ts_nodes_for_types,
        rule_bsl171_fn=runtime_rules._run_bsl171_crazy_multiline_string,
        rule_bsl248_fn=runtime_rules._run_bsl248_several_compiler_directives,
        rule_bsl251_fn=runtime_rules._run_bsl251_ternary_operator_usage,
        rule_bsl252_fn=runtime_rules._run_bsl252_this_object_assign,
        rule_bsl259_fn=runtime_rules._run_bsl259_unknown_preprocessor_symbol,
        rule_bsl268_fn=runtime_rules._run_bsl268_using_find_element_by_string,
    )


def _run_light_call_pool_202_223_243_249(
    context: DiagnosticDocumentContext,
    enabled_codes: tuple[str, ...],
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return context.module_model.validate_bsl202_205_223_243_249_light_call_pool(
        lines=context.lines,
        tree=context.tree,
        enabled=enabled_codes,
        snapshot=context.snapshot,
        strip_inline_comment_preserve_strings_fn=_diag._strip_inline_comment_preserve_strings,
        ts_nodes_for_types_fn=context.diagnostics_engine._ts_nodes_for_types,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        ts_method_call_arg_exprs_fn=_diag._ts_method_call_arg_exprs,
        ts_walk_fn=_diag._ts_walk,
        ts_method_identifier_span_fn=_diag._ts_method_identifier_span,
        utf8_byte_offset_to_lsp_character_fn=_diag.utf8_byte_offset_to_lsp_character,
        bsl223_structure_names=_diag._BSL223_STRUCTURE_NAMES,
        bsl249_style_constructor_names=_diag._BSL249_STYLE_CONSTRUCTOR_NAMES,
        split_top_level_args_fn=_diag._split_top_level_args,
        find_matching_paren_fn=_diag._find_matching_paren,
    )


def _run_light_pool_221_222_239_271(
    context: DiagnosticDocumentContext,
    enabled_codes: tuple[str, ...],
) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    engine = context.diagnostics_engine
    return context.module_model.validate_bsl221_222_239_271_light_pool(
        lines=context.lines,
        tree=context.tree,
        procs=context.procedures,
        enabled=enabled_codes,
        snapshot=context.snapshot,
        strip_inline_comment_preserve_strings_fn=_diag._strip_inline_comment_preserve_strings,
        reserved_parameter_names_re=engine._reserved_parameter_names_re,
        ts_walk_fn=_diag._ts_walk,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=_diag.utf8_byte_offset_to_lsp_character,
        bsl221_nstr_re=_diag._RE_BSL221_NSTR,
        bsl221_lang_re=_diag._RE_BSL221_LANG,
        bsl271_unix_unavailable_new_re=_diag._RE_BSL271_UNIX_UNAVAILABLE_NEW,
        bsl271_platform_guard_re=_diag._RE_BSL271_PLATFORM_GUARD,
        proc_name_span_fn=_diag._proc_name_span,
        declared_languages=engine._declared_languages,
    )


def _chunk_spell_candidates(
    candidates: list[SpellCandidate],
    chunk_count: int,
) -> list[list[SpellCandidate]]:
    if chunk_count <= 1:
        return [candidates]
    size = max(1, (len(candidates) + chunk_count - 1) // chunk_count)
    return [candidates[index : index + size] for index in range(0, len(candidates), size)]


def _run_bsl256_typo_candidates(path: str, candidates: list[SpellCandidate]) -> list[Diagnostic]:
    from onec_hbk_bsl.analysis.bsl_typo.engine import spellcheck_candidate_diagnostics

    rows = spellcheck_candidate_diagnostics(path=path, candidates=candidates)
    return [
        Diagnostic(
            file=d["file"],
            line=d["line"],
            character=d["character"],
            end_line=d["end_line"],
            end_character=d["end_character"],
            severity=Severity.INFORMATION,
            code=d["code"],
        )
        for d in rows
    ]


def _same_line_fact_diagnostic(
    *,
    path: str,
    fact: Any,
    code: str,
    severity: Severity,
) -> Diagnostic:
    line_idx = int(fact.line_idx)
    end_line_idx = fact.end_line_idx
    return Diagnostic(
        file=path,
        line=line_idx + 1,
        character=int(fact.character),
        end_line=(int(end_line_idx) if end_line_idx is not None else line_idx) + 1,
        end_character=int(fact.end_character),
        severity=severity,
        code=code,
    )


def _run_core_fact_rule(
    *,
    code: str,
    path: str,
    lines: list[str],
    procs: list[Any],
    complexity_metrics: list[tuple[int, int]],
    facts: list[Any],
    max_cognitive_complexity: int,
    max_mccabe_complexity: int,
) -> list[Diagnostic]:
    if code in {"BSL011", "BSL019"}:
        from onec_hbk_bsl.analysis import diagnostics as _diag
        from onec_hbk_bsl.analysis.diagnostic.domain import ProcedureModel

        diags: list[Diagnostic] = []
        for proc, (cognitive, mccabe) in zip(procs, complexity_metrics, strict=False):
            proc_model = ProcedureModel.from_proc_info(path, proc)
            if code == "BSL011":
                diags.extend(
                    proc_model.validate_cognitive_complexity(
                        cognitive_complexity=cognitive,
                        max_cognitive_complexity=max_cognitive_complexity,
                        proc_name_span=_diag._proc_name_span,
                        lines=lines,
                    )
                )
            else:
                diags.extend(
                    proc_model.validate_mccabe_complexity(
                        mccabe_complexity=mccabe,
                        max_mccabe_complexity=max_mccabe_complexity,
                        proc_name_span=_diag._proc_name_span,
                        lines=lines,
                    )
                )
        if code == "BSL011":
            diags.extend(
                Diagnostic(
                    file=path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.WARNING,
                    code="BSL011",
                )
                for fact in facts
            )
        return diags

    severity_by_code = {
        "BSL012": Severity.ERROR,
        "BSL013": Severity.INFORMATION,
        "BSL014": Severity.INFORMATION,
        "BSL016": Severity.INFORMATION,
        "BSL017": Severity.WARNING,
        "BSL022": Severity.WARNING,
        "BSL026": Severity.INFORMATION,
        "BSL036": Severity.INFORMATION,
        "BSL040": Severity.INFORMATION,
        "BSL077": Severity.WARNING,
        "BSL131": Severity.INFORMATION,
        "BSL190": Severity.INFORMATION,
        "BSL204": Severity.ERROR,
        "BSL216": Severity.INFORMATION,
        "BSL219": Severity.INFORMATION,
    }
    severity = severity_by_code.get(code, Severity.INFORMATION)
    return [
        _same_line_fact_diagnostic(path=path, fact=fact, code=code, severity=severity)
        for fact in facts
    ]


def _core_fact_rows_for_code(
    *,
    code: str,
    snapshot: Any,
    engine: Any,
) -> list[Any]:
    if code == "BSL011":
        return list(
            snapshot.module_body_cognitive_complexity_facts(engine.max_cognitive_complexity)
        )
    if code == "BSL012":
        return list(snapshot.hardcoded_credential_facts)
    if code == "BSL013":
        return list(snapshot.commented_code_facts)
    if code == "BSL014":
        return list(snapshot.line_too_long_facts(engine.max_line_length))
    if code == "BSL016":
        return list(snapshot.non_standard_region_facts)
    if code == "BSL017":
        return list(snapshot.command_or_form_export_facts)
    if code == "BSL022":
        return list(snapshot.deprecated_warning_facts)
    if code == "BSL026":
        return list(snapshot.empty_region_facts)
    if code == "BSL036":
        return list(snapshot.complex_condition_facts(engine.max_bool_ops))
    if code == "BSL040":
        return list(snapshot.this_form_usage_facts)
    if code == "BSL077":
        return list(snapshot.select_top_without_order_facts)
    if code == "BSL131":
        return list(snapshot.duplicate_region_facts)
    if code == "BSL190":
        return list(snapshot.form_data_to_value_facts)
    if code == "BSL204":
        return list(snapshot.invalid_character_facts)
    if code == "BSL216":
        return list(snapshot.missing_space_facts)
    if code == "BSL219":
        return list(snapshot.module_variable_description_facts)
    return []


def append_diagnostic_runtime_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: Any,
    path: str,
    content: str,
    lines: list[str],
    tree: Any,
    snapshot: Any | None,
) -> None:
    context = DiagnosticDocumentContext(
        path=path,
        content=content,
        lines=lines,
        tree=tree,
        snapshot=snapshot,
        max_bool_ops=int(getattr(engine, "max_bool_ops", 3)),
        bsl036_enabled=bool(engine._rule_enabled("BSL036")),
        runtime_call_context=None,
        ts_nodes_for_types=engine._ts_nodes_for_types,
        global_method_calls_from_nodes=engine._global_method_calls_from_nodes,
        diagnostics_engine=engine,
    )

    def enabled_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(code for code in codes if engine._rule_enabled(code))

    def add_task(codes: tuple[str, ...], fn: Callable[[], list[Diagnostic]]) -> None:
        if codes:
            rule_tasks.append(("+".join(codes), fn))

    if context.ts_nodes_for_types is not None:
        runtime_cst_node_types = _runtime_cst_node_types_for_codes(engine._enabled_rule_codes())
        if runtime_cst_node_types:
            context.ts_nodes_for_types(context.tree, runtime_cst_node_types)

    def add_aggregated_query_tasks() -> None:
        query_text_191_201 = enabled_codes(_QUERY_TEXT_191_201_CODES)
        query_text_220_235_269 = enabled_codes(_QUERY_TEXT_220_235_269_CODES)
        query_join = enabled_codes(_QUERY_JOIN_CODES)
        query_metadata = enabled_codes(_QUERY_METADATA_CODES)
        metadata_pool = enabled_codes(_METADATA_POOL_CODES)
        metadata_runtime = enabled_codes(_METADATA_RUNTIME_CODES)

        if query_text_191_201 or query_text_220_235_269 or query_join or query_metadata:
            # Materialise the shared query view once for all query-family diagnostics.
            query_blocks = context.query_text_blocks

        if query_text_191_201:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
                run_bsl191_201_query_text_diagnostics,
            )

            add_task(
                query_text_191_201,
                lambda codes=query_text_191_201: run_bsl191_201_query_text_diagnostics(
                    context.path,
                    context.lines,
                    codes,
                    engine._rule_enabled,
                    query_blocks,
                ),
            )
        if query_text_220_235_269:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
                run_bsl220_235_269_query_text_diagnostics,
            )

            add_task(
                query_text_220_235_269,
                lambda codes=query_text_220_235_269: run_bsl220_235_269_query_text_diagnostics(
                    context.path,
                    context.lines,
                    codes,
                    engine._rule_enabled,
                    query_blocks,
                ),
            )
        if query_join:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
                run_bsl206_207_209_query_join_diagnostics,
            )

            add_task(
                query_join,
                lambda codes=query_join: run_bsl206_207_209_query_join_diagnostics(
                    context.path,
                    context.lines,
                    codes,
                    engine._rule_enabled,
                    query_blocks,
                ),
            )
        if query_metadata:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
                applicable_bsl174_187_236_238_codes,
                run_bsl174_187_236_238_query_metadata_pool,
            )

            query_metadata = applicable_bsl174_187_236_238_codes(
                context.path,
                query_metadata,
                query_blocks,
            )
            add_task(
                query_metadata,
                lambda codes=query_metadata: run_bsl174_187_236_238_query_metadata_pool(
                    context.path,
                    context.lines,
                    codes,
                    query_blocks,
                    context.lines,
                ),
            )
        if metadata_runtime:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
                run_bsl244_253_261_runtime_pool,
            )

            add_task(
                metadata_runtime,
                lambda codes=metadata_runtime: run_bsl244_253_261_runtime_pool(
                    context.path,
                    context.lines,
                    context.procedures,
                    codes,
                    context.lines,
                    tree=context.tree,
                    snapshot=context.snapshot,
                ),
            )
        if metadata_pool:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
                applicable_bsl189_211_213_214_231_232_241_242_246_274_codes,
                run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool,
            )

            metadata_pool = applicable_bsl189_211_213_214_231_232_241_242_246_274_codes(
                context.path,
                context.content,
                metadata_pool,
            )
            add_task(
                metadata_pool,
                lambda codes=metadata_pool: (
                    run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
                        context.path,
                        context.lines,
                        context.procedures,
                        codes,
                        context.lines,
                    )
                ),
            )

    add_aggregated_query_tasks()
    coarse_parallelized: set[str] = set()
    fact_group_011_175 = tuple(
        code
        for code in enabled_codes(_PROCESS_FACT_GROUP_011_175)
        if snapshot is not None and len(lines) >= _PROCESS_HEAVY_GROUP_MIN_LINES
    )
    if fact_group_011_175 and snapshot is not None:
        rule_tasks.append(
            make_diagnostic_rule_task(
                "+".join(fact_group_011_175),
                partial(
                    _run_bsl011_175_snapshot_facts,
                    path=path,
                    lines=lines,
                    procs=context.procedures,
                    complexity_metrics=list(
                        snapshot.complexity_metrics_for_procs(context.procedures)
                    ),
                    module_body_cognitive_facts=list(
                        snapshot.module_body_cognitive_complexity_facts(
                            engine.max_cognitive_complexity
                        )
                    ),
                    symbols=list(snapshot.symbols),
                    calls=list(snapshot.calls),
                    enabled_codes=fact_group_011_175,
                    max_cognitive_complexity=engine.max_cognitive_complexity,
                ),
                process_safe=True,
            )
        )
        coarse_parallelized.update(fact_group_011_175)

    deprecated_api_parallelized: set[str] = set()
    deprecated_api_pool = tuple(
        code
        for code in enabled_codes(_DEPRECATED_API_POOL_CODES)
        if code not in coarse_parallelized
    )
    if deprecated_api_pool:
        add_task(
            deprecated_api_pool,
            lambda codes=deprecated_api_pool: _run_deprecated_api_pool(context, codes),
        )
        deprecated_api_parallelized.update(deprecated_api_pool)

    light_pool_169_170_181_196_260 = enabled_codes(_LIGHT_POOL_169_170_181_196_260_CODES)
    if light_pool_169_170_181_196_260:
        add_task(
            light_pool_169_170_181_196_260,
            lambda codes=light_pool_169_170_181_196_260: _run_light_pool_169_170_181_196_260(
                context, codes
            ),
        )

    light_pool_171_248_252_259_268 = enabled_codes(_LIGHT_POOL_171_248_252_259_268_CODES)
    if light_pool_171_248_252_259_268:
        add_task(
            light_pool_171_248_252_259_268,
            lambda codes=light_pool_171_248_252_259_268: _run_light_pool_171_248_252_259_268(
                context, codes
            ),
        )

    light_call_pool_202_223_243_249 = enabled_codes(_LIGHT_CALL_POOL_202_223_243_249_CODES)
    if light_call_pool_202_223_243_249:
        add_task(
            light_call_pool_202_223_243_249,
            lambda codes=light_call_pool_202_223_243_249: _run_light_call_pool_202_223_243_249(
                context, codes
            ),
        )

    access_pool_188_203_264 = enabled_codes(_ACCESS_POOL_188_203_264_CODES)
    if access_pool_188_203_264:
        from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import (
            run_bsl188_203_264_access_pool,
        )

        add_task(
            access_pool_188_203_264,
            lambda codes=access_pool_188_203_264: run_bsl188_203_264_access_pool(
                context,
                codes,
            ),
        )

    light_pool_221_222_239_271 = enabled_codes(_LIGHT_POOL_221_222_239_271_CODES)
    if light_pool_221_222_239_271:
        add_task(
            light_pool_221_222_239_271,
            lambda codes=light_pool_221_222_239_271: _run_light_pool_221_222_239_271(
                context, codes
            ),
        )

    core_fact_parallelized: set[str] = set()
    if snapshot is not None:
        split_fragment = _path_is_split_module_fragment(path)
        enabled_core_fact_codes = tuple(
            code
            for code in enabled_codes(_PROCESS_CORE_FACT_CODES)
            if code not in coarse_parallelized
            and not (split_fragment and code in _SPLIT_FRAGMENT_CORE_FACT_CODES)
        )
        if enabled_core_fact_codes:
            complexity_metrics: list[tuple[int, int]] = []
            if "BSL011" in enabled_core_fact_codes or "BSL019" in enabled_core_fact_codes:
                complexity_metrics = list(snapshot.complexity_metrics_for_procs(context.procedures))
            for code in enabled_core_fact_codes:
                facts = _core_fact_rows_for_code(code=code, snapshot=snapshot, engine=engine)
                rule_tasks.append(
                    make_diagnostic_rule_task(
                        code,
                        partial(
                            _run_core_fact_rule,
                            code=code,
                            path=context.path,
                            lines=context.lines,
                            procs=context.procedures,
                            complexity_metrics=complexity_metrics,
                            facts=facts,
                            max_cognitive_complexity=engine.max_cognitive_complexity,
                            max_mccabe_complexity=engine.max_mccabe_complexity,
                        ),
                        process_safe=True,
                    )
                )
                core_fact_parallelized.add(code)

    typo_parallelized = False
    if engine._rule_enabled("BSL256") and len(lines) >= _PROCESS_TYPO_MIN_LINES:
        root = getattr(tree, "root_node", None)
        if root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray)):
            typo_candidates = collect_spell_candidates(tree=tree)
            if len(typo_candidates) >= _PROCESS_TYPO_MIN_CANDIDATES:
                worker_count = min(8, max(1, len(typo_candidates) // _PROCESS_TYPO_MIN_CANDIDATES))
                for shard_index, shard in enumerate(
                    _chunk_spell_candidates(typo_candidates, worker_count)
                ):
                    rule_tasks.append(
                        make_diagnostic_rule_task(
                            f"BSL256:{shard_index}",
                            partial(_run_bsl256_typo_candidates, path, shard),
                            process_safe=True,
                        )
                    )
                typo_parallelized = True

    fork_parallelized: set[str] = set()
    if _process_rule_tasks_enabled() and len(lines) >= _PROCESS_HEAVY_GROUP_MIN_LINES:
        rule_by_code = {rule.code: rule for rule in _RULES}
        fork_groups: list[tuple[str, ...]] = []
        for group in _PROCESS_FORK_RULE_GROUPS:
            enabled_group = tuple(
                code
                for code in group
                if code not in _AGGREGATED_RULE_CODES
                and code not in coarse_parallelized
                and code not in core_fact_parallelized
                and not (code == "BSL256" and typo_parallelized)
                and engine._rule_enabled(code)
                and code in rule_by_code
            )
            if enabled_group:
                fork_groups.append(enabled_group)
                fork_parallelized.update(enabled_group)
        if fork_groups:
            rule_tasks.append(
                make_diagnostic_rule_task(
                    "fork:" + "+".join(sorted(fork_parallelized)),
                    partial(
                        _run_forked_runtime_rule_groups,
                        context=context,
                        rule_by_code=rule_by_code,
                        groups=tuple(fork_groups),
                    ),
                )
            )

    for rule in _RULES:
        if rule.code in _AGGREGATED_RULE_CODES:
            continue
        if rule.code in coarse_parallelized:
            continue
        if rule.code in core_fact_parallelized:
            continue
        if rule.code in deprecated_api_parallelized:
            continue
        if rule.code in fork_parallelized:
            continue
        if rule.code == "BSL256" and typo_parallelized:
            continue
        if engine._rule_enabled(rule.code):
            rule_tasks.append((rule.code, lambda rule=rule: rule.run(context)))
