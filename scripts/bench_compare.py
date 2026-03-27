#!/usr/bin/env python3
"""
Сравнение результатов bench_timing.py до и после оптимизации.

Использование:
    python scripts/bench_timing.py > before.txt
    # ... применить оптимизацию ...
    python scripts/bench_timing.py > after.txt
    python scripts/bench_compare.py before.txt after.txt

Вывод:
   lines   before_ms    after_ms    delta%
     100        12.5        10.1     -19.2%
    3000       412.3        98.7     -76.1%
"""
from __future__ import annotations

import sys
from pathlib import Path


def parse_timing_file(path: str) -> dict[int, tuple[float, float, int]]:
    """
    Парсит вывод bench_timing.py.
    Возвращает {lines: (time_ms, ms_per_kline, diags)}.
    """
    results: dict[int, tuple[float, float, int]] = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        # Ожидаем: lines  time_ms  ms/kline  diags  filename
        if len(parts) >= 4 and parts[0].isdigit():
            try:
                n_lines = int(parts[0])
                time_ms = float(parts[1])
                ms_per_kline = float(parts[2])
                diags = int(parts[3])
                results[n_lines] = (time_ms, ms_per_kline, diags)
            except ValueError:
                continue
    return results


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: bench_compare.py <before.txt> <after.txt>")
        sys.exit(1)

    before_path, after_path = sys.argv[1], sys.argv[2]
    before = parse_timing_file(before_path)
    after = parse_timing_file(after_path)

    all_sizes = sorted(set(before) | set(after))
    if not all_sizes:
        print("No data found. Check file format (output of bench_timing.py).")
        sys.exit(1)

    print(f"\nComparing: {before_path}  →  {after_path}")
    print(f"\n{'lines':>8}  {'before_ms':>10}  {'after_ms':>10}  {'delta%':>8}  {'diags_b':>8}  {'diags_a':>8}")
    print("-" * 68)

    for size in all_sizes:
        b = before.get(size)
        a = after.get(size)
        if b is None:
            print(f"{size:>8}  {'N/A':>10}  {a[0]:>10.1f}  {'N/A':>8}  {'N/A':>8}  {a[2]:>8}")
        elif a is None:
            print(f"{size:>8}  {b[0]:>10.1f}  {'N/A':>10}  {'N/A':>8}  {b[2]:>8}  {'N/A':>8}")
        else:
            delta = (a[0] - b[0]) / b[0] * 100 if b[0] != 0 else 0.0
            sign = "+" if delta > 0 else ""
            print(
                f"{size:>8}  {b[0]:>10.1f}  {a[0]:>10.1f}  {sign}{delta:>7.1f}%"
                f"  {b[2]:>8}  {a[2]:>8}"
            )


if __name__ == "__main__":
    main()
