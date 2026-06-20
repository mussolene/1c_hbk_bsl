"""DiagnosticEngine extracted from diagnostics facade.

This module intentionally imports the diagnostics facade to reuse the existing
module-level helpers, constants, and rule implementations while the remaining
rule bodies are migrated out of ``diagnostics.py``.
"""

# ruff: noqa: F403,F405

from __future__ import annotations

import re
from bisect import bisect_left
from collections import OrderedDict

import onec_hbk_bsl.analysis.diagnostics as _diag
from onec_hbk_bsl.analysis.diagnostic.pipeline import AnalysisFrame, PipelineExecutor
from onec_hbk_bsl.analysis.diagnostic.suppression import (
    is_suppressed,
    parse_suppressions,
)
from onec_hbk_bsl.analysis.diagnostics import *  # noqa: F401,F403
from onec_hbk_bsl.analysis.source_positions import line_col_to_offset, line_start_offsets

_HOT_TS_NODE_TYPES: frozenset[str] = frozenset(
    {
        "ERROR",
        "assignment_statement",
        "binary_expression",
        "call_expression",
        "for_each_statement",
        "function_definition",
        "if_statement",
        "identifier",
        "method_call",
        "new_expression",
        "preprocessor",
        "procedure_definition",
        "ternary_expression",
        "try_statement",
        "unary_expression",
        "var_definition",
    }
)

globals().update(
    {
        name: getattr(_diag, name)
        for name in dir(_diag)
        if name.startswith("_") and not name.startswith("__")
    }
)


def _diagnostic_overlaps_ranges(
    content: str,
    *,
    line: int,
    character: int,
    end_line: int,
    end_character: int,
    ranges: tuple[tuple[int, int], ...],
    line_starts: list[int],
    range_starts: list[int],
) -> bool:
    start = line_col_to_offset(content, line - 1, character, line_starts=line_starts)
    end = line_col_to_offset(content, end_line - 1, end_character, line_starts=line_starts)
    if end < start:
        end = start
    idx = bisect_left(range_starts, end)
    return idx > 0 and ranges[idx - 1][1] > start


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
        bad_words_find_in_comments: bool = True,
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
        self._select: set[str] | None = (
            None if _user_select is None else _user_select & set(_PUBLIC_RULE_CODES)
        )
        # Instrumentation for benchmarks/debug: per-thread (free-threading safe).
        self._metrics_tls = threading.local()
        self._current_snapshot: Any | None = None
        _user_ignore: set[str] = normalize_rule_code_set(ignore) if ignore else set()
        self._ignore: set[str] = _user_ignore & set(_PUBLIC_RULE_CODES)
        self._enabled_codes: frozenset[str] = frozenset(
            code
            for code in RULE_METADATA
            if (self._select is None or code in self._select) and code not in self._ignore
        )
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
        self.bad_words_find_in_comments = bad_words_find_in_comments
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
        except (TypeError, ValueError):
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

    def _enabled_rule_codes(self) -> frozenset[str]:
        return self._enabled_codes

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
        except Exception:
            return [
                Diagnostic(
                    file=path,
                    line=1,
                    character=0,
                    end_line=1,
                    end_character=0,
                    severity=Severity.ERROR,
                    code="BSL001",
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
            except OSError:
                return [
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=0,
                        severity=Severity.ERROR,
                        code="BSL001",
                    )
                ]

            try:
                tree = self._get_parser().parse_content(content, file_path=path)
            except Exception:
                return [
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=0,
                        severity=Severity.ERROR,
                        code="BSL001",
                    )
                ]
        else:
            try:
                content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                return [
                    Diagnostic(
                        file=path,
                        line=1,
                        character=0,
                        end_line=1,
                        end_character=0,
                        severity=Severity.ERROR,
                        code="BSL001",
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
        _str_ranges = snapshot.string_literal_ranges
        if _str_ranges:
            _line_starts = line_start_offsets(content)
            _str_range_starts = [start for start, _ in _str_ranges]

            def bsl030_string_overlap_allowed(diag: Diagnostic) -> bool:
                if diag.code != "BSL030" or not (1 <= diag.line <= len(lines)):
                    return False
                line = lines[diag.line - 1]
                if not re.match(r"^\s*(?:И|Или|AND|OR)\b", line, re.IGNORECASE):
                    return False
                for next_line in lines[diag.line :]:
                    stripped = next_line.strip()
                    if not stripped or stripped.startswith("//"):
                        continue
                    return bool(
                        re.match(
                            r"^\s*(?:КонецФункции|EndFunction|КонецПроцедуры|EndProcedure)\b",
                            next_line,
                            re.IGNORECASE,
                        )
                    )
                return False

            diagnostics = [
                d
                for d in diagnostics
                if d.code in _CODES_EMIT_DIAGNOSTIC_INSIDE_STRING_LITERAL
                or bsl030_string_overlap_allowed(d)
                or not _diagnostic_overlaps_ranges(
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
        if snapshot is None or getattr(snapshot, "lines", None) is not lines:
            raise RuntimeError("complexity metrics require the current DocumentSnapshot")
        return snapshot.complexity_metrics_for_procs(procs)

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
