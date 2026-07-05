from __future__ import annotations

import re
from typing import Any

from onec_hbk_bsl.analysis.bsl_typo.lexicon import CODE_TOKEN_EXACT_IGNORE, SOURCE_TYPO_TOKENS
from onec_hbk_bsl.analysis.bsl_typo.models import SpellCandidate
from onec_hbk_bsl.analysis.bsl_typo.tokenization import contains_cyrillic_letter

FORMAT_STRING_RU = "Л=|ЧЦ=|ЧДЦ=|ЧС=|ЧРД=|ЧРГ=|ЧН=|ЧВН=|ЧГ=|ЧО=|ДФ=|ДЛФ=|ДП=|БЛ=|БИ="
FORMAT_STRING_EN = "|L=|ND=|NFD=|NS=|NDS=|NGS=|NZ=|NLZ=|NG=|NN=|NF=|DF=|DLF=|DE=|BF=|BT="
FORMAT_STRING_PATTERN = re.compile(FORMAT_STRING_RU + FORMAT_STRING_EN, re.IGNORECASE)
QUOTE_PATTERN = re.compile('"')


def collect_spell_candidates(
    *,
    tree: Any,
    nodes_by_type: dict[str, list[Any]] | None = None,
) -> list[SpellCandidate]:
    root = getattr(tree, "root_node", None)
    if root is None:
        return []
    source_bytes = getattr(root, "text", None)
    if not isinstance(source_bytes, (bytes, bytearray)):
        return []
    line_starts = _compute_line_starts(source_bytes)

    candidates: list[SpellCandidate] = []
    if nodes_by_type is None:
        nodes_by_type = _collect_candidate_nodes(root)

    for node in nodes_by_type.get("string", []):
        text = _node_text(node)
        if FORMAT_STRING_PATTERN.search(text):
            continue
        inner = QUOTE_PATTERN.sub("", text).strip()
        _append_candidate(
            node=node,
            source_text=text,
            inner=inner,
            source_bytes=source_bytes,
            line_starts=line_starts,
            kind="string",
            out=candidates,
        )

    for node in nodes_by_type.get("identifier", []):
        text = _node_text(node)
        if not contains_cyrillic_letter(text) or not _identifier_typo_context_ok(node):
            continue
        _append_candidate(
            node=node,
            source_text=text,
            inner=text.strip(),
            source_bytes=source_bytes,
            line_starts=line_starts,
            kind="code",
            exact_ignore=CODE_TOKEN_EXACT_IGNORE,
            out=candidates,
        )

    for node in nodes_by_type.get("property", []):
        text = _node_text(node)
        if not contains_cyrillic_letter(text) or not _property_typo_context_ok(node):
            continue
        _append_candidate(
            node=node,
            source_text=text,
            inner=text.strip(),
            source_bytes=source_bytes,
            line_starts=line_starts,
            kind="code",
            exact_ignore=CODE_TOKEN_EXACT_IGNORE,
            out=candidates,
        )

    candidates.extend(_collect_forced_method_candidates(source_bytes))
    candidates.extend(_collect_forced_source_token_candidates(source_bytes))
    return candidates


def _collect_candidate_nodes(root: Any) -> dict[str, list[Any]]:
    nodes_by_type: dict[str, list[Any]] = {"identifier": [], "property": [], "string": []}
    stack: list[Any] = [root]
    while stack:
        node = stack.pop()
        node_type = getattr(node, "type", None)
        if node_type in nodes_by_type:
            nodes_by_type[node_type].append(node)
        for child in reversed(getattr(node, "children", ()) or ()):
            stack.append(child)
    return nodes_by_type


def _node_text(node: Any) -> str:
    raw = node.text
    return (
        raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    )


def _append_candidate(
    *,
    node: Any,
    source_text: str,
    inner: str,
    source_bytes: bytes,
    line_starts: list[int],
    kind: str,
    out: list[SpellCandidate],
    exact_ignore: frozenset[str] = frozenset(),
) -> None:
    if not inner:
        return
    if kind == "string" and "\n" in source_text:
        return

    anchor_start_byte = node.start_byte
    if kind == "string":
        quote = source_text.find('"')
        if quote >= 0:
            anchor_start_byte += len(source_text[:quote].encode("utf-8"))
    elif kind == "code":
        m = re.match(r"[ \t]+", source_text)
        if m:
            anchor_start_byte += len(m.group(0).encode("utf-8"))

    line, character = _line_char_from_node_point(
        node,
        source_bytes,
        anchor_start_byte,
        line_starts=line_starts,
    )
    end_line, end_character = _line_char_from_node_point(
        node,
        source_bytes,
        node.end_byte,
        line_starts=line_starts,
        is_end=True,
    )
    out.append(
        SpellCandidate(
            text=inner,
            line=line,
            character=character,
            end_line=end_line,
            end_character=end_character,
            kind="string" if kind == "string" else "method" if kind == "method" else "code",
            exact_ignore=exact_ignore,
        )
    )


