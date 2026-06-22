# 01 Core Snapshot Facts Audit

Status: batch gate closed, 17/17 rule contracts present, original-workspace
BSLLS parity classified at batch level; rule-by-rule semantic deltas remain.

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

5. Semantic/parity audit pass 1:
   `BSL013`, `BSL216`, and `BSL040` were checked against their contracts and
   current implementation topology. The semantic pass is closed for this
   iteration. External BSLLS parity is partially probed but still open for
   `BSL013` and `BSL040`; a runnable local BSLLS artifact exists, but the
   parity harness still needs valid rule-profile configuration and/or proper
   form-module fixture metadata for these two rules.

   - `BSL013` remains a textual/comment-group rule. It is implemented through
     `DocumentSnapshot.commented_code_facts`; prose comments are ignored,
     commented procedure blocks are reported as one grouped diagnostic, example
     markers suppress the group, and inline commented assignments are reported
     from the inline comment span.
   - `BSL216` remains a lexical style rule. It is implemented through
     `DocumentSnapshot.missing_space_facts`; string/comment spans are masked or
     excluded before comparison, comma, semicolon, keyword, and arithmetic
     spacing checks produce facts.
   - `BSL040` remains a form-module-only rule. It is implemented through
     `DocumentSnapshot.this_form_usage_facts`; non-form modules are skipped,
     split module fragments are excluded by runtime guards, string/comment spans
     are ignored, and a local `ЭтаФорма`/`ThisForm` parameter suppresses
     reports inside that procedure.

   The targeted oracle produced the expected facts: BSL013 prose `[]`,
   BSL013 commented procedure block one diagnostic, BSL216 string literal `[]`,
   BSL216 `А=1;Б=2` three spacing diagnostics, BSL040 full form module one
   diagnostic, BSL040 shadowing parameter `[]`, and BSL040 split fragment `[]`.
   The repository fixtures CLI sample with only these three selected rules
   produced zero diagnostics, which is acceptable for smoke coverage because
   the targeted oracle is the positive/negative semantic source for this pass.

   Corrective BSLLS probe: local
   `bsl-language-server-0.29.0-exec.jar` is available under the user cache and
   runs `analyze`. On sanitized synthetic modules, BSLLS and onec match BSL216
   exactly for `А=1;Б=2`: three diagnostics at the same line/columns. BSLLS did
   not report BSL013 or BSL040 on the minimal synthetic modules in default,
   `ALL`, or attempted `ONLY` mode; this is not a semantic conclusion about the
   rules. It means the minimal form/comment fixtures need to be repaired before
   BSL013/BSL040 can be called BSLLS-classified.

6. Parity tooling correction:
   The temporary `scripts/compare_diag_bslls.py` runner was removed because its
   temp-copy source root changes workspace and metadata context for
   path-sensitive rules. BSLLS-backed parity audits must use the original
   source root/workspace root and run onec through
   `onec-hbk-bsl check --no-config --format json --select ...` when comparing
   raw rule semantics. Project config parity is a separate product check.

7. Original-workspace core17 parity run:
   onec was run with `check --no-config --format json --select` for all 17
   batch rules, and BSLLS was run with `diagnostics.mode=ONLY` for the matching
   BSLLS names on the same source/workspace roots. The sanitized batch result:

   | Code | onec | BSLLS | exact common | status |
   | --- | ---: | ---: | ---: | --- |
   | BSL011 | 1276 | 1314 | 1274 | semantic/file-layout delta |
   | BSL012 | 4 | 0 | 0 | onec-only vs BSLLS |
   | BSL013 | 714 | 1198 | 528 | semantic delta; standalone directive trigger rejected as overbroad |
   | BSL014 | 13138 | 13178 | 12986 | semantic/range delta |
   | BSL016 | 100 | 100 | 100 | exact match |
   | BSL017 | 0 | 0 | 0 | exact match |
   | BSL019 | 426 | 426 | 426 | exact match |
   | BSL022 | 150 | 150 | 0 | range-only: same file/line, different anchor |
   | BSL026 | 0 | 0 | 0 | exact match |
   | BSL036 | 458 | 458 | 406 | range-only: same file/line, different anchor |
   | BSL040 | 1919 | 1081 | 1081 | onec reports additional legacy `Forms/.../Ext/Module.bsl` layout |
   | BSL077 | 14 | 16 | 14 | BSLLS-only 2 are parse-error/order-present query blocks |
   | BSL131 | 6 | 6 | 0 | semantic delta: same files, different regions/lines |
   | BSL190 | 0 | 0 | 0 | exact match |
   | BSL204 | 8 | 8 | 8 | exact match |
   | BSL216 | 4524 | 4552 | 4524 | BSLLS-only 28 unary `-` after `[` |
   | BSL219 | 478 | 492 | 452 | semantic/range delta |

   `BSL016` was corrected after the run to trim trailing whitespace from the
   diagnostic range, closing its one-character BSLLS range delta.

