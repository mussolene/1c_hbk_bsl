"""BSLLS-compatible BSL formatter.

The formatter is intentionally token-stream based, mirroring BSLLS
``FormatProvider``.  It does not use the parser/CST or the older line heuristic
formatter path.
"""

from __future__ import annotations

import re

from onec_hbk_bsl.analysis.formatter_tokens import FormatToken, format_tokens

_KEYWORDS: dict[str, str] = {
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
    "асинх": "Асинх",
    "знач": "Знач",
    "вызватьисключение": "ВызватьИсключение",
    "перейти": "Перейти",
    "добавитьобработчик": "ДобавитьОбработчик",
    "удалитьобработчик": "УдалитьОбработчик",
    "ждать": "Ждать",
    "и": "И",
    "или": "ИЛИ",
    "не": "НЕ",
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
    "and": "AND",
    "or": "OR",
    "not": "NOT",
    "async": "Async",
    "val": "Val",
    "raise": "Raise",
    "goto": "Goto",
    "addhandler": "AddHandler",
    "removehandler": "RemoveHandler",
    "await": "Await",
}

_DEDENT_BEFORE: frozenset[str] = frozenset(
    {
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
    }
)

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
_PREPROCESSOR_PATTERN = re.compile(
    r"^(\s*)(#[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z]*)(.*)",
    re.IGNORECASE | re.UNICODE,
)

_BSLLS_INCREMENT_TOKEN_TYPES = frozenset(
    {
        "(",
        "?(",
        "PROCEDURE_KEYWORD",
        "FUNCTION_KEYWORD",
        "IF_KEYWORD",
        "ELSIF_KEYWORD",
        "ELSE_KEYWORD",
        "FOR_KEYWORD",
        "WHILE_KEYWORD",
        "TRY_KEYWORD",
        "EXCEPT_KEYWORD",
    }
)
_BSLLS_DECREMENT_TOKEN_TYPES = frozenset(
    {
        ")",
        "ELSIF_KEYWORD",
        "ELSE_KEYWORD",
        "ENDPROCEDURE_KEYWORD",
        "ENDFUNCTION_KEYWORD",
        "ENDIF_KEYWORD",
        "ENDDO_KEYWORD",
        "EXCEPT_KEYWORD",
        "ENDTRY_KEYWORD",
    }
)
_BSLLS_KEYWORD_TOKEN_TYPES = frozenset(
    {
        "IF_KEYWORD",
        "THEN_KEYWORD",
        "ELSIF_KEYWORD",
        "ELSE_KEYWORD",
        "ENDIF_KEYWORD",
        "FOR_KEYWORD",
        "EACH_KEYWORD",
        "IN_KEYWORD",
        "TO_KEYWORD",
        "WHILE_KEYWORD",
        "DO_KEYWORD",
        "ENDDO_KEYWORD",
        "PROCEDURE_KEYWORD",
        "FUNCTION_KEYWORD",
        "ENDFUNCTION_KEYWORD",
        "ENDPROCEDURE_KEYWORD",
        "VAR_KEYWORD",
        "GOTO_KEYWORD",
        "RETURN_KEYWORD",
        "BREAK_KEYWORD",
        "CONTINUE_KEYWORD",
        "AND_KEYWORD",
        "OR_KEYWORD",
        "NOT_KEYWORD",
        "TRY_KEYWORD",
        "EXCEPT_KEYWORD",
        "RAISE_KEYWORD",
        "ENDTRY_KEYWORD",
        "NEW_KEYWORD",
        "ADDHANDLER_KEYWORD",
        "REMOVEHANDLER_KEYWORD",
        "ASYNC_KEYWORD",
        "AWAIT_KEYWORD",
        "VAL_KEYWORD",
        "EXECUTE_KEYWORD",
        "EXPORT_KEYWORD",
    }
)
_BSLLS_PRIMITIVE_TOKEN_TYPES = frozenset(
    {
        "NULL_KEYWORD",
        "DATETIME",
        "number",
        "TRUE_KEYWORD",
        "FALSE_KEYWORD",
        "UNDEFINED_KEYWORD",
        "FLOAT",
        "string",
        "string_content",
    }
)
_BSLLS_STRING_PART_TYPES = frozenset({'"', "string_content", "|"})


