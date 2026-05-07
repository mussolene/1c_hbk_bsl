"""Lightweight BSLLS-compatible token source for formatter.

The formatter mirrors BSLLS ``FormatProvider`` and therefore needs a lexer-like
token stream, not a CST leaf walk.  This scanner intentionally recognizes only
the token classes that affect BSLLS formatting: keywords, identifiers,
primitive literals, comments, preprocessor lines, punctuation, and operators.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatToken:
    type: str
    text: str
    line: int
    column: int


_KEYWORD_TYPES: dict[str, str] = {
    "процедура": "PROCEDURE_KEYWORD",
    "procedure": "PROCEDURE_KEYWORD",
    "конецпроцедуры": "ENDPROCEDURE_KEYWORD",
    "endprocedure": "ENDPROCEDURE_KEYWORD",
    "функция": "FUNCTION_KEYWORD",
    "function": "FUNCTION_KEYWORD",
    "конецфункции": "ENDFUNCTION_KEYWORD",
    "endfunction": "ENDFUNCTION_KEYWORD",
    "если": "IF_KEYWORD",
    "if": "IF_KEYWORD",
    "тогда": "THEN_KEYWORD",
    "then": "THEN_KEYWORD",
    "иначеесли": "ELSIF_KEYWORD",
    "elsif": "ELSIF_KEYWORD",
    "иначе": "ELSE_KEYWORD",
    "else": "ELSE_KEYWORD",
    "конецесли": "ENDIF_KEYWORD",
    "endif": "ENDIF_KEYWORD",
    "для": "FOR_KEYWORD",
    "for": "FOR_KEYWORD",
    "каждого": "EACH_KEYWORD",
    "each": "EACH_KEYWORD",
    "из": "IN_KEYWORD",
    "in": "IN_KEYWORD",
    "по": "TO_KEYWORD",
    "to": "TO_KEYWORD",
    "пока": "WHILE_KEYWORD",
    "while": "WHILE_KEYWORD",
    "цикл": "DO_KEYWORD",
    "do": "DO_KEYWORD",
    "конеццикла": "ENDDO_KEYWORD",
    "enddo": "ENDDO_KEYWORD",
    "попытка": "TRY_KEYWORD",
    "try": "TRY_KEYWORD",
    "исключение": "EXCEPT_KEYWORD",
    "except": "EXCEPT_KEYWORD",
    "конецпопытки": "ENDTRY_KEYWORD",
    "endtry": "ENDTRY_KEYWORD",
    "перем": "VAR_KEYWORD",
    "var": "VAR_KEYWORD",
    "перейти": "GOTO_KEYWORD",
    "goto": "GOTO_KEYWORD",
    "возврат": "RETURN_KEYWORD",
    "return": "RETURN_KEYWORD",
    "прервать": "BREAK_KEYWORD",
    "break": "BREAK_KEYWORD",
    "продолжить": "CONTINUE_KEYWORD",
    "continue": "CONTINUE_KEYWORD",
    "и": "AND_KEYWORD",
    "and": "AND_KEYWORD",
    "или": "OR_KEYWORD",
    "or": "OR_KEYWORD",
    "не": "NOT_KEYWORD",
    "not": "NOT_KEYWORD",
    "новый": "NEW_KEYWORD",
    "new": "NEW_KEYWORD",
    "выполнить": "EXECUTE_KEYWORD",
    "execute": "EXECUTE_KEYWORD",
    "вызватьисключение": "RAISE_KEYWORD",
    "raise": "RAISE_KEYWORD",
    "экспорт": "EXPORT_KEYWORD",
    "export": "EXPORT_KEYWORD",
    "добавитьобработчик": "ADDHANDLER_KEYWORD",
    "addhandler": "ADDHANDLER_KEYWORD",
    "удалитьобработчик": "REMOVEHANDLER_KEYWORD",
    "removehandler": "REMOVEHANDLER_KEYWORD",
    "асинх": "ASYNC_KEYWORD",
    "async": "ASYNC_KEYWORD",
    "ждать": "AWAIT_KEYWORD",
    "await": "AWAIT_KEYWORD",
    "знач": "VAL_KEYWORD",
    "val": "VAL_KEYWORD",
    "истина": "TRUE_KEYWORD",
    "true": "TRUE_KEYWORD",
    "ложь": "FALSE_KEYWORD",
    "false": "FALSE_KEYWORD",
    "неопределено": "UNDEFINED_KEYWORD",
    "undefined": "UNDEFINED_KEYWORD",
    "null": "NULL_KEYWORD",
}

_MULTI_CHAR_OPERATORS = ("<>", "<=", ">=")
_SINGLE_CHAR_TOKENS = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    ";": ";",
    ",": ",",
    ".": ".",
    "=": "=",
    "+": "operator",
    "-": "operator",
    "*": "operator",
    "/": "operator",
    "%": "operator",
    "<": "operator",
    ">": "operator",
    "&": "ANNOTATION_CUSTOM_SYMBOL",
    "~": "~",
    "#": "#",
}


def format_tokens(content: str) -> list[FormatToken]:
    tokens: list[FormatToken] = []
    in_multiline_string = False

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not in_multiline_string and stripped.startswith("#"):
            tokens.append(FormatToken("PREPROCESSOR", stripped, line_no, indent))
            continue
        if not in_multiline_string and stripped.startswith("//"):
            tokens.append(FormatToken("LINE_COMMENT", stripped, line_no, indent))
            continue

        pos = 0
        length = len(line)
        emitted_string_token_on_line = False
        while pos < length:
            char = line[pos]

            if not in_multiline_string and line.startswith("//", pos):
                tokens.append(FormatToken("LINE_COMMENT", line[pos:].strip(), line_no, pos))
                break

            if in_multiline_string:
                if char.isspace() and not emitted_string_token_on_line:
                    next_pos = pos + 1
                    while next_pos < length and line[next_pos].isspace():
                        next_pos += 1
                    if next_pos < length and line[next_pos] == "|":
                        pos += 1
                        continue
                if char == "|":
                    tokens.append(FormatToken("|", "|", line_no, pos))
                    pos += 1
                    emitted_string_token_on_line = True
                    continue
                if char == '"':
                    tokens.append(FormatToken('"', '"', line_no, pos))
                    pos += 1
                    in_multiline_string = False
                    emitted_string_token_on_line = True
                    continue
                start = pos
                while pos < length and line[pos] not in {'"', "|"}:
                    pos += 1
                if start < pos:
                    tokens.append(FormatToken("string_content", line[start:pos], line_no, start))
                    emitted_string_token_on_line = True
                continue

            if char.isspace():
                pos += 1
                continue

            if char == '"':
                pos = _scan_string(line, line_no, pos, tokens)
                if pos > length:
                    in_multiline_string = True
                    pos = length
                continue
            if char == "'":
                pos = _scan_datetime(line, line_no, pos, tokens)
                continue

            if line.startswith("?(", pos):
                tokens.append(FormatToken("?(", "?(", line_no, pos))
                pos += 2
                continue
            if char == "?":
                tokens.append(FormatToken("?", "?", line_no, pos))
                pos += 1
                continue

            op = _match_multi_char_operator(line, pos)
            if op is not None:
                tokens.append(FormatToken("operator", op, line_no, pos))
                pos += len(op)
                continue

            token_type = _SINGLE_CHAR_TOKENS.get(char)
            if token_type is not None:
                if char == "&":
                    annotation = _scan_annotation(line, line_no, pos)
                    if annotation is not None:
                        tokens.append(annotation)
                        pos += len(annotation.text)
                        continue
                tokens.append(FormatToken(token_type, char, line_no, pos))
                pos += 1
                continue

            if char.isdigit():
                start = pos
                pos += 1
                while pos < length:
                    if line[pos].isdigit():
                        pos += 1
                        continue
                    if line[pos] == "." and pos + 1 < length and line[pos + 1].isdigit():
                        pos += 1
                        continue
                    break
                tokens.append(FormatToken("number", line[start:pos], line_no, start))
                continue

            if _is_identifier_start(char):
                start = pos
                pos += 1
                while pos < length and _is_identifier_part(line[pos]):
                    pos += 1
                text = line[start:pos]
                tokens.append(FormatToken(_KEYWORD_TYPES.get(text.lower(), "identifier"), text, line_no, start))
                continue

            tokens.append(FormatToken("operator", char, line_no, pos))
            pos += 1

    return tokens


def _scan_string(line: str, line_no: int, start: int, tokens: list[FormatToken]) -> int:
    tokens.append(FormatToken('"', '"', line_no, start))
    pos = start + 1
    content_start = pos
    length = len(line)

    while pos < length:
        char = line[pos]
        if char == '"':
            if pos + 1 < length and line[pos + 1] == '"':
                pos += 2
                continue
            if content_start < pos:
                tokens.append(FormatToken("string_content", line[content_start:pos], line_no, content_start))
            tokens.append(FormatToken('"', '"', line_no, pos))
            return pos + 1
        pos += 1

    if content_start < length:
        tokens.append(FormatToken("string_content", line[content_start:length], line_no, content_start))
    return length + 1


def _scan_datetime(line: str, line_no: int, start: int, tokens: list[FormatToken]) -> int:
    pos = start + 1
    while pos < len(line) and line[pos] != "'":
        pos += 1
    if pos < len(line):
        pos += 1
    tokens.append(FormatToken("DATETIME", line[start:pos], line_no, start))
    return pos


def _scan_annotation(line: str, line_no: int, start: int) -> FormatToken | None:
    pos = start + 1
    if pos >= len(line) or not _is_identifier_start(line[pos]):
        return None
    pos += 1
    while pos < len(line) and _is_identifier_part(line[pos]):
        pos += 1
    return FormatToken("ANNOTATION_CUSTOM_SYMBOL", line[start:pos], line_no, start)


def _match_multi_char_operator(line: str, pos: int) -> str | None:
    for operator in _MULTI_CHAR_OPERATORS:
        if line.startswith(operator, pos):
            return operator
    return None


def _is_identifier_start(char: str) -> bool:
    return char == "_" or char.isalpha()


def _is_identifier_part(char: str) -> bool:
    return char == "_" or char.isalpha() or char.isdigit()
