from __future__ import annotations

import re
from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo, RegionInfo

_BSL029_MAGIC_NUMBER_RE = re.compile(
    r"(?<![\"'\w.])"
    r"(?:-?(?:[2-9]\d*|\d{2,})(?:\.\d+)?|-?1\.\d*[1-9]\d*|-?0\.(?:0*[1-9]\d*))"
    r"(?![\w.\"])",
)
_BSL029_CONTAINER_ASSIGN_RE = re.compile(
    r"^\s*(?P<name>[\w.]+)\s*=\s*(?:Новый|New)\s+"
    r"(?P<type>Структура|Structure|ФиксированнаяСтруктура|FixedStructure|Соответствие|Map)\b",
    re.IGNORECASE,
)
_BSL029_INSERT_CALL_RE = re.compile(
    r"(?P<receiver>[\w.]+)\s*\.\s*(?:Вставить|Insert)\s*\(",
    re.IGNORECASE,
)
_BSL029_VAR_ASSIGN_RE = re.compile(r"^\s*(?:Перем|Var)\s+\w+\s*=", re.IGNORECASE)
_BSL029_SIMPLE_NUMBER_RE = re.compile(r"\s*-?[0-9]+(?:\.[0-9]+)?\s*")
_BSL029_CONTAINER_NEW_RE = re.compile(
    r"\b(?:Новый|New)\s+(?:Структура|Structure|Соответствие|Map)\s*\([^)]*\)",
    re.IGNORECASE,
)
_BSL029_FIXED_CONTAINER_NEW_RE = re.compile(
    r"\b(?:Новый|New)\s+(?:ФиксированнаяСтруктура|FixedStructure)\s*\([^)]*\)",
    re.IGNORECASE,
)
_BSL029_TO_PREFIX_RE = re.compile(r"\b(?:По|To)\s*$", re.IGNORECASE)
_BSL029_FOR_PREFIX_RE = re.compile(r"\b(?:Для|For)\s+\w+\s*=\s*$", re.IGNORECASE)
_BSL029_TO_SUFFIX_RE = re.compile(r"\s*(?:По|To)\b", re.IGNORECASE)
_BSL029_SINGLE_QUOTED_STRING_RE = re.compile(r"'[^'\n]*(?:''[^'\n]*)*'")
_BSL029_DOUBLE_QUOTED_STRING_RE = re.compile(r'"[^"\n]*(?:""[^"\n]*)*"')


def _mask_unclosed_double_quoted_tail(text: str) -> str:
    pos = 0
    while pos < len(text):
        if text[pos] != '"':
            pos += 1
            continue
        end = pos + 1
        while end < len(text):
            if text[end] == '"':
                if end + 1 < len(text) and text[end + 1] == '"':
                    end += 2
                    continue
                break
            end += 1
        if end >= len(text):
            return text[:pos] + '"' + (" " * max(0, len(text) - pos - 1))
        pos = end + 1
    return text


