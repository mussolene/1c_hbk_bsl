"""Shared filesystem discovery helpers for workspace indexing."""

from __future__ import annotations

from pathlib import Path

EXCLUDED_DISCOVERY_DIRS: frozenset[str] = frozenset(
    {
        ".agent",
        ".agents",
        ".cache",
        ".codex",
        ".cursor",
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)


def is_discovery_dir(name: str) -> bool:
    """Return true when a directory name should be traversed by index discovery."""
    return name not in EXCLUDED_DISCOVERY_DIRS and not name.endswith(".egg-info")


def iter_discovery_dirs(path: Path) -> list[Path]:
    """Return traversable direct child directories, ignoring unavailable folders."""
    try:
        return [
            child for child in path.iterdir() if child.is_dir() and is_discovery_dir(child.name)
        ]
    except PermissionError:
        return []
