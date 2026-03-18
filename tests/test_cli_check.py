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
    _print_sonarqube,
    _run_checks,
    check,
    list_rules,
)

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
# list_rules
# ---------------------------------------------------------------------------


class TestListRules:
    def test_list_rules_does_not_raise(self) -> None:
        # Just ensure it runs without error
        list_rules()
