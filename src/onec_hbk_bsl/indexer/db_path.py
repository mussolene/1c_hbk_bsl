"""
Resolves the default path for the BSL index SQLite database.

Priority:
1. ``INDEX_DB_PATH`` environment variable (explicit override).
2. ``.git/onec-hbk-bsl_index.sqlite`` — if *workspace* is inside a git repository.
   This is 100 % gitignored by design (git never tracks its own .git/ folder).
3. ``~/.cache/onec-hbk-bsl/<sha1[:12] of workspace>/onec-hbk-bsl_index.sqlite`` —
   XDG-style cache for non-git directories.

If the new default file is missing but a legacy ``bsl_index.sqlite`` exists in the
same directory (older onec-hbk-bsl builds), that path is used so the index is not
rebuilt unnecessarily.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Matches product / extension branding (see ``onec-hbk-bsl`` package & VS Code id).
INDEX_DB_FILENAME = "onec-hbk-bsl_index.sqlite"
LEGACY_INDEX_DB_FILENAME = "bsl_index.sqlite"


def _index_db_file_in_dir(directory: Path) -> Path:
    """Prefer the current filename; fall back to legacy ``bsl_index.sqlite`` if present."""
    preferred = directory / INDEX_DB_FILENAME
    legacy = directory / LEGACY_INDEX_DB_FILENAME
    if preferred.exists():
        return preferred
    if legacy.exists():
        return legacy
    return preferred


def resolve_index_db_path(workspace: str) -> str:
    """Return the path where the BSL index DB should be stored.

    The resolution order is documented in the module docstring.
    The caller is responsible for creating parent directories if needed.
    """
    # 1. Explicit env override — highest priority
    env = os.environ.get("INDEX_DB_PATH")
    if env:
        return env

    p = Path(workspace).resolve()

    # 2. Walk up looking for a .git directory
    for candidate in [p, *p.parents]:
        git_dir = candidate / ".git"
        if git_dir.is_dir():
            return str(_index_db_file_in_dir(git_dir))

    # 3. XDG / user-cache fallback
    h = hashlib.sha1(str(p).encode()).hexdigest()[:12]  # noqa: S324
    cache_dir = Path.home() / ".cache" / "onec-hbk-bsl" / h
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(_index_db_file_in_dir(cache_dir))
