"""
Git utilities for onec-hbk-bsl CLI.

Provides helpers to find BSL files changed in git (for --diff mode).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _run_git(args: list[str], cwd: str) -> list[str]:
    """Run a git command and return stripped non-empty output lines."""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _run_git_text(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout text, or an empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


BSL_EXTENSIONS = {".bsl", ".os"}


def git_changed_files(workspace: str, since: str | None = None) -> list[str]:
    """
    Return a list of added/modified BSL files relative to *since*.

    Args:
        workspace: Path to search from (used as git cwd and base for relative paths).
        since:     Git ref to diff against. Defaults to ``HEAD`` (staged + unstaged).
                   Common values: ``HEAD``, ``HEAD~1``, ``main``, ``origin/main``.

    Returns:
        List of absolute paths to changed .bsl/.os files that exist on disk.
        Empty list if not in a git repository or no BSL files changed.
    """
    # Determine git root
    git_root_lines = _run_git(["rev-parse", "--show-toplevel"], cwd=workspace)
    if not git_root_lines:
        return []
    git_root = git_root_lines[0]

    if since is None:
        # Staged + unstaged changes vs HEAD
        changed = _run_git(
            ["diff", "--name-only", "--diff-filter=ACM", "HEAD"],
            cwd=git_root,
        )
        # Also include untracked files
        untracked = _run_git(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=git_root,
        )
        changed = list(dict.fromkeys(changed + untracked))  # deduplicate, preserve order
    else:
        changed = _run_git(
            ["diff", "--name-only", "--diff-filter=ACM", since, "HEAD"],
            cwd=git_root,
        )

    result: list[str] = []
    for rel in changed:
        p = Path(git_root) / rel
        if p.suffix.lower() in BSL_EXTENSIONS and p.is_file():
            result.append(str(p.resolve()))

    return result


_DIFF_HEADER_RE = re.compile(r"^\+\+\+ b/(.*)$")
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def _parse_unified_diff_changed_ranges(
    diff_text: str, git_root: str
) -> dict[str, list[tuple[int, int]]]:
    """Parse ``git diff -U0`` output into absolute-path changed line ranges."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    for line in diff_text.splitlines():
        header = _DIFF_HEADER_RE.match(line)
        if header:
            rel = header.group(1)
            current_file = None if rel == "/dev/null" else str((Path(git_root) / rel).resolve())
            continue

        hunk = _DIFF_HUNK_RE.match(line)
        if not hunk or current_file is None:
            continue

        start = int(hunk.group("start"))
        count = int(hunk.group("count") or "1")
        if count <= 0:
            continue
        ranges.setdefault(current_file, []).append((start, start + count - 1))

    return ranges


def git_changed_line_ranges(
    workspace: str, since: str | None = None
) -> dict[str, list[tuple[int, int]]]:
    """
    Return changed 1-based line ranges for added/modified BSL files.

    Untracked BSL files are represented as the full current file range.
    """
    git_root_lines = _run_git(["rev-parse", "--show-toplevel"], cwd=workspace)
    if not git_root_lines:
        return {}
    git_root = git_root_lines[0]

    if since is None:
        diff_args = ["diff", "--unified=0", "--diff-filter=ACM", "HEAD"]
        untracked = _run_git(["ls-files", "--others", "--exclude-standard"], cwd=git_root)
    else:
        diff_args = ["diff", "--unified=0", "--diff-filter=ACM", since, "HEAD"]
        untracked = []

    ranges = _parse_unified_diff_changed_ranges(_run_git_text(diff_args, cwd=git_root), git_root)

    allowed_files = set(git_changed_files(workspace, since=since))
    ranges = {path: spans for path, spans in ranges.items() if path in allowed_files}

    for rel in untracked:
        p = (Path(git_root) / rel).resolve()
        if p.suffix.lower() not in BSL_EXTENSIONS or not p.is_file():
            continue
        try:
            line_count = len(p.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if line_count:
            ranges[str(p)] = [(1, line_count)]

    return ranges


def git_root(path: str) -> str | None:
    """Return the git root for the given path, or None if not in a repository."""
    lines = _run_git(
        ["rev-parse", "--show-toplevel"],
        cwd=os.path.dirname(path) if os.path.isfile(path) else path,
    )
    return lines[0] if lines else None
