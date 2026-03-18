"""
FastMCP server exposing BSL analysis tools to Claude.

Tools
-----
bsl_status          — index health check
bsl_find_symbol     — search symbols by name
bsl_file_symbols    — list all symbols in a file
bsl_callers         — who calls a given function
bsl_callees         — what a function calls
bsl_diagnostics     — lint issues in a file
bsl_definition      — find definition location(s)
bsl_index_file      — force-reindex a single file
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

import fastmcp
from fastmcp import FastMCP

from bsl_analyzer.analysis.call_graph import build_call_graph
from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
from bsl_analyzer.indexer.incremental import IncrementalIndexer
from bsl_analyzer.indexer.symbol_index import SymbolIndex
from bsl_analyzer.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_DB_PATH = os.environ.get("INDEX_DB_PATH", "bsl_index.sqlite")
_WORKSPACE = os.environ.get("WORKSPACE_ROOT", os.getcwd())

_index: SymbolIndex | None = None
_indexer: IncrementalIndexer | None = None
_parser: BslParser | None = None
_engine: DiagnosticEngine | None = None


def _get_index() -> SymbolIndex:
    global _index
    if _index is None:
        _index = SymbolIndex(db_path=_DB_PATH)
    return _index


def _get_indexer() -> IncrementalIndexer:
    global _indexer
    if _indexer is None:
        _indexer = IncrementalIndexer(index=_get_index())
    return _indexer


def _get_parser() -> BslParser:
    global _parser
    if _parser is None:
        _parser = BslParser()
    return _parser


def _get_engine() -> DiagnosticEngine:
    global _engine
    if _engine is None:
        _engine = DiagnosticEngine(parser=_get_parser())
    return _engine


# ---------------------------------------------------------------------------
# MCP app factory
# ---------------------------------------------------------------------------


def create_mcp_app() -> FastMCP:
    """Create and return the FastMCP application with all BSL tools registered."""
    mcp = FastMCP(
        name="bsl-analyzer",
        instructions=(
            "BSL (1C Enterprise) static analysis server. "
            "Use bsl_status first to verify the index is ready. "
            "Then use bsl_find_symbol, bsl_callers, bsl_callees, etc. "
            "to explore the codebase."
        ),
    )

    # ------------------------------------------------------------------
    # bsl_status
    # ------------------------------------------------------------------

    @mcp.tool(description="Return current indexing status: files indexed, last commit, ready state.")
    def bsl_status() -> dict:
        """
        Check the health of the BSL symbol index.

        Returns stats: symbol count, file count, last indexed git commit, workspace root.
        Call this first to confirm the index is populated before searching.
        """
        stats = _get_index().get_stats()
        return {
            "ready": stats["symbol_count"] > 0,
            "symbol_count": stats["symbol_count"],
            "file_count": stats["file_count"],
            "call_count": stats["call_count"],
            "last_commit": stats["last_commit"],
            "indexed_at": stats["indexed_at"],
            "workspace_root": stats["workspace_root"] or _WORKSPACE,
            "db_path": _DB_PATH,
        }

    # ------------------------------------------------------------------
    # bsl_find_symbol
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Find BSL symbols (procedures/functions/variables) by name. "
            "Returns file path, line, signature, and export status."
        )
    )
    def bsl_find_symbol(
        name: Annotated[str, "Symbol name to search for (case-insensitive, prefix match supported)"],
        file_filter: Annotated[
            str | None, "Optional: restrict results to files matching this substring"
        ] = None,
        limit: Annotated[int, "Maximum results to return (default 20)"] = 20,
        fuzzy: Annotated[bool, "Use FTS prefix match instead of exact name match"] = False,
    ) -> dict:
        """
        Search the symbol index for procedures, functions, or variables matching *name*.

        Args:
            name:        Symbol name (exact or prefix with fuzzy=True).
            file_filter: Restrict to files whose path contains this string.
            limit:       Maximum number of results (default 20).
            fuzzy:       Enable FTS prefix search for partial name matching.

        Returns:
            Dict with ``count`` and ``symbols`` list, each having:
            name, kind, file_path, line, signature, is_export, doc_comment.
        """
        rows = _get_index().find_symbol(name, file_filter=file_filter, limit=limit, fuzzy=fuzzy)
        return {
            "count": len(rows),
            "symbols": [
                {
                    "name": r["name"],
                    "kind": r["kind"],
                    "file_path": r["file_path"],
                    "line": r["line"],
                    "signature": r.get("signature"),
                    "is_export": bool(r["is_export"]),
                    "doc_comment": r.get("doc_comment"),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------
    # bsl_file_symbols
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "List all symbols (procedures, functions, variables) defined in a single BSL file."
        )
    )
    def bsl_file_symbols(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
    ) -> dict:
        """
        Return every symbol defined in *file_path*, ordered by line.

        Useful for building a quick outline of a module.
        """
        path = _resolve_path(file_path)
        rows = _get_index().get_file_symbols(path)
        return {
            "file_path": path,
            "count": len(rows),
            "symbols": [
                {
                    "name": r["name"],
                    "kind": r["kind"],
                    "line": r["line"],
                    "end_line": r["end_line"],
                    "signature": r.get("signature"),
                    "is_export": bool(r["is_export"]),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------
    # bsl_callers
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Find all call sites that call a given BSL procedure/function. "
            "Returns caller file, line, and enclosing procedure name."
        )
    )
    def bsl_callers(
        symbol_name: Annotated[str, "Name of the procedure or function to find callers of"],
        depth: Annotated[int, "How many levels of callers to traverse (default 3)"] = 3,
    ) -> dict:
        """
        Return a tree of callers for *symbol_name* up to *depth* levels deep.

        Args:
            symbol_name: The procedure/function whose callers you want.
            depth:       Recursion depth for the callers tree (default 3).
        """
        graph = build_call_graph(_get_index(), symbol_name, depth=depth)
        return {
            "symbol_name": symbol_name,
            "definition": graph["definition"],
            "callers": graph["callers"],
        }

    # ------------------------------------------------------------------
    # bsl_callees
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Find all procedures/functions called from within a given BSL symbol. "
            "Returns callee name, call line, and resolved definition location."
        )
    )
    def bsl_callees(
        symbol_name: Annotated[str, "Name of the procedure or function to inspect"],
        depth: Annotated[int, "How many call levels to traverse (default 3)"] = 3,
    ) -> dict:
        """
        Return the list of symbols called by *symbol_name*.

        Args:
            symbol_name: The procedure/function to inspect.
            depth:       How deep to follow the call chain (default 3).
        """
        graph = build_call_graph(_get_index(), symbol_name, depth=depth)
        return {
            "symbol_name": symbol_name,
            "definition": graph["definition"],
            "callees": graph["callees"],
        }

    # ------------------------------------------------------------------
    # bsl_diagnostics
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Run BSL lint rules on a file and return diagnostics. "
            "Checks: BSL001 syntax errors, BSL002 long procedures, BSL004 empty except handlers."
        )
    )
    def bsl_diagnostics(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
    ) -> dict:
        """
        Run the DiagnosticEngine on *file_path* and return all issues.

        Returns:
            Dict with ``count``, ``has_errors``, and ``diagnostics`` list.
            Each diagnostic has: file, line, character, severity, code, message.
        """
        path = _resolve_path(file_path)
        issues = _get_engine().check_file(path)
        return {
            "file_path": path,
            "count": len(issues),
            "has_errors": any(d.severity.name == "ERROR" for d in issues),
            "diagnostics": [d.to_dict() for d in issues],
        }

    # ------------------------------------------------------------------
    # bsl_definition
    # ------------------------------------------------------------------

    @mcp.tool(
        description="Find the definition location(s) of a BSL symbol by name.",
    )
    def bsl_definition(
        symbol_name: Annotated[str, "Exact symbol name to look up"],
        file_filter: Annotated[
            str | None, "Optional: restrict to files whose path contains this string"
        ] = None,
    ) -> dict:
        """
        Look up where *symbol_name* is defined in the index.

        Returns a list of definition locations (file, line, signature).
        Multiple results possible if the name is defined in multiple files.
        """
        rows = _get_index().find_symbol(symbol_name, file_filter=file_filter, limit=10)
        return {
            "symbol_name": symbol_name,
            "count": len(rows),
            "definitions": [
                {
                    "file_path": r["file_path"],
                    "line": r["line"],
                    "character": r["character"],
                    "signature": r.get("signature"),
                    "is_export": bool(r["is_export"]),
                    "doc_comment": r.get("doc_comment"),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------
    # bsl_index_file  (mutating tool)
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Force re-index a single BSL file. "
            "Use this after editing a file to update the symbol index immediately."
        ),
    )
    def bsl_index_file(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
    ) -> dict:
        """
        Parse *file_path* and update the symbol index.

        Returns the number of symbols and call edges indexed.
        This is a mutating operation — it modifies the SQLite database.
        """
        path = _resolve_path(file_path)
        result = _get_indexer().index_file(path)
        return {
            "file_path": path,
            "symbols_indexed": result.get("symbols", 0),
            "calls_indexed": result.get("calls", 0),
            "error": result.get("error"),
        }

    return mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_path(file_path: str) -> str:
    """
    Resolve *file_path* to an absolute path.

    If *file_path* is relative, it is joined against WORKSPACE_ROOT.
    """
    p = Path(file_path)
    if p.is_absolute():
        return str(p)
    return str(Path(_WORKSPACE) / file_path)
