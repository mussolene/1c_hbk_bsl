"""
FastMCP server exposing BSL analysis tools to Claude.

Tools
-----
bsl_status          — index health check
bsl_find_symbol     — search symbols by name
bsl_file_symbols    — list all symbols in a file
bsl_callers         — who calls a given function
bsl_callees         — what a function calls
bsl_diagnostics     — full DiagnosticEngine + optional BSL-DEAD (include_unused)
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
bsl_meta_object     — 1C config metadata: attributes/TS/forms for an object
bsl_meta_collection — list objects in a 1C global collection (Справочники, etc.)
bsl_meta_index      — trigger metadata re-indexing from XML config export (+ kind registry snapshot)

Contract
--------
Responses are **assistant-oriented context** (summaries, snippets, navigation, optional
1c-help proxy text). They are **not** a substitute for the tree-sitter CST used inside
the analyzer for diagnostics and formatting; do not treat MCP payloads as an alternate
“code model” for rule correctness.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP

from onec_hbk_bsl.analysis.call_graph import build_call_graph
from onec_hbk_bsl.analysis.diagnostics import (
    RULE_METADATA,
    DiagnosticEngine,
    display_name_for_rule_code,
    normalize_rule_code_set,
    parse_env_rule_filters,
)
from onec_hbk_bsl.analysis.fix_engine import apply_fixes as _apply_fixes
from onec_hbk_bsl.analysis.formatter import default_formatter
from onec_hbk_bsl.analysis.lsp_positions import utf16_len
from onec_hbk_bsl.indexer.db_path import resolve_index_db_path
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
from onec_hbk_bsl.indexer.metadata_registry import defs_snapshot
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
from onec_hbk_bsl.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

# MCP JSON contract version — response shape for clients.
# Tool payloads are for assistant context; lint/format correctness uses CST in analysis/.
MCP_CONTRACT_VERSION = "0.2.0"

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE_ROOT", os.getcwd()))

# Resolve DB path: INDEX_DB_PATH env → .git/onec-hbk-bsl_index.sqlite → ~/.cache/onec-hbk-bsl/<hash>/
_DB_PATH = resolve_index_db_path(_WORKSPACE)

# LRU caches for multi-project runs in a single MCP process.
_CACHE_LIMIT = int(os.environ.get("MCP_INDEX_CACHE_LIMIT", "4"))
_cache_lock = threading.RLock()
_index_cache: OrderedDict[str, SymbolIndex] = OrderedDict()
_indexer_cache: OrderedDict[str, IncrementalIndexer] = OrderedDict()

# Backward-compatible module-level singletons (used by unit tests).
_index: SymbolIndex | None = None
_indexer: IncrementalIndexer | None = None

_parser: BslParser | None = None

# ---------------------------------------------------------------------------
# Optional 1c-help MCP proxy (for AI context / snippets)
# ---------------------------------------------------------------------------

# 1c-help provides an MCP server (see external-help-service project).
# We proxy its "search_1c_help_keyword" and "get_1c_help_topic" tools.
_ONEC_HELP_MCP_BASE = os.environ.get("ONEC_HELP_MCP_BASE", "http://localhost:8050/mcp")
_ONEC_HELP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_help_keyword_cache: dict[tuple[str, int], list[dict]] = {}
_help_topic_cache: dict[str, str] = {}


def _post_1c_help_tool(tool_name: str, arguments: dict[str, object], timeout: float = 5.0) -> list[dict]:
    """Call 1c-help MCP tool and return the parsed `content` list (best-effort)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    req = urllib.request.Request(  # noqa: S310
        _ONEC_HELP_MCP_BASE,
        data=json.dumps(payload).encode(),
        headers=dict(_ONEC_HELP_HEADERS),
        method="POST",
    )
    # 1c-help MCP uses SSE-like responses (lines starting with "data: ").
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        parsed = json.loads(line[6:])
        content = parsed.get("result", {}).get("content", [])
        if isinstance(content, list):
            return [c for c in content if isinstance(c, dict)]
    return []


