"""
BSL type inference engine — pure AST walk, no regex on source text.

Grammar node types (tree-sitter-bsl):
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
    new_expression
      NEW_KEYWORD
      identifier                   — type name
      arguments
    call_expression
      access
        identifier                 — object name
      .
      method_call
        identifier                 — method name
        arguments
    identifier                     — variable reference
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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Return-type table  (object_type.method_name → return_type, all lower-case)
# ---------------------------------------------------------------------------

RETURN_TYPE_MAP: dict[str, str] = {
    # Запрос
    "запрос.выполнить":                             "РезультатЗапроса",
    "query.execute":                                "РезультатЗапроса",
    # РезультатЗапроса
    "результатзапроса.выбрать":                     "ВыборкаИзРезультатаЗапроса",
    "queryresult.choose":                           "ВыборкаИзРезультатаЗапроса",
    "результатзапроса.выгрузить":                   "ТаблицаЗначений",
    "queryresult.unload":                           "ТаблицаЗначений",
    # ТаблицаЗначений
    "таблицазначений.найти":                        "СтрокаТаблицыЗначений",
    "valuetable.find":                              "СтрокаТаблицыЗначений",
    "таблицазначений.добавить":                     "СтрокаТаблицыЗначений",
    "valuetable.add":                               "СтрокаТаблицыЗначений",
    "таблицазначений.вставить":                     "СтрокаТаблицыЗначений",
    "valuetable.insert":                            "СтрокаТаблицыЗначений",
    "таблицазначений.скопировать":                  "ТаблицаЗначений",
    "valuetable.copy":                              "ТаблицаЗначений",
    # Дерево значений
    "деревозначений.строки":                        "КоллекцияСтрокДереваЗначений",
    # Список значений
    "списокзначений.найтипозначению":               "ЭлементСпискаЗначений",
    "valuelist.findbyvalue":                        "ЭлементСпискаЗначений",
    "списокзначений.добавить":                      "ЭлементСпискаЗначений",
    "valuelist.add":                                "ЭлементСпискаЗначений",
    # Справочники
    "справочникменеджер.создатьэлемент":            "СправочникОбъект",
    "catalogmanager.createnewitem":                 "СправочникОбъект",
    "справочникменеджер.найти":                     "СправочникСсылка",
    "catalogmanager.find":                          "СправочникСсылка",
    "справочникменеджер.найтипокоду":               "СправочникСсылка",
    "catalogmanager.findbycode":                    "СправочникСсылка",
    "справочникменеджер.найтипонаименованию":       "СправочникСсылка",
    "catalogmanager.findbydescription":             "СправочникСсылка",
    "справочникссылка.получитьобъект":              "СправочникОбъект",
    "catalogref.getobject":                         "СправочникОбъект",
    # Документы
    "документменеджер.создатьдокумент":             "ДокументОбъект",
    "documentmanager.createnewdocument":            "ДокументОбъект",
    "документссылка.получитьобъект":                "ДокументОбъект",
    "documentref.getobject":                        "ДокументОбъект",
    # РегистрыСведений
    "регистрсведенийменеджер.создатьзапись":        "РегистрСведенийЗапись",
    "informationregistermanager.createrecordset":   "РегистрСведенийЗапись",
    "регистрсведенийменеджер.создатьнаборзаписей":  "РегистрСведенийНаборЗаписей",
    # Перечисления
    "перечислениеменеджер.ссылка":                  "ПеречислениеСсылка",
    # HTTP
    "httpsоединение.получить":                      "HTTPОтвет",
    "httpconnection.get":                           "HTTPОтвет",
    "httpсоединение.отправить":                     "HTTPОтвет",
    "httpconnection.post":                          "HTTPОтвет",
    "httpсоединение.вызватьhttp":                   "HTTPОтвет",
    "httpconnection.callhttp":                      "HTTPОтвет",
    # XML
    "чтениеxml.прочитать":                          "ЧтениеXML",
    "чтениеfastinfoset.прочитать":                  "ЧтениеFastInfoset",
    # Структура
    "структура.скопировать":                        "Структура",
    # МенеджерВременныхТаблиц
    "запрос.менеджертаблиц":                        "МенеджерВременныхТаблиц",
    # ТаблицаФормы
    "таблицаформы.найти":                           "СтрокаТаблицыФормы",
    # ОбластьЯчеекТабличногоДокумента
    "табличныйдокумент.получитьобласть":            "ОбластьЯчеекТабличногоДокумента",
    "spreadsheetdocument.getarea":                  "ОбластьЯчеекТабличногоДокумента",
    # ЗапросHTTP
    "httpsзапрос":                                  "HTTPЗапрос",
}


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

@dataclass
class TypeScope:
    """
    Lexical scope mapping lower-cased variable names → canonical type names.

    Scopes are chained: look-up walks the parent chain until a match is found.
    """
    _vars: dict[str, str] = field(default_factory=dict)
    parent: TypeScope | None = None

    def set(self, name: str, type_name: str) -> None:
        if type_name:
            self._vars[name.casefold()] = type_name

    def get(self, name: str) -> str | None:
        name_lo = name.casefold()
        scope: TypeScope | None = self
        while scope is not None:
            if name_lo in scope._vars:
                return scope._vars[name_lo]
            scope = scope.parent
        return None

    def all_vars(self) -> dict[str, str]:
        """Merge all visible variables (inner scope wins)."""
        merged: dict[str, str] = {}
        scope: TypeScope | None = self
        while scope is not None:
            for k, v in scope._vars.items():
                merged.setdefault(k, v)
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
    from tree-sitter node types and node text.
    """

    def __init__(
        self,
        tree: Any,
        *,
        return_type_map: dict[str, str] | None = None,
    ) -> None:
        self._rtm = return_type_map if return_type_map is not None else RETURN_TYPE_MAP
        self._module_scope = TypeScope()
        # Maps 0-based start_line → TypeScope for each proc/function
        self._proc_scopes: list[tuple[int, int, TypeScope]] = []  # (start, end, scope)

        root = getattr(tree, "root_node", None)
        if root is not None and isinstance(getattr(root, "text", None), (bytes, type(None))):
            # Only process real tree-sitter trees (bytes text, not regex fallback)
            self._walk(root, self._module_scope)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scope_at_line(self, line0: int, _tree: Any = None) -> TypeScope:
        """Return the innermost TypeScope visible at *line0* (0-based)."""
        for start, end, scope in self._proc_scopes:
            if start <= line0 <= end:
                return scope
        return self._module_scope

    def infer(self, var_name: str, line0: int) -> str | None:
        """Infer the type of *var_name* visible at *line0*."""
        return self.scope_at_line(line0).get(var_name)

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
            type_name = self._resolve_expr(rhs_node, scope)
            scope.set(lhs_name, type_name)

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
                col_type = self._resolve_expr(child, scope)
                elem_type = _COLLECTION_ELEM_TYPE.get(col_type.casefold(), "")
                scope.set(iter_name, elem_type)
            elif ct not in (
                "FOR_KEYWORD", "EACH_KEYWORD", "IN_KEYWORD",
                "DO_KEYWORD", "ENDDO_KEYWORD", "identifier", ".",
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
    # Expression type resolution
    # ------------------------------------------------------------------

    def _resolve_expr(self, expr_node: Any, scope: TypeScope) -> str:
        """Recursively determine the type of an expression node."""
        for child in expr_node.children:
            ct = child.type
            if ct == "new_expression":
                return self._resolve_new(child)
            elif ct == "call_expression":
                return self._resolve_call(child, scope)
            elif ct == "identifier":
                # Variable reference
                return scope.get(_node_text(child)) or ""
            elif ct == "expression":
                # Nested expression wrapper
                result = self._resolve_expr(child, scope)
                if result:
                    return result
        return ""

    def _resolve_new(self, node: Any) -> str:
        """new_expression → TypeName from the identifier child."""
        for child in node.children:
            if child.type == "identifier":
                return _node_text(child)
        return ""

    def _resolve_call(self, node: Any, scope: TypeScope) -> str:
        """
        call_expression structure:
          access → identifier (object)
          .
          method_call → identifier (method) + arguments
        """
        obj_name = ""
        method_name = ""
        for child in node.children:
            ct = child.type
            if ct == "access":
                for ac in child.children:
                    if ac.type == "identifier":
                        obj_name = _node_text(ac)
            elif ct == "method_call":
                for mc in child.children:
                    if mc.type == "identifier":
                        method_name = _node_text(mc)
                        break

        if obj_name and method_name:
            obj_type = scope.get(obj_name) or obj_name
            key = f"{obj_type.casefold()}.{method_name.casefold()}"
            return self._rtm.get(key, "")
        return ""


# ---------------------------------------------------------------------------
# Collection element types (for For-Each loops)
# ---------------------------------------------------------------------------

_COLLECTION_ELEM_TYPE: dict[str, str] = {
    "таблицазначений":              "СтрокаТаблицыЗначений",
    "valuetable":                   "СтрокаТаблицыЗначений",
    "выборкаизрезультатазапроса":   "СтрокаВыборкиЗапроса",
    "массив":                       "",
    "array":                        "",
    "списокзначений":               "ЭлементСпискаЗначений",
    "valuelist":                    "ЭлементСпискаЗначений",
    "деревозначений":               "СтрокаДереваЗначений",
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
