"""
Git utilities for onec-hbk-bsl CLI.

Provides helpers to find BSL files changed in git (for --diff mode).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_git(args: list[str], cwd: str) -> list[str]:
    """Run a git command and return stripped non-empty output lines."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


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


def git_root(path: str) -> str | None:
    """Return the git root for the given path, or None if not in a repository."""
    lines = _run_git(["rev-parse", "--show-toplevel"], cwd=os.path.dirname(path) if os.path.isfile(path) else path)
    return lines[0] if lines else None