def _get_stripped_keyword(stripped: str) -> str:
    tokens = format_tokens(stripped)
    if not tokens:
        return ""
    token = tokens[0]
    if token.type == "PREPROCESSOR":
        return token.text.split(maxsplit=1)[0].lstrip("#").lower()
    return token.text.lower()


def _bslls_token_kind(token: FormatToken) -> str:
    if token.type in {"operator", "ERROR", "ANNOTATION_CUSTOM_SYMBOL"}:
        return token.text
    return token.type


def _canonical_token_text(token: FormatToken) -> str:
    if token.type == "LINE_COMMENT":
        return token.text.strip()
    if token.type == "PREPROCESSOR":
        stripped = token.text.strip()
        match = _PREPROCESSOR_PATTERN.match(stripped)
        if match is None:
            return stripped
        directive = _PP_CANONICAL.get(match.group(2)[1:].lower(), match.group(2))
        tail = match.group(3).strip()
        return f"{directive} {tail}" if tail else directive
    if token.type in _BSLLS_KEYWORD_TOKEN_TYPES or token.type == "operator":
        return _KEYWORDS.get(token.text.lower(), token.text)
    return token.text


def _bslls_is_unary(kind: str, previous_kind: str) -> bool:
    if kind != "-":
        return False
    return previous_kind in {
        "+",
        "-",
        "*",
        "/",
        "=",
        "%",
        "<",
        ">",
        "[",
        "(",
        "RETURN_KEYWORD",
        "<>",
        ",",
        "<=",
        ">=",
    }


def _bslls_need_add_space(
    token: FormatToken,
    previous: FormatToken | None,
    previous_is_unary: bool,
) -> bool:
    if previous is None or previous_is_unary:
        return False

    kind = _bslls_token_kind(token)
    previous_kind = _bslls_token_kind(previous)

    if token.type in _BSLLS_STRING_PART_TYPES and previous.type in _BSLLS_STRING_PART_TYPES:
        return False
    if previous_kind in {".", "#", "&", "~", "["}:
        return False
    if previous_kind in {"(", "?("}:
        return kind == ","
    if previous_kind in {",", ">=", "<=", "<>", "="}:
        return True

    if kind == "(":
        return (
            previous.type
            not in {
                "identifier",
                "property",
                "ANNOTATION_CUSTOM_SYMBOL",
                "EXECUTE_KEYWORD",
                "NEW_KEYWORD",
                "RAISE_KEYWORD",
            }
            and previous_kind != "?"
        )

    return kind not in {";", ".", ",", ")", "[", "]"}


