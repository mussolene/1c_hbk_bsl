"""Style/token diagnostic orchestration for ``DiagnosticEngine``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostic.engine import DiagnosticEngine
    from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic
    from onec_hbk_bsl.analysis.document_snapshot import DocumentSnapshot, ProcInfo


def extend_style_comment_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    procs: list[ProcInfo],
    snapshot: DocumentSnapshot,
) -> None:
    """Append early style/comment tasks in declaration order."""
    if engine._rule_enabled("BSL030"):

        def _task_bsl030() -> list[Diagnostic]:
            return engine._rule_bsl030_statement_missing_semicolon(path, lines, procs)

        tasks.append(("BSL030", _task_bsl030))


def extend_style_spacing_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
) -> None:
    """Append spacing-related style tasks in declaration order."""


def extend_style_token_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    snapshot: DocumentSnapshot,
) -> None:
    """Append keyword/line-break style tasks in declaration order."""


def extend_style_tail_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    procs: list[ProcInfo],
    snapshot: DocumentSnapshot,
) -> None:
    """Append late style tasks in declaration order."""
    if engine._rule_enabled("BSL216"):
        tasks.append(("BSL216", lambda: engine._rule_bsl216_missing_space(path, lines, snapshot)))
