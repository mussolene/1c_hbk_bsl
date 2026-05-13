"""DiagnosticEngine extracted from diagnostics facade.

This module intentionally imports the diagnostics facade to reuse the existing
module-level helpers, constants, and rule implementations while the remaining
rule bodies are migrated out of ``diagnostics.py``.
"""

# ruff: noqa: F403,F405

from __future__ import annotations

from collections import OrderedDict

import onec_hbk_bsl.analysis.diagnostics as _diag
from onec_hbk_bsl.analysis.diagnostic.domain import ModuleModel, ProcedureModel
from onec_hbk_bsl.analysis.diagnostic.pipeline import AnalysisFrame, PipelineExecutor
from onec_hbk_bsl.analysis.diagnostic.suppression import (
    is_suppressed,
    parse_suppressions,
)
from onec_hbk_bsl.analysis.diagnostics import *  # noqa: F401,F403

_HOT_TS_NODE_TYPES: frozenset[str] = frozenset(
    {
        "ERROR",
        "assignment_statement",
        "function_definition",
        "method_call",
        "new_expression",
        "preprocessor",
        "procedure_definition",
        "ternary_expression",
        "try_statement",
    }
)

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

    # BSLLS-compatible rules disabled by default.
    DEFAULT_DISABLED: frozenset[str] = frozenset(
        {
            "BSL008",
            "BSL016",
            "BSL042",
            "BSL150",
            "BSL154",
            "BSL169",
            "BSL170",
            "BSL174",
            "BSL181",
            "BSL182",
            "BSL187",
            "BSL188",
            "BSL189",
            "BSL196",
            "BSL203",
            "BSL211",
            "BSL213",
            "BSL214",
            "BSL217",
            "BSL231",
            "BSL232",
            "BSL236",
            "BSL238",
            "BSL241",
            "BSL242",
            "BSL244",
            "BSL246",
            "BSL251",
            "BSL253",
            "BSL260",
            "BSL261",
            "BSL264",
            "BSL274",
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
        self._current_snapshot: Any | None = None
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
        try:
            _cache_limit = int(os.environ.get("BSL_DIAG_CONTENT_CACHE_LIMIT", "64").strip())
        except TypeError, ValueError:
            _cache_limit = 64
        self._content_diag_cache_limit = max(0, _cache_limit)
        # Cache by path and validate content on reuse; avoids per-call hashing on one-shot files.
        self._content_diag_cache: OrderedDict[str, tuple[str, list[Diagnostic]]] = OrderedDict()
        self._content_diag_cache_lock = threading.RLock()

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
        if code not in RULE_METADATA:
            return False
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

        *symbol_index* is optional; when set, enables metadata-aware BSLLS rules.
        """
        cache_key: str | None = None
        if symbol_index is None and self._content_diag_cache_limit > 0:
            cache_key = path
            with self._content_diag_cache_lock:
                cached_entry = self._content_diag_cache.get(cache_key)
                if cached_entry is not None and cached_entry[0] == content:
                    self._content_diag_cache.move_to_end(cache_key)
                    return list(cached_entry[1])

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
        diagnostics = self._run_rules(path, content, tree, symbol_index=symbol_index)

        if cache_key is not None:
            with self._content_diag_cache_lock:
                self._content_diag_cache[cache_key] = (content, diagnostics)
                self._content_diag_cache.move_to_end(cache_key)
                while len(self._content_diag_cache) > self._content_diag_cache_limit:
                    self._content_diag_cache.popitem(last=False)
        return diagnostics

    def check_snapshot(
        self,
        snapshot: Any,
        *,
        symbol_index: Any | None = None,
    ) -> list[Diagnostic]:
        """Run diagnostics on an already parsed :class:`DocumentSnapshot`."""
        return self._run_rules(
            snapshot.path,
            snapshot.content,
            snapshot.tree,
            symbol_index=symbol_index,
            snapshot=snapshot,
        )

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

        *symbol_index* is optional; when set, enables metadata-aware BSLLS rules.
        """
        content: str
        if tree is None:
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
                        message=f"Failed to parse file: {exc}",
                    )
                ]
        else:
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
        snapshot: Any | None = None,
    ) -> list[Diagnostic]:
        """Execute all enabled rules and return filtered, sorted diagnostics."""
        if snapshot is None:
            snapshot = build_document_snapshot(
                path,
                content=content,
                tree=tree,
                parser=self._get_parser(),
            )
        tree = snapshot.tree
        lines = snapshot.lines
        self._current_lines = lines
        suppressions = parse_suppressions(lines)

        # Precompute structural info once (shared across rules).
        # Prefer CST-based extraction (handles multi-line signatures, exact
        # boundaries); fall back to regex when tree-sitter is unavailable.
        tree_is_ts = snapshot.is_tree_sitter
        procs = snapshot.procedures
        proc_source = "ast" if tree_is_ts else "regex"
        regions = snapshot.regions
        regions_source = "ast" if tree_is_ts else "regex"
        last_metrics: dict[str, Any] = {
            "tree_is_ts": bool(tree_is_ts),
            "proc_source": proc_source,
            "regions_source": regions_source,
        }
        last_metrics.update(
            {
                "procs_count": len(procs),
                "regions_count": len(regions),
                "rule_invoke": build_enabled_invoke_snapshot(self, RULE_METADATA),
            }
        )
        self._metrics_tls.data = last_metrics
        self._current_snapshot = snapshot

        frame = AnalysisFrame(
            path=path,
            content=content,
            tree=tree,
            snapshot=snapshot,
            lines=lines,
            symbol_index=symbol_index,
        )
        diagnostics = PipelineExecutor().execute(self, frame)
        # Apply inline suppressions
        diagnostics = [d for d in diagnostics if not is_suppressed(d, suppressions)]
        _str_ranges = double_quoted_string_ranges(content)
        if _str_ranges:
            _line_starts = line_start_offsets(content)
            _str_range_starts = [start for start, _ in _str_ranges]
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
                    range_starts=_str_range_starts,
                )
            ]
        return sorted(diagnostics, key=lambda d: (d.line, d.character))

    def _complexity_metrics_for_procs(
        self, lines: list[str], procs: list[_ProcInfo]
    ) -> list[tuple[int, int]]:
        """Return cached ``(cognitive, mccabe)`` metrics for current file procedures."""
        snapshot = self._current_snapshot
        if snapshot is not None and getattr(snapshot, "lines", None) is lines:
            return snapshot.complexity_metrics_for_procs(
                procs,
                calculator=_calc_complexity_metrics,
            )
        string_states = _build_line_string_states(lines)
        return [
            _calc_complexity_metrics(
                lines, proc.start_idx, proc.end_idx, string_states=string_states
            )
            for proc in procs
        ]

    def _global_method_calls_from_nodes(
        self, method_call_nodes: list[Any], line_texts: list[str]
    ) -> list[dict[str, Any]]:
        """Collect global method calls from an already materialised ``method_call`` node list."""
        out: list[dict[str, Any]] = []
        for node in method_call_nodes:
            if getattr(getattr(node, "parent", None), "type", None) == "call_expression":
                continue
            span = _ts_method_identifier_span(node, line_texts)
            if span is None:
                continue
            ident = _ts_child_of_type(node, "identifier")
            out.append(
                {
                    "node": node,
                    "name": _ts_node_text(ident),
                    "line": span[0],
                    "character": span[1],
                    "end_character": span[2],
                }
            )
        return out

    def _ts_nodes_for_types(self, tree: Any, node_types: set[str]) -> dict[str, list[Any]]:
        """Return materialised CST nodes grouped by type for current file."""
        snapshot = self._current_snapshot
        if snapshot is not None and getattr(snapshot, "tree", None) is tree:
            return snapshot.ts_nodes_for_types(
                node_types,
                hot_node_types=_HOT_TS_NODE_TYPES,
                walker=_ts_walk,
            )
        root = getattr(tree, "root_node", None)
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return {node_type: [] for node_type in node_types}
        collected_types = set(node_types) | set(_HOT_TS_NODE_TYPES)
        grouped = {node_type: [] for node_type in collected_types}
        for node in _ts_walk(root):
            node_type = getattr(node, "type", None)
            if node_type in grouped:
                grouped[node_type].append(node)
        return {node_type: grouped.get(node_type, []) for node_type in node_types}

    def _runtime_call_context(
        self, tree: Any, lines: list[str]
    ) -> tuple[list[dict[str, Any]], list[int], list[Any], list[Any]]:
        """Shared CST context for runtime rules that scan global method calls."""
        snapshot = self._current_snapshot
        if snapshot is not None and getattr(snapshot, "tree", None) is tree:
            cached = snapshot.get_runtime_call_context()
            if cached is not None:
                return cached
        nodes = self._ts_nodes_for_types(
            tree,
            {"method_call", "procedure_definition", "function_definition", "try_statement"},
        )
        global_calls = self._global_method_calls_from_nodes(nodes["method_call"], lines)
        global_call_starts = [
            getattr(call["node"], "start_byte", -1) for call in global_calls
        ]
        proc_nodes = nodes["procedure_definition"] + nodes["function_definition"]
        context = (global_calls, global_call_starts, proc_nodes, nodes["try_statement"])
        if snapshot is not None and getattr(snapshot, "tree", None) is tree:
            snapshot.set_runtime_call_context(context)
        return context

    # ------------------------------------------------------------------
    # BSL001 — Parse errors
    # ------------------------------------------------------------------

    def _rule_bsl001_syntax_errors(self, path: str, tree: Any) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl001_syntax_errors(
            tree=tree,
            parser_extract_errors_fn=self._get_parser().extract_errors,
            current_lines=getattr(self, "_current_lines", []),
        )

    # ------------------------------------------------------------------
    # BSL002 — Method too long
    # ------------------------------------------------------------------

    def _rule_bsl002_method_size(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl002_method_size(
            lines=lines,
            procs=procs,
            procedure_model_from_proc_info_fn=ProcedureModel.from_proc_info,
            max_proc_lines=self.max_proc_lines,
            mask_strings_and_comments_for_counter_fn=_mask_strings_and_comments_for_counter,
            proc_name_span_fn=_proc_name_span,
        )

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
        model = ModuleModel(path=path)
        return model.validate_bsl003_non_export_in_api_region(
            lines=lines,
            procs=procs,
            regions=regions,
            api_region_names=_API_REGION_NAMES,
            procedure_model_from_proc_info_fn=ProcedureModel.from_proc_info,
            proc_name_span_fn=_proc_name_span,
        )

    # ------------------------------------------------------------------
    # BSL004 — EmptyCodeBlock
    # ------------------------------------------------------------------

    def _rule_bsl004_empty_except(self, path: str, lines: list[str], tree: Any) -> list[Diagnostic]:
        _ = tree
        model = ModuleModel(path=path)
        return model.validate_bsl004_empty_code_block(lines=lines)

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
        model = ModuleModel(path=path)
        return model.validate_bsl007_unused_local_variable(
            lines=lines,
            procs=procs,
            snapshot=snapshot,
            strip_inline_comment_preserve_strings_fn=_strip_inline_comment_preserve_strings,
            bsl007_strip_double_quoted_segments_fn=_bsl007_strip_double_quoted_segments,
            bsl007_simple_assign_at_start_re=_BSL007_SIMPLE_ASSIGN_AT_START,
            var_local_re=_RE_VAR_LOCAL,
            region_line_re=_RE_REGION_LINE,
            preproc_line_re=_RE_PREPROC_LINE,
            compiler_directive_re=_RE_COMPILER_DIRECTIVE,
            module_assign_re=_RE_MODULE_ASSIGN,
        )

    # ------------------------------------------------------------------
    # BSL008 — Too many return statements
    # ------------------------------------------------------------------

    def _rule_bsl008_too_many_returns(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_max_returns(
                    lines,
                    max_returns=self.max_returns,
                    return_re=_RE_RETURN,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL009 — Self-assignment
    # ------------------------------------------------------------------

    def _rule_bsl009_self_assign(self, path: str, lines: list[str], tree: Any) -> list[Diagnostic]:
        if not _ts_tree_ok_for_rules(tree):
            return []
        return _diagnostics_bsl009_from_tree(path, tree.root_node)

    # ------------------------------------------------------------------
    # BSL011 — Cognitive complexity
    # ------------------------------------------------------------------

    def _rule_bsl011_cognitive_complexity(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        metrics = self._complexity_metrics_for_procs(lines, procs)
        for proc, (cc, _mc) in zip(procs, metrics, strict=False):
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_cognitive_complexity(
                    cognitive_complexity=cc,
                    max_cognitive_complexity=self.max_cognitive_complexity,
                    proc_name_span=_proc_name_span,
                    lines=lines,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL012 — Hardcoded credentials
    # ------------------------------------------------------------------

    def _rule_bsl012_hardcode_credentials(self, path: str, lines: list[str]) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_hardcoded_credentials(lines, credentials_re=_RE_CREDENTIALS)

    # ------------------------------------------------------------------
    # BSL013 — Commented-out code
    # ------------------------------------------------------------------

    def _rule_bsl013_commented_code(self, path: str, lines: list[str]) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_commented_code(
            lines,
            commented_code_re=_RE_COMMENTED_CODE,
            min_commented_code_block=self.MIN_COMMENTED_CODE_BLOCK,
        )

    # ------------------------------------------------------------------
    # BSL014 — Line too long
    # ------------------------------------------------------------------

    def _rule_bsl014_line_too_long(
        self, path: str, lines: list[str], snapshot: DocumentSnapshot | None = None
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_line_too_long(
            lines,
            max_line_length=self.max_line_length,
            snapshot=snapshot,
        )

    # ------------------------------------------------------------------
    # BSL015 — Too many optional parameters
    # ------------------------------------------------------------------

    def _rule_bsl015_optional_params_count(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_optional_param_limit(
                    lines,
                    max_optional_params=self.max_optional_params,
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
        model = ModuleModel(path=path)
        return model.validate_non_standard_regions(
            lines,
            regions=regions,
            standard_regions_for_path=_standard_regions_for_path,
            is_standard_region_name_for_path=_is_standard_region_name_for_path,
        )

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
        model = ModuleModel(path=path)
        return model.validate_export_in_command_or_form_module(lines, procs=procs)

    # ------------------------------------------------------------------
    # BSL019 — McCabe cyclomatic complexity
    # ------------------------------------------------------------------

    def _rule_bsl019_cyclomatic_complexity(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        metrics = self._complexity_metrics_for_procs(lines, procs)
        for proc, (_cog, cc) in zip(procs, metrics, strict=False):
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_mccabe_complexity(
                    mccabe_complexity=cc,
                    max_mccabe_complexity=self.max_mccabe_complexity,
                    proc_name_span=_proc_name_span,
                    lines=lines,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL020 — Excessive nesting depth
    # ------------------------------------------------------------------

    def _rule_bsl020_excessive_nesting(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_excessive_nesting(
            lines,
            procs=procs,
            max_nesting_depth=self.max_nesting_depth,
        )

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
        model = ModuleModel(path=path)
        return model.validate_deprecated_warning(
            lines,
            procs=procs,
            deprecated_message_re=_RE_DEPRECATED_MSG,
            proc_containing_line=_proc_containing_line,
            is_typical_client_command_handler=_is_typical_client_command_handler,
        )

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
        model = ModuleModel(path=path)
        return model.validate_statement_missing_semicolon(
            lines,
            procs=procs,
            stmt_no_semi_re=_RE_STMT_NO_SEMI,
            double_quoted_string_re=_RE_DOUBLE_QUOTED_STRING,
            single_quoted_string_re=_RE_SINGLE_QUOTED_STRING,
        )

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
        model = ModuleModel(path=path)
        return model.validate_empty_regions(lines, regions=regions)

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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_missing_try_catch(
                    lines,
                    try_block_re=self._RE_TRY_BLOCK,
                    try_close_re=self._RE_TRY_CLOSE,
                    risky_call_re=self._RE_RISKY_CALL,
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
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_magic_numbers(
                    lines,
                    snapshot=snapshot,
                    any_digit_re=_RE_BSL029_ANY_DIGIT,
                    simple_assign_re=_RE_BSL029_SIMPLE_ASSIGN,
                    ternary_re=_RE_BSL029_TERNARY,
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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(model.validate_param_limit(lines, max_params=self.max_params))
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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_function_has_return(
                    lines,
                    return_re=_RE_RETURN,
                    proc_name_span=_proc_name_span,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL148 — AllFunctionPathMustHaveReturn
    # ------------------------------------------------------------------

    def _rule_bsl148_all_function_paths_return(self, path: str, tree: Any) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_function_paths_return(
            tree=tree,
            bsl148_function_name_spans=bsl148_function_name_spans,
            loops_executed_at_least_once=self.bsl148_loops_executed_at_least_once,
        )

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
        loop_lines: set[int] | None = None
        if _ts_tree_ok_for_rules(tree):
            loop_lines = loop_body_line_indices_0(tree.root_node)
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_query_in_loop(
                    lines,
                    loop_lines=loop_lines,
                    query_execute_re=_RE_QUERY_EXECUTE,
                    loop_open_re=_RE_LOOP_OPEN,
                    loop_close_re=_RE_LOOP_CLOSE,
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
        model = ModuleModel(path=path)
        return model.validate_duplicate_string_literal(
            lines,
            procs=procs,
            snapshot=snapshot,
            min_duplicate_uses=self.min_duplicate_uses,
            string_literal_re=_RE_STRING_LITERAL,
            scope_line_indices_fn=_bsl035_scope_line_indices,
            line_starts_with_raise_statement_fn=_line_starts_with_raise_statement,
        )

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
        model = ModuleModel(path=path)
        return model.validate_complex_condition(
            lines=lines,
            max_bool_ops=self.max_bool_ops,
            bool_op_re=_RE_BOOL_OP,
        )

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
        model = ModuleModel(path=path)
        return model.validate_this_form_usage(
            lines,
            procs=procs,
            path_is_likely_form_module_bsl=path_is_likely_form_module_bsl,
            proc_containing_line=_proc_containing_line,
            mask_double_quoted_strings_preserve_len=_mask_double_quoted_strings_preserve_len,
            this_form_re=_RE_THIS_FORM,
        )

    # ------------------------------------------------------------------
    # BSL042 — Empty export method
    # ------------------------------------------------------------------

    def _rule_bsl042_empty_export_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag exported methods that have no meaningful body (only comments/blanks)."""
        model = ModuleModel(path=path)
        return model.validate_bsl042_empty_export_method(
            lines=lines,
            procs=procs,
            procedure_model_from_proc_info_fn=ProcedureModel.from_proc_info,
            blank_or_comment_re=_RE_BLANK_OR_COMMENT,
        )

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    MAX_VARIABLES: int = 15

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
        model = ModuleModel(path=path)
        return model.validate_bsl051_unreachable_code(
            lines=lines,
            procs=procs,
            tree=tree,
            bsl051_delimiter_lines_for_tree_fn=_bsl051_delimiter_lines_for_tree,
            bsl051_all_branch_exit_end_if_lines_fn=self._bsl051_all_branch_exit_end_if_lines,
            re_unconditional_exit=_RE_UNCONDITIONAL_EXIT,
            re_bsl051_delimiter_fallback=_RE_BSL051_DELIMITER_FALLBACK,
        )

    @staticmethod
    def _bsl051_all_branch_exit_end_if_lines(body_lines: list[tuple[int, str]]) -> set[int]:
        if_start_re = re.compile(r"^\s*(?:Если|If)\b.*(?:Тогда|Then)\s*$", re.IGNORECASE)
        elseif_re = re.compile(r"^\s*(?:ИначеЕсли|ElseIf|ElsIf)\b", re.IGNORECASE)
        else_re = re.compile(r"^\s*(?:Иначе|Else)\b", re.IGNORECASE)
        endif_re = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)

        stack: list[dict[str, Any]] = []
        result: set[int] = set()

        def current_exits() -> bool:
            return bool(stack and stack[-1]["current_exit"])

        for abs_idx, line in body_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue

            if if_start_re.match(line):
                stack.append({"branches": [], "current_exit": False, "has_else": False})
                continue

            if not stack:
                continue

            if _RE_UNCONDITIONAL_EXIT.match(line) and ";" in line:
                stack[-1]["current_exit"] = True
                continue

            if elseif_re.match(line):
                stack[-1]["branches"].append(current_exits())
                stack[-1]["current_exit"] = False
                continue

            if else_re.match(line):
                stack[-1]["branches"].append(current_exits())
                stack[-1]["current_exit"] = False
                stack[-1]["has_else"] = True
                continue

            if endif_re.match(line):
                finished = stack.pop()
                finished["branches"].append(finished["current_exit"])
                exits = bool(finished["has_else"] and all(finished["branches"]))
                if exits:
                    result.add(abs_idx)
                    if stack:
                        stack[-1]["current_exit"] = True
                continue

        return result

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

        return []

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
        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines
        model = ModuleModel(path=path)
        return model.validate_module_level_export_variables(
            lines,
            procs=procs,
            var_module_export_re=_RE_VAR_MODULE_EXPORT,
            clean_lines=clean_lines,
        )

    # ------------------------------------------------------------------
    # BSL219 — MissingVariablesDescription (module Перем)
    # ------------------------------------------------------------------

    def _rule_bsl219_missing_variables_description(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        """
        Flag module-level ``Перем`` without a preceding ``//`` / ``///`` description line.

        Aligns with BSLLS ``MissingVariablesDescription`` for module variables.
        """
        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines
        model = ModuleModel(path=path)
        return model.validate_module_variables_description(
            lines,
            procs=procs,
            var_module_re=_RE_VAR_MODULE,
            clean_lines=clean_lines,
            has_preceding_description=_module_export_var_has_preceding_description,
        )

    MIN_METHOD_NAME_LEN: int = 3

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
        model = ModuleModel(path=path)
        return model.validate_bsl062_unused_parameter(
            lines=lines,
            procs=procs,
            tree=tree,
            proc_node_map=proc_node_map,
            path_is_likely_form_module_bsl_fn=path_is_likely_form_module_bsl,
            find_proc_definition_node_fn=_find_proc_definition_node,
            collect_identifier_casefolds_in_proc_body_fn=_collect_identifier_casefolds_in_proc_body,
            procedure_model_from_proc_info_fn=ProcedureModel.from_proc_info,
            bsl062_skip_standard_command_params=_BSL062_SKIP_STANDARD_COMMAND_PARAMS,
            is_typical_client_command_handler_fn=_is_typical_client_command_handler,
            is_client_notify_completion_export_handler_fn=(
                _is_client_notify_completion_export_handler
            ),
        )

    # ------------------------------------------------------------------
    # BSL064 — Procedure returns value
    # ------------------------------------------------------------------

    def _rule_bsl064_procedure_returns_value(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """
        Flag a Процедура body that contains 'Возврат <value>' — it should be a Функция.
        """
        model = ModuleModel(path=path)
        return model.validate_bsl064_procedure_returns_value(
            lines=lines,
            procs=procs,
            procedure_model_from_proc_info_fn=ProcedureModel.from_proc_info,
            return_value_re=_RE_RETURN_VALUE,
            proc_header_re=_RE_PROC_HEADER,
        )

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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_missing_export_comment(
                    lines,
                    compiler_directive_re=_RE_COMPILER_DIRECTIVE,
                    bsl215_comment_line_re=_RE_BSL215_COMMENT_LINE,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    MAX_ELSEIF_BRANCHES: int = 5

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    # Numbers always allowed (too common/obvious to flag)
    _MAGIC_NUMBER_ALLOWED: frozenset[str] = frozenset({"0", "1", "2", "-1", "100"})

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    MAX_IF_DEPTH_FOR_ELSE_CHECK: int = 1  # only top-level if-blocks

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
        model = ModuleModel(path=path)
        return model.validate_select_top_without_order_by(
            query_blocks=blocks_iter,
            query_top_re=_RE_QUERY_TOP,
            query_union_re=_RE_QUERY_UNION,
            query_where_re=_RE_QUERY_WHERE,
            query_order_by_re=_RE_QUERY_ORDER_BY,
        )

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    MAX_METHOD_CHAIN_DEPTH: int = 5

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    MAX_MODULE_VARIABLES: int = 10

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # BSL131 — DuplicateRegion
    # ------------------------------------------------------------------

    def _rule_bsl131_duplicate_region(
        self, path: str, lines: list[str], regions: list[_RegionInfo]
    ) -> list[Diagnostic]:
        """Detect duplicated region names, including BSLLS standard-region synonyms."""
        model = ModuleModel(path=path)
        return model.validate_duplicate_regions(lines, regions=regions)

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
        model = ModuleModel(path=path)
        return model.validate_bsl171_204_217_248_251_252_259_268_light_pool(
            content=content,
            lines=lines,
            tree=tree,
            procs=procs,
            codes=codes,
            rule_enabled_fn=self._rule_enabled,
            ts_nodes_for_types_fn=self._ts_nodes_for_types,
            rule_bsl171_fn=self._rule_bsl171_crazy_multiline_string,
            rule_bsl204_fn=self._rule_bsl204_invalid_character_in_file,
            rule_bsl217_fn=self._rule_bsl217_missing_temp_storage_deletion,
            rule_bsl248_fn=self._rule_bsl248_several_compiler_directives,
            rule_bsl251_fn=self._rule_bsl251_ternary_operator_usage,
            rule_bsl252_fn=self._rule_bsl252_this_object_assign,
            rule_bsl259_fn=self._rule_bsl259_unknown_preprocessor_symbol,
            rule_bsl268_fn=self._rule_bsl268_using_find_element_by_string,
        )

    def _rule_bsl171_crazy_multiline_string(
        self, path: str, lines: list[str], tree: Any | None, error_nodes: list[Any] | None = None
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_crazy_multiline_string(
            lines=lines,
            tree=tree,
            error_nodes=error_nodes,
            ts_walk_fn=_ts_walk,
            ts_node_text_fn=_ts_node_text,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            adjacent_literals_re=_RE_BSL171_ADJACENT_LITERALS,
            rule_descriptions_ru=RULE_DESCRIPTIONS_RU,
        )

    def _rule_bsl204_invalid_character_in_file(
        self, path: str, content: str, lines: list[str]
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_invalid_character_in_file(lines=lines, illegal_chars=_BSL204_ILLEGAL_CHARS)

    def _rule_bsl217_missing_temp_storage_deletion(
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        method_call_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl217_missing_temp_storage_deletion(
            lines=lines,
            tree=tree,
            method_call_nodes=method_call_nodes,
            global_method_calls_from_nodes_fn=self._global_method_calls_from_nodes,
            ts_global_method_calls_fn=_ts_global_method_calls,
            bsl217_get_from_temp_storage_names=_BSL217_GET_FROM_TEMP_STORAGE_NAMES,
            ts_method_identifier_span_fn=_ts_method_identifier_span,
            ts_assignment_lvalue_text_fn=_ts_assignment_lvalue_text,
            ts_bsl218_skip_error_ancestor_fn=_ts_bsl218_skip_error_ancestor,
            ts_bsl218_code_block_roots_fn=_ts_bsl218_code_block_roots,
            bsl217_delete_from_temp_storage_names=_BSL217_DELETE_FROM_TEMP_STORAGE_NAMES,
            ts_method_call_arg_exprs_fn=_ts_method_call_arg_exprs,
            ts_node_text_fn=_ts_node_text,
            rule_descriptions_ru=RULE_DESCRIPTIONS_RU,
        )

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
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        ternary_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_ternary_operator_usage(
            lines=lines,
            tree=tree,
            ternary_nodes=ternary_nodes,
            ts_walk_fn=_ts_walk,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            rule_descriptions_ru=RULE_DESCRIPTIONS_RU,
        )

    def _rule_bsl252_this_object_assign(
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        assignment_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_this_object_assign(
            path=path,
            lines=lines,
            tree=tree,
            assignment_nodes=assignment_nodes,
            path_is_likely_form_module_bsl=path_is_likely_form_module_bsl,
            common_module_path_re=_RE_COMMON_MODULE_PATH,
            ts_walk_fn=_ts_walk,
            ts_child_of_type_fn=_ts_child_of_type,
            ts_node_text_fn=_ts_node_text,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            rule_descriptions_ru=RULE_DESCRIPTIONS_RU,
        )

    def _rule_bsl259_unknown_preprocessor_symbol(
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        preprocessor_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_unknown_preprocessor_symbol(
            lines=lines,
            tree=tree,
            preprocessor_nodes=preprocessor_nodes,
            ts_walk_fn=_ts_walk,
            ts_child_of_type_fn=_ts_child_of_type,
            ts_node_text_fn=_ts_node_text,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            allowed_preproc_symbols=_BSL259_ALLOWED_PREPROC_SYMBOLS,
            preproc_keywords=_BSL259_PREPROC_KEYWORDS,
            preproc_if_re=_RE_BSL259_PREPROC_IF,
            preproc_identifier_re=_RE_BSL259_IDENTIFIER,
        )

    def _rule_bsl268_using_find_element_by_string(
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        method_call_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_using_find_element_by_string(
            lines=lines,
            tree=tree,
            method_call_nodes=method_call_nodes,
            ts_walk_fn=_ts_walk,
            ts_child_of_type_fn=_ts_child_of_type,
            ts_node_text_fn=_ts_node_text,
            ts_method_call_arg_exprs_fn=_ts_method_call_arg_exprs,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            method_name_re=_RE_BSL268_FIND_BY_STRING,
            line_comment_re=_RE_LINE_COMMENT,
            mask_double_quoted_strings_preserve_len_fn=_mask_double_quoted_strings_preserve_len,
        )

    # ------------------------------------------------------------------
    # BSL190 — FormDataToValue
    # ------------------------------------------------------------------

    def _rule_bsl190_form_data_to_value(self, path: str, lines: list[str]) -> list[Diagnostic]:
        """Flag calls to ДанныеФормыВЗначение()/FormDataToValue() — slow operation.

        BSLLS: prefer working with server objects directly instead of converting
        form data to value, which involves full serialization/deserialization.
        """
        model = ModuleModel(path=path)
        return model.validate_form_data_to_value(
            lines=lines,
            line_comment_re=_RE_LINE_COMMENT,
            double_quoted_string_re=_RE_DOUBLE_QUOTED_STRING,
            bsl190_form_data_re=_RE_BSL190_FORM_DATA,
        )

    # ------------------------------------------------------------------
    # BSL175 / BSL176 — deprecated API pool
    # ------------------------------------------------------------------

    def _rule_bsl175_176_177_179_195_deprecated_api_diagnostics(
        self,
        path: str,
        lines: list[str],
        symbols: list[Any],
        calls: list[Any],
        enabled_codes: tuple[str, ...],
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
            lines=lines,
            symbols=symbols,
            calls=calls,
            enabled_codes=enabled_codes,
            line_comment_re=_RE_LINE_COMMENT,
            bsl176_deprecated_doc_re=_RE_BSL176_DEPRECATED_DOC,
            mask_double_quoted_strings_preserve_len_fn=_mask_double_quoted_strings_preserve_len,
            bsl175_attribute_re=_RE_BSL175_ATTRIBUTE,
            bsl175_attr_replacements=_BSL175_ATTR_REPLACEMENTS,
            bsl175_method_replacements=_BSL175_METHOD_REPLACEMENTS,
            bsl175_child_form_items_re=_RE_BSL175_CHILD_FORM_ITEMS,
            bsl175_enum_replacements=_BSL175_ENUM_REPLACEMENTS,
            bsl175_enum_name_re=_RE_BSL175_ENUM_NAME,
            bsl175_global_method_re=_RE_BSL175_GLOBAL_METHOD,
            bsl175_global_methods=_BSL175_GLOBAL_METHODS,
        )

    # ------------------------------------------------------------------
    # BSL215 — MissingParameterDescription
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL233 — PublicMethodsDescription
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL216 — MissingSpace
    # ------------------------------------------------------------------

    def _rule_bsl216_missing_space(
        self,
        path: str,
        lines: list[str],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_missing_space(
            lines=lines,
            snapshot=snapshot,
            line_comment_re=_RE_LINE_COMMENT,
            build_line_string_states_fn=_build_line_string_states,
            mask_double_quoted_strings_preserve_len_fn=_mask_double_quoted_strings_preserve_len,
            comment_start_outside_double_quotes_fn=_comment_start_outside_double_quotes,
            strip_inline_comment_preserve_strings_fn=_strip_inline_comment_preserve_strings,
            proc_header_re=_RE_BSL216_PROC_HEADER,
            any_keyword_re=_RE_BSL216_ANY_KEYWORD,
            arithmetic_missing_space_cols_in_line_fn=_arithmetic_missing_space_cols_in_line,
            comma_missing_space_after_cols_in_line_fn=_comma_missing_space_after_cols_in_line,
            semicolon_nospace_re=_RE_BSL216_SEMICOLON_NOSPACE,
            left_right_keywords_re=_RE_BSL216_LEFT_RIGHT_KEYWORDS,
            left_keywords_re=_RE_BSL216_LEFT_KEYWORDS,
            right_keywords_re=_RE_BSL216_RIGHT_KEYWORDS,
        )

    # ------------------------------------------------------------------
    # BSL254 — TransferringParametersBetweenClientAndServer
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
        model = ModuleModel(path=path)
        return model.validate_bsl208_latin_cyrillic_symbol_in_word(
            lines=lines,
            snapshot=snapshot,
            rule_enabled_fn=self._rule_enabled,
            re_double_quoted_string=_RE_DOUBLE_QUOTED_STRING,
            re_bsl208_has_latin=_RE_BSL208_HAS_LATIN,
            re_bsl208_has_cyrillic=_RE_BSL208_HAS_CYRILLIC,
            re_bsl208_word=_RE_BSL208_WORD,
            re_bsl208_trailing_lang=_RE_BSL208_TRAILING_LANG,
            bsl208_word_is_standard_tech_name_fn=_bsl208_word_is_standard_tech_name,
        )

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

    # ------------------------------------------------------------------
    # BSL202 / BSL223 / BSL243 / BSL249 — lightweight call pool
    # ------------------------------------------------------------------

    def _rule_bsl202_205_223_243_249_light_call_pool(
        self,
        path: str,
        lines: list[str],
        tree: Any,
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl202_205_223_243_249_light_call_pool(
            lines=lines,
            tree=tree,
            enabled=enabled,
            snapshot=snapshot,
            strip_inline_comment_preserve_strings_fn=_strip_inline_comment_preserve_strings,
            ts_nodes_for_types_fn=self._ts_nodes_for_types,
            ts_child_of_type_fn=_ts_child_of_type,
            ts_node_text_fn=_ts_node_text,
            ts_method_call_arg_exprs_fn=_ts_method_call_arg_exprs,
            ts_walk_fn=_ts_walk,
            ts_method_identifier_span_fn=_ts_method_identifier_span,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            bsl223_structure_names=_BSL223_STRUCTURE_NAMES,
            bsl249_style_constructor_names=_BSL249_STYLE_CONSTRUCTOR_NAMES,
            split_top_level_args_fn=_split_top_level_args,
        )

    # ------------------------------------------------------------------
    # BSL221 / BSL222 / BSL239 / BSL271 — lightweight mixed pool
    # ------------------------------------------------------------------

    def _rule_bsl221_222_239_271_light_pool(
        self,
        path: str,
        lines: list[str],
        tree: Any,
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl221_222_239_271_light_pool(
            lines=lines,
            tree=tree,
            procs=procs,
            enabled=enabled,
            snapshot=snapshot,
            strip_inline_comment_preserve_strings_fn=_strip_inline_comment_preserve_strings,
            reserved_parameter_names_re=self._reserved_parameter_names_re,
            ts_walk_fn=_ts_walk,
            ts_child_of_type_fn=_ts_child_of_type,
            ts_node_text_fn=_ts_node_text,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            bsl221_nstr_re=_RE_BSL221_NSTR,
            bsl221_lang_re=_RE_BSL221_LANG,
            bsl271_unix_unavailable_new_re=_RE_BSL271_UNIX_UNAVAILABLE_NEW,
            bsl271_platform_guard_re=_RE_BSL271_PLATFORM_GUARD,
            proc_name_span_fn=_proc_name_span,
            declared_languages=self._declared_languages,
        )

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
        model = ModuleModel(path=path)
        return model.validate_bsl229_275_278_local_xml_pool(
            lines=lines,
            procs=procs,
            enabled=enabled,
            rule_metadata=RULE_METADATA,
            severity_cls=Severity,
            proc_name_span_fn=_proc_name_span,
            re_xml_bool_simple=_RE_XML_BOOL_SIMPLE,
            re_bsl275_handler=_RE_BSL275_HANDLER,
            re_bsl278_procname=_RE_BSL278_PROCNAME,
        )

    def _rule_bsl169_170_181_182_196_260_light_pool(
        self,
        path: str,
        lines: list[str],
        procs: list[_ProcInfo],
        enabled: tuple[str, ...],
        snapshot: DocumentSnapshot | None = None,
    ) -> list[Diagnostic]:
        model = ModuleModel(path=path)
        return model.validate_bsl169_170_181_182_196_260_light_pool(
            lines=lines,
            procs=procs,
            enabled=enabled,
            snapshot=snapshot,
            path_is_likely_form_module_bsl_fn=path_is_likely_form_module_bsl,
            path_is_command_module_bsl_fn=_path_is_command_module_bsl,
            strip_inline_comment_preserve_strings_fn=_strip_inline_comment_preserve_strings,
            line_comment_re=_RE_LINE_COMMENT,
            proc_name_span_fn=_proc_name_span,
        )
