"""Immutable, surface-neutral semantic facts derived from one document snapshot."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from onec_hbk_bsl.analysis.lsp_positions import utf16_len
from onec_hbk_bsl.analysis.sdbl_cst import (
    QUERY_METADATA_ROOT_TO_KIND,
    QUERY_METADATA_ROOTS,
    nullable_join_field_uses_without_isnull,
    query_source_uses,
    query_temp_table_names,
    redundant_reference_nodes,
)

ResolutionState = Literal["resolved", "ambiguous", "unknown"]
MetadataResolver = Callable[[str, str], tuple[str, ...]]
ReceiverResolver = Callable[[Any, int], tuple[str | None, str | list[str] | None]]

_QUERY_METADATA_ROOT_PATTERN = "|".join(
    re.escape(root) for root in sorted(QUERY_METADATA_ROOTS, key=len, reverse=True)
)
_QUERY_METADATA_TYPE_REF_RE = re.compile(
    r"\b(?:ССЫЛКА|REFS?)\s+"
    rf"(?P<refs>({_QUERY_METADATA_ROOT_PATTERN})\.[A-Za-zА-Яа-яЁё_]\w*"
    r"(?:\.[A-Za-zА-Яа-яЁё_]\w*)*)"
    r"|"
    r"\b(?:КАК|AS)\s+"
    rf"(?P<cast>({_QUERY_METADATA_ROOT_PATTERN})\.[A-Za-zА-Яа-яЁё_]\w*"
    r"(?:\.[A-Za-zА-Яа-яЁё_]\w*)*)\s*\)",
    re.IGNORECASE,
)


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
    metadata_contexts: tuple[MetadataContextFact, ...]
    nullable_join_spans: tuple[SourceSpan, ...]
    redundant_reference_spans: tuple[SourceSpan, ...]
    temp_table_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetadataContextFact:
    """Metadata lookup context with explicit conservative resolution."""

    name: str
    collection: str | None
    span: SourceSpan
    state: ResolutionState
    candidate_names: tuple[str, ...]
    catalog_available: bool


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


def _call_fact(
    call: Any,
    path: str,
    receiver_resolver: ReceiverResolver | None,
) -> CallFact:
    start_line = max(0, int(call.caller_line) - 1)
    character = int(call.caller_character)
    callee_name = str(call.callee_name)
    receiver = None
    receiver_node = getattr(call, "receiver_node", None)
    receiver_expression = getattr(call, "receiver_expression", None)
    if receiver_expression and int(getattr(call, "receiver_line", 0)) > 0:
        state: ResolutionState = "unknown"
        candidates: tuple[str, ...] = ()
        if receiver_resolver is not None and receiver_node is not None:
            generic, specific = receiver_resolver(receiver_node, int(call.receiver_line) - 1)
            if isinstance(specific, list):
                candidates = tuple(sorted(set(specific), key=str.casefold))
                if len(candidates) > 1:
                    state = "ambiguous"
                elif candidates:
                    state = "resolved"
                elif generic:
                    candidates = (generic,)
                    state = "resolved"
            elif isinstance(specific, str):
                candidates = (specific,)
                state = "resolved"
            elif generic:
                candidates = (generic,)
                state = "resolved"
        receiver = ReceiverFact(
            expression=str(receiver_expression),
            span=SourceSpan(
                path=path,
                start_line=int(call.receiver_line) - 1,
                start_character=int(call.receiver_character),
                end_line=max(int(call.receiver_line), int(call.receiver_end_line)) - 1,
                end_character=int(call.receiver_end_character),
            ),
            state=state,
            candidate_types=candidates,
        )
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
        receiver=receiver,
    )


def _mapped_node_span(block: Any, node: Any, path: str) -> SourceSpan:
    start_line, start_character = block.original_lsp_position(
        node.start_point[0], node.start_point[1]
    )
    end_line, end_character = block.original_lsp_position(node.end_point[0], node.end_point[1])
    return SourceSpan(
        path=path,
        start_line=start_line,
        start_character=start_character,
        end_line=end_line,
        end_character=end_character,
    )


def _metadata_context(
    source: str,
    span: SourceSpan,
    resolver: MetadataResolver | None,
) -> MetadataContextFact | None:
    parts = source.split(".")
    if len(parts) < 2:
        return None
    collection = QUERY_METADATA_ROOT_TO_KIND.get(parts[0].casefold())
    if collection is None:
        return None
    name = parts[1]
    candidates = (
        tuple(sorted(set(resolver(collection, name)), key=str.casefold))
        if resolver is not None
        else ()
    )
    state: ResolutionState
    if len(candidates) == 1:
        state = "resolved"
    elif len(candidates) > 1:
        state = "ambiguous"
    else:
        state = "unknown"
    return MetadataContextFact(
        name=name,
        collection=collection,
        span=SourceSpan(
            path=span.path,
            start_line=span.start_line,
            start_character=span.start_character,
            end_line=span.start_line,
            end_character=span.start_character + utf16_len(".".join(parts[:2])),
        ),
        state=state,
        candidate_names=candidates,
        catalog_available=resolver is not None,
    )


def _query_metadata_contexts(
    block: Any,
    path: str,
    root: Any | None,
    resolver: MetadataResolver | None,
    temp_table_names: frozenset[str],
) -> tuple[MetadataContextFact, ...]:
    contexts: list[MetadataContextFact] = []
    if root is not None:
        for source_use in query_source_uses(root):
            if source_use.source.casefold() in temp_table_names:
                continue
            context = _metadata_context(
                source_use.source,
                _mapped_node_span(block, source_use.node, path),
                resolver,
            )
            if context is not None:
                contexts.append(context)

    for line in block.content_lines:
        head = str(line.head)
        for match in _QUERY_METADATA_TYPE_REF_RE.finditer(head):
            group_name = "refs" if match.group("refs") is not None else "cast"
            source = match.group(group_name)
            start_character = int(line.content_base) + utf16_len(head[: match.start(group_name)])
            context = _metadata_context(
                source,
                SourceSpan(
                    path=path,
                    start_line=int(line.line_no) - 1,
                    start_character=start_character,
                    end_line=int(line.line_no) - 1,
                    end_character=start_character + utf16_len(source),
                ),
                resolver,
            )
            if context is not None:
                contexts.append(context)

    unique: dict[tuple[SourceSpan, str, str | None], MetadataContextFact] = {}
    for context in contexts:
        unique[(context.span, context.name.casefold(), context.collection)] = context
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.span,
                item.collection or "",
                item.name.casefold(),
            ),
        )
    )


def _query_fact(
    block: Any,
    path: str,
    resolver: MetadataResolver | None,
) -> QueryFact:
    content_lines = tuple(block.content_lines)
    start_line = int(block.start_idx)
    if content_lines:
        last = content_lines[-1]
        end_line = max(start_line, int(last.line_no) - 1)
        end_character = int(last.content_base) + utf16_len(str(last.head))
    else:
        end_line = start_line
        end_character = 0
    root = getattr(getattr(block, "sdbl_tree", None), "root_node", None)
    temp_table_names = query_temp_table_names(root) if root is not None else frozenset()
    nullable_join_spans: list[SourceSpan] = []
    redundant_spans: list[SourceSpan] = []
    if root is not None:
        seen_join_nodes: set[int] = set()
        for usage in nullable_join_field_uses_without_isnull(root):
            join_node = usage.join_node
            key = int(getattr(join_node, "id", 0))
            if key in seen_join_nodes:
                continue
            seen_join_nodes.add(key)
            nullable_join_spans.append(_mapped_node_span(block, join_node, path))
        redundant_spans.extend(
            _mapped_node_span(block, node, path) for node in redundant_reference_nodes(root)
        )

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
        metadata_contexts=_query_metadata_contexts(
            block,
            path,
            root,
            resolver,
            temp_table_names,
        ),
        nullable_join_spans=tuple(nullable_join_spans),
        redundant_reference_spans=tuple(redundant_spans),
        temp_table_names=tuple(sorted(temp_table_names)),
    )


def build_semantic_fact_snapshot(
    snapshot: Any,
    revision: FactRevision,
    *,
    metadata_resolver: MetadataResolver | None = None,
    receiver_resolver: ReceiverResolver | None = None,
) -> SemanticFactSnapshot:
    """Normalize existing snapshot extractors without re-parsing or re-walking the CST."""
    path = str(snapshot.path)
    calls = tuple(_call_fact(call, path, receiver_resolver) for call in snapshot.calls)
    queries = tuple(
        _query_fact(block, path, metadata_resolver) for block in snapshot.query_text_blocks
    )
    return SemanticFactSnapshot(
        revision=revision,
        symbols=tuple(_symbol_fact(symbol, path) for symbol in snapshot.symbols),
        calls=calls,
        queries=queries,
        receivers=tuple(call.receiver for call in calls if call.receiver is not None),
        metadata_contexts=tuple(
            context for query in queries for context in query.metadata_contexts
        ),
    )
