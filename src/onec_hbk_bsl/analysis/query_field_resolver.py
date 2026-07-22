"""Resolve SDBL query field chains to specific metadata identities.

Given a parsed SDBL tree (tree-sitter, see `sdbl_cst`) and a metadata field
lookup, resolves dotted field chains like `Алиас.Организация.ГоловнаяОрганизация`
to concrete identities (`Справочник.Организации.ГоловнаяОрганизация`) by walking
FROM/JOIN alias bindings and dereferencing reference-typed fields through the
configuration metadata index (`meta_members.type_info`).

Scope (see docs/contributors/onec-hbk-bsl-query-field-resolver-proposal.md):
field identity
for where-used queries, not query validation. Composite reference types produce
`ambiguous` results with candidates instead of silently picking the first match.

Known limits:
- virtual tables with renamed fields (Остатки/Обороты resource suffixes) fall
  back to base-table field names — suffixed fields resolve to `unknown`;
- `ВЫРАЗИТЬ(...) КАК ...` followed by dereference is not parsed by the current
  SDBL grammar (ERROR node) and is therefore not resolved;
- dynamically built query texts are out of scope by design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from onec_hbk_bsl.analysis.sdbl_cst import (
    child_by_field_name,
    dotted_identifier_parts,
    first_named_child,
    node_text,
)

# ---------------------------------------------------------------------------
# Type token normalization (`meta_members.type_info` -> query-language identity)
# ---------------------------------------------------------------------------

# Designer XML ref prefix (casefold, without "cfg:") -> (kind id, query-language root).
_REF_PREFIX_TO_KIND: dict[str, tuple[str, str]] = {
    "catalogref": ("Catalog", "Справочник"),
    "documentref": ("Document", "Документ"),
    "documentjournalref": ("DocumentJournal", "ЖурналДокументов"),
    "enumref": ("Enum", "Перечисление"),
    "chartofcharacteristictypesref": ("ChartOfCharacteristicTypes", "ПланВидовХарактеристик"),
    "chartofaccountsref": ("ChartOfAccounts", "ПланСчетов"),
    "chartofcalculationtypesref": ("ChartOfCalculationTypes", "ПланВидовРасчета"),
    "businessprocessref": ("BusinessProcess", "БизнесПроцесс"),
    "taskref": ("Task", "Задача"),
    "exchangeplanref": ("ExchangePlan", "ПланОбмена"),
}

_PRIMITIVE_TOKENS: dict[str, str] = {
    "xs:string": "Строка",
    "xs:decimal": "Число",
    "xs:boolean": "Булево",
    "xs:datetime": "Дата",
    "v8:valuestorage": "ХранилищеЗначения",
    "v8:uuid": "УникальныйИдентификатор",
}

# Query-language table root (casefold, ru/en) -> kind id. Only kinds addressable
# as query sources.
_QUERY_ROOT_TO_KIND: dict[str, str] = {
    "справочник": "Catalog",
    "catalog": "Catalog",
    "документ": "Document",
    "document": "Document",
    "журналдокументов": "DocumentJournal",
    "documentjournal": "DocumentJournal",
    "перечисление": "Enum",
    "enum": "Enum",
    "планвидовхарактеристик": "ChartOfCharacteristicTypes",
    "chartofcharacteristictypes": "ChartOfCharacteristicTypes",
    "плансчетов": "ChartOfAccounts",
    "chartofaccounts": "ChartOfAccounts",
    "планвидоврасчета": "ChartOfCalculationTypes",
    "chartofcalculationtypes": "ChartOfCalculationTypes",
    "регистрсведений": "InformationRegister",
    "informationregister": "InformationRegister",
    "регистрнакопления": "AccumulationRegister",
    "accumulationregister": "AccumulationRegister",
    "регистрбухгалтерии": "AccountingRegister",
    "accountingregister": "AccountingRegister",
    "регистррасчета": "CalculationRegister",
    "calculationregister": "CalculationRegister",
    "бизнеспроцесс": "BusinessProcess",
    "businessprocess": "BusinessProcess",
    "задача": "Task",
    "task": "Task",
    "планобмена": "ExchangePlan",
    "exchangeplan": "ExchangePlan",
}

_KIND_TO_QUERY_ROOT: dict[str, str] = {
    "Catalog": "Справочник",
    "Document": "Документ",
    "DocumentJournal": "ЖурналДокументов",
    "Enum": "Перечисление",
    "ChartOfCharacteristicTypes": "ПланВидовХарактеристик",
    "ChartOfAccounts": "ПланСчетов",
    "ChartOfCalculationTypes": "ПланВидовРасчета",
    "InformationRegister": "РегистрСведений",
    "AccumulationRegister": "РегистрНакопления",
    "AccountingRegister": "РегистрБухгалтерии",
    "CalculationRegister": "РегистрРасчета",
    "BusinessProcess": "БизнесПроцесс",
    "Task": "Задача",
    "ExchangePlan": "ПланОбмена",
}


@dataclass(frozen=True)
class QueryTypeRef:
    """One normalized type token: a metadata ref or a primitive/opaque type."""

    display: str  # "Справочник.Организации" | "Строка" | raw token if unknown
    kind: str = ""  # metadata kind id when this is a reference type
    name: str = ""  # metadata object name when this is a reference type

    @property
    def is_ref(self) -> bool:
        return bool(self.kind)


def normalize_type_info(raw: str) -> tuple[QueryTypeRef, ...]:
    """Normalize a `meta_members.type_info` string into typed tokens.

    Input is a space-separated token list as stored by the metadata indexer,
    e.g. ``"cfg:CatalogRef.Организации xs:string"``. Unknown tokens are kept
    as-is in `display` so callers can still show them.
    """
    result: list[QueryTypeRef] = []
    for token in raw.split():
        token_cf = token.casefold()
        primitive = _PRIMITIVE_TOKENS.get(token_cf)
        if primitive is not None:
            result.append(QueryTypeRef(display=primitive))
            continue
        prefix, dot, obj_name = token.partition(".")
        prefix_cf = prefix.casefold()
        if prefix_cf.startswith("cfg:") and dot:
            mapped = _REF_PREFIX_TO_KIND.get(prefix_cf[len("cfg:") :])
            if mapped is not None and obj_name:
                kind, root_ru = mapped
                result.append(
                    QueryTypeRef(display=f"{root_ru}.{obj_name}", kind=kind, name=obj_name)
                )
                continue
        result.append(QueryTypeRef(display=token))
    return tuple(result)


# ---------------------------------------------------------------------------
# Metadata lookup protocol
# ---------------------------------------------------------------------------


class MetaFieldLookup(Protocol):
    """Field-type source for one configuration."""

    def object_fields(self, kind: str, object_name: str) -> dict[str, tuple[str, str]] | None:
        """Return {field name casefold: (canonical name, raw type_info)}.

        None when the object is unknown (as opposed to known-but-empty).
        """
        ...


class SymbolIndexFieldLookup:
    """Adapter over `SymbolIndex.get_meta_members` (duck-typed).

    `get_meta_members` resolves by object name only; when the stored object's
    kind differs from the requested one, the object is treated as unknown
    rather than returning fields of a same-named object of another kind.
    """

    def __init__(self, index: Any) -> None:
        self._index = index

    def object_fields(self, kind: str, object_name: str) -> dict[str, tuple[str, str]] | None:
        members = self._index.get_meta_members(object_name)
        if not members:
            return None
        if members[0].get("object_kind") != kind:
            return None
        return {
            m["name"].casefold(): (m["name"], m.get("type_info", ""))
            for m in members
            if m.get("kind") == "attribute"
        }


# ---------------------------------------------------------------------------
# Standard (implicit) fields not present in meta_members
# ---------------------------------------------------------------------------

_STANDARD_SELF_REF_FIELDS = frozenset({"ссылка"})
# Parent points to the same catalog-like object.
_STANDARD_PARENT_REF_KINDS = frozenset(
    {"Catalog", "ChartOfCharacteristicTypes", "ChartOfAccounts", "Task"}
)
_STANDARD_PRIMITIVE_FIELDS: dict[str, str] = {
    "наименование": "Строка",
    "код": "",  # Строка|Число depending on object settings — honest unknown
    "номер": "",
    "пометкаудаления": "Булево",
    "этогруппа": "Булево",
    "предопределенный": "Булево",
    "проведен": "Булево",
    "дата": "Дата",
    "период": "Дата",
    "активность": "Булево",
    "порядок": "Число",
    "моментвремени": "МоментВремени",
}


# ---------------------------------------------------------------------------
# Alias environment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableBinding:
    """What one FROM/JOIN alias points to inside a select section."""

    kind: str = ""  # metadata kind id for metadata tables
    name: str = ""  # metadata object name
    virtual: str = ""  # virtual table suffix as written (СрезПоследних, ...)
    # Materialized fields for temp tables / nested query sources:
    # field name casefold -> (canonical name, normalized types).
    fields: Mapping[str, tuple[str, tuple[QueryTypeRef, ...]]] | None = None

    @property
    def display(self) -> str:
        if self.kind:
            root = _KIND_TO_QUERY_ROOT.get(self.kind, self.kind)
            return f"{root}.{self.name}"
        return ""


@dataclass(frozen=True)
class FieldHop:
    """One resolved dereference step of a chain."""

    table: str  # owner table display ("Справочник.Организации"; "" for ВТ/вложенных)
    field: str  # canonical field name
    types: tuple[QueryTypeRef, ...]

    @property
    def identity(self) -> str:
        return f"{self.table}.{self.field}" if self.table else ""


@dataclass(frozen=True)
class ChainResolution:
    status: str  # "resolved" | "ambiguous" | "unknown"
    hops: tuple[FieldHop, ...] = ()
    candidates: tuple[str, ...] = ()  # identities at the ambiguous hop

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(h.identity for h in self.hops if h.identity)


@dataclass(frozen=True)
class QueryFieldUse:
    node: Any  # dotted_identifier CST node
    parts: tuple[str, ...]
    resolution: ChainResolution


_UNKNOWN = ChainResolution(status="unknown")

# Node types that open a new alias scope; bounded walks stop there.
_SCOPE_BOUNDARY_TYPES = frozenset({"nested_query_source", "select_section"})


def _iter_bounded(node: Any, node_type: str, *, skip_root_check: bool = False):
    """Yield descendants of *node* of *node_type* without crossing scope boundaries."""
    if not skip_root_check and getattr(node, "type", None) in _SCOPE_BOUNDARY_TYPES:
        return
    if getattr(node, "type", None) == node_type:
        yield node
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) in _SCOPE_BOUNDARY_TYPES:
            continue
        yield from _iter_bounded(child, node_type, skip_root_check=True)


def _source_alias_identifier(owner: Any) -> str | None:
    alias_node = first_named_child(owner, "source_alias")
    if alias_node is None:
        return None
    ident = first_named_child(alias_node, "identifier")
    if ident is None:
        return None
    name = node_text(ident).strip()
    return name or None


def _binding_for_source(
    name_node: Any,
    lookup: MetaFieldLookup,
    temp_tables: Mapping[str, Mapping[str, tuple[str, tuple[QueryTypeRef, ...]]]],
) -> tuple[TableBinding, str | None]:
    """Build a binding for one FROM/JOIN source node.

    Returns (binding, default alias when no explicit `КАК` is given).
    """
    node_type = getattr(name_node, "type", None)
    if node_type == "virtual_table_source":
        inner = child_by_field_name(name_node, "name") or first_named_child(
            name_node, "dotted_identifier"
        )
        if inner is None:
            return TableBinding(), None
        parts = dotted_identifier_parts(inner)
        if len(parts) >= 3 and parts[0].casefold() in _QUERY_ROOT_TO_KIND:
            kind = _QUERY_ROOT_TO_KIND[parts[0].casefold()]
            return TableBinding(kind=kind, name=parts[1], virtual=parts[2]), None
        return TableBinding(), None
    if node_type == "nested_query_source":
        inner_query = first_named_child(name_node, "query")
        if inner_query is None:
            return TableBinding(), None
        fields = _query_output_fields(inner_query, lookup, temp_tables)
        return TableBinding(fields=fields), None
    if node_type == "dotted_identifier":
        parts = dotted_identifier_parts(name_node)
        if not parts:
            return TableBinding(), None
        root_kind = _QUERY_ROOT_TO_KIND.get(parts[0].casefold())
        if root_kind is not None and len(parts) >= 2:
            virtual = parts[2] if len(parts) >= 3 else ""
            return (
                TableBinding(kind=root_kind, name=parts[1], virtual=virtual),
                parts[-1] if not virtual else None,
            )
        return TableBinding(), None
    if node_type == "identifier":
        name = node_text(name_node).strip()
        fields = temp_tables.get(name.casefold())
        if fields is not None:
            return TableBinding(fields=fields), name
        return TableBinding(), name
    return TableBinding(), None


def build_section_env(
    select_section: Any,
    lookup: MetaFieldLookup,
    temp_tables: Mapping[str, Mapping[str, tuple[str, tuple[QueryTypeRef, ...]]]] | None = None,
) -> dict[str, TableBinding]:
    """Build alias -> binding map for one select section (FROM + all JOINs)."""
    temp_tables = temp_tables or {}
    env: dict[str, TableBinding] = {}
    from_clause = first_named_child(select_section, "from_clause")
    if from_clause is None:
        return env

    def register(owner: Any, name_node: Any | None) -> None:
        if name_node is None:
            return
        binding, default_alias = _binding_for_source(name_node, lookup, temp_tables)
        alias = _source_alias_identifier(owner) or default_alias
        if alias:
            env.setdefault(alias.casefold(), binding)

    for table_source in _iter_bounded(from_clause, "table_source", skip_root_check=True):
        register(table_source, child_by_field_name(table_source, "name"))
        for join in _iter_bounded(table_source, "join_clause", skip_root_check=True):
            register(join, child_by_field_name(join, "source"))
    return env


# ---------------------------------------------------------------------------
# Chain resolution
# ---------------------------------------------------------------------------


def _resolve_field_on_binding(
    binding: TableBinding,
    part: str,
    lookup: MetaFieldLookup,
    cache: dict[tuple[str, str], dict[str, tuple[str, str]] | None],
) -> FieldHop | None:
    part_cf = part.casefold()
    if binding.fields is not None:
        entry = binding.fields.get(part_cf)
        if entry is None:
            return None
        canonical, types = entry
        return FieldHop(table="", field=canonical, types=types)
    if not binding.kind:
        return None
    key = (binding.kind, binding.name)
    if key not in cache:
        cache[key] = lookup.object_fields(binding.kind, binding.name)
    fields = cache[key]
    if fields is not None:
        entry = fields.get(part_cf)
        if entry is not None:
            canonical, raw = entry
            return FieldHop(table=binding.display, field=canonical, types=normalize_type_info(raw))
    if part_cf in _STANDARD_SELF_REF_FIELDS or (
        part_cf == "родитель" and binding.kind in _STANDARD_PARENT_REF_KINDS
    ):
        self_ref = QueryTypeRef(display=binding.display, kind=binding.kind, name=binding.name)
        return FieldHop(table=binding.display, field=part, types=(self_ref,))
    primitive = _STANDARD_PRIMITIVE_FIELDS.get(part_cf)
    if primitive is not None:
        types = (QueryTypeRef(display=primitive),) if primitive else ()
        return FieldHop(table=binding.display, field=part, types=types)
    return None


def resolve_chain(
    parts: tuple[str, ...],
    env: Mapping[str, TableBinding],
    lookup: MetaFieldLookup,
    _cache: dict[tuple[str, str], dict[str, tuple[str, str]] | None] | None = None,
) -> ChainResolution:
    """Resolve `Алиас.Поле[.Поле2...]` against a section alias environment."""
    if len(parts) < 2:
        return _UNKNOWN
    binding = env.get(parts[0].casefold())
    if binding is None:
        return _UNKNOWN
    cache = _cache if _cache is not None else {}
    owners: list[TableBinding] = [binding]
    hops: list[FieldHop] = []
    for part in parts[1:]:
        resolved = [
            hop
            for owner in owners
            if (hop := _resolve_field_on_binding(owner, part, lookup, cache)) is not None
        ]
        if not resolved:
            return ChainResolution(status="unknown", hops=tuple(hops))
        distinct_identities = tuple(dict.fromkeys(h.identity for h in resolved))
        if len(resolved) > 1 and len(distinct_identities) > 1:
            return ChainResolution(
                status="ambiguous", hops=tuple(hops), candidates=distinct_identities
            )
        hop = resolved[0]
        hops.append(hop)
        owners = [TableBinding(kind=ref.kind, name=ref.name) for ref in hop.types if ref.is_ref]
    return ChainResolution(status="resolved", hops=tuple(hops))


# ---------------------------------------------------------------------------
# Temp tables (query package) and query output fields
# ---------------------------------------------------------------------------


def _query_output_fields(
    query: Any,
    lookup: MetaFieldLookup,
    temp_tables: Mapping[str, Mapping[str, tuple[str, tuple[QueryTypeRef, ...]]]],
) -> dict[str, tuple[str, tuple[QueryTypeRef, ...]]]:
    """Field name -> types of a query's first select section (1C union rule)."""
    section = first_named_child(query, "select_section")
    if section is None:
        return {}
    env = build_section_env(section, lookup, temp_tables)
    cache: dict[tuple[str, str], dict[str, tuple[str, str]] | None] = {}
    result: dict[str, tuple[str, tuple[QueryTypeRef, ...]]] = {}
    field_list = first_named_child(section, "field_list")
    if field_list is None:
        return {}
    for field_node in _iter_bounded(field_list, "field", skip_root_check=True):
        value = child_by_field_name(field_node, "value")
        expr = value
        while expr is not None and getattr(expr, "type", None) == "query_expression":
            expr = next(iter(getattr(expr, "named_children", []) or []), None)
        alias_node = first_named_child(field_node, "field_alias")
        alias_ident = (
            first_named_child(alias_node, "identifier") if alias_node is not None else None
        )
        out_name: str | None = node_text(alias_ident).strip() if alias_ident is not None else None
        types: tuple[QueryTypeRef, ...] = ()
        expr_type = getattr(expr, "type", None)
        if expr_type == "dotted_identifier":
            parts = dotted_identifier_parts(expr)
            if out_name is None and parts:
                out_name = parts[-1]
            resolution = resolve_chain(parts, env, lookup, cache)
            if resolution.status == "resolved" and resolution.hops:
                types = resolution.hops[-1].types
        elif expr_type == "cast_expression":
            cast_type = child_by_field_name(expr, "type")
            type_dotted = (
                first_named_child(cast_type, "dotted_identifier") if cast_type is not None else None
            )
            if type_dotted is not None:
                parts = dotted_identifier_parts(type_dotted)
                kind = _QUERY_ROOT_TO_KIND.get(parts[0].casefold()) if parts else None
                if kind is not None and len(parts) >= 2:
                    root_ru = _KIND_TO_QUERY_ROOT.get(kind, kind)
                    types = (
                        QueryTypeRef(display=f"{root_ru}.{parts[1]}", kind=kind, name=parts[1]),
                    )
        elif expr_type == "identifier" and out_name is None:
            out_name = node_text(expr).strip()
        if out_name:
            result.setdefault(out_name.casefold(), (out_name, types))
    return result


