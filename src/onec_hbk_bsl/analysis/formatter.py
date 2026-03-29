"""BSL source code formatter.

Structural (block) indentation is derived from the **tree-sitter BSL CST** (parse
tree) when the parse is available and has no ERROR nodes; otherwise a keyword
heuristic matches the previous line-based behaviour.

Multi-line expression rules (BSL Language Server style): extra indent after a
bare ``=`` until ``;``, extra for lines starting with ``.``, suppressed inside
procedure signatures and inside ``Если``/``Пока``/``Для`` conditions until
``Тогда``/``Цикл``/``Do``.

Full-line ``//`` / ``///`` comments: spaces after the slashes are normalized to a
single space before non-empty text. Contiguous multi-line comment blocks (no blank
lines between) get extra rules: documentation section headers (``Параметры``,
``Parameters``, ``Возвращаемое значение``, ``Returns``, ``Описание``, ``Description``,
``Пример``, ``Example``) are whitespace-normalized; continuation lines under a
section and wrapped preamble lines use a uniform hanging indent after ``// `` so
multi-line descriptions align.

Wrapped procedure/function parameters (``Функция Имя(`` then parameters on the
next lines) get one extra indent level so continuation lines use a "double"
indent relative to the block baseline (BSL-LS style).
"""
from __future__ import annotations

import re
from collections.abc import Callable

from onec_hbk_bsl.analysis.formatter_ast_spacing import normalize_argument_list_spacing
from onec_hbk_bsl.analysis.formatter_structural import ast_structural_indent_levels, tree_has_errors
from onec_hbk_bsl.parser.bsl_parser import BslParser

# ---------------------------------------------------------------------------
# Keyword normalization tables
# ---------------------------------------------------------------------------

# Maps lowercase variant -> canonical form
_KEYWORDS: dict[str, str] = {
    # RU
    "процедура": "Процедура",
    "конецпроцедуры": "КонецПроцедуры",
    "функция": "Функция",
    "конецфункции": "КонецФункции",
    "если": "Если",
    "иначеесли": "ИначеЕсли",
    "иначе": "Иначе",
    "конецесли": "КонецЕсли",
    "тогда": "Тогда",
    "для": "Для",
    "каждого": "Каждого",
    "из": "Из",
    "по": "По",
    "цикл": "Цикл",
    "конеццикла": "КонецЦикла",
    "пока": "Пока",
    "попытка": "Попытка",
    "исключение": "Исключение",
    "конецпопытки": "КонецПопытки",
    "возврат": "Возврат",
    "прервать": "Прервать",
    "продолжить": "Продолжить",
    "перем": "Перем",
    "экспорт": "Экспорт",
    "новый": "Новый",
    "выбор": "Выбор",
    "когда": "Когда",
    "конецвыбора": "КонецВыбора",
    "выполнить": "Выполнить",
    "истина": "Истина",
    "ложь": "Ложь",
    "неопределено": "Неопределено",
    "типзнч": "ТипЗнч",
    "тип": "Тип",
    # EN
    "procedure": "Procedure",
    "endprocedure": "EndProcedure",
    "function": "Function",
    "endfunction": "EndFunction",
    "if": "If",
    "elsif": "ElsIf",
    "else": "Else",
    "endif": "EndIf",
    "then": "Then",
    "for": "For",
    "each": "Each",
    "in": "In",
    "to": "To",
    "do": "Do",
    "enddo": "EndDo",
    "while": "While",
    "try": "Try",
    "except": "Except",
    "endtry": "EndTry",
    "return": "Return",
    "break": "Break",
    "continue": "Continue",
    "var": "Var",
    "export": "Export",
    "new": "New",
    "case": "Case",
    "when": "When",
    "endcase": "EndCase",
    "execute": "Execute",
    "true": "True",
    "false": "False",
    "undefined": "Undefined",
    "null": "Null",
    "and": "And",
    "or": "Or",
    "not": "Not",
    "typeof": "TypeOf",
    "type": "Type",
    # Boolean-like RU (и/или/не are short words — handle them last to avoid collision)
    "и": "И",
    # BSLLS uses uppercase ИЛИ for the logical operator (matches typical 1C style).
    "или": "ИЛИ",
    # Unary / boolean NOT keyword (BSLLS uses НЕ).
    "не": "НЕ",
}

