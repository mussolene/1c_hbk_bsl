"""
Tree-sitter S-expression queries for BSL grammar.

These queries are written against the BSL grammar available via
tree-sitter-languages. Each constant is a multi-line S-expression
string that can be compiled with Language.query(QUERY_STR).

Usage example::

    from tree_sitter_languages import get_language
    from bsl_analyzer.parser.queries import PROCEDURES_QUERY

    lang = get_language("bsl")
    query = lang.query(PROCEDURES_QUERY)
    captures = query.captures(tree.root_node)
"""

# ---------------------------------------------------------------------------
# Procedure / Function declarations
#
# Captures:
#   @proc.def     — the entire procedure/function definition node
#   @proc.name    — the identifier node with the proc/func name
#   @proc.params  — the parameter list node
#   @proc.export  — the "Экспорт"/"Export" keyword (present only when exported)
# ---------------------------------------------------------------------------
PROCEDURES_QUERY = """
(procedure_definition
  name: (identifier) @proc.name
  params: (param_list)? @proc.params
  export: (_)? @proc.export
) @proc.def

(function_definition
  name: (identifier) @proc.name
  params: (param_list)? @proc.params
  export: (_)? @proc.export
) @proc.def
"""

# ---------------------------------------------------------------------------
# Call expressions
#
# Captures:
#   @call.expr    — the full call expression node
#   @call.name    — the identifier (function/method name) being called
#   @call.args    — the argument list node
#
# Covers both standalone calls (ПроцедураА()) and method chains (Obj.Method()).
# ---------------------------------------------------------------------------
CALLS_QUERY = """
(call_expression
  function: (identifier) @call.name
  arguments: (argument_list) @call.args
) @call.expr

(call_expression
  function: (member_expression
    property: (identifier) @call.name)
  arguments: (argument_list) @call.args
) @call.expr
"""

# ---------------------------------------------------------------------------
# Variable declarations
#
# Captures:
#   @var.stmt     — the Перем/Var statement node
#   @var.name     — each declared variable name identifier
#   @var.export   — present when declared with Экспорт/Export modifier
# ---------------------------------------------------------------------------
VARIABLES_QUERY = """
(var_definition
  name: (identifier) @var.name
  export: (_)? @var.export
) @var.stmt
"""

# ---------------------------------------------------------------------------
# #Region / #EndRegion preprocessor blocks
#
# Captures:
#   @region.open  — #Область/#Region directive node
#   @region.name  — the region name string literal
#   @region.close — #КонецОбласти/#EndRegion directive node
# ---------------------------------------------------------------------------
REGIONS_QUERY = """
(preprocessor_region
  name: (_) @region.name
) @region.open

(preprocessor_end_region) @region.close
"""

# ---------------------------------------------------------------------------
# Try/Except/EndTry blocks (used for BSL004: empty exception handler)
#
# Captures:
#   @try.block       — the full try statement
#   @try.handler     — the except (exception handler) body
# ---------------------------------------------------------------------------
TRY_EXCEPT_QUERY = """
(try_statement
  body: (_) @try.body
  handler: (_) @try.handler
) @try.block
"""

# ---------------------------------------------------------------------------
# Return statements — used to detect functions that always return a value
#
# Captures:
#   @return.stmt  — the КонецФункции/Return statement node
#   @return.value — the return value expression (may be absent)
# ---------------------------------------------------------------------------
RETURN_QUERY = """
(return_statement
  value: (_)? @return.value
) @return.stmt
"""
