"""
Resolves the default path for the BSL index SQLite database.

Priority:
1. ``INDEX_DB_PATH`` environment variable (explicit override).
2. ``.git/bsl_index.sqlite`` — if *workspace* is inside a git repository.
   This is 100 % gitignored by design (git never tracks its own .git/ folder).
3. ``~/.cache/bsl-analyzer/<sha1[:12] of workspace>/bsl_index.sqlite`` —
   XDG-style cache for non-git directories.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


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
            return str(git_dir / "bsl_index.sqlite")

    # 3. XDG / user-cache fallback
    h = hashlib.sha1(str(p).encode()).hexdigest()[:12]  # noqa: S324
    cache_dir = Path.home() / ".cache" / "bsl-analyzer" / h
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir / "bsl_index.sqlite")
