#!/usr/bin/env python3
"""Run parity on largest3 as 3 sequential single-file shards and aggregate results."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from onec_hbk_bsl.analysis.bslls_runtime_parity import (
    capture_bslls_baseline,
    compare_with_bslls_baseline,
    compute_baseline_fingerprint,
    resolve_bslls_jar,
)


def _top_codes(diags):  # type: ignore[no-untyped-def]
    c = Counter()
    for item in diags:
        code = item.get("code") or item.get("code_source") or "UNKNOWN"
        c[code] += 1
    return c


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    corpus_root = repo_root / "corpus-largest-3"
    files = sorted(corpus_root.rglob("*.bsl"))
    if len(files) != 3:
        raise SystemExit(f"Expected 3 files in {corpus_root}, got {len(files)}")

    jar = resolve_bslls_jar(repo_root)
    baseline_dir = repo_root / ".nosync/reports/dev-corpus/baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    shard_results = []
    agg = {
        "diagnostics_only_ours": 0,
        "diagnostics_only_bslls": 0,
        "diagnostics_severity_mismatch": 0,
        "diagnostics_message_mismatch": 0,
        "diagnostics_anchor_mismatch": 0,
        "diagnostics_anchor_and_message_mismatch": 0,
        "diagnostics_anchor_and_severity_mismatch": 0,
        "diagnostics_anchor_message_severity_mismatch": 0,
        "formatting_diff_files": 0,
        "diagnostics_exact": True,
        "formatting_exact": True,
    }
    top_only_ours = Counter()
    top_only_bslls = Counter()

    for file_path in files:
        rel = file_path.resolve().relative_to(corpus_root.resolve()).as_posix()
        fingerprint = compute_baseline_fingerprint(
            workspace_root=corpus_root,
            files=[file_path],
            jar_path=jar,
            config_path=None,
        )
        baseline_file = baseline_dir / f"bslls-shard-{fingerprint}.json"
        baseline = capture_bslls_baseline(
            workspace_root=corpus_root,
            files=[file_path],
            config_path=None,
            jar_path=jar,
        )
        baseline_file.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        result = compare_with_bslls_baseline(
            workspace_root=corpus_root,
            files=[file_path],
            profile="strict-bslls",
            baseline=baseline,
        )
        d = result["diagnostics"]
        f = result["formatting"]
        shard_results.append(
            {
                "file": rel,
                "baseline": str(baseline_file),
                "diagnostics_exact": d["exact_match"],
                "formatting_exact": f["exact_match"],
                "diagnostics_only_ours": len(d["only_ours"]),
                "diagnostics_only_bslls": len(d["only_bslls"]),
                "diagnostics_severity_mismatch": len(d["severity_mismatch"]),
                "diagnostics_message_mismatch": len(d["message_mismatch"]),
                "diagnostics_anchor_mismatch": len(d.get("anchor_mismatch", [])),
                "formatting_diff_files": len(f["diffs"]),
                "top_only_ours_codes": d.get("top_only_ours_codes", []),
                "top_only_bslls_codes": d.get("top_only_bslls_codes", []),
            }
        )
        agg["diagnostics_only_ours"] += len(d["only_ours"])
        agg["diagnostics_only_bslls"] += len(d["only_bslls"])
        agg["diagnostics_severity_mismatch"] += len(d["severity_mismatch"])
        agg["diagnostics_message_mismatch"] += len(d["message_mismatch"])
        agg["diagnostics_anchor_mismatch"] += len(d.get("anchor_mismatch", []))
        agg["diagnostics_anchor_and_message_mismatch"] += len(
            d.get("anchor_and_message_mismatch", [])
        )
        agg["diagnostics_anchor_and_severity_mismatch"] += len(
            d.get("anchor_and_severity_mismatch", [])
        )
        agg["diagnostics_anchor_message_severity_mismatch"] += len(
            d.get("anchor_message_severity_mismatch", [])
        )
        agg["formatting_diff_files"] += len(f["diffs"])
        agg["diagnostics_exact"] = agg["diagnostics_exact"] and bool(d["exact_match"])
        agg["formatting_exact"] = agg["formatting_exact"] and bool(f["exact_match"])
        top_only_ours.update(_top_codes(d["only_ours"]))
        top_only_bslls.update(_top_codes(d["only_bslls"]))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = repo_root / ".agent" / "reports" / "python-bslls-full-parity" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "mode": "largest3_sharded",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "corpus_root": str(corpus_root),
        "profile": "strict-bslls",
        "shards": shard_results,
        "aggregate": {
            **agg,
            "top_only_ours_codes": top_only_ours.most_common(15),
            "top_only_bslls_codes": top_only_bslls.most_common(15),
        },
    }
    out_path = out_dir / f"largest3-sharded-parity-{stamp}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report: {out_path}")
    print(f"diagnostics_exact: {agg['diagnostics_exact']}")
    print(f"formatting_exact: {agg['formatting_exact']}")
    print(f"diagnostics_only_ours: {agg['diagnostics_only_ours']}")
    print(f"diagnostics_only_bslls: {agg['diagnostics_only_bslls']}")
    print(f"diagnostics_anchor_mismatch: {agg['diagnostics_anchor_mismatch']}")
    print(f"formatting_diff_files: {agg['formatting_diff_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
