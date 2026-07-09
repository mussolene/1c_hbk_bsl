from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import append_diagnostic_runtime_rule_tasks
from onec_hbk_bsl.analysis.diagnostic.execution import execute_diagnostic_rule_tasks
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic


@dataclass(slots=True)
class AnalysisFrame:
    path: str
    content: str
    tree: Any
    snapshot: Any
    lines: list[str]
    symbol_index: Any | None = None


class PipelineExecutor:
    """Build and execute the runtime task graph for one document snapshot."""

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
