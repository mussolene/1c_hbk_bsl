#!/usr/bin/env python3
"""
cProfile для check_content() на синтетических BSL файлах.

Вывод: top-N функций по cumtime в формате pstats.

Использование:
    python scripts/bench_profile.py 3000         # один размер
    python scripts/bench_profile.py --all        # все размеры
    python scripts/bench_profile.py 3000 --top=30
    python scripts/bench_profile.py 3000 --runs=5
"""
from __future__ import annotations

import cProfile
import io
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
SIZES = [100, 500, 1000, 3000, 5000]
DEFAULT_TOP = 20
DEFAULT_RUNS = 3


def profile_size(size: int, top_n: int, runs: int) -> None:
    bsl_path = FIXTURE_DIR / f"bench_{size}.bsl"
    if not bsl_path.exists():
        print(f"\n[SKIP] bench_{size}.bsl not found — run bench_generate_fixtures.py first")
        return

    content = bsl_path.read_text(encoding="utf-8")
    n_lines = len(content.splitlines())
    path_str = str(bsl_path)
    engine = DiagnosticEngine()

    # warm-up: загрузка tree-sitter grammar
    engine.check_content(path_str, content)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(runs):
        engine.check_content(path_str, content)
    pr.disable()

    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    ps.print_stats(top_n)

    print(f"\n{'='*72}")
    print(
        f"PROFILE: bench_{size}.bsl ({n_lines} lines), "
        f"{runs} runs, top-{top_n} by cumtime"
    )
    print("=" * 72)
    print(buf.getvalue())


def main() -> None:
    args = sys.argv[1:]
    top_n = DEFAULT_TOP
    runs = DEFAULT_RUNS
    use_all = "--all" in args
    sizes = [int(a) for a in args if a.isdigit()]

    for a in args:
        if a.startswith("--top="):
            top_n = int(a.split("=")[1])
        elif a.startswith("--runs="):
            runs = int(a.split("=")[1])

    if use_all or not sizes:
        sizes = SIZES

    for size in sizes:
        profile_size(size, top_n=top_n, runs=runs)


if __name__ == "__main__":
    main()
