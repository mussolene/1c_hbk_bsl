#!/usr/bin/env python
"""Validate diagnostic-rule contract dossiers.

The validator is intentionally boring: it checks that the anti-loop gate has a
complete written contract before a rule implementation is changed. It does not
judge whether the contract is true; tests, parity probes, and review do that.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CONTRACTS_DIR = ROOT / "docs" / "rule-contracts"
CODE_RE = re.compile(r"^BSL\d{3}$")
TARGETED_TESTS_RE = re.compile(
    r"^\s*-\s+Targeted tests:\s*`(?P<command>[^`]+)`",
    re.MULTILINE,
)

REQUIRED_HEADINGS = (
    "Rule Identity",
    "Standard And Product Decision",
    "Semantic Oracle",
    "CST Or Domain Fact Model",
    "Examples",
    "Related-Rule Cluster",
    "BSLLS Parity Taxonomy",
    "Performance Contract",
    "Implementation Decision",
    "Verification Plan",
    "Completion Checklist",
)

REQUIRED_LABELS = (
    "Code",
    "BSLLS compatible name",
    "Rule status",
    "Standard or product policy",
    "Non-goals",
    "Checked language fact",
    "Must diagnose when",
    "Must not diagnose when",
    "Diagnostic anchor token/range",
    "CST/domain object types",
    "Extracted attributes",
    "Parse-error behavior",
    "Shared semantic object",
    "Rules that may report on the same object/range",
    "Intended duplicate policy",
    "Compared input-file set",
    "Config/exclude mode",
    "File-key normalization",
    "Coordinate normalization",
    "Unknown categories",
    "Traversal/fact source",
    "Expected complexity",
    "Change target",
    "Delta category fixed by this change",
    "Targeted tests",
    "Leak check",
    "OACS evidence/checkpoint",
)

TODO_RE = re.compile(r"\bTODO\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUBHEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^- \[(?P<mark>[ xX])\]\s+(?P<label>.+)$", re.MULTILINE)


def _sections(text: str, heading_re: re.Pattern[str]) -> dict[str, str]:
    matches = list(heading_re.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[start:end].strip()
    return sections


def _label_is_filled(text: str, label: str) -> bool:
    pattern = re.compile(rf"^\s*-\s+{re.escape(label)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return False
    value = match.group(1).strip()
    return bool(value) and not TODO_RE.fullmatch(value)


def _numbered_item_count(section: str) -> int:
    return len(re.findall(r"^\s*\d+\.\s+\S", section, re.MULTILINE))


def validate_contract(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    sections = _sections(text, HEADING_RE)
    subsections = _sections(text, SUBHEADING_RE)

    for heading in REQUIRED_HEADINGS:
        if heading not in sections:
            errors.append(f"missing heading: {heading}")

    for label in REQUIRED_LABELS:
        if not _label_is_filled(text, label):
            errors.append(f"missing or TODO label: {label}")

    invalid_section = subsections.get("Invalid Examples", "")
    if _numbered_item_count(invalid_section) < 3 or TODO_RE.search(invalid_section):
        errors.append("invalid examples must contain at least three filled examples")

    negative_section = subsections.get("Valid Negative Twins", "")
    if _numbered_item_count(negative_section) < 3 or TODO_RE.search(negative_section):
        errors.append("valid negative twins must contain at least three filled examples")

    checkbox_matches = list(CHECKBOX_RE.finditer(text))
    if not checkbox_matches:
        errors.append("completion checklist has no checkboxes")
    for checkbox in checkbox_matches:
        if checkbox.group("mark") != "x":
            errors.append(f"unchecked completion item: {checkbox.group('label').strip()}")

    unknown_match = re.search(r"^\s*-\s+Unknown categories:\s*(.+?)\s*$", text, re.MULTILINE)
    if unknown_match and unknown_match.group(1).strip().casefold() not in {"none", "0", "zero"}:
        errors.append("unknown categories must be none/0/zero before implementation")

    return errors


def _declared_code(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s*-\s+Code:\s*(BSL\d{3})\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def targeted_test_command(path: Path) -> list[str] | None:
    text = path.read_text(encoding="utf-8")
    match = TARGETED_TESTS_RE.search(text)
    if not match:
        return None
    try:
        return shlex.split(match.group("command"))
    except ValueError:
        return None


def validate_targeted_test_selector(path: Path) -> list[str]:
    command = targeted_test_command(path)
    if command is None:
        return ["Targeted tests must contain one backticked pytest command"]
    if command[:3] != ["./.venv/bin/python", "-m", "pytest"]:
        return ["Targeted tests must use ./.venv/bin/python -m pytest"]
    if not any(argument == "tests" or argument.startswith("tests/") for argument in command):
        return ["Targeted tests must select repository semantic tests"]

    completed = subprocess.run(
        [*command, "--collect-only"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip().splitlines()
        detail = output[-1] if output else f"pytest exited {completed.returncode}"
        return [f"Targeted tests selector collected no tests: {detail}"]
    return []


def runtime_rule_codes() -> set[str]:
    from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

    return set(RULE_METADATA)


def validate_catalog(
    contracts_dir: Path = CANONICAL_CONTRACTS_DIR,
    *,
    check_selectors: bool = False,
) -> dict[Path, list[str]]:
    contracts = sorted(contracts_dir.glob("BSL*.md"))
    errors: dict[Path, list[str]] = {}
    expected_codes = runtime_rule_codes()
    filenames = {contract.stem for contract in contracts if CODE_RE.fullmatch(contract.stem)}

    catalog_errors: list[str] = []
    missing = sorted(expected_codes - filenames)
    extra = sorted(filenames - expected_codes)
    if missing:
        catalog_errors.append(f"missing runtime contracts: {', '.join(missing)}")
    if extra:
        catalog_errors.append(f"contracts absent from runtime registry: {', '.join(extra)}")

    declared_to_paths: dict[str, list[Path]] = {}
    for contract in contracts:
        declared = _declared_code(contract)
        if declared is not None:
            declared_to_paths.setdefault(declared, []).append(contract)
        contract_errors = validate_contract(contract)
        if declared != contract.stem:
            contract_errors.append(
                f"declared Code {declared or '<missing>'} does not match filename {contract.stem}"
            )
        if check_selectors:
            contract_errors.extend(validate_targeted_test_selector(contract))
        if contract_errors:
            errors[contract] = contract_errors

    duplicates = {code: paths for code, paths in declared_to_paths.items() if len(paths) > 1}
    for code, paths in sorted(duplicates.items()):
        catalog_errors.append(
            f"duplicate declared Code {code}: {', '.join(str(path) for path in paths)}"
        )
    if catalog_errors:
        errors[contracts_dir] = catalog_errors
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contracts", nargs="*", type=Path)
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="validate the canonical catalog against the runtime rule registry",
    )
    parser.add_argument(
        "--check-selectors",
        action="store_true",
        help="prove that each Targeted tests command collects semantic tests",
    )
    args = parser.parse_args(argv)

    if not args.contracts and not args.catalog:
        parser.error("provide contract paths or --catalog")

    failed = False
    if args.catalog:
        catalog_errors = validate_catalog(check_selectors=args.check_selectors)
        if catalog_errors:
            failed = True
            for contract, errors in catalog_errors.items():
                print(f"{contract}: FAIL", file=sys.stderr)
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
        else:
            print(f"{CANONICAL_CONTRACTS_DIR}: PASS")

    for contract in args.contracts:
        errors = validate_contract(contract)
        if args.check_selectors:
            errors.extend(validate_targeted_test_selector(contract))
        if errors:
            failed = True
            print(f"{contract}: FAIL", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"{contract}: PASS")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
