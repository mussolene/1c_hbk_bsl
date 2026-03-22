#!/usr/bin/env python3
"""
Compare onec-hbk-bsl DiagnosticEngine keys to BSLLS ``analyze`` JSON (optional).

Requires a BSLLS fat jar (BSLLS_JAR or .nosync/bsl-language-server/**/bsl-language-server*.jar).
Creates outputDir if missing, runs::

  java -jar … analyze -s <dir_with_one_bsl> -o <out> -r json -q

Then compares (rel_path, 1-based line, normalized code) for each diagnostic.

Exit codes: 0 match, 1 mismatch, 2 BSLLS failed / no jar, 3 usage error.

This complements scripts/compare_diag_baseline.py (offline JSON baseline without Java).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse


def _find_jar(repo_root: Path, explicit: Path | None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit
    env = os.environ.get("BSLLS_JAR", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    nosync = repo_root / ".nosync" / "bsl-language-server"
    if nosync.is_dir():
        for p in sorted(nosync.rglob("bsl-language-server*.jar")):
            if p.is_file():
                return p
    return None


def _norm_keys_from_bslls_json(raw: dict, workspace: Path) -> set[tuple[str, int, str]]:
    from onec_hbk_bsl.analysis.diagnostics import resolve_rule_token_to_code

    keys: set[tuple[str, int, str]] = set()
    for fi in raw.get("fileinfos", []):
        rel = fi.get("path", "")
        if rel.startswith("file://"):
            p = Path(unquote(urlparse(rel).path))
            try:
                rel = str(p.resolve().relative_to(workspace.resolve()))
            except ValueError:
                rel = p.name
        for d in fi.get("diagnostics", []):
            line = int(d.get("range", {}).get("start", {}).get("line", 0)) + 1
            code = str(d.get("code", "")).strip()
            c = resolve_rule_token_to_code(code) or code.upper()
            keys.add((rel.replace("\\", "/"), line, c))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare onec diagnostics to BSLLS analyze JSON.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--jar", type=Path, default=None)
    parser.add_argument("--workspace", type=Path, required=True, help="Workspace root for path normalization")
    parser.add_argument("--file", type=Path, required=True, help="Single .bsl file to analyze (copied to temp dir)")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    workspace = args.workspace.resolve()
    fp = args.file.resolve()
    if not fp.is_file() or fp.suffix.lower() != ".bsl":
        print("Need an existing .bsl file", file=sys.stderr)
        return 3

    jar = _find_jar(repo_root, args.jar)
    if jar is None:
        print("SKIP: no BSLLS jar (BSLLS_JAR or .nosync/bsl-language-server/).", file=sys.stderr)
        return 2

    from onec_hbk_bsl.analysis.diagnostics import (
        DiagnosticEngine,
        parse_env_rule_filters,
        resolve_rule_token_to_code,
    )
    from onec_hbk_bsl.parser.bsl_parser import BslParser

    sel, ign = parse_env_rule_filters()
    engine = DiagnosticEngine(parser=BslParser(), select=sel, ignore=ign)
    onec_keys: set[tuple[str, int, str]] = set()
    for issue in engine.check_file(str(fp)):
        try:
            rel = str(Path(issue.file).resolve().relative_to(workspace))
        except ValueError:
            rel = Path(issue.file).name
        c = resolve_rule_token_to_code(issue.code) or str(issue.code).upper()
        onec_keys.add((rel.replace("\\", "/"), issue.line, c))

    java = os.environ.get("BSLLS_JAVA", "java")
    with tempfile.TemporaryDirectory(prefix="bslls-diag-") as td:
        src_dir = Path(td) / "src"
        out_dir = Path(td) / "out"
        src_dir.mkdir(parents=True)
        out_dir.mkdir(parents=True)
        dst = src_dir / fp.name
        dst.write_bytes(fp.read_bytes())
        r = subprocess.run(
            [
                java,
                "-jar",
                str(jar),
                "analyze",
                "-s",
                str(src_dir),
                "-o",
                str(out_dir),
                "-r",
                "json",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if r.returncode != 0:
            print(r.stderr or r.stdout or "BSLLS analyze failed", file=sys.stderr)
            return 2
        jpath = out_dir / "bsl-json.json"
        if not jpath.is_file():
            print("Missing bsl-json.json", file=sys.stderr)
            return 2
        raw = json.loads(jpath.read_text(encoding="utf-8"))

    bslls_keys = _norm_keys_from_bslls_json(raw, workspace)
    # BSLLS paths are often absolute file://…; normalize to basename match when workspace-relative fails
    onec_by_base = {(Path(a[0]).name, a[1], a[2]) for a in onec_keys}
    bslls_by_base = {(Path(b[0]).name, b[1], b[2]) for b in bslls_keys}
    only_bslls = bslls_by_base - onec_by_base
    only_onec = onec_by_base - bslls_by_base

    if not only_bslls and not only_onec:
        print("OK: onec keys match BSLLS analyze (file, line, code) for this file.")
        return 0

    print("Mismatch (by basename path):", file=sys.stderr)
    for x in sorted(only_bslls):
        print(f"  only in BSLLS: {x}", file=sys.stderr)
    for x in sorted(only_onec):
        print(f"  only in onec:  {x}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
