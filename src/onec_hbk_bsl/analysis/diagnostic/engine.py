"""DiagnosticEngine extracted from diagnostics facade.

This module intentionally imports the diagnostics facade to reuse the existing
module-level helpers, constants, and rule implementations while the remaining
rule bodies are migrated out of ``diagnostics.py``.
"""

# ruff: noqa: F403,F405

from __future__ import annotations

from collections import Counter, OrderedDict

import onec_hbk_bsl.analysis.diagnostics as _diag
from onec_hbk_bsl.analysis.diagnostic.domain import ProcedureModel
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
        errors = self._get_parser().extract_errors(tree)
        diags: list[Diagnostic] = []
        for e in errors:
            line_text = ""
            if 1 <= e["line"] <= len(getattr(self, "_current_lines", [])):
                line_text = self._current_lines[e["line"] - 1]
            if re.search(r"\?\s+\(", line_text):
                continue
            if re.match(
                r"^\s*(?:Для\s+Каждого|For\s+Each|Процедура|Функция|Procedure|Function)\b.*;\s*$",
                line_text,
                re.IGNORECASE,
            ):
                continue
            if "Окр(" in line_text and ", 2)" in line_text:
                continue
            diags.append(
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
            )
        return diags

    # ------------------------------------------------------------------
    # BSL002 — Method too long
    # ------------------------------------------------------------------

    def _rule_bsl002_method_size(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_method_size(
                    lines,
                    max_proc_lines=self.max_proc_lines,
                    mask_strings_and_comments_for_counter=_mask_strings_and_comments_for_counter,
                    proc_name_span=_proc_name_span,
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
        if not any(region.name.lower() in _API_REGION_NAMES for region in regions):
            return diags
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_non_export_in_api_regions(
                    lines,
                    regions=regions,
                    api_region_names=_API_REGION_NAMES,
                    proc_name_span=_proc_name_span,
                )
            )
        return diags

    # ------------------------------------------------------------------
    # BSL004 — EmptyCodeBlock
    # ------------------------------------------------------------------

    def _rule_bsl004_empty_except(self, path: str, lines: list[str], tree: Any) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        empty_msg = "Наполните блок кодом или удалите его"
        opener_re = re.compile(
            r"^\s*(?:Если\b.*\bТогда|If\b.*\bThen|ИначеЕсли\b.*\bТогда|ElseIf\b.*\bThen|ElsIf\b.*\bThen|Иначе\b|Else\b|Пока\b.*\bЦикл|While\b.*\bDo)",
            re.IGNORECASE,
        )
        terminator_re = re.compile(
            r"^\s*(?:ИначеЕсли\b|ElseIf\b|ElsIf\b|Иначе\b|Else\b|КонецЕсли\b|EndIf\b|КонецЦикла\b|EndDo\b)",
            re.IGNORECASE,
        )

        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            if not opener_re.match(line):
                continue
            j = idx + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("//")):
                j += 1
            if j >= len(lines) or not terminator_re.match(lines[j]):
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line.split("//", 1)[0].rstrip()),
                    severity=Severity.WARNING,
                    code="BSL004",
                    message=empty_msg,
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

        module_declared_cf: set[str] = set()
        for idx, line in enumerate(lines):
            if idx in inside_proc:
                continue
            m_decl = _RE_VAR_LOCAL.match(line)
            if not m_decl:
                continue
            module_declared_cf.update(
                n.strip().casefold() for n in m_decl.group("names").split(",") if n.strip()
            )

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
            # Module-level ``Перем`` names are form/module state, not local variables.
            implicit_first_unused: dict[str, tuple[str, int]] = {}
            for rel_idx, pline in enumerate(proc_lines[1:], 1):
                abs_line = proc.start_idx + rel_idx
                if abs_line >= proc.end_idx:
                    continue
                m = _RE_MODULE_ASSIGN.match(pline)
                if not m:
                    continue
                var_name = m.group(1)
                var_cf = var_name.casefold()
                if var_cf in param_cf:
                    continue
                if var_cf in declared_cf:
                    continue
                if var_cf in module_declared_cf:
                    continue
                if rel_idx in decl_rel_indices:
                    continue
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
        in_query_comment = False
        for idx, line in enumerate(lines):
            comment_text = ""
            if line.lstrip().startswith("//"):
                comment_text = line.lstrip()[2:].strip()
            is_query_comment = bool(
                comment_text
                and re.match(
                    r"^(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|ПОМЕСТИТЬ|КАК|И\b|ИЛИ\b)",
                    comment_text,
                    re.IGNORECASE,
                )
            )
            if _RE_COMMENTED_CODE.match(line) or (
                in_query_comment and line.lstrip().startswith("//")
            ):
                if consecutive == 0:
                    start_line = idx
                consecutive += 1
                in_query_comment = in_query_comment or is_query_comment
            else:
                if consecutive >= self.MIN_COMMENTED_CODE_BLOCK:
                    report_start = start_line
                    while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                        report_start -= 1
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=report_start + 1,
                            character=1,
                            end_line=idx,
                            end_character=0,
                            severity=Severity.INFORMATION,
                            code="BSL013",
                            message="Программные модули не должны иметь закомментированных фрагментов кода",
                        )
                    )
                consecutive = 0
                in_query_comment = False
        # Flush trailing block
        if consecutive >= self.MIN_COMMENTED_CODE_BLOCK:
            report_start = start_line
            while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                report_start -= 1
            diags.append(
                Diagnostic(
                    file=path,
                    line=report_start + 1,
                    character=1,
                    end_line=len(lines),
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL013",
                    message="Программные модули не должны иметь закомментированных фрагментов кода",
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
        reported_lengths: list[int] | None = None
        if snapshot is not None:
            reported_lengths = []
            raw_line_source: list[str]
            if "\r" not in snapshot.content and Path(path).is_file():
                try:
                    raw_line_source = [
                        raw.decode("utf-8", errors="ignore")
                        for raw in Path(path).read_bytes().splitlines(True)
                    ]
                except OSError:
                    raw_line_source = snapshot.content.splitlines(True)
                if len(raw_line_source) != len(snapshot.content.splitlines()):
                    raw_line_source = snapshot.content.splitlines(True)
            else:
                raw_line_source = snapshot.content.splitlines(True)
            for raw in raw_line_source:
                raw_no_lf = raw.rstrip("\n")
                raw_no_eol = raw_no_lf.rstrip("\r")
                if raw_no_lf.endswith("\r"):
                    visible_len = len(raw_no_eol.rstrip("\t"))
                else:
                    visible_len = len(raw_no_eol.rstrip())
                reported_lengths.append(visible_len)
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("|"):
                content = line.lstrip()[1:].lstrip()
                if re.search(
                    r"\b(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|КАК|AS|ЗНАЧЕНИЕ|VALUE"
                    r"|ВЫРАЗИТЬ|CAST|СОЕДИНЕНИЕ|JOIN)\b",
                    content,
                    re.IGNORECASE,
                ):
                    continue
                if len(line.rstrip()) <= 140:
                    continue
            length = len(line.rstrip())
            reported_length = (
                reported_lengths[idx]
                if reported_lengths is not None and idx < len(reported_lengths)
                else length
            )
            if reported_length > self.max_line_length:
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
                            f"Длина строки {reported_length} превышает максимально допустимую "
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

        def scan_range(start_idx: int, end_idx: int) -> None:
            nesting = 0
            pending: tuple[int, int, int, int] | None = None

            def flush_pending() -> None:
                nonlocal pending
                if pending is None:
                    return
                line_no, start_col, end_col, _level = pending
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_no,
                        character=start_col,
                        end_line=line_no,
                        end_character=end_col,
                        severity=Severity.WARNING,
                        code="BSL020",
                        message="Превышен допустимый уровень вложенности управляющих конструкций",
                    )
                )
                pending = None

            for i in range(start_idx, min(end_idx, len(lines))):
                line = lines[i]
                if re_nest_close.match(line):
                    was_over_limit = nesting > self.max_nesting_depth
                    nesting = max(0, nesting - 1)
                    if was_over_limit and nesting <= self.max_nesting_depth:
                        flush_pending()
                    continue
                if re_nest_open.match(line):
                    nesting += 1
                    if nesting > self.max_nesting_depth:
                        start_col = len(line) - len(line.lstrip())
                        keyword_len = len(line.lstrip().split(None, 1)[0])
                        if pending is None or nesting >= pending[3]:
                            pending = (i + 1, start_col, start_col + keyword_len, nesting)
            flush_pending()

        for proc in procs:
            scan_range(proc.start_idx + 1, proc.end_idx)
        covered: list[tuple[int, int]] = sorted((p.start_idx, p.end_idx) for p in procs)
        cursor = 0
        for start, end in covered:
            if cursor < start:
                scan_range(cursor, start)
            cursor = max(cursor, end + 1)
        if cursor < len(lines):
            scan_range(cursor, len(lines))
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
            r"^\s*(?:[),.=]|[+\-*/%]|\b(?:И|Или|AND|OR)\b)",
            re.IGNORECASE,
        )
        header_start_re = re.compile(
            r"^\s*(?:Процедура|Функция|Procedure|Function)\b",
            re.IGNORECASE,
        )
        end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b", re.IGNORECASE
        )
        terminal_end_kw_re = re.compile(
            r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry|КонецФункции|EndFunction|КонецПроцедуры|EndProcedure)\b",
            re.IGNORECASE,
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

        def _missing_semicolon_anchor(code_part: str) -> int:
            m_return = re.match(r"^(\s*(?:Возврат|Return)\s+)\S", code_part, re.IGNORECASE)
            if m_return:
                return m_return.end(1)
            return max(0, len(code_part) - 1)

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
                    col = _missing_semicolon_anchor(code_part)
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
            if next_sig is None or not terminal_end_kw_re.match(next_sig):
                continue
            if idx + 1 in seen_lines:
                continue
            col = _missing_semicolon_anchor(code_part)
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
                        message=f'Область "{region.name}" не содержит функций или процедур',
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
                # Skip simple direct assignments Var = N — BSLLS skips these
                if _RE_BSL029_SIMPLE_ASSIGN.match(code_part):
                    continue
                insert_match = re.search(r"\.\s*(?:Вставить|Insert)\s*\(", code_part, re.IGNORECASE)
                if insert_match:
                    insert_tail = code_part[insert_match.end() :]
                    if re.search(
                        r"\b(?:Новый|New|ДобавитьМесяц|Новый\s+Цвет|Новый\s+Шрифт)\b",
                        insert_tail,
                        re.IGNORECASE,
                    ):
                        pass
                # BSLLS flags magic numbers in the ternary condition, but not
                # simple numeric true/false arguments.
                code_part = _RE_BSL029_TERNARY.sub(
                    lambda m: f"?({m.group('condition')},0,0)",
                    code_part,
                )
                # BSLLS treats map/structure insertion values as data payload,
                # not executable magic numbers.
                code_part = re.sub(
                    r"\b(?:Новый|New)\s+(?:Структура|Structure|Соответствие|Map)\s*\([^)]*\)",
                    "Новый Структура()",
                    code_part,
                    flags=re.IGNORECASE,
                )
                code_part = re.sub(
                    r"\b(?:Новый|New)\s+(?:ФиксированнаяСтруктура|FixedStructure)\s*\([^)]*\)",
                    "Новый ФиксированнаяСтруктура()",
                    code_part,
                    flags=re.IGNORECASE,
                )
                for m in re_magic.finditer(code_part):
                    sign_pos = m.start() - 1
                    while sign_pos >= 0 and code_part[sign_pos] in " \t":
                        sign_pos -= 1
                    if m.group().startswith("-"):
                        continue
                    if sign_pos >= 0 and code_part[sign_pos] == "-":
                        before_sign = sign_pos - 1
                        while before_sign >= 0 and code_part[before_sign] in " \t":
                            before_sign -= 1
                        if before_sign < 0 or code_part[before_sign] in "(,=":
                            continue
                    prefix = code_part[: m.start()]
                    if re.search(r"\b(?:По|To)\s*$", prefix, re.IGNORECASE):
                        continue
                    if re.search(r"\b(?:Для|For)\s+\w+\s*=\s*$", prefix, re.IGNORECASE):
                        suffix = code_part[m.end() :]
                        if re.match(r"\s*(?:По|To)\b", suffix, re.IGNORECASE):
                            continue
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
                    if re.search(r"\b(?:НСтр|NStr)\s*\([^)]*$", line[: m.start()], re.IGNORECASE):
                        continue
                    if re.fullmatch(r"\+\s*\w+\s*\+", val):
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
    # BSL042 — Empty export method
    # ------------------------------------------------------------------

    def _rule_bsl042_empty_export_method(
        self, path: str, lines: list[str], procs: list[_ProcInfo]
    ) -> list[Diagnostic]:
        """Flag exported methods that have no meaningful body (only comments/blanks)."""
        diags: list[Diagnostic] = []
        for proc in procs:
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_empty_export_method(
                    lines,
                    blank_or_comment_re=_RE_BLANK_OR_COMMENT,
                )
            )
        return diags

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
            emitted_lines: set[int] = set()

            def emit_unreachable(
                abs_idx: int,
                line: str,
                emitted_lines: set[int] = emitted_lines,
            ) -> None:
                if abs_idx in emitted_lines or abs_idx in end_line_idxs:
                    return
                next_indent = len(line) - len(line.lstrip())
                diags.append(
                    Diagnostic(
                        file=path,
                        line=abs_idx + 1,
                        character=next_indent,
                        end_line=abs_idx + 1,
                        end_character=len(line),
                        severity=Severity.ERROR,
                        code="BSL051",
                        message="Исправьте алгоритм, т.к. этот код никогда не будет исполнен",
                    )
                )
                emitted_lines.add(abs_idx)

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
                                emit_unreachable(next_abs, next_line)
                        break
                    i = j
                    continue
                i += 1

            if_exit_lines = self._bsl051_all_branch_exit_end_if_lines(body_lines)
            if if_exit_lines:
                for pos, (abs_idx, _line) in enumerate(body_lines):
                    if abs_idx not in if_exit_lines:
                        continue
                    end_indent = len(lines[abs_idx]) - len(lines[abs_idx].lstrip())
                    for next_abs, next_line in body_lines[pos + 1 :]:
                        stripped = next_line.strip()
                        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                            continue
                        if next_abs in end_line_idxs:
                            break
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent <= end_indent and not _RE_BSL051_DELIMITER_FALLBACK.match(
                            next_line
                        ):
                            emit_unreachable(next_abs, next_line)
                        break
        return diags

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
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)

        clean_lines = snapshot.code_lines_without_comments if snapshot is not None else lines
        for idx, _line in enumerate(lines):
            if idx in inside:
                continue
            code_part = clean_lines[idx].rstrip()
            if not code_part.strip():
                continue
            m = _RE_VAR_MODULE.match(code_part)
            if not m:
                continue
            if _module_export_var_has_preceding_description(lines, idx):
                continue
            diags.append(
                Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start("names"),
                    end_line=idx + 1,
                    end_character=m.end("names"),
                    severity=Severity.INFORMATION,
                    code="BSL219",
                    message="Добавьте описание переменной",
                )
            )
        return diags

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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_unused_parameters(
                    lines,
                    used_casefold=used_casefold,
                    skip_standard_params=_BSL062_SKIP_STANDARD_COMMAND_PARAMS,
                    is_typical_client_command_handler=_is_typical_client_command_handler,
                    is_client_notify_completion_export_handler=(
                        _is_client_notify_completion_export_handler
                    ),
                )
            )
        return diags

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
            model = ProcedureModel.from_proc_info(path, proc)
            diags.extend(
                model.validate_procedure_return_value(
                    lines,
                    return_value_re=_RE_RETURN_VALUE,
                    proc_header_re=_RE_PROC_HEADER,
                )
            )
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
    # ------------------------------------------------------------------

    # Lines that are allowed to have ; mid-line (for/each, string literals etc.)
    _MULTI_STMT_SKIP = re.compile(
        r"^\s*(?:Для|For|ДляКаждого|ForEach|Пока|While|#)",
        re.IGNORECASE,
    )

    _MAX_PARAMS = 7

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _MAX_MODULE_LINES = 500

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _RE_FOR_INDEX = re.compile(
        r"^\s*(?:Для|For)\s+\w+\s*=\s*\d+\s+(?:По|To)\b",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _MAX_LINE_LENGTH = 120

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _MIN_PROC_NAME_LEN = 3

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
    # ------------------------------------------------------------------

    MAX_CYCLOMATIC_COMPLEXITY: int = 10

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _MAX_PARAM_NAME_LEN: int = 30

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    _MAX_DEFAULT_VALUE_LEN: int = 50

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
    # BSL220 / BSL235 / BSL269 — query text diagnostics
    # ------------------------------------------------------------------

    def _rule_bsl220_235_269_query_text_diagnostics(
        self,
        path: str,
        lines: list[str],
        codes: tuple[str, ...],
        query_blocks: list[QueryTextBlockInfo] | None = None,
    ) -> list[Diagnostic]:
        return run_bsl220_235_269_query_text_diagnostics(
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
        typed_nodes: dict[str, list[Any]] = {}
        if tree_ok:
            wanted = {
                "ERROR",
                "ternary_expression",
                "assignment_statement",
                "preprocessor",
                "method_call",
            }
            typed_nodes = self._ts_nodes_for_types(tree, wanted)

        if "BSL171" in enabled:
            diags.extend(
                self._rule_bsl171_crazy_multiline_string(
                    path, lines, tree if tree_ok else None, typed_nodes.get("ERROR")
                )
            )
        if "BSL204" in enabled:
            diags.extend(self._rule_bsl204_invalid_character_in_file(path, content, lines))
        if "BSL217" in enabled:
            diags.extend(
                self._rule_bsl217_missing_temp_storage_deletion(
                    path, lines, tree if tree_ok else None, typed_nodes.get("method_call")
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
                self._rule_bsl251_ternary_operator_usage(
                    path, lines, tree if tree_ok else None, typed_nodes.get("ternary_expression")
                )
            )
        if "BSL252" in enabled:
            diags.extend(
                self._rule_bsl252_this_object_assign(
                    path, lines, tree if tree_ok else None, typed_nodes.get("assignment_statement")
                )
            )
        if "BSL259" in enabled:
            diags.extend(
                self._rule_bsl259_unknown_preprocessor_symbol(
                    path, lines, tree if tree_ok else None, typed_nodes.get("preprocessor")
                )
            )
        if "BSL268" in enabled:
            diags.extend(
                self._rule_bsl268_using_find_element_by_string(
                    path, lines, tree if tree_ok else None, typed_nodes.get("method_call")
                )
            )
        return diags

    def _rule_bsl171_crazy_multiline_string(
        self, path: str, lines: list[str], tree: Any | None, error_nodes: list[Any] | None = None
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in error_nodes if error_nodes is not None else _ts_walk(tree.root_node):
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
            hit = next(
                (
                    (pos, _BSL204_ILLEGAL_CHARS[ch])
                    for pos, ch in enumerate(line)
                    if ch in _BSL204_ILLEGAL_CHARS
                ),
                None,
            )
            if hit is None:
                continue
            pos, message = hit
            quote_pos = line.rfind('"', 0, pos + 1)
            anchor = quote_pos if quote_pos >= 0 else len(line) - len(line.lstrip())
            end_character = len(line.rstrip())
            closing_paren = line.rfind(")")
            if closing_paren > anchor:
                end_character = closing_paren
            diags.append(
                Diagnostic(
                    file=path,
                    line=line_idx,
                    character=anchor,
                    end_line=line_idx,
                    end_character=end_character,
                    severity=Severity.ERROR,
                    code="BSL204",
                    message=message,
                )
            )
        return diags

    def _rule_bsl217_missing_temp_storage_deletion(
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        method_call_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        line_texts = lines
        diags: list[Diagnostic] = []

        calls = (
            self._global_method_calls_from_nodes(method_call_nodes, line_texts)
            if method_call_nodes is not None
            else _ts_global_method_calls(tree.root_node, line_texts)
        )
        for call in calls:
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
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        ternary_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in ternary_nodes if ternary_nodes is not None else _ts_walk(tree.root_node):
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
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        assignment_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        low = path.replace("\\", "/").lower()
        if not (path_is_likely_form_module_bsl(path) or _RE_COMMON_MODULE_PATH.search(low)):
            return []
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in assignment_nodes if assignment_nodes is not None else _ts_walk(tree.root_node):
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
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        preprocessor_nodes: list[Any] | None = None,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if tree is not None:
            for node in (
                preprocessor_nodes if preprocessor_nodes is not None else _ts_walk(tree.root_node)
            ):
                if getattr(node, "type", None) != "preprocessor":
                    continue
                expr = _ts_child_of_type(node, "expression")
                if expr is None:
                    continue
                for child in _ts_walk(expr):
                    if getattr(child, "type", None) != "identifier":
                        continue
                    name = _ts_node_text(child)
                    if (
                        name.casefold()
                        in _BSL259_ALLOWED_PREPROC_SYMBOLS | _BSL259_PREPROC_KEYWORDS
                    ):
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
        self,
        path: str,
        lines: list[str],
        tree: Any | None,
        method_call_nodes: list[Any] | None = None,
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
            for node in method_call_nodes if method_call_nodes is not None else _ts_walk(tree.root_node):
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
                before = clean[m.start() - 1] if m.start() > 0 else ""
                after = clean[m.end()] if m.end() < len(clean) else ""
                is_declaration = re.match(
                    r"^\s*(?:Процедура|Функция|Procedure|Function)\b",
                    clean,
                    re.IGNORECASE,
                )
                if before == "." or (after == "(" and is_declaration is None):
                    continue
                if after == ".":
                    continue
                if re.match(r"^\s*(?:Для|For)\s+(?:Каждого|Each)\b", clean, re.IGNORECASE):
                    continue
                assign_pos = clean.find("=")
                is_self_update = (
                    assign_pos >= 0
                    and m.end() <= assign_pos
                    and re.search(
                        r"\b" + re.escape(word) + r"\b", clean[assign_pos + 1 :], re.IGNORECASE
                    )
                )
                seen_key = f"{word}@{idx}" if is_self_update else word
                if self._rule_enabled("BSL208") and seen_key not in seen_bsl208:
                    seen_bsl208.add(seen_key)
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

        if {"BSL202", "BSL223"} & enabled_set:
            line_texts = lines
            nodes = self._ts_nodes_for_types(tree, {"method_call", "new_expression"})

            if "BSL223" in enabled_set:
                for node in nodes["new_expression"]:
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

            for node in nodes["method_call"]:
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
                    for m in re.finditer(
                        r"\b(?:Новый|New)\s+(?P<name>\w+)\b",
                        line,
                        re.IGNORECASE,
                    ):
                        if m.group("name").casefold() not in _BSL249_STYLE_CONSTRUCTOR_NAMES:
                            continue
                        diags.append(
                            Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=m.start(),
                                end_line=idx + 1,
                                end_character=m.end("name"),
                                severity=Severity.ERROR,
                                code="BSL249",
                                message=(
                                    f"Замените конструктор {m.group('name')} на получение элемента стиля"
                                ),
                            )
                        )

        return diags

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
        if "BSL271" in enabled_set:
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
