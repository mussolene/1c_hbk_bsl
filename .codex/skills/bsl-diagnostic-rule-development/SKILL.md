---
name: bsl-diagnostic-rule-development
description: Semantic workflow for implementing, reviewing, or fixing onec-hbk-bsl diagnostic rules. Use for BSL/1C rule semantics, CST or tree-sitter behavior, BSLLS parity, performance, synthetic fixtures, related-rule overlap, and questions about whether a rule matches its documented language behavior.
---

# BSL Diagnostic Rule Development

Implement rules from language semantics, not from parity counts or isolated
corpus examples.

## Workflow

1. State acceptance criteria for semantics, implementation, performance,
   related-rule consistency, synthetic coverage, parity, and evidence.
2. Read the public rule page in `docs/rule-contracts/BSL###.md`, runtime metadata,
   message localization, configuration parameters, and cited standard.
3. Define the semantic oracle: the exact statement, expression, query clause,
   declaration, metadata object, or other language fact that may be diagnosed.
4. Name the CST nodes or domain objects and the exact token/range that receives
   the diagnostic.
5. Review every enabled rule that can report on the same semantic object or
   range. Keep overlapping reports only when they explain distinct defects.
6. For BSLLS-backed behavior, compare equivalent semantic facts first. Classify
   deltas as semantic, range-only, parser/CST, configuration/suppression,
   duplicate, or a known upstream defect.
7. Reuse tree-sitter/SDBL CST, `DocumentSnapshot`, or an existing domain model
   for structural rules. Use regex or line logic only for genuinely textual
   semantics.
8. Add compact positive, negative-twin, range, malformed-input, comment,
   string, preprocessing, multiline, nested, and overlap tests as relevant.
   `BSL001` must also cover broken documents.
9. Run targeted tests, relevant wider tests, Ruff, generated documentation,
   `git diff --check`, leak checks, and performance/parity probes as needed.
10. Record OACS evidence and a checkpoint before claiming completion.

## Change Gate

Do not edit rule logic until all of these are explicit:

- the semantic oracle;
- the CST/domain fact model;
- the exact diagnostic anchor;
- the related-rule cluster;
- the major current delta categories and their root causes;
- the category the proposed change fixes;
- the compared input set, configuration mode, coordinate normalization, and
  sanitized file-key strategy when parity is used.

If the gate is incomplete, inspect, instrument, improve tests, or clarify the
public rule documentation before changing behavior.

## Verification

Use the project environment for every Python command.

```bash
./.venv/bin/python -m pytest <targeted-tests> -q --no-cov
./.venv/bin/python scripts/build_diagnostic_rules_doc.py
git diff --exit-code -- docs/diagnostic-rules.md docs/rule-contracts
./.venv/bin/python -m ruff check .
git diff --check
```

Run private parity only with reproducible inputs and normalized coordinates.
Never persist or report private paths, source text, names, URLs, domains, or
identifiers; report sanitized counts and categories only.

## Decision Rules

- Prefer the language or platform standard over parity when they conflict.
- Separate range differences from semantic differences.
- Share semantic passes when multiple rules need the same CST walk.
- Reject a parity improvement that makes the rule less correct.
- Stop and profile when performance regresses materially.
- Update the public page when user-visible behavior, configuration, examples,
  severity, aliases, or suppressions change.
