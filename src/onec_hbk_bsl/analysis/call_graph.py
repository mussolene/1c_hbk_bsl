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

from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character

if TYPE_CHECKING:
    from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

# Regex used in fallback mode
_RE_CALL = re.compile(
    r"(?:^|[^.\w])(?P<name>[А-ЯЁа-яёA-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
# Words that look like calls but are BSL keywords
_BSL_KEYWORDS = frozenset(
    {
        "если",
        "пока",
        "для",
        "каждого",
        "из",
        "по",
        "цикл",
        "процедура",
        "функция",
        "перем",
        "возврат",
        "новый",
        "попытка",
        "исключение",
        "конецпопытки",
        "if",
        "while",
        "for",
        "each",
        "in",
        "do",
        "loop",
        "procedure",
        "function",
        "var",
        "return",
        "new",
        "try",
        "except",
        "endtry",
    }
)


@dataclass
class Call:
    """Represents a single call site in a BSL source file."""

    caller_file: str
    caller_line: int  # 1-based
    caller_name: str | None  # enclosing procedure/function name
    callee_name: str
    caller_character: int = 0  # 0-based column of callee token
    callee_args_count: int = 0
    receiver_expression: str | None = None
    receiver_line: int = 0
    receiver_character: int = 0
    receiver_end_line: int = 0
    receiver_end_character: int = 0
    receiver_node: Any | None = field(default=None, repr=False, compare=False)


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


def _root_source_lines(root: Any) -> list[str]:
    full = getattr(root, "text", None) or b""
    if isinstance(full, bytes):
        return full.decode("utf-8", errors="replace").splitlines()
    return str(full).splitlines()


def _extract_from_ts(root: Any, file_path: str) -> list[Call]:
    lines = _root_source_lines(root)
    calls: list[Call] = []
    _visit_for_calls(root, calls, file_path, container=None, lines=lines)
    return calls


def _visit_for_calls(
    node: Any,
    calls: list[Call],
    file_path: str,
    container: str | None,
    lines: list[str],
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

    # BSL grammar uses `method_call` for all calls:
    # direct:  method_call { identifier, arguments }
    # chained: call_expression { access, ".", method_call }
    if node_type == "method_call":
        call = _ts_method_call_to_record(node, file_path, container, lines)
        if call:
            calls.append(call)

    for child in node.children:
        _visit_for_calls(child, calls, file_path, container, lines)


def _ts_method_call_to_record(
    node: Any, file_path: str, container: str | None, lines: list[str]
) -> Call | None:
    callee_name = ""
    args_count = 0

    for child in node.children:
        ct = child.type
        if ct == "identifier":
            callee_name = _node_text(child)
        elif ct == "arguments":
            args_count = sum(1 for c in child.children if c.type not in ("(", ")", ","))

    if not callee_name or callee_name.lower() in _BSL_KEYWORDS:
        return None

    line_idx = node.start_point[0]
    line_text = lines[line_idx] if line_idx < len(lines) else ""
    caller_character = utf8_byte_offset_to_lsp_character(line_text, node.start_point[1])
    receiver_node = _qualified_receiver_node(node)
    receiver_expression = _node_text(receiver_node) if receiver_node is not None else None
    receiver_line = 0
    receiver_character = 0
    receiver_end_line = 0
    receiver_end_character = 0
    if receiver_node is not None:
        receiver_start_idx = int(receiver_node.start_point[0])
        receiver_end_idx = int(receiver_node.end_point[0])
        receiver_start_text = (
            lines[receiver_start_idx] if 0 <= receiver_start_idx < len(lines) else ""
        )
        receiver_end_text = lines[receiver_end_idx] if 0 <= receiver_end_idx < len(lines) else ""
        receiver_line = receiver_start_idx + 1
        receiver_character = utf8_byte_offset_to_lsp_character(
            receiver_start_text,
            receiver_node.start_point[1],
        )
        receiver_end_line = receiver_end_idx + 1
        receiver_end_character = utf8_byte_offset_to_lsp_character(
            receiver_end_text,
            receiver_node.end_point[1],
        )

    return Call(
        caller_file=file_path,
        caller_line=node.start_point[0] + 1,
        caller_character=caller_character,
        caller_name=container,
        callee_name=callee_name,
        callee_args_count=args_count,
        receiver_expression=receiver_expression,
        receiver_line=receiver_line,
        receiver_character=receiver_character,
        receiver_end_line=receiver_end_line,
        receiver_end_character=receiver_end_character,
        receiver_node=receiver_node,
    )


def _qualified_receiver_node(method_call: Any) -> Any | None:
    """Return the CST subtree immediately left of a qualified method call."""
    parent = getattr(method_call, "parent", None)
    if getattr(parent, "type", None) not in {"access", "call_expression", "property_access"}:
        return None
    children = list(getattr(parent, "children", ()) or ())
    try:
        method_index = children.index(method_call)
    except ValueError:
        return None
    for child in reversed(children[:method_index]):
        if getattr(child, "type", None) in {
            "access",
            "call_expression",
            "identifier",
            "property_access",
        }:
            return child
    return None


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
            rest = line[m.end() :]
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
                    caller_character=m.start("name"),
                    caller_name=current_proc,
                    callee_name=name,
                    callee_args_count=args_count,
                )
            )

    return calls


