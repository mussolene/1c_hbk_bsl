"""
BSL parser using tree-sitter.

Primary: tree-sitter-bsl (dedicated BSL grammar package).
Fallback: regex-based extraction if tree-sitter-bsl is not available.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to load tree-sitter with BSL grammar
_TS_AVAILABLE = False
_BSL_LANGUAGE = None

try:
    import tree_sitter_bsl as _ts_bsl
    from tree_sitter import Language
    from tree_sitter import Parser as _TsParser

    _BSL_LANGUAGE = Language(_ts_bsl.language())
    _TS_AVAILABLE = True
    logger.debug("tree-sitter BSL grammar loaded successfully")
except Exception as exc:  # pragma: no cover
    logger.warning(
        "tree-sitter BSL grammar not available (%s). Using regex fallback.", exc
    )


@dataclass
class BslNode:
    """Lightweight representation of a tree-sitter node (or regex-parsed equivalent)."""

    type: str
    text: str
    start_point: tuple[int, int]  # (row, col) — 0-based
    end_point: tuple[int, int]
    children: list[BslNode] = field(default_factory=list)
    is_error: bool = False

    @property
    def start_line(self) -> int:
        """1-based line number."""
        return self.start_point[0] + 1

    @property
    def start_col(self) -> int:
        """0-based column."""
        return self.start_point[1]


class BslParser:
    """
    Parses BSL source files using tree-sitter (or regex fallback).

    Example::

        parser = BslParser()
        tree = parser.parse_file("/path/to/module.bsl")
        errors = parser.extract_errors(tree)
    """

    def __init__(self) -> None:
        self._ts_parser: Any = None
        if _TS_AVAILABLE:
            self._ts_parser = _TsParser(_BSL_LANGUAGE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(self, path: str | Path) -> Any:
        """
        Parse a .bsl file and return a Tree object.

        Returns a tree-sitter Tree when tree-sitter is available,
        or a _RegexTree stub when running in fallback mode.
        """
        content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        return self.parse_content(content, file_path=str(path))

    def parse_content(self, content: str, file_path: str = "<string>") -> Any:
        """
        Parse BSL source code from a string.

        Args:
            content: BSL source code.
            file_path: Used for error messages only.

        Returns:
            tree-sitter Tree or _RegexTree fallback.
        """
        if _TS_AVAILABLE and self._ts_parser is not None:
            try:
                tree = self._ts_parser.parse(content.encode("utf-8"))
                return tree
            except Exception as exc:  # pragma: no cover
                logger.warning("tree-sitter parse error for %s: %s. Using fallback.", file_path, exc)

        return _RegexTree(content, file_path=file_path)

    def extract_errors(self, tree: Any) -> list[dict]:
        """
        Extract syntax error nodes from a parsed tree.

        Returns a list of dicts with keys:
            - line (1-based)
            - column (0-based)
            - end_line (1-based)
            - end_column (0-based)
            - message
        """
        if isinstance(tree, _RegexTree):
            return tree.errors

        errors: list[dict] = []
        self._collect_errors(tree.root_node, errors)
        return errors

    def get_root_node(self, tree: Any) -> Any:
        """Return the root node of the tree (tree-sitter Node or _RegexNode)."""
        if isinstance(tree, _RegexTree):
            return tree.root_node
        return tree.root_node

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_errors(self, node: Any, errors: list[dict]) -> None:
        """Recursively collect ERROR and MISSING nodes from a tree-sitter tree."""
        if node.type in ("ERROR", "error") or node.is_missing:
            errors.append(
                {
                    "line": node.start_point[0] + 1,
                    "column": node.start_point[1],
                    "end_line": node.end_point[0] + 1,
                    "end_column": node.end_point[1],
                    "message": f"Syntax error near '{node.text.decode('utf-8', errors='replace')[:40]}'",
                }
            )
        for child in node.children:
            self._collect_errors(child, errors)


# ---------------------------------------------------------------------------
# Regex-based fallback tree
# ---------------------------------------------------------------------------

# Patterns for BSL constructs
_RE_PROCEDURE = re.compile(
    r"^(?P<indent>\s*)(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROCEDURE = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_CALL = re.compile(
    r"\b(?P<name>\w+)\s*\(",
    re.IGNORECASE,
)
_RE_VAR = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<name>\w+)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>.+)$",
    re.IGNORECASE | re.MULTILINE,
)


class _RegexNode:
    """Minimal node returned by the regex fallback tree."""

    def __init__(
        self,
        type: str,
        text: str,
        start_point: tuple[int, int],
        end_point: tuple[int, int],
        children: list[_RegexNode] | None = None,
    ) -> None:
        self.type = type
        self.text = text
        self.start_point = start_point
        self.end_point = end_point
        self.children: list[_RegexNode] = children or []
        self.is_missing = False


class _RegexTree:
    """
    Regex-based pseudo-tree used when tree-sitter is not available.

    This provides just enough structure for the analysis layer to
    extract symbols, calls, and basic diagnostics without full parsing.
    """

    def __init__(self, content: str, file_path: str = "<string>") -> None:
        self.content = content
        self.file_path = file_path
        self.errors: list[dict] = []
        self.root_node = self._build(content)

    def _build(self, content: str) -> _RegexNode:
        lines = content.splitlines()
        children: list[_RegexNode] = []

        for m in _RE_PROCEDURE.finditer(content):
            line_no = content[: m.start()].count("\n")
            node = _RegexNode(
                type="procedure_definition",
                text=m.group(0),
                start_point=(line_no, m.start(0) - content.rfind("\n", 0, m.start(0)) - 1),
                end_point=(line_no, m.end(0)),
                children=[
                    _RegexNode(
                        "identifier",
                        m.group("name"),
                        (line_no, 0),
                        (line_no, len(m.group("name"))),
                    )
                ],
            )
            children.append(node)

        for m in _RE_CALL.finditer(content):
            line_no = content[: m.start()].count("\n")
            children.append(
                _RegexNode(
                    "call_expression",
                    m.group(0),
                    (line_no, 0),
                    (line_no, len(m.group(0))),
                )
            )

        for m in _RE_VAR.finditer(content):
            line_no = content[: m.start()].count("\n")
            children.append(
                _RegexNode(
                    "var_statement",
                    m.group(0),
                    (line_no, 0),
                    (line_no, len(m.group(0))),
                )
            )

        for m in _RE_REGION.finditer(content):
            line_no = content[: m.start()].count("\n")
            children.append(
                _RegexNode(
                    "preprocessor_region",
                    m.group(0),
                    (line_no, 0),
                    (line_no, len(m.group(0))),
                )
            )

        total_lines = len(lines)
        return _RegexNode(
            type="module",
            text=content[:80],
            start_point=(0, 0),
            end_point=(total_lines, 0),
            children=children,
        )
