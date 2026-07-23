"""Shared parsed document snapshot for diagnostics, formatting, and indexing.

The project historically re-parsed the same document and re-walked the same
tree-sitter CST in several layers: diagnostics, formatter, symbol extraction,
call graph extraction, and LSP helpers. This module provides a single lazily
derived snapshot object so those layers can share one parsed view of a file.
"""

from __future__ import annotations

import re
import threading
from bisect import bisect_left
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.call_graph import Call
from onec_hbk_bsl.analysis.diagnostic.cst import iter_ts_nodes, tree_has_errors
from onec_hbk_bsl.analysis.diagnostic.helpers.proc_helpers import (
    is_typical_client_command_handler,
    proc_containing_line,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states,
    comma_missing_space_after_cols_in_line,
    comment_start_outside_double_quotes,
    mask_double_quoted_strings_preserve_len,
    span_is_inside_double_quoted_string,
    strip_inline_comment_preserve_strings,
)
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character
from onec_hbk_bsl.analysis.sdbl_cst import select_top_without_order
from onec_hbk_bsl.analysis.semantic import SemanticModel, extract_semantic_model
from onec_hbk_bsl.analysis.source_positions import line_start_offsets
from onec_hbk_bsl.analysis.symbols import Symbol

try:
    import tree_sitter_hbk as _ts_bsl
    from tree_sitter import Language as _TsLanguage
    from tree_sitter import Parser as _TsParser

    _SDBL_LANGUAGE = _TsLanguage(_ts_bsl.sdbl_language())
except Exception:  # pragma: no cover - optional parser dependency fallback
    _SDBL_LANGUAGE = None
    _TsParser = None  # type: ignore[assignment]
from onec_hbk_bsl.parser.bsl_parser import BslParser

_RE_REGION_OPEN = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_CLOSE = re.compile(
    r"^\s*#(?:КонецОбласти|EndRegion)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_QUERY_TEXT_START = re.compile(r'"\s*(?:ВЫБРАТЬ|SELECT)\b', re.IGNORECASE)
_RE_QUERY_INLINE_COMMENT = re.compile(r"\s*//.*$")
_CC_OPEN = re.compile(
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While|Исключение|Except)\b",
    re.IGNORECASE,
)
_CC_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)
_CC_ELSE = re.compile(
    r"^\s*(?:ИначеЕсли|ElsIf|Иначе|Else)\b",
    re.IGNORECASE,
)
_CC_INLINE_EXCEPT_CLOSE = re.compile(
    r"^\s*(?:Исключение|Except)\b.*\b(?:КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)
_RE_MCCABE_BRANCH = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf|Иначе|Else|Для|For|ДляКаждого|ForEach|Пока|While|Исключение|Except|Перейти|Goto)\b",
    re.IGNORECASE,
)
_RE_MCCABE_BOOL = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
_RE_MCCABE_TERNARY = re.compile(r"\?\s*\(")
_RE_MCCABE_CALL_PREFIX = re.compile(
    r"(?P<name>[A-Za-zА-Яа-яЁё_]\w*)\s*$",
    re.IGNORECASE | re.UNICODE,
)
_RE_COGNITIVE_BOOL_TOKEN = re.compile(
    r"\?\s*\(|\b(?:Не|Not|И|And|ИЛИ|Or)\b|[()]",
    re.IGNORECASE,
)
_RE_COGNITIVE_BOOL_START = re.compile(r"^\s*(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
_RE_COGNITIVE_OPEN_CONTROL_EXPR = re.compile(
    r"\b(?:Если|If|ИначеЕсли|ElsIf|Пока|While)\b",
    re.IGNORECASE,
)
_RE_COGNITIVE_EXPR_TERMINATOR = re.compile(
    r"(?:;|\b(?:Тогда|Then|Цикл|Do)\b)\s*$",
    re.IGNORECASE,
)
_RE_COGNITIVE_CONTROL_TERMINATOR = re.compile(r"\b(?:Тогда|Then|Цикл|Do)\b", re.IGNORECASE)
_RE_ASSIGNMENT_CONTINUATION = re.compile(r"[=+\-*/]\s*$")
_COMPLEXITY_LINE_MARKERS = (
    "если",
    "if",
    "иначе",
    "else",
    "elsif",
    "для",
    "for",
    "пока",
    "while",
    "исключение",
    "except",
    "перейти",
    "goto",
    "конец",
    "end",
    " и ",
    " или ",
    "and",
    "or",
    "не",
    "not",
    "?(",
    "? (",
)
_RE_LINE_COMMENT = re.compile(r"^\s*//")
_RE_MODAL_GLOBAL_METHOD = re.compile(
    r"(?<![.\w])"
    r"(?P<name>"
    r"Вопрос|DoQueryBox|ОткрытьФормуМодально|OpenFormModal|ОткрытьЗначение|OpenValue|"
    r"Предупреждение|DoMessageBox|Warning|ВвестиДату|InputDate|ВвестиЗначение|InputValue|"
    r"ВвестиСтроку|InputString|ВвестиЧисло|InputNumber|"
    r"УстановитьВнешнююКомпоненту|InstallAddIn|"
    r"УстановитьРасширениеРаботыСФайлами|InstallFileSystemExtension|"
    r"УстановитьРасширениеРаботыСКриптографией|InstallCryptoExtension|"
    r"ПоместитьФайл|PutFile"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL022_MODAL_GLOBAL_METHODS = frozenset(
    name.casefold()
    for name in (
        "Вопрос",
        "DoQueryBox",
        "ОткрытьФормуМодально",
        "OpenFormModal",
        "ОткрытьЗначение",
        "OpenValue",
        "Предупреждение",
        "DoMessageBox",
        "Warning",
        "ВвестиДату",
        "InputDate",
        "ВвестиЗначение",
        "InputValue",
        "ВвестиСтроку",
        "InputString",
        "ВвестиЧисло",
        "InputNumber",
        "УстановитьВнешнююКомпоненту",
        "InstallAddIn",
        "УстановитьРасширениеРаботыСФайлами",
        "InstallFileSystemExtension",
        "УстановитьРасширениеРаботыСКриптографией",
        "InstallCryptoExtension",
        "ПоместитьФайл",
        "PutFile",
    )
)
_RE_THIS_FORM = re.compile(
    r"\b(?:ЭтаФорма|ThisForm)\b",
    re.IGNORECASE,
)
_RE_BSL190_FORM_DATA = re.compile(
    r"\b(?P<name>ДанныеФормыВЗначение|FormDataToValue)\s*\(",
    re.IGNORECASE,
)
_RE_VAR_MODULE = re.compile(
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+?)\s*(?P<export>Экспорт|Export)?\s*;",
    re.IGNORECASE,
)
_RE_VAR_MODULE_HEAD = re.compile(r"^\s*(?:Перем|Var)\b(?P<tail>.*)$", re.IGNORECASE)
_RE_VAR_MODULE_CONT = re.compile(
    r"^\s*(?P<names>[\w\s,]+?)\s*(?P<export>Экспорт|Export)?\s*[;,]\s*$", re.IGNORECASE
)
_BSL204_ILLEGAL_CHARS = frozenset(
    {"\u00ad", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212", "\u00a0"}
)
_RE_COMPLEX_CONDITION_HEAD = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b",
    re.IGNORECASE,
)
_RE_COMPLEX_CONDITION_HEAD_PREFIX = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b\s*",
    re.IGNORECASE,
)
_RE_COMPLEX_CONDITION_THEN = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
_RE_COMPLEX_CONDITION_BOOL_OP = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
_RE_QUERY_WHERE = re.compile(
    r"\b(?:ГДЕ|WHERE)\b",
    re.IGNORECASE,
)
_RE_QUERY_TOP = re.compile(r"\b(?:ПЕРВЫЕ|TOP)\s+(\d+)\b", re.IGNORECASE)
_RE_QUERY_ORDER_BY = re.compile(r"\b(?:УПОРЯДОЧИТЬ|ORDER\s+BY)\b", re.IGNORECASE)
_RE_QUERY_UNION = re.compile(r"\b(?:ОБЪЕДИНИТЬ|UNION)\b", re.IGNORECASE)
_RE_CREDENTIAL_SEARCH_WORD = re.compile(r"^(?:пароль|password)$", re.IGNORECASE)
_CREDENTIAL_CONTAINER_TYPES = frozenset(
    {
        "структура",
        "structure",
        "соответствие",
        "map",
        "ftpсоединение",
        "ftpconnection",
        "httpсоединение",
        "httpconnection",
    }
)
_CREDENTIAL_CONNECTION_TYPES = frozenset(
    {
        "ftpсоединение",
        "ftpconnection",
        "httpсоединение",
        "httpconnection",
    }
)
_CREDENTIAL_INSERT_METHODS = frozenset({"вставить", "insert"})
_RE_CREDENTIAL_MASKED_VALUE = re.compile(r"^\*+$")
_RE_COMMENTED_CODE = re.compile(
    r"^\s*//\s*(?:"
    r"(?:(?:Процедура|Функция|Procedure|Function)\s+\w+\s*\([^)]*\)\s*(?:Экспорт|Export)?\s*$"
    r"|(?:Перем|Var)\s+\w+"
    r"|(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b)"
    r"|(?:ВЫБРАТЬ|SELECT)\b"
    r"|[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*\s*\([^)]*\)\s*(?:[+;*/-])"
    r"|[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*\s*="
    r")",
    re.IGNORECASE,
)
_RE_COMMENTED_QUERY_LINE = re.compile(r"^(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|ПОМЕСТИТЬ|INTO)\b")
_RE_COMMENTED_EXAMPLE_MARKER = re.compile(
    r"^(?:Пример|Example)\s*:",
    re.IGNORECASE | re.UNICODE,
)
_RE_COMMENTED_EMBEDDED_CALL = re.compile(
    r"\b[A-Za-zА-Яа-яЁё_]\w*\s*\(",
    re.UNICODE,
)
_RE_COMMENTED_EMBEDDED_COMPARISON = re.compile(r"(?:<>|<=|>=|=)", re.UNICODE)
_RE_COMMENTED_EMBEDDED_CASE_TEXT = re.compile(
    r"""^\s*"[^"]+"\s*-\s+в\s+случае\b""",
    re.IGNORECASE | re.UNICODE,
)
_RE_COMMENTED_EMBEDDED_BOOL_TEXT = re.compile(
    r"^\s*(?:и|или|and|or)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_COMMENTED_INLINE_ASSIGNMENT = re.compile(r"\b\w+\s*=\s*\w+\b", re.UNICODE)
_RE_REGION_EMPTY_CODE = re.compile(
    r"^\s*(?!//|#(?:Область|Region|КонецОбласти|EndRegion))\S",
    re.IGNORECASE,
)
_RE_BSL200_INCORRECT_START = re.compile(r"^\s*(\)|;|,\s*\S+|\);)", re.IGNORECASE)
_RE_BSL200_INCORRECT_END = re.compile(r"\s+(ИЛИ|И|OR|AND|\+|-|/|%|\*)\s*(?://.*)?$", re.IGNORECASE)
_RE_BSL216_SEMICOLON_NOSPACE = re.compile(r";(?=\S)")
_RE_BSL216_LEFT_RIGHT_KEYWORDS = re.compile(r"\b(По|To|Из|In|Или|Or|И|And)\b", re.IGNORECASE)
_RE_BSL216_LEFT_KEYWORDS = re.compile(r"\b(Экспорт|Export|Тогда|Then|Цикл|Do)\b", re.IGNORECASE)
_RE_BSL216_RIGHT_KEYWORDS = re.compile(
    r"\b(Если|If|ИначеЕсли|ElsIf|ElseIf|Пока|While|Для|For|Не|Not|Каждого|Each)\b",
    re.IGNORECASE,
)
_RE_BSL216_ANY_KEYWORD = re.compile(
    r"\b(?:"
    r"По|To|Из|In|Или|Or|И|And|"
    r"Экспорт|Export|Тогда|Then|Цикл|Do|"
    r"Если|If|ИначеЕсли|ElsIf|ElseIf|Пока|While|Для|For|Не|Not|Каждого|Each"
    r")\b",
    re.IGNORECASE,
)
_COMPARISON_OPS = ("<=", ">=", "<>", "=", "<", ">")
_RE_BSL216_COMPARISON_OP = re.compile(r"<=|>=|<>|(?<![<>!])=(?!=)|<|>")
_BINARY_LHS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "0123456789_)]\"|'"
)
_STANDARD_REGIONS_BY_KIND: dict[str, frozenset[str]] = {
    "manager": frozenset(
        {
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "обработчикисобытий",
            "инициализация",
            "public",
            "internal",
            "private",
            "eventhandlers",
            "initialize",
        }
    ),
    "object": frozenset(
        {
            "описаниепеременных",
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "обработчикисобытий",
            "инициализация",
            "variables",
            "public",
            "internal",
            "private",
            "eventhandlers",
            "initialize",
        }
    ),
    "form": frozenset(
        {
            "описаниепеременных",
            "обработчикисобытийформы",
            "обработчикисобытийэлементовшапкиформы",
            "обработчикикомандформы",
            "инициализация",
            "служебныепроцедурыифункции",
            "variables",
            "formeventhandlers",
            "formheaderitemseventhandlers",
            "formcommandseventhandlers",
            "initialize",
            "private",
        }
    ),
    "form-table-prefix": frozenset(
        {
            "обработчикисобытийэлементовтаблицыформы",
            "formtableitemseventhandlers",
        }
    ),
    "common": frozenset(
        {
            "программныйинтерфейс",
            "служебныйпрограммныйинтерфейс",
            "служебныепроцедурыифункции",
            "public",
            "internal",
            "private",
        }
    ),
    "application": frozenset(
        {
            "описаниепеременных",
            "программныйинтерфейс",
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "variables",
            "public",
            "eventhandlers",
            "private",
        }
    ),
    "service": frozenset(
        {
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "eventhandlers",
            "private",
        }
    ),
    "external-connection": frozenset(
        {
            "программныйинтерфейс",
            "обработчикисобытий",
            "служебныепроцедурыифункции",
            "public",
            "eventhandlers",
            "private",
        }
    ),
}
_DUPLICATE_REGION_ALIASES = {
    "программныйинтерфейс": "public",
    "публичный": "public",
    "public": "public",
    "служебныйпрограммныйинтерфейс": "internal",
    "служебный": "internal",
    "internal": "internal",
    "служебныепроцедурыифункции": "private",
    "приватный": "private",
    "private": "private",
    "обработчикисобытий": "eventhandlers",
    "eventhandlers": "eventhandlers",
    "обработчикисобытийформы": "formeventhandlers",
    "formeventhandlers": "formeventhandlers",
    "обработчикисобытийэлементовшапкиформы": "formheaderitemseventhandlers",
    "formheaderitemseventhandlers": "formheaderitemseventhandlers",
    "обработчикикомандформы": "formcommandseventhandlers",
    "formcommandseventhandlers": "formcommandseventhandlers",
    "описаниепеременных": "variables",
    "variables": "variables",
    "инициализация": "initialize",
    "initialize": "initialize",
}
_MCCABE_GROUPING_KEYWORDS = frozenset(
    {
        "если",
        "if",
        "иначеесли",
        "elsif",
        "пока",
        "while",
        "не",
        "not",
        "и",
        "and",
        "или",
        "or",
        "возврат",
        "return",
    }
)


