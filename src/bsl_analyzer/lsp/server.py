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
  - textDocument/formatting + textDocument/rangeFormatting + textDocument/onTypeFormatting
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lsprotocol.types import (
    TEXT_DOCUMENT_CODE_LENS,
    CodeLens,
    CodeLensParams,
    Command,
    CALL_HIERARCHY_INCOMING_CALLS,
    CALL_HIERARCHY_OUTGOING_CALLS,
    INITIALIZE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_COMPLETION,
    CompletionOptions,
    InsertTextFormat,
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
    TEXT_DOCUMENT_ON_TYPE_FORMATTING,
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
    DiagnosticTag,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
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
    Location,
    LocationLink,
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
    PublishDiagnosticsParams,
)

try:
    from pygls.server import LanguageServer  # pygls < 1.2
except ImportError:
    from pygls.lsp.server import LanguageServer  # pygls >= 1.2

from bsl_analyzer.analysis.diagnostics import (
    DiagnosticEngine,
    Severity,
    RULE_METADATA,
    _find_procedures_from_tree,
    _calc_cognitive_complexity,
    _calc_mccabe_complexity,
)
from bsl_analyzer.analysis.formatter import (
    default_formatter,
    _DEDENT_BEFORE,
    _get_stripped_keyword,
)
from bsl_analyzer.analysis.platform_api import PlatformApi, get_platform_api
from bsl_analyzer.indexer.db_path import resolve_index_db_path
from bsl_analyzer.indexer.incremental import IncrementalIndexer
from bsl_analyzer.indexer.symbol_index import SymbolIndex
from bsl_analyzer.lsp.diagnostics_ru import translate_message, DIAGNOSTICS_RU
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
            for _ in watch(str(git_head), stop_event=None):
                branch = _current_branch(git_head)
                logger.warning("LSP: branch changed → %s — re-indexing %s", branch, workspace_root)
                try:
                    ls.indexer.index_workspace(workspace_root, force=False)
                    stats = ls.symbol_index.get_stats()
                    logger.warning(
                        "LSP: re-index complete: %d symbols in %d files",
                        stats["symbol_count"], stats["file_count"],
                    )
                except Exception as exc:
                    logger.error("LSP: re-index after branch switch failed: %s", exc)
        except Exception as exc:
            logger.error("LSP: branch watcher crashed: %s", exc)

    threading.Thread(target=_watch, daemon=True, name="bsl-branch-watcher").start()


