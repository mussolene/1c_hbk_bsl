"""
pygls LSP server for BSL (1C Enterprise scripting language).

Capabilities implemented:
  - textDocument/definition
  - textDocument/hover
  - textDocument/documentSymbol
  - workspace/symbol
  - textDocument/publishDiagnostics  (legacy clients without pull diagnostics)
  - textDocument/diagnostic  (pull diagnostics; preferred on VS Code / Cursor — no push spam)
  - textDocument/completion  (global functions + workspace symbols + member access)
  - textDocument/references
  - textDocument/rename + textDocument/prepareRename
  - callHierarchy/prepare + callHierarchy/incomingCalls + callHierarchy/outgoingCalls
  - textDocument/formatting + textDocument/rangeFormatting + textDocument/onTypeFormatting
  - textDocument/semanticTokens/full
  - textDocument/inlayHint
  - textDocument/documentHighlight
  - textDocument/foldingRange
  - textDocument/codeAction

Run with:
    onec-hbk-bsl lsp
"""

from __future__ import annotations

import atexit
import logging
import os
import re as _re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lsprotocol.types import (
    CALL_HIERARCHY_INCOMING_CALLS,
    CALL_HIERARCHY_OUTGOING_CALLS,
    INITIALIZE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_CODE_LENS,
    TEXT_DOCUMENT_COMPLETION,
    TEXT_DOCUMENT_DEFINITION,
    TEXT_DOCUMENT_DIAGNOSTIC,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT,
    TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    TEXT_DOCUMENT_FOLDING_RANGE,
    TEXT_DOCUMENT_FORMATTING,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_INLAY_HINT,
    TEXT_DOCUMENT_ON_TYPE_FORMATTING,
    TEXT_DOCUMENT_PREPARE_CALL_HIERARCHY,
    TEXT_DOCUMENT_PREPARE_RENAME,
    TEXT_DOCUMENT_RANGE_FORMATTING,
    TEXT_DOCUMENT_REFERENCES,
    TEXT_DOCUMENT_RENAME,
    TEXT_DOCUMENT_SELECTION_RANGE,
    TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    TEXT_DOCUMENT_SIGNATURE_HELP,
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
    CodeDescription,
    CodeLens,
    CodeLensParams,
    Command,
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    CompletionOptions,
    CompletionParams,
    DefinitionParams,
    DiagnosticOptions,
    DiagnosticRelatedInformation,
    DiagnosticSeverity,
    DiagnosticTag,
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    DocumentDiagnosticParams,
    DocumentFormattingParams,
    DocumentHighlight,
    DocumentHighlightKind,
    DocumentHighlightParams,
    DocumentOnTypeFormattingOptions,
    DocumentOnTypeFormattingParams,
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
    InsertTextFormat,
    Location,
    LocationLink,
    MarkupContent,
    MarkupKind,
    ParameterInformation,
    Position,
    PrepareRenameParams,
    PublishDiagnosticsParams,
    Range,
    ReferenceParams,
    RelatedFullDocumentDiagnosticReport,
    RenameParams,
    SaveOptions,
    SelectionRange,
    SelectionRangeParams,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensParams,
    SignatureHelp,
    SignatureHelpParams,
    SignatureInformation,
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

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
from onec_hbk_bsl.analysis.diagnostics import (
    _BSLLS_NAME_TO_CODE,
    DiagnosticEngine,
    Severity,
    lsp_compat_severity,
    parse_env_rule_filters,
)
from onec_hbk_bsl.analysis.document_snapshot import (
    DocumentSnapshot,
    ProcInfo,
    build_document_snapshot,
)
from onec_hbk_bsl.analysis.formatter import (
    _DEDENT_BEFORE,
    _get_stripped_keyword,
    default_formatter,
)
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character, utf16_len
from onec_hbk_bsl.analysis.platform_api import PlatformApi, get_platform_api
from onec_hbk_bsl.analysis.symbols import extract_symbols
from onec_hbk_bsl.analysis.type_inference import RETURN_TYPE_MAP as _TYPE_RETURN_MAP
from onec_hbk_bsl.analysis.type_inference import BslTypeEngine
from onec_hbk_bsl.cli.config import load_config
from onec_hbk_bsl.indexer.db_path import resolve_index_db_path
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
from onec_hbk_bsl.indexer.metadata_registry import (
    ALL_COLLECTION_NAMES_RU,
    META_COLLECTION_ALIASES,
    METADATA_ROOT_NAME,
    METADATA_ROOT_NAME_CF,
)
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
from onec_hbk_bsl.lsp.document_state import DocumentDiagnosticsState
from onec_hbk_bsl.lsp.source_fragments import (
    parameter_name_from_declaration_fragment,
    split_commas_outside_double_quotes,
)
from onec_hbk_bsl.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)


def _workspace_index_mode(workspace_root: str) -> str:
    env_mode = os.environ.get("BSL_INDEX_MODE", "").strip().lower()
    if env_mode in {"off", "symbols", "full"}:
        return env_mode
    return load_config(workspace_root).index_mode


