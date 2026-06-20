"""Helpers for diagnostics over parsed SDBL tree-sitter CST."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

QUERY_METADATA_ROOTS: frozenset[str] = frozenset(
    {
        "бизнеспроцесс",
        "businessprocess",
        "документ",
        "document",
        "журналдокументов",
        "documentjournal",
        "справочник",
        "catalog",
        "перечисление",
        "enum",
        "планвидовхарактеристик",
        "chartofcharacteristictypes",
        "планывидовхарактеристик",
        "chartsofcharacteristictypes",
        "плансчетов",
        "chartofaccounts",
        "планысчетов",
        "chartsofaccounts",
        "планвидоврасчета",
        "chartofcalculationtypes",
        "регистрсведений",
        "informationregister",
        "регистрнакопления",
        "accumulationregister",
        "регистрбухгалтерии",
        "accountingregister",
        "регистррасчета",
        "calculationregister",
        "задача",
        "task",
        "планобмена",
        "exchangeplan",
        "внешнийисточникданных",
        "externaldatasource",
        "константа",
        "constant",
        "отчет",
        "report",
        "обработка",
        "dataprocessor",
    }
)


def node_text(node: Any) -> str:
    text = getattr(node, "text", b"")
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def iter_nodes(node: Any, node_type: str):
    if getattr(node, "type", None) == node_type:
        yield node
    for child in getattr(node, "children", []) or []:
        yield from iter_nodes(child, node_type)


def first_named_child(node: Any, node_type: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == node_type:
            return child
    return None


def ancestor(node: Any, node_type: str) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == node_type:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def has_ancestor(node: Any, node_type: str) -> bool:
    return ancestor(node, node_type) is not None


def child_field_name(parent: Any, child: Any) -> str:
    children = getattr(parent, "children", []) or []
    for idx, candidate in enumerate(children):
        if getattr(candidate, "id", None) != getattr(child, "id", None):
            continue
        try:
            return parent.field_name_for_child(idx) or ""
        except Exception:
            return ""
    return ""


def child_by_field_name(node: Any, field_name: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if child_field_name(node, child) == field_name:
            return child
    return None


def source_alias_name(node: Any) -> str | None:
    alias_node = first_named_child(node, "source_alias")
    if alias_node is None:
        return None
    ident = first_named_child(alias_node, "identifier")
    if ident is None:
        return None
    name = node_text(ident).strip()
    return name or None


def dotted_identifier_parts(node: Any) -> tuple[str, ...]:
    return tuple(
        node_text(child).strip()
        for child in getattr(node, "children", []) or []
        if getattr(child, "type", None) == "identifier" and node_text(child).strip()
    )


def function_call_name(node: Any) -> str:
    name_node = child_by_field_name(node, "name") or first_named_child(node, "identifier")
    return node_text(name_node).strip() if name_node is not None else ""


def is_inside_isnull_function(node: Any) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == "function_call":
            if function_call_name(parent).casefold() in {"естьnull", "isnull"}:
                return True
        parent = getattr(parent, "parent", None)
    return False


def is_inside_is_null_predicate(node: Any) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == "null_check_expression":
            return True
        parent = getattr(parent, "parent", None)
    return False


@dataclass(frozen=True)
class NullableJoinFieldUse:
    node: Any
    alias: str
    scope_node: Any


@dataclass(frozen=True)
class SelectTopWithoutOrder:
    node: Any
    limit: str
    query_has_union: bool
    select_has_where: bool


@dataclass(frozen=True)
class QuerySourceUse:
    node: Any
    source: str


def _direct_named_child(node: Any, node_type: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == node_type:
            return child
    return None


def query_source_uses(root: Any) -> list[QuerySourceUse]:
    result: list[QuerySourceUse] = []
    for node in iter_nodes(root, "table_source"):
        source_node = _direct_named_child(node, "dotted_identifier") or _direct_named_child(
            node, "identifier"
        )
        if source_node is None:
            continue
        source = node_text(source_node).strip()
        if source:
            result.append(QuerySourceUse(node=source_node, source=source))
    for node in iter_nodes(root, "join_clause"):
        source_node = _direct_named_child(node, "dotted_identifier") or _direct_named_child(
            node, "identifier"
        )
        if source_node is None:
            continue
        source = node_text(source_node).strip()
        if source:
            result.append(QuerySourceUse(node=source_node, source=source))
    return result


def query_temp_table_names(root: Any) -> frozenset[str]:
    names: set[str] = set()
    for into_clause in iter_nodes(root, "into_clause"):
        ident = first_named_child(into_clause, "identifier")
        if ident is None:
            continue
        name = node_text(ident).strip()
        if name:
            names.add(name.casefold())
    return frozenset(names)


def _join_kind(join_node: Any) -> str:
    kind_node = first_named_child(join_node, "join_kind")
    if kind_node is None:
        return ""
    return node_text(kind_node).casefold()


def _joined_alias(join_node: Any) -> str | None:
    alias_node = None
    for child in getattr(join_node, "children", []) or []:
        if getattr(child, "type", None) == "source_alias":
            alias_node = child
    if alias_node is None:
        return None
    ident = first_named_child(alias_node, "identifier")
    if ident is None:
        return None
    name = node_text(ident).strip()
    return name.casefold() if name else None


def _base_alias(join_node: Any) -> str | None:
    table_source = ancestor(join_node, "table_source")
    if table_source is None:
        return None
    return (source_alias_name(table_source) or "").casefold() or None


def _has_not_keyword(node: Any) -> bool:
    return any(
        getattr(child, "type", None) == "NOT_KEYWORD"
        for child in getattr(node, "children", []) or []
    )


def _is_negated_by_parent(node: Any, boundary: Any) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None and parent is not boundary:
        if _has_not_keyword(parent):
            return True
        parent = getattr(parent, "parent", None)
    return False


def _null_checked_aliases(where_clause: Any | None, nullable_aliases: set[str]) -> set[str]:
    if where_clause is None:
        return set()
    checked: set[str] = set()
    for null_check in iter_nodes(where_clause, "null_check_expression"):
        is_not_null = _has_not_keyword(null_check) or _is_negated_by_parent(
            null_check, where_clause
        )
        if not is_not_null:
            continue
        for dotted in iter_nodes(null_check, "dotted_identifier"):
            parts = dotted_identifier_parts(dotted)
            if len(parts) >= 2 and parts[0].casefold() in nullable_aliases:
                checked.add(parts[0].casefold())
    return checked


def nullable_join_aliases(select_section_node: Any) -> set[str]:
    aliases: set[str] = set()
    for join_node in iter_nodes(select_section_node, "join_clause"):
        kind = _join_kind(join_node)
        joined_alias = _joined_alias(join_node)
        base_alias = _base_alias(join_node)
        if "левое" in kind or "left" in kind:
            if joined_alias:
                aliases.add(joined_alias)
        elif "правое" in kind or "right" in kind:
            if base_alias:
                aliases.add(base_alias)
        elif "полное" in kind or "full" in kind:
            if joined_alias:
                aliases.add(joined_alias)
            if base_alias:
                aliases.add(base_alias)
    return aliases


def nullable_join_field_uses_without_isnull(root: Any) -> list[NullableJoinFieldUse]:
    result: list[NullableJoinFieldUse] = []
    for select_section in iter_nodes(root, "select_section"):
        nullable_aliases = nullable_join_aliases(select_section)
        if not nullable_aliases:
            continue
        field_list = first_named_child(select_section, "field_list")
        where_clause = first_named_child(select_section, "where_clause")
        nullable_aliases -= _null_checked_aliases(where_clause, nullable_aliases)
        if not nullable_aliases:
            continue
        for scope_node in [field_list, where_clause]:
            if scope_node is None:
                continue
            for dotted in iter_nodes(scope_node, "dotted_identifier"):
                parts = dotted_identifier_parts(dotted)
                if len(parts) < 2 or parts[0].casefold() not in nullable_aliases:
                    continue
                if is_inside_isnull_function(dotted) or is_inside_is_null_predicate(dotted):
                    continue
                result.append(
                    NullableJoinFieldUse(node=dotted, alias=parts[0], scope_node=select_section)
                )
    return result


def _direct_child(node: Any, node_type: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == node_type:
            return child
    return None


def _same_node(left: Any | None, right: Any | None) -> bool:
    if left is None or right is None:
        return False
    return getattr(left, "id", None) == getattr(right, "id", None)


def _select_top_limit(top_clause: Any) -> str:
    for child in getattr(top_clause, "children", []) or []:
        text = node_text(child).strip()
        if text.isdigit():
            return text
    return ""


def select_top_without_order(root: Any) -> list[SelectTopWithoutOrder]:
    """Return SDBL SELECT TOP/FIRST clauses whose query has no deterministic order."""

    result: list[SelectTopWithoutOrder] = []
    for query in iter_nodes(root, "query"):
        has_union = _direct_child(query, "union_clause") is not None
        has_order = _direct_child(query, "order_by_clause") is not None
        if has_order and not has_union:
            continue

        for select_section in iter_nodes(query, "select_section"):
            if not _same_node(ancestor(select_section, "query"), query):
                continue
            top_clause = _direct_child(select_section, "top_clause")
            if top_clause is None:
                continue
            limit = _select_top_limit(top_clause)
            has_where = _direct_child(select_section, "where_clause") is not None
            if limit in {"0", "1"} and (not has_union or has_where):
                continue
            result.append(
                SelectTopWithoutOrder(
                    node=top_clause,
                    limit=limit,
                    query_has_union=has_union,
                    select_has_where=has_where,
                )
            )
    return result