def _current_branch(git_head: Path) -> str:
    """Read the current branch name from .git/HEAD (best-effort)."""
    try:
        content = git_head.read_text(encoding="utf-8").strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        return content[:8]  # detached HEAD — show short hash
    except OSError:
        return "unknown"


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
        _start_branch_watcher(ls, workspace_root)


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
# Skip live diagnostics for files larger than this (run only on save)
_DIAG_MAX_LINES_LIVE = 3000


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

    # Skip live diagnostics for very large files — they block the server
    content = ls._docs.get(uri, "")
    if content.count("\n") > _DIAG_MAX_LINES_LIVE:
        logger.debug("LSP: skipping live diags for large file %s", uri)
        return

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
    """Run diagnostic engine and push results to the client.

    Uses in-memory document content when available (reflects current editor
    state) and falls back to reading from disk.
    """
    try:
        cached = ls._docs.get(uri)
        if cached is not None:
            issues = ls.diagnostics_engine.check_content(path, cached)
        else:
            issues = ls.diagnostics_engine.check_file(path)
        lsp_diags = [
            LspDiagnostic(
                range=Range(
                    start=Position(line=d.line - 1, character=d.character),
                    end=Position(line=d.end_line - 1, character=d.end_character),
                ),
                severity=_SEV_MAP.get(d.severity, DiagnosticSeverity.Warning),
                code=d.code,
                message=translate_message(d.code, d.message),
                source="bsl-analyzer",
            )
            for d in issues
        ]

        # Unused (dead) function detection: private symbols with no callers
        # Uses DiagnosticTag.Unnecessary → VSCode renders them as dimmed text
        try:
            for sym in ls.symbol_index.find_unused_symbols(path):
                name = sym.get("name", "")
                sym_line = max(0, sym["line"] - 1)
                sym_char = sym.get("character", 0)
                lsp_diags.append(
                    LspDiagnostic(
                        range=Range(
                            start=Position(line=sym_line, character=sym_char),
                            end=Position(line=sym_line, character=sym_char + len(name)),
                        ),
                        severity=DiagnosticSeverity.Hint,
                        code="BSL-DEAD",
                        message=f"«{name}» не используется в проекте",
                        source="bsl-analyzer",
                        tags=[DiagnosticTag.Unnecessary],
                    )
                )
        except Exception as exc:
            logger.debug("LSP: unused detection failed for %s: %s", path, exc)

        ls.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri=uri, diagnostics=lsp_diags)
        )
    except Exception as exc:
        logger.error("LSP: diagnostics failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Go-to-definition
# ---------------------------------------------------------------------------


@server.feature(TEXT_DOCUMENT_DEFINITION)
def on_definition(
    ls: BslLanguageServer, params: DefinitionParams
) -> list[LocationLink] | None:
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

    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    origin_range = _word_range_at_position(content, pos.line, pos.character)

    # 1. Check local scope first (parameters, Перем, loop vars, assignments).
    #    Local variables shadow same-named globals — resolve them without index.
    try:
        _tree = ls.parser.parse_content(content, file_path=uri)
        local_vars = _extract_scope_vars(_tree, pos.line)
        for lv in local_vars:
            if lv.name.casefold() == word.casefold():
                decl_line = lv.line - 1  # 0-based
                decl_char = lv.character
                name_end = decl_char + len(lv.name)
                r = Range(
                    start=Position(line=decl_line, character=decl_char),
                    end=Position(line=decl_line, character=name_end),
                )
                return [LocationLink(
                    target_uri=uri,
                    target_range=r,
                    target_selection_range=r,
                    origin_selection_range=origin_range,
                )]
    except Exception:
        pass

    # 2. Workspace symbol index (procedures, functions, exported variables)
    symbols = ls.symbol_index.find_symbol(word, limit=20)
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


_KIND_RU: dict[str, str] = {
    "procedure": "процедура",
    "function": "функция",
    "variable": "переменная",
    "unknown": "символ",
}

_API_KIND_RU: dict[str, str] = {
    "class": "класс",
    "enum": "перечисление",
    "global": "глобальный объект",
    "collection": "коллекция",
}


def _hover_markdown(parts: list[str]) -> Hover:
    return Hover(contents=MarkupContent(kind=MarkupKind.Markdown, value="\n\n".join(parts)))


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
    content = ls._docs.get(uri, "")
    word = _word_at_position(content, pos.line, pos.character)
    if not word:
        return None

    left_word = _left_word_at_position(content, pos.line, pos.character)

    # Detect `Новый TypeName` context: check word immediately before cursor on same line.
    lines = content.splitlines()
    _cur_line = lines[pos.line] if pos.line < len(lines) else ""
    _before_word = _cur_line[:pos.character - len(word)].rstrip()
    _after_new = _re.search(
        r"(?:Новый|New)\s*$", _before_word, _re.IGNORECASE | _re.UNICODE
    ) is not None

    # 0. Local variable scope (parameters, Перем, loop vars, assignments).
    #    Check before workspace index — locals shadow global names.
    #    Skip when cursor is on the right side of a dot (member access)
    #    and skip when we are in `Новый TypeName` context.
    if not left_word and not _after_new:
        try:
            _tree = ls.parser.parse_content(content, file_path=uri)
            _local_vars = _extract_scope_vars(_tree, pos.line)
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
                    if _lv.type_hint:
                        _parts.append(f"**Тип:** `{_lv.type_hint}`")
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
        sym = symbols[0]
        kind_ru = _KIND_RU.get(sym.get("kind", ""), "символ")
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
                f"- `{Path(s['file_path']).name}`, строка {s['line']}" for s in symbols
            )
            parts.append(f"*Определено в {len(symbols)} местах:*\n{locations}")
        # Количество мест вызова (быстрый COUNT — без загрузки всех строк)
        caller_count = ls.symbol_index.find_callers_count(word)
        if caller_count:
            parts.append(f"*Вызывается в {caller_count} местах*")
        return _hover_markdown(parts)

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

    # 5. Метаданные конфигурации 1С
    if hasattr(ls, "symbol_index") and ls.symbol_index.has_metadata():
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
            members = ls.symbol_index.get_meta_members(left_word, word)
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


