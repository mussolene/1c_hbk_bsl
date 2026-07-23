"""
BSL type inference engine — pure AST walk, no regex on source text.

Grammar node types (tree-sitter-hbk), verified against the compiled
tree_sitter_hbk grammar rather than assumed from syntax alone:
  source_file
  procedure_definition / function_definition
    identifier          — name
    parameters
      parameter
        VAL_KEYWORD?
        identifier      — param name
    <body nodes>
    ENDPROCEDURE_KEYWORD / ENDFUNCTION_KEYWORD
  assignment_statement
    identifier | property_access   — LHS
    =
    expression                     — RHS
    ;
  expression
    new_expression                 — Новый Тип(...)
      NEW_KEYWORD
      identifier                   — type name
      arguments
    call_expression                — chain ending in a method call
      access                       — possibly nested, see below
      .
      method_call
        identifier                 — method name
        arguments
    property_access                — chain ending in a bare property (no call)
      access                       — base or nested access, same shape as
                                      call_expression's leading segment
      .
      property
    identifier                     — variable reference
    binary_expression               — <expr> <operator> <expr>, e.g. `=`/`ИЛИ`
      expression
      operator
      expression
    method_call                    — a *bare* function call with no object
                                      base, e.g. `Тип(...)`/`ТипЗнч(...)`
                                      (not wrapped in access/call_expression)
      identifier
      arguments
        (
        expression
        )
    const_expression
      string
        "
        string_content
        "
  access                           — a chain segment; nests for multi-hop
                                      chains, e.g. `Запрос.Выполнить().Выгрузить()`
                                      is access(access(access(id)."."method_call)
                                      "."method_call) — an *intermediate* hop's
                                      method_call/property lives INSIDE the
                                      access subtree, not just at the top.
    access | identifier            — base or nested access
    . method_call | . property
  var_statement
    VAR_KEYWORD
    identifier+
    ;
  for_each_statement
    FOR_KEYWORD / EACH_KEYWORD
    identifier                     — iterator variable
    IN_KEYWORD
    expression                     — collection
    DO_KEYWORD
    <body>
    ENDDO_KEYWORD
  for_statement
    FOR_KEYWORD
    identifier
    = / BY_KEYWORD / TO_KEYWORD
    expression
    DO_KEYWORD / CYCLE_KEYWORD
    <body>
    ENDDO_KEYWORD / ENDCYCLE_KEYWORD
  if_statement
    IF_KEYWORD
    expression                     — condition
    THEN_KEYWORD
    <Тогда-branch body nodes as direct children>
    elseif_clause*
      ELSIF_KEYWORD
      expression
      THEN_KEYWORD
      <body nodes>
    else_clause?
      ELSE_KEYWORD
      <body nodes>
    ENDIF_KEYWORD
    ;
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    current_module_xml_context,
)
from onec_hbk_bsl.indexer.metadata_registry import collection_for_alias

# ---------------------------------------------------------------------------
# Return-type table  (object_type.method_name → return_type, all lower-case)
# ---------------------------------------------------------------------------

RETURN_TYPE_MAP: dict[str, str] = {
    # Запрос
    "запрос.выполнить": "РезультатЗапроса",
    "query.execute": "РезультатЗапроса",
    # РезультатЗапроса
    "результатзапроса.выбрать": "ВыборкаИзРезультатаЗапроса",
    "queryresult.choose": "ВыборкаИзРезультатаЗапроса",
    "результатзапроса.выгрузить": "ТаблицаЗначений",
    "queryresult.unload": "ТаблицаЗначений",
    # ТаблицаЗначений
    "таблицазначений.найти": "СтрокаТаблицыЗначений",
    "valuetable.find": "СтрокаТаблицыЗначений",
    "таблицазначений.добавить": "СтрокаТаблицыЗначений",
    "valuetable.add": "СтрокаТаблицыЗначений",
    "таблицазначений.вставить": "СтрокаТаблицыЗначений",
    "valuetable.insert": "СтрокаТаблицыЗначений",
    "таблицазначений.скопировать": "ТаблицаЗначений",
    "valuetable.copy": "ТаблицаЗначений",
    # Дерево значений
    "деревозначений.строки": "КоллекцияСтрокДереваЗначений",
    # Список значений
    "списокзначений.найтипозначению": "ЭлементСпискаЗначений",
    "valuelist.findbyvalue": "ЭлементСпискаЗначений",
    "списокзначений.добавить": "ЭлементСпискаЗначений",
    "valuelist.add": "ЭлементСпискаЗначений",
    # Справочники
    "справочникменеджер.создатьэлемент": "СправочникОбъект",
    "catalogmanager.createnewitem": "СправочникОбъект",
    "справочникменеджер.найти": "СправочникСсылка",
    "catalogmanager.find": "СправочникСсылка",
    "справочникменеджер.найтипокоду": "СправочникСсылка",
    "catalogmanager.findbycode": "СправочникСсылка",
    "справочникменеджер.найтипонаименованию": "СправочникСсылка",
    "catalogmanager.findbydescription": "СправочникСсылка",
    "справочникменеджер.пустаяссылка": "СправочникСсылка",
    "catalogmanager.emptyref": "СправочникСсылка",
    "справочникменеджер.выбрать": "СправочникВыборка",
    "catalogmanager.select": "CatalogSelection",
    "справочниквыборка.ссылка": "СправочникСсылка",
    "catalogselection.ref": "CatalogRef",
    "справочникссылка.получитьобъект": "СправочникОбъект",
    "catalogref.getobject": "СправочникОбъект",
    # Документы
    "документменеджер.создатьдокумент": "ДокументОбъект",
    "documentmanager.createnewdocument": "ДокументОбъект",
    "документменеджер.пустаяссылка": "ДокументСсылка",
    "documentmanager.emptyref": "DocumentRef",
    "документменеджер.выбрать": "ДокументВыборка",
    "documentmanager.select": "DocumentSelection",
    "документвыборка.ссылка": "ДокументСсылка",
    "documentselection.ref": "DocumentRef",
    "документссылка.получитьобъект": "ДокументОбъект",
    "documentref.getobject": "ДокументОбъект",
    # РегистрыСведений
    "регистрсведенийменеджер.создатьзапись": "РегистрСведенийЗапись",
    "informationregistermanager.createrecordset": "РегистрСведенийЗапись",
    "регистрсведенийменеджер.создатьнаборзаписей": "РегистрСведенийНаборЗаписей",
    # Перечисления
    "перечислениеменеджер.ссылка": "ПеречислениеСсылка",
    "перечислениеменеджер.пустаяссылка": "ПеречислениеСсылка",
    # HTTP
    "httpsоединение.получить": "HTTPОтвет",
    "httpconnection.get": "HTTPОтвет",
    "httpсоединение.отправить": "HTTPОтвет",
    "httpconnection.post": "HTTPОтвет",
    "httpсоединение.вызватьhttp": "HTTPОтвет",
    "httpconnection.callhttp": "HTTPОтвет",
    # XML
    "чтениеxml.прочитать": "ЧтениеXML",
    "чтениеfastinfoset.прочитать": "ЧтениеFastInfoset",
    # Структура
    "структура.скопировать": "Структура",
    # МенеджерВременныхТаблиц
    "запрос.менеджертаблиц": "МенеджерВременныхТаблиц",
    # ТаблицаФормы
    "таблицаформы.найти": "СтрокаТаблицыФормы",
    # ОбластьЯчеекТабличногоДокумента
    "табличныйдокумент.получитьобласть": "ОбластьЯчеекТабличногоДокумента",
    "spreadsheetdocument.getarea": "ОбластьЯчеекТабличногоДокумента",
    # ЗапросHTTP
    "httpsзапрос": "HTTPЗапрос",
}


# ---------------------------------------------------------------------------
# Global manager collections (Справочники, Документы, ...) → manager type
# ---------------------------------------------------------------------------

# The base identifier of a multi-segment access chain (e.g. "Справочники" in
# "Справочники.Организации.НайтиПоКоду(...)") is a built-in global collection,
# not a local variable — it never appears in TypeScope. It always denotes the
# same manager type regardless of which specific catalog/document the next
# segment names, so it maps directly to a RETURN_TYPE_MAP key prefix.
_GLOBAL_MANAGER_TYPES: dict[str, str] = {
    "справочники": "СправочникМенеджер",
    "catalogs": "CatalogManager",
    "документы": "ДокументМенеджер",
    "documents": "DocumentManager",
    "регистрысведений": "РегистрСведенийМенеджер",
    "informationregisters": "InformationRegisterManager",
    "перечисления": "ПеречислениеМенеджер",
    "enums": "EnumManager",
    "регистрынакопления": "РегистрНакопленияМенеджер",
    "accumulationregisters": "AccumulationRegisterManager",
    "регистрырасчета": "РегистрРасчетаМенеджер",
    "calculationregisters": "CalculationRegisterManager",
    "планывидовхарактеристик": "ПланВидовХарактеристикМенеджер",
    "chartsofcharacteristictypes": "ChartOfCharacteristicTypesManager",
    "планывидоврасчета": "ПланВидовРасчетаМенеджер",
    "chartsofcalculationtypes": "ChartOfCalculationTypesManager",
    "планыобмена": "ПланОбменаМенеджер",
    "exchangeplans": "ExchangePlanManager",
    "журналыдокументов": "ЖурналДокументовМенеджер",
    "documentjournals": "DocumentJournalManager",
    "константы": "КонстантаМенеджер",
    "constants": "ConstantManager",
    "бизнеспроцессы": "БизнесПроцессМенеджер",
    "businessprocesses": "BusinessProcessManager",
    "задачи": "ЗадачаМенеджер",
    "tasks": "TaskManager",
    "обработки": "ОбработкаМенеджер",
    "dataprocessors": "DataProcessorManager",
    "отчеты": "ОтчетМенеджер",
    "reports": "ReportManager",
}

# Перечисления.<Имя>.<Значение> — the value segment is one of an unbounded
# set of names (not a method), so it can never live in RETURN_TYPE_MAP.
# Recognized structurally: current_type is still the raw manager type from
# _GLOBAL_MANAGER_TYPES (i.e. the very first hop after it), the next step is
# a bare `.property` (values have no call syntax) — any name is valid.
_ENUM_MANAGER_TYPES = frozenset({"перечислениеменеджер", "enummanager"})

# Модули объектов/наборов записей: суффикс, на который заменяется "Менеджер"
# в generic-типе из _GLOBAL_MANAGER_TYPES, чтобы получить тип ЭтотОбъект.
_OBJECT_MODULE_SUFFIX = "Объект"
_RECORDSET_MODULE_SUFFIX = "НаборЗаписей"

_TYPEOF_NAMES = frozenset({"типзнч", "typeof"})
_TYPE_FN_NAMES = frozenset({"тип", "type"})
_OR_OPERATOR_NAMES = frozenset({"или", "or"})


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@dataclass
class TypeScope:
    """
    Lexical scope mapping lower-cased variable names → (generic type,
    specific metadata names) pairs.

    The generic type (e.g. "СправочникСсылка") is always a plain type name,
    used for hover/completion regardless of whether a specific metadata
    identity is known. The specific names (e.g. {"Организации"} for a
    `СправочникСсылка`) are known when the variable was resolved from a
    global manager collection access (`Справочники.Организации...`), from a
    `Если ТипЗнч(Х) = Тип("Kind.Name") Тогда` type guard, or from an implicit
    object-module variable (`Ссылка`/`ЭтотОбъект`); it is `None` when no
    specific identity is known, and may hold more than one name when a
    type-guard narrows an `ИЛИ`-chain of same-kind checks. See `infer`'s
    `metadata_only` parameter for how the two are combined on read.

    Scopes are chained: look-up walks the parent chain until a match is found.
    """

    _vars: dict[str, tuple[str, frozenset[str] | None]] = field(default_factory=dict)
    parent: TypeScope | None = None

    def set(self, name: str, type_name: str, specific: frozenset[str] | None = None) -> None:
        if type_name:
            self._vars[name.casefold()] = (type_name, specific)

    def get_full(self, name: str) -> tuple[str | None, frozenset[str] | None]:
        name_lo = name.casefold()
        scope: TypeScope | None = self
        while scope is not None:
            if name_lo in scope._vars:
                return scope._vars[name_lo]
            scope = scope.parent
        return None, None

    def get(self, name: str) -> str | None:
        return self.get_full(name)[0]

    def all_vars(self) -> dict[str, str]:
        """Merge all visible variables (inner scope wins), generic type only."""
        merged: dict[str, str] = {}
        scope: TypeScope | None = self
        while scope is not None:
            for k, (type_name, _specific) in scope._vars.items():
                merged.setdefault(k, type_name)
            scope = scope.parent
        return merged


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BslTypeEngine:
    """
    Pure-AST type inference engine for a BSL source file.

    Usage::

        engine = BslTypeEngine(tree, return_type_map=RETURN_TYPE_MAP)
        scope  = engine.scope_at_line(pos_line0, tree)
        type_  = scope.get("зап")          # → "Запрос"

    The engine never touches the raw source string — all information comes
    from tree-sitter node types and node text (plus, optionally, the file's
    position in the config tree — see `module_path`).
    """

    def __init__(
        self,
        tree: Any,
        *,
        return_type_map: dict[str, str] | None = None,
        module_path: str | None = None,
    ) -> None:
        self._rtm = return_type_map if return_type_map is not None else RETURN_TYPE_MAP
        self._module_scope = TypeScope()
        # Maps 0-based (start_line, end_line) → TypeScope for each procedure/
        # function and each narrowed if/elseif branch (see scope_at_line).
        self._proc_scopes: list[tuple[int, int, TypeScope]] = []  # (start, end, scope)

        if module_path is not None:
            self._seed_implicit_module_vars(module_path)

        root = getattr(tree, "root_node", None)
        if root is not None and isinstance(getattr(root, "text", None), (bytes, type(None))):
            # Only process real tree-sitter trees (bytes text, not regex fallback)
            self._walk(root, self._module_scope)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scope_at_line(self, line0: int, _tree: Any = None) -> TypeScope:
        """Return the innermost TypeScope visible at *line0* (0-based).

        Ranges can nest (a narrowed if/elseif branch inside its enclosing
        procedure), so the smallest containing range wins, not the first
        one found.
        """
        best: TypeScope | None = None
        best_size: int | None = None
        for start, end, scope in self._proc_scopes:
            if start <= line0 <= end:
                size = end - start
                if best_size is None or size < best_size:
                    best = scope
                    best_size = size
        return best if best is not None else self._module_scope

    def infer(
        self, var_name: str, line0: int, metadata_only: bool = False
    ) -> str | list[str] | None:
        """
        Infer the type of *var_name* visible at *line0*.

        With ``metadata_only=False`` (default), returns the generic type
        string exactly as before — safe for existing consumers (e.g. LSP
        hover), including chains with no specific metadata identity.

        With ``metadata_only=True``, returns the composed
        ``"Kind.Name"`` string when exactly one specific metadata identity
        is known, a sorted list of such strings when a type-guard narrowed
        to several same-kind candidates, or ``None`` when no specific
        identity is known at all.
        """
        type_name, specific = self.scope_at_line(line0).get_full(var_name)
        if not metadata_only:
            return type_name or None
        if not specific:
            return None
        if len(specific) == 1:
            return f"{type_name}.{next(iter(specific))}"
        return sorted(f"{type_name}.{name}" for name in specific)

    # ------------------------------------------------------------------
    # Implicit object/record-set module variables (Ссылка / ЭтотОбъект)
    # ------------------------------------------------------------------

    def _seed_implicit_module_vars(self, module_path: str) -> None:
        basename = Path(module_path).name.casefold()
        if basename == "objectmodule.bsl":
            obj_suffix, has_ref = _OBJECT_MODULE_SUFFIX, True
        elif basename == "recordsetmodule.bsl":
            obj_suffix, has_ref = _RECORDSET_MODULE_SUFFIX, False
        else:
            return

        ctx = current_module_xml_context(module_path)
        folder = ctx.get("folder")
        object_name = ctx.get("object_name")
        if not folder or not object_name:
            return

        collection_ru = collection_for_alias(folder.casefold())
        generic = _GLOBAL_MANAGER_TYPES.get((collection_ru or "").casefold())
        if not generic or "Менеджер" not in generic:
            return

        specific = frozenset({object_name})
        if has_ref:
            self._module_scope.set("Ссылка", generic.replace("Менеджер", "Ссылка"), specific)
        self._module_scope.set("ЭтотОбъект", generic.replace("Менеджер", obj_suffix), specific)

    # ------------------------------------------------------------------
    # AST walk
    # ------------------------------------------------------------------

    def _walk(self, node: Any, scope: TypeScope) -> None:
        ntype = node.type if hasattr(node, "type") else ""

        if ntype in ("procedure_definition", "function_definition"):
            self._handle_proc(node, scope)
            return

        if ntype == "assignment_statement":
            self._handle_assignment(node, scope)
            # Don't recurse deeper — assignments are flat

        elif ntype == "var_statement":
            # Перем Имя; — declare without type
            for child in node.children:
                if child.type == "identifier":
                    scope.set(_node_text(child), "")

        elif ntype == "for_each_statement":
            self._handle_for_each(node, scope)
            return  # recursion handled inside

        elif ntype == "for_statement":
            self._handle_for(node, scope)
            return

        elif ntype == "if_statement":
            self._handle_if(node, scope)
            return  # recursion handled inside

        else:
            for child in node.children:
                self._walk(child, scope)

    def _handle_proc(self, node: Any, parent_scope: TypeScope) -> None:
        proc_scope = TypeScope(parent=parent_scope)
        start = node.start_point[0]
        end = node.end_point[0]
        self._proc_scopes.append((start, end, proc_scope))

        for child in node.children:
            if child.type == "parameters":
                self._collect_params(child, proc_scope)
            else:
                self._walk(child, proc_scope)

    def _collect_params(self, params_node: Any, scope: TypeScope) -> None:
        for child in params_node.children:
            if child.type == "parameter":
                for pc in child.children:
                    if pc.type == "identifier":
                        scope.set(_node_text(pc), "")
                        break

    def _handle_assignment(self, node: Any, scope: TypeScope) -> None:
        lhs_name = ""
        rhs_node = None

        for child in node.children:
            ct = child.type
            if ct == "identifier" and not lhs_name:
                lhs_name = _node_text(child)
            elif ct == "expression":
                rhs_node = child
            # property_access on LHS (Obj.Prop = ...) → no type capture for LHS

        if lhs_name and rhs_node is not None:
            type_name, specific = self._resolve_expr(rhs_node, scope)
            scope.set(lhs_name, type_name, specific)

    def _handle_for_each(self, node: Any, scope: TypeScope) -> None:
        # Для Каждого <iter> Из <collection> Цикл <body> КонецЦикла
        iter_name = ""
        saw_each = False
        for child in node.children:
            ct = child.type
            if ct == "EACH_KEYWORD":
                saw_each = True
            elif saw_each and ct == "identifier" and not iter_name:
                iter_name = _node_text(child)
                # Try to get element type from collection's type
            elif ct == "expression" and iter_name:
                col_type, _specific = self._resolve_expr(child, scope)
                elem_type = _COLLECTION_ELEM_TYPE.get(col_type.casefold(), "")
                scope.set(iter_name, elem_type)
            elif ct not in (
                "FOR_KEYWORD",
                "EACH_KEYWORD",
                "IN_KEYWORD",
                "DO_KEYWORD",
                "ENDDO_KEYWORD",
                "identifier",
                ".",
            ):
                self._walk(child, scope)

    def _handle_for(self, node: Any, scope: TypeScope) -> None:
        # Для <var> = <start> По <end> Цикл
        got_var = False
        for child in node.children:
            ct = child.type
            if ct == "identifier" and not got_var:
                scope.set(_node_text(child), "Число")
                got_var = True
            elif ct not in ("FOR_KEYWORD", "=", ".", ";"):
                self._walk(child, scope)

    # ------------------------------------------------------------------
    # if/elseif/else — type-guard narrowing
    # ------------------------------------------------------------------

    def _handle_if(self, node: Any, scope: TypeScope) -> None:
        children = list(node.children)
        n = len(children)
        i = 0

        condition = None
        while i < n:
            if children[i].type == "expression":
                condition = children[i]
                i += 1
                break
            i += 1
        while i < n and children[i].type != "THEN_KEYWORD":
            i += 1
        i += 1  # past THEN_KEYWORD

        then_body = []
        while i < n and children[i].type not in ("elseif_clause", "else_clause", "ENDIF_KEYWORD"):
            then_body.append(children[i])
            i += 1
        self._walk_branch(condition, then_body, scope)

        while i < n and children[i].type == "elseif_clause":
            self._handle_elseif(children[i], scope)
            i += 1

        if i < n and children[i].type == "else_clause":
            # Иначе gives no positive narrowing (we only know what Х is NOT).
            for c in children[i].children:
                if c.type != "ELSE_KEYWORD":
                    self._walk(c, scope)

    def _handle_elseif(self, node: Any, scope: TypeScope) -> None:
        children = list(node.children)
        n = len(children)
        i = 0

        condition = None
        while i < n:
            if children[i].type == "expression":
                condition = children[i]
                i += 1
                break
            i += 1
        while i < n and children[i].type != "THEN_KEYWORD":
            i += 1
        i += 1  # past THEN_KEYWORD

        self._walk_branch(condition, children[i:], scope)

    def _walk_branch(self, condition: Any, body_nodes: list[Any], parent_scope: TypeScope) -> None:
        narrowing = self._extract_narrowing(condition) if condition is not None else None
        branch_scope = parent_scope
        if narrowing is not None:
            var_name, kind, names = narrowing
            branch_scope = TypeScope(parent=parent_scope)
            branch_scope.set(var_name, kind, names)
            if body_nodes:
                start = min(c.start_point[0] for c in body_nodes)
                end = max(c.end_point[0] for c in body_nodes)
                self._proc_scopes.append((start, end, branch_scope))

        for c in body_nodes:
            self._walk(c, branch_scope)

    def _extract_narrowing(self, condition: Any) -> tuple[str, str, frozenset[str]] | None:
        """
        Match `ТипЗнч(Х) = Тип("Kind.Name")`, optionally `ИЛИ`-chained with
        more checks against the *same* variable and the *same* Kind (e.g.
        `ТипЗнч(Х) = Тип("A.Б") ИЛИ ТипЗнч(Х) = Тип("A.В")`). Any other form
        (parentheses, `И`, `ТипЗнч` of a non-identifier, differing variable
        or Kind across disjuncts) yields no narrowing at all — conservative,
        all-or-nothing, matching current (no-narrowing) behavior.
        """
        disjuncts = self._collect_or_disjuncts(condition)
        if not disjuncts:
            return None
        matches = [self._match_type_guard(d) for d in disjuncts]
        if any(m is None for m in matches):
            return None
        var_names = {m[0].casefold() for m in matches}
        if len(var_names) != 1:
            return None
        kinds = {m[1] for m in matches}
        if len(kinds) != 1:
            return None
        var_name = matches[0][0]
        kind = matches[0][1]
        names = frozenset(m[2] for m in matches)
        return var_name, kind, names

    def _collect_or_disjuncts(self, node: Any) -> list[Any]:
        node = self._unwrap_expr(node)
        if node is None:
            return []
        if node.type == "binary_expression":
            kids = node.children
            if (
                len(kids) == 3
                and kids[1].type == "operator"
                and _node_text(kids[1]).casefold() in _OR_OPERATOR_NAMES
            ):
                return self._collect_or_disjuncts(kids[0]) + self._collect_or_disjuncts(kids[2])
        return [node]

    def _match_type_guard(self, condition: Any) -> tuple[str, str, str] | None:
        """Match a single `ТипЗнч(Х) = Тип("Kind.Name")` (either operand order)."""
        node = self._unwrap_expr(condition)
        if node is None or node.type != "binary_expression":
            return None
        kids = node.children
        if len(kids) != 3:
            return None
        lhs, op, rhs = kids
        if op.type != "operator" or _node_text(op) != "=":
            return None

        var_name = self._match_typeof_var(lhs)
        literal = self._match_type_literal(rhs)
        if var_name is None or literal is None:
            var_name = self._match_typeof_var(rhs)
            literal = self._match_type_literal(lhs)
        if var_name is None or literal is None or "." not in literal:
            return None
        kind, name = literal.split(".", 1)
        return var_name, kind, name

    def _unwrap_expr(self, node: Any) -> Any:
        while node is not None and node.type == "expression" and len(node.children) == 1:
            node = node.children[0]
        return node

    def _match_typeof_var(self, node: Any) -> str | None:
        node = self._unwrap_expr(node)
        if node is None or node.type != "method_call":
            return None
        ident, args = self._method_call_parts(node)
        if ident is None or ident.casefold() not in _TYPEOF_NAMES or args is None:
            return None
        for c in args.children:
            if c.type == "expression":
                inner = self._unwrap_expr(c)
                if inner is not None and inner.type == "identifier":
                    return _node_text(inner)
        return None

    def _match_type_literal(self, node: Any) -> str | None:
        node = self._unwrap_expr(node)
        if node is None or node.type != "method_call":
            return None
        ident, args = self._method_call_parts(node)
        if ident is None or ident.casefold() not in _TYPE_FN_NAMES or args is None:
            return None
        for c in args.children:
            if c.type != "expression":
                continue
            inner = self._unwrap_expr(c)
            if inner is None or inner.type != "const_expression":
                continue
            for cc in inner.children:
                if cc.type == "string":
                    for sc in cc.children:
                        if sc.type == "string_content":
                            return _node_text(sc)
        return None

    def _method_call_parts(self, node: Any) -> tuple[str | None, Any]:
        ident = None
        args = None
        for c in node.children:
            if c.type == "identifier" and ident is None:
                ident = _node_text(c)
            elif c.type == "arguments":
                args = c
        return ident, args

    # ------------------------------------------------------------------
    # Expression type resolution
    # ------------------------------------------------------------------

    def _resolve_expr(self, expr_node: Any, scope: TypeScope) -> tuple[str, frozenset[str] | None]:
        """Recursively determine the (type, specific-names) of an expression."""
        for child in expr_node.children:
            ct = child.type
            if ct == "new_expression":
                return self._resolve_new(child), None
            elif ct in ("call_expression", "property_access"):
                return self._resolve_access_chain(child, scope)
            elif ct == "identifier":
                # Variable reference
                type_name, specific = scope.get_full(_node_text(child))
                return type_name or "", specific
            elif ct == "expression":
                # Nested expression wrapper
                result = self._resolve_expr(child, scope)
                if result[0]:
                    return result
        return "", None

    def _resolve_new(self, node: Any) -> str:
        """new_expression → TypeName from the identifier child."""
        for child in node.children:
            if child.type == "identifier":
                return _node_text(child)
        return ""

    def _resolve_access_chain(
        self, node: Any, scope: TypeScope
    ) -> tuple[str, frozenset[str] | None]:
        """
        Resolve the type produced by a `call_expression`/`property_access`
        node — an ordered chain of `.property` / `.method(...)` hops applied
        to a base identifier (a local variable, or a global manager
        collection such as `Справочники`).

        Chained calls (`Запрос.Выполнить().Выгрузить()`) nest the earlier
        hops *inside* the `access` subtree as embedded `method_call` /
        `property` children, with only the last hop attached directly to
        the outer node — so the type must be threaded sequentially through
        every hop, not just derived from the base name and the final method
        alone. The specific metadata name(s) (e.g. "Организации" for
        `Справочники.Организации...`), when known, are threaded alongside
        the generic type and cleared as soon as a hop fails to resolve.
        """
        steps = self._flatten_chain(node)
        if not steps or steps[0][0] != "id":
            return "", None

        base_name = steps[0][1]
        scoped_type, scoped_specific = scope.get_full(base_name)
        global_type = _GLOBAL_MANAGER_TYPES.get(base_name.casefold())
        if scoped_type is not None:
            # A local value shadows a same-named platform collection.
            current_type = scoped_type
            specific = scoped_specific
            remaining = steps[1:]
        elif global_type and len(steps) > 1 and steps[1][0] == "prop":
            # Справочники.Организации... — the specific catalog/document
            # name doesn't change the manager's type (see class docstring).
            current_type = global_type
            specific: frozenset[str] | None = frozenset({steps[1][1]})
            remaining = steps[2:]
        else:
            current_type, specific = scope.get_full(base_name)
            current_type = current_type or base_name
            remaining = steps[1:]

        for kind, name in remaining:
            if kind == "prop" and specific and current_type.casefold() in _ENUM_MANAGER_TYPES:
                # Перечисления.<Имя>.<Значение> — the value name is
                # unbounded, not looked up in RETURN_TYPE_MAP; any bare
                # property access here is a valid value reference.
                current_type = "ПеречислениеСсылка"
                continue
            if kind in ("call", "prop") and current_type:
                # RETURN_TYPE_MAP keys are "type.member" regardless of
                # whether the member is a method or a read-only property
                # (e.g. "деревозначений.строки" — ДеревоЗначений.Строки is
                # a property, not a method) — the platform help doesn't
                # distinguish them for chaining purposes, so neither do we.
                key = f"{current_type.casefold()}.{name.casefold()}"
                current_type = self._rtm.get(key, "")
            else:
                current_type = ""
            if not current_type:
                specific = None

        return current_type, specific

    def _flatten_chain(self, node: Any) -> list[tuple[str, str]]:
        """
        Flatten an `access` / `call_expression` / `property_access` node
        into an ordered list of chain steps:

          ("id", name)    — the leading base identifier
          ("prop", name)  — a `.property` hop
          ("call", name)  — a `.method(...)` hop (name = method identifier)
        """
        steps: list[tuple[str, str]] = []
        for child in node.children:
            ct = child.type
            if ct == "access":
                steps.extend(self._flatten_chain(child))
            elif ct == "identifier":
                steps.append(("id", _node_text(child)))
            elif ct == "property":
                steps.append(("prop", _node_text(child)))
            elif ct == "method_call":
                method_name = ""
                for mc in child.children:
                    if mc.type == "identifier":
                        method_name = _node_text(mc)
                        break
                steps.append(("call", method_name))
        return steps


# ---------------------------------------------------------------------------
# Collection element types (for For-Each loops)
# ---------------------------------------------------------------------------

_COLLECTION_ELEM_TYPE: dict[str, str] = {
    "таблицазначений": "СтрокаТаблицыЗначений",
    "valuetable": "СтрокаТаблицыЗначений",
    "выборкаизрезультатазапроса": "СтрокаВыборкиЗапроса",
    "массив": "",
    "array": "",
    "списокзначений": "ЭлементСпискаЗначений",
    "valuelist": "ЭлементСпискаЗначений",
    "деревозначений": "СтрокаДереваЗначений",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _node_text(node: Any) -> str:
    """Return the source text of a tree-sitter node as a plain string."""
    if node.text is None:
        return ""
    if isinstance(node.text, bytes):
        return node.text.decode("utf-8", errors="replace")
    return str(node.text)