def _get_index(workspace_root: str | None = None) -> SymbolIndex:
    if workspace_root is None:
        global _index
        if _index is None:
            _index = SymbolIndex(db_path=_DB_PATH)
        return _index

    ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE
    db_path = resolve_index_db_path(ws)

    with _cache_lock:
        existing = _index_cache.get(db_path)
        if existing is not None:
            _index_cache.move_to_end(db_path)
            return existing

        index = SymbolIndex(db_path=db_path)
        _index_cache[db_path] = index
        _index_cache.move_to_end(db_path)

        while len(_index_cache) > _CACHE_LIMIT:
            _, evicted = _index_cache.popitem(last=False)
            evicted.close()

        return index


def _get_indexer(workspace_root: str | None = None) -> IncrementalIndexer:
    if workspace_root is None:
        global _indexer
        if _indexer is None:
            _indexer = IncrementalIndexer(index=_get_index())
        return _indexer

    ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE
    db_path = resolve_index_db_path(ws)

    with _cache_lock:
        existing = _indexer_cache.get(db_path)
        if existing is not None:
            _indexer_cache.move_to_end(db_path)
            return existing

        indexer = IncrementalIndexer(index=_get_index(ws))
        _indexer_cache[db_path] = indexer
        _indexer_cache.move_to_end(db_path)

        while len(_indexer_cache) > _CACHE_LIMIT:
            _indexer_cache.popitem(last=False)

        return indexer


def _get_parser() -> BslParser:
    global _parser
    if _parser is None:
        _parser = BslParser()
    return _parser


def _mcp_diagnostic_list(issues: list[object]) -> list[dict]:
    """JSON diagnostics aligned with LSP: internal ``code`` + ``rule_name`` (BSLLS-style)."""
    return [d.to_dict(include_rule_name=True) for d in issues]


def _mcp_unused_diagnostics(file_path: str, idx: SymbolIndex) -> list[dict]:
    """
    Optional BSL-DEAD items (non-export symbols with no callers), same semantics as LSP.

    Requires a populated index; empty list if nothing unused.
    """
    out: list[dict] = []
    try:
        for sym in idx.find_unused_symbols(file_path):
            name = sym.get("name", "")
            line = int(sym.get("line", 1))
            char = int(sym.get("character", 0))
            end_char = char + utf16_len(name)
            msg = f"Неиспользуемая функция или метод: «{name}»"
            out.append(
                {
                    "file": file_path,
                    "line": line,
                    "character": char,
                    "end_line": line,
                    "end_character": end_char,
                    "severity": "INFORMATION",
                    "code": "BSL-DEAD",
                    "message": msg,
                    "rule_name": display_name_for_rule_code("BSL-DEAD"),
                    "source": "onec-hbk-bsl · unused",
                }
            )
    except Exception:
        logger.debug("MCP: unused diagnostics failed for %s", file_path, exc_info=True)
    return out


def _resolve_mcp_check_file_select_ignore(
    select: str | None,
    ignore: str | None,
) -> tuple[set[str] | None, set[str] | None]:
    """
    Tool parameters override environment when non-empty; otherwise use
    ``BSL_SELECT`` / ``BSL_IGNORE`` (same as LSP).
    """
    env_sel, env_ign = parse_env_rule_filters()
    if select and select.strip():
        sel = normalize_rule_code_set(select.split(","))
    else:
        sel = env_sel
    if ignore and ignore.strip():
        ign = normalize_rule_code_set(ignore.split(","))
    else:
        ign = env_ign
    return sel, ign


# ---------------------------------------------------------------------------
# MCP app factory
# ---------------------------------------------------------------------------


