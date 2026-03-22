#!/usr/bin/env python3
"""
Compare onec-hbk-bsl BslFormatter output to BSLLS CLI formatter (when available).

BSLLS (1c-syntax) exposes a `format` subcommand on the fat jar:

  java -jar bsl-language-server.jar format <path>

Set BSLLS_JAR to the jar path, or pass --jar. Paths are searched in order:
  BSLLS_JAR, --jar, then .nosync/bsl-language-server/**/bsl-language-server*.jar
  under the repo root (optional local clone).

Without a jar, exits 0 with a short message (CI-friendly skip).

Parity rules (defaults):
  • onec output uses tabs like BSLLS CLI: insert_spaces=False in BslFormatter.
  • Full-line // comments: BSLLS does not reformat them; use --strict-comments to
    require exact comment text, otherwise pairs of full-line comments are ignored.
  • Lines are compared after rstrip; BOM-only / whitespace-only lines normalize
    to empty.

Optional: --external-root /path/to/other-bsl-tree — compare all .bsl under that
tree (respects FORMAT_MAX_FILES, default 30).
"""
from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path


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


def _run_bslls_format(jar: Path, bsl_path: Path) -> str:
    """Run BSLLS format in-place; read result from the same path.

    Use cwd=parent directory and pass basename only so BSLLS does not scan the
    whole repository when the CLI is invoked from the project root.
    """
    java = os.environ.get("BSLLS_JAVA", "java")
    r = subprocess.run(
        [java, "-jar", str(jar), "format", bsl_path.name],
        cwd=str(bsl_path.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"BSLLS format failed ({r.returncode}): {r.stderr or r.stdout or '(no output)'}"
        )
    text = bsl_path.read_text(encoding="utf-8")
    # Align with BslFormatter: single trailing newline
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _onec_format(src: str, repo_root: Path) -> str:
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from onec_hbk_bsl.analysis.formatter import default_formatter

    # BSLLS CLI indents with tabs by default; match that for parity (LSP still uses client options).
    return default_formatter.format(src, insert_spaces=False)


def _is_full_line_comment_line(line: str) -> bool:
    s = line.strip()
    return bool(s.startswith("//"))


def _norm_line_for_parity(line: str) -> str:
    """Trailing whitespace off; whitespace-only lines become empty (BSLLS may leave tab-only rows)."""
    s = line.replace("\ufeff", "").rstrip()
    if not s.strip():
        return ""
    return s


def _equal_for_bslls_parity(bslls: str, onec: str, *, ignore_full_line_comments: bool) -> bool:
    """BSLLS leaves full-line // comments unchanged; onec may normalize spaces after //.

    When ``ignore_full_line_comments`` is True, lines where *both* sides are full-line
    comments are treated as equal; other lines match after ``_norm_line_for_parity``.
    """
    a = bslls.replace("\r\n", "\n")
    b = onec.replace("\r\n", "\n")
    la = a.splitlines()
    lb = b.splitlines()
    if len(la) != len(lb):
        return False
    for x, y in zip(la, lb, strict=True):
        if ignore_full_line_comments and _is_full_line_comment_line(x) and _is_full_line_comment_line(y):
            continue
        if _norm_line_for_parity(x) != _norm_line_for_parity(y):
            return False
    return True


def _collect_files(root: Path, max_files: int) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*.bsl")):
        if p.is_file():
            out.append(p)
        if len(out) >= max_files:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare onec formatter vs BSLLS format CLI.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root (for .nosync jar search)",
    )
    parser.add_argument("--jar", type=Path, default=None, help="Path to bsl-language-server.jar")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help="Directory with .bsl samples (e.g. tests/fixtures/format_parity)",
    )
    parser.add_argument(
        "--external-root",
        type=Path,
        default=None,
        help="Optional external directory tree of .bsl files to compare",
    )
    parser.add_argument("--max-files", type=int, default=int(os.environ.get("FORMAT_MAX_FILES", "30")))
    parser.add_argument(
        "--max-diff-lines",
        type=int,
        default=80,
        help="Print at most this many diff lines per file",
    )
    parser.add_argument(
        "--strict-comments",
        action="store_true",
        help="Require full-line // comments to match exactly (default: ignore comment text parity)",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    jar = _find_jar(repo_root, args.jar)
    if jar is None:
        print(
            "SKIP: no BSLLS jar (set BSLLS_JAR or place jar under .nosync/bsl-language-server/).",
            file=sys.stderr,
        )
        return 0

    files_set: dict[str, Path] = {}
    if args.fixtures:
        for p in _collect_files(args.fixtures.resolve(), args.max_files):
            files_set[str(p.resolve())] = p
    if args.external_root:
        for p in _collect_files(args.external_root.resolve(), args.max_files):
            files_set[str(p.resolve())] = p
    files = list(files_set.values())

    if not files:
        print("No .bsl files (use --fixtures and/or --external-root).", file=sys.stderr)
        return 1

    import tempfile

    bad = 0
    for fp in files:
        original = fp.read_text(encoding="utf-8")
        ours = _onec_format(original, repo_root)
        tag = format(abs(hash(str(fp.resolve()))), "x")[:12]
        with tempfile.TemporaryDirectory(prefix="bslls-fmt-") as td:
            tmp = Path(td) / f"{fp.stem}_{tag}.bsl"
            tmp.write_text(original, encoding="utf-8")
            try:
                theirs = _run_bslls_format(jar, tmp)
            except RuntimeError as e:
                print(f"{fp}: {e}", file=sys.stderr)
                bad += 1
                continue
        ign = not args.strict_comments
        if _equal_for_bslls_parity(theirs, ours, ignore_full_line_comments=ign):
            print(f"OK {fp}")
            continue
        print(f"DIFF {fp}", file=sys.stderr)
        diff_lines = list(
            difflib.unified_diff(
                theirs.splitlines(),
                ours.splitlines(),
                fromfile="bslls",
                tofile="onec-hbk-bsl",
                lineterm="",
            )
        )
        for line in diff_lines[: args.max_diff_lines]:
            print(line, file=sys.stderr)
        if len(diff_lines) > args.max_diff_lines:
            print(f"... ({len(diff_lines)} diff lines, truncated)", file=sys.stderr)
        bad += 1

    if bad:
        print(f"{bad} file(s) differ from BSLLS (see above).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
