"""Shared parsed document snapshot for diagnostics, formatting, and indexing.

The project historically re-parsed the same document and re-walked the same
tree-sitter CST in several layers: diagnostics, formatter, symbol extraction,
call graph extraction, and LSP helpers. This module provides a single lazily
derived snapshot object so those layers can share one parsed view of a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.bsl_string_split import (
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.call_graph import Call, extract_calls
from onec_hbk_bsl.analysis.formatter_structural import tree_has_errors
from onec_hbk_bsl.analysis.symbols import Symbol, extract_symbols
from onec_hbk_bsl.parser.bsl_parser import BslParser

_RE_PROC_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_OPEN = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_CLOSE = re.compile(
    r"^\s*#(?:КонецОбласти|EndRegion)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_QUERY_TEXT_START = re.compile(r'"\s*(?:ВЫБРАТЬ|SELECT)\b', re.IGNORECASE)
_RE_QUERY_INLINE_COMMENT = re.compile(r"\s*//.*$")


@dataclass(frozen=True)
class ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    params: list[str]
    val_params: list[str]
    optional_count: int
    header_col: int = 0
    optional_params: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RegionInfo:
    """#Область / #Region block in the source."""

    name: str
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class QueryTextLineInfo:
    """One logical content line inside an embedded query string block."""

    line_no: int
    content_base: int
    content: str
    head: str
    ended_query: bool


@dataclass(frozen=True)
class QueryTextBlockInfo:
    """Embedded query string block with pre-split logical lines."""

    start_idx: int
    block_lines: tuple[str, ...]
    content_lines: tuple[QueryTextLineInfo, ...]

    @property
    def query_text(self) -> str:
        return "\n".join(self.block_lines)

    @property
    def head_text(self) -> str:
        return "\n".join(line.head for line in self.content_lines)


def _parse_params(params_str: str) -> list[tuple[str, bool, bool]]:
    result: list[tuple[str, bool, bool]] = []
    for raw in split_commas_outside_double_quotes(params_str):
        raw = raw.strip()
        if not raw:
            continue
        is_val = bool(re.match(r"^(?:Знач|Val)\s+", raw, re.IGNORECASE))
        clean = strip_leading_val_keywords(raw)
        is_optional = "=" in clean
        name = clean.split("=")[0].strip()
        if name and re.match(r"^\w+$", name):
            result.append((name, is_val, is_optional))
    return result


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _ts_node_to_proc_info(node: Any) -> ProcInfo | None:
    name = ""
    params: list[str] = []
    val_params: list[str] = []
    optional_count = 0
    is_export = False
    optional_params_list: list[str] = []

    for child in getattr(node, "children", []) or []:
        child_type = getattr(child, "type", None)
        if child_type == "identifier" and not name:
            name = _ts_node_text(child)
        elif child_type == "EXPORT_KEYWORD":
            is_export = True
        elif child_type == "parameters":
            for param in getattr(child, "children", []) or []:
                if getattr(param, "type", None) != "parameter":
                    continue
                param_name = ""
                is_val = False
                has_default = False
                for param_child in getattr(param, "children", []) or []:
                    param_child_type = getattr(param_child, "type", None)
                    if param_child_type == "VAL_KEYWORD":
                        is_val = True
                    elif param_child_type == "identifier" and not param_name:
                        param_name = _ts_node_text(param_child)
                    elif param_child_type == "=":
                        has_default = True
                if param_name:
                    params.append(param_name)
                    if is_val:
                        val_params.append(param_name)
                    if has_default:
                        optional_count += 1
                        optional_params_list.append(param_name)

    if not name:
        return None

    kind = "function" if getattr(node, "type", None) == "function_definition" else "procedure"
    return ProcInfo(
        name=name,
        kind=kind,
        start_idx=node.start_point[0],
        end_idx=node.end_point[0],
        is_export=is_export,
        params=params,
        val_params=val_params,
        optional_count=optional_count,
        header_col=node.start_point[1],
        optional_params=frozenset(optional_params_list),
    )


def _collect_procs_from_node(node: Any, result: list[ProcInfo]) -> None:
    if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
        proc = _ts_node_to_proc_info(node)
        if proc:
            result.append(proc)
        return
    for child in getattr(node, "children", []) or []:
        _collect_procs_from_node(child, result)


