# 06 Line Text Style Security Audit

Status: not started.

This audit is the durable routing checklist for
`06-line-text-style-security`. Rule membership comes from
`scripts/diagnostic_rule_matrix.py`.

## Closure Checklist

- [x] BSL006 - exact current-corpus parity with existing hardcoded path implementation
- [x] BSL023 - exact current-corpus parity after service-tag comment range fix
- [x] BSL024 - classified current-corpus parity; no BSLLS-only deltas after comment spacing refinement
- [x] BSL025 - exact-zero current-corpus parity with existing CST empty-statement implementation
- [x] BSL055 - exact current-corpus parity with existing consecutive empty lines implementation
- [x] BSL149 - exact current-corpus parity after dynamic union select-candidate recovery
- [x] BSL150 - exact-zero current-corpus parity with default empty badWords pattern
- [x] BSL184 - exact-zero current-corpus parity with existing server common-module dynamic-code implementation
- [x] BSL188 - exact current-corpus parity with existing CST filesystem access implementation
- [x] BSL203 - exact current-corpus parity with existing CST internet access implementation
- [x] BSL208 - classified current-corpus parity; remaining deltas are mixed-script occurrence policy
- [x] BSL222 - exact-zero current-corpus parity with existing localized template implementation
- [x] BSL226 - exact-zero current-corpus parity with existing OS users method implementation
- [x] BSL239 - exact-zero current-corpus parity with default empty reservedWords pattern
- [x] BSL247 - exact-zero current-corpus parity with existing privileged-mode call implementation
- [ ] BSL251 - open
- [ ] BSL264 - open

## Done Criteria

Set a rule to checked only after its contract, targeted verification, parity or
owner decision, OACS evidence, checkpoint, and commit exist.
