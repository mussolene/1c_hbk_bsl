from __future__ import annotations

from collections.abc import Callable
from typing import Any


def execute_diagnostic_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Any]]]],
) -> list[Any]:
    """
    Run enabled rule callables in declaration order.

    Rules must run in the main thread: tree-sitter ``Parser`` is not thread-safe,
    and optional ``symbol_index`` backends are not assumed to be worker-safe.
    """
    out: list[Any] = []
    for _code, fn in tasks:
        out.extend(fn())
    return out