def _find_procedures_from_tree(tree: Any) -> list[ProcInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []
    result: list[ProcInfo] = []
    _collect_procs_from_node(root, result)
    return result


def _find_procedures(content: str) -> list[ProcInfo]:
    ends: list[int] = []
    for match in _RE_END_PROC.finditer(content):
        ends.append(content[: match.start()].count("\n"))
    ends.sort()

    result: list[ProcInfo] = []
    for match in _RE_PROC_HEADER.finditer(content):
        start_idx = content[: match.start()].count("\n")
        kw = match.group("kw").lower()
        name = match.group("name")
        params_str = match.group("params") or ""
        is_export = bool(match.group("export"))
        kind = "function" if kw in ("функция", "function") else "procedure"
        header_col = len(match.group("indent"))

        parsed = _parse_params(params_str)
        params = [param[0] for param in parsed]
        val_params = [param[0] for param in parsed if param[1]]
        optional_count = sum(1 for param in parsed if param[2])
        optional_params = frozenset(param[0] for param in parsed if param[2])

        end_idx = start_idx + 5
        for candidate in ends:
            if candidate > start_idx:
                end_idx = candidate
                break

        result.append(
            ProcInfo(
                name=name,
                kind=kind,
                start_idx=start_idx,
                end_idx=end_idx,
                is_export=is_export,
                params=params,
                val_params=val_params,
                optional_count=optional_count,
                header_col=header_col,
                optional_params=optional_params,
            )
        )
    return result


def _find_regions(content: str) -> list[RegionInfo]:
    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    for match in _RE_REGION_OPEN.finditer(content):
        line_idx = content[: match.start()].count("\n")
        opens.append((line_idx, match.group("name")))

    for match in _RE_REGION_CLOSE.finditer(content):
        line_idx = content[: match.start()].count("\n")
        closes.append(line_idx)

    closes_sorted = sorted(closes)
    used_closes: set[int] = set()
    result: list[RegionInfo] = []
    for start_idx, name in sorted(opens, key=lambda item: item[0]):
        end_idx = start_idx + 1
        for candidate in closes_sorted:
            if candidate > start_idx and candidate not in used_closes:
                end_idx = candidate
                used_closes.add(candidate)
                break
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
    return result


def _find_regions_from_tree(tree: Any) -> list[RegionInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), bytes):
        return []

    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) == "preprocessor":
            child_types = {getattr(child, "type", None) for child in getattr(node, "children", [])}
            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0

            if "PREPROC_REGION_KEYWORD" in child_types:
                region_name = ""
                seen_keyword = False
                for child in getattr(node, "children", []) or []:
                    child_type = getattr(child, "type", None)
                    if child_type == "PREPROC_REGION_KEYWORD":
                        seen_keyword = True
                        continue
                    if seen_keyword and child_type == "identifier":
                        region_name = _ts_node_text(child)
                        break
                opens.append((start_idx, region_name))
                return

            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(start_idx)
                return

        for child in getattr(node, "children", []) or []:
            visit(child)

    visit(root)

    closes_sorted = sorted(closes)
    used_closes: set[int] = set()
    result: list[RegionInfo] = []
    for start_idx, name in sorted(opens, key=lambda item: item[0]):
        end_idx = start_idx + 1
        for candidate in closes_sorted:
            if candidate > start_idx and candidate not in used_closes:
                end_idx = candidate
                used_closes.add(candidate)
                break
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
    return result


def _build_proc_node_map(tree: Any) -> dict[tuple[str, int, str], Any]:
    result: dict[tuple[str, int, str], Any] = {}
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return result

    def collect(node: Any) -> None:
        if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
            info = _ts_node_to_proc_info(node)
            if info:
                result[(info.name, info.start_idx, info.kind)] = node
            return
        for child in getattr(node, "children", []) or []:
            collect(child)

    collect(root)
    return result


