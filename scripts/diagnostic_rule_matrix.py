#!/usr/bin/env python
"""Build the diagnostic-rule runtime topology matrix.

This is a development/planning tool. It maps each public diagnostic rule to the
current execution topology instead of treating registry phases as the execution
plan. The matrix is intentionally derived from the live runner constants so it
does not become a second hand-maintained rule list.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime import runner
from onec_hbk_bsl.analysis.diagnostic.registry import infer_rule_invoke
from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

CORE_FACT_FEATURES: dict[str, tuple[str, ...]] = {
    "BSL011": ("procedures", "complexity_metrics"),
    "BSL012": ("hardcoded_credential_facts",),
    "BSL013": ("commented_code_facts",),
    "BSL014": ("line_too_long_facts",),
    "BSL016": ("non_standard_region_facts",),
    "BSL017": ("command_or_form_export_facts",),
    "BSL019": ("procedures", "complexity_metrics"),
    "BSL022": ("deprecated_warning_facts",),
    "BSL026": ("empty_region_facts",),
    "BSL036": ("complex_condition_facts",),
    "BSL040": ("this_form_usage_facts",),
    "BSL077": ("select_top_without_order_facts",),
    "BSL131": ("duplicate_region_facts",),
    "BSL190": ("form_data_to_value_facts",),
    "BSL204": ("invalid_character_facts",),
    "BSL216": ("missing_space_facts",),
    "BSL219": ("module_variable_description_facts",),
}

METHOD_CONTRACT_CLUSTER: frozenset[str] = frozenset(
    {
        "BSL007",
        "BSL008",
        "BSL015",
        "BSL031",
        "BSL062",
        "BSL148",
        "BSL192",
        "BSL193",
        "BSL194",
        "BSL212",
        "BSL215",
        "BSL224",
        "BSL228",
        "BSL233",
        "BSL240",
        "BSL254",
        "BSL266",
    }
)

COMMON_MODULE_CLUSTER: frozenset[str] = frozenset(
    {
        "BSL152",
        "BSL154",
        "BSL156",
        "BSL158",
        "BSL159",
        "BSL160",
        "BSL161",
        "BSL162",
        "BSL163",
        "BSL164",
        "BSL165",
        "BSL166",
        "BSL167",
        "BSL168",
        "BSL172",
        "BSL173",
    }
)

TEXTUAL_STYLE_SECURITY_TAGS: frozenset[str] = frozenset(
    {"convention", "style", "security", "naming"}
)


@dataclass(frozen=True, slots=True)
class RuleMatrixRow:
    code: str
    name: str
    registry_phase: str
    registry_source: str
    runtime_rule_class: str
    runner_group: str
    execution_mode: str
    snapshot_features: tuple[str, ...]
    recommended_batch: str
    placement_guidance: str
    tags: tuple[str, ...]


def _runtime_rule_by_code() -> dict[str, object]:
    return {rule.code: rule for rule in runner._RULES}


def _contains(code: str, codes: Iterable[str]) -> bool:
    return code in set(codes)


def _group_for_code(code: str, runtime_rule_class: str) -> tuple[str, str, tuple[str, ...]]:
    if _contains(code, runner._QUERY_TEXT_191_201_CODES):
        return ("query_text_191_201", "local_aggregated_task", ("query_text_blocks", "lines"))
    if _contains(code, runner._QUERY_TEXT_220_235_269_CODES):
        return ("query_text_220_235_269", "local_aggregated_task", ("query_text_blocks", "lines"))
    if _contains(code, runner._QUERY_JOIN_CODES):
        return ("query_join_206_207_209", "local_aggregated_task", ("query_text_blocks", "lines"))
    if _contains(code, runner._QUERY_METADATA_CODES):
        return (
            "query_metadata_174_187_236_238",
            "local_aggregated_task",
            ("query_text_blocks", "lines"),
        )
    if _contains(code, runner._METADATA_POOL_CODES):
        return (
            "metadata_pool_189_211_213_214_231_232_241_242_246_274",
            "local_aggregated_task",
            ("content", "lines", "procedures", "metadata_context"),
        )
    if _contains(code, runner._METADATA_RUNTIME_CODES):
        return (
            "metadata_runtime_244_253_261",
            "local_aggregated_task",
            ("lines", "procedures", "metadata_context"),
        )
    if _contains(code, runner._PROCESS_CORE_FACT_CODES):
        return ("core_snapshot_fact", "process_safe_fact_task", CORE_FACT_FEATURES.get(code, ()))
    if _contains(code, runner._DEPRECATED_API_POOL_CODES):
        return (
            "deprecated_api_pool_175_176",
            "local_pool_or_large_file_fact_task",
            ("module_model", "symbols", "calls", "lines"),
        )
    if code == "BSL256":
        return (
            "typo_runtime_or_large_file_shards",
            "local_or_process_safe_large_file_shards",
            ("tree", "spell_candidates"),
        )
    return (
        f"runtime_rule_class:{runtime_rule_class}",
        "local_runtime_task",
        _features_for_runtime_class(runtime_rule_class),
    )


def _features_for_runtime_class(runtime_rule_class: str) -> tuple[str, ...]:
    if runtime_rule_class == "CommonModuleDiagnosticsRule":
        return ("lines", "procedures", "module_metadata_context")
    if runtime_rule_class == "MethodContractDiagnosticsRule":
        return ("lines", "procedures", "method_contract_context")
    if runtime_rule_class.startswith("Query"):
        return ("query_text_blocks", "lines")
    if runtime_rule_class == "LightPoolDiagnosticsRule":
        return ("document_context", "tree", "lines")
    if runtime_rule_class == "LocalXmlDiagnosticsRule":
        return ("xml_context", "lines")
    if runtime_rule_class == "CoreDiagnosticsRule":
        return ("document_context", "tree", "lines")
    return ("document_context", "lines")


def _recommended_batch(
    *,
    code: str,
    runner_group: str,
    runtime_rule_class: str,
    tags: tuple[str, ...],
) -> str:
    if runner_group == "core_snapshot_fact":
        return "01-core-snapshot-facts"
    if runner_group.startswith(("query_", "metadata_")):
        return "02-query-metadata-aggregation"
    if code in METHOD_CONTRACT_CLUSTER or runtime_rule_class == "MethodContractDiagnosticsRule":
        return "03-method-procedure-contracts"
    if code in COMMON_MODULE_CLUSTER or runtime_rule_class == "CommonModuleDiagnosticsRule":
        return "04-common-module-context"
    if runner_group == "typo_runtime_or_large_file_shards":
        return "05-heavy-process-typo-performance"
    if set(tags) & TEXTUAL_STYLE_SECURITY_TAGS:
        return "06-line-text-style-security"
    return "07-local-runtime-tail"


def _placement_guidance(runner_group: str, execution_mode: str) -> str:
    if runner_group == "core_snapshot_fact":
        return "keep rule logic as a consumer of DocumentSnapshot facts"
    if runner_group.startswith(("query_", "metadata_")):
        return "place beside the aggregated query/metadata pool that owns the shared view"
    if execution_mode == "process_safe_fact_task":
        return "pass only serializable facts into process-safe work"
    if runner_group == "typo_runtime_or_large_file_shards":
        return "shard only collected spell candidates, not full parser state"
    return "keep beside the runtime rule class until a shared fact pool exists"


def build_rule_matrix() -> list[RuleMatrixRow]:
    rule_by_code = _runtime_rule_by_code()
    rows: list[RuleMatrixRow] = []
    for code in sorted(RULE_METADATA):
        meta = RULE_METADATA[code]
        invoke = infer_rule_invoke(code, meta)
        runtime_rule = rule_by_code[code]
        runtime_rule_class = type(runtime_rule).__name__
        runner_group, execution_mode, snapshot_features = _group_for_code(code, runtime_rule_class)
        tags = tuple(sorted(str(tag) for tag in (meta.get("tags") or ())))
        rows.append(
            RuleMatrixRow(
                code=code,
                name=str(meta.get("name", "")),
                registry_phase=invoke.phase.value,
                registry_source=invoke.source,
                runtime_rule_class=runtime_rule_class,
                runner_group=runner_group,
                execution_mode=execution_mode,
                snapshot_features=tuple(sorted(snapshot_features)),
                recommended_batch=_recommended_batch(
                    code=code,
                    runner_group=runner_group,
                    runtime_rule_class=runtime_rule_class,
                    tags=tags,
                ),
                placement_guidance=_placement_guidance(runner_group, execution_mode),
                tags=tags,
            )
        )
    return rows


def _row_for_output(row: RuleMatrixRow) -> dict[str, object]:
    data = asdict(row)
    data["snapshot_features"] = ",".join(row.snapshot_features)
    data["tags"] = ",".join(row.tags)
    return data


def _write_json(rows: list[RuleMatrixRow]) -> None:
    print(
        json.dumps(
            [_row_for_output(row) for row in rows],
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_csv(rows: list[RuleMatrixRow]) -> None:
    fieldnames = list(_row_for_output(rows[0]).keys()) if rows else []
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(_row_for_output(row))


def _write_markdown(rows: list[RuleMatrixRow]) -> None:
    headers = (
        "code",
        "name",
        "registry_phase",
        "runner_group",
        "execution_mode",
        "snapshot_features",
        "recommended_batch",
    )
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        data = _row_for_output(row)
        print("| " + " | ".join(str(data[header]) for header in headers) + " |")


def _write_summary(rows: list[RuleMatrixRow]) -> None:
    for label, values in (
        ("recommended_batch", [row.recommended_batch for row in rows]),
        ("runner_group", [row.runner_group for row in rows]),
        ("execution_mode", [row.execution_mode for row in rows]),
        ("registry_phase", [row.registry_phase for row in rows]),
    ):
        print(f"{label}:")
        for value, count in Counter(values).most_common():
            print(f"  {value}: {count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "csv", "markdown", "summary"),
        default="markdown",
    )
    args = parser.parse_args(argv)

    rows = build_rule_matrix()
    if args.format == "json":
        _write_json(rows)
    elif args.format == "csv":
        _write_csv(rows)
    elif args.format == "summary":
        _write_summary(rows)
    else:
        _write_markdown(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
