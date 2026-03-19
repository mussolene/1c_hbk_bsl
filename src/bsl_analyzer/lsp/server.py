"""
pygls LSP server for BSL (1C Enterprise scripting language).

Capabilities implemented:
  - textDocument/definition
  - textDocument/hover
  - textDocument/documentSymbol
  - workspace/symbol
  - textDocument/publishDiagnostics  (on save)
  - textDocument/completion  (global functions + workspace symbols + member access)
  - textDocument/references
  - textDocument/rename + textDocument/prepareRename
  - callHierarchy/prepare + callHierarchy/incomingCalls + callHierarchy/outgoingCalls
  - textDocument/formatting + textDocument/rangeFormatting
  - textDocument/semanticTokens/full
  - textDocument/inlayHint
  - textDocument/documentHighlight
  - textDocument/foldingRange
  - textDocument/codeAction

Run with:
    bsl-analyzer --lsp
"""

from __future__ import annotations

import logging
import os
import re as _re
import threading
import urllib.parse
from pathlib import Path

from lsprotocol.types import (
    CALL_HIERARCHY_INCOMING_CALLS,
    CALL_HIERARCHY_OUTGOING_CALLS,
    INITIALIZE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_COMPLETION,
    TEXT_DOCUMENT_DEFINITION,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT,
    TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    TEXT_DOCUMENT_FOLDING_RANGE,
    TEXT_DOCUMENT_FORMATTING,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_INLAY_HINT,
    TEXT_DOCUMENT_PREPARE_CALL_HIERARCHY,
    TEXT_DOCUMENT_PREPARE_RENAME,
    TEXT_DOCUMENT_RANGE_FORMATTING,
    TEXT_DOCUMENT_REFERENCES,
    TEXT_DOCUMENT_RENAME,
    TEXT_DOCUMENT_SELECTION_RANGE,
    TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    WORKSPACE_SYMBOL,
    CallHierarchyIncomingCall,
    CallHierarchyIncomingCallsParams,
    CallHierarchyItem,
    CallHierarchyOutgoingCall,
    CallHierarchyOutgoingCallsParams,
    CallHierarchyPrepareParams,
    CodeAction,
    CodeActionKind,
    CodeActionParams,
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    CompletionParams,
    DefinitionParams,
    DiagnosticSeverity,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    DocumentFormattingParams,
    DocumentHighlight,
    DocumentHighlightKind,
    DocumentHighlightParams,
    DocumentRangeFormattingParams,
    DocumentSymbol,
    DocumentSymbolParams,
    FoldingRange,
    FoldingRangeKind,
    FoldingRangeParams,
    Hover,
    HoverParams,
    InitializeParams,
    InlayHint,
    InlayHintKind,
    InlayHintParams,
    Location,
    MarkupContent,
    MarkupKind,
    Position,
    PrepareRenameParams,
    Range,
    ReferenceParams,
    RenameParams,
    SaveOptions,
    SelectionRange,
    SelectionRangeParams,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensParams,
    SymbolInformation,
    SymbolKind,
    TextDocumentSyncKind,
    TextEdit,
    WorkspaceEdit,
    WorkspaceSymbolParams,
)
from lsprotocol.types import (
    Diagnostic as LspDiagnostic,
)

try:
    from pygls.server import LanguageServer  # pygls < 1.2
except ImportError:
    from pygls.lsp.server import LanguageServer  # pygls >= 1.2

from bsl_analyzer.analysis.diagnostics import DiagnosticEngine, Severity
from bsl_analyzer.analysis.formatter import default_formatter
from bsl_analyzer.analysis.platform_api import PlatformApi, get_platform_api
from bsl_analyzer.indexer.db_path import resolve_index_db_path
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
    """Convert a file:// URI to an absolute local path (cross-platform)."""
    if uri.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    return uri


def _path_to_uri(path: str) -> str:
    """Convert an absolute path to a file:// URI."""
    return f"file://{path}"