def _definition_receiver_name(file_path: str) -> str | None:
    """Best-effort module/object name for *file_path* (e.g. ``ЗарплатаКадрыПовтИсп``
    for a common module, ``Организации`` for a catalog manager module), for
    matching against a qualified call site's raw ``receiver_expression``.

    Deferred import: ``config_helpers`` pulls in ``document_snapshot``, which
    imports ``Call`` from this module — a module-level import here would cycle.
    """
    from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (  # noqa: PLC0415
        current_module_xml_context,
    )

    return current_module_xml_context(file_path).get("object_name")


# ---------------------------------------------------------------------------
# Call graph builder
# ---------------------------------------------------------------------------


def build_call_graph(
    index: SymbolIndex,
    symbol_name: str,
    depth: int = 5,
    file_filter: str | None = None,
) -> dict:
    """
    Build a JSON-serializable call graph rooted at *symbol_name*.

    Returns a dict with:
      - ``name``: the queried symbol
      - ``callers``: recursive list of who calls this symbol (up to *depth*)
      - ``callees``: list of symbols resolved from the index (definitions)
      - ``definition``: definition location, if found and unambiguous
      - ``ambiguous`` / ``candidates``: present instead of a resolved graph
        when *symbol_name* matches multiple definitions and *file_filter*
        doesn't narrow it down to exactly one.
      - ``candidate_count`` / ``candidates_truncated``: total ambiguity
        cardinality and whether the stable 20-item candidate page is partial.

    For an exported symbol resolved via *file_filter* out of several
    same-named definitions, ``callers`` attributes qualified call sites
    (``Модуль.Функция(...)``) to this definition only when the qualifier
    names its own module/object; bare/unqualified call sites are still
    returned unfiltered because their target remains unresolved.

    Args:
        index:       SymbolIndex instance to query.
        symbol_name: Name of the procedure/function to analyse.
        depth:       Maximum recursion depth for callers tree.
        file_filter: Optional substring to restrict definition resolution to
                     a specific owner file (same convention as
                     ``SymbolIndex.find_symbol``'s ``file_filter``).
    """
    visited_callers: set[str] = set()

    def _callers_tree(
        name: str,
        d: int,
        scope_file: str | None,
        receiver_name: str | None = None,
    ) -> list[dict]:
        if d <= 0 or name in visited_callers:
            return []
        visited_callers.add(name)
        rows = index.find_callers(
            name, limit=20, scope_file=scope_file, receiver_name=receiver_name
        )
        result = []
        for row in rows:
            caller = row.get("caller_name") or row.get("caller_file", "")
            result.append(
                {
                    "caller_name": row.get("caller_name"),
                    "caller_file": row.get("caller_file"),
                    "caller_line": row.get("caller_line"),
                    "callers": _callers_tree(caller, d - 1, None) if row.get("caller_name") else [],
                }
            )
        return result

    # Resolve callees by looking up the symbol's calls in the index
    definitions, candidate_count = index.find_symbol_candidates(
        symbol_name,
        file_filter=file_filter,
        limit=20,
    )

    if candidate_count > 1:
        return {
            "name": symbol_name,
            "definition": {"file": None, "line": None, "signature": None},
            "ambiguous": True,
            "candidate_count": candidate_count,
            "candidates_truncated": candidate_count > len(definitions),
            "candidates": [
                {
                    "file": d["file_path"],
                    "line": d["line"],
                    "signature": d.get("signature"),
                }
                for d in definitions
            ],
            "callers": [],
            "callees": [],
        }

    definition = definitions[0] if definitions else None

    # A non-exported symbol can only be called (unqualified) from within its
    # own module, so scope callers to the defining file to avoid attributing
    # an unrelated same-named local procedure's callers to this definition.
    #
    # An exported symbol has no such file scope. If *file_filter* was needed
    # to resolve `definition` to one specific candidate, the bare name is
    # ambiguous workspace-wide (candidate_count above already reflects the
    # *filtered* count — always 1 here — so ambiguity must be re-checked
    # without file_filter). In that case, qualified callers
    # (`Модуль.Функция(...)`) do carry the owning module/object name — match
    # that against this definition's own module/object name to avoid
    # attributing a qualified call to a *different* same-named definition.
    # Bare/unqualified callers stay unscoped because their target remains
    # unresolved.
    scope_file = None
    receiver_name = None
    if definition is not None:
        if not definition.get("is_export"):
            scope_file = definition["file_path"]
        elif file_filter is not None:
            _, total_candidate_count = index.find_symbol_candidates(symbol_name, limit=1)
            if total_candidate_count > 1:
                receiver_name = _definition_receiver_name(definition["file_path"])

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
            callees_raw = [c for c in callees_raw if start <= c.get("caller_line", 0) <= end]

    return {
        "name": symbol_name,
        "definition": {
            "file": definition["file_path"] if definition else None,
            "line": definition["line"] if definition else None,
            "signature": definition["signature"] if definition else None,
        },
        "callers": _callers_tree(symbol_name, depth, scope_file, receiver_name),
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
