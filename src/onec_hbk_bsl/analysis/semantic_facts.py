"""Immutable, surface-neutral semantic facts derived from one document snapshot."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from onec_hbk_bsl.analysis.lsp_positions import utf16_len

ResolutionState = Literal["resolved", "ambiguous", "unknown"]


@dataclass(frozen=True, slots=True)
class FactRevision:
    """Identity of every semantic input used to build a fact snapshot."""

    content_sha256: str
    index: int
    metadata: int
    config: int

    @classmethod
    def for_content(
        cls,
        content: str,
        *,
        index: int = 0,
        metadata: int = 0,
        config: int = 0,
    ) -> FactRevision:
        return cls(
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            index=index,
            metadata=metadata,
            config=config,
        )


@dataclass(frozen=True, slots=True, order=True)
class SourceSpan:
    """Exact zero-based LSP source range owned by a canonical path."""

    path: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass(frozen=True, slots=True)
class SymbolFact:
    """Declaration fact used by diagnostics and navigation surfaces."""

    name: str
    kind: str
    span: SourceSpan
    is_export: bool
    container: str | None
    signature: str
    doc_comment: str

    @property
    def file_path(self) -> str:
        return self.span.path

    @property
    def line(self) -> int:
        return self.span.start_line + 1

    @property
    def character(self) -> int:
        return self.span.start_character

    @property
    def end_line(self) -> int:
        return self.span.end_line + 1

    @property
    def end_character(self) -> int:
        return self.span.end_character


@dataclass(frozen=True, slots=True)
class ReceiverFact:
    """Conservative receiver resolution; ambiguous candidates are never guessed."""

    expression: str
    span: SourceSpan
    state: ResolutionState
    candidate_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CallFact:
    """Call site with an optional explicitly resolved receiver."""

    caller_name: str | None
    callee_name: str
    span: SourceSpan
    callee_args_count: int
    receiver: ReceiverFact | None

    @property
    def caller_file(self) -> str:
        return self.span.path

    @property
    def caller_line(self) -> int:
        return self.span.start_line + 1

    @property
    def caller_character(self) -> int:
        return self.span.start_character


@dataclass(frozen=True, slots=True)
class QueryFact:
    """Embedded query text and its owning source range."""

    text: str
    span: SourceSpan
    has_errors: bool


@dataclass(frozen=True, slots=True)
class MetadataContextFact:
    """Metadata lookup context with explicit conservative resolution."""

    name: str
    collection: str | None
    span: SourceSpan
    state: ResolutionState
    candidate_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticFactSnapshot:
    """Immutable fact boundary shared by diagnostics, navigation, and refactors."""

    revision: FactRevision
    symbols: tuple[SymbolFact, ...]
    calls: tuple[CallFact, ...]
    queries: tuple[QueryFact, ...]
    receivers: tuple[ReceiverFact, ...]
    metadata_contexts: tuple[MetadataContextFact, ...]


def _symbol_fact(symbol: Any, path: str) -> SymbolFact:
    start_line = max(0, int(symbol.line) - 1)
    end_line = max(start_line, int(symbol.end_line) - 1)
    return SymbolFact(
        name=str(symbol.name),
        kind=str(symbol.kind),
        span=SourceSpan(
            path=path,
            start_line=start_line,
            start_character=int(symbol.character),
            end_line=end_line,
            end_character=int(symbol.end_character),
        ),
        is_export=bool(symbol.is_export),
        container=symbol.container,
        signature=str(symbol.signature),
        doc_comment=str(symbol.doc_comment),
    )


def _call_fact(call: Any, path: str) -> CallFact:
    start_line = max(0, int(call.caller_line) - 1)
    character = int(call.caller_character)
    callee_name = str(call.callee_name)
    return CallFact(
        caller_name=call.caller_name,
        callee_name=callee_name,
        span=SourceSpan(
            path=path,
            start_line=start_line,
            start_character=character,
            end_line=start_line,
            end_character=character + utf16_len(callee_name),
        ),
        callee_args_count=int(call.callee_args_count),
        receiver=None,
    )


def _query_fact(block: Any, path: str) -> QueryFact:
    content_lines = tuple(block.content_lines)
    start_line = int(block.start_idx)
    if content_lines:
        last = content_lines[-1]
        end_line = max(start_line, int(last.line_no) - 1)
        end_character = int(last.content_base) + utf16_len(str(last.head))
    else:
        end_line = start_line
        end_character = 0
    return QueryFact(
        text=str(block.query_text),
        span=SourceSpan(
            path=path,
            start_line=start_line,
            start_character=0,
            end_line=end_line,
            end_character=end_character,
        ),
        has_errors=bool(block.sdbl_has_errors),
    )


def build_semantic_fact_snapshot(
    snapshot: Any,
    revision: FactRevision,
) -> SemanticFactSnapshot:
    """Normalize existing snapshot extractors without re-parsing or re-walking the CST."""
    path = str(snapshot.path)
    return SemanticFactSnapshot(
        revision=revision,
        symbols=tuple(_symbol_fact(symbol, path) for symbol in snapshot.symbols),
        calls=tuple(_call_fact(call, path) for call in snapshot.calls),
        queries=tuple(_query_fact(block, path) for block in snapshot.query_text_blocks),
        receivers=(),
        metadata_contexts=(),
    )
