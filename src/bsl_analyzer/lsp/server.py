"""
pygls LSP server for BSL (1C Enterprise scripting language).

Capabilities implemented:
  - textDocument/definition
  - textDocument/hover
  - textDocument/documentSymbol
  - workspace/symbol
  - textDocument/publishDiagnostics  (on save)

Run with:
    bsl-analyzer --lsp
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from lsprotocol.types import (
    INITIALIZE,
    TEXT_DOCUMENT_COMPLETION,
    TEXT_DOCUMENT_DEFINITION,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_REFERENCES,
    WORKSPACE_SYMBOL,
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    CompletionParams,
    DefinitionParams,
    DiagnosticSeverity,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    DocumentSymbol,
    DocumentSymbolParams,
    Hover,
    HoverParams,
    InitializeParams,
    Location,
    MarkupContent,
    MarkupKind,
    Position,
    Range,
    ReferenceParams,
    SymbolInformation,
    SymbolKind,
    WorkspaceSymbolParams,
)
from lsprotocol.types import (
    Diagnostic as LspDiagnostic,
)
from pygls.server import LanguageServer

from bsl_analyzer.analysis.diagnostics import DiagnosticEngine, Severity
from bsl_analyzer.analysis.platform_api import PlatformApi, get_platform_api
from bsl_analyzer.indexer.incremental import IncrementalIndexer
from bsl_analyzer.indexer.symbol_index import SymbolIndex
from bsl_analyzer.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

# Map BSL severity → LSP DiagnosticSeverity
_SEV_MAP = {
    Severity.ERROR: DiagnosticSeverity.Error,
    Severity.WARNING: DiagnosticSeverity.Warning,
    Severity.INFORMATION: DiagnosticSeverity.Information,
    Severity.HINT: DiagnosticSeverity.Hint,
}

# Map symbol kind strings → LSP SymbolKind
_KIND_MAP = {
    "procedure": SymbolKind.Function,
    "function": SymbolKind.Function,
    "variable": SymbolKind.Variable,
}


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to an absolute local path."""
    if uri.startswith("file://"):
        return uri[7:]  # crude but works for Linux/macOS; use urllib for Windows
    return uri


def _path_to_uri(path: str) -> str:
    """Convert an absolute path to a file:// URI."""
    return f"file://{path}"


class BslLanguageServer(LanguageServer):
    """Extended LanguageServer with BSL-specific state."""

    def __init__(self) -> None:
        super().__init__("bsl-analyzer", "v0.1.0")
        db_path = os.environ.get("INDEX_DB_PATH", "bsl_index.sqlite")
        self.symbol_index = SymbolIndex(db_path=db_path)
        self.parser = BslParser()
        self.diagnostics_engine = DiagnosticEngine(parser=self.parser)
        self.indexer = IncrementalIndexer(index=self.symbol_index)
        self.platform_api: PlatformApi = get_platform_api()
        # In-memory document cache: uri → content
        self._docs: dict[str, str] = {}


server = BslLanguageServer()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@server.feature(INITIALIZE)
def on_initialize(ls: BslLanguageServer, params: InitializeParams) -> None:
    """Handle initialize — kick off workspace indexing if workspace is set."""
    workspace_root = None
    if params.workspace_folders:
        workspace_root = _uri_to_path(params.workspace_folders[0].uri)
    elif params.root_uri:
        workspace_root = _uri_to_path(params.root_uri)
    elif params.root_path:
        workspace_root = params.root_path

    if workspace_root and Path(workspace_root).is_dir():
        logger.info("LSP: starting background index of %s", workspace_root)

        def _do_index() -> None:
            try:
                ls.indexer.index_workspace(workspace_root, force=False)
                logger.info("LSP: indexing complete")
            except Exception as exc:
                logger.error("LSP: indexing failed: %s", exc)

        import threading
        threading.Thread(target=_do_index, daemon=True).start()