def _workspace_index_max_bytes(workspace_root: str) -> int:
    raw = os.environ.get("BSL_INDEX_MAX_BYTES", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return load_config(workspace_root).index_max_bytes


# Map BSL severity → LSP DiagnosticSeverity
_SEV_MAP = {
    Severity.ERROR: DiagnosticSeverity.Error,
    Severity.WARNING: DiagnosticSeverity.Warning,
    Severity.INFORMATION: DiagnosticSeverity.Information,
    Severity.HINT: DiagnosticSeverity.Hint,
}


# Problems panel: ``source`` = ``onec-hbk-bsl · <internal rule id>`` so VS Code
# "Group by Source" splits diagnostics by rule; ``code`` remains the BSLLS-style name.
def _lsp_diagnostic_source(internal_rule_code: str) -> str:
    return f"onec-hbk-bsl · {internal_rule_code}"


# Map symbol kind strings → LSP SymbolKind
_KIND_MAP = {
    "procedure": SymbolKind.Function,
    "function": SymbolKind.Function,
    "variable": SymbolKind.Variable,
}


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to an absolute local path (cross-platform).

    On Windows, ``urlparse(...).path`` for ``file:///C:/project`` is ``/C:/project``;
    ``urllib.request.url2pathname`` maps that to ``C:\\project`` so ``git`` and
    filesystem walks see a valid cwd (see indexing / incremental indexer).
    """
    if not uri.startswith("file://"):
        return uri
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return uri
    raw = urllib.parse.unquote(parsed.path)
    return urllib.request.url2pathname(raw)


def _path_to_uri(path: str) -> str:
    """Convert an absolute path to a correct file:// URI (drive letters on Windows)."""
    return Path(path).resolve().as_uri()


def _internal_rule_code_from_lsp_diagnostic(diag: LspDiagnostic) -> str:
    """Resolve stable internal id (``BSL###`` or ``BSL-DEAD``) from a published diagnostic."""
    data = getattr(diag, "data", None)
    if isinstance(data, dict) and "bsl" in data:
        return str(data["bsl"])
    c = diag.code
    if c is None:
        return ""
    if isinstance(c, int):
        return str(c)
    s = str(c).strip()
    if _re.match(r"^BSL\d{3}$", s, _re.IGNORECASE):
        return s.upper()
    if s.upper() in ("BSL-DEAD",):
        return "BSL-DEAD"
    return _BSLLS_NAME_TO_CODE.get(s, s)


def _is_bsl_identifier(text: str) -> bool:
    """Return True when *text* can be used as a BSL identifier."""
    if not text:
        return False
    first = text[0]
    return (first.isalpha() or first == "_") and all(ch.isalnum() or ch == "_" for ch in text)


def _lsp_diagnostic_code_fields(internal_code: str) -> tuple[str, CodeDescription | None]:
    """Public ``code`` for Problems (BSLLS-style name) + optional URN for internal id."""
    public = get_rule(internal_code).name
    if internal_code == "BSL-DEAD":
        public = "UnusedPrivateMethod"
    elif internal_code == "BSL-LSP-ERR":
        public = "DiagnosticsFailure"
    urn = f"urn:onec-hbk-bsl:rule:{internal_code}"
    return public, CodeDescription(href=urn)


def _lsp_failure_diagnostic(message: str) -> LspDiagnostic:
    """Single error shown in Problems when the engine fails (never return an empty list silently)."""
    pub, code_desc = _lsp_diagnostic_code_fields("BSL-LSP-ERR")
    return LspDiagnostic(
        range=Range(
            start=Position(line=0, character=0),
            end=Position(line=0, character=0),
        ),
        severity=DiagnosticSeverity.Error,
        code=pub,
        code_description=code_desc,
        message=message,
        source=_lsp_diagnostic_source("BSL-LSP-ERR"),
        data={"bsl": "BSL-LSP-ERR", "rule_description": "Ошибка выполнения диагностики"},
    )


class BslLanguageServer(LanguageServer):
    """Extended LanguageServer with BSL-specific state."""

    def __init__(self) -> None:
        super().__init__(
            "onec-hbk-bsl",
            "v0.1.0",
            text_document_sync_kind=TextDocumentSyncKind.Full,
        )
        self.index_mode = _workspace_index_mode(os.getcwd())
        db_path = ":memory:" if self.index_mode == "off" else resolve_index_db_path(os.getcwd())
        self.symbol_index = SymbolIndex(
            db_path=db_path, max_size_bytes=_workspace_index_max_bytes(os.getcwd())
        )
        _sel, _ign = parse_env_rule_filters()
        self.diagnostics_engine = DiagnosticEngine(
            symbol_index=self.symbol_index,
            select=_sel,
            ignore=_ign,
        )
        # quiet=True: suppress Rich progress bar that would corrupt the JSON-RPC stdio pipe.
        self.indexer = IncrementalIndexer(index=self.symbol_index, quiet=True)
        self.platform_api: PlatformApi = get_platform_api()
        # Document/diagnostics mutable state is isolated in a dedicated service.
        self.doc_state = DocumentDiagnosticsState()
        # Backward-compat aliases used across existing tests and handlers.
        self._docs = self.doc_state.docs
        self._diag_timers = self.doc_state.diag_timers
        self._diag_last_time = self.doc_state.diag_last_time
        self._diag_result_cache = self.doc_state.diag_result_cache
        self._doc_state_lock = self.doc_state.lock
        # tree_sitter.Parser is not thread-safe — one BslParser per thread.
        self._parser_tls = threading.local()
        self._parsed_doc_cache_lock = threading.RLock()
        self._parsed_doc_cache: dict[str, Any] = {}
        self._parsed_doc_cache_versions: dict[str, int] = {}
        # Single-flight guard for workspace reindex.
        self._reindex_lock = threading.Lock()
        self._reindex_running = False
        self._reindex_pending = False
        self._shutdown_event = threading.Event()
        # Set in initialize from ClientCapabilities.text_document.diagnostic (LSP 3.17 pull).
        self.client_pull_diagnostics: bool = False
        self.client_diagnostic_refresh: bool = False
        atexit.register(self.close)

    def close(self) -> None:
        """Best-effort cleanup for interpreter shutdown and client disconnects."""
        self._shutdown_event.set()
        for timer in list(self._diag_timers.values()):
            try:
                timer.cancel()
            except Exception:
                logger.debug("LSP: diagnostic timer cancel failed", exc_info=True)
        try:
            self.symbol_index.close()
        except Exception:
            logger.debug("LSP: symbol index close failed", exc_info=True)

    def _thread_bsl_parser(self) -> BslParser:
        """Return a BSL parser for this thread (underlying tree-sitter Parser is not thread-safe)."""
        p: BslParser | None = getattr(self._parser_tls, "parser", None)
        if p is None:
            p = BslParser()
            self._parser_tls.parser = p
        return p

    def _doc_get(self, uri: str, default: str | None = None) -> str | None:
        """Thread-safe read of cached document text."""
        return self.doc_state.get_doc(uri, default)


server = BslLanguageServer()


# ---------------------------------------------------------------------------
# Git branch watcher — re-indexes when .git/HEAD changes (branch switch)
# ---------------------------------------------------------------------------


def _start_branch_watcher(ls: BslLanguageServer, workspace_root: str) -> None:
    """Watch .git/HEAD for branch switches and trigger incremental re-index.

    When the user runs ``git checkout``, git rewrites ``.git/HEAD`` to point
    at the new branch.  We detect this with watchfiles (already a dependency)
    and kick off an incremental re-index in the background so LSP features
    stay accurate without requiring a server restart.
    """
    git_head = Path(workspace_root) / ".git" / "HEAD"
    if not git_head.exists():
        return  # not a git repo or .git is elsewhere (worktree etc.)

    def _watch() -> None:
        try:
            from watchfiles import watch  # already in requirements

            logger.info("LSP: watching %s for branch changes", git_head)
            for _ in watch(str(git_head), stop_event=ls._shutdown_event):
                if ls._shutdown_event.is_set():
                    break
                branch = _current_branch(git_head)
                logger.warning(
                    "LSP: branch changed → %s — scheduling re-index %s", branch, workspace_root
                )
                _schedule_workspace_reindex(ls, workspace_root, reason=f"branch:{branch}")
        except Exception as exc:
            logger.error("LSP: branch watcher crashed: %s", exc)

    threading.Thread(target=_watch, daemon=True, name="bsl-branch-watcher").start()


def _current_branch(git_head: Path) -> str:
    """Read the current branch name from .git/HEAD (best-effort)."""
    try:
        content = git_head.read_text(encoding="utf-8").strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/") :]
        return content[:8]  # detached HEAD — show short hash
    except OSError:
        return "unknown"


def _schedule_workspace_reindex(
    ls: BslLanguageServer,
    workspace_root: str,
    reason: str = "manual",
) -> None:
    """Schedule workspace reindex with single-flight semantics.

    If a reindex is already running, we only mark one pending pass and return.
    """
    with ls._reindex_lock:
        if ls._reindex_running:
            ls._reindex_pending = True
            logger.debug("LSP: re-index already running; mark pending (%s)", reason)
            return
        ls._reindex_running = True
        ls._reindex_pending = False

    def _worker() -> None:
        try:
            while True:
                try:
                    ls.indexer.index_workspace(workspace_root, force=False)
                    stats = ls.symbol_index.get_stats()
                    logger.info(
                        "LSP: re-index complete (%s): %d symbols in %d files",
                        reason,
                        stats["symbol_count"],
                        stats["file_count"],
                    )
                except Exception as exc:
                    logger.error("LSP: re-index failed (%s): %s", reason, exc)

                with ls._reindex_lock:
                    if ls._reindex_pending:
                        ls._reindex_pending = False
                        continue
                    ls._reindex_running = False
                    break
        finally:
            with ls._reindex_lock:
                if ls._reindex_running and not ls._reindex_pending:
                    ls._reindex_running = False

    threading.Thread(target=_worker, daemon=True, name="bsl-workspace-reindex").start()


def _status_payload(ls: BslLanguageServer) -> dict[str, Any]:
    """Return status-bar payload with counts, size, and reindex state."""
    stats = ls.symbol_index.get_stats()
    with ls._reindex_lock:
        reindex_running = ls._reindex_running
        reindex_pending = ls._reindex_pending
    indexing = reindex_running or reindex_pending
    return {
        "index_mode": ls.index_mode,
        "ready": stats.get("symbol_count", 0) > 0,
        "indexing": indexing,
        "reindex_running": reindex_running,
        "reindex_pending": reindex_pending,
        "symbol_count": stats.get("symbol_count", 0),
        "file_count": stats.get("file_count", 0),
        "call_count": stats.get("call_count", 0),
        "meta_object_count": stats.get("meta_object_count", 0),
        "index_size_bytes": stats.get("index_size_bytes", 0),
        "db_size_bytes": stats.get("db_size_bytes", 0),
        "wal_size_bytes": stats.get("wal_size_bytes", 0),
        "shm_size_bytes": stats.get("shm_size_bytes", 0),
        "max_size_bytes": stats.get("max_size_bytes", 0),
        "over_size_limit": stats.get("over_size_limit", False),
        "last_commit": stats.get("last_commit"),
        "indexed_at": stats.get("indexed_at"),
        "workspace_root": stats.get("workspace_root"),
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@server.feature(INITIALIZE)
def on_initialize(ls: BslLanguageServer, params: InitializeParams) -> None:
    """Handle initialize — kick off workspace indexing if workspace is set."""
    caps = params.capabilities
    td = caps.text_document if caps else None
    ls.client_pull_diagnostics = bool(td is not None and td.diagnostic is not None)
    ws = caps.workspace if caps else None
    ws_diags = getattr(ws, "diagnostics", None) if ws is not None else None
    ls.client_diagnostic_refresh = bool(getattr(ws_diags, "refresh_support", False))

    workspace_root = None
    if params.workspace_folders:
        workspace_root = _uri_to_path(params.workspace_folders[0].uri)
    elif params.root_uri:
        workspace_root = _uri_to_path(params.root_uri)
    elif params.root_path:
        workspace_root = params.root_path

    if workspace_root and Path(workspace_root).is_dir():
        ls.index_mode = _workspace_index_mode(workspace_root)
        # Re-resolve DB path now that we know the actual workspace root
        db_path = ":memory:" if ls.index_mode == "off" else resolve_index_db_path(workspace_root)
        if db_path != ls.symbol_index.db_path:
            ls.symbol_index.close()
            ls.symbol_index = SymbolIndex(
                db_path=db_path, max_size_bytes=_workspace_index_max_bytes(workspace_root)
            )
            ls.indexer = IncrementalIndexer(index=ls.symbol_index, quiet=True)
        else:
            ls.symbol_index.max_size_bytes = _workspace_index_max_bytes(workspace_root)

        if ls.index_mode == "off":
            logger.info("LSP: persistent workspace index disabled")
        else:
            logger.info(
                "LSP: scheduling %s background index of %s (db: %s)",
                ls.index_mode,
                workspace_root,
                db_path,
            )
            _schedule_workspace_reindex(ls, workspace_root, reason="initialize")
            _start_branch_watcher(ls, workspace_root)


# ---------------------------------------------------------------------------
# Document synchronization
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DID_OPEN)
def on_did_open(ls: BslLanguageServer, params: DidOpenTextDocumentParams) -> None:
    """Cache document content on open; push diagnostics only if client has no pull support."""
    doc = params.text_document
    ls.doc_state.set_doc(doc.uri, doc.text)
    ls.doc_state.clear_cache_for_uri(doc.uri)
    _schedule_local_scope_cache(ls, doc.uri, doc.text)
    logger.debug("LSP: opened %s", doc.uri)
    path = _uri_to_path(doc.uri)
    if _diagnostics_enabled() and not ls.client_pull_diagnostics:
        threading.Thread(target=_publish_diagnostics, args=(ls, doc.uri, path), daemon=True).start()


_DIAG_DEBOUNCE_SECS = 0.6  # fallback default; adaptive debounce used when timing is known
_DIAG_DEBOUNCE_MIN = 0.3
_DIAG_DEBOUNCE_MAX = 3.0
_SYNC_LOCAL_SCOPE_PARSE_MAX_BYTES = 1_000_000
_ASYNC_PULL_DIAGNOSTICS_MIN_BYTES = 1_000_000
_BACKGROUND_LOCAL_SCOPE_PARSE_MAX_BYTES = 4_000_000


def _diagnostics_enabled() -> bool:
    value = os.environ.get("BSL_DIAGNOSTICS_ENABLED", "1").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _allow_sync_local_scope_parse(content: str) -> bool:
    """Avoid blocking navigation/hover by parsing very large documents synchronously."""
    return len(content.encode("utf-8", errors="ignore")) <= _SYNC_LOCAL_SCOPE_PARSE_MAX_BYTES


def _adaptive_debounce(ls: BslLanguageServer, uri: str) -> float:
    """Return debounce delay for *uri* scaled to the last observed check duration.

    Keeps the debounce proportional to the actual cost of running diagnostics:
    fast files stay responsive; large slow files avoid cascading re-checks while
    the user is typing.  2× multiplier leaves time for a couple of edits before
    the next check fires.
    """
    last = ls.doc_state.get_last_diag_time(uri)
    if last == 0.0:
        return _DIAG_DEBOUNCE_SECS
    return min(max(last * 2.0, _DIAG_DEBOUNCE_MIN), _DIAG_DEBOUNCE_MAX)


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(ls: BslLanguageServer, params: DidChangeTextDocumentParams) -> None:
    """Update cached content; debounced push diagnostics only without pull-diagnostic support."""
    uri = params.text_document.uri
    for change in params.content_changes:
        ls.doc_state.set_doc(uri, change.text)
        _schedule_local_scope_cache(ls, uri, change.text)
    old_timer = ls.doc_state.pop_timer(uri)
    if old_timer is not None:
        old_timer.cancel()
    logger.debug("LSP: changed %s", uri)

    if not _diagnostics_enabled() or ls.client_pull_diagnostics:
        return

    path = _uri_to_path(uri)

    def _run() -> None:
        ls.doc_state.pop_timer(uri)
        _publish_diagnostics(ls, uri, path)

    timer = threading.Timer(_adaptive_debounce(ls, uri), _run)
    ls.doc_state.set_timer(uri, timer)
    timer.start()


@server.feature(TEXT_DOCUMENT_DID_SAVE, SaveOptions(include_text=True))
def on_did_save(ls: BslLanguageServer, params: DidSaveTextDocumentParams) -> None:
    """Handle save without duplicating pull-diagnostic work for open documents."""
    uri = params.text_document.uri
    path = _uri_to_path(uri)

    if params.text is not None:
        ls.doc_state.set_doc(uri, params.text)
        _schedule_local_scope_cache(ls, uri, params.text)
    old_timer = ls.doc_state.pop_timer(uri)
    if old_timer is not None:
        old_timer.cancel()

    if ls.client_pull_diagnostics and _diagnostics_enabled():
        logger.debug("LSP: save %s handled by pull diagnostics; skip direct index_file", path)
        return

    # Re-index and run diagnostics in background
    def _run() -> None:
        result = ls.indexer.index_file(path)
        logger.debug("LSP: re-indexed %s: %s", path, result)
        if _diagnostics_enabled():
            _publish_diagnostics(ls, uri, path)

    threading.Thread(target=_run, daemon=True).start()


@server.feature(TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(ls: BslLanguageServer, params: DidCloseTextDocumentParams) -> None:
    """Drop per-document runtime state on close to avoid unbounded URI retention."""
    uri = params.text_document.uri
    old_timer = ls.doc_state.close_document(uri)
    _clear_local_scope_cache(ls, uri)
    if old_timer is not None:
        old_timer.cancel()
    if not ls.client_pull_diagnostics:
        ls.text_document_publish_diagnostics(PublishDiagnosticsParams(uri=uri, diagnostics=[]))


def _build_lsp_diagnostics(ls: BslLanguageServer, uri: str, path: str) -> list[LspDiagnostic]:
    """Run the diagnostic engine and return LSP diagnostics (shared by push and pull)."""
    if not _diagnostics_enabled():
        return []
    content_for_hash = ls._doc_get(uri)
    if content_for_hash is None:
        try:
            content_for_hash = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            content_for_hash = None

    if content_for_hash is not None:
        content_hash = hash(content_for_hash)
        action, run = ls.doc_state.begin_diag_run(uri, content_hash)
        if action == "cached":
            cached = ls.doc_state.get_diag_cache(uri)
            if cached is not None and cached[0] == content_hash:
                return cached[1]
        if action == "wait" and run is not None:
            run.event.wait()
            if run.error is not None:
                return [_lsp_failure_diagnostic(f"Diagnostics failed: {run.error}")]
            return run.diagnostics or []
        if action == "run" and run is not None:
            try:
                diagnostics = _build_lsp_diagnostics_inner(ls, uri, path)
            except Exception as exc:
                logger.exception("LSP: diagnostics failed for %s", path)
                ls.doc_state.finish_diag_run(uri, run, error=exc)
                return [_lsp_failure_diagnostic(f"Diagnostics failed: {exc}")]
            ls.doc_state.finish_diag_run(uri, run, diagnostics=diagnostics)
            return diagnostics

    try:
        return _build_lsp_diagnostics_inner(ls, uri, path)
    except Exception as exc:
        logger.exception("LSP: diagnostics failed for %s", path)
        return [_lsp_failure_diagnostic(f"Diagnostics failed: {exc}")]


def _build_lsp_diagnostics_inner(ls: BslLanguageServer, uri: str, path: str) -> list[LspDiagnostic]:
    """Run the diagnostic engine and unused-symbol pass (may raise)."""
    import time as _time

    cached = ls._doc_get(uri)

    # Resolve content string used for hashing (prefer in-memory, fall back to disk).
    if cached is not None:
        _content_for_hash: str | None = cached
    else:
        try:
            _content_for_hash = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            _content_for_hash = None  # will use check_file below

    # Result cache: skip full parse+rules when content is identical to last run.
    if _content_for_hash is not None:
        _chash = hash(_content_for_hash)
        _cached_entry = ls.doc_state.get_diag_cache(uri)
        if _cached_entry is not None and _cached_entry[0] == _chash:
            logger.debug("LSP: diag cache hit for %s", uri)
            return _cached_entry[1]
    else:
        _chash = None

    _t0 = _time.perf_counter()
    context_for_index: _LspDocumentContext | None = None
    if cached is not None:
        context = _get_lsp_document_context(ls, uri, cached, source_path=path)
        if context is not None:
            context_for_index = context
            issues = ls.diagnostics_engine.check_snapshot(
                context.snapshot,
                symbol_index=ls.symbol_index,
            )
        else:
            issues = ls.diagnostics_engine.check_content(
                path,
                cached,
                symbol_index=ls.symbol_index,
            )
    elif _content_for_hash is not None:
        context = _get_lsp_document_context(
            ls,
            uri,
            _content_for_hash,
            source_path=path,
        )
        if context is not None:
            context_for_index = context
            issues = ls.diagnostics_engine.check_snapshot(
                context.snapshot,
                symbol_index=ls.symbol_index,
            )
        else:
            issues = ls.diagnostics_engine.check_content(
                path, _content_for_hash, symbol_index=ls.symbol_index
            )
    else:
        issues = ls.diagnostics_engine.check_file(path, symbol_index=ls.symbol_index)
    # Record elapsed time for adaptive debounce (no lock needed — float write is atomic).
    ls.doc_state.set_last_diag_time(uri, _time.perf_counter() - _t0)

    # Group diagnostics by rule code to reduce Problems panel clutter.
    # Rules that fire many times in one file are collapsed into a single entry
    # with the extra locations in relatedInformation (up to 50 per rule).
    # This prevents the VS Code Problems panel from being truncated at ~52 k entries
    # when a large workspace has many repetitions of the same rule per file.
    _rule_buckets: dict[str, list] = {}
    for d in issues:
        _rule_buckets.setdefault(d.code, []).append(d)

    lsp_diags: list[LspDiagnostic] = []
    for code, group in _rule_buckets.items():
        pub, code_desc = _lsp_diagnostic_code_fields(code)
        first = group[0]
        rest = group[1:]

        # Build relatedInformation for occurrences beyond the first.
        related: list[DiagnosticRelatedInformation] | None = None
        if rest:
            related = [
                DiagnosticRelatedInformation(
                    location=Location(
                        uri=uri,
                        range=Range(
                            start=Position(line=d.line - 1, character=d.character),
                            end=Position(line=d.end_line - 1, character=d.end_character),
                        ),
                    ),
                    message=get_rule(code).message,
                )
                for d in rest[:50]  # LSP spec: no hard limit, but 50 is practical
            ]

        msg = get_rule(code).message
        if rest:
            total = len(group)
            msg = f"{msg} ({total} вхождений)"
            if total > 51:
                msg += " — показаны первые 51"

        lsp_diags.append(
            LspDiagnostic(
                range=Range(
                    start=Position(line=first.line - 1, character=first.character),
                    end=Position(line=first.end_line - 1, character=first.end_character),
                ),
                severity=_SEV_MAP.get(
                    lsp_compat_severity(code, first.severity),
                    DiagnosticSeverity.Warning,
                ),
                code=pub,
                code_description=code_desc,
                message=msg,
                source=_lsp_diagnostic_source(code),
                related_information=related,
                data={"bsl": code, "rule_description": get_rule(code).description},
            )
        )

    try:
        for sym in ls.symbol_index.find_unused_symbols(path):
            name = sym.get("name", "")
            sym_line = max(0, sym["line"] - 1)
            sym_char = sym.get("character", 0)
            dead_pub, dead_desc = _lsp_diagnostic_code_fields("BSL-DEAD")
            lsp_diags.append(
                LspDiagnostic(
                    range=Range(
                        start=Position(line=sym_line, character=sym_char),
                        end=Position(line=sym_line, character=sym_char + utf16_len(name)),
                    ),
                    severity=DiagnosticSeverity.Warning,
                    code=dead_pub,
                    code_description=dead_desc,
                    message=f"Неиспользуемая функция или метод: «{name}»",
                    source=_lsp_diagnostic_source("BSL-DEAD"),
                    tags=[DiagnosticTag.Unnecessary],
                    data={
                        "bsl": "BSL-DEAD",
                        "rule_description": "Неиспользуемая функция или метод",
                    },
                )
            )
    except Exception as exc:
        logger.debug("LSP: unused detection failed for %s: %s", path, exc)

    # Store result in cache for next identical-content request.
    if _chash is not None:
        ls.doc_state.set_diag_cache(uri, _chash, lsp_diags)
        if context_for_index is not None:
            _schedule_snapshot_index(ls, uri, path, _chash, context_for_index.snapshot)

    return lsp_diags


def _schedule_snapshot_index(
    ls: BslLanguageServer,
    uri: str,
    path: str,
    content_hash: int,
    snapshot: DocumentSnapshot,
) -> None:
    """Refresh the open-file index from an existing snapshot, without reparsing."""
    if not ls.doc_state.mark_snapshot_indexed(uri, content_hash):
        return

    def _run() -> None:
        result = ls.indexer.index_snapshot(path, snapshot)
        logger.debug("LSP: snapshot-indexed %s: %s", path, result)

    threading.Thread(target=_run, daemon=True, name="bsl-lsp-snapshot-index").start()


def _publish_diagnostics(ls: BslLanguageServer, uri: str, path: str) -> None:
    """Push diagnostics (clients without textDocument/diagnostic pull support)."""
    lsp_diags = _build_lsp_diagnostics(ls, uri, path)
    ls.text_document_publish_diagnostics(PublishDiagnosticsParams(uri=uri, diagnostics=lsp_diags))


def _content_for_lsp_diagnostics(ls: BslLanguageServer, uri: str, path: str) -> str | None:
    """Return current document content for diagnostics cache decisions."""
    content = ls._doc_get(uri)
    if content is not None:
        return content
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _maybe_start_async_pull_diagnostics(
    ls: BslLanguageServer,
    uri: str,
    path: str,
) -> list[LspDiagnostic] | None:
    """Start expensive pull diagnostics in background for very large documents.

    VS Code supports ``workspace/diagnostic/refresh``; using it keeps the editor
    responsive on first open while preserving full diagnostics once the worker
    completes.
    """
    if not (ls.client_pull_diagnostics and ls.client_diagnostic_refresh):
        return None
    content = _content_for_lsp_diagnostics(ls, uri, path)
    if content is None:
        return None
    if len(content.encode("utf-8", errors="ignore")) < _ASYNC_PULL_DIAGNOSTICS_MIN_BYTES:
        return None

    content_hash = hash(content)
    cached = ls.doc_state.get_diag_cache(uri)
    if cached is not None and cached[0] == content_hash:
        return cached[1]

    action, run = ls.doc_state.begin_diag_run(uri, content_hash)
    if action == "cached":
        cached = ls.doc_state.get_diag_cache(uri)
        return cached[1] if cached is not None and cached[0] == content_hash else []
    if action == "wait":
        return []
    if run is None:
        return None

    def _run() -> None:
        try:
            diagnostics = _build_lsp_diagnostics_inner(ls, uri, path)
        except Exception as exc:
            logger.exception("LSP: async diagnostics failed for %s", path)
            ls.doc_state.finish_diag_run(uri, run, error=exc)
            return
        ls.doc_state.finish_diag_run(uri, run, diagnostics=diagnostics)
        try:
            ls.workspace_diagnostic_refresh()
        except Exception:
            logger.debug("LSP: workspace/diagnostic/refresh failed", exc_info=True)

    threading.Thread(target=_run, daemon=True, name="bsl-lsp-diagnostics").start()
    return []


@server.feature(
    TEXT_DOCUMENT_DIAGNOSTIC,
    DiagnosticOptions(inter_file_dependencies=True, workspace_diagnostics=False),
)
def on_document_diagnostic(
    ls: BslLanguageServer, params: DocumentDiagnosticParams
) -> RelatedFullDocumentDiagnosticReport:
    """Pull diagnostics (LSP 3.17). Used by VS Code / Cursor instead of push."""
    if not _diagnostics_enabled():
        return RelatedFullDocumentDiagnosticReport(items=[])
    uri = params.text_document.uri
    path = _uri_to_path(uri)
    async_items = _maybe_start_async_pull_diagnostics(ls, uri, path)
    if async_items is not None:
        return RelatedFullDocumentDiagnosticReport(items=async_items)
    items = _build_lsp_diagnostics(ls, uri, path)
    return RelatedFullDocumentDiagnosticReport(items=items)


# ---------------------------------------------------------------------------
# Go-to-definition
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DEFINITION)
def on_definition(ls: BslLanguageServer, params: DefinitionParams) -> list[LocationLink] | None:
    """
    Resolve the definition of the symbol at the cursor.

    Returns LocationLink (preferred over Location) so VSCode can:
    - highlight the origin word at the call site (originSelectionRange)
    - show the full function/procedure body in the Peek Definition widget
      (targetRange spans from the keyword line to КонецПроцедуры)
    - highlight only the name in the peek header (targetSelectionRange)

    Peek Definition:  Alt+F12
    Go to Definition: F12  (navigates when one result, shows picker otherwise)
    """
    uri = params.text_document.uri
    pos = params.position

    content = ls._doc_get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    origin_range = _word_range_at_position(content, pos.line, pos.character)
    left_word = _left_word_at_position(content, pos.line, pos.character)

    # 1. Check local scope first (parameters, Перем, loop vars, assignments).
    #    Local variables shadow same-named globals — resolve them without index.
    #    EXCEPTION: if the cursor is on a function call (word followed by '('),
    #    skip local variable lookup so `Foo = Foo()` navigates to the function.
    _line_text = content.splitlines()[pos.line] if pos.line < len(content.splitlines()) else ""
    _word_end = pos.character
    while _word_end < len(_line_text) and (
        _line_text[_word_end].isalnum() or _line_text[_word_end] == "_"
    ):
        _word_end += 1
    _after = _line_text[_word_end:].lstrip()
    _is_call = _after.startswith("(")
    if not _is_call:
        try:
            local_vars = _cached_scope_vars(ls, uri, content, pos.line) or []
            for lv in local_vars:
                if lv.name.casefold() == word.casefold():
                    decl_line = lv.line - 1  # 0-based
                    decl_char = lv.character
                    name_end = decl_char + len(lv.name)
                    r = Range(
                        start=Position(line=decl_line, character=decl_char),
                        end=Position(line=decl_line, character=name_end),
                    )
                    return [
                        LocationLink(
                            target_uri=uri,
                            target_range=r,
                            target_selection_range=r,
                            origin_selection_range=origin_range,
                        )
                    ]
        except Exception:
            pass

    # 2. Workspace symbol index (procedures, functions, exported variables)
    symbols = ls.symbol_index.find_symbol(word, limit=20)
    if left_word:
        symbols = [symbol for symbol in symbols if symbol.get("is_export")]
    if not symbols:
        return None

    # Build the origin selection range (the word the user clicked on)
    origin_range = _word_range_at_position(content, pos.line, pos.character)

    links: list[LocationLink] = []
    for sym in symbols:
        sym_path = sym["file_path"]
        name_line = max(0, sym["line"] - 1)
        name_char = sym["character"]
        name_len = len(sym["name"])

        # targetSelectionRange — just the name (highlighted in peek header)
        target_sel = Range(
            start=Position(line=name_line, character=name_char),
            end=Position(line=name_line, character=name_char + name_len),
        )

        # targetRange — the full body of the procedure/function so the peek
        # widget shows the complete implementation in context.
        end_line = sym.get("end_line")
        end_char = sym.get("end_character", 0)
        if end_line and end_line > sym["line"]:
            target_range = Range(
                start=Position(line=name_line, character=0),
                end=Position(line=max(0, end_line - 1), character=end_char),
            )
        else:
            target_range = target_sel  # fallback: same as name range

        links.append(
            LocationLink(
                target_uri=_path_to_uri(sym_path),
                target_range=target_range,
                target_selection_range=target_sel,
                origin_selection_range=origin_range,
            )
        )
    return links


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------


_API_KIND_RU: dict[str, str] = {
    "class": "класс",
    "enum": "перечисление",
    "global": "глобальный объект",
    "collection": "коллекция",
}


def _hover_markdown(parts: list[str]) -> Hover:
    return Hover(contents=MarkupContent(kind=MarkupKind.Markdown, value="\n\n".join(parts)))


def _workspace_symbol_hover(ls: BslLanguageServer, symbols: list[dict[str, Any]]) -> Hover:
    sym = symbols[0]
    sig = sym.get("signature") or sym["name"]
    parts: list[str] = [f"```bsl\n{sig}\n```"]
    doc = sym.get("doc_comment")
    if doc:
        parts.append(_format_doc_comment(doc))
    if len(symbols) == 1:
        file_name = Path(sym["file_path"]).name
        parts.append(f"*Определено в* `{file_name}`, строка {sym['line']}")
    else:
        locations = "\n".join(
            f"- `{Path(item['file_path']).name}`, строка {item['line']}" for item in symbols
        )
        parts.append(f"*Определено в {len(symbols)} местах:*\n{locations}")
    caller_count = ls.symbol_index.find_callers_count(sym["name"])
    if caller_count:
        parts.append(f"*Вызывается в {caller_count} местах*")
    return _hover_markdown(parts)


def _format_doc_comment(raw: str) -> str:
    """Strip BSL ``// `` line prefixes and render the doc comment as Markdown.

    Input:  '// Описание.\\n//\\n// Параметры:\\n//   А - Тип - Описание'
    Output: 'Описание.\\n\\n**Параметры:**\\n- А - Тип - Описание'
    """
    in_section = False  # True after a section header line (Параметры: etc.)
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        # Strip the // prefix (and one optional space) to get the text content
        if stripped.startswith("///"):
            text = stripped[3:].lstrip()
        elif stripped.startswith("//"):
            text = stripped[2:].lstrip()  # strip ALL leading spaces after //
        else:
            text = stripped

        # Section headers
        if _re.match(r"^Параметры:\s*$", text, _re.IGNORECASE):
            lines.append("**Параметры:**")
            in_section = True
        elif _re.match(r"^Возвращаемое значение:\s*$", text, _re.IGNORECASE):
            lines.append("**Возвращаемое значение:**")
            in_section = True
        elif text == "":
            in_section = False
            lines.append("")  # blank line
        elif in_section:
            # Parameter / return-value entry — format as Markdown list item
            lines.append(f"- {text}")
        else:
            lines.append(text)

    # Collapse multiple consecutive blank lines into one
    result_lines: list[str] = []
    prev_blank = False
    for line in lines:
        if line == "":
            if not prev_blank:
                result_lines.append("")
            prev_blank = True
        else:
            result_lines.append(line)
            prev_blank = False

    return "\n".join(result_lines).strip()


@server.feature(TEXT_DOCUMENT_HOVER)
def on_hover(ls: BslLanguageServer, params: HoverParams) -> Hover | None:
    """
    Показывает сигнатуру и документацию символа при наведении.

    Порядок поиска:
    1. Символы рабочего пространства (пользовательские процедуры/функции)
    2. Глобальные функции платформы 1С
    3. Типы платформы (по имени типа или по имени метода/свойства)
    """
    uri = params.text_document.uri
    pos = params.position
    content = ls._doc_get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    left_word = _left_word_at_position(content, pos.line, pos.character)

    # Detect `Новый TypeName` context: check word immediately before cursor on same line.
    lines = content.splitlines()
    _cur_line = lines[pos.line] if pos.line < len(lines) else ""
    _before_word = _cur_line[: pos.character - len(word)].rstrip()
    _after_new = (
        _re.search(r"(?:Новый|New)\s*$", _before_word, _re.IGNORECASE | _re.UNICODE) is not None
    )

    # 0. Local variable scope (parameters, Перем, loop vars, assignments).
    #    Check before workspace index — locals shadow global names.
    #    Skip when cursor is on the right side of a dot (member access)
    #    and skip when we are in `Новый TypeName` context.
    if not left_word and not _after_new:
        try:
            _engine = _cached_type_engine(ls, uri, content)
            _local_vars = _cached_scope_vars(ls, uri, content, pos.line) or []
            for _lv in _local_vars:
                if _lv.name.casefold() == word.casefold():
                    _kind_map = {
                        "parameter": "параметр",
                        "val_parameter": "параметр (Знач)",
                        "var_decl": "локальная переменная",
                        "loop_var": "переменная цикла",
                        "assignment": "локальная переменная",
                    }
                    _lv_kind = _kind_map.get(_lv.kind, "переменная")
                    _parts: list[str] = [f"```bsl\n{_lv.name}\n```"]
                    _parts.append(f"*{_lv_kind}*, объявлена на строке {_lv.line}")
                    _type = (
                        _engine.infer(_lv.name, pos.line) if _engine is not None else _lv.type_hint
                    )
                    if _type:
                        _parts.append(f"**Тип:** `{_type}`")
                    return _hover_markdown(_parts)
        except Exception:
            pass

    # 1. Символы рабочего пространства
    # Skip workspace/global lookup when:
    #   - cursor is on a member (Obj.Word) — FTS irrelevant for dot-access
    #   - cursor is in `Новый TypeName` context — always a platform type
    #   - word is a known platform TYPE name — type info takes priority
    _is_platform_type = ls.platform_api.find_type(word) is not None
    symbols = (
        ls.symbol_index.find_symbol(word, limit=5)
        if not left_word and not _after_new and not _is_platform_type
        else []
    )
    if symbols:
        return _workspace_symbol_hover(ls, symbols)

    # 2. Глобальная функция платформы 1С (не применимо к вызовам через точку)
    global_fn = ls.platform_api.find_global(word) if not left_word else None
    if global_fn:
        parts = [f"```bsl\n{global_fn.signature or global_fn.name}\n```"]
        if global_fn.description:
            parts.append(global_fn.description)
        if global_fn.returns:
            parts.append(f"**Возвращает:** `{global_fn.returns}`")
        parts.append("*Встроенная функция платформы 1С*")
        return _hover_markdown(parts)

    # 3. Тип платформы (по имени типа)
    api_type = ls.platform_api.find_type(word)
    if api_type:
        kind_ru = _API_KIND_RU.get(api_type.kind, api_type.kind)
        parts = [f"**{api_type.name}** *({kind_ru} платформы 1С)*"]
        if api_type.description:
            parts.append(api_type.description)
        # Show constructor signatures when in `Новый TypeName` context or hovering the type name
        if api_type.constructors:
            ctors = "\n".join(f"```bsl\n{c}\n```" for c in api_type.constructors)
            parts.append(f"**Конструкторы:**\n{ctors}")
        if api_type.methods:
            method_names = ", ".join(m.name for m in api_type.methods[:8])
            suffix = f"... (+{len(api_type.methods) - 8})" if len(api_type.methods) > 8 else ""
            parts.append(f"*Методы:* {method_names}{suffix}")
        if api_type.properties:
            prop_names = ", ".join(p.name for p in api_type.properties[:4])
            suffix = "..." if len(api_type.properties) > 4 else ""
            parts.append(f"*Свойства:* {prop_names}{suffix}")
        return _hover_markdown(parts)

    # 4. Метод/свойство типа платформы (через точку или по имени)
    #    Сначала уточняем тип по левому слову (если есть точка)
    type_methods = []
    if left_word:
        parent_type = ls.platform_api.find_type(left_word)
        if parent_type:
            # Ищем конкретный метод в конкретном типе
            word_lo = word.lower()
            for m in parent_type.methods:
                if m.name.lower() == word_lo or (m.name_en and m.name_en.lower() == word_lo):
                    type_methods = [(parent_type, m)]
                    break
            if not type_methods:
                for p in parent_type.properties:
                    if p.name.lower() == word_lo or (p.name_en and p.name_en.lower() == word_lo):
                        parts = [f"**{p.name}** *(свойство {parent_type.name})*"]
                        if p.description:
                            parts.append(p.description)
                        if p.read_only:
                            parts.append("*Только для чтения*")
                        return _hover_markdown(parts)

    if not type_methods:
        type_methods = ls.platform_api.find_type_method(word)

    if type_methods:
        # Берём первый результат для сигнатуры/описания
        first_type, first_method = type_methods[0]
        sig = first_method.signature or f"{first_method.name}()"
        parts = [f"```bsl\n{sig}\n```"]
        if first_method.description:
            parts.append(first_method.description)
        if first_method.returns:
            parts.append(f"**Возвращает:** `{first_method.returns}`")
        if len(type_methods) == 1:
            parts.append(f"*Метод типа* **{first_type.name}**")
        else:
            type_names = ", ".join(f"**{t.name}**" for t, _ in type_methods)
            parts.append(f"*Метод типов:* {type_names}")
        parts.append("*Встроенный метод платформы 1С*")
        return _hover_markdown(parts)

    # 4b. Exported workspace functions may also be called as object members.
    # Platform methods stay authoritative because their lookup runs first.
    if left_word:
        member_symbols = [
            symbol
            for symbol in ls.symbol_index.find_symbol(word, limit=5)
            if symbol.get("is_export")
        ]
        if member_symbols:
            return _workspace_symbol_hover(ls, member_symbols)

    # 5. Метаданные конфигурации 1С
    if hasattr(ls, "symbol_index") and ls.symbol_index.has_metadata():
        # 5a0. Root property Метаданные
        if not left_word and word.casefold() == METADATA_ROOT_NAME_CF:
            return _hover_markdown(
                [
                    f"**{METADATA_ROOT_NAME}** *(глобальное свойство)*",
                    "Доступ к метаданным текущей конфигурации: коллекции объектов "
                    "(`Справочники`, `Документы`, `РегистрыСведений`, …).",
                ]
            )
        # 5a0b. Named collection (Справочники, Документы, …)
        if not left_word and word in ALL_COLLECTION_NAMES_RU:
            return _hover_markdown(
                [
                    f"**{word}** *(коллекция метаданных)*",
                    f"Соответствует `Метаданные.{word}` — перечисление объектов этой коллекции.",
                ]
            )
        # 5a. Hovering over a metadata object name (e.g. 'Контрагенты')
        if not left_word:
            meta_obj = ls.symbol_index.find_meta_object(word)
            if meta_obj:
                kind_str = meta_obj.get("kind", "")
                synonym = meta_obj.get("synonym_ru", "")
                collection = meta_obj.get("collection", "")
                parts = [f"**{meta_obj['name']}** *({kind_str})*"]
                if synonym and synonym != meta_obj["name"]:
                    parts.append(f"*Синоним:* {synonym}")
                if collection:
                    parts.append(f"*Коллекция:* `{collection}`")
                parts.append("*Объект метаданных конфигурации*")
                return _hover_markdown(parts)

        # 5b. Hovering over a metadata member (e.g. 'Контрагенты.НаименованиеПолное')
        if left_word:
            meta_obj_name = _metadata_object_name_from_chain(ls, _before_word) or left_word
            members = ls.symbol_index.get_meta_members(meta_obj_name, word)
            word_lo = word.casefold()
            for m in members:
                if m["name"].casefold() == word_lo:
                    kind_str = m["kind"]
                    kind_ru = {
                        "attribute": "Реквизит",
                        "tabular_section": "Табличная часть",
                        "ts_attribute": "Реквизит ТЧ",
                        "form_attribute": "Реквизит формы",
                        "form_command": "Команда формы",
                    }.get(kind_str, kind_str)
                    parts = [f"**{m['name']}** *({kind_ru} {m['object_kind']}.{m['object_name']})*"]
                    if m.get("type_info"):
                        parts.append(f"*Тип:* `{m['type_info']}`")
                    if m.get("synonym_ru") and m["synonym_ru"] != m["name"]:
                        parts.append(f"*Синоним:* {m['synonym_ru']}")
                    return _hover_markdown(parts)

    return None


# ---------------------------------------------------------------------------
# Document symbols
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def on_document_symbol(ls: BslLanguageServer, params: DocumentSymbolParams) -> list[DocumentSymbol]:
    """Return all symbols defined in the current file."""
    path = _uri_to_path(params.text_document.uri)
    content = ls._doc_get(params.text_document.uri)
    if content is not None:
        symbols = _open_document_symbols(ls, params.text_document.uri, path, content)
        if symbols is not None:
            return symbols

    rows = ls.symbol_index.get_file_symbols(path)
    return [_document_symbol_from_row(row) for row in rows]


def _open_document_symbols(
    ls: BslLanguageServer,
    uri: str,
    path: str,
    content: str,
) -> list[DocumentSymbol] | None:
    """Return symbols for the current in-memory document version.

    VS Code asks ``textDocument/documentSymbol`` for Outline, breadcrumbs, and
    "Go to Symbol in Editor".  Those views must reflect unsaved edits, so the
    open document is authoritative; the SQLite index is only a fallback for
    unopened files or a still-warming large-document cache.
    """
    context = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
        source_path=path,
    )
    if context is None:
        return None
    return [_document_symbol_from_row(symbol) for symbol in extract_symbols(context.tree, path)]