@dataclass(frozen=True, slots=True)
class ProcedureModel:
    path: str
    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    header_col: int
    params: tuple[str, ...]
    optional_count: int
    optional_params: frozenset[str]
    params_start_idx: int | None = None
    params_start_character: int | None = None
    params_end_idx: int | None = None
    params_end_character: int | None = None

    @classmethod
    def from_proc_info(cls, path: str, proc: ProcInfo) -> ProcedureModel:
        return cls(
            path=path,
            name=proc.name,
            kind=proc.kind,
            start_idx=proc.start_idx,
            end_idx=proc.end_idx,
            is_export=proc.is_export,
            header_col=proc.header_col,
            params=tuple(proc.params),
            optional_count=proc.optional_count,
            optional_params=proc.optional_params,
            params_start_idx=proc.params_start_idx,
            params_start_character=proc.params_start_character,
            params_end_idx=proc.params_end_idx,
            params_end_character=proc.params_end_character,
        )

    def _param_list_range(self, lines: list[str]) -> tuple[int, int, int, int]:
        if (
            self.params_start_idx is not None
            and self.params_start_character is not None
            and self.params_end_idx is not None
            and self.params_end_character is not None
        ):
            return (
                self.params_start_idx + 1,
                self.params_start_character,
                self.params_end_idx + 1,
                self.params_end_character,
            )
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        character = line_text.find("(")
        if character < 0:
            character = self.header_col
        else:
            character += 1
        end_character = line_text.rfind(")")
        if end_character < character:
            end_character = len(line_text.rstrip())
        return self.start_idx + 1, character, self.start_idx + 1, end_character

    def validate_param_limit(self, lines: list[str], *, max_params: int) -> list[Diagnostic]:
        total = len(self.params)
        if total <= max_params:
            return []
        line, character, end_line, end_character = self._param_list_range(lines)
        return [
            Diagnostic(
                file=self.path,
                line=line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                severity=Severity.INFORMATION,
                code="BSL031",
                message=f"Уменьшите количество параметров c {total} до допустимого {max_params}",
            )
        ]

    def validate_optional_param_limit(
        self, lines: list[str], *, max_optional_params: int
    ) -> list[Diagnostic]:
        if self.optional_count <= max_optional_params:
            return []
        line, character, end_line, end_character = self._param_list_range(lines)
        return [
            Diagnostic(
                file=self.path,
                line=line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                severity=Severity.INFORMATION,
                code="BSL015",
                message=(
                    f"Уменьшите количество необязательных параметров c {self.optional_count} "
                    f"до допустимого {max_optional_params}"
                ),
            )
        ]

    def validate_method_size(
        self,
        lines: list[str],
        *,
        max_proc_lines: int,
        mask_strings_and_comments_for_counter,
        proc_name_span,
    ) -> list[Diagnostic]:
        body_start_idx = self.start_idx + 1
        header_balance = 0
        for idx in range(self.start_idx, min(self.end_idx, len(lines))):
            header_part = mask_strings_and_comments_for_counter(lines[idx], False)
            header_balance += header_part.count("(") - header_part.count(")")
            if header_balance <= 0 and ")" in header_part:
                body_start_idx = idx + 1
                break
        first_body: int | None = None
        last_body: int | None = None
        for idx in range(body_start_idx, min(self.end_idx, len(lines))):
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                continue
            if first_body is None:
                first_body = idx
            last_body = idx
        length = 0 if first_body is None or last_body is None else last_body - first_body
        if length <= max_proc_lines:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL002",
                message=(
                    f'Длина метода "{self.name}" равна {length}, '
                    f"что больше установленного лимита в {max_proc_lines} строк"
                ),
            )
        ]

    def validate_procedure_return_value(
        self,
        lines: list[str],
        *,
        return_value_re,
        proc_header_re,
    ) -> list[Diagnostic]:
        if self.kind != "procedure":
            return []
        header_line = lines[self.start_idx]
        match = proc_header_re.search(header_line)
        if not match:
            return []
        kw = match.group("kw").lower()
        if kw not in ("процедура", "procedure"):
            return []
        for idx in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[idx]
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            if return_value_re.match(line):
                return [
                    Diagnostic(
                        file=self.path,
                        line=idx + 1,
                        character=len(line) - len(stripped),
                        end_line=idx + 1,
                        end_character=len(line.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL064",
                        message=(
                            "Процедура contains 'Возврат <value>' — "
                            "change the declaration to 'Функция'."
                        ),
                    )
                ]
        return []

    def validate_max_returns(
        self, lines: list[str], *, max_returns: int, return_re
    ) -> list[Diagnostic]:
        proc_body = "\n".join(lines[self.start_idx : self.end_idx + 1])
        returns = list(return_re.finditer(proc_body))
        if len(returns) <= max_returns:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        kind_ru = "Функция" if self.kind == "function" else "Процедура"
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(line_text),
                severity=Severity.WARNING,
                code="BSL008",
                message=(
                    f"{kind_ru} '{self.name}' содержит {len(returns)} операторов Возврат "
                    f"(максимум {max_returns})"
                ),
            )
        ]

    def validate_function_has_return(
        self,
        lines: list[str],
        *,
        return_re,
        proc_name_span,
    ) -> list[Diagnostic]:
        if self.kind != "function":
            return []
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        has_return = any(return_re.match(line) for line in body_lines)
        if has_return:
            return []
        line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col or len(line_text),
                severity=Severity.ERROR,
                code="BSL032",
                message='Функция не содержит "Возврат"',
            )
        ]

    def validate_empty_export_method(
        self,
        lines: list[str],
        *,
        blank_or_comment_re,
    ) -> list[Diagnostic]:
        if not self.is_export:
            return []
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        has_code = any(line.strip() and not blank_or_comment_re.match(line) for line in body_lines)
        if has_code:
            return []
        header = lines[self.start_idx] if self.start_idx < len(lines) else ""
        kind_ru = "Функция" if self.kind == "function" else "Процедура"
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=self.header_col,
                end_line=self.start_idx + 1,
                end_character=len(header),
                severity=Severity.WARNING,
                code="BSL042",
                message=f"Экспортная {kind_ru.lower()} '{self.name}' не содержит тела",
            )
        ]

    def validate_non_export_in_api_regions(
        self,
        lines: list[str],
        *,
        regions: list[RegionInfo],
        api_region_names: set[str],
        proc_name_span,
    ) -> list[Diagnostic]:
        if self.is_export:
            return []
        for region in regions:
            if region.name.lower() not in api_region_names:
                continue
            if not (region.start_idx < self.start_idx < region.end_idx):
                continue
            line_text = lines[self.start_idx] if self.start_idx < len(lines) else ""
            start_char, end_char = proc_name_span(lines, self._to_proc_info())
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=start_char,
                    end_line=self.start_idx + 1,
                    end_character=end_char or len(line_text),
                    severity=Severity.WARNING,
                    code="BSL003",
                    message=(
                        f'Переместите неэкспортный метод "{self.name}" из области "{region.name}"'
                    ),
                )
            ]
        return []

    def validate_missing_export_comment(
        self,
        lines: list[str],
        *,
        compiler_directive_re,
        bsl215_comment_line_re,
    ) -> list[Diagnostic]:
        block_end = self.start_idx - 1
        while block_end >= 0 and compiler_directive_re.match(lines[block_end]):
            block_end -= 1
        if block_end < 0 or not bsl215_comment_line_re.match(lines[block_end]):
            return []
        block_start = block_end
        while block_start > 0 and bsl215_comment_line_re.match(lines[block_start - 1]):
            block_start -= 1
        comment_block = lines[block_start : block_end + 1]
        if any(re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE) for cl in comment_block):
            return []
        if len(comment_block) == 1:
            text = re.sub(r"^\s*//\s*", "", comment_block[0]).strip()
            if re.match(r"^(?:Конец|End)\b", text, re.IGNORECASE):
                return []

        returns_section_start = None
        for ci, cl in enumerate(comment_block):
            if re.match(
                r"^\s*//\s*(?:Возвращаемое\s+значение|Returns)\s*:?\s*$",
                cl,
                re.IGNORECASE,
            ):
                returns_section_start = ci
                break

        has_valid_return_entry = False
        if returns_section_start is not None:
            return_section_lines = comment_block[returns_section_start + 1 :]
            has_struct_fields = any(
                re.match(r"^\s*//\s+\*\s+\S", rcl) for rcl in return_section_lines
            )

            def has_bslls_return_type_description(text: str) -> bool:
                type_text = text.split(" - ", 1)[0].strip()
                if not type_text or "\t" in type_text:
                    return False
                type_text = type_text.rstrip()
                if type_text.endswith(","):
                    return True
                if type_text.endswith(":"):
                    type_text = type_text[:-1].rstrip()
                elif type_text.rstrip() != type_text.rstrip(".;"):
                    return False
                if re.fullmatch(
                    r"(?:Массив|Array)\s+(?:Из|Of)\s+(?:Структура|Structure)",
                    type_text,
                    re.IGNORECASE,
                ):
                    return True
                if re.search(r"\b(?:или|or|элементов|element)\b", type_text, re.IGNORECASE):
                    return False
                if re.search(r"[A-Za-zА-ЯЁа-яё0-9_]\s+[A-Za-zА-ЯЁа-яё0-9_]", type_text):
                    return False
                type_name = r"[A-ZА-ЯЁ][\w]*(?:\.[A-ZА-ЯЁ]\w*)*"
                return bool(re.fullmatch(rf"{type_name}(?:\s*,\s*{type_name})*", type_text))

            for cl in return_section_lines:
                stripped = cl.strip()
                if stripped == "//":
                    break
                if re.match(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", cl, re.IGNORECASE):
                    break
                if re.match(r"^\s*//\s*(?:См\.|See)\s+\S", cl, re.IGNORECASE):
                    has_valid_return_entry = True
                    break
                entry = re.match(r"^\s*//[ ]{1,4}(?P<text>\S.*)$", cl)
                if not entry:
                    continue
                text = entry.group("text").strip()
                if text.startswith("*"):
                    if has_struct_fields:
                        continue
                    has_valid_return_entry = True
                    break
                first_part = text.split("-", 1)[0].strip()
                if text.startswith("-") and text.rstrip().endswith("."):
                    continue
                if "—" in text and "-" not in text:
                    continue
                if (
                    has_struct_fields
                    and ":" not in first_part
                    and "-" in text
                    and not text.endswith(":")
                ):
                    continue
                if not has_bslls_return_type_description(text):
                    continue
                has_valid_return_entry = True
                break

        header_line = lines[self.start_idx] if self.start_idx < len(lines) else ""
        try:
            col = header_line.index(self.name)
        except ValueError:
            col = 0
        if self.kind == "procedure" and returns_section_start is not None:
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=col,
                    end_line=self.start_idx + 1,
                    end_character=col + len(self.name),
                    severity=Severity.WARNING,
                    code="BSL065",
                    message="Удалите описание возвращаемого значения для процедуры",
                )
            ]
        if self.kind == "function" and (
            returns_section_start is None or not has_valid_return_entry
        ):
            return [
                Diagnostic(
                    file=self.path,
                    line=self.start_idx + 1,
                    character=col,
                    end_line=self.start_idx + 1,
                    end_character=col + len(self.name),
                    severity=Severity.WARNING,
                    code="BSL065",
                    message="Добавьте описание возвращаемого значения функции",
                )
            ]
        return []

    def validate_unused_parameters(
        self,
        lines: list[str],
        *,
        used_casefold: set[str] | None,
        skip_standard_params: set[str] | frozenset[str],
        is_typical_client_command_handler,
        is_client_notify_completion_export_handler,
    ) -> list[Diagnostic]:
        if not self.params or self.is_export:
            return []
        header_line = lines[self.start_idx]
        body_lines = lines[self.start_idx + 1 : self.end_idx]
        body_text = "\n".join(body_lines)
        header_lineno = self.start_idx + 1
        diags: list[Diagnostic] = []

        for param_name in self.params:
            if not param_name:
                continue
            if param_name.startswith("_"):
                continue
            if not param_name.isidentifier():
                continue
            if param_name.casefold() in skip_standard_params:
                continue
            if param_name in self.optional_params:
                continue
            proc_info = self._to_proc_info()
            if param_name.casefold() in ("параметры", "parameters") and (
                is_typical_client_command_handler(proc_info, lines)
                or is_client_notify_completion_export_handler(proc_info, lines)
            ):
                continue
            if used_casefold is not None:
                is_used = param_name.casefold() in used_casefold
            else:
                is_used = bool(
                    re.search(
                        r"\b" + re.escape(param_name) + r"\b",
                        body_text,
                        re.IGNORECASE,
                    )
                )
            if is_used:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=header_lineno,
                    character=self.header_col,
                    end_line=header_lineno,
                    end_character=len(header_line.rstrip()),
                    severity=Severity.WARNING,
                    code="BSL062",
                    message=f"Параметр '{param_name}' не используется в теле метода",
                )
            )
        return diags

    def validate_cognitive_complexity(
        self,
        *,
        cognitive_complexity: int,
        max_cognitive_complexity: int,
        proc_name_span,
        lines: list[str],
    ) -> list[Diagnostic]:
        if cognitive_complexity <= max_cognitive_complexity:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL011",
                message=(
                    f'Уменьшите когнитивную сложность "{self.name}" '
                    f"с {cognitive_complexity} до {max_cognitive_complexity}"
                ),
            )
        ]

    def validate_mccabe_complexity(
        self,
        *,
        mccabe_complexity: int,
        max_mccabe_complexity: int,
        proc_name_span,
        lines: list[str],
    ) -> list[Diagnostic]:
        if mccabe_complexity <= max_mccabe_complexity:
            return []
        start_col, end_col = proc_name_span(lines, self._to_proc_info())
        return [
            Diagnostic(
                file=self.path,
                line=self.start_idx + 1,
                character=start_col,
                end_line=self.start_idx + 1,
                end_character=end_col,
                severity=Severity.WARNING,
                code="BSL019",
                message=(
                    f'Уменьшите цикломатическую сложность "{self.name}" '
                    f"с {mccabe_complexity} до {max_mccabe_complexity}"
                ),
            )
        ]

    def validate_missing_try_catch(
        self,
        lines: list[str],
        *,
        try_block_re,
        try_close_re,
        risky_call_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        in_try = False
        for i in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[i]
            if try_block_re.match(line):
                in_try = True
            elif re.match(r"^\s*(?:Исключение|Except)\b", line, re.IGNORECASE) and in_try:
                j = i + 1
                while j < min(self.end_idx, len(lines)):
                    stripped = lines[j].strip()
                    if not stripped or stripped.startswith("//"):
                        j += 1
                        continue
                    break
                if j < len(lines) and try_close_re.match(lines[j]):
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=len(line) - len(line.lstrip()),
                            end_line=i + 1,
                            end_character=len(line.rstrip()),
                            severity=Severity.ERROR,
                            code="BSL028",
                            message='Отсутствует код в блоке "Исключение"',
                        )
                    )
            elif try_close_re.match(line) and in_try:
                in_try = False
            if in_try or not risky_call_re.match(line):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=i + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=i + 1,
                    end_character=len(line),
                    severity=Severity.INFORMATION,
                    code="BSL028",
                    message="Потенциально опасный вызов вне блока Попытка/Исключение",
                )
            )
        return diags

    def validate_query_in_loop(
        self,
        lines: list[str],
        *,
        loop_lines: set[int] | None,
        query_execute_re,
        loop_open_re,
        loop_close_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        loop_depth = 0
        for i in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[i]
            if loop_lines is not None:
                if i not in loop_lines:
                    continue
                m = query_execute_re.search(line)
                if m and not line.strip().startswith("//"):
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=m.start(),
                            end_line=i + 1,
                            end_character=m.end(),
                            severity=Severity.WARNING,
                            code="BSL033",
                            message=(
                                "Query.Выполнить() inside a loop causes N database "
                                "round-trips. Move the query outside the loop."
                            ),
                        )
                    )
                continue
            if loop_open_re.match(line):
                loop_depth += 1
            elif loop_close_re.match(line):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth > 0:
                m = query_execute_re.search(line)
                if m and not line.strip().startswith("//"):
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=i + 1,
                            character=m.start(),
                            end_line=i + 1,
                            end_character=m.end(),
                            severity=Severity.WARNING,
                            code="BSL033",
                            message=(
                                "Query.Выполнить() inside a loop causes N database "
                                "round-trips. Move the query outside the loop."
                            ),
                        )
                    )
        return diags

    def validate_magic_numbers(
        self,
        lines: list[str],
        *,
        snapshot,
        any_digit_re,
        simple_assign_re,
        ternary_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked_lines = snapshot.masked_lines if snapshot is not None else None
        code_lines_wo_comments = (
            snapshot.code_lines_without_comments if snapshot is not None else None
        )
        container_vars: dict[str, str] = {}

        def split_top_level_args(text: str) -> list[tuple[int, int, str]]:
            args: list[tuple[int, int, str]] = []
            start = 0
            depth = 0
            in_string = False
            pos = 0
            while pos < len(text):
                char = text[pos]
                if in_string:
                    if char == '"':
                        if pos + 1 < len(text) and text[pos + 1] == '"':
                            pos += 2
                            continue
                        in_string = False
                    pos += 1
                    continue
                if char == '"':
                    in_string = True
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth = max(0, depth - 1)
                elif char == "," and depth == 0:
                    args.append((start, pos, text[start:pos]))
                    start = pos + 1
                pos += 1
            args.append((start, len(text), text[start:]))
            return args

        def numeric_is_simple_ternary_branch(code: str, start: int, end: int) -> bool:
            qmark = code.rfind("?", 0, start)
            if qmark < 0:
                return False
            open_paren = code.find("(", qmark, start + 1)
            if open_paren < 0:
                return False
            close_paren = code.find(")", end)
            if close_paren < 0:
                return False
            args = split_top_level_args(code[open_paren + 1 : close_paren])
            if len(args) != 3:
                return False
            relative_start = start - open_paren - 1
            relative_end = end - open_paren - 1
            for arg_start, arg_end, arg_text in args[1:]:
                if not (arg_start <= relative_start and relative_end <= arg_end):
                    continue
                return _BSL029_SIMPLE_NUMBER_RE.fullmatch(arg_text) is not None
            return False

        def numeric_is_inside_known_container_insert(code: str, start: int, end: int) -> bool:
            call_match: re.Match[str] | None = None
            for candidate in _BSL029_INSERT_CALL_RE.finditer(code):
                if candidate.end() <= start:
                    call_match = candidate
                else:
                    break
            if call_match is None:
                return False
            receiver_type = container_vars.get(call_match.group("receiver").casefold())
            if receiver_type is None:
                return False
            close_paren = code.find(")", max(end, call_match.end()))
            if close_paren < 0:
                return False
            args = split_top_level_args(code[call_match.end() : close_paren])
            relative_start = start - call_match.end()
            relative_end = end - call_match.end()
            for arg_index, (arg_start, arg_end, arg_text) in enumerate(args):
                if not (arg_start <= relative_start and relative_end <= arg_end):
                    continue
                if receiver_type in {"соответствие", "map"}:
                    return True
                if arg_index == 1:
                    return (
                        re.fullmatch(
                            r"\s*-?(?:\d+(?:\.\d+)?|0\.\d+)\s*",
                            arg_text,
                        )
                        is not None
                    )
                return False
            return False

        query_line_indices: set[int] = set()
        if snapshot is not None:
            for block in getattr(snapshot, "query_text_blocks", []) or []:
                for query_line in getattr(block, "content_lines", []) or []:
                    query_line_indices.add(int(query_line.line_no) - 1)

        for i in range(self.start_idx + 1, min(self.end_idx, len(lines))):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if i in query_line_indices:
                continue
            if stripped.startswith("|"):
                continue
            if _BSL029_VAR_ASSIGN_RE.match(line):
                continue
            code_part = (
                code_lines_wo_comments[i]
                if code_lines_wo_comments is not None
                else line.split("//")[0]
            )
            code_part = (
                masked_lines[i]
                if masked_lines is not None
                else _BSL029_DOUBLE_QUOTED_STRING_RE.sub(
                    lambda m: '"' + (" " * max(0, len(m.group(0)) - 2)) + '"',
                    code_part,
                )
            )
            code_part = _BSL029_SINGLE_QUOTED_STRING_RE.sub(
                lambda m: "'" + (" " * max(0, len(m.group(0)) - 2)) + "'",
                _mask_unclosed_double_quoted_tail(code_part),
            )
            comment_pos = code_part.find("//")
            if comment_pos >= 0:
                code_part = code_part[:comment_pos]
            assignment = _BSL029_CONTAINER_ASSIGN_RE.match(code_part)
            if assignment is not None:
                container_vars[assignment.group("name").casefold()] = assignment.group(
                    "type"
                ).casefold()
            if not any_digit_re.search(line):
                continue
            if simple_assign_re.match(code_part):
                continue
            code_part = _BSL029_CONTAINER_NEW_RE.sub(
                "Новый Структура()",
                code_part,
            )
            code_part = _BSL029_FIXED_CONTAINER_NEW_RE.sub(
                "Новый ФиксированнаяСтруктура()",
                code_part,
            )
            for m in _BSL029_MAGIC_NUMBER_RE.finditer(code_part):
                sign_pos = m.start() - 1
                while sign_pos >= 0 and code_part[sign_pos] in " \t":
                    sign_pos -= 1
                if m.group().startswith("-"):
                    continue
                if sign_pos >= 0 and code_part[sign_pos] == "-":
                    before_sign = sign_pos - 1
                    while before_sign >= 0 and code_part[before_sign] in " \t":
                        before_sign -= 1
                    if before_sign < 0 or code_part[before_sign] in "(,=":
                        continue
                prefix = code_part[: m.start()]
                if _BSL029_TO_PREFIX_RE.search(prefix):
                    continue
                if _BSL029_FOR_PREFIX_RE.search(prefix):
                    suffix = code_part[m.end() :]
                    if _BSL029_TO_SUFFIX_RE.match(suffix):
                        continue
                if numeric_is_simple_ternary_branch(code_part, m.start(), m.end()):
                    continue
                if numeric_is_inside_known_container_insert(code_part, m.start(), m.end()):
                    continue
                lpos = m.start() - 1
                while lpos >= 0 and code_part[lpos] in " \t":
                    lpos -= 1
                rpos = m.end()
                while rpos < len(code_part) and code_part[rpos] in " \t":
                    rpos += 1
                if (
                    lpos >= 0
                    and rpos < len(code_part)
                    and code_part[lpos] == "["
                    and code_part[rpos] == "]"
                ):
                    continue
                diags.append(
                    Diagnostic(
                        file=self.path,
                        line=i + 1,
                        character=m.start(),
                        end_line=i + 1,
                        end_character=m.end(),
                        severity=Severity.INFORMATION,
                        code="BSL029",
                        message=(
                            "Создайте константу с понятным названием, "
                            f'присвойте ей значение "{m.group()}" и используйте '
                            "эту константу вместо магического числа."
                        ),
                    )
                )
        return diags

    def _to_proc_info(self) -> ProcInfo:
        return ProcInfo(
            name=self.name,
            kind=self.kind,
            start_idx=self.start_idx,
            end_idx=self.end_idx,
            is_export=self.is_export,
            params=list(self.params),
            val_params=[],
            optional_count=self.optional_count,
            header_col=self.header_col,
            optional_params=self.optional_params,
            params_start_idx=self.params_start_idx,
            params_start_character=self.params_start_character,
            params_end_idx=self.params_end_idx,
            params_end_character=self.params_end_character,
        )
