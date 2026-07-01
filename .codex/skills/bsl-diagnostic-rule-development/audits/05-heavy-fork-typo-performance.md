# 05 Heavy Fork Typo Performance Audit

Status: in progress.

This audit is the durable routing checklist for
`05-heavy-fork-typo-performance`. Rule membership comes from
`scripts/diagnostic_rule_matrix.py`.

## Closure Checklist

- [ ] BSL001 - open
- [x] BSL005 - verified; owner-decision parity tail keeps 18 onec-only IP-shaped dotted numeric literals
- [x] BSL020 - exact private parity; contract-only closure
- [x] BSL027 - exact-zero private parity; contract-only closure
- [x] BSL029 - verified; CST magic-number policy with private parity classified
- [x] BSL030 - verified; 978 exact, 48 paired range-only, 2 onec-only tail reports
- [x] BSL035 - verified; 2055 exact, occurrence/range-policy tail classified
- [x] BSL039 - exact private parity; contract-only closure
- [x] BSL060 - exact private parity; contract-only closure
- [x] BSL066 - exact private parity after chained member-call classification fix
- [x] BSL097 - exact private parity; contract-only closure
- [x] BSL153 - verified; exact private parity after removing stale form-module skip
- [x] BSL171 - verified; exact-zero private parity plus synthetic adjacent-string range alignment
- [x] BSL178 - exact-zero private parity; synthetic deprecated 8.3.17 API coverage
- [x] BSL180 - exact-zero private parity; synthetic safe-mode disabling coverage
- [x] BSL181 - verified; Add support/reset/range fix with classified parity tail
- [x] BSL183 - exact private parity after scope/range/string-filter fixes
- [x] BSL185 - exact private parity after declaration false-positive fix
- [x] BSL186 - exact private parity after multiline trailing comma fix
- [x] BSL197 - exact private parity with existing CST branch-block comparison
- [x] BSL200 - verified with classified line-break parity tail
- [x] BSL202 - exact-zero private parity with existing CST call-pool implementation
- [x] BSL205 - exact-zero private parity with existing role-check implementation
- [x] BSL210 - exact private parity after preserving query state across blank lines
- [x] BSL218 - exact private parity with existing CST temp-file lifecycle implementation
- [x] BSL223 - exact private parity after nested constructor arity/range fixes
- [x] BSL227 - exact-zero private parity with existing one-statement scanner
- [x] BSL230 - exact private parity with existing transaction pairing implementation
- [x] BSL243 - exact-zero private parity after full receiver self-insertion fix
- [x] BSL250 - exact private parity with existing TempFilesDir implementation
- [ ] BSL256 - open
- [ ] BSL263 - open
- [ ] BSL265 - open
- [ ] BSL267 - open
- [ ] BSL271 - open
- [ ] BSL279 - open

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
