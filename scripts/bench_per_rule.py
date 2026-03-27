#!/usr/bin/env python3
"""
Замер времени выполнения каждого правила диагностики отдельно.

Метод: monkey-patch _execute_diagnostic_rule_tasks в модуле diagnostics
с инструментированной версией. Работает без изменения исходников.

Вывод:
    rule      total_ms   mean_ms/run   calls   % total
   BSL007       312.1         104.0       3     79.6%
   BSL021        18.3           6.1       3      4.7%

Использование:
    python scripts/bench_per_rule.py                  # все размеры
    python scripts/bench_per_rule.py 3000             # только 3000 строк
    python scripts/bench_per_rule.py 3000 --runs=5
    python scripts/bench_per_rule.py --top=20         # top-20 правил
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import onec_hbk_bsl.analysis.diagnostics as _diag_module  # noqa: E402
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
SIZES = [100, 500, 1000, 3000, 5000]
DEFAULT_RUNS = 3
DEFAULT_TOP = 10


def _make_instrumented_executor(
    rule_times: dict[str, float],
    rule_calls: dict[str, int],
) -> Any:
    """Возвращает инструментированную версию _execute_diagnostic_rule_tasks."""

    def _instrumented(tasks: list[tuple[str, Any]]) -> list[Any]:
        out: list[Any] = []
        for code, fn in tasks:
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

    original = _diag_module._execute_diagnostic_rule_tasks
    _diag_module._execute_diagnostic_rule_tasks = _make_instrumented_executor(rule_times, rule_calls)
    try:
        engine = DiagnosticEngine()
        # warm-up: не засчитываем
        engine.check_content(path_str, content)
        rule_times.clear()
        rule_calls.clear()

        for _ in range(runs):
            engine.check_content(path_str, content)
    finally:
        _diag_module._execute_diagnostic_rule_tasks = original

    return rule_times, rule_calls, n_lines


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

    print(f"\n{'='*68}")
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


def main() -> None:
    args = sys.argv[1:]
    sizes = [int(a) for a in args if a.isdigit()] or SIZES
    runs = DEFAULT_RUNS
    top_n = DEFAULT_TOP
    for a in args:
        if a.startswith("--runs="):
            runs = int(a.split("=")[1])
        elif a.startswith("--top="):
            top_n = int(a.split("=")[1])

    for size in sizes:
        times, calls, n_lines = run_per_rule(size, runs=runs)
        print_report(size, times, calls, n_lines, runs, top_n)


if __name__ == "__main__":
    main()
