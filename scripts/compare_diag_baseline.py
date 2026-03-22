#!/usr/bin/env python3
"""
Compare onec-hbk-bsl DiagnosticEngine output to a saved baseline JSON (e.g. from BSLLS).

Does not invoke bsl-language-server — baseline must be produced offline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _norm_path(key: str, workspace: Path) -> str:
    p = Path(key)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(workspace.resolve()))
        except ValueError:
            return str(p.resolve())
    return str(p).replace("\\", "/")


def _diag_key(
    file: str,
    line: int,
    code: str,
    workspace: Path,
) -> tuple[str, int, str]:
    from onec_hbk_bsl.analysis.diagnostics import resolve_rule_token_to_code

    nf = _norm_path(file, workspace)
    raw = str(code).strip()
    c = resolve_rule_token_to_code(raw) or raw.upper()
    return (nf, int(line), c)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare onec diagnostics to baseline JSON.")
    parser.add_argument("--baseline", required=True, type=Path, help="Path to baseline.json")
    parser.add_argument("--workspace", required=True, type=Path, help="Workspace root")
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help=".bsl files to check (absolute or relative to workspace)",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    os.chdir(workspace)

    raw = json.loads(args.baseline.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        print("Warning: expected baseline version 1", file=sys.stderr)

    baseline_keys: set[tuple[str, int, str]] = set()
    for d in raw.get("diagnostics", []):
        baseline_keys.add(
            _diag_key(d["file"], d["line"], d["code"], workspace),
        )

    from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine, parse_env_rule_filters
    from onec_hbk_bsl.parser.bsl_parser import BslParser

    sel, ign = parse_env_rule_filters()
    engine = DiagnosticEngine(parser=BslParser(), select=sel, ignore=ign)

    actual_keys: set[tuple[str, int, str]] = set()
    for f in args.files:
        fp = Path(f)
        if not fp.is_absolute():
            fp = workspace / fp
        fp = fp.resolve()
        issues = engine.check_file(str(fp))
        for issue in issues:
            rel = _norm_path(issue.file, workspace)
            actual_keys.add((rel, issue.line, issue.code))

    only_base = baseline_keys - actual_keys
    only_actual = actual_keys - baseline_keys

    if not only_base and not only_actual:
        print("OK: baseline matches onec-hbk-bsl for (file, line, code) keys.")
        return 0

    print("Mismatch:", file=sys.stderr)
    for x in sorted(only_base):
        print(f"  only in baseline: {x}", file=sys.stderr)
    for x in sorted(only_actual):
        print(f"  only in onec:     {x}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
