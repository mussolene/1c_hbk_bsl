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

import functools
import re
from collections.abc import Callable

from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
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
    if re.fullmatch(r"/{4,}", stripped):
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


@functools.lru_cache(maxsize=16_384)
def _tokenize(line: str) -> tuple[tuple[str, str], ...]:
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
    return tuple(tokens)


@functools.lru_cache(maxsize=16_384)
def _code_fragment(line: str) -> str:
    """Code-only fragment for ``line`` (strings/comments removed)."""
    return "".join(text for token_type, text in _tokenize(line) if token_type == "code")  # noqa: S105


@functools.lru_cache(maxsize=16_384)
def _code_fragment_without_inline_comment(line: str) -> str:
    return _strip_inline_comment_from_code(_code_fragment(line))


# After comma, BSLLS FormatProvider inserts a space before the next token unless
# the next char is closing / semicolon (see needAddSpace in FormatProvider.java).
_COMMA_SPACE_AFTER = re.compile(r",(?=[^\s)\]\};])")


def _ensure_comma_space_in_code(code: str) -> str:
    """Insert single space after commas in a code-only fragment (strings already stripped)."""
    return _COMMA_SPACE_AFTER.sub(", ", code)


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
    code_part = _code_fragment(stripped).rstrip(";").rstrip()
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
    code_part = _code_fragment(stripped)
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
_EMPTY_FIRST_ARG_RE = re.compile(r"\(\s*,")


def _strip_inline_comment_from_code(code: str) -> str:
    """Remove // comment from a code fragment (not string-aware — same as line heuristics)."""
    if "//" in code:
        code = code.split("//", 1)[0]
    return code


def _line_ends_with_semicolon(stripped: str) -> bool:
    """True if the code part ends with ``;`` (after stripping // comment)."""
    code = _code_fragment_without_inline_comment(stripped).rstrip()
    return code.endswith(";")


def _line_has_unclosed_paren_expression(stripped: str) -> bool:
    """Code has unclosed ``(`` — next line continues the parenthesised expression."""
    code = _code_fragment_without_inline_comment(stripped).rstrip()
    if not code or code.endswith(";"):
        return False
    return _paren_delta_in_code(code) > 0


def _line_is_multiline_if_header(stripped: str) -> bool:
    """``Если``/``ИначеЕсли``/``If``/``ElsIf`` line without closing ``Тогда``/``Then``."""
    code = _code_fragment_without_inline_comment(stripped).strip()
    if not code:
        return False
    first = _get_stripped_keyword(code)
    if first not in ("если", "if", "иначеесли", "elsif"):
        return False
    lower = code.lower()
    return "тогда" not in lower and "then" not in lower


def _line_starts_with_dot(stripped: str) -> bool:
    """Leading `.` on a code line (method chain continuation)."""
    code = _code_fragment(stripped).lstrip()
    return code.startswith(".")


def _line_starts_question_call(stripped: str) -> bool:
    """True when code starts with ``?(`` (ternary call continuation)."""
    code = _code_fragment(stripped).lstrip()
    return code.startswith("?(")


def _line_starts_with_arith_operator(stripped: str) -> bool:
    """True when code starts with leading binary arithmetic operator."""
    code = _code_fragment(stripped).lstrip()
    return code.startswith(("+", "-", "*", "/"))


def _line_starts_condition_connector(stripped: str) -> bool:
    """True for logical continuation starters: И/ИЛИ/AND/OR."""
    first = _get_stripped_keyword(stripped)
    return first in ("и", "или", "and", "or")


def _line_is_string_literal_closer(stripped: str) -> bool:
    """True for standalone string-literal closure lines like `");` / `');`."""
    code = _code_fragment_without_inline_comment(stripped).strip()
    return code in ('");', "');")


def _line_opens_operator(stripped: str) -> bool:
    first = _get_stripped_keyword(stripped)
    return first in _OP_OPEN_FIRST


def _line_ends_operator(stripped: str) -> bool:
    return _get_last_keyword(stripped) in _INDENT_AFTER_ENDS


def _paren_delta_in_code(stripped: str) -> int:
    """Net ``(`` − ``)`` count in code tokens only."""
    delta = 0
    code = _code_fragment(stripped)
    for ch in code:
        if ch == "(":
            delta += 1
        elif ch == ")":
            delta -= 1
    return delta


def _line_has_assignment_without_semicolon(stripped: str) -> bool:
    """Assignment `=` on the line without a trailing ``;`` (code only)."""
    code = _code_fragment_without_inline_comment(stripped).rstrip()
    if code.endswith(";"):
        return False
    return bool(_ASSIGN_EQ_RE.search(code))