def _query_content_end_quote(content: str) -> int | None:
    pos = 0
    while pos < len(content):
        if content[pos] != '"':
            pos += 1
            continue
        if pos + 1 < len(content) and content[pos + 1] == '"':
            pos += 2
            continue
        return pos
    return None


def _is_mccabe_grouping_paren(text: str, index: int) -> bool:
    prefix = text[:index]
    if not prefix.strip():
        return True
    previous = prefix.rstrip()
    previous_char = previous[-1]
    if previous_char == "?":
        return False
    match = _RE_MCCABE_CALL_PREFIX.search(previous)
    if match is None:
        return True
    return match.group("name").casefold() in _MCCABE_GROUPING_KEYWORDS


def _count_mccabe_bool_ops(text: str, paren_depth: int = 0) -> tuple[int, int]:
    paren_stack = [True] * max(0, paren_depth)
    if _RE_MCCABE_BOOL.search(text) is None:
        if "(" not in text and ")" not in text:
            return 0, paren_depth
        for i, ch in enumerate(text):
            if ch == "(":
                paren_stack.append(_is_mccabe_grouping_paren(text, i))
            elif ch == ")" and paren_stack:
                paren_stack.pop()
        return 0, sum(1 for item in paren_stack if item)
    count = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            paren_stack.append(_is_mccabe_grouping_paren(text, i))
            i += 1
            continue
        if ch == ")":
            if paren_stack:
                paren_stack.pop()
            i += 1
            continue
        match = _RE_MCCABE_BOOL.match(text, i)
        if match:
            count += 1 + sum(1 for item in paren_stack if item)
            i = match.end()
            continue
        i += 1
    return count, sum(1 for item in paren_stack if item)


def _count_cognitive_ternary_ops(
    text: str,
    control_nesting: int,
    paren_stack: list[bool],
) -> int:
    score = 0
    i = 0
    while i < len(text):
        if text[i] == "?":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] != "(":
                i += 1
                continue
            ternary_depth = sum(1 for item in paren_stack if item)
            score += 1 + control_nesting + ternary_depth
            paren_stack.append(True)
            i = j + 1
            continue
        if text[i] == "(":
            paren_stack.append(False)
        elif text[i] == ")" and paren_stack:
            paren_stack.pop()
        i += 1
    return score


def _count_cognitive_bool_ops(text: str, last_op: str | None = None) -> tuple[int, str | None]:
    count = 0
    current = last_op
    reset_on_close: list[bool] = []
    pending_not = False
    bool_seen_on_line = False
    for match in _RE_COGNITIVE_BOOL_TOKEN.finditer(text):
        lexeme = match.group(0)
        folded = lexeme.casefold()
        if lexeme.startswith("?"):
            if not bool_seen_on_line:
                current = None
            pending_not = False
            continue
        if lexeme == "(":
            is_not_grouping = pending_not and _is_mccabe_grouping_paren(text, match.start())
            if is_not_grouping:
                current = None
            reset_on_close.append(is_not_grouping)
            pending_not = False
            continue
        if lexeme == ")":
            if reset_on_close and reset_on_close.pop():
                current = None
            pending_not = False
            continue
        if folded in {"не", "not"}:
            pending_not = True
            continue
        pending_not = False
        op = "and" if folded in {"and", "и"} else "or"
        if op != current:
            count += 1
            current = op
        bool_seen_on_line = True
    return count, current


@lru_cache(maxsize=4096)
def _self_call_re(proc_name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![.\w]){re.escape(proc_name)}\s*\(", re.IGNORECASE)


def _line_has_self_call(line: str, proc_name: str | None) -> bool:
    if not proc_name:
        return False
    return bool(_self_call_re(proc_name).search(line))


def _arithmetic_missing_space_cols_in_line(line: str, in_str_at_start: bool = False) -> list[int]:
    stripped = line
    in_s = in_str_at_start
    for ci, ch in enumerate(line):
        if ch == '"':
            in_s = not in_s
        elif ch == "/" and not in_s and ci + 1 < len(line) and line[ci + 1] == "/":
            stripped = line[:ci]
            break

    cols: list[int] = []
    in_s = in_str_at_start
    in_sq = False
    prev_non_space = ""
    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]
        if ch == '"' and not in_sq:
            in_s = not in_s
            prev_non_space = '"'
            i += 1
            continue
        if ch == "'" and not in_s:
            in_sq = not in_sq
            prev_non_space = "'"
            i += 1
            continue
        if in_s or in_sq:
            i += 1
            continue
        if ch in " \t":
            i += 1
            continue

        if ch in "+-*/%":
            if ch in "+-" and re.search(r"\b(?:Возврат|Return)\s*$", stripped[:i], re.IGNORECASE):
                prev_non_space = ch
                i += 1
                continue
            if ch in "+-" and prev_non_space not in _BINARY_LHS:
                prev_non_space = ch
                i += 1
                continue
            prev_ch = stripped[i - 1] if i > 0 else ""
            space_before = prev_ch in " \t"
            next_ch = stripped[i + 1] if i + 1 < n else ""
            space_after = next_ch in " \t"
            if not space_before or not space_after:
                cols.append(i)
            prev_non_space = ch
            i += 1
            continue

        prev_non_space = ch
        i += 1

    return cols


def _comment_looks_like_embedded_code(text: str) -> bool:
    if not text:
        return False
    if _RE_COMMENTED_EMBEDDED_CALL.search(text) is None:
        return False
    if _RE_COMMENTED_EMBEDDED_COMPARISON.search(text) is None:
        return False
    return (
        _RE_COMMENTED_EMBEDDED_CASE_TEXT.search(text) is not None
        or _RE_COMMENTED_EMBEDDED_BOOL_TEXT.search(text) is not None
    )


def _uncomment_line_text(text: str) -> str:
    result = text.strip()
    while result.startswith("//"):
        result = result[2:].strip()
    return result


def _bsl_text_parses_without_errors(text: str, parser: BslParser) -> bool:
    tree = parser.parse_content(text)
    root = getattr(tree, "root_node", None)
    return bool(
        root is not None
        and not getattr(root, "has_error", True)
        and not parser.extract_errors(tree)
    )


def _comment_lines_node_types(texts: list[str], parser: BslParser) -> set[str]:
    uncommented = "\n".join(_uncomment_line_text(text) for text in texts).strip()
    if not uncommented:
        return set()
    tree = parser.parse_content(uncommented)
    root = getattr(tree, "root_node", None)
    if root is None:
        return set()
    return {getattr(node, "type", "") for node in _ts_walk(root)}


def _comment_lines_parse_as_bsl(texts: list[str], parser: BslParser) -> bool:
    uncommented_lines = [_uncomment_line_text(text) for text in texts]
    uncommented = "\n".join(uncommented_lines).strip()
    if not uncommented:
        return False
    return _bsl_text_parses_without_errors(uncommented, parser)


def _double_quoted_span_containing(line: str, pos: int) -> tuple[int, int] | None:
    idx = 0
    while idx < len(line):
        if line[idx] != '"':
            idx += 1
            continue
        start = idx
        idx += 1
        while idx < len(line):
            if line[idx] == '"':
                if idx + 1 < len(line) and line[idx + 1] == '"':
                    idx += 2
                    continue
                end = idx + 1
                if start <= pos < end:
                    return start, end
                idx = end
                break
            idx += 1
        else:
            if start <= pos < len(line):
                return start, len(line.rstrip())
    return None


def _has_preceding_variable_description(lines: list[str], var_line_idx: int) -> bool:
    prev_idx = var_line_idx - 1
    while prev_idx >= 0 and lines[prev_idx].strip().startswith("&"):
        prev_idx -= 1
    if prev_idx < 0:
        return False
    stripped = lines[prev_idx].strip()
    if stripped.startswith("///"):
        return len(stripped) > 3
    if stripped.startswith("//"):
        return len(stripped[2:].strip()) > 0
    return False


def _has_inline_variable_description(line: str) -> bool:
    comment_pos = line.find("//")
    if comment_pos < 0:
        return False
    return len(line[comment_pos + 2 :].strip()) > 0


def _has_previous_inline_variable_description(lines: list[str], var_line_idx: int) -> bool:
    prev_idx = var_line_idx - 1
    while prev_idx >= 0:
        stripped = lines[prev_idx].strip()
        if stripped.startswith("&"):
            prev_idx -= 1
            continue
        if not stripped:
            return False
        if _RE_VAR_MODULE.match(stripped):
            return _has_inline_variable_description(lines[prev_idx])
        return False
    return False


def _module_var_name_ranges(match: re.Match[str]) -> list[tuple[int, int]]:
    names = match.group("names")
    base = match.start("names")
    ranges = [(base + item.start(), base + item.end()) for item in re.finditer(r"\w+", names)]
    if ranges and match.group("export"):
        start, _end = ranges[-1]
        ranges[-1] = (start, match.end("export"))
    return ranges


