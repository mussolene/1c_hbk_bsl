"""
Tests for cli/baseline.py — baseline load/save/filter.
"""

from __future__ import annotations

import json
from pathlib import Path

from bsl_analyzer.analysis.diagnostics import Diagnostic, Severity
from bsl_analyzer.cli.baseline import filter_baseline, load_baseline, save_baseline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _diag(file: str, code: str = "BSL009", line: int = 1) -> Diagnostic:
    return Diagnostic(
        file=file,
        line=line,
        character=0,
        end_line=line,
        end_character=10,
        severity=Severity.WARNING,
        code=code,
        message="test",
    )


# ---------------------------------------------------------------------------
# load_baseline
# ---------------------------------------------------------------------------


class TestLoadBaseline:
    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        result = load_baseline(str(tmp_path / "nonexistent.json"))
        assert result == set()

    def test_loads_valid_baseline(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        data = [{"file": "a.bsl", "code": "BSL009", "line": 5}]
        baseline_path.write_text(json.dumps(data), encoding="utf-8")
        result = load_baseline(str(baseline_path))
        assert ("a.bsl", "BSL009", 5) in result

    def test_loads_multiple_entries(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        data = [
            {"file": "a.bsl", "code": "BSL001", "line": 1},
            {"file": "b.bsl", "code": "BSL012", "line": 10},
        ]
        baseline_path.write_text(json.dumps(data), encoding="utf-8")
        result = load_baseline(str(baseline_path))
        assert len(result) == 2

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text("not valid json", encoding="utf-8")
        assert load_baseline(str(baseline_path)) == set()

    def test_missing_key_returns_empty(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text('[{"file": "a.bsl"}]', encoding="utf-8")
        assert load_baseline(str(baseline_path)) == set()


# ---------------------------------------------------------------------------
# save_baseline
# ---------------------------------------------------------------------------


class TestSaveBaseline:
    def test_saves_correct_structure(self, tmp_path: Path) -> None:
        path = str(tmp_path / "b.json")
        diag = _diag("/project/src/a.bsl", code="BSL009", line=7)
        n = save_baseline([diag], path)
        assert n == 1
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["file"] == "a.bsl"  # basename only
        assert data[0]["code"] == "BSL009"
        assert data[0]["line"] == 7

    def test_save_empty_list(self, tmp_path: Path) -> None:
        path = str(tmp_path / "b.json")
        n = save_baseline([], path)
        assert n == 0
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data == []

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = str(tmp_path / "b.json")
        diags = [
            _diag("/project/a.bsl", "BSL001", 1),
            _diag("/project/b.bsl", "BSL012", 5),
        ]
        save_baseline(diags, path)
        result = load_baseline(path)
        assert ("a.bsl", "BSL001", 1) in result
        assert ("b.bsl", "BSL012", 5) in result


# ---------------------------------------------------------------------------
# filter_baseline
# ---------------------------------------------------------------------------


class TestFilterBaseline:
    def test_removes_known_issues(self, tmp_path: Path) -> None:
        diag = _diag(str(tmp_path / "a.bsl"), "BSL009", 3)
        baseline = {("a.bsl", "BSL009", 3)}
        result = filter_baseline([diag], baseline)
        assert result == []

    def test_keeps_new_issues(self, tmp_path: Path) -> None:
        diag = _diag(str(tmp_path / "a.bsl"), "BSL009", 3)
        baseline: set = set()
        result = filter_baseline([diag], baseline)
        assert len(result) == 1

    def test_partial_filter(self, tmp_path: Path) -> None:
        known = _diag(str(tmp_path / "a.bsl"), "BSL001", 1)
        new_ = _diag(str(tmp_path / "a.bsl"), "BSL012", 2)
        baseline = {("a.bsl", "BSL001", 1)}
        result = filter_baseline([known, new_], baseline)
        assert len(result) == 1
        assert result[0].code == "BSL012"

    def test_empty_diagnostics(self) -> None:
        result = filter_baseline([], {"anything"})  # type: ignore[arg-type]
        assert result == []

    def test_empty_baseline_keeps_all(self, tmp_path: Path) -> None:
        diags = [_diag(str(tmp_path / "a.bsl"), f"BSL00{i}", i) for i in range(1, 4)]
        result = filter_baseline(diags, set())
        assert len(result) == 3