@server.feature(
    TEXT_DOCUMENT_COMPLETION,
    CompletionOptions(trigger_characters=["."]),
)
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
            inferred = _infer_type_from_content(content, obj_name)
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
            items = _meta_dot_completions(ls, obj_name, member_prefix)

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
        ws_symbols = ls.symbol_index.find_symbol(prefix, limit=30, fuzzy=True)
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
                        sym.get("doc_comment") or ""
                        + f"\n*{Path(sym['file_path']).name}:{sym['line']}*"
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


_RE_PROC_HEADER = _re.compile(
    r"^\s*(?:Процедура|Функция|Procedure|Function)\s+(\w+)\s*\(([^)]*)\)",
    _re.IGNORECASE | _re.UNICODE,
)


def _generate_doc_comment(header_line: str, line_idx: int, all_lines: list[str]) -> str | None:
    """Generate a documentation comment block for a Procedure/Function header line.

    Returns ``None`` if the line is not a procedure/function header, or if it is
    already preceded by a ``//`` comment.
    """
    m = _RE_PROC_HEADER.match(header_line)
    if not m:
        return None
    if line_idx > 0 and all_lines[line_idx - 1].strip().startswith("//"):
        return None  # already documented
    indent = " " * (len(header_line) - len(header_line.lstrip()))
    func_name, params_str = m.group(1), m.group(2).strip()
    lines = [f"{indent}// Описание {func_name}."]
    if params_str:
        lines += [f"{indent}//", f"{indent}// Параметры:"]
        for p in params_str.split(","):
            name = p.strip().split("=")[0].strip()
            # Strip leading Знач/Val keyword
            name = _re.sub(r"(?i)^(Знач|Val)\s+", "", name)
            if name:
                lines.append(f"{indent}//   {name} - Тип - Описание")
    lines.append(f"{indent}//")
    return "\n".join(lines) + "\n"


_RE_NEW_ASSIGN = _re.compile(
    r"(?:^|;)\s*(\w+)\s*=\s*(?:Новый|New)\s+([\wА-ЯЁа-яёA-Za-z]+)\s*[;(]",
    _re.IGNORECASE | _re.MULTILINE | _re.UNICODE,
)


def _infer_type_from_content(content: str, var_name: str) -> str | None:
    """Infer BSL type from `VarName = Новый TypeName()` assignment pattern."""
    var_lo = var_name.casefold()
    for m in _RE_NEW_ASSIGN.finditer(content):
        if m.group(1).casefold() == var_lo:
            return m.group(2)
    return None


# 1C global collection names (both RU and EN variants) → canonical Russian name
_META_COLLECTIONS: dict[str, str] = {
    "справочники": "Справочники",
    "catalogs": "Справочники",
    "документы": "Документы",
    "documents": "Документы",
    "обработки": "Обработки",
    "dataprocessors": "Обработки",
    "отчеты": "Отчеты",
    "reports": "Отчеты",
    "регистрысведений": "РегистрыСведений",
    "informationregisters": "РегистрыСведений",
    "регистрынакопления": "РегистрыНакопления",
    "accumulationregisters": "РегистрыНакопления",
    "регистрыбухгалтерии": "РегистрыБухгалтерии",
    "accountingregisters": "РегистрыБухгалтерии",
    "регистрырасчета": "РегистрыРасчета",
    "calculationregisters": "РегистрыРасчета",
    "планыобмена": "ПланыОбмена",
    "exchangeplans": "ПланыОбмена",
    "бизнеспроцессы": "БизнесПроцессы",
    "businessprocesses": "БизнесПроцессы",
    "задачи": "Задачи",
    "tasks": "Задачи",
    "планысчетов": "ПланыСчетов",
    "chartsofaccounts": "ПланыСчетов",
    "планывидоврасчета": "ПланыВидовРасчета",
    "chartsofcalculationtypes": "ПланыВидовРасчета",
    "планывидоххарактеристик": "ПланыВидовХарактеристик",
    "chartsofcharacteristictypes": "ПланыВидовХарактеристик",
    "перечисления": "Перечисления",
    "enums": "Перечисления",
    "общиемодули": "ОбщиеМодули",
    "commonmodules": "ОбщиеМодули",
}

_META_MEMBER_KIND_TO_COMPLETION_KIND: dict[str, object] = {}  # unused; placeholder


