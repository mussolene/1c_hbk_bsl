#!/usr/bin/env python3
"""
Dev-only benchmark on a real external 1C corpus.

This script is intentionally separate from test fixtures. It scans an arbitrary
configuration/workspace directory and measures:

- diagnostics runtime
- formatter runtime
- changed-file ratio after formatting

Example:
    python3 scripts/dev_corpus_bench.py /path/to/1c/config --limit=200
    python3 scripts/dev_corpus_bench.py /path/to/1c/config --sample=500
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import random
import resource
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from onec_hbk_bsl.analysis import diagnostics as diagnostics_mod  # noqa: E402
from onec_hbk_bsl.analysis import document_snapshot as snapshot_mod  # noqa: E402
from onec_hbk_bsl.analysis import semantic as semantic_mod  # noqa: E402
from onec_hbk_bsl.analysis.bsl_typo import candidates as typo_candidates_mod  # noqa: E402
from onec_hbk_bsl.analysis.diagnostic import execution as execution_mod  # noqa: E402
from onec_hbk_bsl.analysis.diagnostic import pipeline as pipeline_mod  # noqa: E402
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import (
    rules as runtime_rules_mod,  # noqa: E402
)
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import (
    runner as runtime_runner_mod,  # noqa: E402
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402
from onec_hbk_bsl.analysis.formatter import BslFormatter  # noqa: E402
from onec_hbk_bsl.parser import bsl_parser as bsl_parser_mod  # noqa: E402


@dataclass
class AnalysisTrace:
    root_walk_calls: dict[str, int] = field(default_factory=dict)
    root_walk_nodes: dict[str, int] = field(default_factory=dict)
    ts_nodes_requests: int = 0
    ts_nodes_hits: int = 0
    ts_nodes_misses: int = 0
    ts_nodes_missing_types: dict[str, int] = field(default_factory=dict)
    parser_calls: int = 0
    parser_seconds: float = 0.0
    semantic_model_calls: int = 0
    semantic_model_seconds: float = 0.0
    sdbl_parse_calls: int = 0
    sdbl_parse_seconds: float = 0.0
    typo_candidate_calls: int = 0
    typo_candidate_seconds: float = 0.0
    typo_candidates_total: int = 0

    def add_walk(self, name: str, nodes: int) -> None:
        self.root_walk_calls[name] = self.root_walk_calls.get(name, 0) + 1
        self.root_walk_nodes[name] = self.root_walk_nodes.get(name, 0) + nodes

    def add_missing_type(self, node_type: str) -> None:
        self.ts_nodes_missing_types[node_type] = self.ts_nodes_missing_types.get(node_type, 0) + 1


@dataclass
class FactTraceRow:
    calls: int = 0
    builds: int = 0
    hits: int = 0
    seconds: float = 0.0
    build_seconds: float = 0.0
    hit_seconds: float = 0.0
    files: set[str] = field(default_factory=set)
    max_lines: int = 0


@dataclass
class FactTrace:
    rows: dict[str, FactTraceRow] = field(default_factory=dict)

    def add(
        self,
        name: str,
        *,
        built: bool,
        seconds: float,
        path: str,
        line_count: int,
    ) -> None:
        row = self.rows.setdefault(name, FactTraceRow())
        row.calls += 1
        row.seconds += seconds
        row.files.add(path)
        row.max_lines = max(row.max_lines, line_count)
        if built:
            row.builds += 1
            row.build_seconds += seconds
        else:
            row.hits += 1
            row.hit_seconds += seconds


class TraceSnapshotFacts(AbstractContextManager["TraceSnapshotFacts"]):
    _PROPERTY_ATTRS: dict[str, str | None] = {
        "lines": "_lines",
        "has_parse_errors": "_has_parse_errors",
        "procedures": "_procs",
        "regions": "_regions",
        "proc_node_map": "_proc_node_map",
        "symbols": "_symbols",
        "calls": "_calls",
        "semantic_model": "_semantic_model",
        "query_text_blocks": "_query_blocks",
        "query_line_indices": "_query_line_indices",
        "query_content_line_tuples": "_query_content_line_tuples",
        "line_string_states": "_line_string_states",
        "comment_starts": "_comment_starts",
        "masked_lines": "_masked_lines",
        "code_lines_without_comments": "_code_lines_wo_comments",
        "counter_lines": "_counter_lines",
        "line_lengths": "_line_lengths",
        "reported_line_lengths": "_reported_line_lengths",
        "blank_line_flags": "_blank_line_flags",
        "string_literal_ranges": "_string_literal_ranges",
        "missing_space_facts": "_missing_space_facts",
        "incorrect_line_break_facts": "_incorrect_line_break_facts",
        "hardcoded_credential_facts": "_hardcoded_credential_facts",
        "commented_code_facts": "_commented_code_facts",
        "non_standard_region_facts": "_non_standard_region_facts",
        "empty_region_facts": "_empty_region_facts",
        "duplicate_region_facts": "_duplicate_region_facts",
        "deprecated_warning_facts": "_deprecated_warning_facts",
        "command_or_form_export_facts": "_command_or_form_export_facts",
        "this_form_usage_facts": "_this_form_usage_facts",
        "form_data_to_value_facts": "_form_data_to_value_facts",
        "invalid_character_facts": "_invalid_character_facts",
        "module_variable_description_facts": "_module_variable_description_facts",
        "select_top_without_order_facts": "_select_top_without_order_facts",
    }

    def __init__(self) -> None:
        self.trace = FactTrace()
        self._patches: list[tuple[Any, str, Any]] = []
        self._line_counts: dict[tuple[str, int], int] = {}

    def __enter__(self) -> TraceSnapshotFacts:
        snapshot_cls = snapshot_mod.DocumentSnapshot
        for name, attr in self._PROPERTY_ATTRS.items():
            member = getattr(snapshot_cls, name, None)
            if isinstance(member, property) and member.fget is not None:
                self._patch(
                    snapshot_cls, name, property(self._wrap_property(name, attr, member.fget))
                )
        self._patch(snapshot_cls, "ts_nodes_for_types", self._wrap_ts_nodes_for_types())
        self._patch(snapshot_cls, "complexity_metrics_for_procs", self._wrap_complexity_metrics())
        self._patch(
            snapshot_cls,
            "module_body_cognitive_complexity_facts",
            self._wrap_keyed_cache_method(
                "module_body_cognitive_complexity_facts",
                "_module_body_cognitive_facts_cache",
                lambda args, _kwargs: args[0] if args else None,
            ),
        )
        self._patch(
            snapshot_cls,
            "complex_condition_facts",
            self._wrap_keyed_cache_method(
                "complex_condition_facts",
                "_complex_condition_facts_cache",
                lambda args, _kwargs: args[0] if args else None,
            ),
        )
        self._patch(
            snapshot_cls,
            "line_too_long_facts",
            self._wrap_keyed_cache_method(
                "line_too_long_facts",
                "_line_too_long_facts_cache",
                lambda args, _kwargs: args[0] if args else None,
            ),
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for target, name, original in reversed(self._patches):
            setattr(target, name, original)
        self._patches.clear()

    def _patch(self, target: Any, name: str, replacement: Any) -> None:
        self._patches.append((target, name, getattr(target, name)))
        setattr(target, name, replacement)

    def _snapshot_line_count(self, snapshot: Any) -> int:
        key = (str(getattr(snapshot, "path", "")), id(snapshot))
        cached = self._line_counts.get(key)
        if cached is not None:
            return cached
        content = getattr(snapshot, "content", "")
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        self._line_counts[key] = line_count
        return line_count

    def _record(self, snapshot: Any, name: str, *, built: bool, seconds: float) -> None:
        self.trace.add(
            name,
            built=built,
            seconds=seconds,
            path=str(getattr(snapshot, "path", "")),
            line_count=self._snapshot_line_count(snapshot),
        )

    def _wrap_property(
        self,
        name: str,
        attr: str | None,
        original: Callable[[Any], Any],
    ) -> Callable[[Any], Any]:
        def wrapped(snapshot: Any) -> Any:
            built = attr is None or getattr(snapshot, attr, None) is None
            started = time.perf_counter()
            try:
                return original(snapshot)
            finally:
                self._record(
                    snapshot,
                    name,
                    built=built,
                    seconds=time.perf_counter() - started,
                )

        return wrapped

    def _wrap_ts_nodes_for_types(self) -> Callable[..., dict[str, list[Any]]]:
        original = snapshot_mod.DocumentSnapshot.ts_nodes_for_types

        def wrapped(snapshot: Any, node_types: set[str], *, hot_node_types=(), walker):
            requested = set(node_types) | set(hot_node_types)
            groups = getattr(snapshot, "_ts_node_groups", None)
            built = groups is None or bool(requested - set(groups))
            started = time.perf_counter()
            try:
                return original(snapshot, node_types, hot_node_types=hot_node_types, walker=walker)
            finally:
                self._record(
                    snapshot,
                    "ts_nodes_for_types",
                    built=built,
                    seconds=time.perf_counter() - started,
                )

        return wrapped

    def _wrap_complexity_metrics(self) -> Callable[..., list[tuple[int, int]]]:
        original = snapshot_mod.DocumentSnapshot.complexity_metrics_for_procs

        def wrapped(snapshot: Any, procs: list[Any]) -> list[tuple[int, int]]:
            key = tuple((proc.start_idx, proc.end_idx) for proc in procs)
            cache = getattr(snapshot, "_complexity_metrics_cache", None)
            built = cache is None or key not in cache
            started = time.perf_counter()
            try:
                return original(snapshot, procs)
            finally:
                self._record(
                    snapshot,
                    "complexity_metrics_for_procs",
                    built=built,
                    seconds=time.perf_counter() - started,
                )

        return wrapped

    def _wrap_keyed_cache_method(
        self,
        name: str,
        cache_attr: str,
        key_fn: Callable[[tuple[Any, ...], dict[str, Any]], Any],
    ) -> Callable[..., list[Any]]:
        original = getattr(snapshot_mod.DocumentSnapshot, name)

        def wrapped(snapshot: Any, *args: Any, **kwargs: Any) -> list[Any]:
            cache = getattr(snapshot, cache_attr, None)
            key = key_fn(args, kwargs)
            built = cache is None or key not in cache
            started = time.perf_counter()
            try:
                return original(snapshot, *args, **kwargs)
            finally:
                self._record(
                    snapshot,
                    name,
                    built=built,
                    seconds=time.perf_counter() - started,
                )

        return wrapped


@dataclass
class TaskTraceRow:
    calls: int = 0
    seconds: float = 0.0
    diagnostics: int = 0
    process_safe_calls: int = 0


@dataclass
class TaskTrace:
    rows: dict[str, TaskTraceRow] = field(default_factory=dict)

    def add(
        self,
        code: str,
        *,
        seconds: float,
        diagnostics_count: int,
        process_safe: bool,
    ) -> None:
        row = self.rows.setdefault(code, TaskTraceRow())
        row.calls += 1
        row.seconds += seconds
        row.diagnostics += diagnostics_count
        if process_safe:
            row.process_safe_calls += 1


class TraceDiagnosticTasks(AbstractContextManager["TraceDiagnosticTasks"]):
    def __init__(self) -> None:
        self.trace = TaskTrace()
        self._patches: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> TraceDiagnosticTasks:
        self._patch(
            execution_mod,
            "execute_diagnostic_rule_tasks",
            self._wrap_execute(execution_mod.execute_diagnostic_rule_tasks),
        )
        self._patch(
            pipeline_mod,
            "execute_diagnostic_rule_tasks",
            self._wrap_execute(pipeline_mod.execute_diagnostic_rule_tasks),
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for target, name, original in reversed(self._patches):
            setattr(target, name, original)
        self._patches.clear()

    def _patch(self, target: Any, name: str, replacement: Any) -> None:
        self._patches.append((target, name, getattr(target, name)))
        setattr(target, name, replacement)

    def _normalize_task_for_trace(self, task: Any) -> Any:
        if isinstance(task, execution_mod.DiagnosticRuleTask):
            return task
        code, fn = task
        return execution_mod.DiagnosticRuleTask(code=code, fn=fn)

    def _wrap_task(self, task: Any) -> Any:
        normalized = self._normalize_task_for_trace(task)

        def wrapped_fn() -> list[Any]:
            started = time.perf_counter()
            result = normalized.fn()
            elapsed = time.perf_counter() - started
            self.trace.add(
                normalized.code,
                seconds=elapsed,
                diagnostics_count=len(result),
                process_safe=normalized.process_safe,
            )
            return result

        return execution_mod.DiagnosticRuleTask(
            code=normalized.code,
            fn=wrapped_fn,
            process_safe=False,
        )

    def _wrap_execute(
        self, original: Callable[[list[Any]], list[Any]]
    ) -> Callable[[list[Any]], list[Any]]:
        def wrapped(tasks: list[Any]) -> list[Any]:
            return original([self._wrap_task(task) for task in tasks])

        return wrapped


class TraceAnalysisPasses(AbstractContextManager["TraceAnalysisPasses"]):
    def __init__(self, *, call_sites: bool = False) -> None:
        self.trace = AnalysisTrace()
        self.call_sites = call_sites
        self._patches: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> TraceAnalysisPasses:
        self._patch_walk(snapshot_mod, "_ts_walk", "document_snapshot._ts_walk")
        self._patch_walk(diagnostics_mod, "_ts_walk", "diagnostics._ts_walk")
        self._patch_walk(runtime_rules_mod, "_ts_walk", "runtime_rules._ts_walk")
        self._patch(snapshot_mod.DocumentSnapshot, "ts_nodes_for_types", self._wrap_ts_nodes())
        self._patch(bsl_parser_mod.BslParser, "parse_content", self._wrap_timed_parser())
        self._patch(snapshot_mod, "extract_semantic_model", self._wrap_timed_semantic())
        self._patch(semantic_mod, "extract_semantic_model", self._wrap_timed_semantic())
        self._patch(snapshot_mod, "_parse_sdbl_query_text", self._wrap_timed_sdbl_parse())
        self._patch(
            typo_candidates_mod,
            "collect_spell_candidates",
            self._wrap_timed_typo_candidates(typo_candidates_mod.collect_spell_candidates),
        )
        self._patch(
            runtime_runner_mod,
            "collect_spell_candidates",
            self._wrap_timed_typo_candidates(runtime_runner_mod.collect_spell_candidates),
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for target, name, original in reversed(self._patches):
            setattr(target, name, original)
        self._patches.clear()

    def _patch(self, target: Any, name: str, replacement: Any) -> None:
        self._patches.append((target, name, getattr(target, name)))
        setattr(target, name, replacement)

    def _patch_walk(self, target: Any, name: str, label: str) -> None:
        def wrapped(node: Any):
            effective_label = label
            if self.call_sites:
                frame = sys._getframe(1)
                effective_label = f"{label}:{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"

            def iterate():
                count = 0
                stack = [node]
                while stack:
                    current = stack.pop()
                    count += 1
                    yield current
                    children = getattr(current, "children", None) or ()
                    stack.extend(reversed(children))
                self.trace.add_walk(effective_label, count)

            return iterate()

        self._patch(target, name, wrapped)

    def _wrap_ts_nodes(self) -> Callable[..., dict[str, list[Any]]]:
        original = snapshot_mod.DocumentSnapshot.ts_nodes_for_types

        def wrapped(snapshot: Any, node_types: set[str], *, hot_node_types=(), walker):
            requested = set(node_types) | set(hot_node_types)
            groups = getattr(snapshot, "_ts_node_groups", None)
            self.trace.ts_nodes_requests += 1
            if groups is None:
                self.trace.ts_nodes_misses += 1
                for node_type in requested:
                    self.trace.add_missing_type(node_type)
            else:
                missing = requested - set(groups)
                if missing:
                    self.trace.ts_nodes_misses += 1
                    for node_type in missing:
                        self.trace.add_missing_type(node_type)
                else:
                    self.trace.ts_nodes_hits += 1
            return original(snapshot, node_types, hot_node_types=hot_node_types, walker=walker)

        return wrapped

    def _wrap_timed_parser(self) -> Callable[..., Any]:
        original = bsl_parser_mod.BslParser.parse_content

        def wrapped(parser: Any, *args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(parser, *args, **kwargs)
            finally:
                self.trace.parser_calls += 1
                self.trace.parser_seconds += time.perf_counter() - started

        return wrapped

    def _wrap_timed_semantic(self) -> Callable[..., Any]:
        original = snapshot_mod.extract_semantic_model

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.trace.semantic_model_calls += 1
                self.trace.semantic_model_seconds += time.perf_counter() - started

        return wrapped

    def _wrap_timed_sdbl_parse(self) -> Callable[..., Any]:
        original = snapshot_mod._parse_sdbl_query_text

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.trace.sdbl_parse_calls += 1
                self.trace.sdbl_parse_seconds += time.perf_counter() - started

        return wrapped

    def _wrap_timed_typo_candidates(
        self, original: Callable[..., list[Any]]
    ) -> Callable[..., list[Any]]:
        def wrapped(*args: Any, **kwargs: Any) -> list[Any]:
            started = time.perf_counter()
            try:
                result = original(*args, **kwargs)
                self.trace.typo_candidates_total += len(result)
                return result
            finally:
                self.trace.typo_candidate_calls += 1
                self.trace.typo_candidate_seconds += time.perf_counter() - started

        return wrapped


def iter_bsl_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for filename in filenames:
            lower_name = filename.lower()
            if lower_name.endswith((".bsl", ".os")) or filename == "Module.bsl":
                files.append(base / filename)
    return sorted(files)


def pick_files(
    files: list[Path], *, limit: int | None, sample: int | None, seed: int, largest: int | None
) -> list[Path]:
    picked = files
    if largest is not None:
        picked = sorted(
            picked,
            key=lambda p: p.stat().st_size,
            reverse=True,
        )[:largest]
    if sample is not None and sample < len(picked):
        rng = random.Random(seed)  # noqa: S311 - deterministic dev-only sampling
        picked = sorted(rng.sample(picked, sample))
    if limit is not None:
        picked = picked[:limit]
    return picked


@dataclass(frozen=True)
class Args:
    root: Path
    limit: int | None
    sample: int | None
    seed: int
    largest: int | None
    diagnostics_only: bool
    trace_analysis: bool
    trace_call_sites: bool
    profile: bool
    profile_top: int
    profile_sort: str
    slow_files: int
    trace_facts: bool
    trace_facts_top: int
    trace_tasks: bool
    trace_tasks_top: int


def parse_args(argv: list[str]) -> Args:
    if not argv:
        raise SystemExit(
            "Usage: dev_corpus_bench.py <corpus_dir> "
            "[--limit=N] [--sample=N] [--seed=N] [--largest=N] "
            "[--diagnostics-only] [--trace-analysis] [--trace-call-sites] "
            "[--profile] [--profile-top=N] [--profile-sort=cumulative|tottime] "
            "[--slow-files=N] [--trace-facts] [--trace-facts-top=N] "
            "[--trace-tasks] [--trace-tasks-top=N]"
        )

    root = Path(argv[0]).expanduser().resolve()
    limit: int | None = None
    sample: int | None = None
    seed = 42
    largest: int | None = None
    diagnostics_only = False
    trace_analysis = False
    trace_call_sites = False
    profile = False
    profile_top = 30
    profile_sort = "cumulative"
    slow_files = 0
    trace_facts = False
    trace_facts_top = 30
    trace_tasks = False
    trace_tasks_top = 30
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--limit":
            i += 1
            if i >= len(argv):
                raise SystemExit("--limit requires a value")
            limit = int(argv[i])
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg == "--sample":
            i += 1
            if i >= len(argv):
                raise SystemExit("--sample requires a value")
            sample = int(argv[i])
        elif arg.startswith("--sample="):
            sample = int(arg.split("=", 1)[1])
        elif arg == "--seed":
            i += 1
            if i >= len(argv):
                raise SystemExit("--seed requires a value")
            seed = int(argv[i])
        elif arg.startswith("--seed="):
            seed = int(arg.split("=", 1)[1])
        elif arg == "--largest":
            i += 1
            if i >= len(argv):
                raise SystemExit("--largest requires a value")
            largest = int(argv[i])
        elif arg.startswith("--largest="):
            largest = int(arg.split("=", 1)[1])
        elif arg == "--diagnostics-only":
            diagnostics_only = True
        elif arg == "--trace-analysis":
            trace_analysis = True
        elif arg == "--trace-call-sites":
            trace_call_sites = True
        elif arg == "--profile":
            profile = True
        elif arg == "--profile-top":
            i += 1
            if i >= len(argv):
                raise SystemExit("--profile-top requires a value")
            profile_top = int(argv[i])
        elif arg.startswith("--profile-top="):
            profile_top = int(arg.split("=", 1)[1])
        elif arg == "--profile-sort":
            i += 1
            if i >= len(argv):
                raise SystemExit("--profile-sort requires a value")
            profile_sort = argv[i].strip().lower()
        elif arg.startswith("--profile-sort="):
            profile_sort = arg.split("=", 1)[1].strip().lower()
        elif arg == "--slow-files":
            i += 1
            if i >= len(argv):
                raise SystemExit("--slow-files requires a value")
            slow_files = int(argv[i])
        elif arg.startswith("--slow-files="):
            slow_files = int(arg.split("=", 1)[1])
        elif arg == "--trace-facts":
            trace_facts = True
        elif arg == "--trace-facts-top":
            i += 1
            if i >= len(argv):
                raise SystemExit("--trace-facts-top requires a value")
            trace_facts_top = int(argv[i])
        elif arg.startswith("--trace-facts-top="):
            trace_facts_top = int(arg.split("=", 1)[1])
        elif arg == "--trace-tasks":
            trace_tasks = True
        elif arg == "--trace-tasks-top":
            i += 1
            if i >= len(argv):
                raise SystemExit("--trace-tasks-top requires a value")
            trace_tasks_top = int(argv[i])
        elif arg.startswith("--trace-tasks-top="):
            trace_tasks_top = int(arg.split("=", 1)[1])
        else:
            raise SystemExit(f"Unknown argument: {arg}")
        i += 1
    if profile_sort not in {"cumulative", "tottime"}:
        raise SystemExit("--profile-sort must be one of: cumulative, tottime")
    return Args(
        root=root,
        limit=limit,
        sample=sample,
        seed=seed,
        largest=largest,
        diagnostics_only=diagnostics_only,
        trace_analysis=trace_analysis,
        trace_call_sites=trace_call_sites,
        profile=profile,
        profile_top=profile_top,
        profile_sort=profile_sort,
        slow_files=slow_files,
        trace_facts=trace_facts,
        trace_facts_top=trace_facts_top,
        trace_tasks=trace_tasks,
        trace_tasks_top=trace_tasks_top,
    )


def print_trace(trace: AnalysisTrace, *, top_sites: int = 20) -> None:
    root_walk_calls = sum(trace.root_walk_calls.values())
    root_walk_nodes = sum(trace.root_walk_nodes.values())
    print(f"trace_root_walk_calls: {root_walk_calls}")
    print(f"trace_root_walk_nodes: {root_walk_nodes}")
    for name, calls in sorted(trace.root_walk_calls.items()):
        nodes = trace.root_walk_nodes.get(name, 0)
        print(f"trace_root_walk[{name}]: calls={calls} nodes={nodes}")
    print(f"trace_root_walk_top_sites: {top_sites}")
    for name, nodes in sorted(
        trace.root_walk_nodes.items(), key=lambda item: item[1], reverse=True
    )[:top_sites]:
        calls = trace.root_walk_calls.get(name, 0)
        print(f"trace_root_walk_top[{name}]: calls={calls} nodes={nodes}")
    print(f"trace_ts_nodes_requests: {trace.ts_nodes_requests}")
    print(f"trace_ts_nodes_hits: {trace.ts_nodes_hits}")
    print(f"trace_ts_nodes_misses: {trace.ts_nodes_misses}")
    for node_type, count in sorted(trace.ts_nodes_missing_types.items()):
        print(f"trace_ts_nodes_missing[{node_type}]: {count}")
    print(f"trace_parser_calls: {trace.parser_calls}")
    print(f"trace_parser_sec: {trace.parser_seconds:.3f}")
    print(f"trace_semantic_model_calls: {trace.semantic_model_calls}")
    print(f"trace_semantic_model_sec: {trace.semantic_model_seconds:.3f}")
    print(f"trace_sdbl_parse_calls: {trace.sdbl_parse_calls}")
    print(f"trace_sdbl_parse_sec: {trace.sdbl_parse_seconds:.3f}")
    print(f"trace_typo_candidate_calls: {trace.typo_candidate_calls}")
    print(f"trace_typo_candidate_sec: {trace.typo_candidate_seconds:.3f}")
    print(f"trace_typo_candidates_total: {trace.typo_candidates_total}")


def print_fact_trace(trace: FactTrace, *, top: int = 30) -> None:
    print(f"fact_trace_top: {top}")
    print(
        "fact_trace_name\tcalls\tbuilds\thits\tseconds\tbuild_seconds\thit_seconds\tfiles\tmax_lines"
    )
    rows = sorted(trace.rows.items(), key=lambda item: item[1].seconds, reverse=True)
    for name, row in rows[:top]:
        print(
            f"{name}\t{row.calls}\t{row.builds}\t{row.hits}\t"
            f"{row.seconds:.3f}\t{row.build_seconds:.3f}\t{row.hit_seconds:.3f}\t"
            f"{len(row.files)}\t{row.max_lines}"
        )


def print_task_trace(trace: TaskTrace, *, top: int = 30) -> None:
    print(f"task_trace_top: {top}")
    print("task_trace_name\tcalls\tprocess_safe_calls\tseconds\tdiagnostics")
    rows = sorted(trace.rows.items(), key=lambda item: item[1].seconds, reverse=True)
    for name, row in rows[:top]:
        print(
            f"{name}\t{row.calls}\t{row.process_safe_calls}\t{row.seconds:.3f}\t{row.diagnostics}"
        )


def maxrss_mb() -> float:
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS reports bytes.
    if maxrss > 10_000_000:
        return maxrss / (1024.0 * 1024.0)
    return maxrss / 1024.0


def print_profile(profile: cProfile.Profile, *, top: int, sort: str) -> None:
    buf = io.StringIO()
    pstats.Stats(profile, stream=buf).sort_stats(sort).print_stats(top)
    print(f"profile_sort: {sort}")
    print(f"profile_top: {top}")
    print(buf.getvalue())


def print_slow_files(
    rows: list[tuple[float, Path, int, int, int]],
    *,
    root: Path,
    top: int,
) -> None:
    if top <= 0:
        return
    print(f"slow_files_top: {top}")
    print("slow_file_sec\tlines\tbytes\tdiags\tfile")
    for elapsed, path, lines_count, byte_count, diag_count in sorted(
        rows, key=lambda row: row[0], reverse=True
    )[:top]:
        try:
            shown_path = path.relative_to(root)
        except ValueError:
            shown_path = path
        print(f"{elapsed:.3f}\t{lines_count}\t{byte_count}\t{diag_count}\t{shown_path}")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = args.root
    if not root.is_dir():
        raise SystemExit(f"Corpus directory not found: {root}")

    files = iter_bsl_files(root)
    picked = pick_files(
        files,
        limit=args.limit,
        sample=args.sample,
        seed=args.seed,
        largest=args.largest,
    )
    if not picked:
        raise SystemExit("No .bsl/.os files found in corpus")

    engine = DiagnosticEngine()
    formatter = BslFormatter()

    total_lines = 0
    total_bytes = 0
    total_diags = 0
    changed_after_format = 0
    slow_rows: list[tuple[float, Path, int, int, int]] = []

    trace_manager = (
        TraceAnalysisPasses(call_sites=args.trace_call_sites) if args.trace_analysis else None
    )
    fact_trace_manager = TraceSnapshotFacts() if args.trace_facts else None
    task_trace_manager = TraceDiagnosticTasks() if args.trace_tasks else None
    profiler = cProfile.Profile() if args.profile else None
    if profiler is not None:
        profiler.enable()

    def run_diagnostics_loop() -> float:
        nonlocal total_lines, total_bytes, total_diags
        if trace_manager is None:
            diag_started = time.perf_counter()
            for path in picked:
                content = path.read_text(encoding="utf-8", errors="ignore")
                file_lines = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                file_bytes = len(content.encode("utf-8", errors="ignore"))
                total_lines += file_lines
                total_bytes += file_bytes
                file_started = time.perf_counter()
                file_diags = len(engine.check_content(str(path), content))
                total_diags += file_diags
                slow_rows.append(
                    (time.perf_counter() - file_started, path, file_lines, file_bytes, file_diags)
                )
            return time.perf_counter() - diag_started

        with trace_manager:
            diag_started = time.perf_counter()
            for path in picked:
                content = path.read_text(encoding="utf-8", errors="ignore")
                file_lines = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                file_bytes = len(content.encode("utf-8", errors="ignore"))
                total_lines += file_lines
                total_bytes += file_bytes
                file_started = time.perf_counter()
                file_diags = len(engine.check_content(str(path), content))
                total_diags += file_diags
                slow_rows.append(
                    (time.perf_counter() - file_started, path, file_lines, file_bytes, file_diags)
                )
            return time.perf_counter() - diag_started

    if fact_trace_manager is not None and task_trace_manager is not None:
        with fact_trace_manager, task_trace_manager:
            diag_elapsed = run_diagnostics_loop()
    elif fact_trace_manager is not None:
        with fact_trace_manager:
            diag_elapsed = run_diagnostics_loop()
    elif task_trace_manager is not None:
        with task_trace_manager:
            diag_elapsed = run_diagnostics_loop()
    else:
        diag_elapsed = run_diagnostics_loop()

    if profiler is not None:
        profiler.disable()

    fmt_elapsed = 0.0
    if not args.diagnostics_only:
        fmt_started = time.perf_counter()
        for path in picked:
            content = path.read_text(encoding="utf-8", errors="ignore")
            formatted = formatter.format(content)
            if formatted != content:
                changed_after_format += 1
        fmt_elapsed = time.perf_counter() - fmt_started

    k_lines = max(total_lines / 1000.0, 1e-9)
    mb = max(total_bytes / (1024 * 1024), 1e-9)

    print(f"corpus_root: {root}")
    print(f"files_total: {len(files)}")
    print(f"files_tested: {len(picked)}")
    print(f"lines_total: {total_lines}")
    print(f"bytes_total: {total_bytes}")
    print(f"diagnostics_total: {total_diags}")
    print(f"format_changed_files: {changed_after_format}")
    print(f"diagnostics_sec: {diag_elapsed:.3f}")
    print(f"formatting_sec: {fmt_elapsed:.3f}")
    print(f"diagnostics_ms_per_kline: {(diag_elapsed * 1000.0) / k_lines:.2f}")
    print(f"formatting_ms_per_kline: {(fmt_elapsed * 1000.0) / k_lines:.2f}")
    print(f"diagnostics_files_per_sec: {len(picked) / max(diag_elapsed, 1e-9):.2f}")
    print(f"formatting_files_per_sec: {len(picked) / max(fmt_elapsed, 1e-9):.2f}")
    print(f"diagnostics_mb_per_sec: {mb / max(diag_elapsed, 1e-9):.2f}")
    print(f"formatting_mb_per_sec: {mb / max(fmt_elapsed, 1e-9):.2f}")
    print(f"process_maxrss_mb: {maxrss_mb():.1f}")
    print_slow_files(slow_rows, root=root, top=args.slow_files)
    if profiler is not None:
        print_profile(profiler, top=args.profile_top, sort=args.profile_sort)
    if fact_trace_manager is not None:
        print_fact_trace(fact_trace_manager.trace, top=args.trace_facts_top)
    if task_trace_manager is not None:
        print_task_trace(task_trace_manager.trace, top=args.trace_tasks_top)
    if trace_manager is not None:
        print_trace(trace_manager.trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
