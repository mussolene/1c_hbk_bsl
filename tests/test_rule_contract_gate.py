from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    path = ROOT / "scripts" / "validate_rule_contract.py"
    spec = importlib.util.spec_from_file_location("validate_rule_contract", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bsl_rule_skill_contains_anti_loop_gate() -> None:
    skill = (ROOT / ".codex" / "skills" / "bsl-diagnostic-rule-development" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "## Anti-Loop Rule Gate" in skill
    assert "scripts/validate_rule_contract.py" in skill
    assert "semantic oracle" in skill
    assert "related-rule cluster" in skill
    assert "delta taxonomy" in skill


def test_rule_contract_reference_points_to_template_and_gate() -> None:
    reference = (
        ROOT
        / ".codex"
        / "skills"
        / "bsl-diagnostic-rule-development"
        / "references"
        / "rule-contract.md"
    ).read_text(encoding="utf-8")

    assert "Rule State Gate" in reference
    assert "rule-contract-template.md" in reference
    assert "Unknown categories: none" in reference


def test_validate_rule_contract_rejects_template_todos() -> None:
    validator = _load_validator()
    template = (
        ROOT
        / ".codex"
        / "skills"
        / "bsl-diagnostic-rule-development"
        / "references"
        / "rule-contract-template.md"
    )

    errors = validator.validate_contract(template)

    assert errors
    assert any("TODO" in error for error in errors)


def test_validate_rule_contract_accepts_complete_contract(tmp_path: Path) -> None:
    validator = _load_validator()
    contract = tmp_path / "bsl999-contract.md"
    contract.write_text(
        """
# BSL999 Contract

## Rule Identity

- Code: BSL999
- BSLLS compatible name: ExampleRule
- Public name/i18n key: rule.example.name
- Default message/i18n key: rule.example.message
- Description/i18n key: rule.example.description
- Severity: error
- Parameters/defaults: none
- Rule status: contracted

## Standard And Product Decision

- Standard or product policy: Example standard.
- Why this diagnostic exists: Prevents an example defect.
- Non-goals: Valid nearby constructs.
- Keep/drop decision: keep

## Semantic Oracle

- Checked language fact: Example semantic fact.
- Must diagnose when: The invalid form appears.
- Must not diagnose when: The valid twin appears.
- Diagnostic anchor token/range: the invalid keyword.
- Quick-fix target, if any: none

## CST Or Domain Fact Model

- Parser/tree source: BSL CST
- CST/domain object types: example_node
- Extracted attributes: name, range
- Parse-error behavior: skip
- Textual/regex behavior, only if genuinely textual: none

## Examples

### Invalid Examples

1. invalid A
2. invalid B
3. invalid C

### Valid Negative Twins

1. valid A
2. valid B
3. valid C

### Edge Examples

- Comments: covered
- Strings: covered
- Preprocessor: covered
- Multiline: covered
- Nested constructs: covered
- BSL/SDBL variants, if relevant: not relevant

## Related-Rule Cluster

- Shared semantic object: example_node
- Rules that may report on the same object/range: BSL998
- Intended duplicate policy: no duplicate
- Cluster fixture or probe: tests/example.bsl

## BSLLS Parity Taxonomy

- Compared input-file set: synthetic only
- Config/exclude mode: disabled
- File-key normalization: relative synthetic key
- Coordinate normalization: one-based line, zero-based character
- Exact common: 1
- Line/common semantic common: 1
- Ours-only categories: none
- BSLLS-only categories: none
- Range-only categories: none
- Known BSLLS defects: none
- Unknown categories: none

## Performance Contract

- Traversal/fact source: single CST traversal
- Expected complexity: O(nodes)
- Shared-pass reuse: none
- Before/after measurement, if changed: not changed

## Implementation Decision

- Change target: rule logic
- Delta category fixed by this change: semantic-mismatch
- Why not another layer: parser facts are sufficient
- Rollback signal: negative twin fails

## Verification Plan

- Targeted tests: pytest tests/example.py
- Synthetic fixture/module: tests/fixtures/example.bsl
- Related-rule tests: pytest tests/related.py
- Parity command/artifact: deferred, synthetic-only
- Performance command/artifact: pytest performance smoke
- Ruff/lint: ruff check
- Leak check: rg private tokens
- OACS evidence/checkpoint: required

## Completion Checklist

- [x] Semantic oracle is explicit.
- [x] CST/domain fact model is explicit.
- [x] At least three invalid examples exist.
- [x] At least three valid negative twins exist.
- [x] Related-rule cluster is reviewed.
- [x] BSLLS deltas are classified or parity is explicitly deferred.
- [x] Unknown high-volume delta categories are zero.
- [x] Implementation target and fixed delta category are named.
- [x] Verification plan covers tests, lint, leak check, evidence, and checkpoint.
""".strip(),
        encoding="utf-8",
    )

    assert validator.validate_contract(contract) == []


def test_rule_contracts_are_complete() -> None:
    validator = _load_validator()
    contracts_dir = ROOT / "docs" / "rule-contracts"
    contracts = sorted(contracts_dir.glob("BSL*.md"))

    assert len(contracts) == 180
    assert {contract.stem for contract in contracts} == validator.runtime_rule_codes()
    assert validator.validate_catalog() == {}


def test_catalog_rejects_missing_extra_and_duplicate_codes(tmp_path: Path, monkeypatch) -> None:
    validator = _load_validator()
    source = ROOT / "docs" / "rule-contracts" / "BSL001.md"
    first = tmp_path / "BSL001.md"
    duplicate = tmp_path / "BSL999.md"
    shutil.copyfile(source, first)
    shutil.copyfile(source, duplicate)
    monkeypatch.setattr(validator, "runtime_rule_codes", lambda: {"BSL001", "BSL002"})

    errors = validator.validate_catalog(tmp_path)
    catalog_errors = errors[tmp_path]

    assert any("missing runtime contracts: BSL002" in error for error in catalog_errors)
    assert any(
        "contracts absent from runtime registry: BSL999" in error for error in catalog_errors
    )
    assert any("duplicate declared Code BSL001" in error for error in catalog_errors)


def test_required_rule_selectors_collect_semantic_tests() -> None:
    validator = _load_validator()
    contracts_dir = ROOT / "docs" / "rule-contracts"

    assert validator.validate_targeted_test_selector(contracts_dir / "BSL248.md") == []
    assert validator.validate_targeted_test_selector(contracts_dir / "BSL260.md") == []
