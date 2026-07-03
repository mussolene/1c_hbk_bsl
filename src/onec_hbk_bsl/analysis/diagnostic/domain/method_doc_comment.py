from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.document_snapshot import ProcInfo


_RE_COMPILER_DIRECTIVE = re.compile(r"^\s*&\w+\s*$")
_RE_COMMENT_LINE = re.compile(r"^\s*//")
_RE_PARAMS_SECTION = re.compile(r"^\s*//\s*(?:Параметры|Parameters)\s*:?\s*$", re.IGNORECASE)
_RE_PARAM_ENTRY = re.compile(r"^\s*//\s{0,4}(\w+)\s*-", re.UNICODE)
_RE_SEPARATOR = re.compile(r"^\s*/{10,}\s*$")
_RE_SEE_LINK = re.compile(r"^\s*//\s*(?:См\.|See)\s+\S", re.IGNORECASE)
_RE_SECTION_HEADER = re.compile(r"^\s*//\s*\w[\w\s]*:\s*$")
_RE_STRUCTURE_COMPOSITION = re.compile(
    r"^\s*//\s*(?:Состав\s+структуры)\s*:?\s*$",
    re.IGNORECASE,
)
_RE_LEGACY_RETURN_HEADER = re.compile(
    r"^\s*//\s*ВозвращаемоеЗначение\s*:?\s*$",
    re.IGNORECASE,
)
_RE_END_TEXT = re.compile(r"^(?:Конец|End)\b", re.IGNORECASE)
_RE_FIELD_ENTRY = re.compile(r"^\s*//\s+\*")
_RE_RAW_PARAM_ENTRY = re.compile(
    r"^\s*//(?P<indent>[ \t]{0,8})(?P<name>\w+)\s*-\s*(?P<tail>.*?)\s*$",
    re.UNICODE,
)
_RE_REFERENCE = re.compile(
    r"^\s*(?:см\.|see)\s+([A-Za-zА-ЯЁа-яё_]\w*(?:\.\w+)+)[.;]?\s*$",
    re.IGNORECASE,
)
_RE_EXAMPLE_SEE = re.compile(r"\(\s*пример\s+см\.", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MethodDocParamEntry:
    name: str
    line_idx: int
    tail: str
    has_valid_description: bool
    stale_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MethodDocComment:
    block_start_idx: int
    block_end_idx: int
    lines: tuple[str, ...]
    has_params_section: bool
    params_section_offset: int | None
    documented_entries: tuple[MethodDocParamEntry, ...]
    empty_description_names: frozenset[str]
    stale_reference_entries: tuple[str, ...]
    is_ignored_for_method_contract: bool
    force_all_params_missing: bool

    @property
    def has_method_documentation(self) -> bool:
        return not self.is_ignored_for_method_contract and any(
            line.strip().startswith("//") for line in self.lines
        )

    @property
    def documented_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.documented_entries)


def build_method_doc_comment(
    lines: list[str],
    proc: ProcInfo,
    *,
    line_comment_nodes: list[Any] | None = None,
    comment_lines_by_idx: dict[int, str] | None = None,
    skip_blank_lines: bool = False,
    legacy_doc_path: bool = False,
) -> MethodDocComment | None:
    if comment_lines_by_idx is None:
        comment_lines_by_idx = build_line_comment_text_index(line_comment_nodes, lines)

    def is_comment_line(idx: int) -> bool:
        if comment_lines_by_idx is not None:
            return idx in comment_lines_by_idx
        return _RE_COMMENT_LINE.match(lines[idx]) is not None

    def comment_line(idx: int) -> str:
        if comment_lines_by_idx is not None:
            return comment_lines_by_idx[idx]
        return lines[idx]

    block_end = proc.start_idx - 1
    while block_end >= 0 and (
        (skip_blank_lines and lines[block_end].strip() == "")
        or _RE_COMPILER_DIRECTIVE.match(lines[block_end])
    ):
        block_end -= 1
    if block_end < 0 or not is_comment_line(block_end):
        return None

    block_start = block_end
    while block_start > 0 and is_comment_line(block_start - 1):
        block_start -= 1

    block_lines = tuple(
        _normalize_legacy_comment(comment_line(idx)) if legacy_doc_path else comment_line(idx)
        for idx in range(block_start, block_end + 1)
    )
    return parse_method_doc_comment(
        block_start,
        block_end,
        block_lines,
        proc_params=tuple(proc.params),
        legacy_doc_path=legacy_doc_path,
    )


