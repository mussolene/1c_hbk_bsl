"""Shared parse-tree helpers for diagnostics and snapshots."""

from __future__ import annotations

from typing import Any

_TREE_ERROR_CACHE_MAX = 200_000
_tree_error_cache: dict[tuple[int, int, int], bool] = {}


def _tree_error_cache_key(node: Any) -> tuple[int, int, int] | None:
    node_id = getattr(node, "id", None)
    start_byte = getattr(node, "start_byte", None)
    end_byte = getattr(node, "end_byte", None)
    if not all(isinstance(value, int) for value in (node_id, start_byte, end_byte)):
        return None
    return (node_id, start_byte, end_byte)


def tree_has_errors(node: Any) -> bool:
    """True when a tree-sitter subtree contains ERROR or missing nodes."""

    key = _tree_error_cache_key(node)
    if key is not None:
        cached = _tree_error_cache.get(key)
        if cached is not None:
            return cached

    if node.type in ("ERROR", "error") or getattr(node, "is_missing", False):
        result = True
    else:
        result = any(tree_has_errors(child) for child in node.children)

    if key is not None:
        if len(_tree_error_cache) >= _TREE_ERROR_CACHE_MAX:
            _tree_error_cache.clear()
        _tree_error_cache[key] = result
    return result


__all__ = ["tree_has_errors"]