class BslLanguageServer(LanguageServer):
    """Extended LanguageServer with BSL-specific state."""

    def __init__(self) -> None:
        super().__init__(
            "bsl-analyzer",
            "v0.1.0",
            text_document_sync_kind=TextDocumentSyncKind.Full,
        )
        db_path = resolve_index_db_path(os.getcwd())
        self.symbol_index = SymbolIndex(db_path=db_path)
        self.parser = BslParser()
        self.diagnostics_engine = DiagnosticEngine(parser=self.parser)
        self.indexer = IncrementalIndexer(index=self.symbol_index)
        self.platform_api: PlatformApi = get_platform_api()
        # In-memory document cache: uri → content
        self._docs: dict[str, str] = {}
        # Debounce timers for diagnostics: uri → Timer
        self._diag_timers: dict[str, threading.Timer] = {}


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
        # Re-resolve DB path now that we know the actual workspace root
        db_path = resolve_index_db_path(workspace_root)
        if db_path != ls.symbol_index.db_path:
            ls.symbol_index = SymbolIndex(db_path=db_path)
            ls.indexer = IncrementalIndexer(index=ls.symbol_index)

        logger.info("LSP: starting background index of %s (db: %s)", workspace_root, db_path)

        def _do_index() -> None:
            try:
                ls.indexer.index_workspace(workspace_root, force=False)
                logger.info("LSP: indexing complete")
            except Exception as exc:
                logger.error("LSP: indexing failed: %s", exc)

        threading.Thread(target=_do_index, daemon=True).start()


# ---------------------------------------------------------------------------
# Document synchronization
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DID_OPEN)
def on_did_open(ls: BslLanguageServer, params: DidOpenTextDocumentParams) -> None:
    """Cache document content on open and run initial diagnostics."""
    doc = params.text_document
    ls._docs[doc.uri] = doc.text
    logger.debug("LSP: opened %s", doc.uri)
    path = _uri_to_path(doc.uri)
    threading.Thread(
        target=_publish_diagnostics, args=(ls, doc.uri, path), daemon=True
    ).start()


_DIAG_DEBOUNCE_SECS = 0.6


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(ls: BslLanguageServer, params: DidChangeTextDocumentParams) -> None:
    """Update cached content and schedule debounced diagnostics."""
    uri = params.text_document.uri
    for change in params.content_changes:
        ls._docs[uri] = change.text
    logger.debug("LSP: changed %s", uri)

    # Cancel previous pending timer for this URI
    old_timer = ls._diag_timers.pop(uri, None)
    if old_timer is not None:
        old_timer.cancel()

    path = _uri_to_path(uri)

    def _run() -> None:
        ls._diag_timers.pop(uri, None)
        _publish_diagnostics(ls, uri, path)

    timer = threading.Timer(_DIAG_DEBOUNCE_SECS, _run)
    ls._diag_timers[uri] = timer
    timer.start()


@server.feature(TEXT_DOCUMENT_DID_SAVE, SaveOptions(include_text=True))
def on_did_save(ls: BslLanguageServer, params: DidSaveTextDocumentParams) -> None:
    """Re-index file and publish diagnostics on save."""
    uri = params.text_document.uri
    path = _uri_to_path(uri)

    # Update cache from saved text if provided
    if params.text is not None:
        ls._docs[uri] = params.text

    # Cancel any pending debounce timer — save supersedes it
    old_timer = ls._diag_timers.pop(uri, None)
    if old_timer is not None:
        old_timer.cancel()

    # Re-index and run diagnostics in background
    def _run() -> None:
        result = ls.indexer.index_file(path)
        logger.debug("LSP: re-indexed %s: %s", path, result)
        _publish_diagnostics(ls, uri, path)

    threading.Thread(target=_run, daemon=True).start()


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
# Rename
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_PREPARE_RENAME)
def on_prepare_rename(
    ls: BslLanguageServer, params: PrepareRenameParams
) -> Range | None:
    """Check whether the symbol under the cursor can be renamed."""
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    symbols = ls.symbol_index.find_symbol(word, limit=1)
    if not symbols:
        return None

    # Return the range of the word under the cursor
    lines = content.splitlines()
    text = lines[pos.line] if pos.line < len(lines) else ""
    start_ch = pos.character
    while start_ch > 0 and (text[start_ch - 1].isalnum() or text[start_ch - 1] == "_"):
        start_ch -= 1
    end_ch = pos.character
    while end_ch < len(text) and (text[end_ch].isalnum() or text[end_ch] == "_"):
        end_ch += 1

    return Range(
        start=Position(line=pos.line, character=start_ch),
        end=Position(line=pos.line, character=end_ch),
    )