def parse_method_doc_comment(
    block_start_idx: int,
    block_end_idx: int,
    lines: tuple[str, ...],
    *,
    proc_params: tuple[str, ...] = (),
    legacy_doc_path: bool = False,
) -> MethodDocComment:
    params_section_offset = _find_params_section(lines)
    is_ignored = _is_ignored_block(lines, params_section_offset)
    documented_entries: tuple[MethodDocParamEntry, ...] = ()
    empty_names: frozenset[str] = frozenset()
    stale_references: tuple[str, ...] = ()
    if params_section_offset is not None and not is_ignored:
        documented_entries, empty_names, stale_references = _parse_param_entries(
            lines,
            block_start_idx=block_start_idx,
            params_section_offset=params_section_offset,
            legacy_doc_path=legacy_doc_path,
        )

    return MethodDocComment(
        block_start_idx=block_start_idx,
        block_end_idx=block_end_idx,
        lines=lines,
        has_params_section=params_section_offset is not None,
        params_section_offset=params_section_offset,
        documented_entries=documented_entries,
        empty_description_names=empty_names,
        stale_reference_entries=stale_references,
        is_ignored_for_method_contract=is_ignored,
        force_all_params_missing=bool(
            proc_params and any(_RE_EXAMPLE_SEE.search(line) for line in lines)
        ),
    )


def build_line_comment_text_index(
    line_comment_nodes: list[Any] | None,
    lines: list[str],
) -> dict[int, str] | None:
    if line_comment_nodes is None:
        return None
    comment_lines_by_idx: dict[int, str] = {}
    for node in line_comment_nodes:
        row = getattr(node, "start_point", (None, None))[0]
        if row is None:
            continue
        col = getattr(node, "start_point", (None, None))[1]
        if col is not None and int(row) < len(lines) and lines[int(row)][: int(col)].strip():
            continue
        text = getattr(node, "text", b"")
        if isinstance(text, bytes):
            comment_lines_by_idx[int(row)] = text.decode("utf-8", errors="replace")
        else:
            comment_lines_by_idx[int(row)] = str(text)
    return comment_lines_by_idx


def _normalize_legacy_comment(line: str) -> str:
    return re.sub(r"^(\s*//)\t ?", r"\1  ", line).replace("\t", " ")


def _find_params_section(lines: tuple[str, ...]) -> int | None:
    for idx, line in enumerate(lines):
        if _RE_PARAMS_SECTION.match(line):
            return idx
    return None


def _is_ignored_block(lines: tuple[str, ...], params_section_offset: int | None) -> bool:
    if any(_RE_SEPARATOR.match(line) for line in lines):
        return True
    if any(_RE_LEGACY_RETURN_HEADER.match(line) for line in lines):
        return True
    if params_section_offset is None and any(_RE_SEE_LINK.match(line) for line in lines):
        return True
    if params_section_offset is None and any(
        _RE_STRUCTURE_COMPOSITION.match(line) for line in lines
    ):
        return True
    if params_section_offset is None and len(lines) == 1:
        text = re.sub(r"^\s*//\s*", "", lines[0]).strip()
        if _RE_END_TEXT.match(text):
            return True
        if text and text[0].islower():
            return True
    return False


def _parse_param_entries(
    lines: tuple[str, ...],
    *,
    block_start_idx: int,
    params_section_offset: int,
    legacy_doc_path: bool,
) -> tuple[tuple[MethodDocParamEntry, ...], frozenset[str], tuple[str, ...]]:
    raw_entries: list[tuple[int, str, str]] = []
    for line in _iter_param_section_lines(lines, params_section_offset):
        match = _RE_RAW_PARAM_ENTRY.match(line)
        if (
            match
            and (legacy_doc_path or not match.group("indent").startswith("\t"))
            and _has_bslls_type_description(match.group("tail"), legacy_doc_path=legacy_doc_path)
        ):
            raw_entries.append(
                (len(match.group("indent")), match.group("name"), match.group("tail"))
            )
    entry_indent = min((indent for indent, _name, _tail in raw_entries), default=0)

    entries: list[MethodDocParamEntry] = []
    empty_names: set[str] = set()
    stale_references: list[str] = []
    for offset, line in _iter_param_section_lines_with_offsets(lines, params_section_offset):
        raw_entry = _RE_RAW_PARAM_ENTRY.match(line)
        if raw_entry and (legacy_doc_path or not raw_entry.group("indent").startswith("\t")):
            raw_name = raw_entry.group("name")
            tail = raw_entry.group("tail")
            if (not entry_indent or len(raw_entry.group("indent")) == entry_indent) and (
                not _has_bslls_type_description(tail, legacy_doc_path=legacy_doc_path)
            ):
                entries.append(
                    MethodDocParamEntry(
                        name=raw_name,
                        line_idx=block_start_idx + offset,
                        tail=tail,
                        has_valid_description=False,
                    )
                )
                empty_names.add(raw_name.casefold())
                continue
        entry = _param_entry(
            line,
            line_idx=block_start_idx + offset,
            entry_indent=entry_indent,
            legacy_doc_path=legacy_doc_path,
        )
        if entry is not None:
            entries.append(entry)
            if not entry.has_valid_description:
                empty_names.add(entry.name.casefold())
            if entry.stale_reference is not None:
                stale_references.append(entry.stale_reference)
    return tuple(entries), frozenset(empty_names), tuple(stale_references)