def _line_ends_with_plus(stripped: str) -> bool:
    """True if code fragment ends with ``+`` (after stripping // comment)."""
    code = _code_fragment_without_inline_comment(stripped).rstrip()
    return code.endswith("+")


def _strict_bslls_empty_first_arg_spacing(stripped: str) -> str:
    """Keep BSLLS spacing for empty first call arguments: ``( ,``."""
    tokens = _tokenize(stripped)
    result_parts: list[str] = []
    for ttype, text in tokens:
        if ttype == "code":
            text = _EMPTY_FIRST_ARG_RE.sub("( ,", text)
        result_parts.append(text)
    return "".join(result_parts)


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

    def _looks_like_statement_without_semicolon(line: str) -> bool:
        stripped_line = line.rstrip()
        if not stripped_line or stripped_line.endswith(";"):
            return False
        keyword = _get_stripped_keyword(stripped_line)
        if keyword in _DEDENT_BEFORE | _INDENT_AFTER_STARTS:
            return False
        if _get_last_keyword(stripped_line) in _INDENT_AFTER_ENDS:
            return False
        return True

    def _previous_significant_code_line(idx: int) -> str:
        j = idx - 1
        while j >= 0:
            candidate = lines[j].rstrip()
            stripped_candidate = _strip_indent(candidate)
            if not stripped_candidate or stripped_candidate.startswith("//"):
                j -= 1
                continue
            if _PREPROCESSOR_PATTERN.match(stripped_candidate):
                j -= 1
                continue
            return _process_code_line_static(
                stripped_candidate,
                in_proc_header=_is_proc_or_func_header(stripped_candidate),
            )
        return ""

    current_indent = 0
    pending_dedent_after = False
    out: list[int] = []
    for idx, raw_line in enumerate(lines):
        if pending_dedent_after:
            current_indent = max(0, current_indent - 1)
            pending_dedent_after = False
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
        first_keyword = _get_stripped_keyword(proc_stripped)
        dedent_before, indent_after = _indent_control(proc_stripped)
        if dedent_before and first_keyword in ("конеццикла", "enddo"):
            prev = _previous_significant_code_line(idx)
            if prev and _looks_like_statement_without_semicolon(prev):
                dedent_before = False
                pending_dedent_after = True
        if dedent_before:
            current_indent = max(0, current_indent - 1)
        out.append(current_indent)
        if indent_after:
            current_indent += 1
    return out


