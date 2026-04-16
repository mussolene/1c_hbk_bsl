"""DiagnosticEngine extracted from diagnostics facade.

This module intentionally imports the diagnostics facade to reuse the existing
module-level helpers, constants, and rule implementations while the remaining
rule bodies are migrated out of ``diagnostics.py``.
"""

# ruff: noqa: F403,F405

from __future__ import annotations

from collections import Counter

import onec_hbk_bsl.analysis.diagnostics as _diag
from onec_hbk_bsl.analysis.diagnostic.execution import execute_diagnostic_rule_tasks
from onec_hbk_bsl.analysis.diagnostic.suppression import (
    is_suppressed,
    parse_suppressions,
)
from onec_hbk_bsl.analysis.diagnostics import *  # noqa: F401,F403

globals().update(
    {
        name: getattr(_diag, name)
        for name in dir(_diag)
        if name.startswith("_") and not name.startswith("__")
    }
)


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
            # "BSL013" enabled — CommentedCode required for BSLLS parity
            "BSL016",  # NonStandardRegion — keep opt-in; BSLLS does not enable it in the strict parity slice
            "BSL018",  # RaiseWithLiteral — opt-in; bare literals are normal; extended syntax is optional
            "BSL038",  # StringConcatenationInLoop — no direct BSLLS equivalent (BSLLS doesn't flag this)
            "BSL058",  # QueryWithoutWhere — no BSLLS equivalent; all firings are FP vs BSLLS
            "BSL042",  # EmptyExportMethod — BSLLS UnusedLocalMethod has different semantics (non-export dead methods)
            # "BSL065" enabled — MissingReturnedValueDescription required for BSLLS parity
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
        suppressions = parse_suppressions(lines)

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

        extend_core_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
            regions=regions,
            tree=tree,
            proc_node_map=_proc_node_map,
            snapshot=snapshot,
        )
        extend_style_comment_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
            snapshot=snapshot,
        )
        extend_query_top_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            query_blocks=_query_blocks,
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
                (
                    "BSL157",
                    lambda: self._rule_bsl157_commit_transaction_outside_try(path, lines, snapshot),
                )
            )
        extend_module_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            content=content,
            lines=lines,
            procs=procs,
            regions=regions,
            tree=tree,
            idx=idx,
        )
        if self._rule_enabled("BSL257"):
            _rule_tasks.append(
                ("BSL257", lambda: self._rule_bsl257_unary_plus_in_concatenation(path, lines))
            )
        if self._rule_enabled("BSL279"):
            _rule_tasks.append(("BSL279", lambda: self._rule_bsl279_yo_letter_usage(path, lines)))
        if self._rule_enabled("BSL210"):
            _rule_tasks.append(
                ("BSL210", lambda: self._rule_bsl210_logical_or_in_where(path, lines))
            )
        extend_style_token_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            snapshot=snapshot,
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
            snapshot=snapshot,
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
            snapshot=snapshot,
        )
        extend_metadata_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            content=content,
            lines=lines,
            tree=tree,
            procs=procs,
            snapshot=snapshot,
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
            snapshot=snapshot,
        )
        if self._rule_enabled("BSL234"):
            _rule_tasks.append(
                ("BSL234", lambda: self._rule_bsl234_query_nested_fields_by_dot(path, lines))
            )
        extend_style_tail_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
            snapshot=snapshot,
        )
        extend_runtime_tail_rule_tasks(
            _rule_tasks,
            engine=self,
            path=path,
            lines=lines,
            procs=procs,
            tree=tree,
            snapshot=snapshot,
        )
        diagnostics = execute_diagnostic_rule_tasks(_rule_tasks)
        # Apply inline suppressions
        diagnostics = [d for d in diagnostics if not is_suppressed(d, suppressions)]
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
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        re_for_index_header = re.compile(r"^\s*(?:Для|For)\s+(\w+)\s*=", re.IGNORECASE)
        diags: list[Diagnostic] = []
        inside_proc: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside_proc.add(i)

        code_lines = snapshot.code_lines_without_comments if snapshot is not None else lines

        def _read_words_ignoring_member_access(code_fragment: str) -> set[str]:
            reads: set[str] = set()
            for match in re.finditer(r"\b\w+\b", code_fragment, re.IGNORECASE):
                if match.start() > 0 and code_fragment[match.start() - 1] == ".":
                    continue
                reads.add(match.group(0).casefold())
            return reads

        def _read_names_by_line(raw_line: str) -> set[str]:
            if not raw_line.strip():
                return set()
            code_no_comments = _strip_inline_comment_preserve_strings(raw_line)
            code_clean = _bsl007_strip_double_quoted_segments(code_no_comments)
            m = _BSL007_SIMPLE_ASSIGN_AT_START.match(code_clean)
            if m:
                tail = code_clean[m.end() :]
                return _read_words_ignoring_member_access(tail)
            return _read_words_ignoring_member_access(code_clean)

        line_read_names = [_read_names_by_line(line) for line in code_lines]
        file_read_counts: Counter[str] = Counter()
        for names in line_read_names:
            file_read_counts.update(names)

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
            if file_read_counts.get(var_name.casefold(), 0) > 0:
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
            emitted: set[tuple[int, str]] = set()

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
            proc_read_counts: Counter[str] = Counter()
            for abs_idx in range(max(body_lo, 0), min(body_hi, len(lines) - 1) + 1):
                for read_name in line_read_names[abs_idx]:
                    proc_read_counts[read_name] += 1

            def _emit_unused(
                abs_line: int,
                var_name: str,
                _emitted: set[tuple[int, str]] = emitted,
            ) -> None:
                key = (abs_line, var_name.casefold())
                if key in _emitted:
                    return
                _emitted.add(key)
                char_pos = lines[abs_line].find(var_name) if var_name in lines[abs_line] else 0
                diags.append(
                    Diagnostic(
                        file=path,
                        line=abs_line + 1,
                        character=char_pos,
                        end_line=abs_line + 1,
                        end_character=char_pos + len(var_name),
                        severity=Severity.WARNING,
                        code="BSL007",
                        message=f"Удалите неиспользуемую переменную {var_name}",
                    )
                )

            for var_name, rel_idx in declared:
                abs_decl = proc.start_idx + rel_idx
                uses = proc_read_counts.get(var_name.casefold(), 0) - (
                    1 if var_name.casefold() in line_read_names[abs_decl] else 0
                )
                if uses > 0:
                    continue
                _emit_unused(abs_decl, var_name)

            # --- Implicit locals: ``Имя =`` without preceding ``Перем`` in this proc ---
            # Emit at the first assignment site for each unread variable to match
            # BSLLS positioning and avoid duplicate noise for reassignments.
            implicit_first_unused: dict[str, tuple[str, int]] = {}
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
                var_cf = var_name.casefold()
                if proc_read_counts.get(var_cf, 0) > 0:
                    continue
                implicit_first_unused.setdefault(var_cf, (var_name, abs_line))
            for var_name, abs_line in sorted(
                implicit_first_unused.values(),
                key=lambda item: item[1],
            ):
                _emit_unused(abs_line, var_name)

            # --- For-loop index variable never read in loop body ---
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                m_for = re_for_index_header.match(pline)
                if not m_for:
                    continue
                var_name = m_for.group(1)
                var_cf = var_name.casefold()
                if var_cf in param_cf:
                    continue
                used = False
                for abs_idx in range(abs_line + 1, min(proc.end_idx, len(lines))):
                    if var_cf in line_read_names[abs_idx]:
                        used = True
                        break
                if not used:
                    _emit_unused(abs_line, var_name)

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
                        severity=Severity.ERROR,
                        code="BSL009",
                        message="Удалите бесполезное присваивание переменной самой себе",
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
                            f'Уменьшите когнитивную сложность "{proc.name}" '
                            f"с {cc} до {self.max_cognitive_complexity}"
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

    def _rule_bsl014_line_too_long(
        self, path: str, lines: list[str], snapshot: DocumentSnapshot | None = None
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        line_lengths = (
            snapshot.line_lengths if snapshot is not None else [len(line) for line in lines]
        )
        for idx, line in enumerate(lines):
            # Skip query string continuation lines (|...) — BSLLS does not flag these for BSL014
            if line.lstrip().startswith("|"):
                continue
            length = line_lengths[idx]
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
                        message=(
                            f"Длина строки {length} превышает максимально допустимую "
                            f"{self.max_line_length}"
                        ),
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
                            f'Уменьшите цикломатическую сложность "{proc.name}" '
                            f"с {cc} до {self.max_mccabe_complexity}"
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
        """Flag opening control-flow lines whose nesting exceeds max_nesting_depth."""
        re_nest_open = re.compile(
            r"^\s*(?:Если|If|ДляКаждого|Для\s+каждого|ForEach|For\s+Each|Для|For|Пока|While|Попытка|Try)\b",
            re.IGNORECASE,
        )
        re_nest_close = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
            re.IGNORECASE,
        )
        diags: list[Diagnostic] = []
        for proc in procs:
            nesting = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                line = lines[i]
                if re_nest_close.match(line):
                    nesting = max(0, nesting - 1)
                    continue
                if re_nest_open.match(line):
                    nesting += 1
                    if nesting > self.max_nesting_depth:
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=i + 1,
                                character=len(line) - len(line.lstrip()),
                                end_line=i + 1,
                                end_character=len(line),
                                severity=Severity.WARNING,
                                code="BSL020",
                                message="Превышен допустимый уровень вложенности управляющих конструкций",
                            )
                        )
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
                        message=f'Найден служебный тег "{m.group(0)}"',
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL024 — No space after // in comment
    # ------------------------------------------------------------------

    def _rule_bsl024_space_at_start_comment(
        self, path: str, lines: list[str], snapshot: DocumentSnapshot | None = None
    ) -> list[Diagnostic]:
        """
        Require a space after ``//`` in single-line comments (BSLLS ``SpaceAtStartComment``).

        Mirrors BSLLS strict-good pattern, ``//@`` / ``//(c)`` / ``//©`` annotations,
        skips commented-code lines (BSLLS ``CodeRecognizer``), ``//!``, ``//|``, noqa.
        """
        diags: list[Diagnostic] = []
        for idx, line in enumerate(snapshot.lines if snapshot is not None else lines):
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
                    message=(
                        "Между символами комментария '//' и самим текстом комментария "
                        "должен быть пробел."
                    ),
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
        continuation_prefix_re = re.compile(
            r"^\s*(?:[),.]|[+\-*/%]|\b(?:И|Или|AND|OR)\b)",
            re.IGNORECASE,
        )
        header_start_re = re.compile(
            r"^\s*(?:Процедура|Функция|Procedure|Function)\b",
            re.IGNORECASE,
        )
        end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b", re.IGNORECASE
        )
        control_header_start_re = re.compile(
            r"^\s*(?:Если|If|ИначеЕсли|ElseIf|Пока|While|Для(?:\s+Каждого)?|For(?:\s+Each)?)\b",
            re.IGNORECASE,
        )
        control_header_tail_re = re.compile(r"\)\s*(?:Тогда|Then|Цикл|Do)\s*$", re.IGNORECASE)

        def _code_without_comments_and_strings(text: str) -> str:
            code = text.split("//", 1)[0]
            code = _RE_DOUBLE_QUOTED_STRING.sub('""', code)
            code = _RE_SINGLE_QUOTED_STRING.sub("''", code)
            return code

        header_continuation_lines: set[int] = set()
        for proc in procs:
            header_end_idx = proc.start_idx
            start_code = _code_without_comments_and_strings(lines[proc.start_idx])
            if header_start_re.match(start_code):
                header_balance = start_code.count("(") - start_code.count(")")
                j = proc.start_idx
                while header_balance > 0 and j + 1 < min(proc.end_idx, len(lines)):
                    j += 1
                    header_balance += _code_without_comments_and_strings(lines[j]).count("(")
                    header_balance -= _code_without_comments_and_strings(lines[j]).count(")")
                header_end_idx = j
                for line_idx in range(proc.start_idx + 1, header_end_idx + 1):
                    header_continuation_lines.add(line_idx)

            paren_balance = 0
            for i in range(proc.start_idx + 1, min(proc.end_idx, len(lines))):
                if i <= header_end_idx:
                    continue
                line = lines[i]
                stripped = line.rstrip()
                if not stripped or stripped.strip().startswith("//"):
                    continue
                code_part = stripped.split("//")[0].rstrip()
                if not code_part:
                    continue
                if header_start_re.match(code_part):
                    continue
                if control_header_start_re.match(code_part) and code_part.rstrip().endswith(
                    ("Тогда", "Then", "Цикл", "Do")
                ):
                    continue
                if control_header_tail_re.search(code_part):
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
                code_masked = _code_without_comments_and_strings(code_part)
                starts_inside_multiline = paren_balance > 0
                paren_balance = max(
                    0,
                    paren_balance + code_masked.count("(") - code_masked.count(")"),
                )
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
                if starts_inside_multiline or paren_balance > 0:
                    continue
                if next_sig is not None and (
                    continuation_re.match(next_sig) or continuation_prefix_re.match(next_sig)
                ):
                    continue
                if _RE_STMT_NO_SEMI.match(code_part):
                    col = max(0, len(code_part) - 1)
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=i + 1,
                            character=col,
                            end_line=i + 1,
                            end_character=col + 1,
                            severity=Severity.INFORMATION,
                            code="BSL030",
                            message=("Пропущена точка с запятой в конце выражения"),
                        )
                    )
        seen_lines = {diag.line for diag in diags}
        for idx, line in enumerate(lines):
            if idx in header_continuation_lines:
                continue
            stripped = line.rstrip()
            if not stripped or stripped.strip().startswith("//"):
                continue
            code_part = stripped.split("//")[0].rstrip()
            if not code_part or code_part.endswith(";"):
                continue
            if header_start_re.match(code_part):
                continue
            if control_header_start_re.match(code_part) and code_part.rstrip().endswith(
                ("Тогда", "Then", "Цикл", "Do")
            ):
                continue
            if control_header_tail_re.search(code_part):
                continue
            code_masked = _code_without_comments_and_strings(code_part)
            if code_masked.count("(") > code_masked.count(")"):
                continue
            if not _RE_STMT_NO_SEMI.match(code_part):
                continue
            next_sig = None
            for j in range(idx + 1, len(lines)):
                nxt = lines[j].strip()
                if not nxt or nxt.startswith("//"):
                    continue
                next_sig = lines[j]
                break
            if next_sig is not None and continuation_prefix_re.match(next_sig):
                continue
            if next_sig is None or not end_kw_re.match(next_sig):
                continue
            if idx + 1 in seen_lines:
                continue
            col = max(0, len(code_part) - 1)
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=col,
                    end_line=idx + 1,
                    end_character=col + 1,
                    severity=Severity.INFORMATION,
                    code="BSL030",
                    message="Пропущена точка с запятой в конце выражения",
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
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        """
        Detect numeric literals > 1 used directly in executable code.

        Ignores:
        - 0 and 1 (universally accepted)
        - Lines that look like constant declarations (Перем Х = N)
        - Comment lines and strings
        """
        re_magic = re.compile(
            r"(?<![\"'\w.])"
            r"(?:-?(?:[2-9]\d*|\d{2,})(?:\.\d+)?|-?0\.(?:0*[1-9]\d*))"
            r"(?![\w.\"])",
        )
        diags: list[Diagnostic] = []
        masked_lines = snapshot.masked_lines if snapshot is not None else None
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments if snapshot is not None else None
        )
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
                if not _RE_BSL029_ANY_DIGIT.search(line):
                    continue
                # Mask string contents before scanning while preserving original
                # character offsets for resulting diagnostics.
                code_part = (
                    code_lines_wo_comments[i]
                    if code_lines_wo_comments is not None
                    else line.split("//")[0]
                )
                code_part = (
                    masked_lines[i]
                    if masked_lines is not None
                    else _RE_DOUBLE_QUOTED_STRING.sub(
                        lambda m: '"' + (" " * max(0, len(m.group(0)) - 2)) + '"',
                        code_part,
                    )
                )
                code_part = _RE_SINGLE_QUOTED_STRING.sub(
                    lambda m: "'" + (" " * max(0, len(m.group(0)) - 2)) + "'",
                    code_part,
                )
                comment_pos = code_part.find("//")
                if comment_pos >= 0:
                    code_part = code_part[:comment_pos]
                # Skip Для/For loop headers — BSLLS does not flag loop bounds
                if _RE_BSL029_FOR_HEADER.match(code_part):
                    continue
                # Skip simple direct assignments Var = N — BSLLS skips these
                if _RE_BSL029_SIMPLE_ASSIGN.match(code_part):
                    continue
                # Remove ternary operator args — BSLLS does not flag simple numeric
                # values in ?(cond, N, M) because they are not in CallParamContext
                code_part = _RE_BSL029_TERNARY.sub("?('',0,0)", code_part)
                # Skip only obvious ``Структура*.Вставить("key", value)`` calls.
                # A broad ``*.Вставить`` skip hides many valid BSLLS diagnostics.
                code_part = re.sub(
                    r"\b(?:Структура\w*|Structure\w*)\s*\.\s*(?:Вставить|Insert)\s*"
                    r'\(\s*(?:"[^"]*"|\'[^\']*\')\s*,\s*([^)]+)\)',
                    '.Вставить("",0)',
                    code_part,
                    flags=re.IGNORECASE,
                )
                for m in re_magic.finditer(code_part):
                    # BSLLS skips plain numeric array indices: arr[2]
                    lpos = m.start() - 1
                    while lpos >= 0 and code_part[lpos] in " \t":
                        lpos -= 1
                    rpos = m.end()
                    while rpos < len(code_part) and code_part[rpos] in " \t":
                        rpos += 1
                    if (
                        lpos >= 0
                        and rpos < len(code_part)
                        and code_part[lpos] == "["
                        and code_part[rpos] == "]"
                    ):
                        continue
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
                                "Создайте константу с понятным названием, "
                                f'присвойте ей значение "{m.group()}" и используйте '
                                "эту константу вместо магического числа."
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
        for line0, col0, col1 in bsl148_function_name_spans(
            root,
            loops_executed_at_least_once=self.bsl148_loops_executed_at_least_once,
        ):
            diags.append(
                Diagnostic(
                    file=path,
                    line=line0,
                    character=col0,
                    end_line=line0,
                    end_character=col1,
                    severity=Severity.WARNING,
                    code="BSL148",
                    message="Не все пути выполнения функции возвращают значение",
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
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
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
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments if snapshot is not None else None
        )
        for scope_lines in _bsl035_scope_line_indices(lines, procs):
            counts: Counter[str] = Counter()
            positions: dict[str, list[tuple[int, int]]] = {}

            for idx in scope_lines:
                line = (
                    code_lines_wo_comments[idx]
                    if code_lines_wo_comments is not None
                    else lines[idx]
                )
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
                                "Необходимо избавиться от многократного использования "
                                f'строкового литерала "{val}"'
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
            _ = self._bsl036_if_condition_chunk(lines, idx) or line
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
                    end_character=char + 1,
                    severity=Severity.INFORMATION,
                    code="BSL036",
                    message="Выделите условие оператора Если в отдельный метод или переменную",
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
                        severity=Severity.INFORMATION,
                        code="BSL041",
                        message='Не следует использовать устаревший метод "Сообщить"',
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
                    crossed_preprocessor = False
                    while j < len(body_lines):
                        next_abs, next_line = body_lines[j]
                        stripped = next_line.strip()
                        if not stripped or stripped.startswith("//"):
                            j += 1
                            continue
                        if stripped.startswith("#"):
                            crossed_preprocessor = True
                            j += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip())
                        # Same or lesser indent => same scope => unreachable
                        if (
                            not crossed_preprocessor
                            and next_indent <= exit_indent
                            and next_abs not in end_line_idxs
                        ):
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
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
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

        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines
        for idx, line in enumerate(lines):
            if idx in inside:
                continue
            m = _RE_VAR_MODULE_EXPORT.match(clean_lines[idx])
            if m:
                start_char = m.start("names")
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=start_char,
                        end_line=idx + 1,
                        end_character=len(line),
                        severity=Severity.WARNING,
                        code="BSL054",
                        message="Не рекомендуется использовать экспортные переменные. Это может стать источником трудновоспроизводимых ошибок",
                    )
                )
        return diags

    # ------------------------------------------------------------------
    # BSL219 — MissingVariablesDescription (exported module Перем)
    # ------------------------------------------------------------------

    def _rule_bsl219_missing_variables_description(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        """
        Flag module-level ``Перем … Экспорт`` without a preceding ``//`` / ``///`` description line.

        Aligns with BSLLS ``MissingVariablesDescription`` for exported module variables.
        """
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)

        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines
        for idx, line in enumerate(lines):
            if idx in inside:
                continue
            code_part = clean_lines[idx].rstrip()
            if not code_part.strip():
                continue
            m = _RE_VAR_MODULE_EXPORT.match(code_part)
            if not m:
                continue
            if _module_export_var_has_preceding_description(lines, idx):
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
                    code="BSL219",
                    message="Добавьте описание переменной",
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL055 — Consecutive blank lines (> MAX_BLANK_LINES)
    # ------------------------------------------------------------------

    # BSLLS ConsecutiveEmptyLines: flag when more than one blank line in a row.
    MAX_BLANK_LINES: int = 1

    def _rule_bsl055_consecutive_blank_lines(
        self, path: str, lines: list[str], snapshot: DocumentSnapshot | None = None
    ) -> list[Diagnostic]:
        """Flag runs of more than ``MAX_BLANK_LINES`` consecutive blank lines."""
        diags: list[Diagnostic] = []
        blank_run = 0
        run_start = 0
        blank_flags = (
            snapshot.blank_line_flags
            if snapshot is not None
            else [line.strip() == "" for line in lines]
        )
        for idx, is_blank in enumerate(blank_flags):
            if is_blank:
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
        if len(lines) >= 2 and blank_flags[-1] and not blank_flags[-2]:
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
        Flag functions whose doc block lacks a valid ``Возвращаемое значение`` section.
        """
        diags: list[Diagnostic] = []
        for proc in procs:
            if proc.kind != "function":
                continue
            block_end = proc.start_idx - 1
            while block_end >= 0 and _RE_COMPILER_DIRECTIVE.match(lines[block_end]):
                block_end -= 1
            if block_end < 0 or not _RE_BSL215_COMMENT_LINE.match(lines[block_end]):
                continue
            block_start = block_end
            while block_start > 0 and _RE_BSL215_COMMENT_LINE.match(lines[block_start - 1]):
                block_start -= 1
            comment_block = lines[block_start : block_end + 1]
            returns_section_start = None
            for ci, cl in enumerate(comment_block):
                if re.match(
                    r"^\s*//\s*(?:Возвращаемое\s+значение|Returns)\s*:?\s*$",
                    cl,
                    re.IGNORECASE,
                ):
                    returns_section_start = ci
                    break
            has_valid_return_entry = False
            if returns_section_start is not None:
                for cl in comment_block[returns_section_start + 1 :]:
                    stripped = cl.strip()
                    if stripped == "//":
                        break
                    if re.match(r"^\s*//\s*\w[\w\s]*:\s*$", cl):
                        break
                    if re.match(r"^\s*//\s{1,4}\S+\s*-", cl):
                        has_valid_return_entry = True
                        break
            if returns_section_start is None or not has_valid_return_entry:
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
                        code="BSL065",
                        message="Добавьте описание возвращаемого значения функции",
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

        standard_aliases = {
            "public",
            "internal",
            "private",
            "eventhandlers",
            "formeventhandlers",
        }

        def region_is_effectively_empty(region: _RegionInfo) -> bool:
            for line_idx in range(region.start_idx + 1, min(region.end_idx, len(lines))):
                stripped = lines[line_idx].strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                    continue
                return False
            return True

        diags: list[Diagnostic] = []
        seen: dict[str, _RegionInfo] = {}
        for region in regions:
            key = normalize(region.name)
            if not key:
                continue
            if key not in seen:
                seen[key] = region
                continue
            prev = seen[key]
            if key not in standard_aliases and not region_is_effectively_empty(prev):
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
                    message=f'Нужно удалить дубли раздела "{region.name}"',
                )
            )
            seen[key] = region
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
        return run_bsl152_cached_public(path, lines, regions, procs)

    # ------------------------------------------------------------------
    # BSL154 — CodeAfterAsyncCall (client command / form / managed app modules)
    # ------------------------------------------------------------------

    def _rule_bsl154_code_after_async(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        return run_bsl154_code_after_async(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL155 — CodeBlockBeforeSub
    # ------------------------------------------------------------------

    def _rule_bsl155_code_block_before_sub(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        return run_bsl155_code_block_before_sub(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL156 — CodeOutOfRegion
    # ------------------------------------------------------------------

    def _rule_bsl156_code_out_of_region(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        return run_bsl156_code_out_of_region(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL158 — CommonModuleAssign (indexed configuration)
    # ------------------------------------------------------------------

    def _rule_bsl158_common_module_assign(
        self, path: str, lines: list[str], symbol_index: Any
    ) -> list[Diagnostic]:
        return run_bsl158_common_module_assign(path, lines, symbol_index)

    # ------------------------------------------------------------------
    # BSL159 — CommonModuleInvalidType (sibling module XML)
    # ------------------------------------------------------------------

    def _rule_bsl159_common_module_invalid_type(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl159_common_module_invalid_type(path, lines)

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
        return run_bsl160_common_module_missing_api(path, lines, regions, procs)

    # ------------------------------------------------------------------
    # BSL161–BSL168 — CommonModuleName* (sibling module XML)
    # ------------------------------------------------------------------

    def _rule_bsl161_168_common_module_names(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        return run_bsl161_168_common_module_names(self._rule_enabled, path, lines, codes)

    # ------------------------------------------------------------------
    # BSL157 — CommitTransactionOutsideTryCatch
    # ------------------------------------------------------------------

    def _rule_bsl157_commit_transaction_outside_try(
        self, path: str, lines: list[str], snapshot: DocumentSnapshot | None = None
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
        pending: tuple[int, int, int] | None = None
        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines

        for idx, line in enumerate(clean_lines):
            if not line.strip():
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
                            message="Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед оператором 'Исключение'",
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
                            message="Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед оператором 'Исключение'",
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
                        message="Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед оператором 'Исключение'",
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
                    message="Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед оператором 'Исключение'",
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL173 — DeletingCollectionItem
    # ------------------------------------------------------------------

    def _rule_bsl173_deleting_collection_item(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        return run_bsl173_deleting_collection_item(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL172 — DataExchangeLoading
    # ------------------------------------------------------------------

    def _rule_bsl172_data_exchange_loading(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        return run_bsl172_data_exchange_loading(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL186 — ExtraCommas
    # ------------------------------------------------------------------

    def _rule_bsl186_extra_commas(self, path: str, lines: list[str]) -> list[Diagnostic]:
        return run_bsl186_extra_commas(path, lines)

    # ------------------------------------------------------------------
    # BSL149 — AssignAliasFieldsInQuery
    # ------------------------------------------------------------------

    def _rule_bsl149_assign_alias_fields_in_query(
        self,
        path: str,
        lines: list[str],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        query_blocks = snapshot.query_text_blocks if snapshot is not None else None
        return run_bsl149_assign_alias_fields_in_query(path, lines, query_blocks)

    # ------------------------------------------------------------------
    # BSL210 — LogicalOrInTheWhereSectionOfQuery
    # ------------------------------------------------------------------

    def _rule_bsl210_logical_or_in_where(self, path: str, lines: list[str]) -> list[Diagnostic]:
        return run_bsl210_logical_or_in_where(path, lines)

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
        return run_bsl220_235_269_273_query_text_diagnostics(
            path, lines, codes, self._rule_enabled, query_blocks
        )

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
        return run_bsl191_201_query_text_diagnostics(
            path, lines, codes, self._rule_enabled, query_blocks
        )

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
        return run_bsl192_193_194_228_266_method_contract_diagnostics(
            path, lines, procs, codes, self._rule_enabled
        )

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
            message = next(
                (_BSL204_ILLEGAL_CHARS.get(ch) for ch in line if ch in _BSL204_ILLEGAL_CHARS),
                None,
            )
            if message is None:
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx,
                    character=0,
                    end_line=line_idx,
                    end_character=len(line),
                    severity=Severity.ERROR,
                    code="BSL204",
                    message=message,
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
        return run_bsl212_missed_required_parameter(path, content, lines, procs, calls)

    def _rule_bsl206_207_209_query_join_diagnostics(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        return run_bsl206_207_209_query_join_diagnostics(
            path, lines, codes, self._rule_enabled, query_blocks
        )

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
        return run_bsl197_if_else_duplicated_code_block(path, lines)

    # ------------------------------------------------------------------
    # BSL198 — IfElseDuplicatedCondition
    # ------------------------------------------------------------------

    def _rule_bsl198_if_else_duplicated_condition(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl198_if_else_duplicated_condition(path, lines)

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
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        enabled = set(enabled_codes)
        diags: list[Diagnostic] = []
        is_common_module = bool(_RE_COMMON_MODULE_PATH.search(path))
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [_strip_inline_comment_preserve_strings(line) for line in lines]
        )

        for idx, raw_line in enumerate(lines):
            if _RE_LINE_COMMENT.match(raw_line):
                continue
            line = clean_lines[idx]
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
        return run_bsl178_deprecated_methods_8317(path, lines, tree)

    # ------------------------------------------------------------------
    # BSL258 — UnionAll
    # ------------------------------------------------------------------

    def _rule_bsl258_union_without_all(self, path: str, lines: list[str]) -> list[Diagnostic]:
        return run_bsl258_union_without_all(path, lines)

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
        return run_bsl215_missing_parameter_description(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL233 — PublicMethodsDescription
    # ------------------------------------------------------------------

    def _rule_bsl233_public_methods_description(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        return run_bsl233_public_methods_description(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL199 — IfElseIfEndsWithElse
    # ------------------------------------------------------------------

    def _rule_bsl199_if_else_if_ends_with_else(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl199_if_else_if_ends_with_else(path, lines)

    # ------------------------------------------------------------------
    # BSL200 — IncorrectLineBreak
    # ------------------------------------------------------------------

    def _rule_bsl200_incorrect_line_break(
        self,
        path: str,
        lines: list[str],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
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
        str_states = (
            snapshot.line_string_states
            if snapshot is not None
            else _build_line_string_states(lines)
        )
        comment_starts = (
            snapshot.comment_starts
            if snapshot is not None
            else [
                _comment_start_outside_double_quotes(line, str_states[idx])
                for idx, line in enumerate(lines)
            ]
        )
        query_prev_lines = _bsl200_query_first_prev_lines(lines)

        for idx, line in enumerate(lines):
            if idx in query_prev_lines:
                continue

            in_str_start = str_states[idx]
            comment_start = comment_starts[idx]

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
                            message=(
                                "Проверьте правильность переноса операндов, операторов и параметров"
                            ),
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
                    message=("Проверьте правильность переноса операндов, операторов и параметров"),
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL216 — MissingSpace
    # ------------------------------------------------------------------

    def _rule_bsl216_missing_space(
        self,
        path: str,
        lines: list[str],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        """Detect missing spaces around assignment and comparison operators."""
        comparison_ops = ("<=", ">=", "<>", "=", "<", ">")
        diags: list[Diagnostic] = []
        str_states = (
            snapshot.line_string_states
            if snapshot is not None
            else _build_line_string_states(lines)
        )
        masked_lines = (
            snapshot.masked_lines
            if snapshot is not None
            else [
                line if str_states[idx] else _mask_double_quoted_strings_preserve_len(line)
                for idx, line in enumerate(lines)
            ]
        )
        comment_starts = (
            snapshot.comment_starts
            if snapshot is not None
            else [
                _comment_start_outside_double_quotes(line, str_states[idx])
                for idx, line in enumerate(lines)
            ]
        )
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [_strip_inline_comment_preserve_strings(line) for line in lines]
        )

        for idx, line in enumerate(lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            in_str_start = str_states[idx]
            clean_full = masked_lines[idx]
            clean = clean_full
            comment_pos = comment_starts[idx]
            if comment_pos is not None:
                clean = clean[:comment_pos]
            has_equals = "=" in clean
            has_arithmetic_ops = any(op in line for op in "+-*/%")
            code_no_comments = code_lines_wo_comments[idx]
            has_comma = "," in code_no_comments
            has_semicolon = ";" in clean
            has_keyword_candidate = bool(_RE_BSL216_ANY_KEYWORD.search(clean))
            if has_equals and not _RE_BSL216_PROC_HEADER.match(clean):
                pos = 0
                seen_ops: set[tuple[int, str]] = set()
                while pos < len(clean):
                    op = None
                    for candidate in comparison_ops:
                        if clean.startswith(candidate, pos):
                            op = candidate
                            break
                    if op is None:
                        pos += 1
                        continue
                    start = pos
                    end = pos + len(op)
                    if op == "=" and (
                        (start > 0 and clean[start - 1] in "<>!")
                        or (end < len(clean) and clean[end] == "=")
                    ):
                        pos += 1
                        continue
                    left_missing = start > 0 and clean[start - 1] not in " \t"
                    right_missing = end < len(clean) and clean[end] not in " \t"
                    if left_missing or right_missing:
                        key = (start, op)
                        if key not in seen_ops:
                            seen_ops.add(key)
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
                                    character=start,
                                    end_line=idx + 1,
                                    end_character=end,
                                    severity=Severity.INFORMATION,
                                    code="BSL216",
                                    message=msg,
                                )
                            )
                    pos = end
            # Arithmetic operators: +, -, *, /
            if has_arithmetic_ops:
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
            comma_cols = (
                _comma_missing_space_after_cols_in_line(code_no_comments) if has_comma else []
            )
            if has_comma:
                extra_comma_cols = {m.start() for m in re.finditer(r",(?=\))", code_no_comments)}
                if extra_comma_cols:
                    comma_cols = sorted(set(comma_cols) | extra_comma_cols)
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
            m_semicolon = _RE_BSL216_SEMICOLON_NOSPACE.search(clean) if has_semicolon else None
            if (
                m_semicolon is None
                and has_semicolon
                and comment_pos is not None
                and comment_pos > 0
                and clean_full[comment_pos - 1] == ";"
                and clean_full[comment_pos : comment_pos + 2] == "//"
            ):
                semicolon_col = comment_pos - 1
                diags.append(
                    Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=semicolon_col,
                        end_line=idx + 1,
                        end_character=semicolon_col + 1,
                        severity=Severity.INFORMATION,
                        code="BSL216",
                        message=("Справа от ';' не хватает пробела"),
                    )
                )
                continue
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
            if has_keyword_candidate:
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
        return run_bsl254_transferring_parameters(self._symbol_index, path, lines, procs)

    # ------------------------------------------------------------------
    # BSL255 — TryNumber
    # ------------------------------------------------------------------

    def _rule_bsl255_try_number(self, path: str, lines: list[str]) -> list[Diagnostic]:
        return run_bsl255_try_number(path, lines)

    # ------------------------------------------------------------------
    # BSL183 — ExecuteExternalCode
    # ------------------------------------------------------------------

    def _rule_bsl183_execute_external_code(self, path: str, lines: list[str]) -> list[Diagnostic]:
        return run_bsl183_execute_external_code(path, lines)

    # ------------------------------------------------------------------
    # BSL208 — LatinAndCyrillicSymbolInWord
    # BSL256 — Typo (BSLLS-style: pyspellchecker + pymorphy3, bundled BSLLS exceptions)
    # ------------------------------------------------------------------

    def _rule_bsl208_bsl256_latin_cyrillic_and_typo(
        self,
        path: str,
        lines: list[str],
        procs: list[Any],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        """
        Mixed Latin/Cyrillic identifiers for **LatinAndCyrillicSymbolInWord** (BSL208).

        Spell-check **Typo** is implemented in :meth:`_rule_bsl256_bslls_typo_spellcheck`
        (Python-only engine; see :mod:`onec_hbk_bsl.analysis.bslls_typo`).
        """
        diags: list[Diagnostic] = []
        _re_comment = re.compile(r"^\s*//")
        # Emit at most once per unique identifier per file (BSL LS behaviour)
        seen_bsl208: set[str] = set()

        masked_lines = snapshot.masked_lines if snapshot is not None else None
        comment_starts = snapshot.comment_starts if snapshot is not None else None
        for idx, line in enumerate(lines):
            if _re_comment.match(line):
                continue
            clean = (
                masked_lines[idx]
                if masked_lines is not None
                else _RE_DOUBLE_QUOTED_STRING.sub('""', line)
            )
            comment_pos = comment_starts[idx] if comment_starts is not None else clean.find("//")
            if comment_pos is not None and comment_pos >= 0:
                clean = clean[:comment_pos]
            if not (_RE_BSL208_HAS_LATIN.search(clean) and _RE_BSL208_HAS_CYRILLIC.search(clean)):
                continue
            for m in _RE_BSL208_WORD.finditer(clean):
                word = m.group()
                # Skip well-known 1C platform names where Latin substrings are
                # all recognised technology acronyms (e.g. HTTPЗапрос, JSONЗапись).
                if _bsl208_word_is_standard_tech_name(word):
                    continue
                # BSLLS allowTrailingPartsInAnotherLanguage=true: skip words where
                # Latin/Cyrillic appears only as a trailing or leading block (no interleaving).
                if len(word) >= 4 and _RE_BSL208_TRAILING_LANG.match(word):
                    continue
                if not (_RE_BSL208_HAS_LATIN.search(word) and _RE_BSL208_HAS_CYRILLIC.search(word)):
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
                            severity=Severity.INFORMATION,
                            code="BSL208",
                            message="Нельзя использовать латинские и кириллические символы в одном идентификаторе",
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
        return run_bsl224_nested_function_in_parameters(path, lines, tree)

    # ------------------------------------------------------------------
    # BSL218 — MissingTemporaryFileDeletion
    # ------------------------------------------------------------------

    def _rule_bsl218_missing_temporary_file_deletion(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        return run_bsl218_missing_temporary_file_deletion(path, lines, tree)

    # ------------------------------------------------------------------
    # BSL202 / BSL205 / BSL223 / BSL243 / BSL249 — lightweight call pool
    # ------------------------------------------------------------------

    def _rule_bsl202_205_223_243_249_light_call_pool(
        self,
        path: str,
        lines: list[str],
        tree: Any,
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return []

        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [_strip_inline_comment_preserve_strings(line) for line in lines]
        )

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
            for idx, line in enumerate(clean_lines):
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
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [_strip_inline_comment_preserve_strings(line) for line in lines]
        )

        if {"BSL221", "BSL222"} & enabled_set:
            for idx, line in enumerate(clean_lines):
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
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        enabled_set = set(enabled)
        diags: list[Diagnostic] = []
        is_form_or_command = path_is_likely_form_module_bsl(path) or _path_is_command_module_bsl(
            path
        )
        clean_lines = (
            snapshot.code_lines_without_comments
            if snapshot is not None
            else [_strip_inline_comment_preserve_strings(line) for line in lines]
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
                    line = clean_lines[idx]
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
                    line = clean_lines[idx]
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
                for idx, _raw_line in enumerate(lines):
                    line = clean_lines[idx]
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
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        enabled = tuple(code for code in enabled if self._rule_enabled(code))
        if not enabled:
            return []
        return run_bsl174_187_236_238_query_metadata_pool(
            path,
            lines,
            enabled,
            query_blocks,
            snapshot.code_lines_without_comments if snapshot is not None else None,
        )

    def _rule_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        enabled = tuple(code for code in enabled if self._rule_enabled(code))
        if not enabled:
            return []
        return run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
            path,
            lines,
            procs,
            enabled,
            snapshot.code_lines_without_comments if snapshot is not None else None,
        )

    def _rule_bsl244_253_261_runtime_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        return run_bsl244_253_261_runtime_pool(
            path,
            lines,
            procs,
            enabled,
            snapshot.code_lines_without_comments if snapshot is not None else None,
        )

    # ------------------------------------------------------------------
    # BSL225 — NumberOfValuesInStructureConstructor
    # ------------------------------------------------------------------

    def _rule_bsl225_number_of_values_in_structure_constructor(
        self, path: str, lines: list[str], tree: Any
    ) -> list[Diagnostic]:
        return run_bsl225_number_of_values_in_structure_constructor(path, lines, tree)

    # ------------------------------------------------------------------
    # BSL234 — QueryNestedFieldsByDot
    # ------------------------------------------------------------------

    def _rule_bsl234_query_nested_fields_by_dot(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl234_query_nested_fields_by_dot(path, lines)

    # ------------------------------------------------------------------
    # BSL237 — RedundantAccessToObject
    # ------------------------------------------------------------------

    def _rule_bsl237_redundant_access_to_object(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl237_redundant_access_to_object(path, lines)

    # ------------------------------------------------------------------
    # BSL245 — ServerSideExportFormMethod
    # ------------------------------------------------------------------

    def _rule_bsl245_server_side_export_form_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        return run_bsl245_server_side_export_form_method(path, lines, procs)

    # ------------------------------------------------------------------
    # BSL230 — PairingBrokenTransaction
    # ------------------------------------------------------------------

    def _rule_bsl230_pairing_broken_transaction(self, path: str, tree: Any) -> list[Diagnostic]:
        return run_bsl230_pairing_broken_transaction(path, tree)

    # ------------------------------------------------------------------
    # BSL277 — WrongUseOfRollbackTransactionMethod
    # ------------------------------------------------------------------

    def _rule_bsl277_wrong_use_of_rollback_transaction(
        self, path: str, tree: Any
    ) -> list[Diagnostic]:
        return run_bsl277_wrong_use_of_rollback_transaction(path, tree)

    # ------------------------------------------------------------------
    # BSL262 — UsageWriteLogEvent
    # ------------------------------------------------------------------

    def _rule_bsl262_usage_write_log_event(self, path: str, tree: Any) -> list[Diagnostic]:
        return run_bsl262_usage_write_log_event(path, tree)

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
        return run_bsl240_rewrite_method_parameter(path, lines, procs, tree, proc_node_map)

    # ------------------------------------------------------------------
    # BSL263 — UseLessForEach
    # ------------------------------------------------------------------

    def _rule_bsl263_useless_for_each(
        self, path: str, lines: list[str], procs: list[Any]
    ) -> list[Diagnostic]:
        return run_bsl263_useless_for_each(path, lines)

    # ------------------------------------------------------------------
    # BSL265 — UselessTernaryOperator
    # ------------------------------------------------------------------

    def _rule_bsl265_useless_ternary_operator(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl265_useless_ternary_operator(path, lines)

    # ------------------------------------------------------------------
    # BSL257 — UnaryPlusInConcatenation
    # ------------------------------------------------------------------

    def _rule_bsl257_unary_plus_in_concatenation(
        self, path: str, lines: list[str]
    ) -> list[Diagnostic]:
        return run_bsl257_unary_plus_in_concatenation(path, lines)

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
                        message='В текстах модулях не допускается использовать букву "Ё".',
                    )
                )
        return diags
