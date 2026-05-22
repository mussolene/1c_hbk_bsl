from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.context import BsllsDocumentContext
from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.rules import (
    AssignAliasFieldsInQueryRule,
    BadWordsRule,
    BeginTransactionBeforeTryCatchRule,
    BsllsDiagnosticRule,
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
    DisableSafeModeRule,
    DoubleNegativesRule,
    EmptyStatementRule,
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
    MethodContractDiagnosticsRule,
    MissingSpaceRuntimeRule,
    MissingTemporaryFileDeletionRule,
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
)
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic

_RULES: tuple[BsllsDiagnosticRule, ...] = (
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
    CoreDiagnosticsRule("BSL028"),
    CoreDiagnosticsRule("BSL029"),
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
    LightPoolDiagnosticsRule("BSL182"),
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
    LightPoolDiagnosticsRule("BSL217"),
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
BSL_RUNTIME_RULE_CODES: frozenset[str] = frozenset(rule.code for rule in _RULES)

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
_AGGREGATED_RULE_CODES: frozenset[str] = frozenset(
    _QUERY_TEXT_191_201_CODES
    + _QUERY_TEXT_220_235_269_CODES
    + _QUERY_JOIN_CODES
    + _QUERY_METADATA_CODES
    + _METADATA_POOL_CODES
    + _METADATA_RUNTIME_CODES
)


def append_bslls_runtime_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: Any,
    path: str,
    content: str,
    lines: list[str],
    tree: Any,
    snapshot: Any | None,
) -> None:
    context = BsllsDocumentContext(
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
                run_bsl174_187_236_238_query_metadata_pool,
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
                ),
            )
        if metadata_pool:
            from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
                run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool,
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
    for rule in _RULES:
        if rule.code in _AGGREGATED_RULE_CODES:
            continue
        if engine._rule_enabled(rule.code):
            rule_tasks.append((rule.code, lambda rule=rule: rule.run(context)))
