"""Shared semantic extraction for BSL documents.

This module intentionally keeps ``extract_symbols`` and ``extract_calls`` as
public compatibility APIs, but provides a single CST pass for callers that need
both symbol and call pools for the same parsed document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.call_graph import (
    Call,
    _root_source_lines,
    _ts_method_call_to_record,
)
from onec_hbk_bsl.analysis.call_graph import (
    _extract_from_source as _extract_calls_from_source,
)
from onec_hbk_bsl.analysis.symbols import (
    Symbol,
    _ts_proc_to_symbol,
    _ts_var_to_symbol,
)
from onec_hbk_bsl.analysis.symbols import (
    _extract_from_source as _extract_symbols_from_source,
)


@dataclass(frozen=True)
class SemanticModel:
    """Semantic pools extracted from one parsed document."""

    symbols: list[Symbol]
    calls: list[Call]


def extract_semantic_model(tree: Any, file_path: str) -> SemanticModel:
    """Extract symbols and calls from *tree* using one CST walk when possible."""
    if hasattr(tree, "root_node"):
        root = tree.root_node
        sample_text = root.children[0].text if root.children else None
        is_ts = isinstance(sample_text, bytes)
        if is_ts:
            return _extract_from_ts(root, file_path)

    if hasattr(tree, "content"):
        return SemanticModel(
            symbols=_extract_symbols_from_source(tree.content, file_path),
            calls=_extract_calls_from_source(tree.content, file_path),
        )

    return SemanticModel(symbols=[], calls=[])


def _extract_from_ts(root: Any, file_path: str) -> SemanticModel:
    source_lines = _root_source_lines(root)
    symbols: list[Symbol] = []
    calls: list[Call] = []
    _visit_node(root, symbols, calls, file_path, source_lines, container=None)
    return SemanticModel(
        symbols=sorted(symbols, key=lambda symbol: symbol.line),
        calls=calls,
    )


def _visit_node(
    node: Any,
    symbols: list[Symbol],
    calls: list[Call],
    file_path: str,
    source_lines: list[str],
    container: str | None,
) -> None:
    node_type = getattr(node, "type", "")
    current_container = container

    if node_type in ("procedure_definition", "function_definition"):
        sym = _ts_proc_to_symbol(node, file_path, source_lines, container)
        if sym is not None:
            symbols.append(sym)
            current_container = sym.name
    elif node_type in ("var_definition", "var_statement"):
        sym = _ts_var_to_symbol(node, file_path, source_lines, container)
        if sym is not None:
            symbols.append(sym)
        return
    elif node_type == "method_call":
        call = _ts_method_call_to_record(node, file_path, container, source_lines)
        if call is not None:
            calls.append(call)

    for child in getattr(node, "children", []) or []:
        _visit_node(child, symbols, calls, file_path, source_lines, current_container)
