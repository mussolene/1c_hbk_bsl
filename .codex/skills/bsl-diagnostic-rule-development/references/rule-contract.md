# Rule Contract

Use this reference when a diagnostic rule is implemented, reviewed, repaired, or compared with BSLLS.

## Rule State Gate

Every diagnostic iteration must start by opening or creating a rule dossier from
`rule-contract-template.md`. The only canonical catalog is
`docs/rule-contracts`; skill-local copies are not rule state. Run:

```bash
./.venv/bin/python scripts/validate_rule_contract.py docs/rule-contracts/BSL###.md
```

The template is allowed to fail validation because it contains placeholders.
A rule-specific dossier must pass validation before editing diagnostic
implementation code. If it does not pass, the only allowed work is to inspect
facts, improve the dossier, add neutral fixtures, or fix the validation/probe
tooling.

Rule states:

- `unknown`: no trusted contract exists.
- `contracted`: oracle, facts, related rules, and examples are explicit.
- `implemented`: code was changed against a contracted delta category.
- `parity-classified`: BSLLS/ours deltas are categorized, or parity is deferred
  with a written reason.
- `verified`: tests, lint, leak check, and OACS evidence/checkpoint are present.
- `released`: the verified state was included in a pushed release/tag.
- `deferred`: the rule is intentionally not changed now, with a reason.

If a rule returns after being marked `verified`, do not edit implementation
first. Reopen the dossier and mark which gate field was wrong, incomplete, or
stale. Repeating the same rule without a failed gate field is a process
failure.

## Rule Dossier

Create a short dossier before code changes:

- Rule: `BSL###` and BSLLS compatible name.
- User-facing text: i18n name, message, description.
- Standard: the 1C/BSL/platform rule or product policy that justifies the diagnostic.
- Scope: source files, metadata files, query text, module kind, or configuration context.
- Parameters: thresholds, allowlists, compatibility switches, and defaults.
- Severity: why this severity is correct.
- Related rules: rules that may fire on the same semantic object or nearby range.
- Non-goals: cases the rule must not diagnose.

## Semantic Target

Define the exact target before implementation:

- CST/domain object: e.g. `assignment_statement`, `return_statement`, `query`, `procedure_definition`, `parameter`.
- Diagnostic token/range: the token that should receive the diagnostic and where quick-fix should apply.
- Valid examples: at least three cases that must not report.
- Invalid examples: at least three cases that must report.
- Ambiguous examples: comments, strings, preprocessing, multiline forms, nested constructs, malformed syntax.

If the rule cannot be described at this level, do not implement it yet.

## Fact Taxonomy Gate

Before editing a rule implementation, build a sanitized fact-level comparison.

For BSLLS-backed rules:

1. Identify the BSLLS semantic object from implementation, not from guesswork:
   visitor/listener method, parser context, token used for diagnostic, and skip conditions.
2. Build our equivalent CST/domain fact set:
   semantic key, CST node type, start/end lines, terminal token, terminal semicolon state, parse-error state, config/suppression state.
3. Compare facts before diagnostics:
   common facts, ours-only facts, BSLLS-only facts, range-only facts, duplicate facts.
4. Validate parity mechanics before interpreting deltas:
   same input-file set, same config/exclude mode, same rule-selection mode, and
   stable normalized `file_key` for coordinate comparison. BSLLS/SARIF/LSP
   ranges use zero-based `range.start.line`/`range.end.line`; the onec CLI JSON
   `Diagnostic.line`/`end_line` fields are one-based while `character` fields
   are zero-based LSP columns. Normalize this before comparing coordinates.
5. Classify every high-volume delta by root cause.
6. Only then edit code.

Required delta labels:

- `semantic-mismatch`: one side reports a different language object.
- `range-only`: both report the same object, but location differs.
- `parser-cst-difference`: parser trees represent the same valid syntax differently.
- `config-or-suppression`: rule disabled or suppressed differently.
- `duplicate`: one side reports the same object more than once.
- `known-bslls-defect`: BSLLS differs from the language standard or crashes.
- `unknown`: not acceptable for implementation edits.

If any large category remains `unknown`, stop and gather better facts.
The rule-specific dossier must state `Unknown categories: none` before
implementation edits. If that is false, keep investigating facts instead of
patching the rule.
If a large category is explained by input-file selection, project config,
exclude rules, stale artifacts, or path/file-key normalization, fix the parity
procedure first and do not change the diagnostic rule.

## Implementation Contract