# ---------------------------------------------------------------------------
# Document synchronization
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DID_OPEN)
def on_did_open(ls: BslLanguageServer, params: DidOpenTextDocumentParams) -> None:
    """Cache document content on open."""
    doc = params.text_document
    ls._docs[doc.uri] = doc.text
    logger.debug("LSP: opened %s", doc.uri)


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(ls: BslLanguageServer, params: DidChangeTextDocumentParams) -> None:
    """Update cached content on every change."""
    uri = params.text_document.uri
    for change in params.content_changes:
        # Full document sync — replace entire content
        ls._docs[uri] = change.text
    logger.debug("LSP: changed %s", uri)


@server.feature(TEXT_DOCUMENT_DID_SAVE)
def on_did_save(ls: BslLanguageServer, params: DidSaveTextDocumentParams) -> None:
    """Re-index file and publish diagnostics on save."""
    uri = params.text_document.uri
    path = _uri_to_path(uri)

    # Re-index this file
    result = ls.indexer.index_file(path)
    logger.debug("LSP: re-indexed %s: %s", path, result)

    # Run diagnostics
    _publish_diagnostics(ls, uri, path)


def _publish_diagnostics(ls: BslLanguageServer, uri: str, path: str) -> None:
    """Run diagnostic engine and push results to the client."""
    try:
        issues = ls.diagnostics_engine.check_file(path)
        lsp_diags = [
            LspDiagnostic(
                range=Range(
                    start=Position(line=d.line - 1, character=d.character),
                    end=Position(line=d.end_line - 1, character=d.end_character),
                ),
                severity=_SEV_MAP.get(d.severity, DiagnosticSeverity.Warning),
                code=d.code,
                message=d.message,
                source="bsl-analyzer",
            )
            for d in issues
        ]
        ls.publish_diagnostics(uri, lsp_diags)
    except Exception as exc:
        logger.error("LSP: diagnostics failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Go-to-definition
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DEFINITION)
def on_definition(
    ls: BslLanguageServer, params: DefinitionParams
) -> list[Location] | None:
    """
    Resolve the definition of the symbol at the cursor position.

    TODO: Extract the word at cursor from the cached document content
    and perform a fuzzy lookup in the symbol index.
    """
    uri = params.text_document.uri
    pos = params.position

    # Extract word at cursor
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    symbols = ls.symbol_index.find_symbol(word, limit=5)
    if not symbols:
        return None

    locations = []
    for sym in symbols:
        sym_path = sym["file_path"]
        line = max(0, sym["line"] - 1)
        locations.append(
            Location(
                uri=_path_to_uri(sym_path),
                range=Range(
                    start=Position(line=line, character=sym["character"]),
                    end=Position(line=line, character=sym["character"] + len(sym["name"])),
                ),
            )
        )
    return locations


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_HOVER)
def on_hover(ls: BslLanguageServer, params: HoverParams) -> Hover | None:
    """
    Show symbol signature and doc comment on hover.

    Resolution order:
    1. Workspace symbol index (user-defined procedures/functions)
    2. Platform API global functions
    3. Platform API types
    """
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    # 1. Workspace symbol
    symbols = ls.symbol_index.find_symbol(word, limit=1)
    if symbols:
        sym = symbols[0]
        parts = [f"```bsl\n{sym.get('signature', sym['name'])}\n```"]
        doc = sym.get("doc_comment")
        if doc:
            parts.append(doc)
        parts.append(f"*Defined in* `{Path(sym['file_path']).name}:{sym['line']}`")
        return Hover(
            contents=MarkupContent(kind=MarkupKind.Markdown, value="\n\n".join(parts))
        )

    # 2. Platform global function
    global_fn = ls.platform_api.find_global(word)
    if global_fn:
        parts = [f"```bsl\n{global_fn.signature or global_fn.name}\n```"]
        if global_fn.description:
            parts.append(global_fn.description)
        if global_fn.returns:
            parts.append(f"**Returns:** `{global_fn.returns}`")
        parts.append("*1C Platform built-in*")
        return Hover(
            contents=MarkupContent(kind=MarkupKind.Markdown, value="\n\n".join(parts))
        )

    # 3. Platform type
    api_type = ls.platform_api.find_type(word)
    if api_type:
        method_names = ", ".join(m.name for m in api_type.methods[:5])
        parts = [f"**{api_type.name}** *(1C {api_type.kind})*"]
        if api_type.description:
            parts.append(api_type.description)
        if method_names:
            parts.append(f"*Methods:* {method_names}{'...' if len(api_type.methods) > 5 else ''}")
        return Hover(
            contents=MarkupContent(kind=MarkupKind.Markdown, value="\n\n".join(parts))
        )

    return None


