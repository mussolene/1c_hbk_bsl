"""DiagnosticEngine extracted from diagnostics facade.

This module intentionally imports the diagnostics facade to reuse the existing
module-level helpers, constants, and rule implementations while the remaining
rule bodies are migrated out of ``diagnostics.py``.
"""

# ruff: noqa: F403,F405

from __future__ import annotations

from collections import OrderedDict

import onec_hbk_bsl.analysis.diagnostics as _diag
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
                lines,
                proc.start_idx,
                proc.end_idx,
                string_states=string_states,
                proc_name=proc.name,
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
        global_call_starts = [getattr(call["node"], "start_byte", -1) for call in global_calls]
        proc_nodes = nodes["procedure_definition"] + nodes["function_definition"]
        context = (global_calls, global_call_starts, proc_nodes, nodes["try_statement"])
        if snapshot is not None and getattr(snapshot, "tree", None) is tree:
            snapshot.set_runtime_call_context(context)
        return context

    # ------------------------------------------------------------------
    # BSL001 — Parse errors
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL002 — Method too long
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL003 — Non-export method in API region
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL007 — Unused local variable
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL009 — Self-assignment
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL011 — Cognitive complexity
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL016 — Non-standard region name
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL019 — McCabe cyclomatic complexity
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL020 — Excessive nesting depth
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL022 — Deprecated Предупреждение() / Warning()
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL030 — SemicolonPresence: «;» в конце выражения (BSLLS) + лишняя «;» в заголовке
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # BSL029 — MagicNumber
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL148 — AllFunctionPathMustHaveReturn
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL033 — Query execution inside a loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL035 — Duplicate string literal
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL040 — ЭтаФорма / ThisForm outside event handler context
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL042 — Empty export method
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL051 — Unreachable code after Return/Raise
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # BSL054 — Module-level Перем/Var (global state)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL062 — Unused parameter
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL064 — Procedure returns value
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL077 — SelectTopWithoutOrderBy
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL171 / BSL204 / BSL217 / BSL248 / BSL251 / BSL252 / BSL259 / BSL268
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL190 — FormDataToValue
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL175 / BSL176 — deprecated API pool
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL215 — MissingParameterDescription
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL233 — PublicMethodsDescription
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL216 — MissingSpace
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL254 — TransferringParametersBetweenClientAndServer
    # ------------------------------------------------------------------

    # BSL208 — LatinAndCyrillicSymbolInWord
    # BSL256 — Typo (BSLLS-style: pyspellchecker + pymorphy3, bundled BSLLS exceptions)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL224 — NestedFunctionInParameters
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL202 / BSL223 / BSL243 / BSL249 — lightweight call pool
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL221 / BSL222 / BSL239 / BSL271 — lightweight mixed pool
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # BSL229 / BSL275 / BSL278 — local XML-backed pool
    # ------------------------------------------------------------------