def _document_symbol_from_row(row: Any) -> DocumentSymbol:
    """Convert an indexed row or Symbol dataclass to an LSP DocumentSymbol."""
    get = (
        row.get if isinstance(row, dict) else lambda name, default=None: getattr(row, name, default)
    )
    line = max(0, int(get("line", 1)) - 1)
    end_line = max(line, int(get("end_line", line + 1)) - 1)
    character = int(get("character", 0))
    end_character = int(get("end_character", character + len(str(get("name", "")))))
    sym_range = Range(
        start=Position(line=line, character=character),
        end=Position(line=end_line, character=end_character),
    )
    return DocumentSymbol(
        name=str(get("name", "")),
        kind=_KIND_MAP.get(str(get("kind", "")), SymbolKind.Function),
        range=sym_range,
        selection_range=sym_range,
        detail=str(get("signature", "") or ""),
    )


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
def on_references(ls: BslLanguageServer, params: ReferenceParams) -> list[Location] | None:
    """
    Return all locations where the symbol under the cursor is called/referenced.

    Uses the call-graph index to find every call site of the function/procedure.
    Also includes the definition itself if ``includeDeclaration`` is True.
    """
    uri = params.text_document.uri
    pos = params.position
    content = ls._doc_get(uri, "")
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
        ch = _call_char_from_row(c)
        locations.append(
            Location(
                uri=_path_to_uri(c["caller_file"]),
                range=Range(
                    start=Position(line=line, character=ch),
                    end=Position(line=line, character=ch + len(word)),
                ),
            )
        )

    return locations if locations else None


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


