from __future__ import annotations

import re
from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.context import BsllsDocumentContext
from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.storage import DiagnosticStorage
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity


class BsllsDiagnosticRule:
    code: str

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        raise NotImplementedError


@dataclass(frozen=True)
class _TernarySpan:
    start: int
    end: int
    line: int
    col: int
    end_line: int
    end_col: int


def _skip_string(text: str, pos: int) -> int:
    quote = text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == quote:
            if quote == '"' and pos + 1 < len(text) and text[pos + 1] == '"':
                pos += 2
                continue
            return pos + 1
        pos += 1
    return pos


def _matching_paren(text: str, open_pos: int) -> int:
    depth = 1
    pos = open_pos + 1
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            if newline < 0:
                return len(text)
            pos = newline + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return len(text)


def _ternary_spans(context: BsllsDocumentContext) -> list[_TernarySpan]:
    spans: list[_TernarySpan] = []
    pos = 0
    text = context.content
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            pos = len(text) if newline < 0 else newline + 1
            continue
        if char == "?":
            open_pos = pos + 1
            while open_pos < len(text) and text[open_pos].isspace():
                open_pos += 1
            if open_pos < len(text) and text[open_pos] == "(":
                end = _matching_paren(text, open_pos)
                line, col = context.to_line_col(pos)
                end_line, end_col = context.to_line_col(end)
                spans.append(_TernarySpan(pos, end, line, col, end_line, end_col))
                pos += 1
                continue
        pos += 1
    return spans


class NestedTernaryOperatorRule(BsllsDiagnosticRule):
    code = "BSL039"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        ternaries = _ternary_spans(context)
        flagged: dict[int, _TernarySpan] = {}
        for inner in ternaries:
            if any(outer.start < inner.start and inner.end <= outer.end for outer in ternaries):
                flagged[inner.start] = inner

        if_start_re = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf)\b", re.IGNORECASE)
        then_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
        for idx, line in enumerate(context.lines):
            if not if_start_re.match(line):
                continue
            end_idx = idx
            while end_idx < len(context.lines) and not then_re.search(context.lines[end_idx]):
                end_idx += 1
            if end_idx >= len(context.lines):
                continue
            for ternary in ternaries:
                if idx <= ternary.line <= end_idx:
                    flagged[ternary.start] = ternary

        storage = DiagnosticStorage(context.path)
        for span in sorted(flagged.values(), key=lambda item: item.start):
            storage.add_range(
                code=self.code,
                line=span.line,
                character=span.col,
                end_line=span.end_line,
                end_character=span.end_col,
                severity=Severity.WARNING,
                message="Не рекомендуется использовать вложенный тернарный оператор",
            )
        return storage.diagnostics


class MagicDateRule(BsllsDiagnosticRule):
    code = "BSL047"
    _authorized = {"00010101", "00010101000000", "000101010000"}
    _date_literal_re = re.compile(r"'([^']*)'")
    _string_literal_re = re.compile(r'"([0-9]{8}|[0-9]{14})"')

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if line.lstrip().startswith("//"):
                continue
            code_part = line.split("//", 1)[0]
            for regex, is_string in (
                (self._date_literal_re, False),
                (self._string_literal_re, True),
            ):
                for match in regex.finditer(code_part):
                    value = match.group(1)
                    if self._line_prefix_skips(line, match.start(), value, is_string):
                        continue
                    storage.add_match(
                        code=self.code,
                        line=idx,
                        start=match.start(),
                        end=match.end(),
                        severity=Severity.INFORMATION,
                        message=(
                            "Создайте переменную с понятным названием, присвойте ей "
                            f'значение "{match.group(0)}" и используйте эту константу '
                            "вместо магической даты."
                        ),
                    )
        return storage.diagnostics

    @classmethod
    def _valid_date(cls, value: str) -> bool:
        try:
            year = int(value[:4].lstrip("0") or "0")
            month = int(value[4:6])
            day = int(value[6:8])
        except ValueError:
            return False
        if year < 1 or year > 9999 or month < 1 or month > 12 or day < 1 or day > 31:
            return False
        if len(value) == 8:
            return True
        try:
            hour = int(value[8:10])
            minute = int(value[10:12])
            second = int(value[12:14])
        except ValueError:
            return False
        return hour <= 24 and minute <= 60 and second <= 60

    @classmethod
    def _line_prefix_skips(cls, line: str, start: int, value: str, is_string: bool) -> bool:
        prefix = line[:start]
        code = line.split("//", 1)[0]
        if value in cls._authorized:
            return True
        digits = re.sub(r"\D", "", value)
        if digits in cls._authorized:
            return True
        if not is_string and len(digits) not in (8, 14):
            return True
        if re.search(r"\b(?:Возврат|Return)\b", prefix, re.IGNORECASE):
            return True
        if re.search(r"\b(?:Функция|Function|Процедура|Procedure)\b", prefix, re.IGNORECASE):
            return True
        if re.match(r"^\s*Структура\w*\.[\wА-Яа-яЁё]+\s*=\s*$", prefix, re.IGNORECASE):
            return True
        if re.search(r"\b(?:ФиксированнаяСтруктура|FixedStructure)\s*\(", line, re.IGNORECASE):
            return True
        if re.search(r"\b(?:Новый\s+)?(?:Структура|Structure|Соответствие|Map)\b", line, re.IGNORECASE):
            return True
        if re.search(r"\.(?:Вставить|Insert)\s*\(", prefix, re.IGNORECASE):
            return True
        if is_string and not cls._valid_date(value):
            return True
        if re.match(r"^\s*[\wА-Яа-яЁё.]+\s*=\s*$", prefix, re.IGNORECASE):
            suffix = line[start + len(value) + 2 :].split("//", 1)[0].strip()
            if suffix.startswith(";") or suffix == "":
                return True
        if re.match(
            r"^\s*[\wА-Яа-яЁё.]+\s*=\s*(?:Дата|Date)\s*\(\s*$",
            prefix,
            re.IGNORECASE,
        ):
            suffix = code[start + len(value) + 2 :].strip()
            if suffix.startswith(")"):
                tail = suffix[1:].strip()
                if tail.startswith(";") or tail == "":
                    return True
        return False


class UselessTernaryOperatorRule(BsllsDiagnosticRule):
    code = "BSL265"
    _boolean_operand_re = re.compile(r"\b(?:Истина|True|Ложь|False)\b", re.IGNORECASE | re.UNICODE)
    _comment_re = re.compile(r"^\s*//")

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for span in _ternary_spans(context):
            line_text = context.lines[span.line] if span.line < len(context.lines) else ""
            if self._comment_re.match(line_text):
                continue
            ternary_text = context.content[span.start : span.end]
            if self._boolean_operand_re.search(ternary_text):
                storage.add_range(
                    code=self.code,
                    line=span.line,
                    character=span.col,
                    end_line=span.end_line,
                    end_character=span.end_col,
                    severity=Severity.INFORMATION,
                    message="Бесполезный тернарный оператор",
                )
        return storage.diagnostics
