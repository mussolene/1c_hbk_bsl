# 03 Method Procedure Contracts Audit

Status: in progress; BSL224+ require preserved-source-root BSLLS parity taxonomy before closure.

This audit is the durable routing checklist for
`03-method-procedure-contracts`. Rule membership comes from
`scripts/diagnostic_rule_matrix.py`.

## Closure Checklist

- [x] BSL007 - parity-classified; current private batch has no ours-only deltas and seven classified BSLLS-only runtime/state divergences
- [x] BSL008 - exact private parity after method-name range alignment
- [x] BSL015 - exact private parity after parameter-list range alignment
- [x] BSL031 - exact private parity via shared parameter-list range facts
- [x] BSL062 - parity-classified; BSLLS CLI/runtime emits zero UnusedParameters diagnostics in current environment
- [x] BSL148 - parity-classified; fixed try/successor-return CFG and severity; final private parity has no BSLLS-only diagnostics, ours-only loop-exit cases kept as stricter semantic checks
- [x] BSL192 - exact private parity after narrowing predicate to Russian `Получить*`
- [x] BSL193 - exact private parity after limiting out-parameter scan to function body
- [x] BSL194 - exact private parity zero; contract-only closure
- [x] BSL212 - exact private parity after omitted-position detection and full-call range alignment
- [x] BSL215 - parity-classified; CST comment-block extraction and continuation range fixes applied, exact parity deferred to a dedicated BSLLS description-parser layer
- [x] BSL224 - exact private parity after CST anchor range fix and regex fallback removal
- [ ] BSL228 - reopened; requires preserved-source-root parity confirmation after metadata change
- [ ] BSL233 - reopened; block parity has unclassified onec-only deltas
- [ ] BSL240 - reopened; block parity has unclassified onec-only deltas
- [ ] BSL254 - reopened; block parity has high-volume unclassified BSLLS-only deltas
- [ ] BSL266 - reopened; block parity has unclassified onec-only deltas

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
