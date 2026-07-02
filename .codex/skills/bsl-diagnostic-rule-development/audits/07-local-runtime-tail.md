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
- [ ] BSL151 - open
- [ ] BSL155 - open
- [ ] BSL157 - open
- [ ] BSL169 - open
- [ ] BSL170 - open
- [ ] BSL175 - open
- [ ] BSL176 - open
- [ ] BSL177 - open
- [ ] BSL179 - open
- [ ] BSL182 - open
- [ ] BSL195 - open
- [ ] BSL196 - open
- [ ] BSL198 - open
- [ ] BSL199 - open
- [ ] BSL217 - open
- [ ] BSL221 - open
- [ ] BSL225 - open
- [ ] BSL229 - open
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
