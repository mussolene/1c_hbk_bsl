# 02 Query Metadata Aggregation Audit

Status: in progress.

This audit is the durable routing checklist for
`02-query-metadata-aggregation`. Rule membership comes from
`scripts/diagnostic_rule_matrix.py`.

## Closure Checklist

- [x] BSL174 - exact; owner-module metadata contract
- [x] BSL187 - mini exact; private CST recovery deltas classified
- [x] BSL189 - exact; forbidden metadata names contract
- [x] BSL191 - exact; full outer join phrase contract
- [x] BSL201 - exact private parity; parsed LIKE operand contract
- [x] BSL206 - exact private parity; nested query join CST contract
- [x] BSL207 - exact private parity; virtual table join CST contract
- [ ] BSL209 - open
- [x] BSL211 - exact no-signal; strict 80-character metadata-name contract
- [x] BSL213 - exact no-signal; exported common-module method contract
- [x] BSL214 - exact no-signal; session-module event subscription contract
- [x] BSL220 - exact private parity; unescaped SDBL cross-line string contract
- [x] BSL231 - exact private parity; exported privileged common-module method contract
- [x] BSL232 - exact private parity; per-protected-module session diagnostic contract
- [x] BSL235 - CST partial-query recovery policy; parser-gap deltas classified
- [x] BSL236 - type-aware active-config metadata lookup; virtual-table sources
- [x] BSL238 - scoped query alias contract; private parity classified tail
- [x] BSL241 - exact no-signal; object/child metadata contract
- [x] BSL242 - referenced scheduled-job handler contract; exact private parity
- [x] BSL244 - exact private parity; BSLLS-compatible forbidden form event server-call contract
- [x] BSL246 - exact private no-signal; cached role-index contract and synthetic coverage
- [x] BSL253 - exact private no-signal; CST timeout constructor/assignment contract
- [x] BSL261 - exact private no-signal; CST SafeMode boolean-use contract
- [x] BSL269 - parsed LIKE expression contract; private parity classified tail
- [x] BSL274 - exact private no-signal; form data path metadata contract

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.

## Batch Preflight 2026-06-23

Scope: remaining open rules in `02-query-metadata-aggregation`.

Inputs:
- Private preserved-source-root parity corpus: 31,797 `.bsl` files.
- BSLLS parity helper: `scripts/compare_diag_bslls.py`.
- onec counter: `onec_hbk_bsl check --no-config --format json --select ...`.

Privacy policy: this audit stores only counts and routing categories. It does
not store private paths, source fragments, object names, URLs, or domains.

Aggregate parity:
- `onec=4259`, `bslls=7880`.
- `only_bslls=4046`: `BSL201=2`, `BSL206=22`, `BSL207=10`,
  `BSL235=88`, `BSL236=3500`, `BSL238=88`, `BSL244=32`,
  `BSL269=304`.
- `only_onec=425`: `BSL201=2`, `BSL206=16`, `BSL207=10`, `BSL209=6`,
  `BSL220=48`, `BSL235=16`, `BSL236=98`, `BSL238=16`, `BSL242=11`,
  `BSL244=18`, `BSL253=8`, `BSL269=176`.
- Runtime: `real=144.56s`, `user=232.06s`, `sys=41.72s`.

Our diagnostic counts on the same selected corpus:
- `BSL201=2`, `BSL206=16`, `BSL207=16`, `BSL209=142`, `BSL220=48`,
  `BSL235=20`, `BSL236=3652`, `BSL238=150`, `BSL242=11`, `BSL244=18`,
  `BSL253=8`, `BSL269=176`.

Routing:

| Rule | Runner group | Private corpus signal | Route |
| --- | --- | --- | --- |
| BSL201 | query text | exact | Closed with SDBL `like_expression` operand-shape facts and exact private parity `onec=2`, `bslls=2`. |
| BSL206 | query join | exact | Closed with SDBL `nested_query_source` join facts and exact private parity `onec=22`, `bslls=22`. |
| BSL207 | query join | exact | Closed with SDBL `virtual_table_source` join facts and exact private parity `onec=16`, `bslls=16`. |
| BSL209 | query join | ours-only mismatch | Investigate JOIN ON logical OR boundaries. |
| BSL211 | metadata XML | no signal | Fast-close candidate only with synthetic/mini fixture. |
| BSL213 | metadata XML | no signal | Fast-close candidate only with synthetic/mini fixture. |
| BSL214 | metadata XML | no signal | Fast-close candidate only with synthetic/mini fixture. |
| BSL220 | query text | exact | Closed with BSL-unescaped SDBL cross-line string facts; private parity 31,797 files exact. |
| BSL231 | metadata XML | exact | Closed with exported-method filtering and nested privileged-module call coverage. |
| BSL232 | metadata XML | exact | Closed with per-protected-module session diagnostics and exact private parity. |
| BSL235 | query text | owner decision | Closed with unescaped SDBL parse, recovered query-candidate evidence, and parser-gap suppression; private parity remains classified at `onec=94`, `bslls=92`, `only_onec=30`, `only_bslls=28`. |
| BSL236 | query metadata | parity-classified | Closed with type-aware active-config metadata lookup and virtual-table source extraction; private parity improved to `onec=7078`, `bslls=7054`, `only_bslls=130`, `only_onec=154`. |
| BSL238 | query metadata | parity-classified | Closed with scoped query alias facts and tabular/simple source suppression; private parity improved to `onec=224`, `bslls=222`, `only_bslls=2`, `only_onec=4`. |
| BSL241 | metadata XML | exact no-signal | Closed with synthetic object-child fixtures, form-only exclusion, severity surface fix, and private parity `onec=0`, `bslls=0`. |
| BSL242 | metadata XML | exact | Closed with referenced-handler gating for unreferenced common modules; private parity improved to `onec=0`, `bslls=0`. |
| BSL244 | metadata runtime | exact | Closed with BSLLS-compatible forbidden form event suffixes, exact `&НаСервере` target filtering, call-expression ranges, and private parity `onec=32`, `bslls=32`. |
| BSL246 | metadata XML | exact no-signal | Closed with cached role-index contract, default full-access role allowlist, synthetic positives/negatives, and private parity `onec=0`, `bslls=0`. |
| BSL253 | metadata runtime | exact no-signal | Closed with CST constructor facts, BSLLS-compatible timeout argument positions, later timeout-property assignment suppression, and private parity `onec=0`, `bslls=0`. |
| BSL261 | metadata runtime | exact no-signal | Closed with CST SafeMode call facts, implicit boolean-use contract, synthetic positives/negatives, and private parity `onec=0`, `bslls=0`. |
| BSL269 | query text | parity-classified | Closed with unescaped SDBL `like_expression` facts, original-CST range mapping for matching starts, and private parity improved to `onec=310`, `bslls=304`, `only_bslls=114`, `only_onec=120`. |
| BSL274 | metadata XML | exact no-signal | Closed with form `DataPath` unresolved-marker contract, managed-application scan for forms without modules, synthetic positives/negatives, and private parity `onec=0`, `bslls=0`. |

Next-order policy:
- Close no-signal metadata rules only through contract plus mini fixture; do not
  infer correctness from corpus silence.
- Investigate shared fact clusters together, but commit closure one rule at a
  time.
- Prefer BSL211 next if the goal is a fast safe closure; prefer BSL201 next if
  the goal is to reduce active query-text mismatches.