def _compute_structural_indent_levels(
    lines: list[str], text: str, tree: object | None = None
) -> list[int]:
    """Per-line base indent: CST (structural) + heuristic merge for special lines."""
    n = len(lines)
    if n == 0:
        return []
    heur = _heuristic_structural_indent_levels(lines)
    if tree is None:
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
            text = _ensure_comma_space_in_code(text)
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
    (
        re.compile(r"^(\s*)(Если\b.*\bТогда)\s+(.+)$", re.IGNORECASE | re.UNICODE),
        _tail_ok_after_then,
    ),
    (re.compile(r"^(\s*)(If\b.*\bThen)\s+(.+)$", re.IGNORECASE | re.UNICODE), _tail_ok_after_then),
    (
        re.compile(r"^(\s*)(ИначеЕсли\b.*\bТогда)\s+(.+)$", re.IGNORECASE | re.UNICODE),
        _tail_ok_after_then,
    ),
    (
        re.compile(r"^(\s*)(ElsIf\b.*\bThen)\s+(.+)$", re.IGNORECASE | re.UNICODE),
        _tail_ok_after_then,
    ),
    (
        re.compile(r"^(\s*)(Пока\b.*\bЦикл)\s+(.+)$", re.IGNORECASE | re.UNICODE),
        _tail_ok_after_loop,
    ),
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

    def __init__(self, *, profile: str = "compat") -> None:
        self.profile = profile
        self._cached_layout_text: str | None = None
        self._cached_layout_snapshot = None
        self._cached_layout_base_levels: list[int] | None = None

    @staticmethod
    def _default_insert_spaces(profile: str, explicit: bool | None) -> bool:
        """BSLLS ``format`` CLI uses tabs (insertSpaces=false); compat keeps spaces."""
        if explicit is not None:
            return explicit
        return profile != "strict-bslls"

    def format(  # noqa: A003
        self,
        content: str,
        indent_size: int = 4,
        insert_spaces: bool | None = None,
    ) -> str:
        """Format an entire BSL source file."""
        insert_spaces = self._default_insert_spaces(self.profile, insert_spaces)
        if content.startswith("\ufeff"):
            content = content[1:]
        lines = _expand_block_headers_one_line(content.splitlines())
        text = "\n".join(lines)
        snapshot = build_document_snapshot(path="<format>", content=text)
        if snapshot.tree_ok:
            normalized = normalize_argument_list_spacing(text, snapshot.root_node)
            if normalized != text:
                text = normalized
                lines = text.splitlines()
        formatted, _ = self._format_lines(
            lines,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
            text_for_parse=text,
            tree=snapshot.tree,
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
        insert_spaces: bool | None = None,
    ) -> str:
        """Format lines [start_line, end_line] (0-based, inclusive).

        Determines the correct indent level at start_line by scanning the
        preceding lines as context, then formats only the selected range.
        Unselected lines are never modified.

        Returns the formatted text for the range only
        (TextEdit-compatible: replace lines start_line..end_line with this text).
        """
        insert_spaces = self._default_insert_spaces(self.profile, insert_spaces)
        if content.startswith("\ufeff"):
            content = content[1:]
        all_lines = content.splitlines()
        s = max(0, start_line)
        e = min(len(all_lines) - 1, end_line)

        selected = all_lines[s : e + 1]
        snapshot, full_base = self._layout_context(
            path="<format-range>",
            content=content,
            lines=all_lines,
        )
        slice_base = full_base[s : e + 1] if full_base else []
        formatted, _ = self._format_lines(
            selected,
            indent_size=indent_size,
            initial_indent=0,
            insert_spaces=insert_spaces,
            text_for_parse=content,
            base_levels=slice_base,
            tree=snapshot.tree,
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
        # On-type indentation only depends on the prefix before target.
        # Parsing the entire document on cache miss is unnecessary CPU work.
        context_lines = full_lines[: target + 1] if target < len(full_lines) else full_lines
        context_text = "\n".join(context_lines)
        snapshot, base_levels = self._layout_context(
            path="<indent>",
            content=context_text,
            lines=context_lines,
        )
        next_struct = (
            base_levels[target]
            if target < len(base_levels)
            else (base_levels[-1] if base_levels else 0)
        )
        _, next_level = self._format_lines(
            context_lines[:target],
            indent_size=indent_size,
            initial_indent=0,
            output=False,
            insert_spaces=insert_spaces,
            text_for_parse=context_text,
            base_levels=base_levels[:target],
            next_line_structural=next_struct,
            tree=snapshot.tree,
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
        tree: object | None = None,
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
            base_levels = _compute_structural_indent_levels(lines, text, tree=tree)
        if len(base_levels) != len(lines):
            base_levels = _compute_structural_indent_levels(lines, text, tree=tree)

        comment_multiline = (
            _precompute_multiline_doc_comment_stripped(lines)
            if self.profile != "strict-bslls"
            else {}
        )

        result: list[str] = []
        continuation = False
        inside_operator = False
        in_method_sig = False
        balance = 0
        previous_code_line = ""
        previous_was_pipe = False
        pipe_block_extra: int | None = None

        for i, raw_line in enumerate(lines):
            line = raw_line.rstrip()
            stripped = _strip_indent(line)

            if not stripped:
                if output:
                    if self.profile == "strict-bslls":
                        lvl = base_levels[i] + initial_indent
                        result.append(self._indent(lvl, indent_size, insert_spaces))
                    else:
                        result.append("")
                continue

            # BSL multi-line string continuation: lines starting with | are string
            # content — preserve content verbatim, only re-apply structural indentation.
            if stripped.startswith("|"):
                if output:
                    # In strict-bslls profile, query/text pipe lines keep BSLLS-like
                    # continuation indentation, but avoid unconditional +2 shift for
                    # standalone pipe blocks.
                    if self.profile == "strict-bslls":
                        if previous_was_pipe and pipe_block_extra is not None:
                            extra = pipe_block_extra
                        else:
                            pipe_context = (
                                continuation
                                or in_method_sig
                                or _line_ends_with_plus(previous_code_line)
                            )
                            extra = 2 if pipe_context else 1
                            pipe_block_extra = extra
                        lvl = base_levels[i] + initial_indent + extra
                        result.append(self._indent(lvl, indent_size, insert_spaces) + stripped)
                    else:
                        extra = 1 if (continuation or in_method_sig) else 0
                        lvl = base_levels[i] + initial_indent + extra
                        result.append(self._indent(lvl, indent_size, insert_spaces) + stripped)
                # Update continuation: if the line ends the statement (closing "; or ") we
                # reset it; otherwise leave continuation unchanged so subsequent | lines are
                # indented correctly.
                raw_stripped = stripped.rstrip()
                if (
                    raw_stripped.endswith('";')
                    or raw_stripped.endswith("';")
                    or raw_stripped.endswith('");')
                    or raw_stripped.endswith("');")
                ):
                    continuation = False
                previous_was_pipe = True
                continue
            previous_was_pipe_line = previous_was_pipe
            previous_was_pipe = False
            pipe_block_extra = None

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
            if continuation and _line_is_string_literal_closer(proc_stripped):
                continuation = False
            if (
                self.profile == "strict-bslls"
                and previous_was_pipe_line
                and not _line_starts_condition_connector(proc_stripped)
                and not _line_starts_with_dot(proc_stripped)
                and not _line_starts_question_call(proc_stripped)
                and not _line_ends_with_plus(proc_stripped)
            ):
                # First code statement after a pipe block should not inherit stale
                # continuation indentation unless this line explicitly continues.
                continuation = False
            inside_op_for_assign = inside_operator or _line_opens_operator(proc_stripped)

            extra_level = 1 if (continuation or _line_starts_with_dot(proc_stripped)) else 0
            if inside_operator and _line_starts_condition_connector(proc_stripped):
                extra_level = max(extra_level, 1)
            if (
                self.profile == "strict-bslls"
                and not inside_operator
                and _line_starts_condition_connector(proc_stripped)
                and (
                    _line_has_unclosed_paren_expression(previous_code_line)
                    or _line_starts_condition_connector(previous_code_line)
                    or _line_is_multiline_if_header(previous_code_line)
                )
            ):
                extra_level = max(extra_level, 1)
            if (
                self.profile == "strict-bslls"
                and continuation
                and (
                    _line_starts_with_arith_operator(proc_stripped)
                    or _line_starts_with_arith_operator(previous_code_line)
                )
            ):
                extra_level = max(extra_level, 2)
            # Lines that continue a split Процедура/Функция parameter list (unclosed `(` from header).
            if in_method_sig:
                extra_level += 1
            base = base_levels[i] + initial_indent

            if output:
                out_level = base + extra_level
                result.append(self._indent(out_level, indent_size, insert_spaces) + proc_stripped)

            next_continuation = continuation
            if _line_ends_with_semicolon(proc_stripped):
                next_continuation = False
            elif _line_ends_operator(proc_stripped):
                # Multi-line logical conditions end at Тогда/Then/Цикл/Do.
                next_continuation = False
            elif (
                not in_method_sig
                and not inside_op_for_assign
                and _line_has_assignment_without_semicolon(proc_stripped)
                and not _is_proc_or_func_header(proc_stripped)
            ):
                next_continuation = True
            elif not in_method_sig and _line_is_multiline_if_header(proc_stripped):
                next_continuation = True
            elif (
                not in_method_sig
                and not _is_proc_or_func_header(proc_stripped)
                and _line_has_unclosed_paren_expression(proc_stripped)
            ):
                next_continuation = True
            elif _line_starts_with_dot(proc_stripped):
                next_continuation = True
            continuation = next_continuation

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
            previous_code_line = proc_stripped

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

    def _layout_context(
        self,
        *,
        path: str,
        content: str,
        lines: list[str],
    ) -> tuple[object, list[int]]:
        if self._cached_layout_text == content:
            snapshot = self._cached_layout_snapshot
            base_levels = self._cached_layout_base_levels
            if snapshot is not None and base_levels is not None:
                return snapshot, base_levels

        snapshot = build_document_snapshot(path=path, content=content)
        base_levels = _compute_structural_indent_levels(lines, content, tree=snapshot.tree)
        self._cached_layout_text = content
        self._cached_layout_snapshot = snapshot
        self._cached_layout_base_levels = base_levels
        return snapshot, base_levels

    @staticmethod
    def _indent(level: int, indent_size: int, insert_spaces: bool) -> str:
        """Build indentation prefix for one logical indent level."""
        if insert_spaces:
            return " " * (level * indent_size)
        return "\t" * level

    def _process_code_line(self, stripped: str, in_proc_header: bool) -> str:
        """Apply keyword normalisation and operator spacing to a single stripped line."""
        processed = _process_code_line_static(stripped, in_proc_header=in_proc_header)
        if self.profile == "strict-bslls":
            processed = _strict_bslls_empty_first_arg_spacing(processed)
        return processed

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

compat_formatter = BslFormatter(profile="compat")
strict_bslls_formatter = BslFormatter(profile="strict-bslls")
default_formatter = strict_bslls_formatter