def _format_bslls_token_stream(
    content: str,
    *,
    indent_size: int,
    insert_spaces: bool,
) -> str:
    tokens = format_tokens(content)
    if not tokens:
        return ""

    indentation = " " * indent_size if insert_spaces else "\t"
    first = tokens[0]
    current_indent_level = first.column // max(len(indentation), 1)
    additional_indent_level = -1
    in_method_definition = False
    inside_operator = False
    parameter_declaration_mode = False
    last_line = first.line
    previous: FormatToken | None = None
    previous_kind = ""
    previous_is_unary = False
    out: list[str] = []

    for token in tokens:
        kind = _bslls_token_kind(token)
        need_new_line = token.line != last_line

        if token.type in {"FUNCTION_KEYWORD", "PROCEDURE_KEYWORD"}:
            in_method_definition = True
        if in_method_definition and kind == ")":
            in_method_definition = False

        if token.type in {"IF_KEYWORD", "ELSIF_KEYWORD", "WHILE_KEYWORD", "FOR_KEYWORD"}:
            inside_operator = True
        if inside_operator and token.type in {"THEN_KEYWORD", "DO_KEYWORD"}:
            inside_operator = False

        if previous is not None and previous.type == "ANNOTATION_CUSTOM_SYMBOL" and kind == "(":
            parameter_declaration_mode = True

        if need_new_line:
            out.append(("\n" + indentation * current_indent_level) * (token.line - last_line - 1))

        if need_new_line and kind == "." and additional_indent_level < 0:
            current_indent_level += 1
            additional_indent_level = current_indent_level

        if kind in _BSLLS_DECREMENT_TOKEN_TYPES:
            current_indent_level -= 1
            if kind != ")" and current_indent_level == additional_indent_level:
                current_indent_level -= 1
                additional_indent_level = -1

        if token is first:
            out.append(indentation * current_indent_level)
        elif need_new_line:
            out.append("\n")
            out.append(indentation * current_indent_level)
        elif _bslls_need_add_space(token, previous, previous_is_unary):
            out.append(" ")

        out.append(_canonical_token_text(token))

        if kind in _BSLLS_INCREMENT_TOKEN_TYPES:
            current_indent_level += 1

        if (
            kind == "="
            and token.type == "="
            and additional_indent_level < 0
            and not in_method_definition
            and not inside_operator
        ):
            current_indent_level += 1
            additional_indent_level = current_indent_level

        if additional_indent_level > 0 and (
            kind == ";"
            or (parameter_declaration_mode and token.type in _BSLLS_PRIMITIVE_TOKEN_TYPES)
        ):
            current_indent_level -= 1
            additional_indent_level = -1

        if parameter_declaration_mode and kind == ")":
            parameter_declaration_mode = False

        last_line = token.line
        previous_is_unary = _bslls_is_unary(kind, previous_kind)
        previous_kind = kind
        previous = token

    return "".join(out).lstrip("\n").rstrip("\n")


class BslFormatter:
    """BSLLS-aligned BSL formatter."""

    @staticmethod
    def _default_insert_spaces(explicit: bool | None) -> bool:
        return False if explicit is None else explicit

    def format(  # noqa: A003
        self,
        content: str,
        indent_size: int = 4,
        insert_spaces: bool | None = None,
    ) -> str:
        insert_spaces = self._default_insert_spaces(insert_spaces)
        if content.startswith("\ufeff"):
            content = content[1:]
        return _format_bslls_token_stream(
            content,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
        )

    def format_range(
        self,
        content: str,
        start_line: int,
        end_line: int,
        indent_size: int = 4,
        insert_spaces: bool | None = None,
    ) -> str:
        """Format lines [start_line, end_line] using full-document BSLLS context."""
        if content.startswith("\ufeff"):
            content = content[1:]
        original_lines = content.splitlines()
        if not original_lines:
            return "\n"
        start = max(0, start_line)
        end = min(len(original_lines) - 1, end_line)
        if end < start:
            return ""
        formatted_lines = self.format(
            content,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
        ).splitlines()
        formatted_range = "\n".join(formatted_lines[start : end + 1])
        return formatted_range if formatted_range.endswith("\n") else formatted_range + "\n"

    def _indent_at(
        self,
        full_lines: list[str],
        target: int,
        indent_size: int,
        *,
        insert_spaces: bool = True,
        full_text: str,
    ) -> int:
        """Indent level for LSP on-type formatting, derived from token formatter output."""
        if target <= 0 or target > len(full_lines):
            return 0
        formatted_lines = self.format(
            full_text,
            indent_size=indent_size,
            insert_spaces=insert_spaces,
        ).splitlines()
        if target >= len(formatted_lines):
            return 0
        line = formatted_lines[target]
        prefix_len = len(line) - len(line.lstrip(" \t"))
        if insert_spaces:
            return prefix_len // max(indent_size, 1)
        return prefix_len


default_formatter = BslFormatter()
