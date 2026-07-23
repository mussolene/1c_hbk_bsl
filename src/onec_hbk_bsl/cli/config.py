"""
Configuration loader for onec-hbk-bsl.

Searches (in order of increasing priority):
1. ``pyproject.toml`` — ``[tool."onec-hbk-bsl"]`` section
2. ``onec-hbk-bsl.toml`` — ``[onec-hbk-bsl]`` section or root-level keys

Walk starts from *search_from* (defaults to cwd) and ascends to the filesystem
root, stopping at the first file that contains a onec-hbk-bsl configuration.

Supported keys
--------------
select              list[str]   — run only these rule codes
ignore              list[str]   — always-skip rule codes
exclude             list[str]   — glob patterns for excluded paths
index-exclude       list[str]   — index-only globs; defaults to exclude
per-file-ignores    dict        — {"pattern": ["BSL001"]}
format              str         — text | json | sarif
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
max-module-lines          int
indent-size               int    — formatter indent width when spaces are used
insert-spaces             bool   — formatter uses spaces instead of tabs
index-mode               str    — off | symbols | full (default: full)
index-max-bytes          int    — hard size budget, 0 = unlimited
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from onec_hbk_bsl.analysis.diagnostics import (
    normalize_rule_code_set,
    normalize_rule_code_set_strict,
)

_CONFIG_SECTION = "onec-hbk-bsl"


class BslConfig:
    """Merged configuration built from a TOML section."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def has(self, key: str) -> bool:
        """Return whether this source explicitly defines *key*."""
        return key in self._data

    # ------------------------------------------------------------------
    # Rule selection
    # ------------------------------------------------------------------

    @property
    def select(self) -> set[str] | None:
        v = self._data.get("select")
        if not v:
            return None
        return normalize_rule_code_set_strict((str(x) for x in v), source="config select")

    @property
    def ignore(self) -> set[str] | None:
        v = self._data.get("ignore")
        if not v:
            return None
        return normalize_rule_code_set_strict((str(x) for x in v), source="config ignore")

    # ------------------------------------------------------------------
    # File filtering
    # ------------------------------------------------------------------

    @property
    def exclude(self) -> list[str]:
        return list(self._data.get("exclude", []))

    @property
    def index_exclude(self) -> list[str]:
        return list(self._data.get("index-exclude", self.exclude))

    @property
    def per_file_ignores(self) -> dict[str, list[str]]:
        return {
            str(pattern): list(codes)
            for pattern, codes in self._data.get("per-file-ignores", {}).items()
        }

    def is_excluded(self, file_path: str) -> bool:
        """Return True if *file_path* matches any exclude pattern."""
        return self._matches_patterns(file_path, self.exclude)

    def is_index_excluded(self, file_path: str) -> bool:
        """Return True if *file_path* is excluded from the workspace symbol index."""
        return self._matches_patterns(file_path, self.index_exclude)

    @staticmethod
    def _matches_patterns(file_path: str, patterns: list[str]) -> bool:
        p = Path(file_path)
        for pattern in patterns:
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
                normalized = normalize_rule_code_set_strict(
                    codes,
                    source=f"per-file-ignores for {pattern}",
                )
                if normalized:
                    result.update(normalized)
        return result

    # ------------------------------------------------------------------
    # Output / behaviour
    # ------------------------------------------------------------------

    @property
    def format(self) -> str | None:
        value = self._data.get("format")
        if value is None:
            return None
        value = str(value)
        if value not in {"text", "json", "sarif"}:
            raise ValueError(f"Unsupported format in config: {value!r}. Use text, json, or sarif.")
        return value

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

    @property
    def indent_size(self) -> int | None:
        v = self._data.get("indent-size")
        return int(v) if v is not None else None

    @property
    def insert_spaces(self) -> bool | None:
        v = self._data.get("insert-spaces")
        return bool(v) if v is not None else None

    @property
    def index_mode(self) -> str:
        value = str(self._data.get("index-mode", "full")).strip().lower()
        if value not in {"off", "symbols", "full"}:
            raise ValueError(f"Unsupported index-mode: {value!r}. Use off, symbols, or full.")
        return value

    @property
    def index_max_bytes(self) -> int:
        value = int(self._data.get("index-max-bytes", 0))
        if value < 0:
            raise ValueError("index-max-bytes must be >= 0")
        return value

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

    @property
    def max_module_lines(self) -> int | None:
        return self._data.get("max-module-lines")

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
            "max_module_lines": self.max_module_lines,
        }
        return {k: v for k, v in mapping.items() if v is not None}


class ResolvedConfig(BslConfig):
    """Immutable configuration snapshot shared by every public adapter."""

    __slots__ = ()

    def __init__(self, data: dict[str, Any]) -> None:
        frozen = {key: _freeze_config_value(value) for key, value in data.items()}
        object.__setattr__(self, "_data", MappingProxyType(frozen))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ResolvedConfig is immutable")


def _freeze_config_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_config_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze_config_value(item) for item in value)
    return value


_UNSET: Final = object()
_THRESHOLD_KEYS: Final = (
    "max-line-length",
    "max-proc-lines",
    "max-cognitive-complexity",
    "max-mccabe-complexity",
    "max-nesting-depth",
    "max-params",
    "max-returns",
    "max-bool-ops",
    "min-duplicate-uses",
    "max-module-lines",
)


