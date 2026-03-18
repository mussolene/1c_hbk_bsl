"""
Call graph extraction and traversal for BSL modules.

Provides:
  - extract_calls()  — parse a tree and return call-site records
  - build_call_graph() — deep callers/callees tree from the index
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bsl_analyzer.indexer.symbol_index import SymbolIndex

# Regex used in fallback mode
_RE_CALL = re.compile(
    r"(?:^|[^.\w])(?P<name>[А-ЯЁа-яёA-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
# Words that look like calls but are BSL keywords
_BSL_KEYWORDS = frozenset(
    {
        "если", "пока", "для", "каждого", "из", "по", "цикл",
        "процедура", "функция", "перем", "возврат", "новый",
        "попытка", "исключение", "конецпопытки",
        "if", "while", "for", "each", "in", "do", "loop",
        "procedure", "function", "var", "return", "new",
        "try", "except", "endtry",
    }
)


@dataclass
class Call:
    """Represents a single call site in a BSL source file."""

    caller_file: str
    caller_line: int  # 1-based
    caller_name: str | None  # enclosing procedure/function name
    callee_name: str
    callee_args_count: int = 0


def extract_calls(tree: Any, file_path: str) -> list[Call]:
    """
    Extract all call expressions from a parsed BSL tree.

    Works with tree-sitter trees and _RegexTree fallback instances.

    Args:
        tree:      Parsed tree.
        file_path: Source file path (for Call.caller_file).

    Returns:
        List of Call records ordered by line number.
    """
    if hasattr(tree, "root_node"):
        root = tree.root_node
        # Detect tree-sitter (bytes text) vs regex fallback
        sample_text = root.children[0].text if root.children else None
        is_ts = isinstance(sample_text, bytes)

        if is_ts:
            return _extract_from_ts(root, file_path)

    if hasattr(tree, "content"):
        return _extract_from_source(tree.content, file_path)

    return []


# ---------------------------------------------------------------------------
# Tree-sitter extraction
# ---------------------------------------------------------------------------

def _extract_from_ts(root: Any, file_path: str) -> list[Call]:
    calls: list[Call] = []
    _visit_for_calls(root, calls, file_path, container=None)
    return calls


def _visit_for_calls(
    node: Any,
    calls: list[Call],
    file_path: str,
    container: str | None,
) -> None:
    node_type = node.type if hasattr(node, "type") else ""

    # Track enclosing procedure/function name
    if node_type in ("procedure_definition", "function_definition"):
        name = ""
        for ch in node.children:
            if ch.type == "identifier":
                name = _node_text(ch)
                break
        container = name or container

    if node_type == "call_expression":
        call = _ts_call_to_record(node, file_path, container)
        if call:
            calls.append(call)

    for child in node.children:
        _visit_for_calls(child, calls, file_path, container)


def _ts_call_to_record(node: Any, file_path: str, container: str | None) -> Call | None:
    callee_name = ""
    args_count = 0

    for child in node.children:
        ct = child.type
        if ct == "identifier":
            callee_name = _node_text(child)
        elif ct == "member_expression":
            # Obj.Method() — use the property part
            for subchild in child.children:
                if subchild.type == "identifier":
                    callee_name = _node_text(subchild)
        elif ct == "argument_list":
            # Count non-comma, non-paren children as arguments
            args_count = sum(
                1
                for c in child.children
                if c.type not in ("(", ")", ",")
            )

    if not callee_name or callee_name.lower() in _BSL_KEYWORDS:
        return None

    return Call(
        caller_file=file_path,
        caller_line=node.start_point[0] + 1,
        caller_name=container,
        callee_name=callee_name,
        callee_args_count=args_count,
    )


# ---------------------------------------------------------------------------
# Regex-based extraction (fallback)
# ---------------------------------------------------------------------------

def _extract_from_source(content: str, file_path: str) -> list[Call]:
    calls: list[Call] = []
    lines = content.splitlines()

    # Track current procedure/function context
    _RE_PROC = re.compile(
        r"^(?:Процедура|Procedure|Функция|Function)\s+(?P<name>\w+)",
        re.IGNORECASE,
    )
    _RE_END = re.compile(
        r"^(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
        re.IGNORECASE,
    )

    current_proc: str | None = None
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        pm = _RE_PROC.match(stripped)
        if pm:
            current_proc = pm.group("name")
            continue
        if _RE_END.match(stripped):
            current_proc = None
            continue

        for m in _RE_CALL.finditer(line):
            name = m.group("name")
            if name.lower() in _BSL_KEYWORDS:
                continue
            # Count arguments (rough estimate via commas after opening paren)
            rest = line[m.end():]
            paren_depth = 1
            args_count = 1 if rest.strip() and rest.strip()[0] != ")" else 0
            for ch in rest:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        break
                elif ch == "," and paren_depth == 1:
                    args_count += 1

            calls.append(
                Call(
                    caller_file=file_path,
                    caller_line=line_idx + 1,
                    caller_name=current_proc,
                    callee_name=name,
                    callee_args_count=args_count,
                )
            )

    return calls


# ---------------------------------------------------------------------------
# Call graph builder
# ---------------------------------------------------------------------------

def build_call_graph(
    index: "SymbolIndex",
    symbol_name: str,
    depth: int = 5,
) -> dict:
    """
    Build a JSON-serializable call graph rooted at *symbol_name*.

    Returns a dict with:
      - ``name``: the queried symbol
      - ``callers``: recursive list of who calls this symbol (up to *depth*)
      - ``callees``: list of symbols resolved from the index (definitions)
      - ``definition``: first definition location, if found

    Args:
        index:       SymbolIndex instance to query.
        symbol_name: Name of the procedure/function to analyse.
        depth:       Maximum recursion depth for callers tree.
    """
    visited_callers: set[str] = set()

    def _callers_tree(name: str, d: int) -> list[dict]:
        if d <= 0 or name in visited_callers:
            return []
        visited_callers.add(name)
        rows = index.find_callers(name, limit=20)
        result = []
        for row in rows:
            caller = row.get("caller_name") or row.get("caller_file", "")
            result.append(
                {
                    "caller_name": row.get("caller_name"),
                    "caller_file": row.get("caller_file"),
                    "caller_line": row.get("caller_line"),
                    "callers": _callers_tree(caller, d - 1) if row.get("caller_name") else [],
                }
            )
        return result

    # Resolve callees by looking up the symbol's calls in the index
    definitions = index.find_symbol(symbol_name)
    definition = definitions[0] if definitions else None

    callees_raw: list[dict] = []
    if definition:
        callees_raw = index.find_callees(
            definition["file_path"],
            caller_line=None,
        )
        # Filter to calls from within this function's line range
        if definition:
            start = definition.get("line", 0)
            end = definition.get("end_line", 9999999)
            callees_raw = [
                c for c in callees_raw if start <= c.get("caller_line", 0) <= end
            ]

    return {
        "name": symbol_name,
        "definition": {
            "file": definition["file_path"] if definition else None,
            "line": definition["line"] if definition else None,
            "signature": definition["signature"] if definition else None,
        },
        "callers": _callers_tree(symbol_name, depth),
        "callees": [
            {
                "callee_name": c.get("callee_name"),
                "caller_line": c.get("caller_line"),
                "callee_file": c.get("callee_file"),
                "callee_line": c.get("callee_line"),
            }
            for c in callees_raw
        ],
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _node_text(node: Any) -> str:
    if node.text is None:
        return ""
    if isinstance(node.text, bytes):
        return node.text.decode("utf-8", errors="replace")
    return str(node.text)
