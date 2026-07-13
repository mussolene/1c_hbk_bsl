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
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def index_storage_lock(db_path: str, *, blocking: bool = False) -> Iterator[bool]:
    """Acquire the cross-process writer lock for an index database.

    The lock file is intentionally persistent: removing lock files creates inode races
    where two processes can lock different files with the same path.  The yielded bool
    is false when another process owns the lock.
    """
    if db_path == ":memory:":
        yield True
        return

    lock_path = Path(f"{db_path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()

    acquired = False
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            handle.seek(0)
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(handle.fileno(), mode, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl  # noqa: PLC0415

            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(handle.fileno(), flags)
                acquired = True
            except BlockingIOError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt  # noqa: PLC0415

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def cleanup_index_storage(db_path: str, *, include_corrupt: bool = True) -> dict[str, int]:
    """Delete disposable SQLite index files. Caller must hold ``index_storage_lock``."""
    if db_path == ":memory:":
        return {"files_removed": 0, "bytes_removed": 0}

    db = Path(db_path)
    candidates = [db, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]
    if include_corrupt:
        candidates.extend(db.parent.glob(f"{db.name}*.corrupt.*"))

    files_removed = 0
    bytes_removed = 0
    for path in dict.fromkeys(candidates):
        try:
            size = path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            continue
        bytes_removed += size
        files_removed += 1
    return {"files_removed": files_removed, "bytes_removed": bytes_removed}


def cleanup_corrupt_index_storage(db_path: str) -> dict[str, int]:
    """Remove legacy quarantined cache copies while preserving the active DB."""
    if db_path == ":memory:":
        return {"files_removed": 0, "bytes_removed": 0}
    db = Path(db_path)
    files_removed = 0
    bytes_removed = 0
    for path in db.parent.glob(f"{db.name}*.corrupt.*"):
        try:
            size = path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            continue
        files_removed += 1
        bytes_removed += size
    return {"files_removed": files_removed, "bytes_removed": bytes_removed}