# Build a single regex that matches any keyword as a whole word (case-insensitive).
# Order longer variants first to prevent partial matches (e.g. "иначеесли" before "иначе").
_sorted_kw = sorted(_KEYWORDS.keys(), key=len, reverse=True)
_KW_PATTERN = re.compile(
    r"(?<![А-Яа-яA-Za-z_\d])"
    r"(" + "|".join(re.escape(k) for k in _sorted_kw) + r")"
    r"(?![А-Яа-яA-Za-z_\d])",
    re.IGNORECASE | re.UNICODE,
)

# ---------------------------------------------------------------------------
# Indent-control keywords (all lowercase for matching after .lower())
# ---------------------------------------------------------------------------

# Lines whose *content* (after stripping) starts with these trigger dedent-before
_DEDENT_BEFORE: frozenset[str] = frozenset(
    [
        "конецпроцедуры",
        "endprocedure",
        "конецфункции",
        "endfunction",
        "конецесли",
        "endif",
        "конеццикла",
        "enddo",
        "конецпопытки",
        "endtry",
        "конецвыбора",
        "endcase",
        "иначеесли",
        "elsif",
        "иначе",
        "else",
        "исключение",
        "except",
        "когда",
        "when",
    ]
)

# Lines that trigger indent-after
_INDENT_AFTER_STARTS: frozenset[str] = frozenset(
    [
        "процедура",
        "procedure",
        "функция",
        "function",
        "попытка",
        "try",
        "выбор",
        "case",
    ]
)

# Lines that *end* with these keywords trigger indent-after (Если/Для/Пока)
_INDENT_AFTER_ENDS: frozenset[str] = frozenset(
    [
        "тогда",
        "then",
        "цикл",
        "do",
    ]
)

# Lines that trigger indent-after (same-level openers: dedent-before + indent-after)
_SAME_LEVEL_OPENERS: frozenset[str] = frozenset(
    [
        "иначеесли",
        "elsif",
        "иначе",
        "else",
        "исключение",
        "except",
        "когда",
        "when",
    ]
)

# Preprocessor directives — any line starting with # followed by a letter.
# These include #Область/#Region (folding) and #Если/#КонецЕсли (conditionals).
# They are output at the current indent level but do NOT change the indent counter —
# preprocessor structure is orthogonal to the runtime code structure.
_PREPROCESSOR_PATTERN = re.compile(
    r"^(\s*)(#[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z]*)(.*)",
    re.IGNORECASE | re.UNICODE,
)

# ---------------------------------------------------------------------------
# Binary-operator spacing
# ---------------------------------------------------------------------------

# Comparison operators pattern (longer first to avoid <> being split into < >)
_CMP_OP_RE = re.compile(r"\s*(<>|<=|>=|<|>)\s*")
# Assignment = (not preceded by < > ! : and not followed by >)
_EQ_OP_RE = re.compile(r"(?<![!<>=:])(\s*)(=)(\s*)(?![>])")
# Arithmetic operators +, -, *, / — but not unary minus at line start or after ( , =
_ARITH_OP_RE = re.compile(r"(?<=[\w\d\)])\s*([+\-*/])\s*(?=[\w\d\(\"А-ЯЁа-яё])", re.UNICODE)

