#!/usr/bin/env python3
"""
Dev-only benchmark on a real external 1C corpus.

This script is intentionally separate from test fixtures. It scans an arbitrary
configuration/workspace directory and measures:

- diagnostics runtime
- formatter runtime
- changed-file ratio after formatting

Example:
    python scripts/dev_corpus_bench.py /Users/maxon/git/config --limit=200
    python scripts/dev_corpus_bench.py /Users/maxon/git/config --sample=500 --profile strict-bslls
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402
from onec_hbk_bsl.analysis.formatter import BslFormatter  # noqa: E402

BSL_SUFFIXES = {".bsl", ".os"}
DEFAULT_PROFILE = "strict-bslls"


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


def parse_args(argv: list[str]) -> tuple[Path, str, int | None, int | None, int, int | None]:
    if not argv:
        raise SystemExit(
            "Usage: dev_corpus_bench.py <corpus_dir> "
            "[--profile=strict-bslls|compat] [--limit=N] [--sample=N] [--seed=N] [--largest=N]"
        )

    root = Path(argv[0]).expanduser().resolve()
    profile = DEFAULT_PROFILE
    limit: int | None = None
    sample: int | None = None
    seed = 42
    largest: int | None = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--profile":
            i += 1
            if i >= len(argv):
                raise SystemExit("--profile requires a value")
            profile = argv[i].strip() or DEFAULT_PROFILE
        elif arg.startswith("--profile="):
            profile = arg.split("=", 1)[1].strip() or DEFAULT_PROFILE
        elif arg == "--limit":
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
        else:
            raise SystemExit(f"Unknown argument: {arg}")
        i += 1
    return root, profile, limit, sample, seed, largest


def main(argv: list[str]) -> int:
    root, profile, limit, sample, seed, largest = parse_args(argv)
    if not root.is_dir():
        raise SystemExit(f"Corpus directory not found: {root}")

    files = iter_bsl_files(root)
    picked = pick_files(files, limit=limit, sample=sample, seed=seed, largest=largest)
    if not picked:
        raise SystemExit("No .bsl/.os files found in corpus")

    engine = DiagnosticEngine(profile=profile)
    formatter = BslFormatter(profile=profile)

    total_lines = 0
    total_bytes = 0
    total_diags = 0
    changed_after_format = 0

    diag_started = time.perf_counter()
    for path in picked:
        content = path.read_text(encoding="utf-8", errors="ignore")
        total_lines += content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        total_bytes += len(content.encode("utf-8", errors="ignore"))
        total_diags += len(engine.check_content(str(path), content))
    diag_elapsed = time.perf_counter() - diag_started

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
    print(f"profile: {profile}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