def create_mcp_app() -> FastMCP:
    """Create and return the FastMCP application with all BSL tools registered."""
    mcp = FastMCP(
        name="onec-hbk-bsl",
        instructions=(
            "BSL (1C Enterprise) static analysis server. "
            "Use bsl_status first to verify the index is ready. "
            "Then use bsl_find_symbol, bsl_callers, bsl_callees, etc. "
            "to explore the codebase."
        ),
    )

    # ------------------------------------------------------------------
    # bsl_contract_version — contract & versioning
    # ------------------------------------------------------------------
    @mcp.tool(description="Return MCP JSON response contract version for onec-hbk-bsl tools.")
    def bsl_contract_version() -> dict:
        return {
            "schema_version": MCP_CONTRACT_VERSION,
            "server": "onec-hbk-bsl",
            "tools": [
                "bsl_status",
                "bsl_find_symbol",
                "bsl_file_symbols",
                "bsl_callers",
                "bsl_callees",
                "bsl_diagnostics",
                "bsl_definition",
                "bsl_check_file",
                "bsl_list_rules",
                "bsl_index_file",
                "bsl_hover",
                "bsl_references",
                "bsl_read_file",
                "bsl_search",
                "bsl_format",
                "bsl_rename",
                "bsl_fix",
                "bsl_workspace_scan",
                "bsl_meta_object",
                "bsl_meta_collection",
                "bsl_meta_index",
            ],
        }

    # ------------------------------------------------------------------
    # bsl_status
    # ------------------------------------------------------------------

    @mcp.tool(description="Return current indexing status: files indexed, last commit, ready state.")
    def bsl_status(
        workspace_root: Annotated[str | None, "Workspace root for the index (defaults to server WORKSPACE_ROOT)"] = None,
    ) -> dict:
        """
        Check the health of the BSL symbol index.

        Returns stats: symbol count, file count, last indexed git commit, workspace root.
        Call this first to confirm the index is populated before searching.
        """
        ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE
        index = _get_index(workspace_root)
        stats = index.get_stats()
        return {
            "ready": stats["symbol_count"] > 0,
            "symbol_count": stats["symbol_count"],
            "file_count": stats["file_count"],
            "call_count": stats["call_count"],
            "meta_object_count": stats.get("meta_object_count", 0),
            "last_commit": stats["last_commit"],
            "indexed_at": stats["indexed_at"],
            "workspace_root": stats["workspace_root"] or ws,
            "db_path": getattr(index, "db_path", resolve_index_db_path(ws)),
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
        workspace_root: Annotated[
            str | None, "Workspace root for index (defaults to server WORKSPACE_ROOT)"
        ] = None,
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
        rows = _get_index(workspace_root).find_symbol(
            name, file_filter=file_filter, limit=limit, fuzzy=fuzzy
        )
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative paths"
        ] = None,
    ) -> dict:
        """
        Return every symbol defined in *file_path*, ordered by line.

        Useful for building a quick outline of a module.
        """
        path = _resolve_path(file_path, workspace_root=workspace_root)
        rows = _get_index(workspace_root).get_file_symbols(path)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving index DB and relative file paths"
        ] = None,
    ) -> dict:
        """
        Return a tree of callers for *symbol_name* up to *depth* levels deep.

        Args:
            symbol_name: The procedure/function whose callers you want.
            depth:       Recursion depth for the callers tree (default 3).
        """
        graph = build_call_graph(_get_index(workspace_root), symbol_name, depth=depth)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving index DB and relative file paths"
        ] = None,
    ) -> dict:
        """
        Return the list of symbols called by *symbol_name*.

        Args:
            symbol_name: The procedure/function to inspect.
            depth:       How deep to follow the call chain (default 3).
        """
        graph = build_call_graph(_get_index(workspace_root), symbol_name, depth=depth)
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
            "Run the full BSL DiagnosticEngine on a file (same rules as LSP: BSL001–BSL280 registry, "
            "respects BSL_SELECT/BSL_IGNORE env, optional BSL280 with workspace metadata index). "
            "Set include_unused=true to also emit BSL-DEAD (unused non-export procedures/functions) "
            "when the symbol index is populated."
        )
    )
    def bsl_diagnostics(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative file paths"
        ] = None,
        include_unused: Annotated[
            bool,
            "If true, append BSL-DEAD diagnostics for unused private symbols (requires index).",
        ] = False,
    ) -> dict:
        """
        Run the DiagnosticEngine on *file_path* and return all issues.

        Uses the same rule selection as LSP: environment ``BSL_SELECT`` /
        ``BSL_IGNORE``, the workspace index for metadata-aware rules (e.g. BSL280),
        and includes ``rule_name`` (BSLLS-style) next to internal ``code``.

        Returns:
            Dict with ``count``, ``has_errors``, and ``diagnostics`` list.
            Each diagnostic has: file, line, character, severity, code, rule_name, message.
            Optional BSL-DEAD entries include ``source``: ``onec-hbk-bsl · unused``.
        """
        path = _resolve_path(file_path, workspace_root=workspace_root)
        env_sel, env_ign = parse_env_rule_filters()
        idx = _get_index(workspace_root)
        engine = DiagnosticEngine(
            parser=_get_parser(),
            symbol_index=idx,
            select=env_sel,
            ignore=env_ign,
        )
        issues = engine.check_file(path)
        diags = _mcp_diagnostic_list(issues)
        if include_unused:
            diags.extend(_mcp_unused_diagnostics(path, idx))
        err = any(d.severity.name == "ERROR" for d in issues)
        return {
            "file_path": path,
            "count": len(diags),
            "has_errors": err,
            "diagnostics": diags,
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving index DB and relative paths"
        ] = None,
    ) -> dict:
        """
        Look up where *symbol_name* is defined in the index.

        Returns a list of definition locations (file, line, signature).
        Multiple results possible if the name is defined in multiple files.
        """
        rows = _get_index(workspace_root).find_symbol(
            symbol_name, file_filter=file_filter, limit=10
        )
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
            "Empty select/ignore falls back to BSL_SELECT/BSL_IGNORE env (same as LSP). "
            "Accepts BSL### or BSLLS names. Diagnostics include rule_name + code."
        )
    )
    def bsl_check_file(
        file_path: Annotated[str, "Absolute or workspace-relative path to the .bsl file"],
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative file paths"
        ] = None,
        select: Annotated[
            str | None,
            "Comma-separated rules (BSL### or BSLLS names). "
            "If omitted, uses BSL_SELECT env (same as LSP); if env unset, all rules.",
        ] = None,
        ignore: Annotated[
            str | None,
            "Comma-separated rules to skip. "
            "If omitted, uses BSL_IGNORE env (same as LSP).",
        ] = None,
        include_unused: Annotated[
            bool,
            "If true, append BSL-DEAD diagnostics for unused private symbols (requires index).",
        ] = False,
    ) -> dict:
        """
        Lint *file_path* using the BSL DiagnosticEngine.

        Supports inline suppression comments in the source::

            А = А;  // noqa: BSL009
            Пароль = "123";  // bsl-disable: BSL012

        Args:
            file_path: Path to the .bsl source file.
            select:    Whitelist; empty → ``BSL_SELECT`` env (LSP parity).
            ignore:    Blacklist; empty → ``BSL_IGNORE`` env (LSP parity).

        Returns:
            Dict with ``count``, ``has_errors``, and ``diagnostics`` list.
        """
        path = _resolve_path(file_path, workspace_root=workspace_root)
        select_set, ignore_set = _resolve_mcp_check_file_select_ignore(select, ignore)
        idx = _get_index(workspace_root)
        engine = DiagnosticEngine(
            parser=_get_parser(),
            symbol_index=idx,
            select=select_set,
            ignore=ignore_set,
        )
        issues = engine.check_file(path)
        diags = _mcp_diagnostic_list(issues)
        if include_unused:
            diags.extend(_mcp_unused_diagnostics(path, idx))
        err = any(d.severity.name == "ERROR" for d in issues)
        return {
            "file_path": path,
            "count": len(diags),
            "has_errors": err,
            "diagnostics": diags,
        }

    # ------------------------------------------------------------------
    # bsl_list_rules
    # ------------------------------------------------------------------

    @mcp.tool(
        description="Return metadata for all built-in BSL lint rules (registry BSL001–BSL280).",
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative paths"
        ] = None,
    ) -> dict:
        """
        Parse *file_path* and update the symbol index.

        Returns the number of symbols and call edges indexed.
        This is a mutating operation — it modifies the SQLite database.
        """
        path = _resolve_path(file_path, workspace_root=workspace_root)
        result = _get_indexer(workspace_root).index_file(path)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving the workspace index"
        ] = None,
    ) -> dict:
        """
        Return hover-style documentation for *symbol_name*.

        Resolution order:
        1. Workspace symbol index (user-defined procedures/functions)
        2. Built-in platform API (global functions and types)
        """
        from onec_hbk_bsl.analysis.platform_api import get_platform_api

        index = _get_index(workspace_root)
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
    # bsl_1c_help (proxy for 1c-help MCP)
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Search 1C help content by keyword (proxy to 1c-help MCP). "
            "Returns a deterministic sorted list of snippets for assistant context."
        )
    )
    def bsl_1c_help_search_keyword(
        query: Annotated[str, "Search query"],
        limit: Annotated[int, "Max number of results (default 3)"] = 3,
    ) -> dict:
        cache_key = (query, int(limit))
        cached = _help_keyword_cache.get(cache_key)
        if cached is not None:
            return {"query": query, "limit": int(limit), "results": cached, "cached": True}

        try:
            raw_results = _post_1c_help_tool(
                "search_1c_help_keyword", {"query": query, "limit": int(limit)}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("1c-help MCP keyword search failed: %s", exc)
            return {
                "query": query,
                "limit": int(limit),
                "results": [],
                "error": str(exc),
                "cached": False,
            }

        # Make ordering deterministic for assistant consumption.
        results = sorted(
            raw_results,
            key=lambda r: (str(r.get("path", "")), str(r.get("text", ""))),
        )
        _help_keyword_cache[cache_key] = results
        return {"query": query, "limit": int(limit), "results": results, "cached": False}

    @mcp.tool(
        description=(
            "Get a full 1C help topic by path (proxy to 1c-help MCP). "
            "Returns extracted text suitable for assistant context."
        )
    )
    def bsl_1c_help_get_topic(path: Annotated[str, "Topic path (as used by 1c-help)"]) -> dict:
        cached = _help_topic_cache.get(path)
        if cached is not None:
            return {"path": path, "text": cached, "cached": True}

        try:
            content = _post_1c_help_tool("get_1c_help_topic", {"path": path})
            text = ""
            if content:
                # 1c-help returns a list; we take the first item.
                text = str(content[0].get("text", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("1c-help MCP get_topic failed: %s", exc)
            return {"path": path, "text": "", "error": str(exc), "cached": False}

        _help_topic_cache[path] = text
        return {"path": path, "text": text, "cached": False}

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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving the workspace index"
        ] = None,
    ) -> dict:
        """
        Return all locations where *symbol_name* appears in the codebase:
        its definition(s) and every call site.
        """
        index = _get_index(workspace_root)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative paths"
        ] = None,
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
        path = _resolve_path(file_path, workspace_root=workspace_root)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving index DB and scanning files"
        ] = None,
    ) -> dict:
        """
        Search the workspace for *query*.

        search_type='symbol'  — FTS prefix search in symbol index.
        search_type='text'    — regex grep over file contents.
        search_type='both'    — runs both and merges results.
        """
        results: dict = {"query": query, "search_type": search_type}
        ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE

        if search_type in ("symbol", "both"):
            rows = _get_index(workspace_root).find_symbol(
                query, file_filter=file_filter, limit=limit, fuzzy=True
            )
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

            workspace = Path(ws)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative file paths"
        ] = None,
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
        path = _resolve_path(file_path, workspace_root=workspace_root)
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving the index DB and file edits"
        ] = None,
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

        index = _get_index(workspace_root)
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
            "Comma-separated rules to fix (BSL### or BSLLS names). Default: all fixable.",
        ] = None,
        workspace_root: Annotated[
            str | None, "Workspace root for resolving workspace-relative file paths"
        ] = None,
    ) -> dict:
        """
        Run the FixEngine on *file_path* and return fixed content.

        Fixable rules: BSL009 (trailing whitespace), BSL010 (missing EOF newline),
        BSL055 (commented-out code removal), BSL060 (tab → spaces).
        """
        path = _resolve_path(file_path, workspace_root=workspace_root)
        if not Path(path).exists():
            return {"error": f"File not found: {path}", "file_path": path}

        fixable_codes = {"BSL009", "BSL010", "BSL055", "BSL060"}
        select_set = normalize_rule_code_set(rules.split(",")) if rules else None
        run_codes = (select_set & fixable_codes) if select_set else fixable_codes

        engine = DiagnosticEngine(
            parser=_get_parser(),
            symbol_index=_get_index(workspace_root),
            select=run_codes,
            ignore=None,
        )
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
        workspace_root: Annotated[
            str | None, "Workspace root for resolving relative paths"
        ] = None,
    ) -> dict:
        """
        Walk *directory* and list all .bsl files with optional per-file metrics.

        Returns:
            Dict with ``file_count``, ``total_lines``, and ``files`` list.
            Each file entry has: path, size_bytes, line_count, symbol_count (if indexed).
        """
        ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE
        root = Path(_resolve_path(directory, workspace_root=workspace_root)) if directory else Path(ws)
        if not root.is_dir():
            return {"error": f"Not a directory: {root}"}

        bsl_files = sorted(root.rglob("*.bsl"))
        total_lines = 0
        files_info: list[dict] = []

        index = _get_index(workspace_root)

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

    # ------------------------------------------------------------------
    # bsl_meta_object — metadata object info
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Get 1C configuration metadata for an object: attributes (requisites), "
            "tabular sections, and form attributes. Works only when a 1C configuration "
            "export (with Configuration.xml) is present in the workspace."
        )
    )
    def bsl_meta_object(
        name: Annotated[str, "Technical name of the 1C metadata object (e.g. 'Контрагенты')"],
        kind_filter: Annotated[
            str | None,
            "Optional: filter members by kind: 'attribute', 'tabular_section', "
            "'ts_attribute', 'form_attribute', 'form_command'",
        ] = None,
        workspace_root: Annotated[
            str | None, "Workspace root for selecting the metadata index DB"
        ] = None,
    ) -> dict:
        """
        Return metadata members (attributes, tabular sections, form data) for a 1C config object.

        Args:
            name: Technical name of the object (e.g. 'Контрагенты', 'РасходнаяНакладная').
            kind_filter: Filter by member kind (attribute, tabular_section, etc.).

        Returns:
            Dict with object info and list of members.
        """
        index = _get_index(workspace_root)
        obj_info = index.find_meta_object(name)
        if obj_info is None:
            return {"error": f"Metadata object '{name}' not found. Is 1C config indexed?"}

        members = index.get_meta_members(name)
        if kind_filter:
            members = [m for m in members if m.get("kind") == kind_filter]

        # Group by kind for readability
        attributes = [m for m in members if m["kind"] == "attribute"]
        tabular_sections = [m for m in members if m["kind"] == "tabular_section"]
        ts_attributes = [m for m in members if m["kind"] == "ts_attribute"]
        form_attributes = [m for m in members if m["kind"] == "form_attribute"]
        form_commands = [m for m in members if m["kind"] == "form_command"]

        return {
            "name": obj_info["name"],
            "kind": obj_info["kind"],
            "synonym_ru": obj_info.get("synonym_ru", ""),
            "collection": obj_info.get("collection", ""),
            "attributes": [{"name": m["name"], "type": m.get("type_info", "")} for m in attributes],
            "tabular_sections": [m["name"] for m in tabular_sections],
            "ts_attributes": [
                {"name": m["name"], "type": m.get("type_info", "")} for m in ts_attributes
            ],
            "form_attributes": [m["name"] for m in form_attributes],
            "form_commands": [m["name"] for m in form_commands],
            "total_members": len(members),
        }

    # ------------------------------------------------------------------
    # bsl_meta_collection — list objects in a 1C global collection
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "List all objects in a 1C global metadata collection "
            "(e.g. 'Справочники', 'Документы', 'РегистрыСведений'). "
            "Returns object names, kinds, and synonyms."
        )
    )
    def bsl_meta_collection(
        collection: Annotated[
            str, "Russian name of the collection (e.g. 'Справочники', 'Документы')"
        ],
        prefix: Annotated[str, "Optional name prefix to filter results"] = "",
        limit: Annotated[int, "Maximum results (default 100)"] = 100,
        workspace_root: Annotated[
            str | None, "Workspace root for selecting the metadata index DB"
        ] = None,
    ) -> dict:
        """
        List metadata objects in a 1C global collection.

        Args:
            collection: Russian collection name (e.g. 'Справочники', 'Документы').
            prefix: Filter objects whose name starts with this prefix.
            limit: Maximum number of results.

        Returns:
            Dict with collection name and list of objects.
        """
        index = _get_index(workspace_root)
        if not index.has_metadata():
            return {
                "error": "No metadata indexed. Is a 1C configuration export present in workspace?"
            }
        objects = index.find_meta_objects_by_collection(collection, prefix)[:limit]
        return {
            "collection": collection,
            "count": len(objects),
            "objects": [
                {
                    "name": o["name"],
                    "kind": o["kind"],
                    "synonym_ru": o.get("synonym_ru", ""),
                }
                for o in objects
            ],
        }

    # ------------------------------------------------------------------
    # bsl_meta_index — trigger metadata re-indexing
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Trigger re-indexing of 1C configuration metadata (XML export). "
            "Searches for Configuration.xml within the workspace and parses all objects."
        )
    )
    def bsl_meta_index(
        workspace: Annotated[
            str | None, "Workspace path to index (defaults to server WORKSPACE_ROOT)"
        ] = None,
        workspace_root: Annotated[
            str | None, "Workspace root alias for multi-project MCP"
        ] = None,
        config_root: Annotated[
            str | None, "Explicit 1C config root (Configuration.xml folder) override"
        ] = None,
    ) -> dict:
        """
        Re-index 1C configuration metadata from XML export.

        Args:
            workspace: Path to workspace containing the 1C config export.
                       Defaults to the server's WORKSPACE_ROOT.

        Returns:
            Dict with objects count, members count, or error.
        """
        ws = os.path.abspath(workspace_root or workspace or _WORKSPACE)
        indexer = _get_indexer(ws)
        result = indexer.index_metadata(ws, config_root=config_root)
        if isinstance(result, dict):
            result["metadata_kind_registry"] = defs_snapshot()
        return result

    return mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_path(file_path: str, workspace_root: str | None = None) -> str:
    """
    Resolve *file_path* to an absolute path.

    If *file_path* is relative, it is joined against WORKSPACE_ROOT.
    """
    p = Path(file_path)
    if p.is_absolute():
        return str(p)
    ws = os.path.abspath(workspace_root) if workspace_root else _WORKSPACE
    return str(Path(ws) / file_path)