# Canonical case for preprocessor words
_PP_CANONICAL: dict[str, str] = {
    "область": "#Область",
    "конецобласти": "#КонецОбласти",
    "region": "#Region",
    "endregion": "#EndRegion",
    "если": "#Если",
    "иначеесли": "#ИначеЕсли",
    "иначе": "#Иначе",
    "конецесли": "#КонецЕсли",
    "if": "#If",
    "elseif": "#ElseIf",
    "else": "#Else",
    "endif": "#EndIf",
    "использоватьрасширение": "#ИспользоватьРасширение",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_line_comment_spaces(stripped: str) -> str:
    """Normalize a full-line // comment: ``//`` + one space + trimmed text (BSL LS style)."""
    if not stripped.startswith("//"):
        return stripped
    # XML-doc / structured lines (/// …) — keep one space after ///, preserve rest of the line
    if stripped.startswith("///"):
        rest = stripped[3:]
        if not rest.strip():
            return "///"
        return "/// " + rest.lstrip()
    rest = stripped[2:]
    if not rest.strip():
        return "//"
    return "// " + rest.lstrip()


# Documentation blocks (Parameters / Returns / …) inside contiguous // or /// runs.
_DOC_SECTION_HEADER = re.compile(
    r"^\s*(?:"
    r"Параметры|Parameters|"
    r"Возвращаемое\s+значение|Returns|"
    r"Описание|Description|"
    r"Пример|Example"
    r")\s*:",
    re.IGNORECASE | re.UNICODE,
)


def _comment_prefix_and_core(stripped: str) -> tuple[str, str]:
    """Return ``("//" or "///", text after the slashes)."""
    s = stripped.strip()
    if s.startswith("///"):
        return "///", s[3:].lstrip()
    if s.startswith("//"):
        return "//", s[2:].lstrip()
    return "//", s.lstrip()


def _find_contiguous_full_line_comment_runs(lines: list[str]) -> list[tuple[int, int]]:
    """Inclusive [start, end] indices of runs of 2+ consecutive full-line ``//``/``///`` lines.

    A blank line or a non-comment line ends the run.
    """
    n = len(lines)
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        st = _strip_indent(lines[i].rstrip())
        if not st or not st.startswith("//"):
            i += 1
            continue
        j = i
        while j + 1 < n:
            nst = _strip_indent(lines[j + 1].rstrip())
            if not nst:
                break
            if not nst.startswith("//"):
                break
            j += 1
        if j > i:
            runs.append((i, j))
        i = j + 1
    return runs


def _normalize_doc_comment_block_stripped(
    stripped_lines: list[str],
    *,
    inner_spaces: int = 2,
) -> list[str]:
    """Normalize a contiguous block of stripped full-line ``//``/``///`` lines (2+ lines).

    * Section headers (Параметры / Parameters / …) are collapsed to single spaces.
    * Lines after a section header, and preamble continuation lines before the first
      header, get a hanging indent of ``inner_spaces`` extra spaces after ``// ``/``/// ``.
    * Default ``inner_spaces=2`` produces the BSLLS-standard 3-space indent
      (``//   content``) that also satisfies BSL215 ``\\s{1,4}`` entry pattern.
    """
    sp = " " * inner_spaces
    first_header_idx: int | None = None
    for idx, line in enumerate(stripped_lines):
        _pref, core = _comment_prefix_and_core(line)
        if not core.strip():
            continue
        if _DOC_SECTION_HEADER.match(core):
            first_header_idx = idx
            break

    out: list[str] = []
    for idx, line in enumerate(stripped_lines):
        pref, core = _comment_prefix_and_core(line)
        if not core.strip():
            out.append("///" if pref == "///" else "//")
            continue

        if _DOC_SECTION_HEADER.match(core):
            canon = re.sub(r"\s+", " ", core.strip())
            canon = re.sub(r" +:", ":", canon)
            out.append(f"{pref} {canon}")
            continue

        # Non-header body line
        if first_header_idx is None:
            if idx > 0:
                out.append(f"{pref} {sp}{core.lstrip()}")
            else:
                out.append(f"{pref} {core.strip()}")
            continue

        if idx < first_header_idx:
            if idx > 0:
                out.append(f"{pref} {sp}{core.lstrip()}")
            else:
                out.append(f"{pref} {core.strip()}")
            continue

        out.append(f"{pref} {sp}{core.lstrip()}")

    return out


def _precompute_multiline_doc_comment_stripped(lines: list[str]) -> dict[int, str]:
    """Map line index -> normalized stripped comment for lines in 2+ line comment runs."""
    out: dict[int, str] = {}
    for start, end in _find_contiguous_full_line_comment_runs(lines):
        block = [_strip_indent(lines[k].rstrip()) for k in range(start, end + 1)]
        normed = _normalize_doc_comment_block_stripped(block)
        for k, idx in enumerate(range(start, end + 1)):
            out[idx] = normed[k]
    return out


def _tokenize(line: str) -> list[tuple[str, str]]:
    """Split a line into tokens of types: 'string', 'comment', 'code'.

    Returns list of (token_type, text) tuples whose concatenation == line.
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"':
            # String literal — consume until closing quote (doubled quotes are escapes)
            j = i + 1
            while j < n:
                if line[j] == '"':
                    j += 1
                    if j < n and line[j] == '"':
                        j += 1  # escaped quote
                    else:
                        break
                else:
                    j += 1
            tokens.append(("string", line[i:j]))
            i = j
        elif line[i : i + 2] == "//":
            # Comment — rest of line
            tokens.append(("comment", line[i:]))
            i = n
        else:
            # Collect code until next special char
            j = i + 1
            while j < n and line[j] != '"' and line[j : j + 2] != "//":
                j += 1
            tokens.append(("code", line[i:j]))
            i = j
    return tokens


def _squeeze_whitespace_runs(code: str) -> str:
    """Collapse runs of spaces/tabs in a code fragment to a single space (no regex)."""
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch in " \t":
            j = i + 1
            while j < n and code[j] in " \t":
                j += 1
            out.append(" ")
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _normalize_keywords_in_code(code: str) -> str:
    """Replace keywords in a pure code segment."""

    def replacer(m: re.Match) -> str:  # type: ignore[type-arg]
        word = m.group(0)
        return _KEYWORDS.get(word.lower(), word)

    return _KW_PATTERN.sub(replacer, code)


def _add_operator_spaces(code: str, in_proc_header: bool) -> str:
    """Add spaces around comparison and assignment operators in a code segment.

    Arithmetic operators (+, -, *, /) are intentionally NOT touched —
    BSL-LS formatter does not add spaces around them, and doing so
    incorrectly modifies expressions like ``Array[i-1]`` or date offsets.
    """
    # Comparison operators first (handles <>, <=, >= before < and >)
    result = _CMP_OP_RE.sub(lambda m: f" {m.group(1)} ", code)

    # Skip = spacing inside proc headers (default param values like А = 0)
    if not in_proc_header:
        result = _EQ_OP_RE.sub(lambda m: f" {m.group(2)} ", result)

    result = _squeeze_whitespace_runs(result)
    return result


def _strip_indent(line: str) -> str:
    return line.lstrip(" \t")


def _get_stripped_keyword(line: str) -> str:
    """Return the first word of the stripped line, lowercased."""
    stripped = _strip_indent(line)
    m = re.match(r"([А-Яа-яA-Za-z_#][А-Яа-яA-Za-z0-9_]*)", stripped, re.UNICODE)
    if m:
        return m.group(1).lower()
    return ""


def _get_last_keyword(line: str) -> str:
    """Return the last word of the stripped line (excluding trailing ;), lowercased."""
    stripped = _strip_indent(line).rstrip(";").rstrip()
    # Only look at the code part (ignore comment/strings at end)
    tokens = _tokenize(stripped)
    code_part = "".join(t[1] for t in tokens if t[0] == "code").rstrip(";").rstrip()
    m = re.search(r"([А-Яа-яA-Za-z_][А-Яа-яA-Za-z0-9_]*)$", code_part, re.UNICODE)
    if m:
        return m.group(1).lower()
    return ""


def _is_proc_or_func_header(line: str) -> bool:
    """True if line starts a procedure or function definition."""
    first = _get_stripped_keyword(line)
    return first in ("процедура", "функция", "procedure", "function")


def _indent_control(stripped: str) -> tuple[bool, bool]:
    """Return (dedent_before, indent_after) for a stripped (already keyword-normalised) line."""
    # Get first word
    tokens = _tokenize(stripped)
    code_part = "".join(t[1] for t in tokens if t[0] == "code")
    first_m = re.match(r"([А-Яа-яA-Za-z_][А-Яа-яA-Za-z0-9_]*)", code_part, re.UNICODE)
    first_word = first_m.group(1).lower() if first_m else ""

    last_word = _get_last_keyword(stripped)

    dedent_before = first_word in _DEDENT_BEFORE
    indent_after = first_word in _INDENT_AFTER_STARTS or last_word in _INDENT_AFTER_ENDS

    # Same-level openers are dedented first, then open a new nested block.
    # For ElseIf/When this must happen only when the condition is closed
    # with Тогда/Then on the same logical line.
    if first_word in ("иначе", "else", "исключение", "except"):
        indent_after = True
    elif first_word in ("иначеесли", "elsif", "когда", "when"):
        indent_after = last_word in _INDENT_AFTER_ENDS

    return dedent_before, indent_after


# ---------------------------------------------------------------------------
# BSL LS–compatible continuation / signature (line-based)
# ---------------------------------------------------------------------------

# Opening keywords for "operator" context (condition / head) until Then/Do.
_OP_OPEN_FIRST: frozenset[str] = frozenset(
    [
        "если",
        "if",
        "иначеесли",
        "elsif",
        "пока",
        "while",
        "для",
        "for",
    ]
)

# First word on a line that cannot be a multiline assignment tail (heuristic).
_CONTINUATION_BREAK_FIRST: frozenset[str] = frozenset(
    _DEDENT_BEFORE
    | _INDENT_AFTER_STARTS
    | frozenset(
        [
            "возврат",
            "return",
            "прервать",
            "break",
            "продолжить",
            "continue",
            "перем",
            "var",
            "выполнить",
            "execute",
            "если",
            "if",
            "пока",
            "while",
            "для",
            "for",
        ]
    )
)

# Single `=` used as assignment (not <=, >=, <>, !=).
_ASSIGN_EQ_RE = re.compile(r"(?<![!<>=])(?<!=)=(?!=)")


def _strip_inline_comment_from_code(code: str) -> str:
    """Remove // comment from a code fragment (not string-aware — same as line heuristics)."""
    if "//" in code:
        code = code.split("//", 1)[0]
    return code


def _line_ends_with_semicolon(stripped: str) -> bool:
    """True if the code part ends with ``;`` (after stripping // comment)."""
    tokens = _tokenize(stripped)
    code = "".join(t[1] for t in tokens if t[0] == "code")
    code = _strip_inline_comment_from_code(code).rstrip()
    return code.endswith(";")


def _line_expression_ends_with_open_paren(stripped: str) -> bool:
    """Code ends with ``(`` — next line continues the parenthesised expression (BSLLS-style)."""
    tokens = _tokenize(stripped)
    code = "".join(t[1] for t in tokens if t[0] == "code")
    code = _strip_inline_comment_from_code(code).rstrip()
    return code.endswith("(")


def _line_starts_with_dot(stripped: str) -> bool:
    """Leading `.` on a code line (method chain continuation)."""
    tokens = _tokenize(stripped)
    code = "".join(t[1] for t in tokens if t[0] == "code").lstrip()
    return code.startswith(".")


def _line_opens_operator(stripped: str) -> bool:
    first = _get_stripped_keyword(stripped)
    return first in _OP_OPEN_FIRST


def _line_ends_operator(stripped: str) -> bool:
    return _get_last_keyword(stripped) in _INDENT_AFTER_ENDS


def _paren_delta_in_code(stripped: str) -> int:
    """Net ``(`` − ``)`` count in code tokens only."""
    delta = 0
    tokens = _tokenize(stripped)
    for ttype, text in tokens:
        if ttype != "code":
            continue
        for ch in text:
            if ch == "(":
                delta += 1
            elif ch == ")":
                delta -= 1
    return delta


def _line_has_assignment_without_semicolon(stripped: str) -> bool:
    """Assignment `=` on the line without a trailing ``;`` (code only)."""
    tokens = _tokenize(stripped)
    code = "".join(t[1] for t in tokens if t[0] == "code")
    code = _strip_inline_comment_from_code(code).rstrip()
    if code.endswith(";"):
        return False
    return bool(_ASSIGN_EQ_RE.search(code))


def _is_special_layout_line(raw_line: str) -> bool:
    stripped = _strip_indent(raw_line.rstrip())
    if not stripped:
        return True
    if stripped.startswith("//"):
        return True
    if _PREPROCESSOR_PATTERN.match(stripped):
        return True
    return False


def _heuristic_structural_indent_levels(lines: list[str]) -> list[int]:
    """Base indent level before each line (keyword state machine, no assign/dot extra)."""
    current_indent = 0
    out: list[int] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = _strip_indent(line)
        if not stripped:
            out.append(current_indent)
            continue
        if stripped.startswith("//"):
            out.append(current_indent)
            continue
        if _PREPROCESSOR_PATTERN.match(stripped):
            out.append(current_indent)
            continue

        processed = _process_code_line_static(
            stripped, in_proc_header=_is_proc_or_func_header(stripped)
        )
        proc_stripped = _strip_indent(processed)
        dedent_before, indent_after = _indent_control(proc_stripped)
        if dedent_before:
            current_indent = max(0, current_indent - 1)
        out.append(current_indent)
        if indent_after:
            current_indent += 1
    return out


def _compute_structural_indent_levels(lines: list[str], text: str) -> list[int]:
    """Per-line base indent: CST (structural) + heuristic merge for special lines."""
    n = len(lines)
    if n == 0:
        return []
    heur = _heuristic_structural_indent_levels(lines)
    parser = BslParser()
    tree = parser.parse_content(text)
    if getattr(tree, "content", None) is not None:
        return heur
    if tree_has_errors(tree.root_node):
        return heur
    ast = ast_structural_indent_levels(tree.root_node, n)
    merged: list[int] = []
    for i, raw in enumerate(lines):
        if _is_special_layout_line(raw):
            merged.append(heur[i])
        else:
            merged.append(max(heur[i], ast[i]))
    return merged


def _process_code_line_static(stripped: str, in_proc_header: bool) -> str:
    """Keyword normalisation + operator spacing (no BslFormatter instance)."""
    tokens = _tokenize(stripped)
    result_parts: list[str] = []
    for ttype, text in tokens:
        if ttype == "code":
            text = _normalize_keywords_in_code(text)
            text = _add_operator_spaces(text, in_proc_header=in_proc_header)
        elif ttype == "comment" and text.startswith("//") and result_parts:
            # BSL136 / BSLLS MissingSpaceBeforeComment: space before trailing //
            prev = result_parts[-1]
            if prev and not prev[-1].isspace():
                result_parts.append(" ")
        result_parts.append(text)
    result = "".join(result_parts)
    result = _collapse_spaces_static(result)
    return result.rstrip()


def _collapse_spaces_static(line: str) -> str:
    tokens = _tokenize(line)
    parts: list[str] = []
    for ttype, text in tokens:
        if ttype == "code":
            text = _squeeze_whitespace_runs(text)
        parts.append(text)
    return "".join(parts)


def _code_mask_for_layout_match(line: str) -> str:
    """Same length as ``line``; strings and comments replaced with spaces (layout-safe regex)."""
    parts: list[str] = []
    for ttype, text in _tokenize(line):
        if ttype in ("string", "comment"):
            parts.append(" " * len(text))
        else:
            parts.append(text)
    return "".join(parts)


def _tail_ok_after_then(tail: str) -> bool:
    """First statement after ``Тогда`` should not be only a block closer at same line."""
    t = tail.strip()
    if not t or t.startswith("//"):
        return False
    kw = _get_stripped_keyword(t)
    if kw in ("конецесли", "endif", "иначе", "else", "иначеесли", "elsif"):
        return False
    return True


def _tail_ok_after_loop(tail: str) -> bool:
    t = tail.strip()
    if not t or t.startswith("//"):
        return False
    kw = _get_stripped_keyword(t)
    if kw in ("конеццикла", "enddo"):
        return False
    return True


# (pattern on layout line, tail validator)
_BLOCK_HEADER_ONE_LINE: list[tuple[re.Pattern[str], Callable[[str], bool]]] = [
    (re.compile(r"^(\s*)(Если\b.*\bТогда)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_then),
    (re.compile(r"^(\s*)(If\b.*\bThen)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_then),
    (re.compile(r"^(\s*)(ИначеЕсли\b.*\bТогда)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_then),
    (re.compile(r"^(\s*)(ElsIf\b.*\bThen)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_then),
    (re.compile(r"^(\s*)(Пока\b.*\bЦикл)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_loop),
    (re.compile(r"^(\s*)(While\b.*\bDo)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_loop),
    (re.compile(r"^(\s*)(Для\b.*\bЦикл)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_loop),
    (re.compile(r"^(\s*)(For\b.*\bDo)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_loop),
]


def _try_split_block_header_one_line(line: str) -> list[str] | None:
    """Split ``Если … Тогда <stmt>`` (and similar) into two lines so body indents vertically."""
    if not line.strip():
        return None
    layout = _code_mask_for_layout_match(line)
    if layout.lstrip().startswith("//"):
        return None
    layout_raw = layout.rstrip()
    for pat, tail_ok in _BLOCK_HEADER_ONE_LINE:
        m = pat.match(layout_raw)
        if not m:
            continue
        tail_src = line[m.start(3) : m.end(3)].strip()
        if not tail_ok(tail_src):
            continue
        head_line = line[: m.end(2)].rstrip()
        indent = line[m.start(1) : m.end(1)]
        return [head_line, indent + tail_src]
    return None


def _expand_block_headers_one_line(lines: list[str]) -> list[str]:
    """Insert line breaks after ``Тогда``/``Цикл``/``Do`` when the block body starts on the same line."""
    out: list[str] = []
    for line in lines:
        spl = _try_split_block_header_one_line(line)
        if spl:
            out.extend(spl)
        else:
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# Main formatter class
# ---------------------------------------------------------------------------


class BslFormatter:
    """Formats BSL (1C:Enterprise) source code."""

    def format(  # noqa: A003
        self,
        content: str,
        indent_size: int = 4,
        insert_spaces: bool = True,
    ) -> str:
        """Format an entire BSL source file."""
        if content.startswith("\ufeff"):
            content = content[1:]
        lines = _expand_block_headers_one_line(content.splitlines())
        text = "\n".join(lines)
        parser = BslParser()
        tree = parser.parse_content(text)
        if getattr(tree, "content", None) is None and not tree_has_errors(tree.root_node):
            text = normalize_argument_list_spacing(text, tree.root_node)
            lines = text.splitlines()
        formatted, _ = self._format_lines(
            lines,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
            text_for_parse=text,
        )
        # Normalise blank runs: at most one empty line in a row (BSL055 / BSLLS ConsecutiveEmptyLines)
        result = self._normalize_blank_lines(formatted)
        # Strip leading blank lines (BSLLS does not emit them even when source has BOM+newline)
        result = result.lstrip("\n")
        # Ensure single trailing newline
        result = result.rstrip("\n") + "\n"
        return result

    def format_range(
        self,
        content: str,
        start_line: int,
        end_line: int,
        indent_size: int = 4,
        insert_spaces: bool = True,
    ) -> str:
        """Format lines [start_line, end_line] (0-based, inclusive).

        Determines the correct indent level at start_line by scanning the
        preceding lines as context, then formats only the selected range.
        Unselected lines are never modified.

        Returns the formatted text for the range only
        (TextEdit-compatible: replace lines start_line..end_line with this text).
        """
        if content.startswith("\ufeff"):
            content = content[1:]
        all_lines = content.splitlines()
        s = max(0, start_line)
        e = min(len(all_lines) - 1, end_line)

        selected = all_lines[s : e + 1]
        full_base = _compute_structural_indent_levels(all_lines, content)
        slice_base = full_base[s : e + 1] if full_base else []
        formatted, _ = self._format_lines(
            selected,
            indent_size=indent_size,
            initial_indent=0,
            insert_spaces=insert_spaces,
            text_for_parse=content,
            base_levels=slice_base,
        )
        return formatted + "\n"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _indent_at(
        self,
        full_lines: list[str],
        target: int,
        indent_size: int,
        *,
        insert_spaces: bool = True,
        full_text: str,
    ) -> int:
        """Indent level for line *target* (0-based). Uses full-document CST when possible."""
        if target <= 0:
            return 0
        if target > len(full_lines):
            return 0
        base_levels = _compute_structural_indent_levels(full_lines, full_text)
        next_struct = base_levels[target] if target < len(base_levels) else (base_levels[-1] if base_levels else 0)
        _, next_level = self._format_lines(
            full_lines[:target],
            indent_size=indent_size,
            initial_indent=0,
            output=False,
            insert_spaces=insert_spaces,
            text_for_parse=full_text,
            base_levels=base_levels[:target],
            next_line_structural=next_struct,
        )
        return next_level

    def _format_lines(
        self,
        lines: list[str],
        indent_size: int,
        initial_indent: int = 0,
        output: bool = True,
        insert_spaces: bool = True,
        *,
        text_for_parse: str | None = None,
        base_levels: list[int] | None = None,
        next_line_structural: int | None = None,
    ) -> tuple[str, int]:
        """Core formatting pass: keyword normalisation, indentation, spacing.

        Args:
            lines:          Lines to format.
            indent_size:    Spaces per indent level.
            initial_indent: Added to structural base (range formatting into a block).
            output:         If False, only track indent (dry run — for context building).
            text_for_parse: Full text for tree-sitter (defaults to joined lines).
            base_levels:    Precomputed structural indent per line (same length as lines).

        Returns:
            (formatted_text, next_line_indent_level)
        """
        text = text_for_parse if text_for_parse is not None else "\n".join(lines)
        if base_levels is None:
            base_levels = _compute_structural_indent_levels(lines, text)
        if len(base_levels) != len(lines):
            base_levels = _compute_structural_indent_levels(lines, text)

        comment_multiline = _precompute_multiline_doc_comment_stripped(lines)

        result: list[str] = []
        continuation = False
        inside_operator = False
        in_method_sig = False
        balance = 0

        for i, raw_line in enumerate(lines):
            line = raw_line.rstrip()
            stripped = _strip_indent(line)

            if not stripped:
                if output:
                    result.append("")
                continue

            # BSL multi-line string continuation: lines starting with | are string
            # content — preserve content verbatim, only re-apply structural indentation.
            if stripped.startswith("|"):
                if output:
                    extra = 1 if (continuation or in_method_sig) else 0
                    lvl = base_levels[i] + initial_indent + extra
                    result.append(self._indent(lvl, indent_size, insert_spaces) + stripped)
                # Update continuation: if the line ends the statement (closing "; or ") we
                # reset it; otherwise leave continuation unchanged so subsequent | lines are
                # indented correctly.
                raw_stripped = stripped.rstrip()
                if raw_stripped.endswith('";') or raw_stripped.endswith("';"):
                    continuation = False
                continue

            is_comment_line = stripped.startswith("//")
            pp_match = _PREPROCESSOR_PATTERN.match(stripped)

            if is_comment_line:
                stripped = comment_multiline.get(i, _normalize_line_comment_spaces(stripped))
                if output:
                    lvl = base_levels[i] + initial_indent
                    result.append(self._indent(lvl, indent_size, insert_spaces) + stripped)
                continue

            if pp_match:
                if output:
                    tag = pp_match.group(2)
                    rest = pp_match.group(3)
                    canonical = _PP_CANONICAL.get(tag.lstrip("#").lower(), tag)
                    lvl = base_levels[i] + initial_indent
                    result.append(self._indent(lvl, indent_size, insert_spaces) + canonical + rest)
                continue

            processed = self._process_code_line(
                stripped, in_proc_header=_is_proc_or_func_header(stripped)
            )
            proc_stripped = _strip_indent(processed)

            kw0 = _get_stripped_keyword(proc_stripped)
            if kw0 in _CONTINUATION_BREAK_FIRST:
                continuation = False
            inside_op_for_assign = inside_operator or _line_opens_operator(proc_stripped)

            extra_level = 1 if (continuation or _line_starts_with_dot(proc_stripped)) else 0
            # Lines that continue a split Процедура/Функция parameter list (unclosed `(` from header).
            if in_method_sig:
                extra_level += 1
            base = base_levels[i] + initial_indent

            if output:
                out_level = base + extra_level
                result.append(self._indent(out_level, indent_size, insert_spaces) + proc_stripped)

            if _line_ends_with_semicolon(proc_stripped):
                continuation = False
            elif (
                not in_method_sig
                and not inside_op_for_assign
                and _line_has_assignment_without_semicolon(proc_stripped)
                and not _is_proc_or_func_header(proc_stripped)
            ):
                continuation = True
            elif (
                not in_method_sig
                and not _is_proc_or_func_header(proc_stripped)
                and kw0 in ("если", "if", "иначеесли", "elsif")
                and _line_has_assignment_without_semicolon(proc_stripped)
                and ("тогда" not in proc_stripped.lower())
                and ("then" not in proc_stripped.lower())
            ):
                # Multiline Если/ИначеЕсли condition: next line may be ИЛИ/…/Тогда even though
                # this line opens operator context (inside_op_for_assign would block above).
                continuation = True
            elif (
                not in_method_sig
                and not _is_proc_or_func_header(proc_stripped)
                and _line_expression_ends_with_open_paren(proc_stripped)
            ):
                continuation = True
            elif _line_starts_with_dot(proc_stripped):
                continuation = True

            if _line_opens_operator(proc_stripped):
                inside_operator = True
            if inside_operator and _line_ends_operator(proc_stripped):
                inside_operator = False

            if _is_proc_or_func_header(proc_stripped):
                balance = _paren_delta_in_code(proc_stripped)
                in_method_sig = balance > 0
            elif in_method_sig:
                balance += _paren_delta_in_code(proc_stripped)
                if balance <= 0:
                    in_method_sig = False
                    balance = 0

        if next_line_structural is not None:
            next_struct = next_line_structural
        elif lines and len(base_levels) > len(lines):
            next_struct = base_levels[len(lines)]
        elif lines:
            next_struct = base_levels[-1]
        else:
            next_struct = 0

        next_line_level = next_struct + initial_indent + (1 if continuation else 0)
        return "\n".join(result), next_line_level

    @staticmethod
    def _indent(level: int, indent_size: int, insert_spaces: bool) -> str:
        """Build indentation prefix for one logical indent level."""
        if insert_spaces:
            return " " * (level * indent_size)
        return "\t" * level

    def _process_code_line(self, stripped: str, in_proc_header: bool) -> str:
        """Apply keyword normalisation and operator spacing to a single stripped line."""
        return _process_code_line_static(stripped, in_proc_header=in_proc_header)

    def _collapse_spaces(self, line: str) -> str:
        """Collapse multiple consecutive spaces in code segments only."""
        tokens = _tokenize(line)
        parts: list[str] = []
        for ttype, text in tokens:
            if ttype == "code":
                text = _squeeze_whitespace_runs(text)
            parts.append(text)
        return "".join(parts)

    @staticmethod
    def _normalize_blank_lines(text: str) -> str:
        """Reduce consecutive blank lines to at most one (matches DiagnosticEngine.MAX_BLANK_LINES)."""
        lines = text.splitlines()
        result: list[str] = []
        blank_count = 0
        for line in lines:
            if line.strip() == "":
                blank_count += 1
                if blank_count <= 1:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)
        return "\n".join(result)


# ---------------------------------------------------------------------------
# Singleton for use in LSP
# ---------------------------------------------------------------------------

default_formatter = BslFormatter()