@server.feature(TEXT_DOCUMENT_RENAME)
def on_rename(
    ls: BslLanguageServer, params: RenameParams
) -> WorkspaceEdit | None:
    """Rename the symbol under the cursor across the whole workspace."""
    uri = params.text_document.uri
    pos = params.position
    new_name = params.new_name
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    # Collect all locations: definitions + call sites
    changes: dict[str, list[TextEdit]] = {}

    def _add_edit(file_uri: str, line: int, character: int) -> None:
        edit = TextEdit(
            range=Range(
                start=Position(line=line, character=character),
                end=Position(line=line, character=character + len(word)),
            ),
            new_text=new_name,
        )
        changes.setdefault(file_uri, []).append(edit)

    # Definitions
    for sym in ls.symbol_index.find_symbol(word, limit=50):
        line = max(0, sym["line"] - 1)
        _add_edit(_path_to_uri(sym["file_path"]), line, sym["character"])

    # Call sites
    for c in ls.symbol_index.find_callers(word, limit=500):
        line = max(0, c["caller_line"] - 1)
        _add_edit(_path_to_uri(c["caller_file"]), line, 0)

    if not changes:
        return None

    return WorkspaceEdit(changes=changes)


# ---------------------------------------------------------------------------
# Call Hierarchy
# ---------------------------------------------------------------------------


def _sym_to_call_hierarchy_item(sym: dict, ls: BslLanguageServer) -> CallHierarchyItem:
    """Convert a symbol dict from the index into a CallHierarchyItem."""
    line = max(0, sym["line"] - 1)
    end_line = max(line, sym.get("end_line", sym["line"]) - 1)
    r = Range(
        start=Position(line=line, character=sym["character"]),
        end=Position(line=end_line, character=sym.get("end_character", 0)),
    )
    return CallHierarchyItem(
        name=sym["name"],
        kind=_KIND_MAP.get(sym["kind"], SymbolKind.Function),
        uri=_path_to_uri(sym["file_path"]),
        range=r,
        selection_range=r,
        detail=sym.get("signature") or "",
    )


@server.feature(TEXT_DOCUMENT_PREPARE_CALL_HIERARCHY)
def on_prepare_call_hierarchy(
    ls: BslLanguageServer, params: CallHierarchyPrepareParams
) -> list[CallHierarchyItem] | None:
    """Prepare call hierarchy for the symbol under the cursor."""
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    symbols = ls.symbol_index.find_symbol(word, limit=5)
    if not symbols:
        return None

    return [_sym_to_call_hierarchy_item(sym, ls) for sym in symbols]


@server.feature(CALL_HIERARCHY_INCOMING_CALLS)
def on_call_hierarchy_incoming(
    ls: BslLanguageServer, params: CallHierarchyIncomingCallsParams
) -> list[CallHierarchyIncomingCall] | None:
    """Return all callers of the given symbol (incoming calls)."""
    item_name = params.item.name
    callers = ls.symbol_index.find_callers(item_name, limit=200)
    if not callers:
        return None

    result: list[CallHierarchyIncomingCall] = []
    for c in callers:
        caller_line = max(0, c["caller_line"] - 1)
        call_range = Range(
            start=Position(line=caller_line, character=0),
            end=Position(line=caller_line, character=len(item_name)),
        )
        # Build a minimal CallHierarchyItem for the caller function
        caller_syms = ls.symbol_index.find_symbol(c["caller_name"], limit=1)
        if caller_syms:
            from_item = _sym_to_call_hierarchy_item(caller_syms[0], ls)
        else:
            # Caller not in symbol index — build a stub item
            from_item = CallHierarchyItem(
                name=c["caller_name"] or "<unknown>",
                kind=SymbolKind.Function,
                uri=_path_to_uri(c["caller_file"]),
                range=call_range,
                selection_range=call_range,
            )
        result.append(
            CallHierarchyIncomingCall(
                from_=from_item,
                from_ranges=[call_range],
            )
        )
    return result


