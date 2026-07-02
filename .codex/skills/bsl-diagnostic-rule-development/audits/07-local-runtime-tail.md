# 07 Local Runtime Tail Audit

Status: not started.

This audit is the durable routing checklist for `07-local-runtime-tail`. Rule
membership comes from `scripts/diagnostic_rule_matrix.py`.

## Closure Checklist

- [x] BSL002 - exact current-corpus parity with existing method-size implementation
- [x] BSL003 - exact current-corpus parity with existing API-region export implementation
- [x] BSL004 - exact current-corpus parity with existing CST empty-block implementation
- [x] BSL009 - exact-zero current-corpus parity with existing CST self-assign implementation
- [x] BSL028 - exact current-corpus parity with existing CST empty-exception implementation
- [x] BSL032 - exact current-corpus parity with existing function-return implementation
- [x] BSL033 - exact current-corpus parity after execute-call range refinement
- [x] BSL041 - exact current-corpus parity with existing deprecated-message implementation
- [x] BSL042 - exact-zero current-corpus parity with existing unused-local-method implementation
- [x] BSL047 - exact current-corpus parity with existing magic-date implementation
- [x] BSL051 - exact current-corpus parity after dirty-CST local unreachable fallback
- [x] BSL052 - exact-zero current-corpus parity with CST identical-expression implementation
- [x] BSL054 - exact current-corpus parity after export-variable range alignment
- [x] BSL064 - exact-zero current-corpus parity with existing CST procedure-return implementation
- [x] BSL065 - count parity with classified method-doc parser-context boundary after return-description parsing fixes
- [x] BSL151 - exact current-corpus parity with existing CST transaction-begin placement implementation
- [x] BSL155 - exact-zero current-corpus parity after whole-module scope and preprocessor-region handling
- [x] BSL157 - exact current-corpus parity with synthetic commit-placement coverage
- [x] BSL169 - exact-zero current-corpus parity after split-form layout scope fix
- [x] BSL170 - exact-zero current-corpus parity with existing needless compilation directive implementation
- [x] BSL175 - exact-zero current-corpus parity after docs-listed chart method coverage
- [x] BSL176 - exact current-corpus parity after platform/member surface and BSLLS-style deprecated doc-comment semantics
- [x] BSL177 - exact-zero current-corpus parity after full documented 8.3.10 client-method coverage and method-token range alignment
- [x] BSL179 - exact-zero current-corpus parity with deprecated managed-form type contract and synthetic negatives
- [x] BSL182 - exact-zero current-corpus parity after CST AutoTest single-return branch implementation
- [x] BSL195 - exact current-corpus parity with get-form method contract and receiver-call coverage
- [x] BSL196 - exact-zero current-corpus parity with global 8.3.12 method-collision contract
- [x] BSL198 - exact-zero current-corpus parity with CST duplicated-condition contract and non-skipping synthetic coverage
- [x] BSL199 - exact current-corpus parity with CST elseif-without-else contract and synthetic coverage
- [x] BSL217 - exact current-corpus parity with temp-storage get/delete scope contract and existing fixture coverage
- [x] BSL221 - exact-zero current-corpus parity with declared-language NStr contract and synthetic clean coverage
- [x] BSL225 - exact current-corpus parity with structure constructor value-count contract and fixed-structure coverage
- [x] BSL229 - exact-zero current-corpus parity with ordinary-app support XML contract and recommended-flags negative coverage
- [ ] BSL234 - open
- [ ] BSL237 - open
- [ ] BSL245 - open
- [ ] BSL248 - open
- [ ] BSL249 - open
- [ ] BSL252 - open
- [ ] BSL255 - open
- [ ] BSL257 - open
- [ ] BSL258 - open
- [ ] BSL259 - open
- [ ] BSL260 - open
- [ ] BSL262 - open
- [ ] BSL268 - open
- [ ] BSL272 - open
- [ ] BSL273 - open
- [ ] BSL275 - open
- [ ] BSL276 - open
- [ ] BSL277 - open
- [ ] BSL278 - open

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
