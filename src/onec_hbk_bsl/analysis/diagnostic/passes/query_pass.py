"""Query-related diagnostic orchestration for ``DiagnosticEngine``.

This module only schedules rule groups. Rule implementations still live in the
engine for now, which lets us reduce the size of ``_run_rules`` without
changing behavior or creating a second rule registry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from onec_hbk_bsl.analysis.document_snapshot import QueryTextBlockInfo

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostic.engine import DiagnosticEngine
    from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic


def extend_query_top_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    query_blocks: list[QueryTextBlockInfo],
) -> None:
    """Append early query-related rule tasks in declaration order."""
    if engine._rule_enabled("BSL077"):
        tasks.append(
            (
                "BSL077",
                lambda: engine._rule_bsl077_select_top_without_order_by(path, lines, query_blocks),
            )
        )


def extend_query_text_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    query_blocks: list[QueryTextBlockInfo],
) -> None:
    """Append query-text tasks in declaration order."""
    bsl220_235_269_273 = ("BSL220", "BSL235", "BSL269", "BSL273")
    if any(engine._rule_enabled(code) for code in bsl220_235_269_273):
        tasks.append(
            (
                "BSL220_235_269_273",
                lambda: engine._rule_bsl220_235_269_273_query_text_diagnostics(
                    path, lines, bsl220_235_269_273, query_blocks
                ),
            )
        )

    bsl191_201 = ("BSL191", "BSL201")
    if any(engine._rule_enabled(code) for code in bsl191_201):
        tasks.append(
            (
                "BSL191_201",
                lambda: engine._rule_bsl191_201_query_text_diagnostics(
                    path, lines, bsl191_201, query_blocks
                ),
            )
        )


def extend_query_join_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    query_blocks: list[QueryTextBlockInfo],
) -> None:
    """Append join-related query tasks in declaration order."""
    bsl206_207_209 = ("BSL206", "BSL207", "BSL209")
    if any(engine._rule_enabled(code) for code in bsl206_207_209):
        tasks.append(
            (
                "BSL206_207_209",
                lambda: engine._rule_bsl206_207_209_query_join_diagnostics(
                    path, lines, bsl206_207_209, query_blocks
                ),
            )
        )


def extend_query_metadata_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: DiagnosticEngine,
    path: str,
    lines: list[str],
    query_blocks: list[QueryTextBlockInfo],
) -> None:
    """Append metadata-aware query tasks in declaration order."""
    bsl174_187_236_238 = ("BSL174", "BSL187", "BSL236", "BSL238")
    if any(engine._rule_enabled(code) for code in bsl174_187_236_238):
        tasks.append(
            (
                "BSL174_187_236_238",
                lambda: engine._rule_bsl174_187_236_238_query_metadata_pool(
                    path, lines, bsl174_187_236_238, query_blocks
                ),
            )
        )
