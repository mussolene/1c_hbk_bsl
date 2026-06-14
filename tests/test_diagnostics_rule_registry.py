"""diagnostics_rule_registry — phase inference and enabled snapshot."""

from __future__ import annotations

from onec_hbk_bsl.analysis.bslls_parity import BSLLS_DEFAULT_DISABLED_NAMES
from onec_hbk_bsl.analysis.diagnostic.registry import (
    RulePhase,
    build_enabled_invoke_snapshot,
    infer_rule_invoke,
)
from onec_hbk_bsl.analysis.diagnostics import (
    RULE_METADATA,
    DiagnosticEngine,
    normalize_rule_code_set,
    normalize_rule_code_set_strict,
    resolve_rule_token_to_code,
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
    eng = DiagnosticEngine(select={"BSL014", "BSL278"})
    snap = build_enabled_invoke_snapshot(eng, RULE_METADATA)
    assert snap["counts_by_phase"].get("line") == 1
    assert snap["counts_by_phase"].get("other") == 1
    assert "BSL014" in snap["codes_by_phase"].get("line", [])


def test_server_side_export_form_method_is_not_bslls_default_disabled() -> None:
    assert "ServerSideExportFormMethod" not in BSLLS_DEFAULT_DISABLED_NAMES
    assert DiagnosticEngine()._rule_enabled("BSL245")


def test_high_value_zero_noise_rules_are_default_enabled() -> None:
    for code in (
        "BSL196",
        "BSL213",
        "BSL214",
        "BSL231",
        "BSL244",
        "BSL246",
        "BSL253",
        "BSL261",
        "BSL274",
    ):
        assert DiagnosticEngine()._rule_enabled(code)


def test_local_only_rules_are_not_public_or_selectable() -> None:
    for code in ("BSL999", "BSL998"):
        assert code not in RULE_METADATA
        assert resolve_rule_token_to_code(code) is None
        assert not DiagnosticEngine(select={code})._rule_enabled(code)

    assert normalize_rule_code_set(["BSL999,LineLength,WrongWebServiceHandler"]) == {
        "BSL014",
        "BSL278",
    }


def test_user_facing_rule_selection_rejects_unknown_tokens() -> None:
    assert normalize_rule_code_set(["BSL999,LineLength"]) == {"BSL014"}

    try:
        normalize_rule_code_set_strict(["BSL999,LineLength"], source="test")
    except ValueError as exc:
        assert "Unknown diagnostic rule token(s) in test: BSL999" in str(exc)
    else:
        raise AssertionError("strict normalization should reject unknown rule tokens")
