"""
Tests for analysis/fix_engine.py — auto-fix logic.
"""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import Diagnostic, DiagnosticEngine, Severity
from onec_hbk_bsl.analysis.fix_engine import (
    FIXABLE_RULES,
    FixResult,
    _fix_bsl009_self_assign,
    _fix_bsl010_useless_return,
    _fix_bsl055_consecutive_blank_lines,
    _fix_bsl060_double_negation,
    apply_fixes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _diag(file: str, line: int, code: str) -> Diagnostic:
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


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unit tests for individual fixers
# ---------------------------------------------------------------------------


class TestFixBsl009SelfAssign:
    def test_deletes_self_assign_line(self, tmp_path: Path) -> None:
        lines = ["А = 1;\n", "Б = Б;\n", "В = 3;\n"]
        diag = _diag("f.bsl", 2, "BSL009")
        result = _fix_bsl009_self_assign(lines, diag)
        assert result is not None
        assert len(result) == 2
        assert "Б = Б" not in "".join(result)

    def test_preserves_surrounding_lines(self, tmp_path: Path) -> None:
        lines = ["А = 1;\n", "Б = Б;\n", "В = 3;\n"]
        diag = _diag("f.bsl", 2, "BSL009")
        result = _fix_bsl009_self_assign(lines, diag)
        assert result is not None
        assert result[0] == "А = 1;\n"
        assert result[1] == "В = 3;\n"

    def test_returns_none_for_invalid_line(self) -> None:
        lines = ["А = 1;\n"]
        diag = _diag("f.bsl", 99, "BSL009")
        result = _fix_bsl009_self_assign(lines, diag)
        assert result is None


class TestFixBsl010UselessReturn:
    def test_deletes_empty_return(self) -> None:
        lines = ["Процедура Тест()\n", "    А = 1;\n", "    Возврат;\n", "КонецПроцедуры\n"]
        diag = _diag("f.bsl", 3, "BSL010")
        result = _fix_bsl010_useless_return(lines, diag)
        assert result is not None
        assert len(result) == 3
        assert not any("Возврат;" in line for line in result)

    def test_does_not_delete_return_with_value(self) -> None:
        lines = ["Функция Тест()\n", "    Возврат 42;\n", "КонецФункции\n"]
        diag = _diag("f.bsl", 2, "BSL010")
        result = _fix_bsl010_useless_return(lines, diag)
        assert result is None  # safety re-check prevents deletion


class TestFixBsl055BlankLines:
    def test_compresses_five_blank_lines_to_one(self) -> None:
        lines = ["А = 1;\n", "\n", "\n", "\n", "\n", "\n", "Б = 2;\n"]
        diag = _diag("f.bsl", 2, "BSL055")  # blank run starts at line 2
        result = _fix_bsl055_consecutive_blank_lines(lines, diag)
        assert result is not None
        assert len(result) == 3  # 1 + 1 blank + 1

    def test_two_blank_lines_compress_to_one(self) -> None:
        lines = ["А = 1;\n", "\n", "\n", "Б = 2;\n"]
        diag = _diag("f.bsl", 2, "BSL055")
        result = _fix_bsl055_consecutive_blank_lines(lines, diag)
        assert result is not None
        blank_count = sum(1 for line in result if not line.strip())
        assert blank_count == 1

    def test_three_blank_lines_become_one(self) -> None:
        lines = ["А = 1;\n", "\n", "\n", "\n", "Б = 2;\n"]
        diag = _diag("f.bsl", 2, "BSL055")
        result = _fix_bsl055_consecutive_blank_lines(lines, diag)
        assert result is not None
        blank_count = sum(1 for line in result if not line.strip())
        assert blank_count == 1


class TestFixBsl060DoubleNegation:
    def test_removes_double_negation(self) -> None:
        lines = ["Если НЕ НЕ Флаг Тогда\n"]
        diag = _diag("f.bsl", 1, "BSL060")
        result = _fix_bsl060_double_negation(lines, diag)
        assert result is not None
        assert "НЕ НЕ" not in result[0]
        assert "Флаг" in result[0]

    def test_returns_none_when_no_match(self) -> None:
        lines = ["Если НЕ Флаг Тогда\n"]
        diag = _diag("f.bsl", 1, "BSL060")
        result = _fix_bsl060_double_negation(lines, diag)
        assert result is None

    def test_preserves_rest_of_line(self) -> None:
        lines = ["    Если НЕ НЕ Значение Тогда\n"]
        diag = _diag("f.bsl", 1, "BSL060")
        result = _fix_bsl060_double_negation(lines, diag)
        assert result is not None
        assert "Значение" in result[0]
        assert "Тогда" in result[0]


# ---------------------------------------------------------------------------
# FIXABLE_RULES registry
# ---------------------------------------------------------------------------


class TestFixableRulesRegistry:
    def test_registry_contains_expected_rules(self) -> None:
        assert "BSL009" in FIXABLE_RULES
        assert "BSL010" in FIXABLE_RULES
        assert "BSL055" in FIXABLE_RULES
        assert "BSL060" in FIXABLE_RULES

    def test_unfixable_rule_not_in_registry(self) -> None:
        assert "BSL014" not in FIXABLE_RULES
        assert "BSL001" not in FIXABLE_RULES


# ---------------------------------------------------------------------------
# apply_fixes integration tests
# ---------------------------------------------------------------------------


class TestApplyFixes:
    def test_fixes_self_assign_in_file(self, tmp_path: Path) -> None:
        content = "А = 1;\nБ = Б;\nВ = 3;\n"
        p = _write(tmp_path, "t.bsl", content)
        diags = DiagnosticEngine(select={"BSL009"}).check_file(str(p))
        result = apply_fixes(str(p), diags)
        assert result.error is None
        assert "BSL009" in result.applied
        text = p.read_text(encoding="utf-8")
        assert "Б = Б" not in text
        assert "А = 1" in text
        assert "В = 3" in text

    def test_fixes_consecutive_blank_lines(self, tmp_path: Path) -> None:
        content = "А = 1;\n\n\n\n\nБ = 2;\n"
        p = _write(tmp_path, "t.bsl", content)
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(p))
        result = apply_fixes(str(p), diags)
        assert result.error is None
        text = p.read_text(encoding="utf-8")
        blank_count = sum(1 for line in text.splitlines() if not line.strip())
        assert blank_count <= 1

    def test_fix_result_has_applied_and_skipped(self, tmp_path: Path) -> None:
        content = "Б = Б;\n"
        p = _write(tmp_path, "t.bsl", content)
        # Manually add a BSL009 and an unfixable BSL014 diagnostic
        diags = [
            _diag(str(p), 1, "BSL009"),
            _diag(str(p), 1, "BSL014"),
        ]
        result = apply_fixes(str(p), diags)
        assert "BSL009" in result.applied
        assert "BSL014" in result.skipped

    def test_returns_fix_result_type(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "t.bsl", "А = 1;\n")
        result = apply_fixes(str(p), [])
        assert isinstance(result, FixResult)
        assert result.file == str(p)
        assert result.error is None

    def test_io_error_sets_error_field(self, tmp_path: Path) -> None:
        result = apply_fixes("/nonexistent/path/file.bsl", [_diag("/nonexistent/path/file.bsl", 1, "BSL009")])
        assert result.error is not None

    def test_no_diagnostics_leaves_file_unchanged(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        p = _write(tmp_path, "t.bsl", content)
        result = apply_fixes(str(p), [])
        assert result.applied == []
        assert p.read_text(encoding="utf-8") == content

    def test_multiple_fixes_in_one_file(self, tmp_path: Path) -> None:
        content = "А = А;\nЕсли НЕ НЕ Б Тогда\nКонецЕсли;\n"
        p = _write(tmp_path, "t.bsl", content)
        diags = [
            _diag(str(p), 1, "BSL009"),
            _diag(str(p), 2, "BSL060"),
        ]
        result = apply_fixes(str(p), diags)
        assert result.error is None
        assert set(result.applied) == {"BSL009", "BSL060"}
        text = p.read_text(encoding="utf-8")
        assert "А = А" not in text
        assert "НЕ НЕ" not in text


# ---------------------------------------------------------------------------
# --fix flag end-to-end via check()
# ---------------------------------------------------------------------------


class TestCheckFixFlag:
    def test_fix_flag_removes_self_assign(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.cli.check import check

        p = _write(tmp_path, "t.bsl", "А = А;\n")
        rc = check([str(tmp_path)], format="text", select={"BSL009"}, fix=True)
        text = p.read_text(encoding="utf-8")
        assert "А = А" not in text
        assert rc == 0  # fixed, so no remaining issues

    def test_fix_flag_reports_unfixable_issues(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.cli.check import check

        long_line = "А" * 150 + ";\n"
        _write(tmp_path, "t.bsl", long_line)
        rc = check([str(tmp_path)], format="text", select={"BSL014"}, fix=True)
        # BSL014 is not auto-fixable, issue should remain
        assert rc == 1