def _open_document_method_symbols(
    ls: BslLanguageServer,
    uri: str,
    content: str,
) -> list[dict[str, Any]]:
    path = _uri_to_path(uri)
    context = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
        source_path=path,
    )
    if context is None:
        return []
    return [
        {
            "name": symbol.name,
            "kind": symbol.kind,
            "file_path": path,
            "line": symbol.line,
            "character": symbol.character,
            "end_line": symbol.end_line,
            "end_character": symbol.end_character,
        }
        for symbol in extract_symbols(context.tree, path)
        if symbol.kind in ("procedure", "function")
    ]


def _identifier_ranges_from_cst(content: str, name: str) -> list[Range]:
    parser = BslParser()
    tree = parser.parse_content(content)
    root = getattr(tree, "root_node", None)
    if root is None:
        return []

    lines = content.splitlines()
    ranges: list[Range] = []

    def visit(node: Any, parent_type: str = "") -> None:
        node_type = getattr(node, "type", "")
        if (
            node_type == "identifier"
            and parent_type in ("procedure_definition", "function_definition", "method_call")
            and _ast_node_text(node).casefold() == name
        ):
            line0 = node.start_point[0]
            line_text = lines[line0] if 0 <= line0 < len(lines) else ""
            start = utf8_byte_offset_to_lsp_character(line_text, node.start_point[1])
            ranges.append(
                Range(
                    start=Position(line=line0, character=start),
                    end=Position(line=line0, character=start + utf16_len(_ast_node_text(node))),
                )
            )
        for child in getattr(node, "children", []) or []:
            visit(child, node_type)

    visit(root)
    return ranges


def _add_rename_edit(
    changes: dict[str, list[TextEdit]],
    seen: set[tuple[str, int, int]],
    uri: str,
    edit_range: Range,
    new_name: str,
) -> None:
    key = (uri, int(edit_range.start.line), int(edit_range.start.character))
    if key in seen:
        return
    seen.add(key)
    changes.setdefault(uri, []).append(TextEdit(range=edit_range, new_text=new_name))


@server.feature(TEXT_DOCUMENT_PREPARE_RENAME)
def on_prepare_rename(ls: BslLanguageServer, params: PrepareRenameParams) -> Range | None:
    """Check whether the symbol under the cursor can be renamed."""
    uri = params.text_document.uri
    pos = params.position
    content = ls._doc_get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not _is_bsl_identifier(word):
        return None

    open_symbols = _open_document_method_symbols(ls, uri, content) if content else []
    symbols = [s for s in open_symbols if s["name"].casefold() == word.casefold()]
    if not symbols:
        symbols = [
            s
            for s in ls.symbol_index.find_symbol(word, limit=1)
            if s.get("kind") in ("procedure", "function")
        ]
    if not symbols:
        return None

    return _word_range_at_position(content, pos.line, pos.character)


@server.feature(TEXT_DOCUMENT_RENAME)
def on_rename(ls: BslLanguageServer, params: RenameParams) -> WorkspaceEdit | None:
    """Rename the symbol under the cursor across the whole workspace."""
    uri = params.text_document.uri
    pos = params.position
    new_name = params.new_name
    content = ls._doc_get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not _is_bsl_identifier(word) or not _is_bsl_identifier(new_name):
        return None

    changes: dict[str, list[TextEdit]] = {}
    seen: set[tuple[str, int, int]] = set()
    open_uris = set(ls._docs)

    open_symbols = _open_document_method_symbols(ls, uri, content) if content else []
    indexed_symbols = [
        s
        for s in ls.symbol_index.find_symbol(word, limit=50)
        if s.get("kind") in ("procedure", "function")
    ]
    if not any(s["name"].casefold() == word.casefold() for s in open_symbols + indexed_symbols):
        return None

    for open_uri, open_content in list(ls._docs.items()):
        for r in _identifier_ranges_from_cst(open_content, word.casefold()):
            _add_rename_edit(changes, seen, open_uri, r, new_name)

    # Definitions
    for sym in indexed_symbols:
        file_uri = _path_to_uri(sym["file_path"])
        if file_uri in open_uris:
            continue
        line = max(0, sym["line"] - 1)
        _add_rename_edit(
            changes,
            seen,
            file_uri,
            Range(
                start=Position(line=line, character=sym["character"]),
                end=Position(line=line, character=sym["character"] + utf16_len(word)),
            ),
            new_name,
        )

    # Call sites
    for c in ls.symbol_index.find_callers(word, limit=500):
        file_uri = _path_to_uri(c["caller_file"])
        if file_uri in open_uris:
            continue
        line = max(0, c["caller_line"] - 1)
        character = _call_char_from_row(c)
        _add_rename_edit(
            changes,
            seen,
            file_uri,
            Range(
                start=Position(line=line, character=character),
                end=Position(line=line, character=character + utf16_len(word)),
            ),
            new_name,
        )

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


def _call_char_from_row(call_row: dict[str, Any]) -> int:
    """Return best-effort call-site column from index row."""
    char = int(call_row.get("caller_character", 0) or 0)
    return char if char >= 0 else 0


