"""
1C HBK BSL — static analysis toolkit for 1C Enterprise BSL language.

Provides:
  - MCP server (bsl_find_symbol, bsl_callers, bsl_callees, bsl_diagnostics, …)
  - LSP server for VSCode/Cursor (go-to-definition, hover, completions, diagnostics)
  - CLI linter (ruff-style output, --check mode)
  - Incremental symbol indexing backed by SQLite

Version: from **git tags** (``vMAJOR.MINOR.PATCH``) via setuptools-scm at build/install time.
:data:`__version__` prefers :func:`setuptools_scm.get_version` when the module is loaded from
a ``src/onec_hbk_bsl`` tree with a ``.git`` directory (avoids stale ``importlib.metadata`` from
an unrelated install); otherwise uses installed package metadata, then setuptools-scm fallback.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__description__ = "1C Enterprise BSL: MCP server, LSP server, and CLI linter"
__author__ = "1C HBK BSL Contributors"


def _version() -> str:
    here = Path(__file__).resolve()
    pkg_dir = here.parent
    if pkg_dir.name == "onec_hbk_bsl":
        src_dir = pkg_dir.parent
        if src_dir.name == "src":
            repo_root = src_dir.parent
            if (repo_root / ".git").exists():
                try:
                    from setuptools_scm import get_version

                    return get_version(root=str(repo_root))
                except (ImportError, LookupError):
                    pass
    try:
        return version("onec-hbk-bsl")
    except PackageNotFoundError:
        pass
    try:
        from setuptools_scm import get_version

        root = Path(__file__).resolve().parents[2]
        return get_version(root=str(root))
    except (ImportError, LookupError):
        pass
    return "0.0.0+unknown"


__version__ = _version()