def build_temp_table_env(
    root: Any,
    lookup: MetaFieldLookup,
) -> dict[str, dict[str, tuple[str, tuple[QueryTypeRef, ...]]]]:
    """Materialize temp-table fields across a query package, in document order."""
    temp_tables: dict[str, dict[str, tuple[str, tuple[QueryTypeRef, ...]]]] = {}
    package = first_named_child(root, "query_package") or root
    for query in [
        child for child in getattr(package, "children", []) or [] if child.type == "query"
    ]:
        section = first_named_child(query, "select_section")
        if section is None:
            continue
        into = first_named_child(section, "into_clause")
        if into is None:
            continue
        name_node = child_by_field_name(into, "name") or first_named_child(into, "identifier")
        if name_node is None:
            continue
        temp_name = node_text(name_node).strip()
        if not temp_name:
            continue
        temp_tables[temp_name.casefold()] = _query_output_fields(query, lookup, temp_tables)
    return temp_tables


# ---------------------------------------------------------------------------
# Top-level: resolve every field chain in a parsed query text
# ---------------------------------------------------------------------------


def resolve_query_field_uses(root: Any, lookup: MetaFieldLookup) -> list[QueryFieldUse]:
    """Resolve all dotted field chains in a parsed SDBL tree.

    *root* is the tree root (`source_file`). Table-source names, cast types and
    virtual-table names are not field uses and are skipped; every remaining
    `dotted_identifier` inside a query expression is resolved against the alias
    environment of its enclosing select section plus package temp tables.
    """
    source_file = root
    temp_tables = build_temp_table_env(source_file, lookup)
    section_envs: dict[int, dict[str, TableBinding]] = {}
    cache: dict[tuple[str, str], dict[str, tuple[str, str]] | None] = {}
    uses: list[QueryFieldUse] = []

    def walk(node: Any) -> None:
        for child in getattr(node, "children", []) or []:
            walk(child)
        if getattr(node, "type", None) != "dotted_identifier":
            return
        parent_type = getattr(getattr(node, "parent", None), "type", None)
        if parent_type != "query_expression":
            return
        section = _enclosing_select_section(node)
        if section is None:
            return
        section_id = id(section)
        if section_id not in section_envs:
            section_envs[section_id] = build_section_env(section, lookup, temp_tables)
        parts = dotted_identifier_parts(node)
        resolution = resolve_chain(parts, section_envs[section_id], lookup, cache)
        uses.append(QueryFieldUse(node=node, parts=parts, resolution=resolution))

    walk(source_file)
    return uses


def _enclosing_select_section(node: Any) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == "select_section":
            return parent
        parent = getattr(parent, "parent", None)
    return None