def _iter_param_section_lines(lines: tuple[str, ...], params_section_offset: int):
    for _offset, line in _iter_param_section_lines_with_offsets(lines, params_section_offset):
        yield line


def _iter_param_section_lines_with_offsets(lines: tuple[str, ...], params_section_offset: int):
    for offset in range(params_section_offset + 1, len(lines)):
        line = lines[offset]
        stripped = line.strip()
        if stripped == "//" or (_RE_SECTION_HEADER.match(line) and not _RE_PARAM_ENTRY.match(line)):
            break
        if _RE_FIELD_ENTRY.match(line):
            continue
        yield offset, line


def _param_entry(
    line: str,
    *,
    line_idx: int,
    entry_indent: int,
    legacy_doc_path: bool,
) -> MethodDocParamEntry | None:
    match = _RE_RAW_PARAM_ENTRY.match(line)
    if not match:
        return None
    if match.group("indent").startswith("\t") and not legacy_doc_path:
        return None
    if entry_indent and len(match.group("indent")) != entry_indent:
        return None
    tail = match.group("tail")
    if not _has_bslls_type_description(tail, legacy_doc_path=legacy_doc_path):
        return None
    reference_match = _RE_REFERENCE.match(tail)
    if reference_match is not None and tail.rstrip().endswith((".", ";")):
        reference = reference_match.group(1).rstrip(".;")
        return MethodDocParamEntry(
            name=reference,
            line_idx=line_idx,
            tail=tail,
            has_valid_description=True,
            stale_reference=reference,
        )
    return MethodDocParamEntry(
        name=match.group("name"),
        line_idx=line_idx,
        tail=tail,
        has_valid_description=True,
    )


def _has_bslls_type_description(tail: str, *, legacy_doc_path: bool) -> bool:
    if legacy_doc_path:
        tail = re.sub(r"\t+", " ", tail)
    if _RE_REFERENCE.match(tail):
        return True
    type_text = re.split(r"\s+-\s+", tail, maxsplit=1)[0].strip()
    if not type_text or "\t" in type_text:
        return False
    type_text = type_text.rstrip()
    if type_text.endswith(","):
        type_text = type_text[:-1].rstrip()
    if legacy_doc_path and type_text.endswith("-"):
        type_text = type_text[:-1].rstrip()
    if type_text.endswith(":"):
        type_text = type_text[:-1].rstrip()
    elif type_text.rstrip() != type_text.rstrip(".;"):
        return False
    if type_text.casefold() in {"структура", "structure"}:
        return True
    if re.fullmatch(
        r"(?:Массив|Array)\s+(?:Из|Of)\s+[A-ZА-ЯЁ][\w]*(?:\.[A-ZА-ЯЁ]\w*)*",
        type_text,
        re.IGNORECASE,
    ):
        return legacy_doc_path or bool(
            re.fullmatch(
                r"(?:Массив|Array)\s+(?:Из|Of)\s+(?:Структура|Structure)",
                type_text,
                re.IGNORECASE,
            )
        )
    if re.search(r"\b(?:или|or|элементов|element)\b", type_text, re.IGNORECASE):
        return False
    if re.search(r"[A-Za-zА-ЯЁа-яё0-9_]\s+[A-Za-zА-ЯЁа-яё0-9_]", type_text):
        return False
    type_name = r"[A-ZА-ЯЁ][\w]*(?:\.[A-ZА-ЯЁ]\w*)*"
    return bool(
        re.fullmatch(rf"{type_name}(?:\s*,\s*{type_name})*", type_text)
        or re.fullmatch(r"[a-zа-яё]+", type_text)
    )
