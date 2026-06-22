#!/usr/bin/env python3
"""Compare selected onec-hbk-bsl diagnostics with BSLLS ``analyze`` JSON.

This is a development-only parity helper. It deliberately compares only the
requested rule set on both sides, so neighbouring BSLLS diagnostics cannot
pollute a focused rule audit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onec_hbk_bsl.analysis.diagnostics import (  # noqa: E402
    DiagnosticEngine,
    resolve_rule_token_to_code,
)
from onec_hbk_bsl.parser.bsl_parser import BslParser  # noqa: E402


@dataclass(frozen=True, order=True)
class DiagnosticKey:
    file_key: str
    line: int
    character: int
    end_line: int
    end_character: int
    code: str


def normalize_rule_codes(raw: str) -> frozenset[str]:
    codes: set[str] = set()
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        code = resolve_rule_token_to_code(token) or token.upper()
        codes.add(code)
    if not codes:
        raise ValueError("--select must contain at least one rule code or BSLLS name")
    return frozenset(codes)


def find_bslls_jar(repo_root: Path, explicit: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    env = os.environ.get("BSLLS_JAR", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates.extend(sorted((repo_root / ".nosync" / "bsl-language-server").glob("**/*.jar")))
    candidates.extend(sorted(Path.home().glob(".cache/onec-hbk-bsl/bslls/bsl-language-server*-exec.jar")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _relative_file_key(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.name


def _path_from_uri_or_text(value: str) -> Path | None:
    if not value:
        return None
    if value.startswith("file://"):
        parsed = urlparse(value)
        return Path(unquote(parsed.path))
    return Path(value)


def _bslls_file_key(fileinfo: dict, source_root: Path, workspace: Path) -> str:
    for field in ("mdoRef", "path"):
        path = _path_from_uri_or_text(str(fileinfo.get(field, "")))
        if path is None:
            continue
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            try:
                return path.resolve().relative_to(workspace.resolve()).as_posix()
            except ValueError:
                continue
    return Path(str(fileinfo.get("path", ""))).name


def onec_keys(files: list[Path], workspace: Path, select: frozenset[str]) -> set[DiagnosticKey]:
    engine = DiagnosticEngine(parser=BslParser(), select=select)
    keys: set[DiagnosticKey] = set()
    for path in files:
        for issue in engine.check_file(str(path)):
            code = resolve_rule_token_to_code(issue.code) or str(issue.code).upper()
            if code not in select:
                continue
            keys.add(
                DiagnosticKey(
                    file_key=_relative_file_key(Path(issue.file), workspace),
                    line=issue.line,
                    character=issue.character,
                    end_line=issue.end_line,
                    end_character=issue.end_character,
                    code=code,
                )
            )
    return keys


def bslls_keys(raw: dict, source_root: Path, workspace: Path, select: frozenset[str]) -> set[DiagnosticKey]:
    keys: set[DiagnosticKey] = set()
    for fileinfo in raw.get("fileinfos", []):
        file_key = _bslls_file_key(fileinfo, source_root, workspace)
        for item in fileinfo.get("diagnostics", []):
            code = resolve_rule_token_to_code(str(item.get("code", "")).strip()) or str(
                item.get("code", "")
            ).upper()
            if code not in select:
                continue
            diagnostic_range = item.get("range", {})
            start = diagnostic_range.get("start", {})
            end = diagnostic_range.get("end", {})
            keys.add(
                DiagnosticKey(
                    file_key=file_key,
                    line=int(start.get("line", 0)) + 1,
                    character=int(start.get("character", 0)),
                    end_line=int(end.get("line", 0)) + 1,
                    end_character=int(end.get("character", 0)),
                    code=code,
                )
            )
    return keys


def _selected_files(workspace: Path, paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else workspace / raw_path
        if path.is_file() and path.suffix.lower() == ".bsl":
            files.append(path.resolve())
            continue
        if path.is_dir():
            files.extend(sorted(p.resolve() for p in path.rglob("*.bsl") if p.is_file()))
            continue
        raise FileNotFoundError(f"not a .bsl file or directory: {raw_path}")
    return sorted(set(files))


def _copy_inputs(files: list[Path], workspace: Path, source_root: Path) -> list[Path]:
    copied: list[Path] = []
    for path in files:
        rel = Path(_relative_file_key(path, workspace))
        destination = source_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(destination)
    return copied


def run_bslls(jar: Path, source_root: Path, output_dir: Path) -> dict:
    java = os.environ.get("BSLLS_JAVA", "java")
    command = [
        java,
        "-jar",
        str(jar),
        "analyze",
        "-s",
        str(source_root),
        "-w",
        str(source_root),
        "-o",
        str(output_dir),
        "-r",
        "json",
        "-q",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=240)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "BSLLS analyze failed"
        raise RuntimeError(message)
    json_path = output_dir / "bsl-json.json"
    if not json_path.is_file():
        raise RuntimeError("BSLLS did not produce bsl-json.json")
    return json.loads(json_path.read_text(encoding="utf-8"))


def _print_delta(label: str, values: set[DiagnosticKey], *, limit: int) -> None:
    print(f"{label}: {len(values)}")
    for value in sorted(values)[:limit]:
        print(
            "  "
            f"{value.file_key}:{value.line}:{value.character}-"
            f"{value.end_line}:{value.end_character} {value.code}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help=".bsl files or directories under workspace")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--select", required=True, help="Comma-separated BSL### or BSLLS rule names")
    parser.add_argument("--jar", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--limit", type=int, default=30, help="Maximum deltas printed per side")
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    select = normalize_rule_codes(args.select)
    jar = find_bslls_jar(args.repo_root.resolve(), args.jar)
    if jar is None:
        print("SKIP: no BSLLS jar found (use --jar, BSLLS_JAR, .nosync, or user cache).", file=sys.stderr)
        return 2

    try:
        files = _selected_files(workspace, args.paths)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if not files:
        print("No .bsl files selected.", file=sys.stderr)
        return 3

    try:
        with tempfile.TemporaryDirectory(prefix="bslls-parity-") as td:
            source_root = Path(td) / "src"
            output_dir = Path(td) / "out"
            source_root.mkdir(parents=True)
            output_dir.mkdir()
            copied = _copy_inputs(files, workspace, source_root)
            ours = onec_keys(copied, source_root, select)
            raw = run_bslls(jar, source_root, output_dir)
            theirs = bslls_keys(raw, source_root, source_root, select)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(str(exc), file=sys.stderr)
        return 2

    only_bslls = theirs - ours
    only_onec = ours - theirs
    print(f"selected: {','.join(sorted(select))}")
    print(f"files: {len(files)}")
    print(f"onec: {len(ours)}")
    print(f"bslls: {len(theirs)}")
    if not only_bslls and not only_onec:
        print("OK: selected diagnostics match by file, range, and code.")
        return 0

    _print_delta("only_bslls", only_bslls, limit=args.limit)
    _print_delta("only_onec", only_onec, limit=args.limit)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
