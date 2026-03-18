"""
Symbol extraction from BSL parse trees.

Extracts procedures, functions, and module-level variable declarations
from a tree-sitter Tree (or _RegexTree fallback).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Regex fallbacks (used when tree-sitter node types differ)
_RE_PROC_HEADER = re.compile(
    r"^(?:Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE,
)
_RE_DOC_LINE = re.compile(r"^\s*//\s?(?P<text>.*)$")


@dataclass
class Symbol:
    """Represents a single BSL symbol (procedure, function, or variable)."""

    name: str
    kind: str  # 'procedure' | 'function' | 'variable'
    line: int  # 1-based
    character: int  # 0-based column
    end_line: int
    end_character: int
    is_export: bool = False
    container: str | None = None  # enclosing procedure/function name
    signature: str = ""
    doc_comment: str = ""
    file_path: str = ""


def extract_symbols(tree: Any, file_path: str) -> list[Symbol]:
    """
    Extract all symbols from a parsed BSL tree.

    Works with both tree-sitter Tree objects and _RegexTree fallback instances.

    Args:
        tree:      Parsed tree (tree-sitter or regex fallback).
        file_path: Path of the source file (for Symbol.file_path).

    Returns:
        List of Symbol dataclasses, ordered by line number.
    """
    # Check if this is a real tree-sitter tree
    if hasattr(tree, "root_node") and hasattr(tree.root_node, "children"):
        root = tree.root_node
        if hasattr(root, "type") and root.type not in ("module", "source_file"):
            # Might be a tree-sitter tree — try the TS extractor first
            pass

        # Determine backend: real tree-sitter nodes have .text as bytes
        node_text = root.children[0].text if root.children else None
        is_ts = isinstance(node_text, (bytes, type(None))) and not isinstance(node_text, str)

        if is_ts:
            return _extract_from_ts(tree, file_path)

    # Fallback: source-code based regex extraction
    if hasattr(tree, "content"):
        return _extract_from_source(tree.content, file_path)

    return []


# ---------------------------------------------------------------------------
# Tree-sitter extraction
# ---------------------------------------------------------------------------

def _extract_from_ts(tree: Any, file_path: str) -> list[Symbol]:
    """Extract symbols using tree-sitter node types."""
    symbols: list[Symbol] = []
    source_bytes: bytes = tree.root_node.text if hasattr(tree.root_node, "text") else b""

    # Collect source lines for doc-comment extraction
    try:
        source_lines = source_bytes.decode("utf-8", errors="replace").splitlines()
    except Exception:
        source_lines = []

    _visit_node(tree.root_node, symbols, file_path, source_lines, container=None)
    return sorted(symbols, key=lambda s: s.line)


def _visit_node(
    node: Any,
    symbols: list[Symbol],
    file_path: str,
    source_lines: list[str],
    container: str | None,
) -> None:
    """Recursively walk tree-sitter nodes to extract symbols."""
    node_type = node.type if hasattr(node, "type") else ""

    if node_type in ("procedure_definition", "function_definition"):
        sym = _ts_proc_to_symbol(node, file_path, source_lines, container)
        if sym:
            symbols.append(sym)
            # Recurse into procedure body to find nested vars
            for child in node.children:
                _visit_node(child, symbols, file_path, source_lines, container=sym.name)
        return

    if node_type in ("var_definition", "var_statement"):
        sym = _ts_var_to_symbol(node, file_path, container)
        if sym:
            symbols.append(sym)
        return

    for child in node.children:
        _visit_node(child, symbols, file_path, source_lines, container)


def _ts_proc_to_symbol(
    node: Any,
    file_path: str,
    source_lines: list[str],
    container: str | None,
) -> Symbol | None:
    """Convert a procedure/function tree-sitter node to a Symbol."""
    name = ""
    params: list[str] = []
    is_export = False

    for child in node.children:
        ct = child.type
        if ct == "identifier":
            name = _node_text(child)
        elif ct == "parameters":
            params = [_node_text(p) for p in child.children if p.type == "parameter"]
        elif ct == "EXPORT_KEYWORD":
            is_export = True

    if not name:
        return None

    kind = "function" if node.type == "function_definition" else "procedure"
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    signature = f"{kind.capitalize()} {name}({', '.join(params)})"
    if is_export:
        signature += " Export"

    doc_comment = _extract_doc_comment(source_lines, start_line - 1)

    return Symbol(
        name=name,
        kind=kind,
        line=start_line,
        character=node.start_point[1],
        end_line=end_line,
        end_character=node.end_point[1],
        is_export=is_export,
        container=container,
        signature=signature,
        doc_comment=doc_comment,
        file_path=file_path,
    )


def _ts_var_to_symbol(node: Any, file_path: str, container: str | None) -> Symbol | None:
    """Convert a var declaration tree-sitter node to a Symbol."""
    name = ""
    is_export = False

    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child)
        elif child.type == "EXPORT_KEYWORD":
            is_export = True

    if not name:
        return None

    return Symbol(
        name=name,
        kind="variable",
        line=node.start_point[0] + 1,
        character=node.start_point[1],
        end_line=node.end_point[0] + 1,
        end_character=node.end_point[1],
        is_export=is_export,
        container=container,
        signature=f"Var {name}",
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# Regex-based extraction (fallback)
# ---------------------------------------------------------------------------

_RE_PROC_FULL = re.compile(
    r"^(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_VAR_DECL = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<name>\w+)(?:\s*(?:,\s*\w+)*)?\s*(?:(?:Экспорт|Export)\s*)?;",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_from_source(content: str, file_path: str) -> list[Symbol]:
    """Regex-based symbol extraction for fallback mode."""
    symbols: list[Symbol] = []
    lines = content.splitlines()

    # Track procedure start/end positions for end-line calculation
    proc_starts: list[tuple[int, re.Match]] = []  # (line_idx, match)
    end_positions: list[int] = []

    for m in _RE_PROC_FULL.finditer(content):
        line_idx = content[: m.start()].count("\n")
        proc_starts.append((line_idx, m))

    for m in _RE_END_PROC.finditer(content):
        line_idx = content[: m.start()].count("\n")
        end_positions.append(line_idx)

    # Match procedures to their end lines
    sorted_starts = sorted(proc_starts, key=lambda x: x[0])

    for _idx, (line_idx, m) in enumerate(sorted_starts):
        kw = m.group("kw").lower()
        kind = "function" if kw in ("функция", "function") else "procedure"
        name = m.group("name")
        params_str = m.group("params").strip()
        is_export = bool(m.group("export"))

        # Find the next end position after this start
        end_line_idx = line_idx + 5  # default fallback
        for ep in sorted(end_positions):
            if ep > line_idx:
                end_line_idx = ep
                break

        signature = f"{kind.capitalize()} {name}({params_str})"
        if is_export:
            signature += " Export"

        doc_comment = _extract_doc_comment(lines, line_idx)

        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=line_idx + 1,
                character=len(m.group(0)) - len(m.group(0).lstrip()),
                end_line=end_line_idx + 1,
                end_character=0,
                is_export=is_export,
                container=None,
                signature=signature,
                doc_comment=doc_comment,
                file_path=file_path,
            )
        )

    # Variables
    for m in _RE_VAR_DECL.finditer(content):
        line_idx = content[: m.start()].count("\n")
        name = m.group("name")
        is_export = "экспорт" in m.group(0).lower() or "export" in m.group(0).lower()
        symbols.append(
            Symbol(
                name=name,
                kind="variable",
                line=line_idx + 1,
                character=0,
                end_line=line_idx + 1,
                end_character=len(m.group(0)),
                is_export=is_export,
                container=None,
                signature=f"Var {name}",
                file_path=file_path,
            )
        )

    return sorted(symbols, key=lambda s: s.line)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _node_text(node: Any) -> str:
    """Extract text from a tree-sitter node (handles bytes or str)."""
    if node.text is None:
        return ""
    if isinstance(node.text, bytes):
        return node.text.decode("utf-8", errors="replace")
    return str(node.text)


def _extract_doc_comment(lines: list[str], proc_line_idx: int) -> str:
    """
    Extract leading // comment block immediately above the procedure definition.

    Reads backwards from *proc_line_idx* collecting comment lines.
    """
    doc_lines: list[str] = []
    idx = proc_line_idx - 1
    while idx >= 0:
        stripped = lines[idx].strip()
        m = _RE_DOC_LINE.match(lines[idx])
        if m:
            doc_lines.append(m.group("text"))
            idx -= 1
        elif stripped == "":
            idx -= 1  # skip blank lines
            break
        else:
            break
    return "\n".join(reversed(doc_lines))
