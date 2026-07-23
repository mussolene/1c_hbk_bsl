from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_release.py"
SPEC = importlib.util.spec_from_file_location("verify_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_release)


def _coverage(path: Path, parser_covered: int = 63) -> Path:
    data = {
        "totals": {"percent_covered": 80.5},
        "files": {
            "src/onec_hbk_bsl/parser/example.py": {
                "executed_lines": list(range(1, parser_covered + 1)),
                "missing_lines": list(range(parser_covered + 1, 101)),
                "summary": {
                    "covered_lines": parser_covered,
                    "num_statements": 100,
                },
            },
            "src/onec_hbk_bsl/lsp/example.py": {
                "executed_lines": list(range(1, 75)),
                "missing_lines": list(range(75, 101)),
                "summary": {"covered_lines": 74, "num_statements": 100},
            },
            "src/onec_hbk_bsl/mcp_bridge/example.py": {
                "executed_lines": list(range(1, 69)),
                "missing_lines": list(range(69, 101)),
                "summary": {"covered_lines": 68, "num_statements": 100},
            },
            "src/onec_hbk_bsl/indexer/example.py": {
                "executed_lines": list(range(1, 82)),
                "missing_lines": list(range(82, 101)),
                "summary": {"covered_lines": 81, "num_statements": 100},
            },
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_component_coverage_floor_rejects_controlled_regression(tmp_path: Path) -> None:
    path = _coverage(tmp_path / "coverage.json", parser_covered=62)
    with pytest.raises(ValueError, match="parser"):
        verify_release.verify_coverage(path)


def test_diff_coverage_uses_only_changed_executable_lines(tmp_path: Path) -> None:
    path = _coverage(tmp_path / "coverage.json")
    with pytest.raises(ValueError, match="diff 50.00%"):
        verify_release.verify_coverage(
            path,
            changed_lines={"src/onec_hbk_bsl/parser/example.py": {62, 64}},
        )


def test_release_publish_jobs_depend_on_full_preflight() -> None:
    verify_release.verify_release_dag()


def test_rule_contract_has_exact_runtime_parity() -> None:
    contract = verify_release.source_contract()
    assert len(contract["rules"]) == 180
    assert contract["rules"] == contract["runtime_rules"]
    assert len(contract["platform_api"]["types"]) > 50


def test_missing_artifact_blocks_preflight(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing release artifacts"):
        verify_release.verify_artifacts(tmp_path, "0.8.43", tmp_path / "out")


def test_checksum_manifest_is_independent_of_input_order(tmp_path: Path) -> None:
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    manifest = tmp_path / "SHA256SUMS"
    verify_release.write_checksum_manifest([second, first], manifest)
    forward = manifest.read_text(encoding="utf-8")
    verify_release.write_checksum_manifest([first, second], manifest)
    assert manifest.read_text(encoding="utf-8") == forward
    assert forward.splitlines()[0].endswith("  a.bin")
