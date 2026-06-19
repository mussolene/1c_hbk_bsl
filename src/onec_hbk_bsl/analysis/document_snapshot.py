"""Shared parsed document snapshot for diagnostics, formatting, and indexing.

The project historically re-parsed the same document and re-walked the same
tree-sitter CST in several layers: diagnostics, formatter, symbol extraction,
call graph extraction, and LSP helpers. This module provides a single lazily
derived snapshot object so those layers can share one parsed view of a file.
"""

from __future__ import annotations

import re
import threading
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.bsl_string_split import (
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.call_graph import Call
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
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character, utf16_len
from onec_hbk_bsl.analysis.parse_tree import tree_has_errors
from onec_hbk_bsl.analysis.sdbl_cst import select_top_without_order
from onec_hbk_bsl.analysis.semantic import SemanticModel, extract_semantic_model
from onec_hbk_bsl.analysis.symbols import Symbol

try:
    import tree_sitter_bsl as _ts_bsl
    from tree_sitter import Language as _TsLanguage
    from tree_sitter import Parser as _TsParser

    _SDBL_LANGUAGE = _TsLanguage(_ts_bsl.sdbl_language())
except Exception:  # pragma: no cover - optional parser dependency fallback
    _SDBL_LANGUAGE = None
    _TsParser = None  # type: ignore[assignment]
from onec_hbk_bsl.parser.bsl_parser import BslParser

_RE_PROC_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?:Асинх|Async)\s+)?(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
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
    r"^\s*(?:Перем|Var)\s+(?P<names>[\w\s,]+?)\s*(?:Экспорт|Export)?\s*;",
    re.IGNORECASE,
)
_BSL204_ILLEGAL_CHARS = {
    "\u00ad": 'Нужно исправить на правильный символ "-"',
    "\u2012": 'Нужно исправить на правильный символ "-"',
    "\u2013": 'Нужно исправить на правильный символ "-"',
    "\u2014": 'Нужно исправить на правильный символ "-"',
    "\u2015": 'Нужно исправить на правильный символ "-"',
    "\u2212": 'Нужно исправить на правильный символ "-"',
    "\u00a0": "Нужно заменить символ неразрывного пробела на обычный пробел",
}
_RE_COMPLEX_CONDITION_HEAD = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\b",
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
_RE_CREDENTIALS = re.compile(
    r"(?:пароль|password|passwd|pwd|secret|credential(?:s)?|token"
    r'|логин|login|auth|apikey|api_key|accesskey|access_key)\s*=\s*"[^"]{2,}"',
    re.IGNORECASE,
)
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


def _line_has_self_call(line: str, proc_name: str | None) -> bool:
    if not proc_name:
        return False
    return bool(re.search(rf"(?<![.\w]){re.escape(proc_name)}\s*\(", line, re.IGNORECASE))


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
        if not stripped or stripped.startswith("&"):
            prev_idx -= 1
            continue
        if _RE_VAR_MODULE.match(stripped):
            return _has_inline_variable_description(lines[prev_idx])
        return False
    return False


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
    parts = [x.lower() for x in p.parts]
    if p.suffix.lower() != ".bsl":
        return False
    form_indexes = [idx for idx, part in enumerate(parts) if part in {"forms", "формы"}]
    if not any("ext" in parts[idx + 1 :] for idx in form_indexes):
        return False
    if p.name.lower() == "module.bsl":
        return True
    try:
        lower_siblings = {sibling.name.lower() for sibling in p.parent.iterdir()}
    except OSError:
        return False
    return bool({"module.bsl", "module.header", "form.xml", "form.prettydata"} & lower_siblings)


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
    message: str
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


