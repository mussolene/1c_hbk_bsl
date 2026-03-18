"""
Configuration loader for bsl-analyzer.

Searches (in order of increasing priority):
1. ``pyproject.toml`` — ``[tool.bsl-analyzer]`` section
2. ``bsl-analyzer.toml`` — ``[bsl-analyzer]`` section or root-level keys

Walk starts from *search_from* (defaults to cwd) and ascends to the filesystem
root, stopping at the first file that contains a bsl-analyzer configuration.

Supported keys
--------------
select              list[str]   — run only these rule codes
ignore              list[str]   — always-skip rule codes
exclude             list[str]   — glob patterns for excluded paths
per-file-ignores    dict        — {"pattern": ["BSL001"]}
format              str         — text | json | sonarqube | sarif
jobs                int         — 0 = auto
exit-zero           bool        — never return exit code 1
baseline            str         — path to baseline JSON
max-line-length     int
max-proc-lines      int
max-cognitive-complexity  int
max-mccabe-complexity     int
max-nesting-depth         int
max-params                int
max-returns               int
max-bool-ops              int
min-duplicate-uses        int
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path
from typing import Any


class BslConfig:
    """Merged configuration built from a TOML section."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # ------------------------------------------------------------------
    # Rule selection
    # ------------------------------------------------------------------

    @property
    def select(self) -> set[str] | None:
        v = self._data.get("select")
        if not v:
            return None
        return {c.strip().upper() for c in v}

    @property
    def ignore(self) -> set[str] | None:
        v = self._data.get("ignore")
        if not v:
            return None
        return {c.strip().upper() for c in v}

    # ------------------------------------------------------------------
    # File filtering
    # ------------------------------------------------------------------

    @property
    def exclude(self) -> list[str]:
        return list(self._data.get("exclude", []))

    @property
    def per_file_ignores(self) -> dict[str, list[str]]:
        return dict(self._data.get("per-file-ignores", {}))

    def is_excluded(self, file_path: str) -> bool:
        """Return True if *file_path* matches any exclude pattern."""
        p = Path(file_path)
        for pattern in self.exclude:
            # Exact fnmatch on full path
            if fnmatch.fnmatch(str(p), pattern):
                return True
            # Basename only
            if fnmatch.fnmatch(p.name, pattern):
                return True
            # Any path component (e.g. "vendor" matches .../vendor/...)
            stripped = pattern.rstrip("/")
            for part in p.parts:
                if fnmatch.fnmatch(part, stripped):
                    return True
        return False

    def get_file_ignores(self, file_path: str) -> set[str]:
        """Return extra ignore codes for *file_path* from per-file-ignores."""
        p = Path(file_path)
        result: set[str] = set()
        for pattern, codes in self.per_file_ignores.items():
            if fnmatch.fnmatch(str(p), pattern) or fnmatch.fnmatch(p.name, pattern):
                result.update(c.strip().upper() for c in codes)
        return result

    # ------------------------------------------------------------------
    # Output / behaviour
    # ------------------------------------------------------------------

    @property
    def format(self) -> str | None:
        return self._data.get("format")

    @property
    def jobs(self) -> int | None:
        v = self._data.get("jobs")
        return int(v) if v is not None else None

    @property
    def exit_zero(self) -> bool:
        return bool(self._data.get("exit-zero", False))

    @property
    def baseline(self) -> str | None:
        return self._data.get("baseline")

    # ------------------------------------------------------------------
    # DiagnosticEngine threshold overrides
    # ------------------------------------------------------------------

    @property
    def max_line_length(self) -> int | None:
        return self._data.get("max-line-length")

    @property
    def max_proc_lines(self) -> int | None:
        return self._data.get("max-proc-lines")

    @property
    def max_cognitive_complexity(self) -> int | None:
        return self._data.get("max-cognitive-complexity")

    @property
    def max_mccabe_complexity(self) -> int | None:
        return self._data.get("max-mccabe-complexity")

    @property
    def max_nesting_depth(self) -> int | None:
        return self._data.get("max-nesting-depth")

    @property
    def max_params(self) -> int | None:
        return self._data.get("max-params")

    @property
    def max_returns(self) -> int | None:
        return self._data.get("max-returns")

    @property
    def max_bool_ops(self) -> int | None:
        return self._data.get("max-bool-ops")

    @property
    def min_duplicate_uses(self) -> int | None:
        return self._data.get("min-duplicate-uses")

    def engine_kwargs(self) -> dict[str, Any]:
        """Return DiagnosticEngine __init__ kwargs derived from config (non-None only)."""
        mapping = {
            "max_line_length": self.max_line_length,
            "max_proc_lines": self.max_proc_lines,
            "max_cognitive_complexity": self.max_cognitive_complexity,
            "max_mccabe_complexity": self.max_mccabe_complexity,
            "max_nesting_depth": self.max_nesting_depth,
            "max_params": self.max_params,
            "max_returns": self.max_returns,
            "max_bool_ops": self.max_bool_ops,
            "min_duplicate_uses": self.min_duplicate_uses,
        }
        return {k: v for k, v in mapping.items() if v is not None}


# Singleton representing "no config found"
_EMPTY = BslConfig({})


def load_config(search_from: str | None = None) -> BslConfig:
    """
    Walk up from *search_from* and return the first bsl-analyzer config found.

    Priority (first wins):
    - ``bsl-analyzer.toml`` in any ancestor directory
    - ``pyproject.toml`` with a ``[tool.bsl-analyzer]`` section

    Returns :data:`_EMPTY` (empty config) if nothing is found.
    """
    start = Path(search_from).resolve() if search_from else Path.cwd()

    for directory in [start, *start.parents]:
        # bsl-analyzer.toml takes highest priority
        cfg_file = directory / "bsl-analyzer.toml"
        if cfg_file.exists():
            try:
                with cfg_file.open("rb") as f:
                    data = tomllib.load(f)
                # Support [bsl-analyzer] section or root-level keys
                section = data.get("bsl-analyzer", data)
                return BslConfig(section)
            except Exception:
                pass

        # pyproject.toml with [tool.bsl-analyzer]
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                with pyproject.open("rb") as f:
                    data = tomllib.load(f)
                section = data.get("tool", {}).get("bsl-analyzer")
                if section:
                    return BslConfig(section)
            except Exception:
                pass

    return _EMPTY
