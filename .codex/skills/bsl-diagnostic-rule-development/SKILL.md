---
name: bsl-diagnostic-rule-development
description: Semantic workflow for implementing, reviewing, or fixing onec-hbk-bsl diagnostic rules. Use when Codex works on BSL/1C diagnostic rules, CST/tree-sitter behavior, BSLLS parity, rule performance, synthetic diagnostic fixtures, rule chains on the same semantic node, or questions like "is this rule correct by the language standard and its description?"
---

# BSL Diagnostic Rule Development

Use this skill to make diagnostic-rule work boring, repeatable, and evidence-based.
Do not start from parity counts or isolated corpus examples. Start from the rule's language semantics and finish with tests, performance, parity, and OACS evidence.

## Required Workflow

1. State acceptance criteria before editing:
   `AC1 rule semantics`, `AC2 correct implementation`, `AC3 performance`, `AC4 related-rule consistency`, `AC5 synthetic coverage`, `AC6 BSLLS parity`, `AC7 verification/evidence`.

2. Open or create the rule contract dossier before editing:
   use `references/rule-contract-template.md` as the minimum shape and run
   `scripts/validate_rule_contract.py <dossier.md>` before implementation.
   If no dossier exists, write one first. A missing dossier is a blocker, not
   a TODO.

3. Read the rule contract:
   public code `BSL###`, compatible BSLLS name, i18n name/message/description, severity, config parameters, and documented standard behind the rule.

4. Decide whether the rule is necessary:
   keep it only if it maps to a real BSL/platform standard, a clear product policy, or a BSLLS-compatible diagnostic the project intentionally supports. If the rule is only parity noise, stop and report that.

5. Define the semantic target:
   specify exactly which language object is checked: statement, expression, query clause, method declaration, parameter, module region, metadata object, etc. Name the CST node types and the exact token/range that should receive the diagnostic.

6. Build a fact-level taxonomy before changing rule code:
   compare semantic facts, not diagnostics first. For BSLLS-backed rules, identify the BSLLS visitor/listener object (for example `StatementContext`) and build the equivalent CST/domain fact set. Stop if you cannot explain every major delta category by root cause.

7. Check related rules before changing code:
   rules touching the same node, range, or standard must be reviewed together. Prevent duplicate reports unless both diagnostics are intentionally valid and explain different defects.

8. Implement from CST or structured domain models:
   use tree-sitter/SDBL CST or existing domain objects for structural rules. Do not add regex fallback for valid CST paths. Regex/line logic is acceptable only for rules whose semantics are genuinely textual.

9. Build or update synthetic coverage:
   add compact synthetic BSL modules or fixtures that cover valid/invalid examples, edge cases, comments, strings, preprocessing, multiline forms, nested forms, and related-rule overlap. `BSL001` is the exception: it must include broken documents.

10. Run parity after semantic correctness:
   compare our CLI and BSLLS on the established private corpus with the same
   input-file set and the same config/exclude mode. Persist the normalized
   private `file_key` used for comparison in the temporary parity artifact, and
   normalize BSLLS zero-based LSP ranges to the onec CLI diagnostic coordinate
   model before comparing. Without reproducible file-key and coordinate
   normalization, coordinate deltas are invalid for rule-code edits. Do not leak
   paths, source text, names, URLs, domains, or private identifiers. Report only
   counts and sanitized categories.

11. Run verification:
   use `./.venv/bin/python` for Python. Run targeted tests first, then relevant wider tests, `ruff`, `git diff --check`, leak checks, and performance/parity probes as needed.

12. Record OACS evidence and checkpoint before claiming done.

## Red Gate

Do not edit a diagnostic implementation until all are true:

- the rule's semantic oracle is named;
- the CST/domain fact model is named;
- current deltas are classified as semantic mismatch, range-only, parser/CST difference, config/suppression, duplicate, or known BSLLS defect;
- each high-volume delta category has a root cause;
- the proposed code change says which category it fixes.
- the compared input-file set, config/exclude mode, and normalized file-key
  strategy are stated.
- `scripts/validate_rule_contract.py` passes for the rule dossier.

If this gate is not satisfied, only inspect, instrument, document, or improve synthetic fixtures/skill instructions.

## Anti-Loop Rule Gate

Every rule iteration must leave a durable rule state. The state is not "fixed"
until the dossier records all of these fields:

- semantic oracle: the language fact the rule is allowed to diagnose;
- CST/domain fact model: exact node/object types and extracted attributes;
- negative twin cases: valid snippets that are intentionally close to invalid
  snippets;
- related-rule cluster: every enabled rule that can report on the same semantic
  object, range, or user action;
- delta taxonomy: BSLLS/ours differences classified as semantic mismatch,
  range-only, parser/CST difference, config/suppression, duplicate, known BSLLS
  defect, or not compared with a reason;
- owner decision: whether the next change edits rule logic, shared facts,
  tests, parity tooling, docs, or nothing.

If a rule comes back after being marked done, do not patch it immediately.
First rerun the dossier through the anti-loop gate and identify which field was
wrong or missing. A repeated rule without a failed gate field means the process
failed, not just the implementation.

## Decision Rules

- If BSLLS differs from the language standard, prefer the standard and document the difference.
- If our result differs from BSLLS because of range/column only, classify it separately from semantic mismatch.
- If a rule catches a node already handled by another rule, decide whether to merge, suppress one, or keep both with distinct messages.
- If the implementation needs the same CST walk as another rule, consider one shared semantic pass that emits multiple rule facts.
- If a fix makes parity better but makes the rule less correct, reject the fix.
- If performance worsens materially, stop and profile before continuing.

## Reference

Read `references/rule-contract.md` when implementing or reviewing a diagnostic rule. It contains the checklist, synthetic-module pattern, parity procedure, and done criteria.