def _collect_forced_method_candidates(source_bytes: bytes) -> list[SpellCandidate]:
    # Keep method-name coverage explicit. Generic method-name spell checking has
    # too many false positives; known typo tokens are selected later by lexicon.
    header_re = re.compile(
        r"^\s*(?:Процедура|Функция|Procedure|Function)\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)",
        re.IGNORECASE,
    )
    source_text = source_bytes.decode("utf-8", errors="replace")
    result: list[SpellCandidate] = []
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        match = header_re.search(line)
        if match is None:
            continue
        name = match.group(1)
        result.append(
            SpellCandidate(
                text=name,
                line=line_no,
                character=match.start(1),
                end_line=line_no,
                end_character=match.start(1) + len(name),
                kind="method",
            )
        )
    return result


def _collect_forced_source_token_candidates(source_bytes: bytes) -> list[SpellCandidate]:
    source_text = source_bytes.decode("utf-8", errors="replace")
    result: list[SpellCandidate] = []
    for token in SOURCE_TYPO_TOKENS:
        token_re = re.compile(
            rf"^\s*(?:Перем|Var)\s+(?P<name>[A-Za-zА-Яа-яЁё_]*{re.escape(token)})\b",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in token_re.finditer(source_text):
            start = match.start("name")
            end = match.end("name")
            line, character = _line_char_from_byte_offset(
                source_bytes,
                len(source_text[:start].encode("utf-8")),
            )
            end_line, end_character = _line_char_from_byte_offset(
                source_bytes,
                len(source_text[:end].encode("utf-8")),
            )
            result.append(
                SpellCandidate(
                    text=match.group("name"),
                    line=line,
                    character=character,
                    end_line=end_line,
                    end_character=end_character,
                    kind="code",
                )
            )
    return result


def _node_inside(outer: Any, inner: Any) -> bool:
    return int(getattr(outer, "start_byte", -1)) <= int(getattr(inner, "start_byte", -2)) and int(
        getattr(inner, "end_byte", -2)
    ) <= int(getattr(outer, "end_byte", -1))


def _identifier_typo_context_ok(node: Any) -> bool:
    if getattr(node, "type", None) != "identifier":
        return False
    parent = node.parent
    if parent is None:
        return False
    if parent.type in ("var_definition", "var_statement"):
        return True
    cur = parent
    while cur is not None:
        if cur.type in ("procedure_definition", "function_definition"):
            return False
        if cur.type == "assignment_statement":
            if not cur.named_children:
                return False
            return _node_inside(cur.named_children[0], node)
        cur = getattr(cur, "parent", None)
    return False


def _property_typo_context_ok(node: Any) -> bool:
    if getattr(node, "type", None) != "property":
        return False
    cur = node.parent
    while cur is not None:
        if cur.type == "assignment_statement":
            if not cur.named_children:
                return False
            return _node_inside(cur.named_children[0], node)
        cur = getattr(cur, "parent", None)
    return False


def _line_char_from_byte_offset(source_bytes: bytes, offset: int) -> tuple[int, int]:
    prefix = source_bytes[:offset]
    line = prefix.count(b"\n") + 1
    line_start = prefix.rfind(b"\n")
    line_bytes = prefix[line_start + 1 :] if line_start >= 0 else prefix
    return line, len(line_bytes.decode("utf-8", errors="ignore"))


def _line_char_from_node_point(
    node: Any,
    source_bytes: bytes,
    offset: int,
    *,
    line_starts: list[int] | None = None,
    is_end: bool = False,
) -> tuple[int, int]:
    point = getattr(node, "end_point" if is_end else "start_point", None)
    if point is not None:
        row = int(getattr(point, "row", -1))
        col = int(getattr(point, "column", -1))
        if row >= 0 and col >= 0:
            return row + 1, _char_from_row_byte_column(
                source_bytes,
                row,
                col,
                line_starts=line_starts,
            )
    return _line_char_from_byte_offset(source_bytes, offset)


def _char_from_row_byte_column(
    source_bytes: bytes,
    row0: int,
    col_bytes: int,
    *,
    line_starts: list[int] | None = None,
) -> int:
    if row0 < 0 or col_bytes <= 0:
        return 0
    total = len(source_bytes)
    if line_starts is not None:
        if row0 >= len(line_starts):
            return 0
        line_start = line_starts[row0]
    else:
        line_start = 0
        cur_row = 0
        while cur_row < row0 and line_start < total:
            nl = source_bytes.find(b"\n", line_start)
            if nl < 0:
                return 0
            line_start = nl + 1
            cur_row += 1
    prefix = source_bytes[line_start : min(line_start + col_bytes, total)]
    return len(prefix.decode("utf-8", errors="ignore"))


def _compute_line_starts(source_bytes: bytes) -> list[int]:
    starts = [0]
    search_from = 0
    total = len(source_bytes)
    while search_from < total:
        nl = source_bytes.find(b"\n", search_from)
        if nl < 0:
            break
        starts.append(nl + 1)
        search_from = nl + 1
    return starts
