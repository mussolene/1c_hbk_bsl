from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.document_snapshot import ProcInfo


@dataclass(frozen=True, slots=True)
class ModuleModel:
    path: str

    def validate_hardcoded_credentials(self, lines: list[str], *, credentials_re) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = credentials_re.search(line)
            if not m:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.ERROR,
                    code="BSL012",
                    message=f"Possible hardcoded credential: {m.group()!r}",
                )
            )
        return diags

    def validate_commented_code(
        self,
        lines: list[str],
        *,
        commented_code_re,
        min_commented_code_block: int,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        consecutive = 0
        start_line = 0
        in_query_comment = False
        for idx, line in enumerate(lines):
            comment_text = ""
            if line.lstrip().startswith("//"):
                comment_text = line.lstrip()[2:].strip()
            is_query_comment = bool(
                comment_text
                and re.match(
                    r"^(?:ВЫБРАТЬ|SELECT|ИЗ|FROM|ГДЕ|WHERE|ПОМЕСТИТЬ|КАК|И\b|ИЛИ\b)",
                    comment_text,
                    re.IGNORECASE,
                )
            )
            if commented_code_re.match(line) or (in_query_comment and line.lstrip().startswith("//")):
                if consecutive == 0:
                    start_line = idx
                consecutive += 1
                in_query_comment = in_query_comment or is_query_comment
            else:
                if consecutive >= min_commented_code_block:
                    report_start = start_line
                    while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                        report_start -= 1
                    diags.append(
                        Diagnostic(
                            file=self.path,
                            line=report_start + 1,
                            character=1,
                            end_line=idx,
                            end_character=0,
                            severity=Severity.INFORMATION,
                            code="BSL013",
                            message="Программные модули не должны иметь закомментированных фрагментов кода",
                        )
                    )
                consecutive = 0
                in_query_comment = False
        if consecutive >= min_commented_code_block:
            report_start = start_line
            while report_start > 0 and lines[report_start - 1].lstrip().startswith("//"):
                report_start -= 1
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=report_start + 1,
                    character=1,
                    end_line=len(lines),
                    end_character=0,
                    severity=Severity.INFORMATION,
                    code="BSL013",
                    message="Программные модули не должны иметь закомментированных фрагментов кода",
                )
            )
        return diags

    def validate_line_too_long(
        self,
        lines: list[str],
        *,
        max_line_length: int,
        snapshot,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        reported_lengths: list[int] | None = None
        if snapshot is not None:
            reported_lengths = []
            raw_line_source: list[str]
            if "\r" not in snapshot.content and Path(self.path).is_file():
                try:
                    raw_line_source = [
                        raw.decode("utf-8", errors="ignore")
                        for raw in Path(self.path).read_bytes().splitlines(True)
                    ]
                except OSError:
                    raw_line_source = snapshot.content.splitlines(True)
                if len(raw_line_source) != len(snapshot.content.splitlines()):
                    raw_line_source = snapshot.content.splitlines(True)
            else:
                raw_line_source = snapshot.content.splitlines(True)
            for raw in raw_line_source:
                raw_no_lf = raw.rstrip("\n")
                raw_no_eol = raw_no_lf.rstrip("\r")
                if raw_no_lf.endswith("\r"):
                    visible_len = len(raw_no_eol.rstrip("\t"))
                else:
                    visible_len = len(raw_no_eol.rstrip())
                reported_lengths.append(visible_len)
        for idx, line in enumerate(lines):
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
            reported_length = (
                reported_lengths[idx]
                if reported_lengths is not None and idx < len(reported_lengths)
                else length
            )
            if reported_length <= max_line_length:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=0,
                    end_line=idx + 1,
                    end_character=length,
                    severity=Severity.INFORMATION,
                    code="BSL014",
                    message=(
                        f"Длина строки {reported_length} превышает максимально допустимую "
                        f"{max_line_length}"
                    ),
                )
            )
        return diags

    def validate_deprecated_warning(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        deprecated_message_re,
        proc_containing_line,
        is_typical_client_command_handler,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = deprecated_message_re.match(line)
            if not m:
                continue
            proc = proc_containing_line(procs, idx)
            if proc is not None and is_typical_client_command_handler(proc, lines):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.WARNING,
                    code="BSL022",
                    message=(
                        "Предупреждение()/Warning() is a modal dialog deprecated in managed UI. "
                        "Use ПоказатьПредупреждение() / ShowMessageBox() instead."
                    ),
                )
            )
        return diags

    def validate_useless_condition_regex_fallback(
        self,
        lines: list[str],
        *,
        if_literal_re,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            if not if_literal_re.match(line):
                continue
            literal_m = re.search(r"\b(Истина|True|Ложь|False)\b", line, re.IGNORECASE)
            literal = literal_m.group(1) if literal_m else "literal"
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=len(line) - len(line.lstrip()),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.WARNING,
                    code="BSL052",
                    message=(
                        f"Condition is always '{literal}' — "
                        "this If branch either always or never executes."
                    ),
                )
            )
        return diags

    def validate_module_level_export_variables(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        var_module_export_re,
        clean_lines: list[str],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)
        for idx, line in enumerate(lines):
            if idx in inside:
                continue
            m = var_module_export_re.match(clean_lines[idx])
            if not m:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start("names"),
                    end_line=idx + 1,
                    end_character=len(line),
                    severity=Severity.WARNING,
                    code="BSL054",
                    message="Не рекомендуется использовать экспортные переменные. Это может стать источником трудновоспроизводимых ошибок",
                )
            )
        return diags

    def validate_module_variables_description(
        self,
        lines: list[str],
        *,
        procs: list[ProcInfo],
        var_module_re,
        clean_lines: list[str],
        has_preceding_description,
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        inside: set[int] = set()
        for proc in procs:
            for i in range(proc.start_idx, proc.end_idx + 1):
                inside.add(i)
        for idx, _line in enumerate(lines):
            if idx in inside:
                continue
            code_part = clean_lines[idx].rstrip()
            if not code_part.strip():
                continue
            m = var_module_re.match(code_part)
            if not m:
                continue
            if has_preceding_description(lines, idx):
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start("names"),
                    end_line=idx + 1,
                    end_character=m.end("names"),
                    severity=Severity.INFORMATION,
                    code="BSL219",
                    message="Добавьте описание переменной",
                )
            )
        return diags

    def validate_self_assign_regex_fallback(
        self, lines: list[str], *, self_assign_re
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for idx, line in enumerate(lines):
            if line.strip().startswith("//"):
                continue
            m = self_assign_re.search(line)
            if not m:
                continue
            diags.append(
                Diagnostic(
                    file=self.path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=Severity.ERROR,
                    code="BSL009",
                    message="Удалите бесполезное присваивание переменной самой себе",
                )
            )
        return diags