8. BSL014 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL014`
   with BSLLS 0.29.0 `LineLength` JSON output. Exact common cases include
   threshold behavior, long comments, method-description comments, trailing
   comments, trailing spaces, and long single-line string literals. The sampled
   onec-only category was long multiline string/query content lines starting
   with `|`; BSLLS `LineLength` is token-line based and does not report those
   content lines. `DocumentSnapshot.line_too_long_facts` now skips all `|`
   multiline content lines, which removes the sampled onec-only category and
   removes the previous keyword regex from that hot path. No BSLLS-only or
   range-only category was reproduced by the synthetic BSL014 sample; the
   private batch still has unsampled semantic/range deltas.

9. BSL011 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL011`
   with BSLLS 0.29.0 `CognitiveComplexity` JSON output. Method-level high and
   low complexity cases matched exactly. The sampled BSLLS-only category was a
   complex module-body code block because BSLLS has `checkModuleBody=true` by
   default while the previous BSL011 contract treated module-level code as a
   non-goal. onec now emits BSL011 for module-body cognitive complexity using
   the existing line-level complexity calculator and keeps method metrics
   shared with BSL019. The sampled module-body cases now match BSLLS exactly.
   No synthetic ours-only or range-only category was reproduced; the private
   batch still has unsampled semantic/file-layout deltas.

10. BSL219 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL219`
   with BSLLS 0.29.0 `MissingVariablesDescription` JSON output. Single variable,
   exported variable, multi-name, multi-export, described variable,
   previous-inline group description, and local-variable cases matched BSLLS.
   The sampled range/granularity category was multi-name module declarations:
   onec previously emitted one diagnostic spanning the whole names list, while
   BSLLS emits one diagnostic per variable name and extends the last exported
   variable range through `Экспорт`. `DocumentSnapshot.module_variable_description_facts`
   now emits matching per-name facts. No sampled ours-only or BSLLS-only category
   was reproduced; the private batch still has unsampled semantic/range deltas.

11. BSL131 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL131`
   with BSLLS 0.29.0 `DuplicateRegion` JSON output. Unique region and nested
   same-name region cases produced no diagnostics in both tools. Plain duplicate,
   standard-alias duplicate, and third duplicate groups matched BSLLS after
   aligning the representative fact: BSLLS reports the first region opening once
   per duplicate group, with a range from after `#` through the region name.
   `DocumentSnapshot.duplicate_region_facts` now emits that same representative
   fact instead of reporting later duplicate openings. No sampled ours-only or
   BSLLS-only category was reproduced; private batch exact parity should be
   rerun when the batch completes.

12. BSL013 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL013`
   with BSLLS 0.29.0 `CommentedCode` JSON output and the decompiled
   `CommentedCodeDiagnostic` contract. BSLLS applies `CodeRecognizer` with
   threshold `0.9` to individual comment tokens, then reports the whole adjacent
   comment group when one token is recognized as code. Sampled BSLLS-recognized
   `Если` block, single `Сообщить(...)`, and long assignment cases match onec
   exactly. Sampled ours-only categories are intentionally retained: short or
   generic commented procedure groups, inline assignment comments, embedded
   prose/expression groups, and annotation+method groups. Standalone directive
   comment groups remain rejected because they overreported heavily on the
   corpus and lack executable-code structure by themselves.

13. BSL022 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL022`
   with BSLLS 0.29.0 `UsingModalWindows` JSON output using
   `forceModalityMode=true` for standalone rule semantics. BSLLS reports modal
   global method calls on the full `globalMethodCall` range, from method
   identifier through the closing parenthesis. `DocumentSnapshot.deprecated_warning_facts`
   now uses the same full-call range in the CST path and the line fallback.
   Sampled simple modal call, nested modal call, object call, string, and
   inline-comment cases match BSLLS exactly.

14. BSL036 sampled taxonomy:
   A local synthetic taxonomy probe compared onec `--no-config --select BSL036`
   with BSLLS 0.29.0 `IfConditionComplexity` JSON output using
   `allowedComplexity=3`. Sampled single-line high-complexity condition,
   multiline `ИначеЕсли`, and below-threshold cases matched BSLLS exactly,
   including the expression range after `Если` / `ИначеЕсли` and before
   `Тогда`. No sampled ours-only, BSLLS-only, or range-only category was
   reproduced; remaining private batch range-only entries need sanitized
   examples before any runtime edit.

## Known Gaps

- Full BSLLS parity taxonomy is now available at batch-count level. The
  remaining open work is rule-specific semantic taxonomy and owner decisions
  for the non-exact rules.
- `BSL036` private batch still has unsampled range-only entries; sampled
  single-line and multiline cases match BSLLS exactly, so do not edit runtime
  without sanitized private examples.
- `BSL040` keeps additional `Forms/.../Ext/Module.bsl` findings unless the
  product decision drops that legacy full form module layout.
- `BSL216` does not intentionally match BSLLS on unary `-` after `[` because
  unary minus should not require surrounding spaces.
- `BSL013` does not accept standalone commented annotation/preprocessor
  directives as enough evidence by itself. A probe that did so overreported
  thousands of comment groups on the corpus; annotations remain included when
  adjacent to an already code-like commented method/query block.
- `BSL077` keeps skipping SDBL parse-error blocks. The two remaining BSLLS-only
  reports are in parse-error query blocks that also contain an order clause, so
  they are not accepted as a rule bug without a narrower semantic example.

## Next Cheap Tests

1. Keep `tests/test_rule_contract_gate.py` validating every `BSL*.md` contract
   so invalid dossiers cannot silently accumulate.