def environment_config(environ: Mapping[str, str] | None = None) -> BslConfig:
    """Translate the established public environment variables into one config layer."""
    values = os.environ if environ is None else environ
    data: dict[str, Any] = {}

    for env_key, config_key in (("BSL_SELECT", "select"), ("BSL_IGNORE", "ignore")):
        raw = values.get(env_key, "").strip()
        if raw:
            normalized = normalize_rule_code_set(raw.split(","))
            data[config_key] = sorted(normalized)

    mode = values.get("BSL_INDEX_MODE", "").strip().lower()
    if mode in {"off", "symbols", "full"}:
        data["index-mode"] = mode

    raw_max_bytes = values.get("BSL_INDEX_MAX_BYTES", "").strip()
    if raw_max_bytes:
        try:
            max_bytes = int(raw_max_bytes)
        except ValueError:
            pass
        else:
            if max_bytes >= 0:
                data["index-max-bytes"] = max_bytes

    return BslConfig(data)


def resolve_config(
    project: BslConfig | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    select: set[str] | frozenset[str] | None | object = _UNSET,
    ignore: set[str] | frozenset[str] | None | object = _UNSET,
    exclude: list[str] | tuple[str, ...] | object = _UNSET,
    index_exclude: list[str] | tuple[str, ...] | object = _UNSET,
    per_file_ignores: Mapping[str, list[str] | tuple[str, ...]] | object = _UNSET,
    format: str | None | object = _UNSET,  # noqa: A002
    jobs: int | None | object = _UNSET,
    exit_zero: bool | None | object = _UNSET,
    baseline: str | None | object = _UNSET,
    indent_size: int | None | object = _UNSET,
    insert_spaces: bool | None | object = _UNSET,
    index_mode: str | None | object = _UNSET,
    index_max_bytes: int | None | object = _UNSET,
) -> ResolvedConfig:
    """Resolve ``explicit > environment > project > defaults`` once.

    ``None`` is an explicit value when passed by an adapter only where the
    corresponding public option uses it meaningfully. Omitting an argument
    entirely is represented by the private sentinel.
    """
    project_layer = project or _EMPTY
    environment_layer = environment_config(environ)
    explicit_values = {
        "select": select,
        "ignore": ignore,
        "exclude": exclude,
        "index-exclude": index_exclude,
        "per-file-ignores": per_file_ignores,
        "format": format,
        "jobs": jobs,
        "exit-zero": exit_zero,
        "baseline": baseline,
        "indent-size": indent_size,
        "insert-spaces": insert_spaces,
        "index-mode": index_mode,
        "index-max-bytes": index_max_bytes,
    }
    defaults: dict[str, Any] = {
        "select": None,
        "ignore": None,
        "exclude": (),
        "per-file-ignores": {},
        "format": "text",
        "jobs": 0,
        "exit-zero": False,
        "baseline": None,
        "indent-size": 4,
        "insert-spaces": False,
        "index-mode": "full",
        "index-max-bytes": 0,
        **dict.fromkeys(_THRESHOLD_KEYS),
    }

    resolved: dict[str, Any] = {}
    for key, default in defaults.items():
        explicit = explicit_values.get(key, _UNSET)
        if explicit is not _UNSET:
            resolved[key] = explicit
        elif environment_layer.has(key):
            resolved[key] = environment_layer._data[key]
        elif project_layer.has(key):
            resolved[key] = project_layer._data[key]
        else:
            resolved[key] = default

    if index_exclude is not _UNSET:
        resolved["index-exclude"] = index_exclude
    elif environment_layer.has("index-exclude"):
        resolved["index-exclude"] = environment_layer._data["index-exclude"]
    elif project_layer.has("index-exclude"):
        resolved["index-exclude"] = project_layer._data["index-exclude"]
    else:
        resolved["index-exclude"] = resolved["exclude"]

    snapshot = ResolvedConfig(resolved)
    # Eager validation keeps adapter failures deterministic and source-independent.
    _ = (
        snapshot.select,
        snapshot.ignore,
        snapshot.format,
        snapshot.jobs,
        snapshot.index_mode,
        snapshot.index_max_bytes,
    )
    for pattern, codes in snapshot.per_file_ignores.items():
        normalize_rule_code_set_strict(
            codes,
            source=f"per-file-ignores for {pattern}",
        )
    return snapshot


# Singleton representing "no config found"
_EMPTY = BslConfig({})


def load_config(search_from: str | None = None) -> BslConfig:
    """
    Walk up from *search_from* and return the first onec-hbk-bsl config found.

    Priority (first wins):
    - ``onec-hbk-bsl.toml`` in any ancestor directory
    - ``pyproject.toml`` with a ``[tool."onec-hbk-bsl"]`` section

    Returns :data:`_EMPTY` (empty config) if nothing is found.
    """
    start = Path(search_from).resolve() if search_from else Path.cwd()

    for directory in [start, *start.parents]:
        # onec-hbk-bsl.toml takes highest priority
        cfg_file = directory / "onec-hbk-bsl.toml"
        if cfg_file.exists():
            try:
                with cfg_file.open("rb") as f:
                    data = tomllib.load(f)
                # Support [onec-hbk-bsl] section or root-level keys
                section = data.get(_CONFIG_SECTION, data)
                return BslConfig(section)
            except Exception:
                pass

        # pyproject.toml with [tool."onec-hbk-bsl"]
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                with pyproject.open("rb") as f:
                    data = tomllib.load(f)
                section = data.get("tool", {}).get(_CONFIG_SECTION)
                if section:
                    return BslConfig(section)
            except Exception:
                pass

    return _EMPTY
