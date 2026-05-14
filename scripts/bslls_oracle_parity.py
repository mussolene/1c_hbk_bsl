#!/usr/bin/env python3
"""Run container BSLLS and compare it with onec-hbk-bsl diagnostics.

The oracle is the portable `1c-develop` image. The script intentionally avoids
host Java/JAR discovery so the reference run is independent from the host
environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "ghcr.io/mussolene/1c-developer:8.5.1.1302"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def _prepare_target(target: Path, *, repo_root: Path) -> tuple[Path, str]:
    if target.is_dir():
        try:
            target.resolve().relative_to(repo_root.resolve())
        except ValueError as exc:
            raise RuntimeError(
                "external directory targets are too easy to make accidentally heavy; "
                "pass a single .bsl file or stage a small directory inside the repository",
            ) from exc
        return target, _rel(target, repo_root)
    if not target.is_file():
        raise RuntimeError(f"target does not exist: {target}")

    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:16]
    staged_dir = repo_root / ".agent" / "tmp" / "bslls-oracle-input" / digest
    shutil.rmtree(staged_dir, ignore_errors=True)
    staged_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, staged_dir / target.name)
    return staged_dir, _rel(target, repo_root)


def _container_bslls(
    target: Path,
    *,
    output_dir: Path,
    image: str,
    repo_root: Path,
) -> dict[str, Any]:
    if not shutil.which("docker"):
        raise RuntimeError("docker is not available")
    output_dir.mkdir(parents=True, exist_ok=True)
    rel_target = _rel(target, repo_root)
    rel_output = _rel(output_dir, repo_root)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/workspace/project",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "bash",
        image,
        "-lc",
        (
            f"rm -rf {rel_output!r} && mkdir -p {rel_output!r} && "
            f"export BSLLS_OUTPUT_DIR={rel_output!r}; "
            f"onec-agent bslls {rel_target!r}"
        ),
    ]
    proc = _run(cmd, cwd=repo_root)
    (output_dir / "bslls.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "bslls.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"container BSLLS failed with exit code {proc.returncode}")
    report_path = output_dir / "bsl-json.json"
    if not report_path.is_file():
        raise RuntimeError(f"container BSLLS did not write {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _local_diagnostics(target: Path, *, repo_root: Path) -> list[Any]:
    from onec_hbk_bsl.analysis.bslls_runtime_parity import iter_bsl_files
    from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
    from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
    from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

    files = iter_bsl_files(target) if target.is_dir() else [target]
    idx = SymbolIndex(db_path=":memory:")
    indexer = IncrementalIndexer(index=idx, quiet=True)
    indexer.index_metadata(str(target if target.is_dir() else target.parent))
    for path in files:
        indexer.index_file(str(path))
    engine = DiagnosticEngine(symbol_index=idx)
    out = []
    try:
        for path in files:
            content = path.read_text(encoding="utf-8", errors="ignore")
            out.extend(
                d
                for d in engine.check_content(str(path), content, symbol_index=idx)
                if engine._rule_enabled(d.code)
            )
    finally:
        idx.close()
    return out


def _summarize_diff(diff: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "only_ours": len(diff["only_ours"]),
        "only_bslls": len(diff["only_bslls"]),
        "message_mismatch": len(diff["message_mismatch"]),
        "severity_mismatch": len(diff["severity_mismatch"]),
        "anchor_mismatch": len(diff["anchor_mismatch"]),
        "anchor_and_message_mismatch": len(diff["anchor_and_message_mismatch"]),
        "anchor_and_severity_mismatch": len(diff["anchor_and_severity_mismatch"]),
        "anchor_message_severity_mismatch": len(diff["anchor_message_severity_mismatch"]),
        "exact_match": bool(diff["exact_match"]),
    }
    return summary


def _top_codes(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return Counter(str(row.get("code")) for row in rows).most_common(20)


def _rule_filter_tokens(rules: list[str]) -> list[str]:
    return [token for raw in rules for token in str(raw).replace(",", " ").split()]


def _rule_filter_codes(rules: list[str]) -> set[str]:
    from onec_hbk_bsl.analysis.diagnostics import resolve_rule_token_to_code

    return {
        code for token in _rule_filter_tokens(rules) if (code := resolve_rule_token_to_code(token))
    }


def _row_rule_code(row: Any) -> str | None:
    from onec_hbk_bsl.analysis.diagnostics import resolve_rule_token_to_code

    source = str(row.code_source)
    if source.upper().startswith("BSL"):
        return source.upper()
    return resolve_rule_token_to_code(str(row.code))


def _filter_normalized_by_rule(rows: list[Any], rules: list[str]) -> list[Any]:
    if not rules:
        return rows
    codes = _rule_filter_codes(rules)
    return [row for row in rows if _row_rule_code(row) in codes]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare onec-hbk-bsl diagnostics with container BSLLS",
    )
    parser.add_argument("target", nargs="?", default="tests/fixtures")
    parser.add_argument("--image", default=os.environ.get("BSLLS_ORACLE_IMAGE", DEFAULT_IMAGE))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".agent/reports/bslls-oracle"),
        help="Directory for oracle and parity artifacts",
    )
    parser.add_argument(
        "--reuse-oracle",
        action="store_true",
        help="Reuse output-dir/bsl-json.json instead of running Docker",
    )
    parser.add_argument(
        "--rule",
        action="append",
        default=[],
        help="Compare only this rule code or BSLLS diagnostic name; repeatable",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()
    if args.rule:
        unknown_rules = sorted(set(_rule_filter_tokens(args.rule)) - _rule_filter_codes(args.rule))
        if unknown_rules:
            parser.error(f"unknown --rule value(s): {', '.join(unknown_rules)}")

    repo_root = REPO_ROOT
    target = (repo_root / args.target).resolve()
    effective_target, original_target = _prepare_target(target, repo_root=repo_root)
    output_dir = (repo_root / args.output_dir).resolve()
    report_path = output_dir / "bsl-json.json"

    if args.reuse_oracle and report_path.is_file():
        bslls_report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        bslls_report = _container_bslls(
            effective_target,
            output_dir=output_dir,
            image=args.image,
            repo_root=repo_root,
        )

    from onec_hbk_bsl.analysis.bslls_runtime_parity import (
        diff_diagnostics,
        normalize_bslls_json_report,
        normalize_our_diagnostics,
    )

    ours = normalize_our_diagnostics(
        _local_diagnostics(effective_target, repo_root=repo_root),
        workspace_root=effective_target,
    )
    bslls = normalize_bslls_json_report(
        bslls_report,
        workspace_root=effective_target,
        extra_roots=(
            repo_root,
            Path("/workspace/project") / _rel(effective_target, repo_root),
            Path("/workspace/project"),
        ),
    )
    ours = _filter_normalized_by_rule(ours, args.rule)
    bslls = _filter_normalized_by_rule(bslls, args.rule)
    diff = diff_diagnostics(ours, bslls)
    payload = {
        "target": _rel(effective_target, repo_root),
        "original_target": original_target,
        "rule_filter": {
            "input": args.rule,
            "codes": sorted(_rule_filter_codes(args.rule)),
        },
        "oracle": {
            "image": args.image,
            "report": _rel(report_path, repo_root),
            "diagnostics": len(bslls),
        },
        "ours": {"diagnostics": len(ours)},
        "summary": _summarize_diff(diff),
        "top_only_ours_codes": _top_codes(diff["only_ours"]),
        "top_only_bslls_codes": _top_codes(diff["only_bslls"]),
        "diff": diff,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "parity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        print(f"wrote: {_rel(output_dir / 'parity.json', repo_root)}")
    return 0 if payload["summary"]["exact_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
