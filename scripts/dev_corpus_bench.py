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

import random
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
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import (
    rules as runtime_rules_mod,  # noqa: E402
)
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import (
    runner as runtime_runner_mod,  # noqa: E402
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402
from onec_hbk_bsl.analysis.formatter import BslFormatter  # noqa: E402
from onec_hbk_bsl.parser import bsl_parser as bsl_parser_mod  # noqa: E402

BSL_SUFFIXES = {".bsl", ".os"}


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

    def _wrap_timed_typo_candidates(self, original: Callable[..., list[Any]]) -> Callable[..., list[Any]]:
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
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and (p.suffix.lower() in BSL_SUFFIXES or p.name == "Module.bsl")
    )


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


def parse_args(argv: list[str]) -> Args:
    if not argv:
        raise SystemExit(
            "Usage: dev_corpus_bench.py <corpus_dir> "
            "[--limit=N] [--sample=N] [--seed=N] [--largest=N] "
            "[--diagnostics-only] [--trace-analysis] [--trace-call-sites]"
        )

    root = Path(argv[0]).expanduser().resolve()
    limit: int | None = None
    sample: int | None = None
    seed = 42
    largest: int | None = None
    diagnostics_only = False
    trace_analysis = False
    trace_call_sites = False
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
        else:
            raise SystemExit(f"Unknown argument: {arg}")
        i += 1
    return Args(
        root=root,
        limit=limit,
        sample=sample,
        seed=seed,
        largest=largest,
        diagnostics_only=diagnostics_only,
        trace_analysis=trace_analysis,
        trace_call_sites=trace_call_sites,
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
    for name, nodes in sorted(trace.root_walk_nodes.items(), key=lambda item: item[1], reverse=True)[
        :top_sites
    ]:
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

    trace_manager = (
        TraceAnalysisPasses(call_sites=args.trace_call_sites) if args.trace_analysis else None
    )
    if trace_manager is None:
        diag_started = time.perf_counter()
        for path in picked:
            content = path.read_text(encoding="utf-8", errors="ignore")
            total_lines += content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            total_bytes += len(content.encode("utf-8", errors="ignore"))
            total_diags += len(engine.check_content(str(path), content))
        diag_elapsed = time.perf_counter() - diag_started
    else:
        with trace_manager:
            diag_started = time.perf_counter()
            for path in picked:
                content = path.read_text(encoding="utf-8", errors="ignore")
                total_lines += content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                total_bytes += len(content.encode("utf-8", errors="ignore"))
                total_diags += len(engine.check_content(str(path), content))
            diag_elapsed = time.perf_counter() - diag_started

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
    if trace_manager is not None:
        print_trace(trace_manager.trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
