# 01 Core Snapshot Facts Audit

Status: batch gate closed, 17/17 rule contracts present, rule-by-rule parity audit pending.

This audit records the current falsification-test state for the
`01-core-snapshot-facts` batch. It does not claim that every rule is
semantically complete. It separates topology, contract state, synthetic
coverage, and legacy architecture scan results so the next iteration does not
restart from chat memory.

## Batch Inventory

| Code | Rule | Snapshot fact source | Contract | Current coverage signal |
| --- | --- | --- | --- | --- |
| BSL011 | CognitiveComplexity | `procedures`, `complexity_metrics` | `BSL011.md` | synthetic tests present |
| BSL012 | UsingHardcodeSecretInformation | `hardcoded_credential_facts` | `BSL012.md` | synthetic tests present |
| BSL013 | CommentedCode | `commented_code_facts` | `BSL013.md` | synthetic tests present |
| BSL014 | LineLength | `line_too_long_facts` | `BSL014.md` | synthetic tests present |
| BSL016 | NonStandardRegion | `non_standard_region_facts` | `BSL016.md` | synthetic tests present |
| BSL017 | CommandModuleExportMethods | `command_or_form_export_facts` | `BSL017.md` | synthetic tests present |
| BSL019 | CyclomaticComplexity | `procedures`, `complexity_metrics` | `BSL019.md` | synthetic tests present |
| BSL022 | UsingModalWindows | `deprecated_warning_facts` | `BSL022.md` | synthetic tests present |
| BSL026 | EmptyRegion | `empty_region_facts` | `BSL026.md` | synthetic tests present |
| BSL036 | IfConditionComplexity | `complex_condition_facts` | `BSL036.md` | synthetic tests present |
| BSL040 | UsingThisForm | `this_form_usage_facts` | `BSL040.md` | synthetic tests present |
| BSL077 | SelectTopWithoutOrderBy | `select_top_without_order_facts` | `BSL077.md` | synthetic tests present |
| BSL131 | DuplicateRegion | `duplicate_region_facts` | `BSL131.md` | synthetic tests present |
| BSL190 | FormDataToValue | `form_data_to_value_facts` | `BSL190.md` | synthetic tests present |
| BSL204 | InvalidCharacterInFile | `invalid_character_facts` | `BSL204.md` | synthetic tests present |
| BSL216 | MissingSpace | `missing_space_facts` | `BSL216.md` | synthetic tests present |
| BSL219 | MissingVariablesDescription | `module_variable_description_facts` | `BSL219.md` | synthetic tests present |

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

4. Contract completion:
   all 17 rules now have validator-backed contract dossiers. Diagnostic logic
   was not changed by this contract completion step.

## Known Gaps

- Full BSLLS parity taxonomy has not been rerun for the whole batch in this
  audit step.
- The current coverage signal is based on existing synthetic tests plus
  contract-level semantic oracles, not a fresh per-rule corpus parity run.

## Next Cheap Tests

1. Run a sanitized parity sample only after the rule contract names the exact
   semantic fact and expected coordinate model.
2. Start with the highest-risk remaining semantic checks: `BSL013`, `BSL216`,
   and `BSL040` path/module-kind behavior.
3. Keep `tests/test_rule_contract_gate.py` validating every `BSL*.md` contract
   so invalid dossiers cannot silently accumulate.