@server.feature(CALL_HIERARCHY_OUTGOING_CALLS)
def on_call_hierarchy_outgoing(
    ls: BslLanguageServer, params: CallHierarchyOutgoingCallsParams
) -> list[CallHierarchyOutgoingCall] | None:
    """Return all callees of the given symbol (outgoing calls)."""
    caller_uri = params.item.uri
    caller_file = _uri_to_path(caller_uri)
    caller_name = params.item.name

    callees = ls.symbol_index.find_callees(caller_file, caller_name=caller_name)
    if not callees:
        return None

    result: list[CallHierarchyOutgoingCall] = []
    for c in callees:
        call_line = max(0, c["caller_line"] - 1)
        call_range = Range(
            start=Position(line=call_line, character=0),
            end=Position(line=call_line, character=len(c["callee_name"])),
        )
        # Resolve callee definition
        callee_syms = ls.symbol_index.find_symbol(c["callee_name"], limit=1)
        if callee_syms:
            to_item = _sym_to_call_hierarchy_item(callee_syms[0], ls)
        else:
            callee_file = c.get("callee_file") or caller_file
            callee_def_line = max(0, (c.get("callee_line") or 1) - 1)
            callee_range = Range(
                start=Position(line=callee_def_line, character=0),
                end=Position(line=callee_def_line, character=len(c["callee_name"])),
            )
            to_item = CallHierarchyItem(
                name=c["callee_name"],
                kind=SymbolKind.Function,
                uri=_path_to_uri(callee_file),
                range=callee_range,
                selection_range=callee_range,
            )
        result.append(
            CallHierarchyOutgoingCall(
                to=to_item,
                from_ranges=[call_range],
            )
        )
    return result


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


# ---------------------------------------------------------------------------
# Code Formatting
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_FORMATTING)
def on_formatting(
    ls: BslLanguageServer, params: DocumentFormattingParams
) -> list[TextEdit] | None:
    """Format the entire document."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None
    indent_size = params.options.tab_size if params.options else 4
    try:
        formatted = default_formatter.format(content, indent_size=indent_size)
    except Exception as exc:
        logger.error("LSP: formatting failed for %s: %s", uri, exc)
        return None
    if formatted == content:
        return []
    lines = content.splitlines()
    return [
        TextEdit(
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=len(lines), character=0),
            ),
            new_text=formatted,
        )
    ]


@server.feature(TEXT_DOCUMENT_RANGE_FORMATTING)
def on_range_formatting(
    ls: BslLanguageServer, params: DocumentRangeFormattingParams
) -> list[TextEdit] | None:
    """Format the selected range."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None
    indent_size = params.options.tab_size if params.options else 4
    r = params.range
    try:
        formatted_range = default_formatter.format_range(
            content,
            start_line=r.start.line,
            end_line=r.end.line,
            indent_size=indent_size,
        )
    except Exception as exc:
        logger.error("LSP: range formatting failed for %s: %s", uri, exc)
        return None
    return [
        TextEdit(
            range=Range(
                start=Position(line=r.start.line, character=0),
                end=Position(line=r.end.line + 1, character=0),
            ),
            new_text=formatted_range,
        )
    ]


# ---------------------------------------------------------------------------
# Document Highlight (highlight all occurrences of symbol under cursor)
# ---------------------------------------------------------------------------

_IDENT_BOUNDARY_RE = __import__("re").compile(r"[А-ЯЁа-яёA-Za-z_]\w*", __import__("re").UNICODE)


