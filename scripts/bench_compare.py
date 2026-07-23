#!/usr/bin/env python3
"""
Сравнение результатов bench_timing.py до и после оптимизации.

Использование:
    python3 scripts/bench_timing.py > before.txt
    # ... применить оптимизацию ...
    python3 scripts/bench_timing.py > after.txt
    python3 scripts/bench_compare.py before.txt after.txt

Вывод:
   lines   before_ms    after_ms    delta%
     100        12.5        10.1     -19.2%
    3000       412.3        98.7     -76.1%
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


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


def compare_observability(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Compare deterministic counters only; wall-clock observations are ignored."""
    if baseline.get("schema_version") != current.get("schema_version"):
        return ["performance schema_version differs"]
    base_rows = {row["dataset"]["name"]: row for row in baseline.get("datasets", [])}
    current_rows = {row["dataset"]["name"]: row for row in current.get("datasets", [])}
    failures: list[str] = []
    for name, base_row in base_rows.items():
        row = current_rows.get(name)
        if row is None:
            failures.append(f"{name}: dataset missing")
            continue
        if base_row["dataset"] != row["dataset"]:
            failures.append(f"{name}: dataset provenance differs")
            continue
        for plane, metrics in base_row.get("counts", {}).items():
            for metric, maximum in metrics.items():
                actual = row.get("counts", {}).get(plane, {}).get(metric)
                if actual is None:
                    failures.append(f"{name}.{plane}.{metric}: metric missing")
                elif actual > maximum:
                    failures.append(
                        f"{name}.{plane}.{metric}: {actual} exceeds deterministic budget {maximum}"
                    )
    return failures


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: bench_compare.py <before.txt> <after.txt>")
        sys.exit(1)

    before_path, after_path = sys.argv[1], sys.argv[2]
    if before_path.endswith(".json") and after_path.endswith(".json"):
        before_json = json.loads(Path(before_path).read_text(encoding="utf-8"))
        after_json = json.loads(Path(after_path).read_text(encoding="utf-8"))
        failures = compare_observability(before_json, after_json)
        if failures:
            print("\n".join(failures))
            sys.exit(1)
        print("Deterministic performance budgets: PASS (wall-clock ignored)")
        return
    before = parse_timing_file(before_path)
    after = parse_timing_file(after_path)

    all_sizes = sorted(set(before) | set(after))
    if not all_sizes:
        print("No data found. Check file format (output of bench_timing.py).")
        sys.exit(1)

    print(f"\nComparing: {before_path}  →  {after_path}")
    print(
        f"\n{'lines':>8}  {'before_ms':>10}  {'after_ms':>10}  {'delta%':>8}  {'diags_b':>8}  {'diags_a':>8}"
    )
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
