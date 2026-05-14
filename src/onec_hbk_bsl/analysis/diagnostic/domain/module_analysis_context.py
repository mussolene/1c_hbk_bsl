from __future__ import annotations

from dataclasses import dataclass

from onec_hbk_bsl.analysis.diagnostic.domain.module_model import ModuleModel
from onec_hbk_bsl.analysis.diagnostic.domain.procedure_model import ProcedureModel
from onec_hbk_bsl.analysis.document_snapshot import (
    DocumentSnapshot,
    QueryTextBlockInfo,
)


@dataclass(frozen=True, slots=True)
class LineFacts:
    """Cached per-line facts derived from a document snapshot."""

    index: int
    line_no: int
    text: str
    code_text: str
    masked_text: str
    length: int
    comment_start: int | None
    starts_in_string: bool
    is_blank: bool

    @property
    def has_code(self) -> bool:
        return bool(self.code_text.strip())

    @property
    def is_comment_only(self) -> bool:
        stripped = self.text.lstrip()
        return stripped.startswith("//")


@dataclass(slots=True)
class ModuleAnalysisContext:
    """Opt-in domain view over cached document analysis primitives."""

    snapshot: DocumentSnapshot
    _module: ModuleModel | None = None
    _procedures: tuple[ProcedureModel, ...] | None = None
    _line_facts: tuple[LineFacts, ...] | None = None

    @classmethod
    def from_snapshot(cls, snapshot: DocumentSnapshot) -> ModuleAnalysisContext:
        return cls(snapshot=snapshot)

    @property
    def path(self) -> str:
        return self.snapshot.path

    @property
    def content(self) -> str:
        return self.snapshot.content

    @property
    def lines(self) -> list[str]:
        return self.snapshot.lines

    @property
    def module(self) -> ModuleModel:
        if self._module is None:
            self._module = ModuleModel(self.path)
        return self._module

    @property
    def procedures(self) -> tuple[ProcedureModel, ...]:
        if self._procedures is None:
            self._procedures = tuple(
                ProcedureModel.from_proc_info(self.path, proc) for proc in self.snapshot.procedures
            )
        return self._procedures

    @property
    def query_text_blocks(self) -> list[QueryTextBlockInfo]:
        return self.snapshot.query_text_blocks

    @property
    def line_string_states(self) -> list[bool]:
        return self.snapshot.line_string_states

    @property
    def comment_starts(self) -> list[int | None]:
        return self.snapshot.comment_starts

    @property
    def masked_lines(self) -> list[str]:
        return self.snapshot.masked_lines

    @property
    def code_lines_without_comments(self) -> list[str]:
        return self.snapshot.code_lines_without_comments

    @property
    def line_lengths(self) -> list[int]:
        return self.snapshot.line_lengths

    @property
    def blank_line_flags(self) -> list[bool]:
        return self.snapshot.blank_line_flags

    @property
    def line_facts(self) -> tuple[LineFacts, ...]:
        if self._line_facts is None:
            self._line_facts = tuple(
                LineFacts(
                    index=idx,
                    line_no=idx + 1,
                    text=line,
                    code_text=self.code_lines_without_comments[idx],
                    masked_text=self.masked_lines[idx],
                    length=self.line_lengths[idx],
                    comment_start=self.comment_starts[idx],
                    starts_in_string=self.line_string_states[idx],
                    is_blank=self.blank_line_flags[idx],
                )
                for idx, line in enumerate(self.lines)
            )
        return self._line_facts

    def line_fact(self, index: int) -> LineFacts:
        return self.line_facts[index]

    def query_text_blocks_containing_line(self, line_no: int) -> tuple[QueryTextBlockInfo, ...]:
        return tuple(
            block
            for block in self.query_text_blocks
            if any(line.line_no == line_no for line in block.content_lines)
        )
