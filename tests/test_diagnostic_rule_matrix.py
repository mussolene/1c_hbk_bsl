from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

ROOT = Path(__file__).resolve().parents[1]


def _load_matrix_module():
    path = ROOT / "scripts" / "diagnostic_rule_matrix.py"
    spec = importlib.util.spec_from_file_location("diagnostic_rule_matrix", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows_by_code():
    module = _load_matrix_module()
    return {row.code: row for row in module.build_rule_matrix()}


def test_rule_matrix_covers_every_public_rule_once() -> None:
    rows = _rows_by_code()

    assert set(rows) == set(RULE_METADATA)
    assert len(rows) == len(RULE_METADATA)


def test_rule_matrix_maps_core_snapshot_fact_rules() -> None:
    rows = _rows_by_code()
    core_codes = {
        code
        for code, row in rows.items()
        if row.recommended_batch == "01-core-snapshot-facts"
    }

    assert core_codes == {
        "BSL011",
        "BSL012",
        "BSL013",
        "BSL014",
        "BSL016",
        "BSL017",
        "BSL019",
        "BSL022",
        "BSL026",
        "BSL036",
        "BSL040",
        "BSL077",
        "BSL131",
        "BSL190",
        "BSL204",
        "BSL216",
        "BSL219",
    }
    assert all(rows[code].runner_group == "core_snapshot_fact" for code in core_codes)
    assert all(rows[code].execution_mode == "process_safe_fact_task" for code in core_codes)

    row = rows["BSL040"]
    assert row.runner_group == "core_snapshot_fact"
    assert row.execution_mode == "process_safe_fact_task"
    assert row.snapshot_features == ("this_form_usage_facts",)
    assert row.recommended_batch == "01-core-snapshot-facts"


def test_rule_matrix_maps_query_aggregation_rules() -> None:
    row = _rows_by_code()["BSL191"]

    assert row.runner_group == "query_text_191_201"
    assert row.execution_mode == "local_aggregated_task"
    assert "query_text_blocks" in row.snapshot_features
    assert row.recommended_batch == "02-query-metadata-aggregation"


def test_rule_matrix_maps_method_contract_cluster_even_when_core_rule() -> None:
    row = _rows_by_code()["BSL062"]

    assert row.runtime_rule_class == "CoreDiagnosticsRule"
    assert row.recommended_batch == "03-method-procedure-contracts"
    assert row.placement_guidance


def test_rule_matrix_maps_typo_as_heavy_sharded_work() -> None:
    row = _rows_by_code()["BSL256"]

    assert row.runner_group == "typo_runtime_or_large_file_shards"
    assert row.execution_mode == "local_or_process_safe_large_file_shards"
    assert row.recommended_batch == "05-heavy-fork-typo-performance"


def test_rule_matrix_summary_cli(capsys) -> None:
    module = _load_matrix_module()

    assert module.main(["--format", "summary"]) == 0
    captured = capsys.readouterr()
    assert "recommended_batch:" in captured.out
    assert "01-core-snapshot-facts" in captured.out