# ---------------------------------------------------------------------------
# Document symbols
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def on_document_symbol(
    ls: BslLanguageServer, params: DocumentSymbolParams
) -> list[DocumentSymbol]:
    """Return all symbols defined in the current file."""
    path = _uri_to_path(params.text_document.uri)
    rows = ls.symbol_index.get_file_symbols(path)

    result: list[DocumentSymbol] = []
    for row in rows:
        line = max(0, row["line"] - 1)
        end_line = max(line, row["end_line"] - 1)
        sym_range = Range(
            start=Position(line=line, character=row["character"]),
            end=Position(line=end_line, character=row["end_character"]),
        )
        result.append(
            DocumentSymbol(
                name=row["name"],
                kind=_KIND_MAP.get(row["kind"], SymbolKind.Function),
                range=sym_range,
                selection_range=sym_range,
                detail=row.get("signature") or "",
            )
        )
    return result


# ---------------------------------------------------------------------------
# Workspace symbol search
# ---------------------------------------------------------------------------


@server.feature(WORKSPACE_SYMBOL)
def on_workspace_symbol(
    ls: BslLanguageServer, params: WorkspaceSymbolParams
) -> list[SymbolInformation]:
    """Search symbols across the whole workspace."""
    query = params.query.strip()
    if not query:
        return []

    rows = ls.symbol_index.find_symbol(query, limit=30, fuzzy=True)

    result: list[SymbolInformation] = []
    for row in rows:
        line = max(0, row["line"] - 1)
        result.append(
            SymbolInformation(
                name=row["name"],
                kind=_KIND_MAP.get(row["kind"], SymbolKind.Function),
                location=Location(
                    uri=_path_to_uri(row["file_path"]),
                    range=Range(
                        start=Position(line=line, character=row["character"]),
                        end=Position(line=line, character=row["character"] + len(row["name"])),
                    ),
                ),
                container_name=row.get("container") or "",
            )
        )
    return result


# ---------------------------------------------------------------------------
# Find all references
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_REFERENCES)
def on_references(
    ls: BslLanguageServer, params: ReferenceParams
) -> list[Location] | None:
    """
    Return all locations where the symbol under the cursor is called/referenced.

    Uses the call-graph index to find every call site of the function/procedure.
    Also includes the definition itself if ``includeDeclaration`` is True.
    """
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    locations: list[Location] = []

    # Include declaration if requested
    if params.context and params.context.include_declaration:
        defs = ls.symbol_index.find_symbol(word, limit=5)
        for sym in defs:
            line = max(0, sym["line"] - 1)
            locations.append(
                Location(
                    uri=_path_to_uri(sym["file_path"]),
                    range=Range(
                        start=Position(line=line, character=sym["character"]),
                        end=Position(line=line, character=sym["character"] + len(sym["name"])),
                    ),
                )
            )

    # All call sites
    callers = ls.symbol_index.find_callers(word, limit=200)
    for c in callers:
        line = max(0, c["caller_line"] - 1)
        locations.append(
            Location(
                uri=_path_to_uri(c["caller_file"]),
                range=Range(
                    start=Position(line=line, character=0),
                    end=Position(line=line, character=len(word)),
                ),
            )
        )

    return locations if locations else None


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

