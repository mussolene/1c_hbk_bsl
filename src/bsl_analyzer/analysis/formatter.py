"""BSL source code formatter."""
from __future__ import annotations

import re
from typing import NamedTuple


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
    "или": "Или",
    "не": "Не",
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
        "иначеесли",
        "elsif",
        "иначе",
        "else",
        "исключение",
        "except",
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
    ]
)

# Preprocessor directives — kept as-is except case normalisation of the tag
_PREPROCESSOR_PATTERN = re.compile(
    r"^(\s*)(#(Область|КонецОбласти|Region|EndRegion))(.*)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Binary-operator spacing
# ---------------------------------------------------------------------------

# Comparison operators pattern (longer first to avoid <> being split into < >)
_CMP_OP_RE = re.compile(r"\s*(<>|<=|>=|<|>)\s*")
# Assignment / arithmetic operators handled separately
_ARITH_OP_RE = re.compile(r"(?<![<>])(\s*)([+\-*/%])(\s*)(?![=])")
_EQ_OP_RE = re.compile(r"(?<![!<>=:])(\s*)(=)(\s*)(?![>])")

# Canonical case for preprocessor words
_PP_CANONICAL: dict[str, str] = {
    "область": "#Область",
    "конецобласти": "#КонецОбласти",
    "region": "#Region",
    "endregion": "#EndRegion",
}


class _TextEdit(NamedTuple):
    start_line: int
    end_line: int
    new_text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _normalize_keywords_in_code(code: str) -> str:
    """Replace keywords in a pure code segment."""

    def replacer(m: re.Match) -> str:  # type: ignore[type-arg]
        word = m.group(0)
        return _KEYWORDS.get(word.lower(), word)

    return _KW_PATTERN.sub(replacer, code)


def _add_operator_spaces(code: str, in_proc_header: bool) -> str:
    """Add spaces around binary operators in a code segment."""
    # Comparison operators first (handles <>, <=, >= before < and >)
    result = _CMP_OP_RE.sub(lambda m: f" {m.group(1)} ", code)

    # Skip = spacing inside proc headers (default param values like А = 0)
    if not in_proc_header:
        result = _EQ_OP_RE.sub(lambda m: f" {m.group(2)} ", result)

    # Normalise multiple spaces to single
    result = re.sub(r"  +", " ", result)
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
    indent_after = (
        first_word in _INDENT_AFTER_STARTS
        or last_word in _INDENT_AFTER_ENDS
        or first_word in _SAME_LEVEL_OPENERS
    )

    return dedent_before, indent_after


# ---------------------------------------------------------------------------
# Main formatter class
# ---------------------------------------------------------------------------


class BslFormatter:
    """Formats BSL (1C:Enterprise) source code."""

    def format(self, content: str, indent_size: int = 4) -> str:  # noqa: A003
        """Format an entire BSL source file."""
        lines = content.splitlines()
        formatted = self._format_lines(lines, indent_size=indent_size)
        # Normalise trailing empty lines: max 2 consecutive blanks
        result = self._normalize_blank_lines(formatted)
        # Ensure single trailing newline
        result = result.rstrip("\n") + "\n"
        return result

    def format_range(
        self,
        content: str,
        start_line: int,
        end_line: int,
        indent_size: int = 4,
    ) -> str:
        """Format lines [start_line, end_line] (0-based, inclusive).

        Returns the formatted text for the requested range only
        (TextEdit-compatible: replace lines start_line..end_line with this text).
        """
        all_lines = content.splitlines()
        # Format the whole file to get correct indentation context
        formatted_all = self._format_lines(all_lines, indent_size=indent_size)
        formatted_lines = formatted_all.splitlines()
        # Clamp range
        s = max(0, start_line)
        e = min(len(formatted_lines) - 1, end_line)
        selected = formatted_lines[s : e + 1]
        return "\n".join(selected) + "\n"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _format_lines(self, lines: list[str], indent_size: int) -> str:
        """Core formatting pass: keyword normalisation, indentation, spacing."""
        output: list[str] = []
        current_indent = 0

        for raw_line in lines:
            # 1. Strip trailing whitespace
            line = raw_line.rstrip()

            # 2. Get stripped content
            stripped = _strip_indent(line)

            # 3. Skip blank lines (handled later by blank-line normalisation)
            if not stripped:
                output.append("")
                continue

            # 4. Check if line is a pure comment
            is_comment_line = stripped.startswith("//")

            # 5. Check preprocessor directive
            pp_match = _PREPROCESSOR_PATTERN.match(stripped)

            if is_comment_line:
                # Normalise indent only; keep comment text verbatim
                indented = " " * (current_indent * indent_size) + stripped
                output.append(indented)
                continue

            if pp_match:
                # Preprocessor — normalise tag case, keep rest
                tag = pp_match.group(2)
                rest = pp_match.group(4)
                canonical_tag = _PP_CANONICAL.get(tag.lstrip("#").lower(), tag)
                indented = " " * (current_indent * indent_size) + canonical_tag + rest
                output.append(indented)
                continue

            # 6. Normalise keywords and operator spacing (respecting string/comment tokens)
            processed = self._process_code_line(stripped, in_proc_header=_is_proc_or_func_header(stripped))

            # 7. Determine indent adjustments using the processed line
            proc_stripped = _strip_indent(processed)
            dedent_before, indent_after = _indent_control(proc_stripped)

            if dedent_before:
                current_indent = max(0, current_indent - 1)

            indented_line = " " * (current_indent * indent_size) + proc_stripped
            output.append(indented_line)

            if indent_after:
                current_indent += 1

        return "\n".join(output)

    def _process_code_line(self, stripped: str, in_proc_header: bool) -> str:
        """Apply keyword normalisation and operator spacing to a single stripped line."""
        tokens = _tokenize(stripped)
        result_parts: list[str] = []
        for ttype, text in tokens:
            if ttype == "code":
                text = _normalize_keywords_in_code(text)
                text = _add_operator_spaces(text, in_proc_header=in_proc_header)
            result_parts.append(text)
        # Re-join and clean up multiple spaces in code segments only
        result = "".join(result_parts)
        # Collapse any multi-space runs introduced in code (not inside strings/comments)
        result = self._collapse_spaces(result)
        return result.rstrip()

    def _collapse_spaces(self, line: str) -> str:
        """Collapse multiple consecutive spaces in code segments only."""
        tokens = _tokenize(line)
        parts: list[str] = []
        for ttype, text in tokens:
            if ttype == "code":
                text = re.sub(r"  +", " ", text)
            parts.append(text)
        return "".join(parts)

    @staticmethod
    def _normalize_blank_lines(text: str) -> str:
        """Reduce consecutive blank lines to at most 2."""
        lines = text.splitlines()
        result: list[str] = []
        blank_count = 0
        for line in lines:
            if line.strip() == "":
                blank_count += 1
                if blank_count <= 2:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)
        return "\n".join(result)


# ---------------------------------------------------------------------------
# Singleton for use in LSP
# ---------------------------------------------------------------------------

default_formatter = BslFormatter()
