# 07 Local Runtime Tail Audit

Status: complete.

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
- [x] BSL234 - exact current-corpus parity after query type-literal masking
- [x] BSL237 - exact-zero current-corpus parity with existing redundant receiver implementation
- [x] BSL245 - exact-zero current-corpus parity after managed form metadata and split-layout gating
- [x] BSL248 - exact-zero current-corpus parity with existing multiple compiler directive implementation
- [x] BSL249 - exact current-corpus parity with existing style constructor implementation
- [x] BSL252 - exact current-corpus parity with existing CST this-object assignment implementation
- [x] BSL255 - exact current-corpus parity with existing CST try-body number conversion implementation
- [x] BSL257 - exact current-corpus parity with existing CST unary-plus concatenation implementation
- [x] BSL258 - exact current-corpus parity after extracted query-block scope and UTF-8 range mapping
- [x] BSL259 - exact current-corpus parity with existing CST unknown preprocessor symbol implementation
- [x] BSL260 - exact current-corpus parity with existing unsafe FindByCode metadata contract
- [x] BSL262 - exact current-corpus parity after BSLLS-compatible variable comment expression handling
- [x] BSL268 - exact current-corpus parity with existing find-by-string CST implementation
- [x] BSL272 - exact current-corpus parity after split fragment/layout scope gating
- [x] BSL273 - exact current-corpus parity with existing virtual table parameter query-block implementation
- [x] BSL275 - exact current-corpus parity with existing HTTP service handler XML contract
- [x] BSL276 - exact current-corpus parity with existing ProceedWithCall annotation contract
- [x] BSL277 - exact current-corpus parity with existing rollback placement contract
- [x] BSL278 - exact current-corpus parity with existing web service handler XML contract

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
