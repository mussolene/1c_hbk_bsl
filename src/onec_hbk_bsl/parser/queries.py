"""
Tree-sitter S-expression queries for BSL grammar (tree-sitter-bsl).

These queries are written against the actual BSL grammar node types.
Can be compiled with Language.query() or the Query() constructor.

Usage example::

    import tree_sitter_bsl
    from tree_sitter import Language, Query
    from onec_hbk_bsl.parser.queries import PROCEDURES_QUERY

    lang = Language(tree_sitter_bsl.language())
    query = Query(lang, PROCEDURES_QUERY)
    captures = query.captures(tree.root_node)

BSL grammar node types (verified against tree-sitter-bsl):
  procedure_definition  — Процедура … КонецПроцедуры
  function_definition   — Функция … КонецФункции
  parameters            — the ( … ) parameter list          [NOT param_list]
  parameter             — a single parameter node            [NOT param]
  EXPORT_KEYWORD        — Экспорт / Export keyword
  method_call           — any function/procedure call        [NOT call_expression]
  arguments             — the ( … ) argument list            [NOT argument_list]
  call_expression       — chained call: Obj.Method()
  call_statement        — statement wrapping a call
  var_definition        — Перем … ;
  preprocessor          — #Область / #КонецОбласти block
  try_statement         — Попытка … Исключение … КонецПопытки
  return_statement      — Возврат …
"""

# ---------------------------------------------------------------------------
# Procedure / Function declarations
#
# Captures:
#   @proc.def     — the entire procedure/function definition node
#   @proc.name    — the identifier node with the proc/func name
#   @proc.params  — the parameter list node
#   @proc.export  — the EXPORT_KEYWORD node (present only when exported)
# ---------------------------------------------------------------------------
PROCEDURES_QUERY = """
(procedure_definition
  name: (identifier) @proc.name
  parameters: (parameters)? @proc.params
  export: (EXPORT_KEYWORD)? @proc.export
) @proc.def

(function_definition
  name: (identifier) @proc.name
  parameters: (parameters)? @proc.params
  export: (EXPORT_KEYWORD)? @proc.export
) @proc.def
"""

# ---------------------------------------------------------------------------
# Call expressions
#
# Captures:
#   @call.stmt    — the full call_statement or containing node
#   @call.name    — the identifier (function/method name) being called
#   @call.args    — the argument list node
#
# Covers both standalone calls (ПроцедураА()) and chained calls (Obj.Method()).
# All calls in BSL use method_call nodes, which appear either directly in
# call_statement or nested inside call_expression (for chained calls).
# ---------------------------------------------------------------------------
CALLS_QUERY = """
(method_call
  (identifier) @call.name
  (arguments) @call.args
) @call.expr
"""

# ---------------------------------------------------------------------------
# Variable declarations
#
# Captures:
#   @var.stmt   — the Перем/Var statement node
#   @var.name   — each declared variable name identifier
#   @var.export — present when declared with Экспорт/Export modifier
#
# Note: BSL has two variable node types:
#   var_definition — module-level:  Перем Имя Экспорт;
#   var_statement  — inside body:   Перем Имя;  (no Export allowed)
# ---------------------------------------------------------------------------
VARIABLES_QUERY = """
(var_definition
  (identifier) @var.name
  (EXPORT_KEYWORD)? @var.export
) @var.stmt

(var_statement
  (identifier) @var.name
) @var.stmt
"""

# ---------------------------------------------------------------------------
# #Region / #EndRegion preprocessor blocks
#
# Captures:
#   @region.open  — the preprocessor node containing PREPROC_REGION_KEYWORD
#   @region.name  — the region name identifier
#   @region.close — the preprocessor node containing PREPROC_ENDREGION_KEYWORD
# ---------------------------------------------------------------------------
REGIONS_QUERY = """
(preprocessor
  (PREPROC_REGION_KEYWORD)
  (identifier) @region.name
) @region.open

(preprocessor
  (PREPROC_ENDREGION_KEYWORD)
) @region.close
"""

# ---------------------------------------------------------------------------
# Try/Except/EndTry blocks (used for BSL004: empty exception handler)
#
# Captures:
#   @try.block    — the full try statement
# ---------------------------------------------------------------------------
TRY_EXCEPT_QUERY = """
(try_statement) @try.block
"""

# ---------------------------------------------------------------------------
# Return statements — used to detect functions that always return a value
#
# Captures:
#   @return.stmt  — the return statement node
#   @return.value — the return value expression (may be absent)
# ---------------------------------------------------------------------------
RETURN_QUERY = """
(return_statement
  (expression)? @return.value
) @return.stmt
"""
