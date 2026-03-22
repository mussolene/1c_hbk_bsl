"""diagnostics_rule_registry — phase inference and enabled snapshot."""

from __future__ import annotations

from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA, DiagnosticEngine
from onec_hbk_bsl.analysis.diagnostics_rule_registry import (
    RulePhase,
    build_enabled_invoke_snapshot,
    infer_rule_invoke,
)


def test_infer_explicit_bsl014_line() -> None:
    info = infer_rule_invoke("BSL014", {"tags": ["convention"]})
    assert info.phase is RulePhase.LINE
    assert info.source == "explicit"


def test_infer_heuristic_complexity_proc() -> None:
    meta = {"name": "Foo", "tags": ["brain-overload", "complexity"]}
    info = infer_rule_invoke("BSL999", meta)
    assert info.phase is RulePhase.PROC
    assert info.source == "tags"


def test_build_snapshot_respects_engine_select() -> None:
    eng = DiagnosticEngine(select={"BSL014", "BSL280"})
    snap = build_enabled_invoke_snapshot(eng, RULE_METADATA)
    assert snap["counts_by_phase"].get("line") == 1
    assert snap["counts_by_phase"].get("index") == 1
    assert "BSL014" in snap["codes_by_phase"].get("line", [])
