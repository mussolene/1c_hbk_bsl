#!/usr/bin/env python3
"""Profile diagnostics parity corpora with isolated CPU/RSS measurements."""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from onec_hbk_bsl.analysis.bslls_runtime_parity import (  # noqa: E402
    _run_bslls_analyze,
    capture_bslls_baseline,
    compare_with_bslls_baseline,
    iter_bsl_files,
    resolve_bslls_jar,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine  # noqa: E402
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer  # noqa: E402
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex  # noqa: E402


def _rss_mb(raw: int) -> float:
    if sys.platform == "darwin":
        return raw / (1024 * 1024)
    return raw / 1024


def _usage_delta(before: resource.struct_rusage, after: resource.struct_rusage) -> dict[str, Any]:
    return {
        "user_sec": round(after.ru_utime - before.ru_utime, 3),
        "sys_sec": round(after.ru_stime - before.ru_stime, 3),
        "maxrss_mb": round(_rss_mb(after.ru_maxrss), 1),
    }


def _picked_files(root: Path, *, limit: int | None, largest: int | None) -> list[Path]:
    files = iter_bsl_files(root)
    if largest is not None:
        files = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:largest]
    if limit is not None:
        files = files[:limit]
    return files


def _run_ours(root: Path, files: list[Path], *, parallel: bool) -> int:
    os.environ["BSL_DIAG_PARALLEL_RULES"] = "1" if parallel else "0"
    os.environ["BSL_DIAG_PROCESS_RULES"] = "1" if parallel else "0"
    os.environ.setdefault("BSL_DIAG_PARALLEL_WORKERS", "8")

    import tempfile

    total = 0
    with tempfile.TemporaryDirectory(prefix="onec-perf-index-") as tmp:
        idx = SymbolIndex(db_path=str(Path(tmp) / "index.sqlite"))
        indexer = IncrementalIndexer(index=idx, quiet=True)
        indexer.index_metadata(str(root))
        for path in files:
            indexer.index_file(str(path))
        engine = DiagnosticEngine(symbol_index=idx)
        for path in files:
            content = path.read_text(encoding="utf-8", errors="ignore")
            total += len(engine.check_content(str(path), content, symbol_index=idx))
        idx.close()
    return total


def _run_bslls(root: Path, files: list[Path]) -> int:
    jar = resolve_bslls_jar(Path.cwd())
    rows = _run_bslls_analyze(
        jar_path=jar,
        workspace_root=root,
        files=files,
        config_path=None,
    )
    return len(rows)


def child_main(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    files = _picked_files(root, limit=args.limit, largest=args.largest)
    if not files:
        raise SystemExit(f"No BSL files in {root}")

    lines = 0
    bytes_total = 0
    for path in files:
        content = path.read_text(encoding="utf-8", errors="ignore")
        lines += content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        bytes_total += len(content.encode("utf-8", errors="ignore"))

    self_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    if args.mode == "ours-seq":
        diagnostics = _run_ours(root, files, parallel=False)
    elif args.mode == "ours-par":
        diagnostics = _run_ours(root, files, parallel=True)
    elif args.mode == "bslls":
        diagnostics = _run_bslls(root, files)
    else:
        raise SystemExit(f"Unknown mode: {args.mode}")
    wall = time.perf_counter() - started
    self_after = resource.getrusage(resource.RUSAGE_SELF)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)

    self_usage = _usage_delta(self_before, self_after)
    children_usage = _usage_delta(children_before, children_after)
    result = {
        "corpus": root.name,
        "mode": args.mode,
        "files": len(files),
        "lines": lines,
        "bytes": bytes_total,
        "diagnostics": diagnostics,
        "wall_sec": round(wall, 3),
        "self": self_usage,
        "children": children_usage,
        "total_cpu_sec": round(
            self_usage["user_sec"]
            + self_usage["sys_sec"]
            + children_usage["user_sec"]
            + children_usage["sys_sec"],
            3,
        ),
        "maxrss_mb": max(self_usage["maxrss_mb"], children_usage["maxrss_mb"]),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _run_child(root: Path, mode: str, *, limit: int | None, largest: int | None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--root",
        str(root),
        "--mode",
        mode,
    ]
    if limit is not None:
        cmd.extend(["--limit", str(limit)])
    if largest is not None:
        cmd.extend(["--largest", str(largest)])
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _parity_summary(root: Path, *, limit: int | None, largest: int | None) -> dict[str, Any]:
    files = _picked_files(root, limit=limit, largest=largest)
    jar = resolve_bslls_jar(Path.cwd())
    baseline = capture_bslls_baseline(
        workspace_root=root,
        files=files,
        config_path=None,
        jar_path=jar,
    )
    result = compare_with_bslls_baseline(workspace_root=root, files=files, baseline=baseline)
    diagnostics = result["diagnostics"]
    formatting = result["formatting"]
    return {
        "corpus": root.name,
        "files": len(files),
        "diagnostics_exact": diagnostics["exact_match"],
        "only_ours": len(diagnostics["only_ours"]),
        "only_bslls": len(diagnostics["only_bslls"]),
        "severity_mismatch": len(diagnostics["severity_mismatch"]),
        "message_mismatch": len(diagnostics["message_mismatch"]),
        "anchor_mismatch": len(diagnostics.get("anchor_mismatch", [])),
        "formatting_exact": formatting["exact_match"],
        "formatting_diff_files": len(formatting["diffs"]),
    }


def parent_main(args: argparse.Namespace) -> int:
    roots = [Path(item).expanduser().resolve() for item in args.roots]
    report: dict[str, Any] = {"perf": [], "parity": []}
    for root in roots:
        for mode in ("ours-seq", "ours-par", "bslls"):
            report["perf"].append(_run_child(root, mode, limit=args.limit, largest=args.largest))
        if not args.no_parity:
            report["parity"].append(_parity_summary(root, limit=args.limit, largest=args.largest))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="*")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--mode", choices=("ours-seq", "ours-par", "bslls"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--largest", type=int)
    parser.add_argument("--no-parity", action="store_true")
    args = parser.parse_args(argv)
    if args.child:
        if not args.root or not args.mode:
            parser.error("--child requires --root and --mode")
    elif not args.roots:
        parser.error("at least one corpus root is required")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.child:
        return child_main(args)
    return parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
