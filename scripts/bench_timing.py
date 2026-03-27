#!/usr/bin/env python3
"""
Замер времени check_content() на синтетических BSL файлах.

Вывод:
   lines    time_ms   ms/kline    diags  file

Использование:
    python scripts/bench_timing.py
    python scripts/bench_timing.py --runs=10
    python scripts/bench_timing.py 1000 3000   # только эти размеры
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
SIZES = [100, 500, 1000, 3000, 5000]
DEFAULT_RUNS = 5


def measure(
    engine: DiagnosticEngine, path_str: str, content: str, runs: int
) -> tuple[float, int]:
    """Возвращает (mean_ms, diag_count). Trimmed mean — убираем min и max."""
    # warm-up: загрузка grammar, JIT прогрев
    diags = engine.check_content(path_str, content)

    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        engine.check_content(path_str, content)
        times.append(time.perf_counter() - t0)

    if len(times) >= 3:
        times = sorted(times)[1:-1]  # убрать outliers
    mean_ms = sum(times) / len(times) * 1000
    return mean_ms, len(diags)


def main() -> None:
    args = sys.argv[1:]
    runs = DEFAULT_RUNS
    sizes = []
    for a in args:
        if a.startswith("--runs="):
            runs = int(a.split("=")[1])
        elif a.isdigit():
            sizes.append(int(a))
    if not sizes:
        sizes = SIZES

    engine = DiagnosticEngine()

    print(f"\n{'lines':>8} {'time_ms':>10} {'ms/kline':>10} {'diags':>8}  file")
    print("-" * 58)

    for size in sizes:
        bsl_path = FIXTURE_DIR / f"bench_{size}.bsl"
        if not bsl_path.exists():
            print(
                f"{'?':>8} {'N/A':>10} {'N/A':>10} {'N/A':>8}  bench_{size}.bsl"
                f"  (not found — run bench_generate_fixtures.py)"
            )
            continue
        content = bsl_path.read_text(encoding="utf-8")
        n_lines = len(content.splitlines())
        mean_ms, n_diags = measure(engine, str(bsl_path), content, runs)
        ms_per_kline = mean_ms / (n_lines / 1000)
        print(f"{n_lines:>8} {mean_ms:>10.1f} {ms_per_kline:>10.1f} {n_diags:>8}  bench_{size}.bsl")

    print(f"\n(Runs per file: {runs}, trimmed mean excl. min/max)")


if __name__ == "__main__":
    main()
