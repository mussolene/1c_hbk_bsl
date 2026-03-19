"""
Tests for CLI check module: format output, rule listing, file collection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bsl_analyzer.analysis.diagnostics import Diagnostic, Severity
from bsl_analyzer.cli.check import (
    BSL_EXTENSIONS,
    _collect_files,
    _print_json,
    _print_sarif,
    _print_sonarqube,
    _print_stats,
    _run_checks,
    check,
    list_rules,
)
from bsl_analyzer.cli.config import BslConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_bsl(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _make_diag(
    file: str,
    line: int = 1,
    code: str = "BSL009",
    message: str = "test",
    severity: Severity = Severity.WARNING,
) -> Diagnostic:
    return Diagnostic(
        file=file,
        line=line,
        character=0,
        end_line=line,
        end_character=10,
        severity=severity,
        code=code,
        message=message,
    )


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------


class TestCollectFiles:
    def test_collects_bsl_files(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "a.bsl", "")
        _write_bsl(tmp_path, "b.bsl", "")
        (tmp_path / "c.txt").write_text("ignored")
        files = _collect_files([str(tmp_path)])
        names = {Path(f).name for f in files}
        assert "a.bsl" in names
        assert "b.bsl" in names
        assert "c.txt" not in names

    def test_collects_os_extension(self, tmp_path: Path) -> None:
        (tmp_path / "m.os").write_text("А = 1;")
        files = _collect_files([str(tmp_path)])
        assert any(f.endswith(".os") for f in files)

    def test_single_file_path(self, tmp_path: Path) -> None:
        f = _write_bsl(tmp_path, "test.bsl", "")
        files = _collect_files([str(f)])
        assert str(f) in files

    def test_nonexistent_path_ignored(self) -> None:
        files = _collect_files(["/no/such/path/ever"])
        assert files == []

    def test_extensions_constant(self) -> None:
        assert ".bsl" in BSL_EXTENSIONS
        assert ".os" in BSL_EXTENSIONS


# ---------------------------------------------------------------------------
# _run_checks
# ---------------------------------------------------------------------------


class TestRunChecks:
    def test_finds_issues_serial(self, tmp_path: Path) -> None:
        f = _write_bsl(tmp_path, "t.bsl", 'Пароль = "секрет123";\n')
        diags, err = _run_checks([str(f)], select={"BSL012"}, ignore=None, jobs=1)
        assert not err
        assert any(d.code == "BSL012" for d in diags)

    def test_finds_issues_parallel(self, tmp_path: Path) -> None:
        files = []
        for i in range(4):
            files.append(str(_write_bsl(tmp_path, f"t{i}.bsl", 'Пароль = "с123";\n')))
        diags, err = _run_checks(files, select={"BSL012"}, ignore=None, jobs=2)
        assert not err
        assert len(diags) >= 4

    def test_no_files_returns_empty(self) -> None:
        diags, err = _run_checks([], select=None, ignore=None, jobs=1)
        assert diags == []
        assert not err

    def test_select_limits_rules(self, tmp_path: Path) -> None:
        f = _write_bsl(tmp_path, "t.bsl", "А = А;\n")
        diags, _ = _run_checks([str(f)], select={"BSL009"}, ignore=None, jobs=1)
        assert all(d.code == "BSL009" for d in diags)

    def test_ignore_suppresses_rule(self, tmp_path: Path) -> None:
        f = _write_bsl(tmp_path, "t.bsl", 'Пароль = "с123";\n')
        diags, _ = _run_checks([str(f)], select=None, ignore={"BSL012"}, jobs=1)
        assert not any(d.code == "BSL012" for d in diags)


# ---------------------------------------------------------------------------
# _print_json
# ---------------------------------------------------------------------------


class TestPrintJson:
    def test_outputs_valid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag(str(tmp_path / "a.bsl"))
        _print_json([diag])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["code"] == "BSL009"

    def test_empty_list_outputs_empty_array(self, capsys: pytest.CaptureFixture) -> None:
        _print_json([])
        captured = capsys.readouterr()
        assert json.loads(captured.out) == []

    def test_json_fields(self, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag("/some/file.bsl", line=5)
        _print_json([diag])
        captured = capsys.readouterr()
        item = json.loads(captured.out)[0]
        assert "file" in item
        assert "line" in item
        assert item["line"] == 5


# ---------------------------------------------------------------------------
# _print_sonarqube
# ---------------------------------------------------------------------------


class TestPrintSonarqube:
    def test_outputs_valid_sonarqube_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        diag = _make_diag(str(tmp_path / "src" / "a.bsl"))
        _print_sonarqube([diag], project_root=None)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "issues" in data
        assert len(data["issues"]) == 1
        issue = data["issues"][0]
        assert issue["engineId"] == "bsl-analyzer"
        assert issue["ruleId"] == "BSL009"
        assert "primaryLocation" in issue

    def test_sonar_root_makes_relative_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        diag = _make_diag(str(src / "module.bsl"))
        _print_sonarqube([diag], project_root=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        loc = data["issues"][0]["primaryLocation"]
        assert "module.bsl" in loc["filePath"]
        assert not loc["filePath"].startswith("/")

    def test_empty_list_outputs_empty_issues(self, capsys: pytest.CaptureFixture) -> None:
        _print_sonarqube([], project_root=None)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["issues"] == []


# ---------------------------------------------------------------------------
# check() integration
# ---------------------------------------------------------------------------


class TestCheckIntegration:
    def test_clean_file_returns_0(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "clean.bsl", "Процедура Тест()\nКонецПроцедуры\n")
        rc = check([str(tmp_path)], format="text", select={"BSL001"})
        assert rc == 0

    def test_dirty_file_returns_1(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "dirty.bsl", 'Пароль = "секрет123";\n')
        rc = check([str(tmp_path)], format="text", select={"BSL012"})
        assert rc == 1

    def test_no_files_returns_0(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("nothing")
        rc = check([str(tmp_path)])
        assert rc == 0

    def test_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        rc = check([str(tmp_path)], format="json", select={"BSL012"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert rc == 1

    def test_sonarqube_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        rc = check([str(tmp_path)], format="sonarqube", select={"BSL012"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "issues" in data
        assert rc == 1


# ---------------------------------------------------------------------------
# _print_sarif
# ---------------------------------------------------------------------------


class TestPrintSarif:
    def test_valid_sarif_structure(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag(str(tmp_path / "a.bsl"))
        _print_sarif([diag])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert "runs" in data
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert "tool" in run
        assert "results" in run

    def test_sarif_result_fields(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag(str(tmp_path / "b.bsl"), line=3)
        _print_sarif([diag])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        result = data["runs"][0]["results"][0]
        assert result["ruleId"] == "BSL009"
        assert "message" in result
        assert "locations" in result
        loc = result["locations"][0]["physicalLocation"]
        assert loc["region"]["startLine"] == 3

    def test_sarif_empty_list(self, capsys: pytest.CaptureFixture) -> None:
        _print_sarif([])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["runs"][0]["results"] == []

    def test_sarif_relative_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        src = tmp_path / "src"
        src.mkdir()
        diag = _make_diag(str(src / "module.bsl"))
        _print_sarif([diag], project_root=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        uri = data["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert "module.bsl" in uri
        assert not uri.startswith("/")

    def test_sarif_rule_descriptors(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag(str(tmp_path / "a.bsl"))
        _print_sarif([diag])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        rules = data["runs"][0]["tool"]["driver"]["rules"]
        assert any(r["id"] == "BSL009" for r in rules)


# ---------------------------------------------------------------------------
# check() — new features
# ---------------------------------------------------------------------------


class TestCheckNewFeatures:
    def test_exit_zero_suppresses_exit_1(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "dirty.bsl", 'Пароль = "секрет123";\n')
        rc = check([str(tmp_path)], format="text", select={"BSL012"}, exit_zero=True)
        assert rc == 0

    def test_sarif_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        rc = check([str(tmp_path)], format="sarif", select={"BSL012"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "runs" in data
        assert rc == 1

    def test_update_baseline_writes_file_and_exits_0(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        baseline_path = str(tmp_path / "b.json")
        rc = check(
            [str(tmp_path)],
            format="text",
            select={"BSL012"},
            update_baseline=baseline_path,
        )
        assert rc == 0
        import json as _json
        with open(baseline_path, encoding="utf-8") as f:
            data = _json.load(f)
        assert isinstance(data, list)
        assert any(item["code"] == "BSL012" for item in data)

    def test_baseline_suppresses_known_issues(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        baseline_path = str(tmp_path / "b.json")
        # Create baseline
        check(
            [str(tmp_path)],
            format="text",
            select={"BSL012"},
            update_baseline=baseline_path,
        )
        # Now run with baseline — should be clean
        rc = check(
            [str(tmp_path)],
            format="text",
            select={"BSL012"},
            baseline=baseline_path,
        )
        assert rc == 0

    def test_config_exclude_removes_file(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "skip.bsl", 'Пароль = "секрет123";\n')
        cfg = BslConfig({"exclude": ["skip.bsl"]})
        rc = check([str(tmp_path)], format="text", select={"BSL012"}, config=cfg)
        assert rc == 0

    def test_config_per_file_ignores(self, tmp_path: Path) -> None:
        _write_bsl(tmp_path, "legacy.bsl", 'Пароль = "секрет123";\n')
        cfg = BslConfig({"per-file-ignores": {"legacy.bsl": ["BSL012"]}})
        rc = check([str(tmp_path)], format="text", select={"BSL012"}, config=cfg)
        assert rc == 0

    def test_config_threshold_applied(self, tmp_path: Path) -> None:
        # Very short max line length — should trigger BSL001
        long_line = "А" * 50 + ";\n"
        _write_bsl(tmp_path, "t.bsl", long_line)
        cfg = BslConfig({"max-line-length": 10})
        rc = check([str(tmp_path)], format="text", select={"BSL001"}, config=cfg)
        assert rc == 1


# ---------------------------------------------------------------------------
# _print_stats
# ---------------------------------------------------------------------------


class TestPrintStats:
    def test_stats_valid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diag = _make_diag(str(tmp_path / "a.bsl"))
        _print_stats([diag], file_count=5)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total"] == 1
        assert data["files_checked"] == 5
        assert "by_severity" in data
        assert "by_rule" in data

    def test_stats_empty(self, capsys: pytest.CaptureFixture) -> None:
        _print_stats([], file_count=10)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total"] == 0
        assert data["files_checked"] == 10

    def test_stats_counts_by_rule(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        diags = [
            _make_diag(str(tmp_path / "a.bsl"), code="BSL009"),
            _make_diag(str(tmp_path / "a.bsl"), code="BSL009"),
            _make_diag(str(tmp_path / "a.bsl"), code="BSL012"),
        ]
        _print_stats(diags, file_count=1)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["by_rule"]["BSL009"] == 2
        assert data["by_rule"]["BSL012"] == 1


class TestCheckStats:
    def test_stats_flag_outputs_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write_bsl(tmp_path, "f.bsl", 'Пароль = "секрет123";\n')
        check([str(tmp_path)], format="text", select={"BSL012"}, stats=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "total" in data
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# list_rules
# ---------------------------------------------------------------------------


class TestListRules:
    def test_list_rules_does_not_raise(self) -> None:
        # Just ensure it runs without error
        list_rules()
