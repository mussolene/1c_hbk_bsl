"""
1C HBK BSL — static analysis toolkit for 1C Enterprise BSL language.

Provides:
  - MCP server (bsl_find_symbol, bsl_callers, bsl_callees, bsl_diagnostics, …)
  - LSP server for VSCode/Cursor (go-to-definition, hover, completions, diagnostics)
  - CLI linter (ruff-style output, --check mode)
  - Incremental symbol indexing backed by SQLite

Runtime uses a generated version module instead of importing setuptools-scm on
startup.
"""

from __future__ import annotations

from onec_hbk_bsl._version import __version__ as __version__

__description__ = "1C Enterprise BSL: MCP server, LSP server, and CLI linter"
__author__ = "1C HBK BSL Contributors"