@server.feature(TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def on_document_highlight(
    ls: BslLanguageServer, params: DocumentHighlightParams
) -> list[DocumentHighlight] | None:
    """Highlight all occurrences of the symbol under the cursor in the document."""
    uri = params.text_document.uri
    pos = params.position
    content = ls._docs.get(uri, "")
    if not content:
        return None
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    highlights: list[DocumentHighlight] = []
    import re
    pattern = re.compile(
        r"(?<![А-ЯЁа-яёA-Za-z_\d])" + re.escape(word) + r"(?![А-ЯЁа-яёA-Za-z_\d])",
        re.IGNORECASE | re.UNICODE,
    )
    for line_idx, line_text in enumerate(content.splitlines()):
        for m in pattern.finditer(line_text):
            highlights.append(
                DocumentHighlight(
                    range=Range(
                        start=Position(line=line_idx, character=m.start()),
                        end=Position(line=line_idx, character=m.end()),
                    ),
                    kind=DocumentHighlightKind.Text,
                )
            )
    return highlights if highlights else None


# ---------------------------------------------------------------------------
# Folding Ranges (#Область / Процедура / Если / Для / Попытка)
# ---------------------------------------------------------------------------

_FOLD_OPEN_RE = _re.compile(
    r"^\s*(?:"
    r"#(?:Область|Region)\b"
    r"|(?:Процедура|Функция|Procedure|Function)\b"
    r"|(?:Если|If)\b.*(?:Тогда|Then)\s*$"
    r"|(?:Для|ДляКаждого|For|ForEach|Пока|While)\b.*(?:Цикл|Do)\s*$"
    r"|(?:Попытка|Try)\s*$"
    r")",
    _re.IGNORECASE,
)

_FOLD_CLOSE_RE = _re.compile(
    r"^\s*(?:"
    r"#(?:КонецОбласти|EndRegion)\b"
    r"|(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\b"
    r"|(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b"
    r")",
    _re.IGNORECASE,
)

_REGION_OPEN_RE = _re.compile(r"^\s*#(?:Область|Region)\b", _re.IGNORECASE)


@server.feature(TEXT_DOCUMENT_FOLDING_RANGE)
def on_folding_range(
    ls: BslLanguageServer, params: FoldingRangeParams
) -> list[FoldingRange] | None:
    """Return folding ranges for BSL block structures."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None

    lines = content.splitlines()
    stack: list[tuple[int, str]] = []  # (start_line, kind)
    ranges: list[FoldingRange] = []

    for idx, line in enumerate(lines):
        if _FOLD_OPEN_RE.match(line):
            kind = FoldingRangeKind.Region if _REGION_OPEN_RE.match(line) else None
            stack.append((idx, kind))
        elif _FOLD_CLOSE_RE.match(line) and stack:
            start_line, kind = stack.pop()
            if idx > start_line:
                ranges.append(
                    FoldingRange(
                        start_line=start_line,
                        end_line=idx,
                        kind=kind,
                    )
                )

    return ranges if ranges else None


# ---------------------------------------------------------------------------
# Semantic Tokens (syntax highlighting via LSP)
# ---------------------------------------------------------------------------

# Token types (indices must match the legend order)
_ST_KEYWORD = 0
_ST_FUNCTION = 1
_ST_VARIABLE = 2
_ST_STRING = 3
_ST_NUMBER = 4
_ST_COMMENT = 5
_ST_OPERATOR = 6

_SEMANTIC_LEGEND = SemanticTokensLegend(
    token_types=["keyword", "function", "variable", "string", "number", "comment", "operator"],
    token_modifiers=["declaration", "definition", "readonly", "static", "deprecated"],
)

_ST_KEYWORD_RE = _re.compile(
    r"(?<![А-ЯЁа-яёA-Za-z_\d])("
    r"Процедура|КонецПроцедуры|Функция|КонецФункции"
    r"|Если|ИначеЕсли|Иначе|КонецЕсли|Тогда"
    r"|Для|Каждого|Из|По|Пока|Цикл|КонецЦикла"
    r"|Попытка|Исключение|КонецПопытки"
    r"|Возврат|Прервать|Продолжить|Новый|Перем|Экспорт"
    r"|Истина|Ложь|Неопределено|Null"
    r"|И|Или|Не"
    r"|Procedure|EndProcedure|Function|EndFunction"
    r"|If|ElsIf|Else|EndIf|Then"
    r"|For|Each|In|To|While|Do|EndDo"
    r"|Try|Except|EndTry"
    r"|Return|Break|Continue|New|Var|Export"
    r"|True|False|Undefined|And|Or|Not"
    r")(?![А-ЯЁа-яёA-Za-z_\d])",
    _re.UNICODE,
)
_ST_NUMBER_RE = _re.compile(r"\b\d+(?:\.\d+)?\b")
_ST_STRING_RE = _re.compile(r'"[^"]*"')
_ST_COMMENT_RE = _re.compile(r"//.*$")
_ST_CALL_RE = _re.compile(r"([А-ЯЁа-яёA-Za-z_]\w*)\s*\(", _re.UNICODE)


@server.feature(
    TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    SemanticTokensLegend(
        token_types=_SEMANTIC_LEGEND.token_types,
        token_modifiers=_SEMANTIC_LEGEND.token_modifiers,
    ),
)
def on_semantic_tokens_full(
    ls: BslLanguageServer, params: SemanticTokensParams
) -> SemanticTokens | None:
    """Return semantic tokens for the entire document."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None

    data: list[int] = []
    prev_line = 0
    prev_start = 0

    def _emit(line: int, start: int, length: int, token_type: int, modifiers: int = 0) -> None:
        nonlocal prev_line, prev_start
        delta_line = line - prev_line
        delta_start = start if delta_line > 0 else start - prev_start
        data.extend([delta_line, delta_start, length, token_type, modifiers])
        prev_line = line
        prev_start = start

    # Collect all tokens per line, sorted by start position
    for line_idx, line_text in enumerate(content.splitlines()):
        tokens: list[tuple[int, int, int]] = []  # (start, length, type)

        # Comments — scan first so we know their range
        cm = _ST_COMMENT_RE.search(line_text)
        comment_start = cm.start() if cm else len(line_text)
        if cm:
            tokens.append((cm.start(), len(cm.group()), _ST_COMMENT))

        # Only scan code before the comment
        code_part = line_text[:comment_start]

        # String literals
        string_ranges = [(m.start(), m.end()) for m in _ST_STRING_RE.finditer(code_part)]
        for sr_start, sr_end in string_ranges:
            tokens.append((sr_start, sr_end - sr_start, _ST_STRING))

        def _in_string(pos: int, sr: list = string_ranges) -> bool:  # noqa: B008
            return any(s <= pos < e for s, e in sr)

        # Numbers
        for m in _ST_NUMBER_RE.finditer(code_part):
            if not _in_string(m.start()):
                tokens.append((m.start(), len(m.group()), _ST_NUMBER))

        # Keywords
        for m in _ST_KEYWORD_RE.finditer(code_part):
            if not _in_string(m.start()):
                tokens.append((m.start(), len(m.group()), _ST_KEYWORD))

        # Function calls
        for m in _ST_CALL_RE.finditer(code_part):
            if not _in_string(m.start(1)):
                tokens.append((m.start(1), len(m.group(1)), _ST_FUNCTION))

        # Sort by start position, deduplicate (prefer earlier type in priority)
        tokens.sort(key=lambda t: t[0])
        seen_starts: set[int] = set()
        for start, length, ttype in tokens:
            if start not in seen_starts:
                seen_starts.add(start)
                _emit(line_idx, start, length, ttype)

    if not data:
        return None
    return SemanticTokens(data=data)


# ---------------------------------------------------------------------------
# Inlay Hints (parameter name hints at call sites)
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_INLAY_HINT)
def on_inlay_hint(
    ls: BslLanguageServer, params: InlayHintParams
) -> list[InlayHint] | None:
    """Show parameter name hints at function call sites."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None

    r = params.range
    lines = content.splitlines()
    hints: list[InlayHint] = []

    # Pattern: identifier followed by '(' — find calls and match to known symbols
    call_re = _re.compile(r"([А-ЯЁа-яёA-Za-z_]\w*)\s*\(([^)]*)\)", _re.UNICODE)

    for line_idx in range(r.start.line, min(r.end.line + 1, len(lines))):
        line_text = lines[line_idx]
        for m in call_re.finditer(line_text):
            func_name = m.group(1)
            args_text = m.group(2).strip()
            if not args_text:
                continue

            # Look up symbol to get parameter names
            syms = ls.symbol_index.find_symbol(func_name, limit=1)
            if not syms:
                continue
            sig = syms[0].get("signature") or ""
            # Extract param names from signature: FuncName(Param1, Param2 = default)
            import re as _re_inner
            param_match = _re_inner.search(r"\(([^)]*)\)", sig)
            if not param_match:
                continue
            params_str = param_match.group(1)
            param_names = [
                p.strip().split("=")[0].strip().lstrip("&").split()[0]
                for p in params_str.split(",")
                if p.strip()
            ]
            if not param_names:
                continue

            # Split args by comma (naive — doesn't handle nested calls)
            args = [a.strip() for a in args_text.split(",")]

            # Emit hint for each positional arg
            arg_start = m.start(2)
            pos_in_args = 0
            for i, arg in enumerate(args):
                if i >= len(param_names):
                    break
                param_name = param_names[i]
                if not param_name or param_name == arg:
                    pos_in_args += len(arg) + 1
                    continue
                char = arg_start + pos_in_args
                hints.append(
                    InlayHint(
                        position=Position(line=line_idx, character=char),
                        label=f"{param_name}:",
                        kind=InlayHintKind.Parameter,
                        padding_right=True,
                    )
                )
                pos_in_args += len(arg) + 1

    return hints if hints else None


# ---------------------------------------------------------------------------
# Code Actions (quick fixes from diagnostics)
# ---------------------------------------------------------------------------

# Map diagnostic code → fix description
_FIX_DESCRIPTIONS: dict[str, str] = {
    "BSL009": "Remove trailing whitespace",
    "BSL010": "Add newline at end of file",
    "BSL055": "Remove commented-out code",
    "BSL060": "Fix TabIndentation → spaces",
}


@server.feature(TEXT_DOCUMENT_CODE_ACTION)
def on_code_action(
    ls: BslLanguageServer, params: CodeActionParams
) -> list[CodeAction] | None:
    """Return quick-fix code actions for diagnostics in the given range."""
    actions: list[CodeAction] = []

    for diag in params.context.diagnostics:
        code = str(diag.code) if diag.code else ""
        description = _FIX_DESCRIPTIONS.get(code)
        if not description:
            continue
        actions.append(
            CodeAction(
                title=description,
                kind=CodeActionKind.QuickFix,
                diagnostics=[diag],
                command={
                    "title": description,
                    "command": f"bsl-analyzer.fix.{code.lower()}",
                    "arguments": [params.text_document.uri],
                },
            )
        )

    return actions if actions else None


# ---------------------------------------------------------------------------
# Selection Range (Shift+Alt+→ smart expand)
# ---------------------------------------------------------------------------

# BSL block openers → their matching closers (lowercase)
_BLOCK_PAIRS: dict[str, str] = {
    "процедура": "конецпроцедуры",
    "функция": "конецфункции",
    "если": "конецесли",
    "для": "конеццикла",
    "пока": "конеццикла",
    "попытка": "конецпопытки",
    "procedure": "endprocedure",
    "function": "endfunction",
    "if": "endif",
    "for": "enddo",
    "while": "enddo",
    "try": "endtry",
}
_BLOCK_OPENERS = frozenset(_BLOCK_PAIRS)
_BLOCK_CLOSERS = frozenset(_BLOCK_PAIRS.values())


def _first_word(line: str) -> str:
    """Return first identifier on the line, lowercased."""
    m = _re.match(r"[^\S\n]*([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z0-9_]*)", line)
    return m.group(1).lower() if m else ""


def _build_selection_range(
    lines: list[str], cursor_line: int
) -> SelectionRange | None:
    """
    Return a chain of SelectionRange nodes for the cursor position:
      word → current line → enclosing block → outer block → …
    """
    n = len(lines)
    if cursor_line >= n:
        return None

    ranges: list[tuple[int, int]] = []

    # 1. Current line (inner-most range)
    ranges.append((cursor_line, cursor_line))

    # 2. Walk outward: find enclosing blocks using a stack
    #    We scan from line 0 upward to cursor to build nesting stack,
    #    then from cursor downward to find matching closers.
    stack: list[int] = []  # line numbers of openers above cursor
    for i in range(cursor_line):
        fw = _first_word(lines[i])
        if fw in _BLOCK_OPENERS:
            stack.append(i)
        elif fw in _BLOCK_CLOSERS and stack:
            stack.pop()

    # stack now contains unmatched openers (innermost last)
    for opener_line in reversed(stack):
        opener_fw = _first_word(lines[opener_line])
        closer_kw = _BLOCK_PAIRS.get(opener_fw, "")
        # Find the matching closer after cursor
        depth = 0
        closer_line = None
        for j in range(opener_line + 1, n):
            fw = _first_word(lines[j])
            if fw == opener_fw:
                depth += 1
            elif fw == closer_kw:
                if depth == 0:
                    closer_line = j
                    break
                depth -= 1
        if closer_line is not None:
            ranges.append((opener_line, closer_line))

    if not ranges:
        return None

    # Build chain from innermost → outermost
    result: SelectionRange | None = None
    for start_l, end_l in reversed(ranges):
        end_char = len(lines[end_l]) if end_l < n else 0
        r = Range(
            start=Position(line=start_l, character=0),
            end=Position(line=end_l, character=end_char),
        )
        result = SelectionRange(range=r, parent=result)

    return result


@server.feature(TEXT_DOCUMENT_SELECTION_RANGE)
def on_selection_range(
    ls: BslLanguageServer, params: SelectionRangeParams
) -> list[SelectionRange] | None:
    """Return BSL-aware selection ranges for each requested position."""
    doc = ls.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.splitlines() if doc.source else []
    if not lines:
        return None

    result: list[SelectionRange] = []
    for pos in params.positions:
        sr = _build_selection_range(lines, pos.line)
        if sr:
            result.append(sr)

    return result if result else None


# ---------------------------------------------------------------------------
# Custom BSL requests (used by VSCode extension commands)
# ---------------------------------------------------------------------------


@server.feature("bsl/status")
def on_bsl_status(ls: BslLanguageServer, params: object) -> dict:  # type: ignore[type-arg]
    """Return index statistics for the status bar."""
    stats = ls.symbol_index.get_stats()
    return {
        "ready": True,
        "symbol_count": stats.get("symbol_count", 0),
        "file_count": stats.get("file_count", 0),
    }


@server.feature("bsl/reindexWorkspace")
def on_bsl_reindex_workspace(ls: BslLanguageServer, params: dict) -> dict:  # type: ignore[type-arg]
    """Re-index the entire workspace (triggered from VSCode command)."""
    root = params.get("root", "")
    if not root or not Path(root).is_dir():
        return {"success": False, "error": f"Invalid root: {root}"}

    import threading

    def _do() -> None:
        try:
            ls.indexer.index_workspace(root, force=True)
            logger.info("LSP: reindex complete for %s", root)
        except Exception as exc:
            logger.error("LSP: reindex failed: %s", exc)

    threading.Thread(target=_do, daemon=True).start()
    return {"success": True}


@server.feature("bsl/reindexFile")
def on_bsl_reindex_file(ls: BslLanguageServer, params: dict) -> dict:  # type: ignore[type-arg]
    """Re-index a single file (triggered from VSCode command)."""
    file_path = params.get("filePath", "")
    if not file_path or not Path(file_path).is_file():
        return {"success": False, "error": f"File not found: {file_path}"}
    try:
        ls.indexer.index_file(file_path)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------


def start_lsp_server() -> None:
    """Start the BSL LSP server on stdio (called from __main__)."""
    logger.info("Starting BSL LSP server (pygls) on stdio")
    server.start_io()
