from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.domain import (
    ModuleAnalysisContext,
    ModuleModel,
    ProcedureModel,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states,
    comment_start_outside_double_quotes,
)


@dataclass(frozen=True)
class DiagnosticDocumentContext:
    """Small parser-backed document facade over the current parser snapshot."""

    path: str
    content: str
    lines: list[str]
    tree: Any
    snapshot: Any | None = None
    max_bool_ops: int = 3
    bsl036_enabled: bool = False
    runtime_call_context: Any | None = None
    ts_nodes_for_types: Any | None = None
    global_method_calls_from_nodes: Any | None = None
    diagnostics_engine: Any | None = None

    @cached_property
    def line_offsets(self) -> list[int]:
        offsets = [0]
        for pos, char in enumerate(self.content):
            if char == "\n":
                offsets.append(pos + 1)
        return offsets

    def to_line_col(self, offset: int) -> tuple[int, int]:
        offsets = self.line_offsets
        line = bisect_right(offsets, offset) - 1
        return line, offset - offsets[line]

    @cached_property
    def analysis(self) -> ModuleAnalysisContext | None:
        if self.snapshot is None or not hasattr(self.snapshot, "path"):
            return None
        return ModuleAnalysisContext.from_snapshot(self.snapshot)

    @cached_property
    def module_model(self) -> ModuleModel:
        if self.analysis is not None:
            return self.analysis.module
        return ModuleModel(path=self.path)

    @cached_property
    def procedures(self) -> list[Any]:
        return list(getattr(self.snapshot, "procedures", []) or [])

    @cached_property
    def regions(self) -> list[Any]:
        return list(getattr(self.snapshot, "regions", []) or [])

    @cached_property
    def procedure_models(self) -> list[ProcedureModel]:
        if self.analysis is not None:
            return list(self.analysis.procedures)
        return [ProcedureModel.from_proc_info(self.path, proc) for proc in self.procedures]

    @cached_property
    def _procedure_model_by_span(self) -> dict[tuple[int, int, str], ProcedureModel]:
        return {
            (model.start_idx, model.end_idx, model.name.casefold()): model
            for model in self.procedure_models
        }

    def procedure_model_from_proc_info(self, path: str, proc: Any) -> ProcedureModel:
        if path == self.path:
            key = (
                int(getattr(proc, "start_idx", -1)),
                int(getattr(proc, "end_idx", -1)),
                str(getattr(proc, "name", "")).casefold(),
            )
            cached = self._procedure_model_by_span.get(key)
            if cached is not None:
                return cached
        return ProcedureModel.from_proc_info(path, proc)

    @cached_property
    def string_states(self) -> list[bool]:
        if self.analysis is not None:
            return self.analysis.line_string_states
        if self.snapshot is not None:
            return list(self.snapshot.line_string_states)
        return build_line_string_states(self.lines)

    @cached_property
    def comment_starts(self) -> list[int | None]:
        if self.analysis is not None:
            return self.analysis.comment_starts
        if self.snapshot is not None:
            return list(self.snapshot.comment_starts)
        return [
            comment_start_outside_double_quotes(line, self.string_states[idx])
            for idx, line in enumerate(self.lines)
        ]

    @cached_property
    def masked_lines(self) -> list[str]:
        if self.analysis is not None:
            return self.analysis.masked_lines
        if self.snapshot is not None:
            return list(self.snapshot.masked_lines)
        return list(self.lines)

    @cached_property
    def code_lines_without_comments(self) -> list[str]:
        if self.analysis is not None:
            return self.analysis.code_lines_without_comments
        if self.snapshot is not None:
            return list(self.snapshot.code_lines_without_comments)
        return list(self.lines)

    @cached_property
    def query_text_blocks(self) -> list[Any]:
        if self.analysis is not None:
            return self.analysis.query_text_blocks
        return list(getattr(self.snapshot, "query_text_blocks", []) or [])
