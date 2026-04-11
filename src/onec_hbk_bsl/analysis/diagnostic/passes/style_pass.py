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
    if engine._rule_enabled("BSL024"):
        tasks.append(
            ("BSL024", lambda: engine._rule_bsl024_space_at_start_comment(path, lines, snapshot))
        )

    if engine._rule_enabled("BSL030"):

        def _task_bsl030() -> list[Diagnostic]:
            out = engine._rule_bsl030_header_semicolon(path, lines)
            out.extend(engine._rule_bsl030_statement_missing_semicolon(path, lines, procs))
            return out

        tasks.append(("BSL030", _task_bsl030))


def extend_style_spacing_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
) -> None:
    """Append spacing-related style tasks in declaration order."""
    if engine._rule_enabled("BSL136"):
        tasks.append(
            ("BSL136", lambda: engine._rule_bsl136_missing_space_before_comment(path, lines))
        )


def extend_style_token_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    snapshot: DocumentSnapshot,
) -> None:
    """Append keyword/line-break style tasks in declaration order."""
    if engine._rule_enabled("BSL153"):
        tasks.append(
            ("BSL153", lambda: engine._rule_bsl153_canonical_spelling_keywords(path, lines))
        )
    if engine._rule_enabled("BSL200"):
        tasks.append(
            ("BSL200", lambda: engine._rule_bsl200_incorrect_line_break(path, lines, snapshot))
        )


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
    if engine._rule_enabled("BSL227"):
        tasks.append(
            ("BSL227", lambda: engine._rule_bsl227_one_statement_per_line(path, lines, procs))
        )
    if engine._rule_enabled("BSL216"):
        tasks.append(("BSL216", lambda: engine._rule_bsl216_missing_space(path, lines, snapshot)))