def _meta_dot_completions(
    ls: "BslLanguageServer",
    obj_name: str,
    member_prefix: str,
) -> list["CompletionItem"]:
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

    # Case 1: global collection name
    collection = _META_COLLECTIONS.get(obj_lo)
    if collection:
        for meta_obj in ls.symbol_index.find_meta_objects_by_collection(collection, member_prefix):
            label = meta_obj["name"]
            detail = meta_obj.get("synonym_ru", "")
            items.append(
                CompletionItem(
                    label=label,
                    kind=CompletionItemKind.Module,
                    detail=detail or meta_obj.get("kind", ""),
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
        detail_parts = []
        if member.get("type_info"):
            detail_parts.append(member["type_info"])
        if member.get("synonym_ru"):
            detail_parts.append(member["synonym_ru"])
        items.append(
            CompletionItem(
                label=label,
                kind=ck,
                detail=" | ".join(detail_parts),
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
    kind: str       # 'parameter' | 'val_parameter' | 'var_decl' | 'loop_var' | 'assignment'
    line: int       # 1-based declaration line
    character: int  # 0-based column of the name token
    type_hint: str = ""  # e.g. "Массив" from «МойМассив = Новый Массив»


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
                result.append(_LocalVar(
                    name=_ast_node_text(child),
                    kind="var_decl",
                    line=node.start_point[0] + 1,
                    character=child.start_point[1],
                ))

    elif node.type == "for_each_statement":
        # Для Каждого <iterator> Из <collection> Цикл
        # The first identifier child (after FOR/EACH keywords) is the iterator
        saw_each = False
        for child in node.children:
            if child.type == "EACH_KEYWORD":
                saw_each = True
            elif saw_each and child.type == "identifier":
                result.append(_LocalVar(
                    name=_ast_node_text(child),
                    kind="loop_var",
                    line=node.start_point[0] + 1,
                    character=child.start_point[1],
                ))
                break
        # Recurse into loop body
        for child in node.children:
            _collect_local_vars(child, up_to_line0, result)

    elif node.type == "for_statement":
        # Для <var> = <start> По <end> Цикл
        for child in node.children:
            if child.type == "identifier":
                result.append(_LocalVar(
                    name=_ast_node_text(child),
                    kind="loop_var",
                    line=node.start_point[0] + 1,
                    character=child.start_point[1],
                ))
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
                # Look for Новый TypeName to capture the type
                for ec in child.children:
                    if ec.type == "new_expression":
                        for nc in ec.children:
                            if nc.type == "identifier":
                                type_hint = _ast_node_text(nc)
                                break
        if target_node is not None:
            result.append(_LocalVar(
                name=_ast_node_text(target_node),
                kind="assignment",
                line=node.start_point[0] + 1,
                character=target_node.start_point[1],
                type_hint=type_hint,
            ))

    else:
        for child in node.children:
            _collect_local_vars(child, up_to_line0, result)


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
                        vars.append(_LocalVar(
                            name=_ast_node_text(pc),
                            kind="val_parameter" if is_val else "parameter",
                            line=proc_node.start_point[0] + 1,
                            character=pc.start_point[1],
                        ))
                        break

    # 2. Body: Перем, loop vars, assignments up to cursor
    skip_types = frozenset({
        "PROCEDURE_KEYWORD", "FUNCTION_KEYWORD", "ENDPROCEDURE_KEYWORD",
        "ENDFUNCTION_KEYWORD", "EXPORT_KEYWORD", "identifier", "parameters",
    })
    for child in proc_node.children:
        if child.type not in skip_types:
            _collect_local_vars(child, cursor_line0, vars)

    # Deduplicate: first declaration wins (for Go-to-Definition)
    seen: dict[str, _LocalVar] = {}
    for v in vars:
        key = v.name.casefold()
        if key not in seen:
            seen[key] = v
    return list(seen.values())


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
    params = [p.strip() for p in m.group(1).split(",")]
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
        return Range(start=Position(line=line, character=character),
                     end=Position(line=line, character=character))
    text = lines[line]
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return Range(start=Position(line=line, character=start),
                 end=Position(line=line, character=end))


# ---------------------------------------------------------------------------
# Code Formatting
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Code Lens — cognitive / cyclomatic complexity above each procedure
# ---------------------------------------------------------------------------

@server.feature(TEXT_DOCUMENT_CODE_LENS)
def on_code_lens(
    ls: BslLanguageServer, params: CodeLensParams
) -> list[CodeLens] | None:
    """Return code lenses showing cognitive and cyclomatic complexity above each method."""
    uri = params.text_document.uri
    content = ls._docs.get(uri, "")
    if not content:
        return None
    try:
        tree = ls.parser.parse_content(content, file_path=uri)
        procs = _find_procedures_from_tree(tree)
        lines = content.splitlines()
    except Exception:
        return None

    result: list[CodeLens] = []
    for proc in procs:
        cc = _calc_cognitive_complexity(lines, proc.start_idx, proc.end_idx)
        mc = _calc_mccabe_complexity(lines, proc.start_idx, proc.end_idx)
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
    content = ls._docs.get(uri, "")
    if not content:
        return None

    indent_size = (params.options.tab_size if params.options else None) or 4
    lines = content.splitlines()

    # position.line is the newly-created line (where the cursor landed after Enter).
    new_line_idx = params.position.line
    if new_line_idx <= 0 or new_line_idx > len(lines):
        return None

    # Compute expected indent level from all lines above the new one
    context = lines[:new_line_idx]
    indent_level = default_formatter._indent_at(context, len(context), indent_size)

    # If the new line already contains a keyword that dedents (КонецЕсли, Иначе, …),
    # reduce the indent level by one so the keyword aligns with its opener
    current_line = lines[new_line_idx] if new_line_idx < len(lines) else ""
    stripped = current_line.lstrip()
    if stripped:
        first_kw = _get_stripped_keyword(stripped)
        if first_kw in _DEDENT_BEFORE:
            indent_level = max(0, indent_level - 1)

    wanted = " " * (indent_level * indent_size)

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
_FOLD_AST_TYPES = frozenset({
    "procedure_definition",
    "function_definition",
    "if_statement",
    "while_statement",
    "for_statement",
    "for_each_statement",
    "try_statement",
})


def _collect_ast_fold_ranges(node: Any, ranges: list[FoldingRange]) -> None:
    """Walk tree-sitter AST and collect folding ranges for block nodes."""
    if node.type in _FOLD_AST_TYPES:
        start = node.start_point[0]   # 0-based row
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
    content = ls._docs.get(uri, "")
    if not content:
        return None

    ranges: list[FoldingRange] = []

    # 1. AST-based ranges (handles multi-line conditions correctly)
    try:
        tree = ls.parser.parse_content(content, file_path=uri)
        _collect_ast_fold_ranges(tree.root_node, ranges)
    except Exception:
        pass  # fall through to regex pass for regions

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
                ranges.append(FoldingRange(
                    start_line=start, end_line=idx, kind=FoldingRangeKind.Region,
                ))

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

            # Split args by comma keeping raw (unstripped) chunks to track real offsets
            raw_args = m.group(2).split(",")

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
# Code Actions (quick fixes from diagnostics)
# ---------------------------------------------------------------------------

# Map diagnostic code → fix description
# ---------------------------------------------------------------------------
# Reverse BSLLS name map: BSL code → BSLLS name (for suppression comments)
# ---------------------------------------------------------------------------

def _build_code_to_bslls() -> dict[str, str]:
    try:
        from bsl_analyzer.analysis.diagnostics import _BSLLS_NAME_TO_CODE
        result: dict[str, str] = {}
        for name, code in _BSLLS_NAME_TO_CODE.items():
            if code not in result:
                result[code] = name
        return result
    except Exception:
        return {}

_CODE_TO_BSLLS_NAME: dict[str, str] = _build_code_to_bslls()


@server.feature(TEXT_DOCUMENT_CODE_ACTION)
def on_code_action(
    ls: BslLanguageServer, params: CodeActionParams
) -> list[CodeAction] | None:
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
    content = ls._docs.get(uri, "")
    doc_lines = content.splitlines()

    for diag in params.context.diagnostics:
        code = str(diag.code) if diag.code else ""
        try:
            diag_line = int(diag.range.start.line)
        except (TypeError, ValueError):
            continue

        if 0 <= diag_line < len(doc_lines):
            line_text = doc_lines[diag_line]
            line_end_char = len(line_text)
            indent = len(line_text) - len(line_text.lstrip())
            pad = " " * indent
            rule_name = RULE_METADATA.get(code, {}).get("name", "")
            rule_desc_ru = DIAGNOSTICS_RU.get(code, {}).get("title", "")
            display_name = rule_desc_ru or rule_name or code

            # ── 1. Игнорировать строку (noqa) ──────────────────────────────
            # If the line already has a noqa comment, append the code to it.
            _noqa_existing = _re.search(
                r"//\s*noqa:\s*([\w,\s]+?)\s*$", line_text, _re.IGNORECASE
            )
            if _noqa_existing and code:
                _existing_codes = [c.strip() for c in _noqa_existing.group(1).split(",")]
                if code not in _existing_codes:
                    _new_comment = f"  // noqa: {', '.join(_existing_codes + [code])}"
                    actions.append(CodeAction(
                        title=f"Добавить {code} к noqa-комментарию",
                        kind=CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=WorkspaceEdit(changes={uri: [TextEdit(
                            range=Range(
                                start=Position(line=diag_line, character=_noqa_existing.start()),
                                end=Position(line=diag_line, character=line_end_char),
                            ),
                            new_text=_new_comment,
                        )]}),
                    ))
            else:
                noqa_suffix = f"  // noqa: {code}" if code else "  // noqa"
                noqa_title = f"Игнорировать строку — {display_name}" if display_name != code else f"Игнорировать строку ({code})"
                actions.append(CodeAction(
                    title=noqa_title,
                    kind=CodeActionKind.QuickFix,
                    diagnostics=[diag],
                    edit=WorkspaceEdit(changes={uri: [TextEdit(
                        range=Range(
                            start=Position(line=diag_line, character=line_end_char),
                            end=Position(line=diag_line, character=line_end_char),
                        ),
                        new_text=noqa_suffix,
                    )]}),
                ))

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
                actions.append(CodeAction(
                    title=f"Отключить «{display_name}» для этой строки (BSLLS-off/on)",
                    kind=CodeActionKind.QuickFix,
                    diagnostics=[diag],
                    edit=WorkspaceEdit(changes={uri: [
                        TextEdit(
                            range=Range(start=insert_before, end=insert_before),
                            new_text=f"{pad}// BSLLS:{bslls_name}-off\n",
                        ),
                        TextEdit(range=after_range, new_text=after_new_text),
                    ]}),
                ))

                # ── 3. Отключить правило во всём файле ─────────────────────
                actions.append(CodeAction(
                    title=f"Отключить «{display_name}» в этом файле (BSLLS-off)",
                    kind=CodeActionKind.QuickFix,
                    diagnostics=[diag],
                    edit=WorkspaceEdit(changes={uri: [TextEdit(
                        range=Range(
                            start=Position(line=0, character=0),
                            end=Position(line=0, character=0),
                        ),
                        new_text=f"// BSLLS:{bslls_name}-off\n",
                    )]}),
                ))

    # ── 4. Сгенерировать комментарий к методу ──────────────────────────────
    try:
        cursor_line = int(params.range.start.line)
    except (TypeError, ValueError, AttributeError):
        cursor_line = -1
    if 0 <= cursor_line < len(doc_lines):
        doc_block = _generate_doc_comment(doc_lines[cursor_line], cursor_line, doc_lines)
        if doc_block:
            actions.append(CodeAction(
                title="Сгенерировать комментарий к методу",
                kind=CodeActionKind.RefactorExtract,
                edit=WorkspaceEdit(changes={uri: [TextEdit(
                    range=Range(
                        start=Position(line=cursor_line, character=0),
                        end=Position(line=cursor_line, character=0),
                    ),
                    new_text=doc_block,
                )]}),
            ))

    # ── 5. Переформатировать документ (если есть что форматировать) ────────
    if content:
        try:
            from bsl_analyzer.analysis.formatter import default_formatter
            formatted = default_formatter.format(content)
            if formatted != content:
                actions.append(CodeAction(
                    title="Переформатировать документ",
                    kind=CodeActionKind.SourceFixAll,
                    edit=WorkspaceEdit(changes={uri: [TextEdit(
                        range=Range(
                            start=Position(line=0, character=0),
                            end=Position(line=len(doc_lines), character=0),
                        ),
                        new_text=formatted,
                    )]}),
                ))
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
    content = ls._docs.get(uri)
    if content is None:
        try:
            content = Path(_uri_to_path(uri)).read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:
            return {"uri": uri, "tree": None, "error": str(exc)}
    try:
        tree = ls.parser.parse_content(content, file_path=uri)
        root = ls.parser.get_root_node(tree)
        return {"uri": uri, "tree": _node_to_dict(root), "error": None}
    except Exception as exc:
        return {"uri": uri, "tree": None, "error": str(exc)}


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
