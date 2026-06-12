"""
1C HBK BSL — static analysis toolkit for 1C Enterprise BSL language.

Provides:
  - MCP server (bsl_find_symbol, bsl_callers, bsl_callees, bsl_diagnostics, …)
  - LSP server for VSCode/Cursor (go-to-definition, hover, completions, diagnostics)
  - CLI linter (``check`` command)
  - Incremental symbol indexing backed by SQLite

Runtime uses a generated version module instead of importing setuptools-scm on
startup. In a source checkout, ``__version__`` is resolved lazily from git tags
on first access; bundled runtimes fall back to the generated static version.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

from onec_hbk_bsl._version import __version__ as _STATIC_VERSION

__description__ = "1C Enterprise BSL: MCP server, LSP server, and CLI linter"
__author__ = "1C HBK BSL Contributors"
__all__ = ["__version__", "check_files"]


@functools.lru_cache(maxsize=1)
def _resolve_version() -> str:
    if getattr(sys, "frozen", False):
        return _STATIC_VERSION
    try:
        from setuptools_scm import get_version

        repo_root = Path(__file__).resolve().parents[2]
        return get_version(root=str(repo_root))
    except Exception:
        return _STATIC_VERSION


def __getattr__(name: str) -> str:
    if name == "__version__":
        return _resolve_version()
    raise AttributeError(name)


def check_files(*args, **kwargs):
    """Run diagnostics for an explicit BSL/OS file list."""
    from onec_hbk_bsl.cli.check import check_files as _check_files

    return _check_files(*args, **kwargs)
