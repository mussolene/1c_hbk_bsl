#!/usr/bin/env python3
"""Deterministic performance-observability contract for CI and nightly trends."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from bench_compare import compare_observability  # noqa: E402
from bench_generate_fixtures import (  # noqa: E402
    DATASET_SCHEMA_VERSION,
    DEFAULT_SEED,
    generate_bsl,
)
from dev_corpus_bench import TraceDiagnosticTasks  # noqa: E402

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402
from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot  # noqa: E402
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer  # noqa: E402
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_SIZES = (100, 500)
REQUIRED_PLANES = ("parse", "index", "diagnostics", "cache", "scheduler")


def _node_count(tree: Any) -> int:
    root = tree.root_node
    stack = [root]
    total = 0
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(node.children)
    return total


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() or "unavailable"


def _measure_dataset(size: int, seed: int, *, include_timing: bool) -> dict[str, Any]:
    content = generate_bsl(size, seed=seed)
    path = f"synthetic-{size}-{seed}.bsl"
    started = time.perf_counter()
    snapshot = build_document_snapshot(path=path, content=content)
    parse_ms = (time.perf_counter() - started) * 1000

    with tempfile.TemporaryDirectory(prefix="onec-hbk-bsl-bench-") as temp_dir:
        db_path = str(Path(temp_dir) / "index.sqlite")
        index = SymbolIndex(db_path=db_path)
        try:
            index_result = IncrementalIndexer(index=index, quiet=True).index_snapshot(
                path, snapshot
            )
            index_stats = index.get_stats()
        finally:
            index.close()

    engine = DiagnosticEngine()
    started = time.perf_counter()
    with TraceDiagnosticTasks() as task_trace:
        diagnostics = engine.check_content(path, content)
    diagnostic_ms = (time.perf_counter() - started) * 1000
    cache_entries_after_miss = len(engine._content_diag_cache)
    cached_diagnostics = engine.check_content(path, content)
    cache_entries_after_hit = len(engine._content_diag_cache)
    invoke = engine.last_metrics.get("rule_invoke", {})
    phase_counts = invoke.get("counts_by_phase", {})
    enabled_tasks = sum(int(value) for value in phase_counts.values())
    scheduled_tasks = sum(row.calls for row in task_trace.trace.rows.values())
    process_safe_tasks = sum(row.process_safe_calls for row in task_trace.trace.rows.values())

    counts: dict[str, dict[str, int]] = {
        "parse": {
            "bytes": len(content.encode("utf-8")),
            "lines": len(content.splitlines()),
            "nodes": _node_count(snapshot.tree),
            "runs": 1,
        },
        "index": {
            "files": int(index_stats["file_count"]),
            "symbols": int(index_result.get("symbols", 0)),
            "calls": int(index_result.get("calls", 0)),
            "upserts": 1,
        },
        "diagnostics": {
            "diagnostics": len(diagnostics),
            "rules_enabled": enabled_tasks,
            "runs": 1,
        },
        "cache": {
            "lookups": 2,
            "misses": cache_entries_after_miss,
            "hits": int(
                cache_entries_after_hit == cache_entries_after_miss
                and cached_diagnostics == diagnostics
            ),
            "entries": cache_entries_after_hit,
        },
        "scheduler": {
            "tasks": scheduled_tasks,
            "task_codes": len(task_trace.trace.rows),
            "phases": len(phase_counts),
            "process_safe_tasks": process_safe_tasks,
            "local_tasks": scheduled_tasks - process_safe_tasks,
        },
    }
    row: dict[str, Any] = {
        "dataset": {
            "name": f"synthetic-{size}",
            "schema_version": DATASET_SCHEMA_VERSION,
            "seed": seed,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
        "counts": counts,
    }
    if include_timing:
        row["observations"] = {
            "parse_wall_clock_ms": round(parse_ms, 3),
            "diagnostic_wall_clock_ms": round(diagnostic_ms, 3),
        }
    return row


def validate_report(report: dict[str, Any]) -> None:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {report.get('schema_version')!r}")
    datasets = report.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("datasets must be a non-empty list")
    for row in datasets:
        counts = row.get("counts", {})
        missing = set(REQUIRED_PLANES) - set(counts)
        if missing:
            raise ValueError(f"missing performance planes: {sorted(missing)}")
        for plane in REQUIRED_PLANES:
            if not counts[plane] or not all(
                isinstance(value, int) and value >= 0 for value in counts[plane].values()
            ):
                raise ValueError(f"{plane} counts must be non-negative integers")
        dataset = row.get("dataset", {})
        for key in ("name", "schema_version", "seed", "sha256"):
            if key not in dataset:
                raise ValueError(f"dataset provenance is missing {key}")


def build_report(
    *, sizes: tuple[int, ...] = DEFAULT_SIZES, seed: int = DEFAULT_SEED, include_timing: bool
) -> dict[str, Any]:
    os.environ.setdefault("BSL_DIAG_PROCESS_RULES", "0")
    report = {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "commit": _commit(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "onec_hbk_bsl": _version("onec-hbk-bsl-core"),
            "tree_sitter_hbk": _version("tree-sitter-hbk"),
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "seed": seed,
        },
        "datasets": [_measure_dataset(size, seed, include_timing=include_timing) for size in sizes],
    }
    validate_report(report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--include-timing", action="store_true")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = build_report(
        sizes=tuple(args.sizes),
        seed=args.seed,
        include_timing=args.include_timing,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.check:
        if args.baseline is None:
            raise SystemExit("--check requires --baseline")
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        failures = compare_observability(baseline, report)
        if failures:
            raise SystemExit("\n".join(failures))
    print(args.output)


if __name__ == "__main__":
    main()