def _parse_params(params_str: str) -> list[tuple[str, bool, bool]]:
    result: list[tuple[str, bool, bool]] = []
    for raw in split_commas_outside_double_quotes(params_str):
        raw = raw.strip()
        if not raw:
            continue
        is_val = bool(re.match(r"^(?:Знач|Val)\s+", raw, re.IGNORECASE))
        clean = strip_leading_val_keywords(raw)
        is_optional = "=" in clean
        name = clean.split("=")[0].strip()
        if name and re.match(r"^\w+$", name):
            result.append((name, is_val, is_optional))
    return result


def _param_ranges_from_params_string(
    content: str,
    line_breaks: list[int],
    params_str: str,
    params_start_offset: int,
) -> tuple[tuple[str, int, int, int, int], ...]:
    ranges: list[tuple[str, int, int, int, int]] = []
    offset = 0
    for raw_part in split_commas_outside_double_quotes(params_str):
        part_start = params_start_offset + offset
        offset += len(raw_part) + 1
        clean = strip_leading_val_keywords(raw_part.strip())
        if not clean:
            continue
        name = clean.split("=", 1)[0].strip()
        if not name or not re.match(r"^\w+$", name):
            continue
        relative = raw_part.find(name)
        if relative < 0:
            continue
        start_offset = part_start + relative
        end_offset = start_offset + len(name)
        start_idx, start_character = _lsp_point_for_offset(content, line_breaks, start_offset)
        end_idx, end_character = _lsp_point_for_offset(content, line_breaks, end_offset)
        ranges.append((name, start_idx, start_character, end_idx, end_character))
    return tuple(ranges)


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _ts_walk(node: Any):
    yield node
    for child in getattr(node, "children", []) or []:
        yield from _ts_walk(child)