def _cached_symbol_lookup(
    ls: BslLanguageServer,
    cache: dict[tuple[str, int], list[dict[str, Any]]],
    name: str | None,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Resolve a symbol once per request for repeated call-hierarchy rows."""
    if not name:
        return []
    key = (name.casefold(), limit)
    if key not in cache:
        cache[key] = ls.symbol_index.find_symbol(name, limit=limit)
    return cache[key]


@server.feature(TEXT_DOCUMENT_PREPARE_CALL_HIERARCHY)
def on_prepare_call_hierarchy(
    ls: BslLanguageServer, params: CallHierarchyPrepareParams
) -> list[CallHierarchyItem] | None:
    """Prepare call hierarchy for the symbol under the cursor."""
    uri = params.text_document.uri
    pos = params.position
    content = ls._doc_get(uri, "")
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
    caller_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for c in callers:
        caller_line = max(0, c["caller_line"] - 1)
        caller_char = _call_char_from_row(c)
        call_range = Range(
            start=Position(line=caller_line, character=caller_char),
            end=Position(line=caller_line, character=caller_char + len(item_name)),
        )
        # Build a minimal CallHierarchyItem for the caller function
        caller_syms = _cached_symbol_lookup(ls, caller_cache, c.get("caller_name"), limit=1)
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
    callee_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for c in callees:
        call_line = max(0, c["caller_line"] - 1)
        call_char = _call_char_from_row(c)
        call_range = Range(
            start=Position(line=call_line, character=call_char),
            end=Position(line=call_line, character=call_char + len(c["callee_name"])),
        )
        # Resolve callee definition
        callee_syms = _cached_symbol_lookup(ls, callee_cache, c["callee_name"], limit=1)
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


@server.feature(
    TEXT_DOCUMENT_COMPLETION,
    CompletionOptions(trigger_characters=["."]),
)
def on_completion(ls: BslLanguageServer, params: CompletionParams) -> CompletionList | None:
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
    content = ls._doc_get(uri, "")
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
        _snippet_kinds = {"function", "procedure", "method"}
        for c in type_completions:
            label = c["label"]
            if member_prefix and not label.lower().startswith(member_prefix.lower()):
                continue
            kind_str = c.get("kind", "")
            if kind_str in _snippet_kinds:
                insert, fmt = _make_snippet(label, c.get("signature"))
            else:
                insert, fmt = label, InsertTextFormat.PlainText
            items.append(
                CompletionItem(
                    label=label,
                    kind=_COMPLETION_KIND_MAP.get(kind_str, CompletionItemKind.Method),
                    detail=c.get("signature", ""),
                    documentation=c.get("description", ""),
                    insert_text=insert,
                    insert_text_format=fmt,
                )
            )

        # ---- common module dot-completion: ОбщийМодуль. → exported symbols --
        if not items:
            for sym in ls.symbol_index.get_module_exports(obj_name):
                label = sym["name"]
                if member_prefix and not label.lower().startswith(member_prefix.lower()):
                    continue
                kind_str = sym.get("kind", "")
                if kind_str in _snippet_kinds:
                    insert, fmt = _make_snippet(label, sym.get("signature"))
                else:
                    insert, fmt = label, InsertTextFormat.PlainText
                items.append(
                    CompletionItem(
                        label=label,
                        kind=_COMPLETION_KIND_MAP.get(kind_str, CompletionItemKind.Function),
                        detail=sym.get("signature") or "",
                        documentation=sym.get("doc_comment") or "",
                        insert_text=insert,
                        insert_text_format=fmt,
                    )
                )

        # ---- type inference: Зап = Новый Запрос() → Зап. → методы Запрос ---
        if not items:
            try:
                _inf_engine = _cached_type_engine(ls, uri, content)
                inferred = (
                    _inf_engine.scope_at_line(pos.line).get(obj_name)
                    if _inf_engine is not None
                    else None
                )
            except Exception:
                inferred = None
            if inferred:
                for c in ls.platform_api.get_method_completions(inferred):
                    label = c["label"]
                    if member_prefix and not label.lower().startswith(member_prefix.lower()):
                        continue
                    kind_str = c.get("kind", "")
                    if kind_str in _snippet_kinds:
                        insert, fmt = _make_snippet(label, c.get("signature"))
                    else:
                        insert, fmt = label, InsertTextFormat.PlainText
                    items.append(
                        CompletionItem(
                            label=label,
                            kind=_COMPLETION_KIND_MAP.get(kind_str, CompletionItemKind.Method),
                            detail=c.get("signature", ""),
                            documentation=c.get("description", ""),
                            insert_text=insert,
                            insert_text_format=fmt,
                        )
                    )

        # ---- metadata: Контрагенты. → attributes/TS; Справочники. → names ---
        if not items:
            meta_obj_name = _metadata_object_name_from_chain(ls, before_dot) or obj_name
            items = _meta_dot_completions(ls, meta_obj_name, member_prefix)

        # Return member completions even if empty (no global pollution on `.`)
        return CompletionList(is_incomplete=False, items=items)

    # ---- global scope: prefix match ----------------------------------------
    prefix = _last_identifier(prefix_line)

    _snippet_kinds = {"function", "procedure", "method"}

    # Platform global functions
    for c in ls.platform_api.get_global_completions(prefix):
        label = c["label"]
        kind_str = c.get("kind", "function")
        if kind_str in _snippet_kinds:
            insert, fmt = _make_snippet(label, c.get("signature"))
        else:
            insert, fmt = label, InsertTextFormat.PlainText
        items.append(
            CompletionItem(
                label=label,
                kind=CompletionItemKind.Function,
                detail=c.get("signature", ""),
                documentation=c.get("description", ""),
                insert_text=insert,
                insert_text_format=fmt,
            )
        )

    # Workspace symbols (procedures/functions from the index)
    if prefix:
        try:
            ws_symbols = ls.symbol_index.find_symbol(prefix, limit=30, fuzzy=True)
        except Exception:  # noqa: BLE001
            logger.debug("Completion workspace symbol lookup failed", exc_info=True)
            ws_symbols = []
        seen: set[str] = {c.label for c in items}  # type: ignore[attr-defined]
        for sym in ws_symbols:
            if sym["name"] in seen:
                continue
            seen.add(sym["name"])
            kind_str = sym.get("kind", "")
            if kind_str in _snippet_kinds:
                insert, fmt = _make_snippet(sym["name"], sym.get("signature"))
            else:
                insert, fmt = sym["name"], InsertTextFormat.PlainText
            items.append(
                CompletionItem(
                    label=sym["name"],
                    kind=_COMPLETION_KIND_MAP.get(kind_str, CompletionItemKind.Function),
                    detail=sym.get("signature") or "",
                    documentation=(
                        sym.get("doc_comment")
                        or "" + f"\n*{Path(sym['file_path']).name}:{sym['line']}*"
                    ),
                    insert_text=insert,
                    insert_text_format=fmt,
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


def _generate_doc_comment_for_proc(proc: ProcInfo, all_lines: list[str]) -> str | None:
    """Generate a documentation comment block for a CST procedure/function model."""
    if proc.start_idx > 0 and all_lines[proc.start_idx - 1].strip().startswith("//"):
        return None  # already documented
    header_line = all_lines[proc.start_idx] if proc.start_idx < len(all_lines) else ""
    prefix = header_line[: len(header_line) - len(header_line.lstrip())]
    lines = [f"{prefix}// Описание {proc.name}."]
    if proc.params:
        lines += [f"{prefix}//", f"{prefix}// Параметры:"]
        for name in proc.params:
            lines.append(f"{prefix}//   {name} - Тип - Описание")
    if proc.kind == "function":
        lines += [f"{prefix}//", f"{prefix}// Возвращаемое значение:"]
        lines.append(f"{prefix}//   Тип - Описание")
    lines.append(f"{prefix}//")
    return "\n".join(lines) + "\n"


def _generate_doc_comment_at_line(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    line_idx: int,
) -> str | None:
    context = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
    )
    if context is None:
        return None
    for proc in context.snapshot.procedures:
        if proc.start_idx == line_idx:
            return _generate_doc_comment_for_proc(proc, content.splitlines(keepends=True))
    return None


_META_MEMBER_KIND_TO_COMPLETION_KIND: dict[str, object] = {}  # unused; placeholder


def _metadata_object_name_from_chain(
    ls: BslLanguageServer,
    chain_expr: str,
) -> str | None:
    """Resolve a metadata object name from a dotted expression.

    Examples:
    - ``Справочники.Контрагенты`` -> ``Контрагенты``
    - ``Справочники.Контрагенты.Товары`` -> ``Контрагенты``
    - ``Контрагенты.Товары`` -> ``Контрагенты`` (if object exists)
    """
    if not chain_expr or not hasattr(ls, "symbol_index") or not ls.symbol_index.has_metadata():
        return None

    tokens = _re.findall(r"[А-ЯЁа-яёA-Za-z_]\w*", chain_expr)
    if not tokens:
        return None

    # Case 0: Метаданные.Коллекция.Объект
    if len(tokens) >= 3 and tokens[0].casefold() == METADATA_ROOT_NAME_CF:
        if META_COLLECTION_ALIASES.get(tokens[1].casefold()) and ls.symbol_index.find_meta_object(
            tokens[2]
        ):
            return tokens[2]

    # Case 1: known global metadata collection path.
    if len(tokens) >= 2 and META_COLLECTION_ALIASES.get(tokens[0].casefold()):
        second = tokens[1]
        if ls.symbol_index.find_meta_object(second):
            return second

    # Case 2: fallback — pick first token in the chain that is a known metadata object.
    for tok in tokens:
        if ls.symbol_index.find_meta_object(tok):
            return tok

    return None


def _meta_dot_completions(
    ls: BslLanguageServer,
    obj_name: str,
    member_prefix: str,
) -> list[CompletionItem]:
    """
    Return metadata-based completion items for ``obj_name.member_prefix``.

    Handles two cases:
    1. ``obj_name`` is a 1C global collection (e.g. 'Справочники') →
       returns object names in that collection.
    2. ``obj_name`` is a metadata object name (e.g. 'Контрагенты') →
       returns attributes, TS, form attributes.
    """
    from lsprotocol.types import CompletionItem, CompletionItemKind  # noqa: PLC0415

    if not hasattr(ls, "symbol_index") or not ls.symbol_index.has_metadata():
        return []

    items: list[CompletionItem] = []
    obj_lo = obj_name.casefold()

    # Case 0: Метаданные. → canonical collection names
    if obj_lo == METADATA_ROOT_NAME_CF:
        for coll in ALL_COLLECTION_NAMES_RU:
            if member_prefix and not coll.casefold().startswith(member_prefix.casefold()):
                continue
            items.append(
                CompletionItem(
                    label=coll,
                    kind=CompletionItemKind.Module,
                    detail="Коллекция метаданных",
                    documentation=f"Глобальная коллекция (`{METADATA_ROOT_NAME}.{coll}`)",
                    insert_text=coll,
                )
            )
        return items

    # Case 1: global collection name
    collection = META_COLLECTION_ALIASES.get(obj_lo)
    if collection:
        for meta_obj in ls.symbol_index.find_meta_objects_by_collection(collection, member_prefix):
            label = meta_obj["name"]
            kind = meta_obj.get("kind", "")
            synonym = meta_obj.get("synonym_ru", "")
            detail_parts = [kind] if kind else []
            if synonym and synonym != label:
                detail_parts.append(f"Синоним: {synonym}")
            items.append(
                CompletionItem(
                    label=label,
                    kind=CompletionItemKind.Module,
                    detail=" | ".join(detail_parts),
                    documentation=f"Объект метаданных коллекции `{collection}`",
                    insert_text=label,
                )
            )
        return items

    # Case 2: direct object name → members
    for member in ls.symbol_index.get_meta_members(obj_name, member_prefix):
        label = member["name"]
        kind_str = member["kind"]
        if kind_str == "tabular_section":
            ck = CompletionItemKind.Class
        elif kind_str == "form_command":
            ck = CompletionItemKind.Event
        else:
            ck = CompletionItemKind.Field
        kind_ru = {
            "attribute": "Реквизит",
            "tabular_section": "Табличная часть",
            "ts_attribute": "Реквизит ТЧ",
            "form_attribute": "Реквизит формы",
            "form_command": "Команда формы",
        }.get(kind_str, kind_str)
        detail_parts = [kind_ru]
        if member.get("type_info"):
            detail_parts.append(f"Тип: {member['type_info']}")
        if member.get("synonym_ru") and member["synonym_ru"] != label:
            detail_parts.append(member["synonym_ru"])
        items.append(
            CompletionItem(
                label=label,
                kind=ck,
                detail=" | ".join(detail_parts),
                documentation=(
                    f"{kind_ru} объекта `{member.get('object_kind', '')}.{member.get('object_name', obj_name)}`"
                ),
                insert_text=label,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Local scope variable tracking (AST-based)
# ---------------------------------------------------------------------------


@dataclass
class _LocalVar:
    """A local variable visible at a given cursor position."""

    name: str
    kind: str  # 'parameter' | 'val_parameter' | 'var_decl' | 'loop_var' | 'assignment'
    line: int  # 1-based declaration line
    character: int  # 0-based column of the name token
    type_hint: str = ""  # e.g. "Массив" from «МойМассив = Новый Массив»


@dataclass
class _LocalScopeProc:
    """Cached local scope declarations for one procedure/function."""

    start_line0: int
    end_line0: int
    vars: list[_LocalVar]


@dataclass
class _CodeLensMetric:
    """Precomputed code lens values for one procedure/function."""

    line0: int
    cognitive: int
    mccabe: int


@dataclass
class _LspDocumentContext:
    """Lazy semantic context for one open LSP document version."""

    content_hash: int
    snapshot: DocumentSnapshot
    local_scopes: list[_LocalScopeProc]
    type_engine: BslTypeEngine | None = None
    code_lens_metrics: list[_CodeLensMetric] | None = None
    folding_ranges: list[FoldingRange] | None = None

    @property
    def tree(self) -> Any:
        return self.snapshot.tree


def _ast_node_text(node: Any) -> str:
    t = getattr(node, "text", None)
    if t is None:
        return ""
    return t.decode("utf-8", errors="replace") if isinstance(t, bytes) else str(t)


def _find_proc_at_line(node: Any, line0: int) -> Any | None:
    """Return the innermost procedure/function AST node that contains line0."""
    if node.type in ("procedure_definition", "function_definition"):
        if node.start_point[0] <= line0 <= node.end_point[0]:
            for child in node.children:
                inner = _find_proc_at_line(child, line0)
                if inner:
                    return inner
            return node
    for child in node.children:
        r = _find_proc_at_line(child, line0)
        if r:
            return r
    return None


def _collect_local_vars(node: Any, up_to_line0: int, result: list[_LocalVar]) -> None:
    """Walk an AST subtree collecting local variable declarations up to up_to_line0."""
    if node.start_point[0] > up_to_line0:
        return

    if node.type == "var_statement":
        # Перем ИмяПерем; — may declare multiple names
        for child in node.children:
            if child.type == "identifier":
                result.append(
                    _LocalVar(
                        name=_ast_node_text(child),
                        kind="var_decl",
                        line=node.start_point[0] + 1,
                        character=child.start_point[1],
                    )
                )

    elif node.type == "for_each_statement":
        # Для Каждого <iterator> Из <collection> Цикл
        # The first identifier child (after FOR/EACH keywords) is the iterator
        saw_each = False
        for child in node.children:
            if child.type == "EACH_KEYWORD":
                saw_each = True
            elif saw_each and child.type == "identifier":
                result.append(
                    _LocalVar(
                        name=_ast_node_text(child),
                        kind="loop_var",
                        line=node.start_point[0] + 1,
                        character=child.start_point[1],
                    )
                )
                break
        # Recurse into loop body
        for child in node.children:
            _collect_local_vars(child, up_to_line0, result)

    elif node.type == "for_statement":
        # Для <var> = <start> По <end> Цикл
        for child in node.children:
            if child.type == "identifier":
                result.append(
                    _LocalVar(
                        name=_ast_node_text(child),
                        kind="loop_var",
                        line=node.start_point[0] + 1,
                        character=child.start_point[1],
                    )
                )
                break
        for child in node.children:
            _collect_local_vars(child, up_to_line0, result)

    elif node.type == "assignment_statement":
        # <target> = <expr>  — first identifier is the assignment target
        target_node = None
        type_hint = ""
        for child in node.children:
            if child.type == "identifier" and target_node is None:
                target_node = child
            elif child.type == "expression":
                for ec in child.children:
                    if ec.type == "new_expression":
                        # Новый TypeName() → type_hint = TypeName
                        for nc in ec.children:
                            if nc.type == "identifier":
                                type_hint = _ast_node_text(nc)
                                break
                    elif ec.type == "call_expression":
                        # Object.Method() → look up return type via AST structure
                        _obj_n = ""
                        _meth_n = ""
                        for mc in ec.children:
                            if mc.type == "access":
                                for ac in mc.children:
                                    if ac.type == "identifier":
                                        _obj_n = _ast_node_text(ac)
                            elif mc.type == "method_call":
                                for mm in mc.children:
                                    if mm.type == "identifier":
                                        _meth_n = _ast_node_text(mm)
                                        break
                        if _obj_n and _meth_n:
                            _obj_type = next(
                                (
                                    v.type_hint
                                    for v in result
                                    if v.name.casefold() == _obj_n.casefold() and v.type_hint
                                ),
                                _obj_n,
                            )
                            _key = f"{_obj_type.casefold()}.{_meth_n.casefold()}"
                            type_hint = _TYPE_RETURN_MAP.get(_key, "")
        if target_node is not None:
            result.append(
                _LocalVar(
                    name=_ast_node_text(target_node),
                    kind="assignment",
                    line=node.start_point[0] + 1,
                    character=target_node.start_point[1],
                    type_hint=type_hint,
                )
            )

    else:
        for child in node.children:
            _collect_local_vars(child, up_to_line0, result)


def _extract_scope_vars_from_proc(proc_node: Any, cursor_line0: int) -> list[_LocalVar]:
    """Extract visible local variables from an already selected procedure/function node."""
    vars: list[_LocalVar] = []

    # 1. Parameters from the procedure/function signature
    for child in proc_node.children:
        if child.type == "parameters":
            for param in child.children:
                if param.type != "parameter":
                    continue
                is_val = any(pc.type == "VAL_KEYWORD" for pc in param.children)
                for pc in param.children:
                    if pc.type == "identifier":
                        vars.append(
                            _LocalVar(
                                name=_ast_node_text(pc),
                                kind="val_parameter" if is_val else "parameter",
                                line=proc_node.start_point[0] + 1,
                                character=pc.start_point[1],
                            )
                        )
                        break

    # 2. Body: Перем, loop vars, assignments up to cursor
    skip_types = frozenset(
        {
            "PROCEDURE_KEYWORD",
            "FUNCTION_KEYWORD",
            "ENDPROCEDURE_KEYWORD",
            "ENDFUNCTION_KEYWORD",
            "EXPORT_KEYWORD",
            "identifier",
            "parameters",
        }
    )
    for child in proc_node.children:
        if child.type not in skip_types:
            _collect_local_vars(child, cursor_line0, vars)

    # Deduplicate: first declaration wins (for Go-to-Definition)
    seen: dict[str, _LocalVar] = {}
    for v in vars:
        if v.line - 1 > cursor_line0:
            continue
        key = v.name.casefold()
        if key not in seen:
            seen[key] = v
    return list(seen.values())


def _extract_scope_vars(tree: Any, cursor_line0: int) -> list[_LocalVar]:
    """Extract local variables visible at cursor_line0 (0-based row).

    Finds the enclosing procedure/function, then collects:
    - parameters (with Знач/Val distinction)
    - Перем declarations
    - loop iterators (Для Каждого/Для)
    - assignment targets (А = ...)
    Only returns declarations at or before cursor_line0.
    Results are deduplicated by name (first occurrence wins for navigation).
    """
    root = getattr(tree, "root_node", None)
    if root is None:
        return []
    # Only works with real tree-sitter trees (bytes text)
    if not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []

    proc_node = _find_proc_at_line(root, cursor_line0)
    if proc_node is None:
        return []
    return _extract_scope_vars_from_proc(proc_node, cursor_line0)


def _iter_proc_nodes(node: Any) -> list[Any]:
    """Return all procedure/function nodes under *node* without descending into nested routines."""
    out: list[Any] = []
    node_type = getattr(node, "type", None)
    if node_type in ("procedure_definition", "function_definition"):
        out.append(node)
        return out
    for child in getattr(node, "children", []) or []:
        out.extend(_iter_proc_nodes(child))
    return out


def _content_cache_key(content: str) -> int:
    """Return the in-process cache key for an open document snapshot."""
    return hash(content)


def _build_lsp_document_context(
    content: str,
    uri: str,
    *,
    parser: BslParser | None = None,
    source_path: str | None = None,
) -> _LspDocumentContext:
    """Parse a document once and materialise reusable LSP semantic state."""
    snapshot = build_document_snapshot(
        path=source_path or uri,
        content=content,
        parser=parser or BslParser(),
    )
    root = snapshot.root_node
    scopes: list[_LocalScopeProc] = []
    if root is not None:
        for proc_node in _iter_proc_nodes(root):
            end_line0 = proc_node.end_point[0]
            scopes.append(
                _LocalScopeProc(
                    start_line0=proc_node.start_point[0],
                    end_line0=end_line0,
                    vars=_extract_scope_vars_from_proc(proc_node, end_line0),
                )
            )
    return _LspDocumentContext(
        content_hash=_content_cache_key(content),
        snapshot=snapshot,
        local_scopes=scopes,
    )


def _get_lsp_document_context(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    *,
    allow_sync_build: bool = True,
    source_path: str | None = None,
) -> _LspDocumentContext | None:
    """Return cached or freshly built semantic context for an LSP document."""
    content_hash = _content_cache_key(content)
    with ls._parsed_doc_cache_lock:
        cached = ls._parsed_doc_cache.get(uri)
        if isinstance(cached, _LspDocumentContext) and cached.content_hash == content_hash:
            if source_path is not None:
                cached.snapshot.path = source_path
            return cached
        if not allow_sync_build:
            return None

    context = _build_lsp_document_context(
        content,
        uri,
        parser=ls._thread_bsl_parser(),
        source_path=source_path,
    )
    with ls._parsed_doc_cache_lock:
        latest = ls._parsed_doc_cache.get(uri)
        if isinstance(latest, _LspDocumentContext) and latest.content_hash == content_hash:
            return latest
        if ls._doc_get(uri) == content:
            ls._parsed_doc_cache[uri] = context
            return context
    return context


def _clear_local_scope_cache(ls: BslLanguageServer, uri: str) -> None:
    """Drop cached local scopes for a closed or small document."""
    with ls._parsed_doc_cache_lock:
        ls._parsed_doc_cache.pop(uri, None)
        ls._parsed_doc_cache_versions.pop(uri, None)


def _schedule_local_scope_cache(ls: BslLanguageServer, uri: str, content: str) -> None:
    """Build local scope data in the background for large documents only."""
    if _allow_sync_local_scope_parse(content):
        _clear_local_scope_cache(ls, uri)
        return
    if len(content.encode("utf-8", errors="ignore")) > _BACKGROUND_LOCAL_SCOPE_PARSE_MAX_BYTES:
        _clear_local_scope_cache(ls, uri)
        return

    with ls._parsed_doc_cache_lock:
        version = ls._parsed_doc_cache_versions.get(uri, 0) + 1
        ls._parsed_doc_cache_versions[uri] = version
        ls._parsed_doc_cache.pop(uri, None)

    def _worker() -> None:
        try:
            cache = _build_lsp_document_context(content, uri)
        except Exception:
            logger.debug("LSP: parsed document cache build failed for %s", uri, exc_info=True)
            return
        with ls._parsed_doc_cache_lock:
            if ls._parsed_doc_cache_versions.get(uri) == version and ls._doc_get(uri) == content:
                ls._parsed_doc_cache[uri] = cache
            else:
                return
        _compute_cached_code_lens_metrics(ls, uri, content, version)

    threading.Thread(target=_worker, daemon=True, name="bsl-parsed-document-cache").start()


def _cached_scope_vars(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    cursor_line0: int,
) -> list[_LocalVar] | None:
    """Return cached visible locals for a large document, or None while cache is not ready."""
    cache = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
    )
    if cache is None or cache.content_hash != _content_cache_key(content):
        return None
    for scope in cache.local_scopes:
        if scope.start_line0 <= cursor_line0 <= scope.end_line0:
            seen: dict[str, _LocalVar] = {}
            for var in scope.vars:
                if var.line - 1 > cursor_line0:
                    continue
                key = var.name.casefold()
                if key not in seen:
                    seen[key] = var
            return list(seen.values())
    return []


def _cached_parse_tree(ls: BslLanguageServer, uri: str, content: str) -> Any | None:
    """Return a cached parse tree for a document when available."""
    cache = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
    )
    if cache is None or cache.content_hash != _content_cache_key(content):
        return None
    return cache.tree


def _cached_type_engine(
    ls: BslLanguageServer,
    uri: str,
    content: str,
) -> BslTypeEngine | None:
    """Return a cached type engine for the current document context."""
    cache = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
    )
    if cache is None:
        return None
    if cache.type_engine is not None:
        return cache.type_engine
    engine = BslTypeEngine(cache.tree)
    with ls._parsed_doc_cache_lock:
        latest = ls._parsed_doc_cache.get(uri)
        if isinstance(latest, _LspDocumentContext) and latest.content_hash == cache.content_hash:
            latest.type_engine = engine
            return engine
    return engine


def _compute_cached_code_lens_metrics(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    version: int | None = None,
) -> list[_CodeLensMetric] | None:
    """Compute and store code-lens complexity metrics for a cached large document."""
    with ls._parsed_doc_cache_lock:
        cache = ls._parsed_doc_cache.get(uri)
        current_version = ls._parsed_doc_cache_versions.get(uri)
    if not isinstance(cache, _LspDocumentContext) or cache.content_hash != _content_cache_key(
        content
    ):
        return None
    if version is not None and current_version != version:
        return None
    if cache.code_lens_metrics is not None:
        return cache.code_lens_metrics

    snapshot = cache.snapshot
    procs = snapshot.procedures
    complexity_metrics = snapshot.complexity_metrics_for_procs(procs)
    metrics = [
        _CodeLensMetric(line0=proc.start_idx, cognitive=cognitive, mccabe=mccabe)
        for proc, (cognitive, mccabe) in zip(procs, complexity_metrics, strict=False)
    ]

    with ls._parsed_doc_cache_lock:
        latest = ls._parsed_doc_cache.get(uri)
        if (
            isinstance(latest, _LspDocumentContext)
            and latest.content_hash == _content_cache_key(content)
            and (version is None or ls._parsed_doc_cache_versions.get(uri) == version)
        ):
            latest.code_lens_metrics = metrics
            return metrics
    return None


def _cached_folding_ranges(
    ls: BslLanguageServer,
    uri: str,
    content: str,
) -> list[FoldingRange] | None:
    """Return AST folding ranges cached on the shared document context."""
    cache = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
    )
    if cache is None:
        return None
    if cache.folding_ranges is not None:
        return list(cache.folding_ranges)

    ranges: list[FoldingRange] = []
    try:
        _collect_ast_fold_ranges(cache.snapshot.root_node, ranges)
    except Exception:
        return None
    with ls._parsed_doc_cache_lock:
        latest = ls._parsed_doc_cache.get(uri)
        if isinstance(latest, _LspDocumentContext) and latest.content_hash == cache.content_hash:
            latest.folding_ranges = ranges
    return list(ranges)


def _make_snippet(label: str, signature: str | None) -> tuple[str, InsertTextFormat]:
    """Build a snippet insert text for function/procedure/method items.

    E.g. 'Найти(Знач, Кол?)' → 'Найти(${1:Знач}, ${2:Кол?})$0'
    """
    import re

    if not signature:
        return label, InsertTextFormat.PlainText
    m = re.search(r"\(([^)]*)\)", signature)
    if not m or not m.group(1).strip():
        return f"{label}()$0", InsertTextFormat.Snippet
    params = [p.strip() for p in split_commas_outside_double_quotes(m.group(1))]
    snippet_params = ", ".join(f"${{{i + 1}:{p}}}" for i, p in enumerate(params))
    return f"{label}({snippet_params})$0", InsertTextFormat.Snippet


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


def _left_word_at_position(content: str, line: int, character: int) -> str:
    """Extract the identifier immediately to the LEFT of the dot before `character`.

    For `Объект.Метод(` with cursor on «Метод», returns «Объект».
    Returns empty string if there is no dot-separated left-hand identifier.
    """
    lines = content.splitlines()
    if line >= len(lines):
        return ""
    text = lines[line]

    # Find start of the current word
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1

    # Check that the character right before start is a dot
    if start == 0 or text[start - 1] != ".":
        return ""

    # Walk left past the dot to extract the previous identifier
    dot_pos = start - 1
    lend = dot_pos
    lstart = lend
    while lstart > 0 and (text[lstart - 1].isalnum() or text[lstart - 1] == "_"):
        lstart -= 1

    return text[lstart:lend]


def _word_range_at_position(content: str, line: int, character: int) -> Range:
    """Return the LSP Range that covers the identifier at the given position.

    Used as ``originSelectionRange`` in LocationLink so VSCode highlights the
    call-site word when the user invokes Go-to-Definition / Peek Definition.
    """
    lines = content.splitlines()
    if line >= len(lines):
        return Range(
            start=Position(line=line, character=character),
            end=Position(line=line, character=character),
        )
    text = lines[line]
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return Range(start=Position(line=line, character=start), end=Position(line=line, character=end))


# ---------------------------------------------------------------------------
# Code Formatting
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Code Lens — cognitive / cyclomatic complexity above each procedure
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_CODE_LENS)
def on_code_lens(ls: BslLanguageServer, params: CodeLensParams) -> list[CodeLens] | None:
    """Return code lenses showing cognitive and cyclomatic complexity above each method."""
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None
    cached_metrics = _compute_cached_code_lens_metrics(ls, uri, content)
    if cached_metrics is not None:
        result: list[CodeLens] = []
        for metric in cached_metrics:
            r = Range(
                start=Position(line=metric.line0, character=0),
                end=Position(line=metric.line0, character=0),
            )
            result.append(
                CodeLens(
                    range=r,
                    command=Command(title=f"Когнитивная сложность: {metric.cognitive}", command=""),
                )
            )
            result.append(
                CodeLens(
                    range=r,
                    command=Command(
                        title=f"Цикломатическая сложность: {metric.mccabe}", command=""
                    ),
                )
            )
        return result or None

    try:
        cache = _get_lsp_document_context(
            ls,
            uri,
            content,
            allow_sync_build=_allow_sync_local_scope_parse(content),
        )
        if cache is None:
            return None
        snapshot = cache.snapshot
        procs = snapshot.procedures
        complexity_metrics = snapshot.complexity_metrics_for_procs(procs)
    except Exception:
        return None

    result: list[CodeLens] = []
    for proc, (cc, mc) in zip(procs, complexity_metrics, strict=False):
        line = proc.start_idx  # 0-based header line
        r = Range(start=Position(line=line, character=0), end=Position(line=line, character=0))
        # Cognitive complexity lens
        cc_label = f"Когнитивная сложность: {cc}"
        result.append(CodeLens(range=r, command=Command(title=cc_label, command="")))
        # Cyclomatic complexity lens
        mc_label = f"Цикломатическая сложность: {mc}"
        result.append(CodeLens(range=r, command=Command(title=mc_label, command="")))
    return result or None


# ---------------------------------------------------------------------------
# Code Formatting
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_FORMATTING)
def on_formatting(ls: BslLanguageServer, params: DocumentFormattingParams) -> list[TextEdit] | None:
    """Format the entire document."""
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None
    indent_size = params.options.tab_size if params.options else 4
    insert_spaces = _resolve_insert_spaces(params.options)
    try:
        formatted = default_formatter.format(
            content,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
        )
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
    content = ls._doc_get(uri, "")
    if not content:
        return None
    indent_size = params.options.tab_size if params.options else 4
    insert_spaces = _resolve_insert_spaces(params.options)
    r = params.range
    start_line = max(0, int(r.start.line))
    end_line = max(0, int(r.end.line))
    # LSP range end is exclusive. For line-based replacement this means:
    # if end is at column 0 on a later line, that line is not part of selection.
    if end_line > start_line and int(r.end.character) == 0:
        end_line -= 1
    if end_line < start_line:
        return []

    original_lines = content.splitlines()
    original_slice = "\n".join(original_lines[start_line : end_line + 1]) + "\n"
    try:
        formatted_range = default_formatter.format_range(
            content,
            start_line=start_line,
            end_line=end_line,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
        )
    except Exception as exc:
        logger.error("LSP: range formatting failed for %s: %s", uri, exc)
        return None
    if formatted_range == original_slice:
        return []
    return [
        TextEdit(
            range=Range(
                start=Position(line=start_line, character=0),
                end=Position(line=end_line + 1, character=0),
            ),
            new_text=formatted_range,
        )
    ]


# ---------------------------------------------------------------------------
# On-type formatting (auto-indent on Enter)
# ---------------------------------------------------------------------------


@server.feature(
    TEXT_DOCUMENT_ON_TYPE_FORMATTING,
    DocumentOnTypeFormattingOptions(first_trigger_character="\n"),
)
def on_type_formatting(
    ls: BslLanguageServer, params: DocumentOnTypeFormattingParams
) -> list[TextEdit] | None:
    """Auto-indent the new line when the user presses Enter.

    Computes the correct BSL indent level using the formatter's internal
    ``_indent_at`` logic (respects Процедура/КонецПроцедуры, Если/КонецЕсли, etc.)
    and returns a single TextEdit that replaces the line's leading whitespace.
    """
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None

    indent_size = (params.options.tab_size if params.options else None) or 4
    insert_spaces = _resolve_insert_spaces(params.options)
    lines = content.splitlines()

    # position.line is the newly-created line (where the cursor landed after Enter).
    new_line_idx = params.position.line
    if new_line_idx <= 0 or new_line_idx > len(lines):
        return None

    # Compute expected indent level for the new line (full document AST + continuation)
    effective_insert = (
        insert_spaces
        if insert_spaces is not None
        else default_formatter._default_insert_spaces(None)
    )
    indent_level = default_formatter._indent_at(
        lines,
        new_line_idx,
        indent_size,
        insert_spaces=effective_insert,
        full_text=content,
    )

    # If the new line already contains a keyword that dedents (КонецЕсли, Иначе, …),
    # reduce the indent level by one so the keyword aligns with its opener
    current_line = lines[new_line_idx] if new_line_idx < len(lines) else ""
    stripped = current_line.lstrip()
    if stripped:
        first_kw = _get_stripped_keyword(stripped)
        if first_kw in _DEDENT_BEFORE:
            indent_level = max(0, indent_level - 1)

    wanted = (" " * (indent_level * indent_size)) if effective_insert else ("\t" * indent_level)

    # Current leading whitespace on the new line
    current_indent_len = len(current_line) - len(stripped) if stripped else len(current_line)
    current_indent = current_line[:current_indent_len]

    if current_indent == wanted:
        return []  # already correct — nothing to do

    return [
        TextEdit(
            range=Range(
                start=Position(line=new_line_idx, character=0),
                end=Position(line=new_line_idx, character=current_indent_len),
            ),
            new_text=wanted,
        )
    ]


def _resolve_insert_spaces(options: Any) -> bool | None:
    """Return ``textDocument/formatting`` insertSpaces when the client sent it.

    ``None`` means: let :class:`~onec_hbk_bsl.analysis.formatter.BslFormatter`
    pick the default for the BSLLS-compatible formatter (tabs, same as BSLLS CLI
    and :file:`vscode-extension/package.json` ``[bsl].editor.insertSpaces`` false).
    """
    if options is None:
        return None
    value = getattr(options, "insert_spaces", None)
    if isinstance(value, bool):
        return value
    return None


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
    content = ls._doc_get(uri, "")
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
#
# Uses tree-sitter AST so multi-line conditions like
#   Если А = 1
#       Или Б = 2 Тогда          ← Тогда on different line than Если
# are correctly folded. Regex-based approach fails for these.
#
# #Область / #КонецОбласти are separate preprocessor nodes in the AST
# (not parent-child), so they are matched with a regex stack pass.

_REGION_PREPROC_OPEN_RE = _re.compile(r"^\s*#(?:Область|Region)\b", _re.IGNORECASE)
_REGION_PREPROC_CLOSE_RE = _re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", _re.IGNORECASE)

# AST node types that map to code-fold ranges (start_point → end_point)
_FOLD_AST_TYPES = frozenset(
    {
        "procedure_definition",
        "function_definition",
        "if_statement",
        "while_statement",
        "for_statement",
        "for_each_statement",
        "try_statement",
    }
)


def _collect_ast_fold_ranges(node: Any, ranges: list[FoldingRange]) -> None:
    """Walk tree-sitter AST and collect folding ranges for block nodes."""
    if node.type in _FOLD_AST_TYPES:
        start = node.start_point[0]  # 0-based row
        end = node.end_point[0]
        if end > start:
            ranges.append(FoldingRange(start_line=start, end_line=end, kind=None))
    for child in node.children:
        _collect_ast_fold_ranges(child, ranges)


@server.feature(TEXT_DOCUMENT_FOLDING_RANGE)
def on_folding_range(
    ls: BslLanguageServer, params: FoldingRangeParams
) -> list[FoldingRange] | None:
    """Return folding ranges for BSL block structures using the AST."""
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None

    # 1. AST-based ranges (handles multi-line conditions correctly)
    ranges = _cached_folding_ranges(ls, uri, content) or []

    # 2. #Область / #КонецОбласти — preprocessor nodes are siblings in AST,
    #    so match them with a line-by-line stack pass (faster than AST walk).
    lines = content.splitlines()
    region_stack: list[int] = []
    for idx, line in enumerate(lines):
        if _REGION_PREPROC_OPEN_RE.match(line):
            region_stack.append(idx)
        elif _REGION_PREPROC_CLOSE_RE.match(line) and region_stack:
            start = region_stack.pop()
            if idx > start:
                ranges.append(
                    FoldingRange(
                        start_line=start,
                        end_line=idx,
                        kind=FoldingRangeKind.Region,
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

# Longer keywords first (e.g. ИЛИ before И). BSL is case-insensitive — use IGNORECASE.
_ST_KEYWORD_RE = _re.compile(
    r"(?<![А-ЯЁа-яёA-Za-z_\d])("
    r"Процедура|КонецПроцедуры|Функция|КонецФункции"
    r"|Если|ИначеЕсли|Иначе|КонецЕсли|Тогда"
    r"|Для|Каждого|Из|По|Пока|Цикл|КонецЦикла"
    r"|Попытка|Исключение|КонецПопытки"
    r"|Возврат|Прервать|Продолжить|Новый|Перем|Знач|Экспорт"
    r"|Истина|Ложь|Неопределено|Null"
    r"|ИЛИ|И|НЕ"
    r"|Procedure|EndProcedure|Function|EndFunction"
    r"|If|ElsIf|Else|EndIf|Then"
    r"|For|Each|In|To|While|Do|EndDo"
    r"|Try|Except|EndTry"
    r"|Return|Break|Continue|New|Var|Val|Export"
    r"|True|False|Undefined|And|Or|Not"
    r")(?![А-ЯЁа-яёA-Za-z_\d])",
    _re.UNICODE | _re.IGNORECASE,
)
_ST_NUMBER_RE = _re.compile(r"\b\d+(?:\.\d+)?\b")
_ST_STRING_RE = _re.compile(r'"[^"]*"')
_ST_COMMENT_RE = _re.compile(r"//.*$")
_ST_CALL_RE = _re.compile(r"([А-ЯЁа-яёA-Za-z_]\w*)\s*\(", _re.UNICODE)
# Line-start preprocessor (same scope as TextMate keyword.other.preprocessor.bsl)
_ST_PREPROCESSOR_LINE_RE = _re.compile(
    r"^\s*#("
    r"Если|If|ИначеЕсли|ElsIf|Иначе|Else|КонецЕсли|EndIf|"
    r"Область|Region|КонецОбласти|EndRegion|"
    r"Использовать|Use|Удаление|Delete|КонецУдаления|EndDelete|"
    r"Вставка|Insert|КонецВставки|EndInsert"
    r")\b",
    _re.IGNORECASE | _re.UNICODE,
)


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
    content = ls._doc_get(uri, "")
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

        # Preprocessor (#Если / #Область / …) — keyword styling
        for m in _ST_PREPROCESSOR_LINE_RE.finditer(line_text):
            if m.start() >= comment_start:
                continue
            tokens.append((m.start(), len(m.group()), _ST_KEYWORD))

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
def on_inlay_hint(ls: BslLanguageServer, params: InlayHintParams) -> list[InlayHint] | None:
    """Show parameter name hints at function call sites."""
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None

    r = params.range
    lines = content.splitlines()
    hints: list[InlayHint] = []

    # Pattern: identifier followed by '(' — find calls and match to known symbols
    call_re = _re.compile(r"([А-ЯЁа-яёA-Za-z_]\w*)\s*\(([^)]*)\)", _re.UNICODE)

    _decl_before_name = _re.compile(
        r"(?:Процедура|Функция|Procedure|Function)\s*$",
        _re.IGNORECASE,
    )

    for line_idx in range(r.start.line, min(r.end.line + 1, len(lines))):
        line_text = lines[line_idx]
        for m in call_re.finditer(line_text):
            # Declaration line: Имя(...) lists parameters, not call arguments — skip inlays.
            prefix_before_name = line_text[: m.start(1)].rstrip()
            if _decl_before_name.search(prefix_before_name):
                continue

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
                parameter_name_from_declaration_fragment(p)
                for p in split_commas_outside_double_quotes(params_str)
                if p.strip()
            ]
            param_names = [n for n in param_names if n]
            if not param_names:
                continue

            # Split args by comma keeping raw (unstripped) chunks to track real offsets
            raw_args = split_commas_outside_double_quotes(m.group(2))

            # Emit hint for each positional arg.
            # Track offset in the raw group(2) text to correctly handle ", " separators
            # and multi-byte Cyrillic characters (Python len() counts code points, matching
            # LSP UTF-16 for BMP characters).
            arg_start = m.start(2)
            pos_in_raw = 0
            for i, raw_arg in enumerate(raw_args):
                if i >= len(param_names):
                    break
                arg_stripped = raw_arg.strip()
                leading = len(raw_arg) - len(raw_arg.lstrip())
                param_name = param_names[i]
                if not param_name or param_name.casefold() == arg_stripped.casefold():
                    pos_in_raw += len(raw_arg) + 1  # +1 for ','
                    continue
                char = arg_start + pos_in_raw + leading
                hints.append(
                    InlayHint(
                        position=Position(line=line_idx, character=char),
                        label=f"{param_name}:",
                        kind=InlayHintKind.Parameter,
                        padding_right=True,
                    )
                )
                pos_in_raw += len(raw_arg) + 1  # +1 for ','

    return hints if hints else None


# ---------------------------------------------------------------------------
# Signature Help (parameter list on call sites)
# ---------------------------------------------------------------------------


def _count_commas_outside_strings(text: str) -> int:
    """Count commas not inside double-quoted string literals."""
    in_string = False
    commas = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == ",":
            commas += 1
        i += 1
    return commas


def _parse_signature_params(sig: str | None) -> list[str]:
    if not sig:
        return []
    m = _re.search(r"\(([^)]*)\)", sig)
    if not m:
        return []
    inside = m.group(1).strip()
    if not inside:
        return []
    return [p.strip() for p in split_commas_outside_double_quotes(inside) if p.strip()]


def _param_label(param: str) -> str:
    return parameter_name_from_declaration_fragment(param)


@server.feature(TEXT_DOCUMENT_SIGNATURE_HELP)
def on_signature_help(ls: BslLanguageServer, params: SignatureHelpParams) -> SignatureHelp | None:
    """Show signature and active parameter for the call under the cursor."""
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    if not content:
        return None

    pos = params.position
    lines = content.splitlines()
    if pos.line >= len(lines):
        return None

    line_text = lines[pos.line]
    cursor_char = min(pos.character, len(line_text))
    before_cursor = line_text[:cursor_char]

    # Find the last simple call name directly before the cursor on the same line.
    call_re = _re.compile(r"([А-ЯЁа-яёA-Za-z_]\w*)\s*\(")
    matches = list(call_re.finditer(before_cursor))
    if not matches:
        return None
    m = matches[-1]
    func_name = m.group(1)
    open_paren_idx = m.end() - 1  # points to '('

    args_before = line_text[open_paren_idx + 1 : cursor_char]
    comma_count = _count_commas_outside_strings(args_before)
    active_param = comma_count

    # Resolve signature (workspace first, then platform API).
    sym = ls.symbol_index.find_symbol(func_name, limit=1)
    signature_text: str | None = None
    doc: str | None = None
    if sym:
        signature_text = sym[0].get("signature") or ""
        doc = sym[0].get("doc_comment") or None
    else:
        api_method = ls.platform_api.find_global(func_name)
        if api_method:
            signature_text = getattr(api_method, "signature", None) or ""
            doc = getattr(api_method, "description", None) or None

    param_defs = _parse_signature_params(signature_text)
    param_labels = [_param_label(p) for p in param_defs]
    param_labels = [pl for pl in param_labels if pl]
    param_infos = [ParameterInformation(label=pl) for pl in param_labels]

    if param_infos:
        active_param = min(max(active_param, 0), len(param_infos) - 1)
    else:
        active_param = 0

    signature_info = SignatureInformation(
        label=f"{func_name}",
        documentation=doc or None,
        parameters=param_infos or None,
        active_parameter=active_param,
    )

    return SignatureHelp(
        signatures=[signature_info],
        active_signature=0,
        active_parameter=active_param,
    )


# ---------------------------------------------------------------------------
# Code Actions (quick fixes from diagnostics)
# ---------------------------------------------------------------------------

# Map diagnostic code → fix description
# ---------------------------------------------------------------------------
# Reverse BSLLS name map: BSL code → BSLLS name (for suppression comments)
# ---------------------------------------------------------------------------


def _build_code_to_bslls() -> dict[str, str]:
    try:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE

        result: dict[str, str] = {}
        for name, code in _BSLLS_NAME_TO_CODE.items():
            if code not in result:
                result[code] = name
        return result
    except Exception:
        return {}


_CODE_TO_BSLLS_NAME: dict[str, str] = _build_code_to_bslls()


def _fix_bsl024_space_after_double_slash(line: str) -> str | None:
    """
    Insert a space after ``//`` when BSL024 would fire (same conditions as the rule).

    Returns the full replacement line, or None if no fix applies.
    """
    from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import (
        bsl024_find_report_comment_col,
    )

    col = bsl024_find_report_comment_col(line)
    if col is None:
        return None
    return line[: col + 2] + " " + line[col + 2 :]


def _selection_range_is_empty(rng: Range) -> bool:
    return rng.start.line == rng.end.line and rng.start.character == rng.end.character


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _selected_text_from_range(lines: list[str], rng: Range) -> str:
    start_line = int(rng.start.line)
    end_line = int(rng.end.line)
    start_char = int(rng.start.character)
    end_char = int(rng.end.character)
    if start_line < 0 or start_line >= len(lines) or end_line < start_line:
        return ""
    if end_line >= len(lines):
        end_line = len(lines) - 1
        end_char = len(lines[end_line])
    if start_line == end_line:
        return lines[start_line][start_char:end_char]
    selected = [lines[start_line][start_char:]]
    selected.extend(lines[start_line + 1 : end_line])
    if end_char > 0:
        selected.append(lines[end_line][:end_char])
    return "\n".join(selected)


def _build_extract_procedure_action(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    rng: Range,
) -> CodeAction | None:
    if not content or _selection_range_is_empty(rng):
        return None
    lines = content.splitlines()
    selected = _selected_text_from_range(lines, rng).strip("\n")
    if not selected.strip():
        return None

    start_line = int(rng.start.line)
    context = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
        source_path=_uri_to_path(uri),
    )
    if context is None or getattr(context.tree, "root_node", None) is None:
        return None
    proc_node = _find_proc_at_line(context.tree.root_node, start_line)
    if proc_node is None:
        return None

    insert_line = min(proc_node.end_point[0] + 1, len(lines))
    call_indent = _line_indent(lines[start_line]) if 0 <= start_line < len(lines) else ""
    body_lines = selected.splitlines()
    body_indent = _line_indent(body_lines[0]) if body_lines else ""
    if body_indent and all(
        (not line.strip()) or line.startswith(body_indent) for line in body_lines
    ):
        body_lines = [
            line[len(body_indent) :] if line.startswith(body_indent) else line
            for line in body_lines
        ]
    body = "\n".join(f"\t{line}" if line.strip() else "" for line in body_lines)
    procedure_name = "ИзвлеченныйФрагмент"
    procedure_text = f"\nПроцедура {procedure_name}()\n{body}\nКонецПроцедуры\n"

    return CodeAction(
        title="Извлечь в процедуру",
        kind=CodeActionKind.RefactorExtract,
        edit=WorkspaceEdit(
            changes={
                uri: [
                    TextEdit(range=rng, new_text=f"{call_indent}{procedure_name}();"),
                    TextEdit(
                        range=Range(
                            start=Position(line=insert_line, character=0),
                            end=Position(line=insert_line, character=0),
                        ),
                        new_text=procedure_text,
                    ),
                ]
            }
        ),
    )


def _build_extract_function_action(
    ls: BslLanguageServer,
    uri: str,
    content: str,
    rng: Range,
) -> CodeAction | None:
    if not content or _selection_range_is_empty(rng):
        return None
    lines = content.splitlines()
    selected = _selected_text_from_range(lines, rng).strip()
    if not selected or "\n" in selected or selected.endswith(";"):
        return None

    start_line = int(rng.start.line)
    context = _get_lsp_document_context(
        ls,
        uri,
        content,
        allow_sync_build=_allow_sync_local_scope_parse(content),
        source_path=_uri_to_path(uri),
    )
    if context is None or getattr(context.tree, "root_node", None) is None:
        return None
    proc_node = _find_proc_at_line(context.tree.root_node, start_line)
    if proc_node is None:
        return None

    insert_line = min(proc_node.end_point[0] + 1, len(lines))
    function_name = "ИзвлеченнаяФункция"
    function_text = f"\nФункция {function_name}()\n\tВозврат {selected};\nКонецФункции\n"
    return CodeAction(
        title="Извлечь в функцию",
        kind=CodeActionKind.RefactorExtract,
        edit=WorkspaceEdit(
            changes={
                uri: [
                    TextEdit(range=rng, new_text=f"{function_name}()"),
                    TextEdit(
                        range=Range(
                            start=Position(line=insert_line, character=0),
                            end=Position(line=insert_line, character=0),
                        ),
                        new_text=function_text,
                    ),
                ]
            }
        ),
    )


@server.feature(TEXT_DOCUMENT_CODE_ACTION)
def on_code_action(ls: BslLanguageServer, params: CodeActionParams) -> list[CodeAction] | None:
    """
    Возвращает действия быстрого исправления для диагностик в указанном диапазоне.

    Для каждой диагностики предлагается:
    1. Игнорировать строку — добавляет // noqa: BSLxxx в конец строки
    2. Игнорировать правило в блоке — оборачивает строку // BSLLS:Name-off / -on
    3. Игнорировать правило во всём файле — добавляет // BSLLS:Name-off в начало файла
    Дополнительно: Переформатировать документ (если он не в нормальной форме)
    """
    actions: list[CodeAction] = []
    uri = params.text_document.uri
    content = ls._doc_get(uri, "")
    doc_lines = content.splitlines()

    if content and isinstance(params.range, Range):
        extract_action = _build_extract_procedure_action(ls, uri, content, params.range)
        if extract_action is not None:
            actions.append(extract_action)
        extract_function_action = _build_extract_function_action(ls, uri, content, params.range)
        if extract_function_action is not None:
            actions.append(extract_function_action)

    for diag in params.context.diagnostics:
        code = _internal_rule_code_from_lsp_diagnostic(diag)
        try:
            diag_line = int(diag.range.start.line)
        except (TypeError, ValueError):
            continue

        if 0 <= diag_line < len(doc_lines):
            line_text = doc_lines[diag_line]
            line_end_char = len(line_text)
            # Match diagnostic line indent (tabs/spaces as in source), not N spaces.
            pad = line_text[: len(line_text) - len(line_text.lstrip())]
            rule = get_rule(code)
            display_name = rule.description or rule.name or code

            # ── 1. Игнорировать строку (noqa) ──────────────────────────────
            # If the line already has a noqa comment, append the code to it.
            _noqa_existing = _re.search(r"//\s*noqa:\s*([\w,\s]+?)\s*$", line_text, _re.IGNORECASE)
            if _noqa_existing and code:
                _existing_codes = [c.strip() for c in _noqa_existing.group(1).split(",")]
                if code not in _existing_codes:
                    _new_comment = f"  // noqa: {', '.join(_existing_codes + [code])}"
                    actions.append(
                        CodeAction(
                            title=f"Добавить {code} к noqa-комментарию",
                            kind=CodeActionKind.QuickFix,
                            diagnostics=[diag],
                            edit=WorkspaceEdit(
                                changes={
                                    uri: [
                                        TextEdit(
                                            range=Range(
                                                start=Position(
                                                    line=diag_line, character=_noqa_existing.start()
                                                ),
                                                end=Position(
                                                    line=diag_line, character=line_end_char
                                                ),
                                            ),
                                            new_text=_new_comment,
                                        )
                                    ]
                                }
                            ),
                        )
                    )
            else:
                noqa_suffix = f"  // noqa: {code}" if code else "  // noqa"
                noqa_title = (
                    f"Игнорировать строку — {display_name}"
                    if display_name != code
                    else f"Игнорировать строку ({code})"
                )
                actions.append(
                    CodeAction(
                        title=noqa_title,
                        kind=CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=WorkspaceEdit(
                            changes={
                                uri: [
                                    TextEdit(
                                        range=Range(
                                            start=Position(line=diag_line, character=line_end_char),
                                            end=Position(line=diag_line, character=line_end_char),
                                        ),
                                        new_text=noqa_suffix,
                                    )
                                ]
                            }
                        ),
                    )
                )

            # ── 2. Обернуть правило BSLLS-off / -on ────────────────────────
            bslls_name = _CODE_TO_BSLLS_NAME.get(code)
            if bslls_name:
                insert_before = Position(line=diag_line, character=0)
                # For the last line of the file, append to the current line
                if diag_line + 1 >= len(doc_lines):
                    after_range = Range(
                        start=Position(line=diag_line, character=line_end_char),
                        end=Position(line=diag_line, character=line_end_char),
                    )
                    after_new_text = f"\n{pad}// BSLLS:{bslls_name}-on"
                else:
                    after_range = Range(
                        start=Position(line=diag_line + 1, character=0),
                        end=Position(line=diag_line + 1, character=0),
                    )
                    after_new_text = f"{pad}// BSLLS:{bslls_name}-on\n"
                actions.append(
                    CodeAction(
                        title=f"Отключить «{display_name}» для этой строки (BSLLS-off/on)",
                        kind=CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=WorkspaceEdit(
                            changes={
                                uri: [
                                    TextEdit(
                                        range=Range(start=insert_before, end=insert_before),
                                        new_text=f"{pad}// BSLLS:{bslls_name}-off\n",
                                    ),
                                    TextEdit(range=after_range, new_text=after_new_text),
                                ]
                            }
                        ),
                    )
                )

                # ── 3. Отключить правило во всём файле ─────────────────────
                actions.append(
                    CodeAction(
                        title=f"Отключить «{display_name}» в этом файле (BSLLS-off)",
                        kind=CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=WorkspaceEdit(
                            changes={
                                uri: [
                                    TextEdit(
                                        range=Range(
                                            start=Position(line=0, character=0),
                                            end=Position(line=0, character=0),
                                        ),
                                        new_text=f"// BSLLS:{bslls_name}-off\n",
                                    )
                                ]
                            }
                        ),
                    )
                )

            # ── BSL065: вставить блок описания экспортного метода ─────────────
            if code == "BSL065":
                doc_fix = _generate_doc_comment_at_line(ls, uri, content, diag_line)
                if doc_fix:
                    actions.append(
                        CodeAction(
                            title="Вставить описание экспортного метода (// …)",
                            kind=CodeActionKind.QuickFix,
                            diagnostics=[diag],
                            edit=WorkspaceEdit(
                                changes={
                                    uri: [
                                        TextEdit(
                                            range=Range(
                                                start=Position(line=diag_line, character=0),
                                                end=Position(line=diag_line, character=0),
                                            ),
                                            new_text=doc_fix,
                                        )
                                    ]
                                }
                            ),
                        )
                    )

            # ── BSL024: пробел после // (как в правиле SpaceAtStartComment) ──
            if code == "BSL024":
                fixed_line = _fix_bsl024_space_after_double_slash(line_text)
                if fixed_line is not None and fixed_line != line_text:
                    actions.append(
                        CodeAction(
                            title="Вставить пробел после «//» (BSL024)",
                            kind=CodeActionKind.QuickFix,
                            diagnostics=[diag],
                            edit=WorkspaceEdit(
                                changes={
                                    uri: [
                                        TextEdit(
                                            range=Range(
                                                start=Position(line=diag_line, character=0),
                                                end=Position(
                                                    line=diag_line, character=line_end_char
                                                ),
                                            ),
                                            new_text=fixed_line,
                                        )
                                    ]
                                }
                            ),
                        )
                    )

    # ── 4. Сгенерировать комментарий к методу ──────────────────────────────
    try:
        cursor_line = int(params.range.start.line)
    except (TypeError, ValueError, AttributeError):
        cursor_line = -1
    if 0 <= cursor_line < len(doc_lines):
        doc_block = _generate_doc_comment_at_line(ls, uri, content, cursor_line)
        if doc_block:
            actions.append(
                CodeAction(
                    title="Сгенерировать комментарий к методу",
                    kind=CodeActionKind.RefactorRewrite,
                    edit=WorkspaceEdit(
                        changes={
                            uri: [
                                TextEdit(
                                    range=Range(
                                        start=Position(line=cursor_line, character=0),
                                        end=Position(line=cursor_line, character=0),
                                    ),
                                    new_text=doc_block,
                                )
                            ]
                        }
                    ),
                )
            )

    # ── 5. Переформатировать документ (если есть что форматировать) ────────
    if content:
        try:
            from onec_hbk_bsl.analysis.formatter import default_formatter

            formatted = default_formatter.format(content)
            if formatted != content:
                actions.append(
                    CodeAction(
                        title="Переформатировать документ",
                        kind=CodeActionKind.SourceFixAll,
                        edit=WorkspaceEdit(
                            changes={
                                uri: [
                                    TextEdit(
                                        range=Range(
                                            start=Position(line=0, character=0),
                                            end=Position(line=len(doc_lines), character=0),
                                        ),
                                        new_text=formatted,
                                    )
                                ]
                            }
                        ),
                    )
                )
        except Exception:
            pass

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


def _build_selection_range(lines: list[str], cursor_line: int) -> SelectionRange | None:
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


def _node_to_dict(node: object, depth: int = 0, max_depth: int = 12) -> dict:
    """Recursively convert a tree-sitter node to a JSON-serialisable dict."""
    text = getattr(node, "text", "") or ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    result: dict = {
        "type": getattr(node, "type", "unknown"),
        "text": text[:200],
        "start": list(getattr(node, "start_point", (0, 0))),
        "end": list(getattr(node, "end_point", (0, 0))),
    }
    children = list(getattr(node, "children", []))
    if depth < max_depth:
        if children:
            result["children"] = [_node_to_dict(c, depth + 1, max_depth) for c in children]
    else:
        if children:
            result["children_truncated"] = len(children)
    return result


@server.feature("bsl/parseTree")
def on_bsl_parse_tree(ls: BslLanguageServer, params: dict) -> dict:  # type: ignore[type-arg]
    """Return the AST of a document as a JSON-serialisable dict."""
    uri = params.get("uri", "")
    content = ls._doc_get(uri)
    if content is None:
        try:
            content = Path(_uri_to_path(uri)).read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:
            return {"uri": uri, "tree": None, "error": str(exc)}
    try:
        context = _get_lsp_document_context(ls, uri, content)
        root = context.snapshot.root_node if context is not None else None
        return {"uri": uri, "tree": _node_to_dict(root), "error": None}
    except Exception as exc:
        return {"uri": uri, "tree": None, "error": str(exc)}


@server.feature("bsl/status")
def on_bsl_status(ls: BslLanguageServer, params: object) -> dict:  # type: ignore[type-arg]
    """Return index statistics for the status bar."""
    return _status_payload(ls)


@server.feature("bsl/reindexWorkspace")
def on_bsl_reindex_workspace(ls: BslLanguageServer, params: dict) -> dict:  # type: ignore[type-arg]
    """Re-index the entire workspace (triggered from VSCode command)."""
    if ls.index_mode == "off":
        return {"success": False, "error": "Workspace index is disabled (index-mode=off)"}
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
    return {"success": True, "started": True, "indexing": True}


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