# Map platform kind strings → LSP CompletionItemKind
_COMPLETION_KIND_MAP = {
    "function": CompletionItemKind.Function,
    "method": CompletionItemKind.Method,
    "property": CompletionItemKind.Property,
    "class": CompletionItemKind.Class,
    "enum": CompletionItemKind.Enum,
    "procedure": CompletionItemKind.Function,
    "variable": CompletionItemKind.Variable,
}


@server.feature(TEXT_DOCUMENT_COMPLETION)
def on_completion(
    ls: BslLanguageServer, params: CompletionParams
) -> CompletionList | None:
    """
    Provide completion suggestions at the cursor position.

    Strategy:
    1. If the cursor follows a ``.`` (member access), resolve the preceding
       identifier as a type name and offer its methods/properties.
    2. Otherwise offer global platform functions + workspace-level symbols
       filtered by the current word prefix.
    """
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    lines = content.splitlines()

    if pos.line >= len(lines):
        return None

    line_text = lines[pos.line]
    col = min(pos.character, len(line_text))
    prefix_line = line_text[:col]

    items: list[CompletionItem] = []

    # ---- member access: Obj.Prefix ----------------------------------------
    dot_idx = prefix_line.rfind(".")
    if dot_idx != -1:
        # Extract the identifier before the dot
        before_dot = prefix_line[:dot_idx]
        obj_name = _last_identifier(before_dot)
        member_prefix = prefix_line[dot_idx + 1 :]

        # Try to resolve obj_name as a known type (direct type name reference)
        type_completions = ls.platform_api.get_method_completions(obj_name)
        for c in type_completions:
            label = c["label"]
            if member_prefix and not label.lower().startswith(member_prefix.lower()):
                continue
            items.append(
                CompletionItem(
                    label=label,
                    kind=_COMPLETION_KIND_MAP.get(c["kind"], CompletionItemKind.Method),
                    detail=c.get("signature", ""),
                    documentation=c.get("description", ""),
                    insert_text=label,
                )
            )
        # Return member completions even if empty (no global pollution on `.`)
        return CompletionList(is_incomplete=False, items=items)

    # ---- global scope: prefix match ----------------------------------------
    prefix = _last_identifier(prefix_line)

    # Platform global functions
    for c in ls.platform_api.get_global_completions(prefix):
        items.append(
            CompletionItem(
                label=c["label"],
                kind=CompletionItemKind.Function,
                detail=c.get("signature", ""),
                documentation=c.get("description", ""),
                insert_text=c["label"],
            )
        )

    # Workspace symbols (procedures/functions from the index)
    if prefix:
        ws_symbols = ls.symbol_index.find_symbol(prefix, limit=30, fuzzy=True)
        seen: set[str] = {c.label for c in items}  # type: ignore[attr-defined]
        for sym in ws_symbols:
            if sym["name"] in seen:
                continue
            seen.add(sym["name"])
            items.append(
                CompletionItem(
                    label=sym["name"],
                    kind=_COMPLETION_KIND_MAP.get(sym["kind"], CompletionItemKind.Function),
                    detail=sym.get("signature") or "",
                    documentation=(
                        sym.get("doc_comment") or ""
                        + f"\n*{Path(sym['file_path']).name}:{sym['line']}*"
                    ),
                    insert_text=sym["name"],
                )
            )

    return CompletionList(is_incomplete=len(items) >= 30, items=items)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _last_identifier(text: str) -> str:
    """Extract the last BSL identifier from *text* (for prefix completion)."""
    import re

    m = re.search(r"[А-ЯЁа-яёA-Za-z_]\w*$", text)
    return m.group(0) if m else ""


def _word_at_position(content: str, line: int, character: int) -> str:
    """Extract the word (identifier) at a given position in the content."""
    lines = content.splitlines()
    if line >= len(lines):
        return ""
    text = lines[line]
    if character > len(text):
        return ""

    # Expand left and right from cursor
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1

    return text[start:end]


def start_lsp_server() -> None:
    """Start the BSL LSP server on stdio (called from __main__)."""
    logger.info("Starting BSL LSP server (pygls) on stdio")
    server.start_io()