def _module_var_multiline_name_ranges(
    lines: list[str],
    start_idx: int,
) -> tuple[int, list[LineDiagnosticFact]] | None:
    """Extract names from a multiline module variable declaration."""
    head = _RE_VAR_MODULE_HEAD.match(lines[start_idx])
    if head is None or ";" in head.group("tail"):
        return None

    facts: list[LineDiagnosticFact] = []
    idx = start_idx + 1
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("&"):
            idx += 1
            continue
        match = _RE_VAR_MODULE_CONT.match(line)
        if match is None:
            return None
        facts.extend(
            LineDiagnosticFact(
                line_idx=idx,
                character=start,
                end_character=end,
            )
            for start, end in _module_var_name_ranges(match)
        )
        if ";" in line:
            return idx, facts
        idx += 1
    return None


def _standard_regions_for_path(path: str) -> frozenset[str]:
    low = path.replace("\\", "/").lower()
    if "/forms/" in low and low.endswith("/form/module.bsl"):
        return _STANDARD_REGIONS_BY_KIND["form"]
    if low.endswith("/ext/managermodule.bsl") or low.endswith("managermodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["manager"]
    if low.endswith("/ext/objectmodule.bsl") or low.endswith("objectmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["object"]
    if low.endswith("/ext/recordsetmodule.bsl") or low.endswith("recordsetmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["object"]
    if "/commonmodules/" in low:
        return _STANDARD_REGIONS_BY_KIND["common"]
    if low.endswith("applicationmodule.bsl") or low.endswith("managedapplicationmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["application"]
    if low.endswith("ordinaryapplicationmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["application"]
    if low.endswith("commandmodule.bsl") or low.endswith("sessionmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["service"]
    if low.endswith("httpservicemodule.bsl") or low.endswith("webservicemodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["service"]
    if low.endswith("externalconnectionmodule.bsl"):
        return _STANDARD_REGIONS_BY_KIND["external-connection"]
    return frozenset()


def _path_is_likely_form_module_bsl(path: str) -> bool:
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    if p.suffix.lower() != ".bsl":
        return False
    normalized = p.as_posix().lower()
    if p.name.lower() != "module.bsl":
        return False
    return "/forms/" in normalized and (
        normalized.endswith("/ext/module.bsl") or normalized.endswith("/ext/form/module.bsl")
    )


def _is_standard_region_name_for_path(path: str, region_name: str) -> bool:
    name = region_name.strip().lower()
    allowed = _standard_regions_for_path(path)
    if not allowed:
        return True
    if name in allowed:
        return True
    table_prefixes = _STANDARD_REGIONS_BY_KIND["form-table-prefix"]
    return any(name.startswith(prefix) for prefix in table_prefixes)


def _normalize_duplicate_region_name(name: str) -> str:
    raw = re.sub(r"\s+", "", name).casefold()
    return _DUPLICATE_REGION_ALIASES.get(raw, raw)


def _region_directive_name_range(line: str) -> tuple[int, int]:
    start = len(line) - len(line.lstrip())
    if start < len(line) and line[start] == "#":
        start += 1
    return start, len(line.rstrip())


def _module_level_regions(regions: list[RegionInfo]) -> list[RegionInfo]:
    return [
        region
        for region in regions
        if not any(
            other is not region
            and other.start_idx < region.start_idx
            and region.end_idx <= other.end_idx
            for other in regions
        )
    ]


def _calc_complexity_metrics_from_lines(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    *,
    masked_lines: list[str],
    proc_name: str | None = None,
) -> tuple[int, int]:
    cognitive = 0
    nesting = 0
    bool_last_op: str | None = None
    bool_expr_open = False
    ternary_paren_stack: list[bool] = []
    mccabe = 1
    paren_depth = 0
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line.lstrip().startswith("|"):
            bool_last_op = None
            bool_expr_open = False
            ternary_paren_stack.clear()
            paren_depth = 0
            continue
        line_no_strings = masked_lines[i]
        folded_line = line_no_strings.casefold()
        if (
            not bool_expr_open
            and not ternary_paren_stack
            and paren_depth == 0
            and not any(marker in folded_line for marker in _COMPLEXITY_LINE_MARKERS)
            and not (proc_name and proc_name.casefold() in folded_line)
        ):
            continue

        starts_with_bool = bool(_RE_COGNITIVE_BOOL_START.match(line_no_strings))
        line_bool_count, bool_last_op = _count_cognitive_bool_ops(
            line_no_strings,
            bool_last_op if (bool_expr_open or starts_with_bool) else None,
        )
        cognitive += line_bool_count
        line_has_bool = line_bool_count > 0 or _RE_MCCABE_BOOL.search(line_no_strings) is not None
        opens_control_expr = bool(
            _RE_COGNITIVE_OPEN_CONTROL_EXPR.search(line_no_strings)
            and not _RE_COGNITIVE_CONTROL_TERMINATOR.search(line_no_strings)
        )
        line_terminates_expr = bool(_RE_COGNITIVE_EXPR_TERMINATOR.search(line_no_strings))
        bool_expr_open = (
            opens_control_expr
            or bool(_RE_ASSIGNMENT_CONTINUATION.search(line_no_strings))
            or (line_has_bool and not line_terminates_expr)
            or bool((bool_expr_open or starts_with_bool) and not line_terminates_expr)
        )
        if not bool_expr_open:
            bool_last_op = None
        ternary_count = len(_RE_MCCABE_TERNARY.findall(line_no_strings))
        cognitive += _count_cognitive_ternary_ops(
            line_no_strings,
            nesting,
            ternary_paren_stack,
        )
        has_self_call = _line_has_self_call(line_no_strings, proc_name)
        if has_self_call:
            cognitive += 1
        if _CC_OPEN.match(line):
            cognitive += 1 + nesting
            nesting += 1
            if _CC_INLINE_EXCEPT_CLOSE.match(line_no_strings):
                nesting = max(0, nesting - 1)
        elif _CC_CLOSE.match(line):
            nesting = max(0, nesting - 1)
        elif _CC_ELSE.match(line):
            cognitive += 1

        if _RE_MCCABE_BRANCH.match(line_no_strings):
            mccabe += 1
        bool_count, paren_depth = _count_mccabe_bool_ops(line_no_strings, paren_depth)
        mccabe += bool_count
        mccabe += ternary_count
        if has_self_call:
            mccabe += 1
    return cognitive, mccabe


@dataclass(frozen=True)
class ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    params: list[str]
    val_params: list[str]
    optional_count: int
    header_col: int = 0
    optional_params: frozenset[str] = frozenset()
    params_start_idx: int | None = None
    params_start_character: int | None = None
    params_end_idx: int | None = None
    params_end_character: int | None = None
    param_ranges: tuple[tuple[str, int, int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class LineDiagnosticFact:
    """Zero-based same-line diagnostic fact derived from a document snapshot."""

    line_idx: int
    character: int
    end_character: int
    end_line_idx: int | None = None


@dataclass(frozen=True)
class RegionInfo:
    """#Область / #Region block in the source."""

    name: str
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class QueryTextLineInfo:
    """One logical content line inside an embedded query string block."""

    line_no: int
    content_base: int
    content: str
    head: str
    ended_query: bool


QueryContentLineTuple = tuple[int, int, str, str, bool]


@dataclass(frozen=True)
class QueryTextBlockInfo:
    """Embedded query string block with pre-split logical lines."""

    start_idx: int
    block_lines: tuple[str, ...]
    content_lines: tuple[QueryTextLineInfo, ...]
    sdbl_tree: Any | None = None
    sdbl_has_errors: bool = False
    content_line_tuples: tuple[QueryContentLineTuple, ...] = ()

    @property
    def query_text(self) -> str:
        return "\n".join(line.head for line in self.content_lines)

    @property
    def head_text(self) -> str:
        return "\n".join(line.head for line in self.content_lines)

    def original_lsp_position(self, row: int, utf8_col: int) -> tuple[int, int]:
        if row < 0 or row >= len(self.content_lines):
            return self.start_idx, 0
        line = self.content_lines[row]
        character = line.content_base + utf8_byte_offset_to_lsp_character(line.head, utf8_col)
        return line.line_no - 1, character


def _parse_sdbl_query_text(query_text: str) -> tuple[Any | None, bool]:
    if _SDBL_LANGUAGE is None or _TsParser is None or not query_text.strip():
        return None, False
    parser = _TsParser(_SDBL_LANGUAGE)
    tree = parser.parse(query_text.encode("utf-8"))
    root = getattr(tree, "root_node", None)
    return tree, bool(root is not None and tree_has_errors(root))


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _iter_ts_children(node: Any):
    child_count = getattr(node, "child_count", None)
    child_at = getattr(node, "child", None)
    if isinstance(child_count, int) and callable(child_at):
        for index in range(child_count):
            child = child_at(index)
            if child is not None:
                yield child
        return
    yield from getattr(node, "children", []) or []


def _ts_walk(node: Any):
    yield from iter_ts_nodes(node)


def _ts_child_of_type(node: Any, child_type: str) -> Any | None:
    for child in _iter_ts_children(node):
        if getattr(child, "type", None) == child_type:
            return child
    return None


def _ts_children(node: Any) -> list[Any]:
    return list(getattr(node, "children", []) or [])


def _credential_clear_string(text: str) -> str:
    return text.replace('"', "").replace(" ", "")


def _credential_key_matches(text: str) -> bool:
    return bool(_RE_CREDENTIAL_SEARCH_WORD.fullmatch(_credential_clear_string(text)))


def _credential_string_value(text: str) -> str | None:
    stripped = text.strip()
    if len(stripped) <= 2 or not (stripped.startswith('"') and stripped.endswith('"')):
        return None
    value = stripped[1:-1]
    if not value or _RE_CREDENTIAL_MASKED_VALUE.fullmatch(value):
        return None
    return value


def _credential_single_string_expression(expression: Any | None) -> Any | None:
    if expression is None:
        return None
    node = expression
    if getattr(node, "type", None) == "expression":
        node = _ts_child_of_type(node, "const_expression")
    if getattr(node, "type", None) == "const_expression":
        node = _ts_child_of_type(node, "string")
    if getattr(node, "type", None) != "string":
        return None
    if _ts_node_text(expression).strip() != _ts_node_text(node):
        return None
    return node if _credential_string_value(_ts_node_text(node)) else None


def _credential_argument_expressions(arguments_node: Any | None) -> list[Any | None]:
    if arguments_node is None:
        return []
    params: list[Any | None] = []
    current: Any | None = None
    for child in _ts_children(arguments_node):
        child_type = getattr(child, "type", None)
        if child_type in {"(", ")", "line_comment", "comment"}:
            continue
        if child_type == ",":
            params.append(current)
            current = None
            continue
        if child_type == "omitted_argument":
            params.append(current)
            current = None
            continue
        if child_type == "expression":
            current = child
    params.append(current)
    return params


def _credential_assignment_parts(assignment: Any) -> tuple[Any | None, Any | None]:
    left: Any | None = None
    value: Any | None = None
    for child in _ts_children(assignment):
        child_type = getattr(child, "type", None)
        if child_type in {"=", ";", "line_comment", "comment"}:
            continue
        if child_type == "expression":
            value = child
            continue
        if left is None:
            left = child
    return left, value


def _credential_property_key(access_node: Any) -> str | None:
    text = _ts_node_text(access_node)
    if "[" in text and "]" in text:
        strings = [
            node for node in _ts_walk(access_node) if getattr(node, "type", None) == "string"
        ]
        return _ts_node_text(strings[-1]) if strings else None
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return None


def _credential_first_identifier(node: Any) -> Any | None:
    for child in _ts_children(node):
        if getattr(child, "type", None) == "identifier":
            return child
    return None


def _credential_ancestor_of_type(node: Any, node_types: set[str]) -> Any | None:
    current = node
    while current is not None:
        if getattr(current, "type", None) in node_types:
            return current
        current = getattr(current, "parent", None)
    return None


def _credential_fact_for_node(node: Any, lines: list[str]) -> LineDiagnosticFact:
    start_line, start_char = _ts_point_to_line_lsp_character(lines, node.start_point)
    end_line, end_char = _ts_point_to_line_lsp_character(lines, node.end_point)
    return LineDiagnosticFact(
        line_idx=start_line,
        character=start_char,
        end_line_idx=end_line,
        end_character=end_char,
    )


def _ts_point_to_lsp_character(container_node: Any, point: Any) -> int:
    node_text = _ts_node_text(container_node)
    row = point[0]
    local_row = row - container_node.start_point[0]
    lines = node_text.splitlines()
    if local_row < 0 or local_row >= len(lines):
        return point[1]
    return utf8_byte_offset_to_lsp_character(lines[local_row], point[1])


def _ts_point_to_line_lsp_character(lines: list[str], point: Any) -> tuple[int, int]:
    row = point[0]
    if row < 0 or row >= len(lines):
        return row, point[1]
    return row, utf8_byte_offset_to_lsp_character(lines[row], point[1])


def _call_end_character(line: str, open_paren_idx: int) -> int:
    depth = 0
    in_string = False
    idx = open_paren_idx
    while idx < len(line):
        ch = line[idx]
        if ch == '"':
            if in_string and idx + 1 < len(line) and line[idx + 1] == '"':
                idx += 2
                continue
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return idx + 1
        idx += 1
    return len(line.rstrip())


def _bsl022_modal_facts_from_nodes(
    method_calls: list[Any],
    lines: list[str],
    procedures: list[ProcInfo],
) -> list[LineDiagnosticFact]:
    facts: list[LineDiagnosticFact] = []
    for node in method_calls:
        if getattr(getattr(node, "parent", None), "type", None) == "call_expression":
            continue
        ident = _ts_child_of_type(node, "identifier")
        if ident is None:
            continue
        method_name = _ts_node_text(ident)
        if method_name.casefold() not in _BSL022_MODAL_GLOBAL_METHODS:
            continue
        line_idx, character = _ts_point_to_line_lsp_character(lines, node.start_point)
        end_line_idx, end_character = _ts_point_to_line_lsp_character(lines, node.end_point)
        proc = proc_containing_line(procedures, line_idx)
        if proc is not None and is_typical_client_command_handler(proc, lines):
            continue
        facts.append(
            LineDiagnosticFact(
                line_idx=line_idx,
                character=character,
                end_line_idx=end_line_idx,
                end_character=end_character,
            )
        )
    return facts


def _bsl022_modal_facts_from_lines(
    lines: list[str],
    procedures: list[ProcInfo],
) -> list[LineDiagnosticFact]:
    facts: list[LineDiagnosticFact] = []
    for idx, line in enumerate(lines):
        if line.strip().startswith("//"):
            continue
        code_line = strip_inline_comment_preserve_strings(line)
        code_line = mask_double_quoted_strings_preserve_len(code_line)
        match = _RE_MODAL_GLOBAL_METHOD.search(code_line)
        if match is None:
            continue
        proc = proc_containing_line(procedures, idx)
        if proc is not None and is_typical_client_command_handler(proc, lines):
            continue
        facts.append(
            LineDiagnosticFact(
                line_idx=idx,
                character=match.start("name"),
                end_character=_call_end_character(line, match.end() - 1),
            )
        )
    return facts


def _ts_node_to_proc_info(node: Any) -> ProcInfo | None:
    name = ""
    params: list[str] = []
    val_params: list[str] = []
    optional_count = 0
    is_export = False
    optional_params_list: list[str] = []
    param_ranges_list: list[tuple[str, int, int, int, int]] = []
    params_start_idx: int | None = None
    params_start_character: int | None = None
    params_end_idx: int | None = None
    params_end_character: int | None = None

    for child in getattr(node, "children", []) or []:
        child_type = getattr(child, "type", None)
        if child_type == "identifier" and not name:
            name = _ts_node_text(child)
        elif child_type == "EXPORT_KEYWORD":
            is_export = True
        elif child_type == "parameters":
            open_node = None
            close_node = None
            parameter_nodes: list[Any] = []
            for param_child in getattr(child, "children", []) or []:
                param_child_type = getattr(param_child, "type", None)
                if param_child_type == "(":
                    open_node = param_child
                elif param_child_type == ")":
                    close_node = param_child
                elif param_child_type == "parameter":
                    parameter_nodes.append(param_child)
            if open_node is not None and close_node is not None:
                if parameter_nodes:
                    first_param = parameter_nodes[0]
                    last_param = parameter_nodes[-1]
                    params_start_idx = first_param.start_point[0]
                    params_start_character = _ts_point_to_lsp_character(
                        node, first_param.start_point
                    )
                    params_end_idx = last_param.end_point[0]
                    params_end_character = _ts_point_to_lsp_character(node, last_param.end_point)
                else:
                    params_start_idx = open_node.end_point[0]
                    params_start_character = _ts_point_to_lsp_character(node, open_node.end_point)
                    params_end_idx = close_node.start_point[0]
                    params_end_character = _ts_point_to_lsp_character(node, close_node.start_point)
            for param in parameter_nodes:
                param_name = ""
                param_identifier = None
                is_val = False
                has_default = False
                for param_child in getattr(param, "children", []) or []:
                    param_child_type = getattr(param_child, "type", None)
                    if param_child_type == "VAL_KEYWORD":
                        is_val = True
                    elif param_child_type == "identifier" and not param_name:
                        param_name = _ts_node_text(param_child)
                        param_identifier = param_child
                    elif param_child_type == "=":
                        has_default = True
                if param_name:
                    params.append(param_name)
                    if param_identifier is not None:
                        param_ranges_list.append(
                            (
                                param_name,
                                param_identifier.start_point[0],
                                _ts_point_to_lsp_character(node, param_identifier.start_point),
                                param_identifier.end_point[0],
                                _ts_point_to_lsp_character(node, param_identifier.end_point),
                            )
                        )
                    if is_val:
                        val_params.append(param_name)
                    if has_default:
                        optional_count += 1
                        optional_params_list.append(param_name)

    if not name:
        return None

    kind = "function" if getattr(node, "type", None) == "function_definition" else "procedure"
    return ProcInfo(
        name=name,
        kind=kind,
        start_idx=node.start_point[0],
        end_idx=node.end_point[0],
        is_export=is_export,
        params=params,
        val_params=val_params,
        optional_count=optional_count,
        header_col=node.start_point[1],
        optional_params=frozenset(optional_params_list),
        params_start_idx=params_start_idx,
        params_start_character=params_start_character,
        params_end_idx=params_end_idx,
        params_end_character=params_end_character,
        param_ranges=tuple(param_ranges_list),
    )


def _collect_procs_from_node(node: Any, result: list[ProcInfo]) -> None:
    if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
        proc = _ts_node_to_proc_info(node)
        if proc:
            result.append(proc)
        return
    for child in _iter_ts_children(node):
        _collect_procs_from_node(child, result)


def _collect_proc_names_from_node(node: Any, result: set[str]) -> None:
    node_type = getattr(node, "type", None)
    if node_type in ("procedure_definition", "function_definition"):
        for child in _iter_ts_children(node):
            if getattr(child, "type", None) == "identifier":
                name = _ts_node_text(child)
                if name:
                    result.add(name.casefold())
                break
        return
    for child in _iter_ts_children(node):
        _collect_proc_names_from_node(child, result)


def _find_procedures_from_tree(tree: Any) -> list[ProcInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []
    result: list[ProcInfo] = []
    _collect_procs_from_node(root, result)
    return result


def find_procedure_names_from_tree(tree: Any) -> frozenset[str]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return frozenset()
    result: set[str] = set()
    _collect_proc_names_from_node(root, result)
    return frozenset(result)


def find_exported_procedure_names_from_tree(tree: Any) -> frozenset[str]:
    return frozenset(
        proc.name.casefold() for proc in _find_procedures_from_tree(tree) if proc.is_export
    )


def find_procedure_names_in_content(content: str) -> frozenset[str]:
    tree = BslParser().parse_content(content)
    return find_procedure_names_from_tree(tree)


def find_exported_procedure_names_in_content(content: str) -> frozenset[str]:
    tree = BslParser().parse_content(content)
    return find_exported_procedure_names_from_tree(tree)


def _line_break_positions(content: str) -> list[int]:
    breaks: list[int] = []
    start = content.find("\n")
    while start != -1:
        breaks.append(start)
        start = content.find("\n", start + 1)
    return breaks


def _point_row_column(point: Any) -> tuple[int, int]:
    row = getattr(point, "row", None)
    column = getattr(point, "column", None)
    if row is not None and column is not None:
        return int(row), int(column)
    return int(point[0]), int(point[1])


def _char_offset_for_ts_point(
    lines: list[str],
    line_starts: list[int],
    point: Any,
) -> int:
    row, byte_col = _point_row_column(point)
    if row < 0:
        return 0
    if row >= len(lines):
        return line_starts[-1] + len(lines[-1]) if lines else 0
    line = lines[row]
    raw = line.encode("utf-8")
    if byte_col >= len(raw):
        char_col = len(line)
    else:
        char_col = len(raw[: max(0, byte_col)].decode("utf-8", errors="replace"))
    return line_starts[row] + char_col


def _line_index_for_offset(line_breaks: list[int], offset: int) -> int:
    return bisect_left(line_breaks, offset)


def _find_regions(content: str) -> list[RegionInfo]:
    line_breaks = _line_break_positions(content)
    opens_iter = iter(_RE_REGION_OPEN.finditer(content))
    closes_iter = iter(_RE_REGION_CLOSE.finditer(content))
    next_open = next(opens_iter, None)
    next_close = next(closes_iter, None)
    stack: list[tuple[str, int]] = []
    result: list[RegionInfo] = []

    while next_open is not None or next_close is not None:
        open_pos = next_open.start() if next_open is not None else None
        close_pos = next_close.start() if next_close is not None else None
        use_open = close_pos is None or (open_pos is not None and open_pos <= close_pos)

        if use_open and next_open is not None:
            stack.append(
                (
                    next_open.group("name"),
                    _line_index_for_offset(line_breaks, next_open.start()),
                )
            )
            next_open = next(opens_iter, None)
            continue

        if next_close is not None:
            end_idx = _line_index_for_offset(line_breaks, next_close.start())
            if stack:
                name, start_idx = stack.pop()
                result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
            next_close = next(closes_iter, None)

    # Unclosed regions are retained with a short synthetic span to preserve fallback behavior.
    for name, start_idx in stack:
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=start_idx + 1))

    result.sort(key=lambda region: region.start_idx)
    return result


def _find_regions_from_tree(tree: Any) -> list[RegionInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), bytes):
        return []

    opens: list[tuple[int, str]] = []
    closes: list[int] = []
    result: list[RegionInfo] = []

    def inspect_preprocessor(node: Any) -> bool:
        if getattr(node, "type", None) == "preprocessor":
            child_types: set[str | None] = set()
            region_name = ""
            seen_region_keyword = False
            for child in _iter_ts_children(node):
                child_type = getattr(child, "type", None)
                child_types.add(child_type)
                if child_type == "PREPROC_REGION_KEYWORD":
                    seen_region_keyword = True
                elif seen_region_keyword and child_type == "identifier" and not region_name:
                    region_name = _ts_node_text(child)
            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0

            if "PREPROC_REGION_KEYWORD" in child_types:
                if "PREPROC_ENDREGION_KEYWORD" in child_types:
                    end_idx = (
                        node.end_point[0] if getattr(node, "end_point", None) else start_idx + 1
                    )
                    result.append(
                        RegionInfo(name=region_name, start_idx=start_idx, end_idx=end_idx)
                    )
                    return True
                opens.append((start_idx, region_name))
                return False

            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(start_idx)
                return False

        return True

    walk = getattr(root, "walk", None)
    if callable(walk):
        cursor = walk()
        done = False
        while not done:
            descend = inspect_preprocessor(cursor.node)
            if descend and cursor.goto_first_child():
                continue
            while True:
                if cursor.goto_next_sibling():
                    break
                if not cursor.goto_parent():
                    done = True
                    break
    else:

        def visit(node: Any) -> None:
            if not inspect_preprocessor(node):
                return
            for child in _iter_ts_children(node):
                visit(child)

        visit(root)

    events = [(idx, "open", name) for idx, name in opens]
    events.extend((idx, "close", "") for idx in closes)
    events.sort(key=lambda item: (item[0], 0 if item[1] == "open" else 1))
    stack: list[tuple[str, int]] = []
    for idx, kind, name in events:
        if kind == "open":
            stack.append((name, idx))
        elif stack:
            open_name, start_idx = stack.pop()
            result.append(RegionInfo(name=open_name, start_idx=start_idx, end_idx=idx))
    for name, start_idx in stack:
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=start_idx + 1))
    result.sort(key=lambda region: region.start_idx)
    return result


def _build_proc_node_map(tree: Any) -> dict[tuple[str, int, str], Any]:
    result: dict[tuple[str, int, str], Any] = {}
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return result

    def collect(node: Any) -> None:
        if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
            info = _ts_node_to_proc_info(node)
            if info:
                result[(info.name, info.start_idx, info.kind)] = node
            return
        for child in getattr(node, "children", []) or []:
            collect(child)

    collect(root)
    return result


def _build_query_text_blocks(lines: list[str]) -> list[QueryTextBlockInfo]:
    result: list[QueryTextBlockInfo] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.lstrip()
        if stripped_line.startswith("//"):
            i += 1
            continue
        starts_query = bool(_RE_QUERY_TEXT_START.search(line))
        if not starts_query and '"' in line:
            j_probe = i + 1
            while j_probe < len(lines) and (
                not lines[j_probe].strip()
                or lines[j_probe].lstrip().startswith("|")
                or lines[j_probe].lstrip().startswith("//")
            ):
                if re.match(r"^\s*\|\s*(?:ВЫБРАТЬ|SELECT)\b", lines[j_probe], re.IGNORECASE):
                    starts_query = True
                    break
                j_probe += 1
        if not starts_query:
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        while j < len(lines) and (
            lines[j].lstrip().startswith("|")
            or lines[j].lstrip().startswith("//")
            or not lines[j].strip()
        ):
            block_lines.append(lines[j])
            j += 1

        content_lines: list[QueryTextLineInfo] = []
        for offset, raw_line in enumerate(block_lines):
            stripped = raw_line.rstrip()
            if not stripped:
                continue

            if offset == 0:
                quote_pos = raw_line.find('"')
                if quote_pos < 0:
                    continue
                after_quote = raw_line[quote_pos + 1 :]
                leading_ws = len(after_quote) - len(after_quote.lstrip())
                content_base = quote_pos + 1 + leading_ws
                raw_content = after_quote.lstrip()
            else:
                pipe_pos = raw_line.find("|")
                if pipe_pos < 0:
                    continue
                after_pipe = raw_line[pipe_pos + 1 :]
                leading_ws = len(after_pipe) - len(after_pipe.lstrip())
                content_base = pipe_pos + 1 + leading_ws
                raw_content = after_pipe.lstrip()

            content = _RE_QUERY_INLINE_COMMENT.sub("", raw_content).rstrip()
            if not content:
                continue

            end_quote = _query_content_end_quote(content)
            ended_query = end_quote is not None
            head = content[:end_quote].rstrip() if ended_query else content
            if not head:
                if ended_query:
                    break
                continue

            content_lines.append(
                QueryTextLineInfo(
                    line_no=i + offset + 1,
                    content_base=content_base,
                    content=content,
                    head=head,
                    ended_query=ended_query,
                )
            )
            if ended_query:
                break

        content_lines_tuple = tuple(content_lines)
        content_line_tuples = tuple(
            (
                line.line_no,
                line.content_base,
                line.content,
                line.head,
                line.ended_query,
            )
            for line in content_lines_tuple
        )
        sdbl_text = "\n".join(line.head for line in content_lines_tuple)
        sdbl_tree, sdbl_has_errors = _parse_sdbl_query_text(sdbl_text)
        result.append(
            QueryTextBlockInfo(
                start_idx=i,
                block_lines=tuple(block_lines),
                content_lines=content_lines_tuple,
                sdbl_tree=sdbl_tree,
                sdbl_has_errors=sdbl_has_errors,
                content_line_tuples=content_line_tuples,
            )
        )
        i = j
    return result


@dataclass(slots=True)
class DocumentSnapshot:
    """One parsed view of a BSL document with lazily derived analysis data."""

    path: str
    content: str
    tree: Any

    _lines: list[str] | None = None
    _procs: list[ProcInfo] | None = None
    _regions: list[RegionInfo] | None = None
    _proc_node_map: dict[tuple[str, int, str], Any] | None = None
    _symbols: list[Symbol] | None = None
    _calls: list[Call] | None = None
    _semantic_model: SemanticModel | None = None
    _query_blocks: list[QueryTextBlockInfo] | None = None
    _query_line_indices: frozenset[int] | None = None
    _query_content_line_tuples: tuple[QueryContentLineTuple, ...] | None = None
    _string_literal_ranges: tuple[tuple[int, int], ...] | None = None
    _line_string_states: list[bool] | None = None
    _comment_starts: list[int | None] | None = None
    _masked_lines: list[str] | None = None
    _code_lines_wo_comments: list[str] | None = None
    _counter_lines: list[str] | None = None
    _line_lengths: list[int] | None = None
    _reported_line_lengths: list[int] | None = None
    _blank_line_flags: list[bool] | None = None
    _has_parse_errors: bool | None = None
    _ts_node_groups: dict[str, list[Any]] | None = None
    _complexity_metrics_cache: dict[tuple[tuple[int, int], ...], list[tuple[int, int]]] | None = (
        None
    )
    _module_body_cognitive_facts_cache: dict[int, list[LineDiagnosticFact]] | None = None
    _missing_space_facts: list[LineDiagnosticFact] | None = None
    _incorrect_line_break_facts: list[LineDiagnosticFact] | None = None
    _hardcoded_credential_facts: list[LineDiagnosticFact] | None = None
    _commented_code_facts: list[LineDiagnosticFact] | None = None
    _non_standard_region_facts: list[LineDiagnosticFact] | None = None
    _empty_region_facts: list[LineDiagnosticFact] | None = None
    _duplicate_region_facts: list[LineDiagnosticFact] | None = None
    _deprecated_warning_facts: list[LineDiagnosticFact] | None = None
    _command_or_form_export_facts: list[LineDiagnosticFact] | None = None
    _this_form_usage_facts: list[LineDiagnosticFact] | None = None
    _form_data_to_value_facts: list[LineDiagnosticFact] | None = None
    _invalid_character_facts: list[LineDiagnosticFact] | None = None
    _module_variable_description_facts: list[LineDiagnosticFact] | None = None
    _complex_condition_facts_cache: dict[int, list[LineDiagnosticFact]] | None = None
    _select_top_without_order_facts: list[LineDiagnosticFact] | None = None
    _line_too_long_facts_cache: dict[int, list[LineDiagnosticFact]] | None = None
    _runtime_call_context_cache: Any | None = None
    _global_method_calls_cache: Any | None = None
    _ternary_spans_cache: Any | None = None
    _semantic_fact_snapshots: dict[Any, Any] | None = None
    _semantic_fact_build_count: int = 0
    _cache_lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def root_node(self) -> Any | None:
        return getattr(self.tree, "root_node", None)

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            self._lines = self.content.splitlines()
        return self._lines

    @property
    def is_tree_sitter(self) -> bool:
        root = self.root_node
        return root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))

    @property
    def has_parse_errors(self) -> bool:
        if self._has_parse_errors is None:
            root = self.root_node
            if root is None or not self.is_tree_sitter:
                self._has_parse_errors = True
            else:
                self._has_parse_errors = tree_has_errors(root)
        return self._has_parse_errors

    @property
    def tree_ok(self) -> bool:
        return self.is_tree_sitter and not self.has_parse_errors

    @property
    def procedures(self) -> list[ProcInfo]:
        if self._procs is None:
            self._procs = _find_procedures_from_tree(self.tree) if self.is_tree_sitter else []
        return self._procs

    @property
    def regions(self) -> list[RegionInfo]:
        if self._regions is None:
            self._regions = _find_regions_from_tree(self.tree) if self.is_tree_sitter else []
        return self._regions

    @property
    def proc_node_map(self) -> dict[tuple[str, int, str], Any]:
        if self._proc_node_map is None:
            self._proc_node_map = _build_proc_node_map(self.tree)
        return self._proc_node_map

    @property
    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            self._symbols = self.semantic_model.symbols
        return self._symbols

    @property
    def calls(self) -> list[Call]:
        if self._calls is None:
            self._calls = self.semantic_model.calls
        return self._calls

    @property
    def semantic_model(self) -> SemanticModel:
        if self._semantic_model is None:
            self._semantic_model = extract_semantic_model(self.tree, file_path=self.path)
        return self._semantic_model

    @property
    def query_text_blocks(self) -> list[QueryTextBlockInfo]:
        if self._query_blocks is None:
            self._query_blocks = _build_query_text_blocks(self.lines)
        return self._query_blocks

    @property
    def query_line_indices(self) -> frozenset[int]:
        """Zero-based source line indices that belong to embedded query text."""
        if self._query_line_indices is None:
            self._query_line_indices = frozenset(
                line.line_no - 1 for block in self.query_text_blocks for line in block.content_lines
            )
        return self._query_line_indices

    @property
    def query_content_line_tuples(self) -> tuple[QueryContentLineTuple, ...]:
        """Flat cached query content lines as ``(line_no, base, content, head, ended)``."""
        if self._query_content_line_tuples is None:
            self._query_content_line_tuples = tuple(
                item for block in self.query_text_blocks for item in block.content_line_tuples
            )
        return self._query_content_line_tuples

    @property
    def line_string_states(self) -> list[bool]:
        if self._line_string_states is None:
            self._line_string_states = build_line_string_states(self.lines)
        return self._line_string_states

    @property
    def comment_starts(self) -> list[int | None]:
        if self._comment_starts is None:
            states = self.line_string_states
            self._comment_starts = [
                comment_start_outside_double_quotes(line, states[idx])
                for idx, line in enumerate(self.lines)
            ]
        return self._comment_starts

    @property
    def masked_lines(self) -> list[str]:
        if self._masked_lines is None:
            states = self.line_string_states
            self._masked_lines = [
                line if states[idx] else mask_double_quoted_strings_preserve_len(line)
                for idx, line in enumerate(self.lines)
            ]
        return self._masked_lines

    @property
    def code_lines_without_comments(self) -> list[str]:
        if self._code_lines_wo_comments is None:
            self._code_lines_wo_comments = [
                strip_inline_comment_preserve_strings(line) for line in self.lines
            ]
        return self._code_lines_wo_comments

    @property
    def counter_lines(self) -> list[str]:
        """Lines with comments and double-quoted strings masked for metric counters."""
        if self._counter_lines is None:
            states = self.line_string_states
            code_lines = self.code_lines_without_comments
            self._counter_lines = [
                line if states[idx] else mask_double_quoted_strings_preserve_len(line)
                for idx, line in enumerate(code_lines)
            ]
        return self._counter_lines

    @property
    def line_lengths(self) -> list[int]:
        if self._line_lengths is None:
            self._line_lengths = [len(line) for line in self.lines]
        return self._line_lengths

    @property
    def reported_line_lengths(self) -> list[int]:
        """Return significant row ends used by BSL014.

        BSL014 is a readability rule: trailing spaces and tabs after the last
        visible source character do not make the row harder to read.
        """
        if self._reported_line_lengths is not None:
            return self._reported_line_lengths

        self._reported_line_lengths = [len(line.rstrip(" \t")) for line in self.lines]
        return self._reported_line_lengths

    @property
    def blank_line_flags(self) -> list[bool]:
        if self._blank_line_flags is None:
            self._blank_line_flags = [line.strip() == "" for line in self.lines]
        return self._blank_line_flags

    @property
    def string_literal_ranges(self) -> tuple[tuple[int, int], ...]:
        """Absolute character ranges of CST ``string`` nodes."""
        if self._string_literal_ranges is None:
            if not self.is_tree_sitter:
                self._string_literal_ranges = ()
            else:
                line_starts = line_start_offsets(self.content)
                ranges: list[tuple[int, int]] = []
                for node in self.ts_nodes_for_types({"string"}, walker=_ts_walk)["string"]:
                    start = _char_offset_for_ts_point(self.lines, line_starts, node.start_point)
                    end = _char_offset_for_ts_point(self.lines, line_starts, node.end_point)
                    if end > start:
                        ranges.append((start, end))
                self._string_literal_ranges = tuple(ranges)
        return self._string_literal_ranges

    def ts_nodes_for_types(
        self,
        node_types: set[str],
        *,
        hot_node_types: Iterable[str] = (),
        walker: Callable[[Any], Iterable[Any]],
    ) -> dict[str, list[Any]]:
        """Return CST nodes grouped by type, materialised once per snapshot."""
        root = self.root_node
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return {node_type: [] for node_type in node_types}
        with self._cache_lock:
            if self._ts_node_groups is None:
                collected_types = set(node_types) | set(hot_node_types)
                grouped = {node_type: [] for node_type in collected_types}
                for node in walker(root):
                    node_type = getattr(node, "type", None)
                    if node_type in grouped:
                        grouped[node_type].append(node)
                self._ts_node_groups = grouped
            else:
                missing = (set(node_types) | set(hot_node_types)) - set(self._ts_node_groups)
                if missing:
                    for node_type in missing:
                        self._ts_node_groups[node_type] = []
                    for node in walker(root):
                        node_type = getattr(node, "type", None)
                        if node_type in missing:
                            self._ts_node_groups[node_type].append(node)
            return {node_type: self._ts_node_groups.get(node_type, []) for node_type in node_types}

    def complexity_metrics_for_procs(
        self,
        procs: list[ProcInfo],
    ) -> list[tuple[int, int]]:
        """Return cached ``(cognitive, mccabe)`` metrics for procedures."""
        key = tuple((proc.start_idx, proc.end_idx) for proc in procs)
        if self._complexity_metrics_cache is None:
            self._complexity_metrics_cache = {}
        cached = self._complexity_metrics_cache.get(key)
        if cached is not None:
            return cached
        metrics = [
            _calc_complexity_metrics_from_lines(
                self.lines,
                proc.start_idx,
                proc.end_idx,
                masked_lines=self.counter_lines,
                proc_name=proc.name,
            )
            for proc in procs
        ]
        self._complexity_metrics_cache[key] = metrics
        return metrics

    def module_body_cognitive_complexity_facts(
        self,
        max_cognitive_complexity: int,
    ) -> list[LineDiagnosticFact]:
        """Return cached BSL011 facts for complex module-body code blocks."""
        if self._module_body_cognitive_facts_cache is None:
            self._module_body_cognitive_facts_cache = {}
        cached = self._module_body_cognitive_facts_cache.get(max_cognitive_complexity)
        if cached is not None:
            return cached

        facts: list[LineDiagnosticFact] = []
        cursor = 0
        for proc in sorted(self.procedures, key=lambda item: item.start_idx):
            facts.extend(
                self._module_body_cognitive_complexity_facts_for_range(
                    cursor,
                    proc.start_idx - 1,
                    max_cognitive_complexity,
                )
            )
            cursor = max(cursor, proc.end_idx + 1)
        facts.extend(
            self._module_body_cognitive_complexity_facts_for_range(
                cursor,
                len(self.lines) - 1,
                max_cognitive_complexity,
            )
        )
        self._module_body_cognitive_facts_cache[max_cognitive_complexity] = facts
        return facts

    def _module_body_cognitive_complexity_facts_for_range(
        self,
        start_idx: int,
        end_idx: int,
        max_cognitive_complexity: int,
    ) -> list[LineDiagnosticFact]:
        if start_idx > end_idx:
            return []
        cognitive, _mccabe = _calc_complexity_metrics_from_lines(
            self.lines,
            start_idx - 1,
            end_idx + 1,
            masked_lines=self.counter_lines,
        )
        if cognitive <= max_cognitive_complexity:
            return []
        for idx in range(start_idx, min(end_idx + 1, len(self.lines))):
            line = self.lines[idx]
            if not line.strip() or line.lstrip().startswith(("//", "|")):
                continue
            match = re.search(r"\S+", line)
            if match is None:
                continue
            return [
                LineDiagnosticFact(
                    line_idx=idx,
                    character=match.start(),
                    end_character=match.end(),
                )
            ]
        return []

    @property
    def missing_space_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL216 spacing facts for this document."""
        if self._missing_space_facts is not None:
            return self._missing_space_facts

        facts: list[LineDiagnosticFact] = []
        str_states = self.line_string_states
        masked_lines = self.masked_lines
        comment_starts = self.comment_starts
        code_lines_wo_comments = self.code_lines_without_comments
        for idx, line in enumerate(self.lines):
            if _RE_LINE_COMMENT.match(line):
                continue
            in_str_start = str_states[idx]
            clean_full = masked_lines[idx]
            clean = clean_full
            comment_pos = comment_starts[idx]
            if comment_pos is not None:
                clean = clean[:comment_pos]
            has_comparison = "=" in clean or "<" in clean or ">" in clean
            has_arithmetic_ops = any(op in line for op in "+-*/%")
            code_no_comments = code_lines_wo_comments[idx]
            has_comma = "," in code_no_comments
            has_semicolon = ";" in clean
            has_keyword_candidate = bool(_RE_BSL216_ANY_KEYWORD.search(clean))
            if has_comparison:
                facts.extend(self._missing_comparison_space_facts(idx, clean))
            if has_arithmetic_ops:
                facts.extend(self._missing_arithmetic_space_facts(idx, line, in_str_start))
            if has_comma:
                facts.extend(self._missing_comma_space_facts(idx, code_no_comments))
            facts.extend(
                self._missing_semicolon_space_facts(
                    idx,
                    clean,
                    clean_full,
                    comment_pos,
                    has_semicolon,
                )
            )
            if has_keyword_candidate:
                facts.extend(self._missing_keyword_space_facts(idx, line, clean))
        self._missing_space_facts = facts
        return facts

    def _missing_comparison_space_facts(
        self,
        line_idx: int,
        clean: str,
    ) -> list[LineDiagnosticFact]:
        facts: list[LineDiagnosticFact] = []
        for match in _RE_BSL216_COMPARISON_OP.finditer(clean):
            start = match.start()
            end = match.end()
            left_missing = start > 0 and clean[start - 1] not in " \t"
            right_missing = end < len(clean) and clean[end] not in " \t"
            if not left_missing and not right_missing:
                continue
            facts.append(LineDiagnosticFact(line_idx, start, end))
        return facts

    def _missing_arithmetic_space_facts(
        self,
        line_idx: int,
        line: str,
        in_str_start: bool,
    ) -> list[LineDiagnosticFact]:
        arithmetic_cols = _arithmetic_missing_space_cols_in_line(line, in_str_start)
        stripped_line = line.lstrip()
        if (
            stripped_line.startswith(("+", "-"))
            and len(stripped_line) > 1
            and stripped_line[1] not in " \t"
        ):
            arithmetic_cols = sorted(set(arithmetic_cols) | {len(line) - len(stripped_line)})
        facts: list[LineDiagnosticFact] = []
        for col in arithmetic_cols:
            facts.append(LineDiagnosticFact(line_idx, col, col + 1))
        return facts

    def _missing_comma_space_facts(
        self,
        line_idx: int,
        code_no_comments: str,
    ) -> list[LineDiagnosticFact]:
        comma_cols = comma_missing_space_after_cols_in_line(code_no_comments)
        extra_comma_cols = {m.start() for m in re.finditer(r",(?=\))", code_no_comments)}
        if extra_comma_cols:
            comma_cols = sorted(set(comma_cols) | extra_comma_cols)
        return [
            LineDiagnosticFact(
                line_idx,
                comma_col,
                comma_col + 1,
            )
            for comma_col in comma_cols
        ]

    def _missing_semicolon_space_facts(
        self,
        line_idx: int,
        clean: str,
        clean_full: str,
        comment_pos: int | None,
        has_semicolon: bool,
    ) -> list[LineDiagnosticFact]:
        facts: list[LineDiagnosticFact] = []
        m_semicolon = _RE_BSL216_SEMICOLON_NOSPACE.search(clean) if has_semicolon else None
        if (
            m_semicolon is None
            and has_semicolon
            and comment_pos is not None
            and comment_pos > 0
            and clean_full[comment_pos - 1] == ";"
            and clean_full[comment_pos : comment_pos + 2] == "//"
        ):
            semicolon_col = comment_pos - 1
            facts.append(
                LineDiagnosticFact(
                    line_idx,
                    semicolon_col,
                    semicolon_col + 1,
                )
            )
        if m_semicolon:
            facts.append(
                LineDiagnosticFact(
                    line_idx,
                    m_semicolon.start(),
                    m_semicolon.end(),
                )
            )
        return facts

    def _missing_keyword_space_facts(
        self,
        line_idx: int,
        line: str,
        clean: str,
    ) -> list[LineDiagnosticFact]:
        facts: list[LineDiagnosticFact] = []
        for m_kw in _RE_BSL216_LEFT_RIGHT_KEYWORDS.finditer(clean):
            start = m_kw.start(1)
            end = m_kw.end(1)
            left_missing = start > 0 and clean[start - 1] not in " \t"
            right_missing = end < len(clean) and clean[end] not in " \t"
            if not left_missing and not right_missing:
                continue
            facts.append(LineDiagnosticFact(line_idx, start, end))
        for m_kw in _RE_BSL216_LEFT_KEYWORDS.finditer(clean):
            start = m_kw.start(1)
            end = m_kw.end(1)
            if start <= 0 or clean[start - 1] in " \t":
                continue
            facts.append(LineDiagnosticFact(line_idx, start, end))
        for m_kw in _RE_BSL216_RIGHT_KEYWORDS.finditer(clean):
            start = m_kw.start(1)
            end = m_kw.end(1)
            if end >= len(clean) or clean[end] in " \t":
                continue
            facts.append(LineDiagnosticFact(line_idx, start, end))
        return facts

    @property
    def incorrect_line_break_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL200 token-adjacency line-break facts for this document."""
        if self._incorrect_line_break_facts is not None:
            return self._incorrect_line_break_facts
        query_prev_lines = {
            block.start_idx - 1 for block in self.query_text_blocks if block.start_idx > 0
        }
        facts: list[LineDiagnosticFact] = []
        for idx, line in enumerate(self.lines):
            if idx in query_prev_lines:
                continue
            for match in (
                _RE_BSL200_INCORRECT_START.search(line),
                _RE_BSL200_INCORRECT_END.search(line),
            ):
                fact = self._incorrect_line_break_fact(idx, line, match)
                if fact is not None:
                    facts.append(fact)
        self._incorrect_line_break_facts = facts
        return facts

    def _incorrect_line_break_fact(
        self,
        line_idx: int,
        line: str,
        match: re.Match[str] | None,
    ) -> LineDiagnosticFact | None:
        if match is None:
            return None
        start = match.start(1)
        end = match.end(1)
        comment_start = self.comment_starts[line_idx]
        in_comment = comment_start is not None and end >= comment_start
        token_end = start + 1
        in_string = span_is_inside_double_quoted_string(
            line,
            start,
            token_end,
            in_str_at_start=False
            if line[start:token_end] in ",);"
            else self.line_string_states[line_idx],
        )
        if in_comment or in_string:
            return None
        return LineDiagnosticFact(
            line_idx,
            start,
            end,
        )

    @property
    def hardcoded_credential_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL012 hardcoded credential facts."""
        if self._hardcoded_credential_facts is not None:
            return self._hardcoded_credential_facts
        facts: list[LineDiagnosticFact] = []
        if not self.tree_ok:
            self._hardcoded_credential_facts = facts
            return facts

        emitted: set[tuple[int, int, int, int]] = set()

        def add_fact(node: Any) -> None:
            key = (
                node.start_point[0],
                node.start_point[1],
                node.end_point[0],
                node.end_point[1],
            )
            if key in emitted:
                return
            emitted.add(key)
            facts.append(_credential_fact_for_node(node, self.lines))

        nodes = self.ts_nodes_for_types(
            {"assignment_statement", "method_call", "new_expression"},
            hot_node_types=(
                "assignment_statement",
                "method_call",
                "new_expression",
            ),
            walker=_ts_walk,
        )

        for assignment in nodes["assignment_statement"]:
            left, value = _credential_assignment_parts(assignment)
            if _credential_single_string_expression(value) is None:
                continue
            if getattr(left, "type", None) == "identifier":
                if _credential_key_matches(_ts_node_text(left)):
                    add_fact(assignment)
                continue
            if getattr(left, "type", None) == "property_access":
                key = _credential_property_key(left)
                if key is not None and _credential_key_matches(key):
                    add_fact(assignment)

        for method_call in nodes["method_call"]:
            name = _credential_first_identifier(method_call)
            if name is None or _ts_node_text(name).casefold() not in _CREDENTIAL_INSERT_METHODS:
                continue
            args = _credential_argument_expressions(_ts_child_of_type(method_call, "arguments"))
            if (
                len(args) > 1
                and args[0] is not None
                and args[1] is not None
                and _credential_single_string_expression(args[1]) is not None
                and _credential_key_matches(_ts_node_text(args[0]))
            ):
                statement = _credential_ancestor_of_type(method_call, {"call_statement"})
                add_fact(statement or method_call)

        for new_expression in nodes["new_expression"]:
            type_node = _credential_first_identifier(new_expression)
            type_name = _ts_node_text(type_node).casefold() if type_node is not None else ""
            if type_name not in _CREDENTIAL_CONTAINER_TYPES:
                continue
            args = _credential_argument_expressions(_ts_child_of_type(new_expression, "arguments"))
            assignment = _credential_ancestor_of_type(new_expression, {"assignment_statement"})
            if assignment is None:
                continue
            if type_name in _CREDENTIAL_CONNECTION_TYPES:
                if len(args) >= 4 and _credential_single_string_expression(args[3]) is not None:
                    add_fact(assignment)
                continue
            if not args or args[0] is None:
                continue
            keys = _credential_clear_string(_ts_node_text(args[0])).split(",")
            for index, key in enumerate(keys):
                value_index = index + 1
                if (
                    _credential_key_matches(key)
                    and len(args) > value_index
                    and _credential_single_string_expression(args[value_index]) is not None
                ):
                    add_fact(assignment)
                    break

        self._hardcoded_credential_facts = facts
        return facts

    @property
    def commented_code_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL013 commented-code facts."""
        if self._commented_code_facts is not None:
            return self._commented_code_facts

        if self.is_tree_sitter:
            self._commented_code_facts = self._commented_code_facts_from_cst()
            return self._commented_code_facts

        self._commented_code_facts = self._commented_code_facts_from_lines()
        return self._commented_code_facts

    def _commented_code_facts_from_cst(self) -> list[LineDiagnosticFact]:
        facts: list[LineDiagnosticFact] = []
        nodes = self.ts_nodes_for_types({"line_comment"}, walker=_ts_walk)["line_comment"]
        if not nodes:
            return facts

        parser = BslParser()
        group: list[Any] = []
        group_texts: list[str] = []
        group_has_example_marker = False
        in_query_comment = False

        def node_start(node: Any) -> tuple[int, int]:
            return _ts_point_to_line_lsp_character(self.lines, node.start_point)

        def node_end(node: Any) -> tuple[int, int]:
            return _ts_point_to_line_lsp_character(self.lines, node.end_point)

        def is_full_line_comment(node: Any) -> bool:
            row, character = node_start(node)
            if row < 0 or row >= len(self.lines):
                return False
            return self.lines[row][:character].strip() == ""

        def is_before_method_description_group() -> bool:
            if not group:
                return False
            node_types = _comment_lines_node_types(group_texts, parser)
            if node_types & {
                "procedure_definition",
                "function_definition",
                "PREPROC_IF_KEYWORD",
                "PREPROC_REGION_KEYWORD",
            }:
                return False
            end_row, _ = node_end(group[-1])
            idx = end_row + 1
            while idx < len(self.lines):
                stripped = self.lines[idx].strip()
                if not stripped or stripped.startswith("&"):
                    idx += 1
                    continue
                return bool(
                    re.match(
                        r"^(?:Процедура|Функция|Procedure|Function)\b",
                        stripped,
                        re.IGNORECASE,
                    )
                )
            return False

        def flush_group() -> None:
            nonlocal group, group_texts, group_has_example_marker, in_query_comment
            group_has_code = _comment_lines_parse_as_bsl(group_texts, parser) or in_query_comment
            if (
                not group
                or not group_has_code
                or group_has_example_marker
                or is_before_method_description_group()
            ):
                group = []
                group_texts = []
                group_has_example_marker = False
                in_query_comment = False
                return
            start_row, start_character = node_start(group[0])
            end_row, end_character = node_end(group[-1])
            facts.append(
                LineDiagnosticFact(
                    line_idx=start_row,
                    character=start_character,
                    end_line_idx=end_row,
                    end_character=end_character,
                )
            )
            group = []
            group_texts = []
            group_has_example_marker = False
            in_query_comment = False

        def start_group(node: Any, text: str, comment_text: str) -> None:
            nonlocal group, group_texts, group_has_example_marker, in_query_comment
            group = [node]
            group_texts = [text]
            group_has_example_marker = bool(_RE_COMMENTED_EXAMPLE_MARKER.match(comment_text))
            is_query_comment = bool(comment_text and _RE_COMMENTED_QUERY_LINE.match(comment_text))
            in_query_comment = is_query_comment

        for node in sorted(nodes, key=lambda item: item.start_point):
            text = _ts_node_text(node)
            comment_text = _uncomment_line_text(text)
            full_line = is_full_line_comment(node)
            if not full_line:
                flush_group()
                in_query_comment = False
                continue

            if not group:
                start_group(node, text, comment_text)
                continue

            prev = group[-1]
            prev_row, _ = node_end(prev)
            row, _ = node_start(node)
            if row != prev_row + 1:
                flush_group()
                in_query_comment = False
                start_group(node, text, comment_text)
                continue

            group.append(node)
            group_texts.append(text)
            group_has_example_marker = group_has_example_marker or bool(
                _RE_COMMENTED_EXAMPLE_MARKER.match(comment_text)
            )
            is_query_comment = bool(comment_text and _RE_COMMENTED_QUERY_LINE.match(comment_text))
            in_query_comment = in_query_comment or is_query_comment

        flush_group()
        return facts

    def _commented_code_facts_from_lines(self) -> list[LineDiagnosticFact]:
        facts: list[LineDiagnosticFact] = []
        group_start: int | None = None
        group_end: int | None = None
        group_has_code = False
        group_has_example_marker = False
        in_query_comment = False

        def add_group() -> None:
            nonlocal group_start, group_end, group_has_code, group_has_example_marker
            if group_start is None or group_end is None or not group_has_code:
                return
            if group_has_example_marker:
                return
            start_character = self.lines[group_start].find("//")
            end_character = len(self.lines[group_end].rstrip())
            facts.append(
                LineDiagnosticFact(
                    line_idx=group_start,
                    character=max(start_character, 0),
                    end_character=end_character,
                    end_line_idx=group_end,
                )
            )

        for idx, line in enumerate(self.lines):
            comment_text = ""
            line_is_comment = line.lstrip().startswith("//")
            if line_is_comment:
                comment_text = line.lstrip()[2:].strip()
            is_query_comment = bool(comment_text and _RE_COMMENTED_QUERY_LINE.match(comment_text))
            if line_is_comment:
                if group_start is None:
                    group_start = idx
                group_end = idx
                group_has_example_marker = group_has_example_marker or bool(
                    _RE_COMMENTED_EXAMPLE_MARKER.match(comment_text)
                )
                group_has_code = (
                    group_has_code
                    or _RE_COMMENTED_CODE.match(line) is not None
                    or _comment_looks_like_embedded_code(comment_text)
                    or in_query_comment
                )
                in_query_comment = in_query_comment or is_query_comment
                continue

            add_group()
            group_start = None
            group_end = None
            group_has_code = False
            group_has_example_marker = False
            in_query_comment = False
            comment_pos = line.find("//")
            if comment_pos >= 0:
                inline_comment = line[comment_pos:]
                if _RE_COMMENTED_INLINE_ASSIGNMENT.search(
                    inline_comment
                ) or _RE_COMMENTED_CODE.match(inline_comment):
                    facts.append(
                        LineDiagnosticFact(
                            line_idx=idx,
                            character=comment_pos,
                            end_character=len(line.rstrip()),
                        )
                    )

        add_group()
        return facts

    @property
    def non_standard_region_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL016 non-standard region facts."""
        if self._non_standard_region_facts is not None:
            return self._non_standard_region_facts
        allowed = _standard_regions_for_path(self.path)
        module_regions = _module_level_regions(self.regions)
        if not allowed or not module_regions:
            self._non_standard_region_facts = []
            return self._non_standard_region_facts

        facts: list[LineDiagnosticFact] = []
        for region in module_regions:
            if _is_standard_region_name_for_path(self.path, region.name):
                continue
            line_idx = region.start_idx
            line_text = self.lines[line_idx] if line_idx < len(self.lines) else ""
            start_char = 1 if line_text.startswith("#") else 0
            facts.append(
                LineDiagnosticFact(
                    line_idx=line_idx,
                    character=start_char,
                    end_character=len(line_text.rstrip()),
                )
            )
        self._non_standard_region_facts = facts
        return facts

    @property
    def empty_region_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL026 empty region facts."""
        if self._empty_region_facts is not None:
            return self._empty_region_facts
        facts: list[LineDiagnosticFact] = []
        for region in self.regions:
            has_code = False
            for line_idx in range(region.start_idx + 1, min(region.end_idx, len(self.lines))):
                if _RE_REGION_EMPTY_CODE.match(self.lines[line_idx]):
                    has_code = True
                    break
            if has_code:
                continue
            line_idx = region.start_idx
            line_text = self.lines[line_idx] if line_idx < len(self.lines) else ""
            facts.append(
                LineDiagnosticFact(
                    line_idx=line_idx,
                    character=0,
                    end_character=len(line_text),
                )
            )
        self._empty_region_facts = facts
        return facts

    @property
    def duplicate_region_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL131 duplicate region facts."""
        if self._duplicate_region_facts is not None:
            return self._duplicate_region_facts

        facts: list[LineDiagnosticFact] = []
        seen: dict[str, RegionInfo] = {}
        reported: set[str] = set()
        for region in _module_level_regions(self.regions):
            key = _normalize_duplicate_region_name(region.name)
            if not key:
                continue
            if key not in seen:
                seen[key] = region
                continue
            if key in reported:
                continue
            first = seen[key]
            line = self.lines[first.start_idx] if 0 <= first.start_idx < len(self.lines) else ""
            start, end = _region_directive_name_range(line)
            facts.append(
                LineDiagnosticFact(
                    line_idx=first.start_idx,
                    character=start,
                    end_character=end,
                )
            )
            reported.add(key)
        self._duplicate_region_facts = facts
        return facts

    @property
    def deprecated_warning_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL022 modal global method facts."""
        if self._deprecated_warning_facts is not None:
            return self._deprecated_warning_facts
        root = self.root_node
        facts = (
            _bsl022_modal_facts_from_nodes(
                self.ts_nodes_for_types({"method_call"}, walker=_ts_walk)["method_call"],
                self.lines,
                self.procedures,
            )
            if self.tree_ok and root is not None
            else _bsl022_modal_facts_from_lines(self.lines, self.procedures)
        )
        self._deprecated_warning_facts = facts
        return facts

    @property
    def command_or_form_export_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL017 export-in-command/form-module facts."""
        if self._command_or_form_export_facts is not None:
            return self._command_or_form_export_facts
        stem_lower = Path(self.path).stem.lower()
        is_command_or_form = (
            stem_lower.endswith("command")
            or stem_lower.endswith("команды")
            or "форма" in stem_lower
            or "form" in stem_lower
        )
        if not is_command_or_form:
            self._command_or_form_export_facts = []
            return self._command_or_form_export_facts

        facts: list[LineDiagnosticFact] = []
        for proc in self.procedures:
            if not proc.is_export:
                continue
            line_text = self.lines[proc.start_idx] if proc.start_idx < len(self.lines) else ""
            facts.append(
                LineDiagnosticFact(
                    line_idx=proc.start_idx,
                    character=proc.header_col,
                    end_character=len(line_text),
                )
            )
        self._command_or_form_export_facts = facts
        return facts

    @property
    def this_form_usage_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL040 ThisForm usage facts."""
        if self._this_form_usage_facts is not None:
            return self._this_form_usage_facts
        if not _path_is_likely_form_module_bsl(self.path):
            self._this_form_usage_facts = []
            return self._this_form_usage_facts

        facts: list[LineDiagnosticFact] = []
        for idx, line in enumerate(self.lines):
            line_cf = line.casefold()
            if "этаформа" not in line_cf and "thisform" not in line_cf:
                continue
            proc = proc_containing_line(self.procedures, idx)
            if proc is not None and any(
                re.fullmatch(r"(?:ЭтаФорма|ThisForm)", param, re.IGNORECASE)
                for param in proc.params
            ):
                continue
            clean = mask_double_quoted_strings_preserve_len(line)
            comment_col = clean.find("//")
            if comment_col >= 0:
                clean = clean[:comment_col]
            for match in _RE_THIS_FORM.finditer(clean):
                facts.append(
                    LineDiagnosticFact(
                        line_idx=idx,
                        character=match.start(),
                        end_character=match.end(),
                    )
                )
        self._this_form_usage_facts = facts
        return facts

    @property
    def form_data_to_value_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL190 ДанныеФормыВЗначение/FormDataToValue facts."""
        if self._form_data_to_value_facts is not None:
            return self._form_data_to_value_facts

        facts: list[LineDiagnosticFact] = []
        for idx, line in enumerate(self.lines):
            line_cf = line.casefold()
            if "данныеформывзначение" not in line_cf and "formdatatovalue" not in line_cf:
                continue
            if _RE_LINE_COMMENT.match(line):
                continue
            clean = self.masked_lines[idx]
            comment_start = self.comment_starts[idx]
            if comment_start is not None:
                clean = clean[:comment_start]
            match = _RE_BSL190_FORM_DATA.search(clean)
            if match is None:
                continue
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=match.start("name"),
                    end_character=match.end("name"),
                )
            )
        self._form_data_to_value_facts = facts
        return facts

    @property
    def invalid_character_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL204 invalid-character facts."""
        if self._invalid_character_facts is not None:
            return self._invalid_character_facts

        facts: list[LineDiagnosticFact] = []
        for line_idx, line in enumerate(self.lines):
            hit = next(
                (pos for pos, ch in enumerate(line) if ch in _BSL204_ILLEGAL_CHARS),
                None,
            )
            if hit is None:
                continue
            pos = hit
            string_span = _double_quoted_span_containing(line, pos)
            if string_span is None:
                anchor = len(line) - len(line.lstrip())
                end_character = len(line.rstrip())
            else:
                anchor, end_character = string_span
            facts.append(
                LineDiagnosticFact(
                    line_idx=line_idx,
                    character=anchor,
                    end_character=end_character,
                )
            )
        self._invalid_character_facts = facts
        return facts

    @property
    def module_variable_description_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL219 module-level variable description facts."""
        if self._module_variable_description_facts is not None:
            return self._module_variable_description_facts

        inside_procedure_lines: set[int] = set()
        for proc in self.procedures:
            inside_procedure_lines.update(range(proc.start_idx, proc.end_idx + 1))

        facts: list[LineDiagnosticFact] = []
        idx = 0
        clean_lines = self.code_lines_without_comments
        while idx < len(clean_lines):
            clean_line = clean_lines[idx]
            if idx in inside_procedure_lines:
                idx += 1
                continue
            code_part = clean_line.rstrip()
            if not code_part.strip():
                idx += 1
                continue
            if (
                _RE_VAR_MODULE_HEAD.match(code_part) is not None
                and _RE_VAR_MODULE.match(code_part) is None
            ):
                multiline = _module_var_multiline_name_ranges(clean_lines, idx)
                if multiline is not None:
                    end_idx, multiline_facts = multiline
                    if not (
                        _has_preceding_variable_description(self.lines, idx)
                        or _has_inline_variable_description(self.lines[idx])
                        or _has_previous_inline_variable_description(self.lines, idx)
                    ):
                        facts.extend(
                            fact
                            for fact in multiline_facts
                            if fact.line_idx not in inside_procedure_lines
                            and not _has_inline_variable_description(self.lines[fact.line_idx])
                        )
                    idx = end_idx + 1
                    continue
            match = _RE_VAR_MODULE.match(code_part)
            if (
                match is None
                or _has_preceding_variable_description(self.lines, idx)
                or _has_inline_variable_description(self.lines[idx])
                or _has_previous_inline_variable_description(self.lines, idx)
            ):
                idx += 1
                continue
            facts.extend(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=start,
                    end_character=end,
                )
                for start, end in _module_var_name_ranges(match)
            )
            idx += 1
        self._module_variable_description_facts = facts
        return facts

    def complex_condition_facts(self, max_bool_ops: int) -> list[LineDiagnosticFact]:
        """Return cached BSL036 complex If/ElseIf condition facts."""
        if self._complex_condition_facts_cache is None:
            self._complex_condition_facts_cache = {}
        cached = self._complex_condition_facts_cache.get(max_bool_ops)
        if cached is not None:
            return cached

        facts: list[LineDiagnosticFact] = []
        for idx, line in enumerate(self.lines):
            line_cf = line.casefold()
            if "если" not in line_cf and "if" not in line_cf:
                continue
            span = self._complex_condition_span(idx, max_bool_ops)
            if span is None:
                continue
            end_line_idx, end_char = span
            match = _RE_COMPLEX_CONDITION_HEAD_PREFIX.match(line)
            char = match.end() if match is not None else len(line) - len(line.lstrip())
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=char,
                    end_line_idx=end_line_idx,
                    end_character=end_char,
                )
            )
        self._complex_condition_facts_cache[max_bool_ops] = facts
        return facts

    def _complex_condition_span(
        self,
        line_idx: int,
        max_bool_ops: int,
    ) -> tuple[int, int] | None:
        chunk = self._complex_condition_chunk(line_idx)
        if chunk is None:
            return None
        text, end_line_idx, end_char = chunk
        if len(_RE_COMPLEX_CONDITION_BOOL_OP.findall(text)) + 1 <= max_bool_ops:
            return None
        return end_line_idx, end_char

    def _complex_condition_chunk(self, line_idx: int) -> tuple[str, int, int] | None:
        line = self.lines[line_idx]
        if line.strip().startswith("//"):
            return None
        if not _RE_COMPLEX_CONDITION_HEAD.match(line):
            return None
        masked_line = line.partition("//")[0]
        then_match = _RE_COMPLEX_CONDITION_THEN.search(masked_line)
        if then_match is not None:
            return (
                masked_line,
                line_idx,
                len(masked_line[: then_match.start()].rstrip()),
            )

        parts = [masked_line]
        idx = line_idx + 1
        max_idx = min(len(self.lines), line_idx + 48)
        while idx < max_idx:
            masked_next = self.lines[idx].partition("//")[0]
            if re.match(r"^\s*(?:Тогда|Then)\b", masked_next, re.IGNORECASE):
                previous_idx = idx - 1
                while previous_idx > line_idx:
                    previous = self.lines[previous_idx].partition("//")[0]
                    if previous.strip():
                        return "\n".join(parts), previous_idx, len(previous.rstrip())
                    previous_idx -= 1
                previous = self.lines[previous_idx].partition("//")[0]
                return "\n".join(parts), previous_idx, len(previous.rstrip())
            parts.append(masked_next)
            then_match = _RE_COMPLEX_CONDITION_THEN.search(masked_next)
            if then_match is not None:
                return "\n".join(parts), idx, len(masked_next[: then_match.start()].rstrip())
            idx += 1
        return (
            "\n".join(parts),
            idx - 1,
            len(self.lines[idx - 1].partition("//")[0].rstrip())
            if idx > line_idx
            else len(masked_line.rstrip()),
        )

    @property
    def select_top_without_order_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL077 SELECT TOP/FIRST without ORDER BY facts."""
        if self._select_top_without_order_facts is not None:
            return self._select_top_without_order_facts

        facts: list[LineDiagnosticFact] = []
        for block in self.query_text_blocks:
            root = getattr(getattr(block, "sdbl_tree", None), "root_node", None)
            if root is None:
                continue
            if block.sdbl_has_errors:
                continue
            for top_fact in select_top_without_order(root):
                start_line, start_char = block.original_lsp_position(
                    top_fact.node.start_point[0],
                    top_fact.node.start_point[1],
                )
                end_line, end_char = block.original_lsp_position(
                    top_fact.node.end_point[0],
                    top_fact.node.end_point[1],
                )
                facts.append(
                    LineDiagnosticFact(
                        line_idx=start_line,
                        character=start_char,
                        end_character=end_char,
                        end_line_idx=end_line,
                    )
                )
        self._select_top_without_order_facts = facts
        return facts

    def _region_is_empty(self, region: RegionInfo) -> bool:
        for line_idx in range(region.start_idx + 1, min(region.end_idx, len(self.lines))):
            stripped = self.lines[line_idx].strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                continue
            return False
        return True

    def line_too_long_facts(self, max_line_length: int) -> list[LineDiagnosticFact]:
        """Return cached BSL014 line-length facts for the configured limit."""
        if self._line_too_long_facts_cache is None:
            self._line_too_long_facts_cache = {}
        cached = self._line_too_long_facts_cache.get(max_line_length)
        if cached is not None:
            return cached

        reported_lengths = self.reported_line_lengths
        candidate_indices = [
            idx
            for idx, reported_length in enumerate(reported_lengths)
            if reported_length > max_line_length
        ]
        if not candidate_indices:
            self._line_too_long_facts_cache[max_line_length] = []
            return []

        facts: list[LineDiagnosticFact] = []
        needs_query_exclusion = any(
            self.lines[idx].lstrip().startswith("|") or _RE_QUERY_TEXT_START.search(self.lines[idx])
            for idx in candidate_indices
        )
        query_line_indices = self.query_line_indices if needs_query_exclusion else frozenset()
        for idx in candidate_indices:
            if idx in query_line_indices:
                continue
            reported_length = reported_lengths[idx]
            if reported_length <= max_line_length:
                continue
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=0,
                    end_character=reported_length,
                )
            )
        self._line_too_long_facts_cache[max_line_length] = facts
        return facts

    def get_runtime_call_context(self) -> Any | None:
        """Return cached runtime call context if it has been built."""
        return self._runtime_call_context_cache

    def set_runtime_call_context(self, context: Any) -> None:
        """Store shared runtime call context for this snapshot."""
        self._runtime_call_context_cache = context

    def get_global_method_calls(self) -> Any | None:
        """Return cached global method-call facts if they have been built."""
        return self._global_method_calls_cache

    def set_global_method_calls(self, calls: Any) -> None:
        """Store global method-call facts shared by runtime rules."""
        self._global_method_calls_cache = calls

    def semantic_facts(self, revision: Any | None = None) -> Any:
        """Return one immutable fact snapshot for this content and semantic revision."""
        from onec_hbk_bsl.analysis.semantic_facts import (  # noqa: PLC0415
            FactRevision,
            build_semantic_fact_snapshot,
        )

        if revision is None:
            revision = FactRevision.for_content(self.content)
        with self._cache_lock:
            if self._semantic_fact_snapshots is None:
                self._semantic_fact_snapshots = {}
            facts = self._semantic_fact_snapshots.get(revision)
            if facts is None:
                facts = build_semantic_fact_snapshot(self, revision)
                self._semantic_fact_snapshots[revision] = facts
                self._semantic_fact_build_count += 1
            return facts

    @property
    def semantic_fact_build_count(self) -> int:
        """Number of distinct content/revision fact snapshots materialized."""
        with self._cache_lock:
            return self._semantic_fact_build_count

    def get_ternary_spans(self) -> Any | None:
        """Return cached textual ternary spans if they have been built."""
        return self._ternary_spans_cache

    def set_ternary_spans(self, spans: Any) -> None:
        """Store textual ternary spans shared by runtime rules."""
        self._ternary_spans_cache = spans


def build_document_snapshot(
    path: str,
    *,
    content: str,
    tree: Any | None = None,
    parser: BslParser | None = None,
) -> DocumentSnapshot:
    """Build a shared snapshot for one BSL document."""

    effective_parser = parser or BslParser()
    effective_tree = (
        tree if tree is not None else effective_parser.parse_content(content, file_path=path)
    )
    return DocumentSnapshot(path=path, content=content, tree=effective_tree)
