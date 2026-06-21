# Diagnostic Rule Contract Template

Copy this template for any diagnostic-rule implementation, repair, parity
review, or release-blocking investigation. Keep corpus paths, source fragments,
customer names, URLs, and private identifiers out of the dossier.

## Rule Identity

- Code: BSL000
- BSLLS compatible name: TODO
- Public name/i18n key: TODO
- Default message/i18n key: TODO
- Description/i18n key: TODO
- Severity: TODO
- Parameters/defaults: TODO
- Rule status: unknown

Allowed statuses: unknown, contracted, implemented, parity-classified,
verified, released, deferred.

## Standard And Product Decision

- Standard or product policy: TODO
- Why this diagnostic exists: TODO
- Non-goals: TODO
- Keep/drop decision: TODO

## Semantic Oracle

- Checked language fact: TODO
- Must diagnose when: TODO
- Must not diagnose when: TODO
- Diagnostic anchor token/range: TODO
- Quick-fix target, if any: TODO

## CST Or Domain Fact Model

- Parser/tree source: TODO
- CST/domain object types: TODO
- Extracted attributes: TODO
- Parse-error behavior: TODO
- Textual/regex behavior, only if genuinely textual: TODO

## Examples

### Invalid Examples

1. TODO
2. TODO
3. TODO

### Valid Negative Twins

1. TODO
2. TODO
3. TODO

### Edge Examples

- Comments: TODO
- Strings: TODO
- Preprocessor: TODO
- Multiline: TODO
- Nested constructs: TODO
- BSL/SDBL variants, if relevant: TODO

## Related-Rule Cluster

- Shared semantic object: TODO
- Rules that may report on the same object/range: TODO
- Intended duplicate policy: TODO
- Cluster fixture or probe: TODO

## BSLLS Parity Taxonomy

- Compared input-file set: TODO
- Config/exclude mode: TODO
- File-key normalization: TODO
- Coordinate normalization: TODO
- Exact common: TODO
- Line/common semantic common: TODO
- Ours-only categories: TODO
- BSLLS-only categories: TODO
- Range-only categories: TODO
- Known BSLLS defects: TODO
- Unknown categories: none

## Performance Contract

- Traversal/fact source: TODO
- Expected complexity: TODO
- Shared-pass reuse: TODO
- Before/after measurement, if changed: TODO

## Implementation Decision

- Change target: TODO
- Delta category fixed by this change: TODO
- Why not another layer: TODO
- Rollback signal: TODO

## Verification Plan

- Targeted tests: TODO
- Synthetic fixture/module: TODO
- Related-rule tests: TODO
- Parity command/artifact: TODO
- Performance command/artifact: TODO
- Ruff/lint: TODO
- Leak check: TODO
- OACS evidence/checkpoint: TODO

## Completion Checklist

- [ ] Semantic oracle is explicit.
- [ ] CST/domain fact model is explicit.
- [ ] At least three invalid examples exist.
- [ ] At least three valid negative twins exist.
- [ ] Related-rule cluster is reviewed.
- [ ] BSLLS deltas are classified or parity is explicitly deferred.
- [ ] Unknown high-volume delta categories are zero.
- [ ] Implementation target and fixed delta category are named.
- [ ] Verification plan covers tests, lint, leak check, evidence, and checkpoint.
