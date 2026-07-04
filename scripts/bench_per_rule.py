#!/usr/bin/env python3
"""
Замер времени выполнения каждого правила диагностики отдельно.

Метод: monkey-patch _execute_diagnostic_rule_tasks в модуле diagnostics
с инструментированной версией. Работает без изменения исходников.

Вывод:
    rule      total_ms   mean_ms/run   calls   % total
   BSL007       312.1         104.0       3     79.6%
   BSL014        18.3           6.1       3      4.7%

Использование:
    python3 scripts/bench_per_rule.py                  # все размеры
    python3 scripts/bench_per_rule.py 3000             # только 3000 строк
    python3 scripts/bench_per_rule.py 3000 --runs=5
    python3 scripts/bench_per_rule.py --top=20         # top-20 правил
    python3 scripts/bench_per_rule.py --paths-from=/tmp/files.txt --ignore=BSL001
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import onec_hbk_bsl.analysis.diagnostic.pipeline as _pipeline_module  # noqa: E402
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
SIZES = [100, 500, 1000, 3000, 5000]
DEFAULT_RUNS = 3
DEFAULT_TOP = 10


def _path_for_run(path_str: str, run_idx: int) -> str:
    return f"{path_str}::bench-per-rule-{run_idx}"


def _make_instrumented_executor(
    rule_times: dict[str, float],
    rule_calls: dict[str, int],
) -> Any:
    """Возвращает инструментированную версию _execute_diagnostic_rule_tasks."""

    def _instrumented(tasks: list[Any]) -> list[Any]:
        out: list[Any] = []
        for task in tasks:
            if hasattr(task, "code") and hasattr(task, "fn"):
                code = task.code
                fn = task.fn
            else:
                code, fn = task
            t0 = time.perf_counter()
            result = fn()
            elapsed = time.perf_counter() - t0
            rule_times[code] = rule_times.get(code, 0.0) + elapsed
            rule_calls[code] = rule_calls.get(code, 0) + 1
            out.extend(result)
        return out

    return _instrumented


def run_per_rule(size: int, runs: int) -> tuple[dict[str, float], dict[str, int], int]:
    """
    Возвращает (accumulated_times_sec, call_counts, lines_count).
    times — суммарное время каждого правила за все runs (в секундах).
    """
    bsl_path = FIXTURE_DIR / f"bench_{size}.bsl"
    if not bsl_path.exists():
        return {}, {}, 0

    content = bsl_path.read_text(encoding="utf-8")
    n_lines = len(content.splitlines())
    path_str = str(bsl_path)

    rule_times: dict[str, float] = {}
    rule_calls: dict[str, int] = {}

    original = _pipeline_module.execute_diagnostic_rule_tasks
    _pipeline_module.execute_diagnostic_rule_tasks = _make_instrumented_executor(
        rule_times, rule_calls
    )
    try:
        engine = DiagnosticEngine()
        # warm-up: не засчитываем
        engine.check_content(_path_for_run(path_str, -1), content)
        rule_times.clear()
        rule_calls.clear()

        for run_idx in range(runs):
            engine.check_content(_path_for_run(path_str, run_idx), content)
    finally:
        _pipeline_module.execute_diagnostic_rule_tasks = original

    return rule_times, rule_calls, n_lines


def run_paths_per_rule(
    paths: list[Path],
    *,
    runs: int,
    ignore: set[str] | None,
) -> tuple[dict[str, float], dict[str, int], int, int, int]:
    """Return accumulated per-rule timings for an explicit external file list."""
    picked = [path for path in paths if path.is_file()]
    if not picked:
        return {}, {}, 0, 0, 0

    contents: list[tuple[Path, str]] = []
    total_lines = 0
    total_bytes = 0
    for path in picked:
        content = path.read_text(encoding="utf-8", errors="ignore")
        contents.append((path, content))
        total_lines += content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        total_bytes += len(content.encode("utf-8", errors="ignore"))

    rule_times: dict[str, float] = {}
    rule_calls: dict[str, int] = {}

    original = _pipeline_module.execute_diagnostic_rule_tasks
    _pipeline_module.execute_diagnostic_rule_tasks = _make_instrumented_executor(
        rule_times, rule_calls
    )
    try:
        engine = DiagnosticEngine(ignore=ignore or None)
        for run_idx in range(runs):
            for path, content in contents:
                engine.check_content(_path_for_run(str(path), run_idx), content)
    finally:
        _pipeline_module.execute_diagnostic_rule_tasks = original

    return rule_times, rule_calls, total_lines, total_bytes, len(picked)


def print_report(
    size: int,
    times: dict[str, float],
    calls: dict[str, int],
    n_lines: int,
    runs: int,
    top_n: int,
) -> None:
    if not times:
        print(f"\n[SKIP] bench_{size}.bsl not found — run bench_generate_fixtures.py first")
        return

    total_ms = sum(times.values()) * 1000
    sorted_rules = sorted(times.items(), key=lambda x: x[1], reverse=True)[:top_n]

    print(f"\n{'=' * 68}")
    print(f"bench_{size}.bsl  ({n_lines} lines, {runs} runs)")
    print(f"Total rule time: {total_ms:.1f} ms  |  Top-{top_n} slowest rules:")
    print(f"{'rule':>12}  {'total_ms':>10}  {'mean_ms/run':>12}  {'calls':>6}  {'% total':>8}")
    print("-" * 68)
    for code, elapsed in sorted_rules:
        rule_ms = elapsed * 1000
        mean_ms = rule_ms / runs
        pct = rule_ms / total_ms * 100 if total_ms > 0 else 0.0
        c = calls.get(code, 0)
        print(f"{code:>12}  {rule_ms:>10.1f}  {mean_ms:>12.2f}  {c:>6}  {pct:>7.1f}%")


def print_external_report(
    label: str,
    times: dict[str, float],
    calls: dict[str, int],
    n_lines: int,
    n_bytes: int,
    n_files: int,
    runs: int,
    top_n: int,
) -> None:
    if not times:
        print(f"\n[SKIP] {label}: no readable files")
        return

    total_ms = sum(times.values()) * 1000
    sorted_rules = sorted(times.items(), key=lambda x: x[1], reverse=True)[:top_n]
    mb = n_bytes / 1024 / 1024
    print(f"\n{'=' * 68}")
    print(f"{label}  ({n_files} files, {n_lines} lines, {mb:.1f} MiB, {runs} runs)")
    print(f"Total rule time: {total_ms:.1f} ms  |  Top-{top_n} slowest rules:")
    print(f"{'rule':>12}  {'total_ms':>10}  {'mean_ms/run':>12}  {'calls':>6}  {'% total':>8}")
    print("-" * 68)
    for code, elapsed in sorted_rules:
        rule_ms = elapsed * 1000
        mean_ms = rule_ms / runs
        pct = rule_ms / total_ms * 100 if total_ms > 0 else 0.0
        c = calls.get(code, 0)
        print(f"{code:>12}  {rule_ms:>10.1f}  {mean_ms:>12.2f}  {c:>6}  {pct:>7.1f}%")


def _parse_codes(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sizes", nargs="*", type=int)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--paths-from", default=None)
    parser.add_argument("--ignore", default=None)
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.paths_from:
        path_list = Path(args.paths_from).read_text(encoding="utf-8").splitlines()
        paths = [Path(line) for line in path_list if line.strip()]
        times, calls, n_lines, n_bytes, n_files = run_paths_per_rule(
            paths,
            runs=args.runs,
            ignore=_parse_codes(args.ignore),
        )
        print_external_report(
            Path(args.paths_from).name,
            times,
            calls,
            n_lines,
            n_bytes,
            n_files,
            args.runs,
            args.top,
        )
        return

    sizes = args.sizes or SIZES
    for size in sizes:
        times, calls, n_lines = run_per_rule(size, runs=args.runs)
        print_report(size, times, calls, n_lines, args.runs, args.top)


if __name__ == "__main__":
    main()
