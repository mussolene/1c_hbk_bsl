from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import append_diagnostic_runtime_rule_tasks
from onec_hbk_bsl.analysis.diagnostic.execution import execute_diagnostic_rule_tasks
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic
from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA


class PipelinePhase(StrEnum):
    SYNTAX = "syntax"
    LEXICAL = "lexical"
    CST = "cst"
    QUERY = "query"
    METADATA = "metadata"
    FINAL = "final"


@dataclass(slots=True)
class AnalysisFrame:
    path: str
    content: str
    tree: Any
    snapshot: Any
    lines: list[str]
    symbol_index: Any | None = None


@dataclass(frozen=True, slots=True)
class RuleSpec:
    code: str
    phase: PipelinePhase


class RuleRegistry:
    """Rule metadata for pipeline planning.

    The current runtime executor already encapsulates fine-grained routing;
    this registry provides a stable object model for future phase-based
    orchestration without changing rule behavior now.
    """

    def iter_enabled(self, engine: Any) -> list[RuleSpec]:
        return [
            RuleSpec(code=code, phase=PipelinePhase.FINAL)
            for code in sorted(RULE_METADATA)
            if engine._rule_enabled(code)
        ]


class PipelineExecutor:
    """Object pipeline facade over the current runtime rule executor."""

    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self._registry = registry or RuleRegistry()

    def execute(self, engine: Any, frame: AnalysisFrame) -> list[Diagnostic]:
        # Build rule tasks through the runtime dispatcher (single source of truth).
        rule_tasks: list[tuple[str, Any]] = []
        append_diagnostic_runtime_rule_tasks(
            rule_tasks,
            engine=engine,
            path=frame.path,
            content=frame.content,
            lines=frame.lines,
            tree=frame.tree,
            snapshot=frame.snapshot,
        )
        return execute_diagnostic_rule_tasks(rule_tasks)