def _ts_child_of_type(node: Any, child_type: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
        if getattr(child, "type", None) == child_type:
            return child
    return None


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


def _bsl022_message(method_name: str) -> str:
    return (
        f"{method_name}() is a modal global method deprecated in managed UI. "
        "Use asynchronous APIs instead."
    )


def _bsl022_modal_facts_from_tree(
    root: Any,
    lines: list[str],
    procedures: list[ProcInfo],
) -> list[LineDiagnosticFact]:
    facts: list[LineDiagnosticFact] = []
    for node in _ts_walk(root):
        if getattr(node, "type", None) != "method_call":
            continue
        if getattr(getattr(node, "parent", None), "type", None) == "call_expression":
            continue
        ident = _ts_child_of_type(node, "identifier")
        if ident is None:
            continue
        method_name = _ts_node_text(ident)
        if method_name.casefold() not in _BSL022_MODAL_GLOBAL_METHODS:
            continue
        line_idx, character = _ts_point_to_line_lsp_character(lines, ident.start_point)
        end_line_idx, end_character = _ts_point_to_line_lsp_character(lines, ident.end_point)
        proc = proc_containing_line(procedures, line_idx)
        if proc is not None and is_typical_client_command_handler(proc, lines):
            continue
        facts.append(
            LineDiagnosticFact(
                line_idx=line_idx,
                character=character,
                end_line_idx=end_line_idx,
                end_character=end_character,
                message=_bsl022_message(method_name),
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
        method_name = match.group("name")
        facts.append(
            LineDiagnosticFact(
                line_idx=idx,
                character=match.start("name"),
                end_character=match.end("name"),
                message=_bsl022_message(method_name),
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
            for param_child in getattr(child, "children", []) or []:
                param_child_type = getattr(param_child, "type", None)
                if param_child_type == "(":
                    open_node = param_child
                elif param_child_type == ")":
                    close_node = param_child
            if open_node is not None and close_node is not None:
                params_start_idx = open_node.end_point[0]
                params_start_character = _ts_point_to_lsp_character(node, open_node.end_point)
                params_end_idx = close_node.start_point[0]
                params_end_character = _ts_point_to_lsp_character(node, close_node.start_point)
            for param in getattr(child, "children", []) or []:
                if getattr(param, "type", None) != "parameter":
                    continue
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

    node_text = _ts_node_text(node)
    header_match = _RE_PROC_HEADER.search(node_text)
    if header_match is not None:
        name = header_match.group("name")
        is_export = bool(header_match.group("export"))
        parsed = _parse_params(header_match.group("params") or "")
        params = [param[0] for param in parsed]
        val_params = [param[0] for param in parsed if param[1]]
        optional_count = sum(1 for param in parsed if param[2])
        optional_params_list = [param[0] for param in parsed if param[2]]

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
    for child in getattr(node, "children", []) or []:
        _collect_procs_from_node(child, result)


def _collect_proc_names_from_node(node: Any, result: set[str]) -> None:
    node_type = getattr(node, "type", None)
    if node_type in ("procedure_definition", "function_definition"):
        for child in getattr(node, "children", []) or []:
            if getattr(child, "type", None) == "identifier":
                name = _ts_node_text(child)
                if name:
                    result.add(name.casefold())
                break
        return
    for child in getattr(node, "children", []) or []:
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


def find_procedure_names_in_content(content: str) -> frozenset[str]:
    return frozenset(proc.name.casefold() for proc in _find_procedures(content))


def _line_break_positions(content: str) -> list[int]:
    breaks: list[int] = []
    start = content.find("\n")
    while start != -1:
        breaks.append(start)
        start = content.find("\n", start + 1)
    return breaks


def _line_index_for_offset(line_breaks: list[int], offset: int) -> int:
    return bisect_left(line_breaks, offset)


def _lsp_point_for_offset(content: str, line_breaks: list[int], offset: int) -> tuple[int, int]:
    line_idx = _line_index_for_offset(line_breaks, offset)
    line_start = 0 if line_idx == 0 else line_breaks[line_idx - 1] + 1
    line_end = line_breaks[line_idx] if line_idx < len(line_breaks) else len(content)
    line_text = content[line_start:line_end].rstrip("\r")
    character = utf16_len(line_text[: max(0, offset - line_start)])
    return line_idx, character


def _find_procedures(content: str) -> list[ProcInfo]:
    line_breaks = _line_break_positions(content)
    ends = [
        _line_index_for_offset(line_breaks, match.start())
        for match in _RE_END_PROC.finditer(content)
    ]

    result: list[ProcInfo] = []
    for match in _RE_PROC_HEADER.finditer(content):
        start_idx = _line_index_for_offset(line_breaks, match.start())
        kw = match.group("kw").lower()
        name = match.group("name")
        params_str = match.group("params") or ""
        is_export = bool(match.group("export"))
        kind = "function" if kw in ("функция", "function") else "procedure"
        header_col = len(match.group("indent"))

        parsed = _parse_params(params_str)
        params = [param[0] for param in parsed]
        val_params = [param[0] for param in parsed if param[1]]
        optional_count = sum(1 for param in parsed if param[2])
        optional_params = frozenset(param[0] for param in parsed if param[2])
        param_ranges = _param_ranges_from_params_string(
            content,
            line_breaks,
            params_str,
            match.start("params"),
        )
        params_start_idx, params_start_character = _lsp_point_for_offset(
            content, line_breaks, match.start("params")
        )
        params_end_idx, params_end_character = _lsp_point_for_offset(
            content, line_breaks, match.end("params")
        )

        end_idx = start_idx + 5
        end_pos = bisect_right(ends, start_idx)
        if end_pos < len(ends):
            end_idx = ends[end_pos]

        result.append(
            ProcInfo(
                name=name,
                kind=kind,
                start_idx=start_idx,
                end_idx=end_idx,
                is_export=is_export,
                params=params,
                val_params=val_params,
                optional_count=optional_count,
                header_col=header_col,
                optional_params=optional_params,
                params_start_idx=params_start_idx,
                params_start_character=params_start_character,
                params_end_idx=params_end_idx,
                params_end_character=params_end_character,
                param_ranges=param_ranges,
            )
        )
    return result


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

    def visit(node: Any) -> None:
        if getattr(node, "type", None) == "preprocessor":
            child_types = {getattr(child, "type", None) for child in getattr(node, "children", [])}
            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0

            if "PREPROC_REGION_KEYWORD" in child_types:
                region_name = ""
                seen_keyword = False
                for child in getattr(node, "children", []) or []:
                    child_type = getattr(child, "type", None)
                    if child_type == "PREPROC_REGION_KEYWORD":
                        seen_keyword = True
                        continue
                    if seen_keyword and child_type == "identifier":
                        region_name = _ts_node_text(child)
                        break
                if "PREPROC_ENDREGION_KEYWORD" in child_types:
                    end_idx = (
                        node.end_point[0] if getattr(node, "end_point", None) else start_idx + 1
                    )
                    result.append(
                        RegionInfo(name=region_name, start_idx=start_idx, end_idx=end_idx)
                    )
                    for child in getattr(node, "children", []) or []:
                        visit(child)
                    return
                opens.append((start_idx, region_name))
                return

            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(start_idx)
                return

        for child in getattr(node, "children", []) or []:
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
            self._procs = (
                _find_procedures_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_procedures(self.content)
            )
        return self._procs

    @property
    def regions(self) -> list[RegionInfo]:
        if self._regions is None:
            self._regions = (
                _find_regions_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_regions(self.content)
            )
            if not self._regions:
                self._regions = _find_regions(self.content)
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
        """Return BSLLS-compatible visible line lengths used by BSL014."""
        if self._reported_line_lengths is not None:
            return self._reported_line_lengths

        if "\r" not in self.content and Path(self.path).is_file():
            try:
                raw_line_source = [
                    raw.decode("utf-8", errors="ignore")
                    for raw in Path(self.path).read_bytes().splitlines(True)
                ]
            except OSError:
                raw_line_source = self.content.splitlines(True)
            if len(raw_line_source) != len(self.content.splitlines()):
                raw_line_source = self.content.splitlines(True)
        else:
            raw_line_source = self.content.splitlines(True)

        reported_lengths: list[int] = []
        for raw in raw_line_source:
            raw_no_lf = raw.rstrip("\n")
            raw_no_eol = raw_no_lf.rstrip("\r")
            if raw_no_lf.endswith("\r") and raw_no_eol.lstrip().startswith("//"):
                visible_len = len(raw_no_eol.rstrip("\t"))
            else:
                visible_len = len(raw_no_eol.rstrip())
            reported_lengths.append(visible_len)
        self._reported_line_lengths = reported_lengths
        return reported_lengths

    @property
    def blank_line_flags(self) -> list[bool]:
        if self._blank_line_flags is None:
            self._blank_line_flags = [line.strip() == "" for line in self.lines]
        return self._blank_line_flags

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
            op = match.group(0)
            start = match.start()
            end = match.end()
            left_missing = start > 0 and clean[start - 1] not in " \t"
            right_missing = end < len(clean) and clean[end] not in " \t"
            if not left_missing and not right_missing:
                continue
            if left_missing and right_missing:
                msg = f"Слева и справа от '{op}' не хватает пробела"
            elif left_missing:
                msg = f"Слева от '{op}' не хватает пробела"
            else:
                msg = f"Справа от '{op}' не хватает пробела"
            facts.append(LineDiagnosticFact(line_idx, start, end, msg))
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
            op = line[col]
            left_missing = col > 0 and line[col - 1] not in " \t"
            right_missing = col + 1 < len(line) and line[col + 1] not in " \t"
            if left_missing and right_missing:
                msg = f"Слева и справа от '{op}' не хватает пробела"
            elif left_missing:
                msg = f"Слева от '{op}' не хватает пробела"
            else:
                msg = f"Справа от '{op}' не хватает пробела"
            facts.append(LineDiagnosticFact(line_idx, col, col + 1, msg))
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
                line_idx, comma_col, comma_col + 1, "Справа от ',' не хватает пробела"
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
                    "Справа от ';' не хватает пробела",
                )
            )
        if m_semicolon:
            facts.append(
                LineDiagnosticFact(
                    line_idx,
                    m_semicolon.start(),
                    m_semicolon.end(),
                    "Справа от ';' не хватает пробела",
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
            kw = line[start:end]
            if left_missing and right_missing:
                msg = f"Слева и справа от '{kw}' не хватает пробела"
            elif left_missing:
                msg = f"Слева от '{kw}' не хватает пробела"
            else:
                msg = f"Справа от '{kw}' не хватает пробела"
            facts.append(LineDiagnosticFact(line_idx, start, end, msg))
        for m_kw in _RE_BSL216_LEFT_KEYWORDS.finditer(clean):
            start = m_kw.start(1)
            end = m_kw.end(1)
            if start <= 0 or clean[start - 1] in " \t":
                continue
            kw = line[start:end]
            facts.append(
                LineDiagnosticFact(line_idx, start, end, f"Слева от '{kw}' не хватает пробела")
            )
        for m_kw in _RE_BSL216_RIGHT_KEYWORDS.finditer(clean):
            start = m_kw.start(1)
            end = m_kw.end(1)
            if end >= len(clean) or clean[end] in " \t":
                continue
            kw = line[start:end]
            facts.append(
                LineDiagnosticFact(line_idx, start, end, f"Справа от '{kw}' не хватает пробела")
            )
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
            "Проверьте правильность переноса операндов, операторов и параметров",
        )

    @property
    def hardcoded_credential_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL012 hardcoded credential facts."""
        if self._hardcoded_credential_facts is not None:
            return self._hardcoded_credential_facts
        facts: list[LineDiagnosticFact] = []
        for idx, line in enumerate(self.lines):
            if line.strip().startswith("//"):
                continue
            match = _RE_CREDENTIALS.search(line)
            if match is None:
                continue
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=match.start(),
                    end_character=match.end(),
                    message=f"Возможное хранение секрета в коде: {match.group()!r}",
                )
            )
        self._hardcoded_credential_facts = facts
        return facts

    @property
    def commented_code_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL013 commented-code facts."""
        if self._commented_code_facts is not None:
            return self._commented_code_facts

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
                    message="Программные модули не должны иметь закомментированных фрагментов кода",
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
                if _RE_COMMENTED_INLINE_ASSIGNMENT.search(inline_comment):
                    facts.append(
                        LineDiagnosticFact(
                            line_idx=idx,
                            character=comment_pos,
                            end_character=len(line.rstrip()),
                            message=(
                                "Программные модули не должны иметь "
                                "закомментированных фрагментов кода"
                            ),
                        )
                    )

        add_group()
        self._commented_code_facts = facts
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
                    end_character=len(line_text),
                    message=f'Нужно удалить нестандартный раздел "{region.name}"',
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
                    message=f'Область "{region.name}" не содержит функций или процедур',
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
        for region in _module_level_regions(self.regions):
            key = _normalize_duplicate_region_name(region.name)
            if not key:
                continue
            if key not in seen:
                seen[key] = region
                continue
            line = self.lines[region.start_idx] if 0 <= region.start_idx < len(self.lines) else ""
            facts.append(
                LineDiagnosticFact(
                    line_idx=region.start_idx,
                    character=len(line) - len(line.lstrip()),
                    end_character=len(line.rstrip()),
                    message=f'Нужно удалить дубли раздела "{region.name}"',
                )
            )
            seen[key] = region
        self._duplicate_region_facts = facts
        return facts

    @property
    def deprecated_warning_facts(self) -> list[LineDiagnosticFact]:
        """Return cached BSL022 modal global method facts."""
        if self._deprecated_warning_facts is not None:
            return self._deprecated_warning_facts
        root = self.root_node
        facts = (
            _bsl022_modal_facts_from_tree(root, self.lines, self.procedures)
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
                    message=(
                        f"Модификатор Экспорт запрещен в модулях команд и форм "
                        f"({proc.kind} '{proc.name}')"
                    ),
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
                        message=(
                            "Избегайте использования ЭтаФорма/ThisForm, "
                            "передавайте форму в параметрах метода"
                        ),
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
                    message="Не рекомендуемое использование метода ДанныеФормыВЗначение",
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
                (
                    (pos, _BSL204_ILLEGAL_CHARS[ch])
                    for pos, ch in enumerate(line)
                    if ch in _BSL204_ILLEGAL_CHARS
                ),
                None,
            )
            if hit is None:
                continue
            pos, message = hit
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
                    message=message,
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
        for idx, clean_line in enumerate(self.code_lines_without_comments):
            if idx in inside_procedure_lines:
                continue
            code_part = clean_line.rstrip()
            if not code_part.strip():
                continue
            match = _RE_VAR_MODULE.match(code_part)
            if (
                match is None
                or _has_preceding_variable_description(self.lines, idx)
                or _has_inline_variable_description(self.lines[idx])
                or _has_previous_inline_variable_description(self.lines, idx)
            ):
                continue
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=match.start("names"),
                    end_character=len(code_part.rstrip().rstrip(";").rstrip()),
                    message="Добавьте описание переменной",
                )
            )
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
            span = self._complex_condition_span(idx, max_bool_ops)
            if span is None:
                continue
            end_line_idx, end_char = span
            char = len(line) - len(line.lstrip())
            keyword = line.lstrip()
            keyword_lower = keyword.lower()
            if keyword_lower.startswith("если "):
                char += len("Если ")
            elif keyword_lower.startswith("if "):
                char += len("If ")
            elif keyword_lower.startswith("иначеесли "):
                char += len("ИначеЕсли ")
            elif keyword_lower.startswith("elsif "):
                char += len("ElsIf ")
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=char,
                    end_line_idx=end_line_idx,
                    end_character=end_char,
                    message="Выделите условие оператора Если в отдельный метод или переменную",
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
        masked_line = re.sub(r"//.*", "", line)
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
            masked_next = re.sub(r"//.*", "", self.lines[idx])
            parts.append(masked_next)
            then_match = _RE_COMPLEX_CONDITION_THEN.search(masked_next)
            if then_match is not None:
                return "\n".join(parts), idx, len(masked_next[: then_match.start()].rstrip())
            if re.match(r"^\s*(?:Тогда|Then)\b", masked_next, re.IGNORECASE):
                break
            idx += 1
        return (
            "\n".join(parts),
            idx - 1,
            len(re.sub(r"//.*", "", self.lines[idx - 1]).rstrip())
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
                        message="Нужно изменить запрос, добавив упорядочивание",
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

        facts: list[LineDiagnosticFact] = []
        reported_lengths = self.reported_line_lengths
        for idx, line in enumerate(self.lines):
            if line.lstrip().startswith("|"):
                content = line.lstrip()[1:].lstrip()
                if re.search(
                    r"\b(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|КАК|AS|ЗНАЧЕНИЕ|VALUE|ВЫРАЗИТЬ|CAST|СОЕДИНЕНИЕ|JOIN)\b",
                    content,
                    re.IGNORECASE,
                ):
                    continue
                if len(line.rstrip()) <= 140:
                    continue
            length = len(line.rstrip())
            reported_length = reported_lengths[idx] if idx < len(reported_lengths) else length
            if reported_length <= max_line_length:
                continue
            facts.append(
                LineDiagnosticFact(
                    line_idx=idx,
                    character=0,
                    end_character=reported_length,
                    message=(
                        f"Длина строки {reported_length} превышает максимально допустимую "
                        f"{max_line_length}"
                    ),
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