def _build_query_text_blocks(lines: list[str]) -> list[QueryTextBlockInfo]:
    result: list[QueryTextBlockInfo] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _RE_QUERY_TEXT_START.search(line):
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        while j < len(lines) and (lines[j].lstrip().startswith("|") or not lines[j].strip()):
            block_lines.append(lines[j])
            j += 1

        content_lines: list[QueryTextLineInfo] = []
        for offset, raw_line in enumerate(block_lines):
            stripped = raw_line.rstrip()
            if not stripped:
                continue

            if offset == 0:
                quote_pos = raw_line.find('"')
                if quote_pos < 0:
                    continue
                content_base = quote_pos + 1
                raw_content = raw_line[content_base:]
            else:
                pipe_pos = raw_line.find("|")
                if pipe_pos < 0:
                    continue
                after_pipe = raw_line[pipe_pos + 1 :]
                leading_ws = len(after_pipe) - len(after_pipe.lstrip())
                content_base = pipe_pos + 1 + leading_ws
                raw_content = after_pipe.lstrip()

            content = _RE_QUERY_INLINE_COMMENT.sub("", raw_content).rstrip().lstrip()
            if not content:
                continue

            ended_query = '"' in content
            head = content.split('"', 1)[0].rstrip() if ended_query else content
            if not head:
                if ended_query:
                    break
                continue

            content_lines.append(
                QueryTextLineInfo(
                    line_no=i + offset + 1,
                    content_base=content_base,
                    content=content,
                    head=head,
                    ended_query=ended_query,
                )
            )
            if ended_query:
                break

        result.append(
            QueryTextBlockInfo(
                start_idx=i,
                block_lines=tuple(block_lines),
                content_lines=tuple(content_lines),
            )
        )
        i = j
    return result


@dataclass(slots=True)
class DocumentSnapshot:
    """One parsed view of a BSL document with lazily derived analysis data."""

    path: str
    content: str
    tree: Any

    _lines: list[str] | None = None
    _procs: list[ProcInfo] | None = None
    _regions: list[RegionInfo] | None = None
    _proc_node_map: dict[tuple[str, int, str], Any] | None = None
    _symbols: list[Symbol] | None = None
    _calls: list[Call] | None = None
    _query_blocks: list[QueryTextBlockInfo] | None = None

    @property
    def root_node(self) -> Any | None:
        return getattr(self.tree, "root_node", None)

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            self._lines = self.content.splitlines()
        return self._lines

    @property
    def is_tree_sitter(self) -> bool:
        root = self.root_node
        return root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))

    @property
    def has_parse_errors(self) -> bool:
        root = self.root_node
        if root is None or not self.is_tree_sitter:
            return True
        return tree_has_errors(root)

    @property
    def tree_ok(self) -> bool:
        return self.is_tree_sitter and not self.has_parse_errors

    @property
    def procedures(self) -> list[ProcInfo]:
        if self._procs is None:
            self._procs = (
                _find_procedures_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_procedures(self.content)
            )
        return self._procs

    @property
    def regions(self) -> list[RegionInfo]:
        if self._regions is None:
            self._regions = (
                _find_regions_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_regions(self.content)
            )
            if not self._regions:
                self._regions = _find_regions(self.content)
        return self._regions

    @property
    def proc_node_map(self) -> dict[tuple[str, int, str], Any]:
        if self._proc_node_map is None:
            self._proc_node_map = _build_proc_node_map(self.tree)
        return self._proc_node_map

    @property
    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            self._symbols = extract_symbols(self.tree, file_path=self.path)
        return self._symbols

    @property
    def calls(self) -> list[Call]:
        if self._calls is None:
            self._calls = extract_calls(self.tree, file_path=self.path)
        return self._calls

    @property
    def query_text_blocks(self) -> list[QueryTextBlockInfo]:
        if self._query_blocks is None:
            self._query_blocks = _build_query_text_blocks(self.lines)
        return self._query_blocks


def build_document_snapshot(
    path: str,
    *,
    content: str,
    tree: Any | None = None,
    parser: BslParser | None = None,
) -> DocumentSnapshot:
    """Build a shared snapshot for one BSL document."""

    effective_parser = parser or BslParser()
    effective_tree = (
        tree if tree is not None else effective_parser.parse_content(content, file_path=path)
    )
    return DocumentSnapshot(path=path, content=content, tree=effective_tree)
