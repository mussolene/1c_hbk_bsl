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
bsl_hover           — symbol signature + doc comment
bsl_references      — all definitions + call sites for a symbol
bsl_read_file       — read file or line range
bsl_search          — text / symbol search across workspace
bsl_format          — format a BSL file using built-in formatter
bsl_rename          — rename symbol across workspace (applies to files)
bsl_fix             — apply auto-fixes to a file (trailing ws, tabs, etc.)
bsl_workspace_scan  — list BSL files + quick metrics for a directory
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP

from bsl_analyzer.analysis.call_graph import build_call_graph
from bsl_analyzer.analysis.diagnostics import RULE_METADATA, DiagnosticEngine
from bsl_analyzer.analysis.fix_engine import apply_fixes as _apply_fixes
from bsl_analyzer.analysis.formatter import default_formatter
from bsl_analyzer.indexer.db_path import resolve_index_db_path
from bsl_analyzer.indexer.incremental import IncrementalIndexer
from bsl_analyzer.indexer.symbol_index import SymbolIndex
from bsl_analyzer.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_WORKSPACE = os.environ.get("WORKSPACE_ROOT", os.getcwd())

# Resolve DB path: INDEX_DB_PATH env → .git/bsl_index.sqlite → ~/.cache/bsl-analyzer/<hash>/
_DB_PATH = resolve_index_db_path(_WORKSPACE)

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
    # bsl_check_file
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Run BSL lint rules on a file with optional rule selection/ignore. "
            "Returns structured diagnostics list. Supports all BSL001–BSL021 rules."
        )
    )
    def bsl_check_file(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        select: Annotated[
            str | None,
            "Comma-separated rule codes to enable (e.g. 'BSL001,BSL012'). "
            "If omitted, all rules run.",
        ] = None,
        ignore: Annotated[
            str | None,
            "Comma-separated rule codes to skip (e.g. 'BSL014'). "
            "Ignored when *select* is provided.",
        ] = None,
    ) -> dict:
        """
        Lint *file_path* using the BSL DiagnosticEngine.

        Supports inline suppression comments in the source::

            А = А;  // noqa: BSL009
            Пароль = "123";  // bsl-disable: BSL012

        Args:
            file_path: Path to the .bsl source file.
            select:    Whitelist of rule codes (comma-separated).
            ignore:    Blacklist of rule codes (comma-separated).

        Returns:
            Dict with ``count``, ``has_errors``, and ``diagnostics`` list.
        """
        path = _resolve_path(file_path)
        select_set: set[str] | None = (
            {c.strip().upper() for c in select.split(",") if c.strip()} if select else None
        )
        ignore_set: set[str] | None = (
            {c.strip().upper() for c in ignore.split(",") if c.strip()} if ignore else None
        )
        engine = DiagnosticEngine(select=select_set, ignore=ignore_set)
        issues = engine.check_file(path)
        return {
            "file_path": path,
            "count": len(issues),
            "has_errors": any(d.severity.name == "ERROR" for d in issues),
            "diagnostics": [d.to_dict() for d in issues],
        }

    # ------------------------------------------------------------------
    # bsl_list_rules
    # ------------------------------------------------------------------

    @mcp.tool(
        description="Return metadata for all built-in BSL lint rules (BSL001–BSL021).",
    )
    def bsl_list_rules(
        tag_filter: Annotated[
            str | None, "Optional: only return rules that have this tag (e.g. 'security')"
        ] = None,
    ) -> dict:
        """
        List all available BSL diagnostic rules with descriptions and SonarQube mapping.

        Returns:
            Dict with ``count`` and ``rules`` list, each having:
            code, name, description, severity, sonar_type, sonar_severity, tags.
        """
        rules = []
        for code, meta in sorted(RULE_METADATA.items()):
            if tag_filter and tag_filter.lower() not in [t.lower() for t in meta.get("tags", [])]:
                continue
            rules.append(
                {
                    "code": code,
                    "name": meta["name"],
                    "description": meta["description"],
                    "severity": meta["severity"],
                    "sonar_type": meta["sonar_type"],
                    "sonar_severity": meta["sonar_severity"],
                    "tags": meta.get("tags", []),
                }
            )
        return {"count": len(rules), "rules": rules}

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

    # ------------------------------------------------------------------
    # bsl_hover
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Return signature and documentation for a BSL symbol. "
            "Searches workspace index first, then built-in platform API."
        )
    )
    def bsl_hover(
        symbol_name: Annotated[str, "Symbol name to look up"],
    ) -> dict:
        """
        Return hover-style documentation for *symbol_name*.

        Resolution order:
        1. Workspace symbol index (user-defined procedures/functions)
        2. Built-in platform API (global functions and types)
        """
        from bsl_analyzer.analysis.platform_api import get_platform_api

        index = _get_index()
        syms = index.find_symbol(symbol_name, limit=1)
        if syms:
            s = syms[0]
            return {
                "found": True,
                "source": "workspace",
                "name": s["name"],
                "kind": s["kind"],
                "signature": s.get("signature"),
                "doc_comment": s.get("doc_comment"),
                "file_path": s["file_path"],
                "line": s["line"],
                "is_export": bool(s["is_export"]),
            }

        api = get_platform_api()
        fn = api.find_global(symbol_name)
        if fn:
            return {
                "found": True,
                "source": "platform_api",
                "name": fn.name,
                "kind": "function",
                "signature": fn.signature,
                "description": fn.description,
                "returns": fn.returns,
            }

        tp = api.find_type(symbol_name)
        if tp:
            return {
                "found": True,
                "source": "platform_api",
                "name": tp.name,
                "kind": tp.kind,
                "description": tp.description,
                "methods": [m.name for m in tp.methods[:10]],
            }

        return {"found": False, "symbol_name": symbol_name}

    # ------------------------------------------------------------------
    # bsl_references
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Find all references to a BSL symbol: its definitions and all call sites. "
            "Combines bsl_definition + bsl_callers into one result."
        )
    )
    def bsl_references(
        symbol_name: Annotated[str, "Symbol name to find all references for"],
        include_definitions: Annotated[bool, "Include definition locations (default True)"] = True,
        limit: Annotated[int, "Max call sites to return (default 100)"] = 100,
    ) -> dict:
        """
        Return all locations where *symbol_name* appears in the codebase:
        its definition(s) and every call site.
        """
        index = _get_index()
        definitions = index.find_symbol(symbol_name, limit=10) if include_definitions else []
        callers = index.find_callers(symbol_name, limit=limit)
        return {
            "symbol_name": symbol_name,
            "definition_count": len(definitions),
            "reference_count": len(callers),
            "definitions": [
                {
                    "file_path": d["file_path"],
                    "line": d["line"],
                    "signature": d.get("signature"),
                }
                for d in definitions
            ],
            "references": [
                {
                    "file_path": c["caller_file"],
                    "line": c["caller_line"],
                    "caller_name": c.get("caller_name"),
                }
                for c in callers
            ],
        }

    # ------------------------------------------------------------------
    # bsl_read_file
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Read the contents of a BSL file, optionally restricting to a line range. "
            "Equivalent to get_range_content in mcp-bsl-lsp-bridge."
        )
    )
    def bsl_read_file(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        start_line: Annotated[int | None, "First line to return (1-based, inclusive)"] = None,
        end_line: Annotated[int | None, "Last line to return (1-based, inclusive)"] = None,
    ) -> dict:
        """
        Read *file_path* and return its content (or a line slice).

        Args:
            file_path:  Path to the .bsl file.
            start_line: First line (1-based). If omitted, starts at line 1.
            end_line:   Last line (1-based). If omitted, reads to EOF.

        Returns:
            Dict with ``content``, ``total_lines``, ``start_line``, ``end_line``.
        """
        path = _resolve_path(file_path)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            return {"error": str(exc), "file_path": path}

        all_lines = text.splitlines()
        total = len(all_lines)
        s = (start_line or 1) - 1
        e = (end_line or total)
        selected = all_lines[max(0, s) : e]
        return {
            "file_path": path,
            "total_lines": total,
            "start_line": s + 1,
            "end_line": min(e, total),
            "content": "\n".join(selected),
        }

    # ------------------------------------------------------------------
    # bsl_search
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Search for a text pattern or symbol name across all BSL files in the workspace. "
            "Combines symbol index search with optional filesystem text scan."
        )
    )
    def bsl_search(
        query: Annotated[str, "Text or regex pattern to search for"],
        search_type: Annotated[
            str,
            "One of: 'symbol' (index lookup), 'text' (grep in files), 'both' (default)",
        ] = "both",
        file_filter: Annotated[str | None, "Restrict to files whose path contains this string"] = None,
        case_sensitive: Annotated[bool, "Case-sensitive text search (default False)"] = False,
        limit: Annotated[int, "Max results per search type (default 20)"] = 20,
    ) -> dict:
        """
        Search the workspace for *query*.

        search_type='symbol'  — FTS prefix search in symbol index.
        search_type='text'    — regex grep over file contents.
        search_type='both'    — runs both and merges results.
        """
        results: dict = {"query": query, "search_type": search_type}

        if search_type in ("symbol", "both"):
            rows = _get_index().find_symbol(query, file_filter=file_filter, limit=limit, fuzzy=True)
            results["symbols"] = [
                {
                    "name": r["name"],
                    "kind": r["kind"],
                    "file_path": r["file_path"],
                    "line": r["line"],
                    "signature": r.get("signature"),
                }
                for r in rows
            ]

        if search_type in ("text", "both"):
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(query, flags)
            except re.error as exc:
                results["text_error"] = f"Invalid regex: {exc}"
                return results

            workspace = Path(_WORKSPACE)
            bsl_files = list(workspace.rglob("*.bsl")) if workspace.is_dir() else []
            if file_filter:
                bsl_files = [f for f in bsl_files if file_filter in str(f)]

            matches: list[dict] = []
            for bsl_file in bsl_files:
                if len(matches) >= limit:
                    break
                try:
                    content = bsl_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for line_idx, line_text in enumerate(content.splitlines(), start=1):
                    if pattern.search(line_text):
                        matches.append(
                            {
                                "file_path": str(bsl_file),
                                "line": line_idx,
                                "text": line_text.strip(),
                            }
                        )
                        if len(matches) >= limit:
                            break
            results["text_matches"] = matches
            results["text_match_count"] = len(matches)

        return results

    # ------------------------------------------------------------------
    # bsl_format
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Format a BSL file using the built-in formatter. "
            "Normalises keyword casing, indentation, and operator spacing. "
            "Returns the formatted text and optionally writes the file."
        )
    )
    def bsl_format(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        write: Annotated[bool, "If True, write the formatted content back to the file"] = False,
        indent_size: Annotated[int, "Spaces per indent level (default 4)"] = 4,
    ) -> dict:
        """
        Format *file_path* with the BSL formatter.

        Args:
            file_path:   Path to the .bsl file.
            write:       If True, overwrite the file with formatted content.
            indent_size: Indentation width (default 4).

        Returns:
            Dict with ``formatted`` text, ``changed`` flag, and (if write=True) ``written``.
        """
        path = _resolve_path(file_path)
        try:
            original = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            return {"error": str(exc), "file_path": path}

        formatted = default_formatter.format(original, indent_size=indent_size)
        changed = formatted != original

        result: dict = {
            "file_path": path,
            "changed": changed,
            "formatted": formatted,
        }

        if write and changed:
            try:
                Path(path).write_text(formatted, encoding="utf-8")
                result["written"] = True
            except OSError as exc:
                result["write_error"] = str(exc)
                result["written"] = False
        else:
            result["written"] = False

        return result

    # ------------------------------------------------------------------
    # bsl_rename
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Rename a BSL symbol across the entire workspace. "
            "Finds all definitions and call sites, then optionally applies edits to files."
        )
    )
    def bsl_rename(
        old_name: Annotated[str, "Current symbol name"],
        new_name: Annotated[str, "New symbol name"],
        apply: Annotated[bool, "If True, actually write changes to files (default False — dry run)"] = False,
    ) -> dict:
        """
        Rename *old_name* to *new_name* across the workspace.

        When ``apply=False`` (default) returns a dry-run preview — files and line counts
        that would be changed — without touching disk.
        When ``apply=True`` performs the rename in-place on all files.

        Args:
            old_name: Symbol to rename.
            new_name: Replacement name (must be a valid BSL identifier).
            apply:    Write changes to disk (default False).
        """
        if not re.match(r"^[А-ЯЁа-яёA-Za-z_]\w*$", new_name, re.UNICODE):
            return {"error": f"'{new_name}' is not a valid BSL identifier"}

        index = _get_index()
        definitions = index.find_symbol(old_name, limit=50)
        callers = index.find_callers(old_name, limit=1000)

        # Group edits by file: {path: [(line_0based, old_name)]}
        file_edits: dict[str, list[int]] = {}
        for d in definitions:
            file_edits.setdefault(d["file_path"], []).append(d["line"] - 1)
        for c in callers:
            file_edits.setdefault(c["caller_file"], []).append(c["caller_line"] - 1)

        preview = [
            {"file_path": fp, "lines_affected": len(lines)}
            for fp, lines in sorted(file_edits.items())
        ]
        total_changes = sum(len(v) for v in file_edits.values())

        if not apply:
            return {
                "dry_run": True,
                "old_name": old_name,
                "new_name": new_name,
                "files_affected": len(file_edits),
                "total_occurrences": total_changes,
                "preview": preview,
            }

        # Apply edits
        applied_files = 0
        errors: list[str] = []
        pattern = re.compile(
            r"(?<![А-ЯЁа-яёA-Za-z_\d])" + re.escape(old_name) + r"(?![А-ЯЁа-яёA-Za-z_\d])",
            re.UNICODE | re.IGNORECASE,
        )
        for fp in file_edits:
            try:
                content = Path(fp).read_text(encoding="utf-8")
                new_content = pattern.sub(new_name, content)
                if new_content != content:
                    Path(fp).write_text(new_content, encoding="utf-8")
                    applied_files += 1
            except OSError as exc:
                errors.append(f"{fp}: {exc}")

        return {
            "dry_run": False,
            "old_name": old_name,
            "new_name": new_name,
            "files_affected": applied_files,
            "total_occurrences": total_changes,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # bsl_fix
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Apply automatic fixes to a BSL file (trailing whitespace, tab indentation, "
            "missing newline at EOF). Optionally writes the fixed content to disk."
        )
    )
    def bsl_fix(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        write: Annotated[bool, "Write fixed content back to file (default False — dry run)"] = False,
        rules: Annotated[
            str | None,
            "Comma-separated rule codes to fix (e.g. 'BSL009,BSL010'). Default: all fixable.",
        ] = None,
    ) -> dict:
        """
        Run the FixEngine on *file_path* and return fixed content.

        Fixable rules: BSL009 (trailing whitespace), BSL010 (missing EOF newline),
        BSL055 (commented-out code removal), BSL060 (tab → spaces).
        """
        path = _resolve_path(file_path)
        if not Path(path).exists():
            return {"error": f"File not found: {path}", "file_path": path}

        fixable_codes = {"BSL009", "BSL010", "BSL055", "BSL060"}
        select_set: set[str] | None = (
            {c.strip().upper() for c in rules.split(",") if c.strip()} if rules else None
        )
        run_codes = (select_set & fixable_codes) if select_set else fixable_codes

        engine = DiagnosticEngine(select=run_codes)
        issues = engine.check_file(path)
        fixable = [d for d in issues if d.code in fixable_codes]

        if not fixable:
            return {
                "file_path": path,
                "changed": False,
                "fixes_applied": 0,
                "fixed_rules": [],
                "written": False,
            }

        if write:
            fix_result = _apply_fixes(path, fixable)
            applied = fix_result.applied or []
            return {
                "file_path": path,
                "changed": bool(applied),
                "fixes_applied": len(applied),
                "fixed_rules": sorted(set(applied)),
                "written": bool(applied),
                "error": fix_result.error,
            }
        else:
            return {
                "file_path": path,
                "changed": True,
                "fixes_applied": len(fixable),
                "fixed_rules": sorted({d.code for d in fixable}),
                "written": False,
                "note": "Dry run — set write=True to apply fixes",
            }

    # ------------------------------------------------------------------
    # bsl_workspace_scan
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Scan a directory for BSL files and return a summary: "
            "file list, line counts, and quick module metrics."
        )
    )
    def bsl_workspace_scan(
        directory: Annotated[str | None, "Directory to scan (default: WORKSPACE_ROOT)"] = None,
        max_files: Annotated[int, "Maximum files to include in result (default 200)"] = 200,
        include_metrics: Annotated[bool, "Include line/symbol counts per file (default True)"] = True,
    ) -> dict:
        """
        Walk *directory* and list all .bsl files with optional per-file metrics.

        Returns:
            Dict with ``file_count``, ``total_lines``, and ``files`` list.
            Each file entry has: path, size_bytes, line_count, symbol_count (if indexed).
        """
        root = Path(_resolve_path(directory or _WORKSPACE))
        if not root.is_dir():
            return {"error": f"Not a directory: {root}"}

        bsl_files = sorted(root.rglob("*.bsl"))
        total_lines = 0
        files_info: list[dict] = []

        index = _get_index()

        for bsl_file in bsl_files[:max_files]:
            entry: dict = {
                "path": str(bsl_file),
                "size_bytes": bsl_file.stat().st_size,
            }
            if include_metrics:
                try:
                    content = bsl_file.read_text(encoding="utf-8", errors="ignore")
                    lc = len(content.splitlines())
                    entry["line_count"] = lc
                    total_lines += lc
                except OSError:
                    entry["line_count"] = 0

                syms = index.get_file_symbols(str(bsl_file))
                entry["symbol_count"] = len(syms)
                entry["procedure_count"] = sum(1 for s in syms if s["kind"] in ("procedure", "function"))

            files_info.append(entry)

        return {
            "directory": str(root),
            "file_count": len(bsl_files),
            "shown_count": len(files_info),
            "total_lines": total_lines,
            "files": files_info,
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
