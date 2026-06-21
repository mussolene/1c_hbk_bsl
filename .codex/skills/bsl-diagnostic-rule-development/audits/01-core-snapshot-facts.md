# 01 Core Snapshot Facts Audit

Status: batch gate closed, rule-by-rule semantic audit in progress.

This audit records the current falsification-test state for the
`01-core-snapshot-facts` batch. It does not claim that every rule is
semantically complete. It separates topology, contract state, synthetic
coverage, and legacy architecture scan results so the next iteration does not
restart from chat memory.

## Batch Inventory

| Code | Rule | Snapshot fact source | Contract | Current coverage signal |
| --- | --- | --- | --- | --- |
| BSL011 | CognitiveComplexity | `procedures`, `complexity_metrics` | missing | synthetic tests present |
| BSL012 | UsingHardcodeSecretInformation | `hardcoded_credential_facts` | missing | synthetic tests present |
| BSL013 | CommentedCode | `commented_code_facts` | missing | synthetic tests present |
| BSL014 | LineLength | `line_too_long_facts` | missing | synthetic tests present |
| BSL016 | NonStandardRegion | `non_standard_region_facts` | missing | synthetic tests present |
| BSL017 | CommandModuleExportMethods | `command_or_form_export_facts` | missing | synthetic tests present |
| BSL019 | CyclomaticComplexity | `procedures`, `complexity_metrics` | missing | synthetic tests present |
| BSL022 | UsingModalWindows | `deprecated_warning_facts` | missing | synthetic tests present |
| BSL026 | EmptyRegion | `empty_region_facts` | missing | synthetic tests present |
| BSL036 | IfConditionComplexity | `complex_condition_facts` | missing | synthetic tests present |
| BSL040 | UsingThisForm | `this_form_usage_facts` | `BSL040.md` | synthetic tests present |
| BSL077 | SelectTopWithoutOrderBy | `select_top_without_order_facts` | `BSL077.md` | synthetic tests present |
| BSL131 | DuplicateRegion | `duplicate_region_facts` | missing | synthetic tests present |
| BSL190 | FormDataToValue | `form_data_to_value_facts` | missing | synthetic tests present |
| BSL204 | InvalidCharacterInFile | `invalid_character_facts` | missing | synthetic tests present |
| BSL216 | MissingSpace | `missing_space_facts` | missing | synthetic tests present |
| BSL219 | MissingVariablesDescription | `module_variable_description_facts` | missing | synthetic tests present |

## Falsification Tests Run

1. Rule-state inventory:
   all 17 rules are mapped by `scripts/diagnostic_rule_matrix.py` to
   `core_snapshot_fact` with `process_safe_fact_task`.
2. End-to-end risk-rule audit:
   `BSL077` has a written semantic oracle, SDBL CST fact model, related-query
   rule cluster, and targeted synthetic coverage. Diagnostic logic was not
   changed in this audit step.
3. Legacy architecture scan:
   `LineDiagnosticFact` has no `message` payload. The remaining regex usage in
   `DocumentSnapshot` is classified as textual extraction or lexical style
   detection for line/comment/region/query-literal facts, not diagnostic message
   duplication. `BSL077` uses SDBL CST through `select_top_without_order`.

## Known Gaps

- Per-rule contracts are still missing for 15 of the 17 rules.
- Full BSLLS parity taxonomy has not been rerun for the whole batch in this
  audit step.
- The current coverage signal is based on existing synthetic tests, not a
  completed per-rule oracle review for all 17 rules.

## Next Cheap Tests

1. Add contracts for the next two risky shared-fact rules:
   `BSL013` and `BSL216`.
2. Run a sanitized parity sample only after the rule contract names the exact
   semantic fact and expected coordinate model.
3. Keep `tests/test_rule_contract_gate.py` validating every `BSL*.md` contract
   so invalid dossiers cannot silently accumulate.