- Prefer existing CST helpers/domain models over new ad hoc parsers.
- Keep rule logic local to the rule or a shared semantic pass only when multiple rules need the same facts.
- Do not add fallback when a valid CST is available.
- Do not duplicate messages inside rule bodies; diagnostics should resolve text through the central rule catalog/i18n.
- Do not use corpus-specific names, paths, URLs, domains, strings, or private examples in tests, docs, comments, commits, OACS evidence, or final replies.
- Keep line/regex logic only for line-style rules such as line length, spelling in comments, or truly textual conventions.
- For malformed CST, either skip structural rules or explicitly route only `BSL001`; do not patch semantic rules with brittle recovery filters.

## Related-Rule Chain

When several rules touch the same node:

1. Name the shared semantic object.
2. List every enabled rule that can report on it.
3. Decide emission order and de-duplication.
4. Confirm whether multiple diagnostics are useful to a user.
5. Add synthetic examples for each intentional overlap and each forbidden duplicate.

Examples of chains:

- statement termination: `BSL025`, `BSL030`, parser `BSL001`.
- empty control flow: `BSL004`, `BSL025`, `BSL028`.
- method contract: parameter count, unused parameter, missing descriptions, return contract.
- query text: query CST rules, query metadata rules, query runtime rules.

## Synthetic Module Strategy

Prefer a small number of dense synthetic modules over scattered one-off fixtures.

Use comments to mark expected diagnostics, but keep comments generic:

```bsl
// EXPECT: BSL030 missing semicolon after assignment
Значение = 1

// OK: statement has terminator
Значение = 1;
```

Synthetic modules should cover:

- canonical valid and invalid cases;
- Russian and English syntax when supported;
- nested blocks and adjacent related-rule cases;
- multiline expressions and string literals;
- query literals and SDBL CST cases;
- comments and suppression comments;
- preprocessing;
- malformed syntax only for `BSL001` or explicit parser tests.

Do not include private corpus code or recognizable business/domain names.

## Parity Procedure

1. Run our CLI with exact `--select BSL###` and JSON/SARIF output.
2. Run BSLLS `analyze` with `mode=ONLY` for the compatible diagnostic name.
3. Prove both tools analyzed the same file set. Record whether project config
   and exclude rules are enabled or disabled. For rule semantics parity, prefer
   disabled project excludes unless the test explicitly validates product config
   behavior.
4. Normalize to:
   rule code, relative sanitized file key, line, column, end line, end column.
   For BSLLS JSON, convert LSP ranges to onec diagnostic coordinates with
   `line = range.start.line + 1` and `end_line = range.end.line + 1`; keep
   `character` and `end_character` unchanged as zero-based LSP columns.
   Resolve BSLLS file identity per diagnostic, not only per fileinfo: first use
   `diagnostic.relatedInformation[*].location.uri` when it points into the
   current corpus, then remap any known temporary/source-root prefix in
   `fileinfo.path` to the current corpus root, then fall back to `fileinfo.mdoRef`
   if it is a real path, then `fileinfo.path`. If a BSLLS artifact contains metadata refs such as
   `DataProcessor.Name` plus generic module names like `ObjectModule.bsl` or
   `Module.bsl`, use a metadata-ref-to-EDT-path resolver before comparing. Do
   not compare unmappable entries by basename.
5. Compare:
   exact match, line-only match, statement/key match, ours-only, BSLLS-only.
6. Classify every delta category:
   semantic mismatch, range-only, parser/CST difference, config difference, duplicate, suppression, or known BSLLS defect.
7. Do not print or store private paths/source text in public evidence.

Parity is evidence, not the source of truth. The source of truth is the rule semantics and the BSL/platform standard.

## Performance Contract

- Prefer one CST traversal for a related rule family.
- Avoid reparsing query text or module text per rule when a shared fact can be cached.
- Measure on the same corpus before/after if the rule traverses many nodes or query text.
- Report rule time and total diagnostic time when performance is part of the task.
- Stop if a correctness fix causes material slowdown without a profiling explanation.

## Done Criteria

A rule iteration is done only when:

- AC1 semantics are stated and checked against standard/description.
- AC2 implementation follows CST/domain contract.
- AC3 related-rule overlap is reviewed.
- AC4 synthetic tests cover valid, invalid, and edge cases.
- AC5 targeted tests pass.
- AC6 relevant broader tests and `ruff` pass.
- AC7 parity is run or explicitly deferred with reason.
- AC8 leak check passes.
- AC9 OACS evidence and checkpoint exist.

If any criterion fails, do not claim the rule is complete.
