# 03 Method Procedure Contracts Audit

Status: not started.

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
- [ ] BSL212 - open
- [ ] BSL215 - open
- [ ] BSL224 - open
- [ ] BSL228 - open
- [ ] BSL233 - open
- [ ] BSL240 - open
- [ ] BSL254 - open
- [ ] BSL266 - open

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
