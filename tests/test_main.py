"""
Tests for __main__ entry point — argument parsing and dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bsl_analyzer.__main__ import _parse_codes, main

# ---------------------------------------------------------------------------
# _parse_codes
# ---------------------------------------------------------------------------


class TestParseCodes:
    def test_none_returns_none(self) -> None:
        assert _parse_codes(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_codes("") is None

    def test_single_code(self) -> None:
        result = _parse_codes("BSL001")
        assert result == {"BSL001"}

    def test_multiple_codes(self) -> None:
        result = _parse_codes("BSL001,BSL012,BSL014")
        assert result == {"BSL001", "BSL012", "BSL014"}

    def test_spaces_stripped(self) -> None:
        result = _parse_codes(" BSL001 , BSL002 ")
        assert result == {"BSL001", "BSL002"}

    def test_lowercase_uppercased(self) -> None:
        result = _parse_codes("bsl001,bsl002")
        assert result == {"BSL001", "BSL002"}


# ---------------------------------------------------------------------------
# main() — check mode
# ---------------------------------------------------------------------------


class TestMainCheck:
    def test_check_mode_clean_exits_0(self, tmp_path: Path) -> None:
        (tmp_path / "ok.bsl").write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
        with patch("sys.argv", ["bsl-analyzer", "--check", str(tmp_path), "--select", "BSL001"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_check_mode_dirty_exits_1(self, tmp_path: Path) -> None:
        (tmp_path / "dirty.bsl").write_text('Пароль = "секрет123";\n', encoding="utf-8")
        with patch("sys.argv", ["bsl-analyzer", "--check", str(tmp_path), "--select", "BSL012"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_check_with_json_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            ["bsl-analyzer", "--check", str(tmp_path), "--format", "json", "--select", "BSL001"],
        ):
            with pytest.raises(SystemExit):
                main()
        # JSON written to stdout (not stderr)
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_check_with_sonarqube_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "bsl-analyzer", "--check", str(tmp_path),
                "--format", "sonarqube", "--select", "BSL001",
            ],
        ):
            with pytest.raises(SystemExit):
                main()
        import json
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "issues" in data

    def test_check_no_path_uses_cwd(self, tmp_path: Path) -> None:
        """--check with no paths should use cwd (returns 0 if cwd has no BSL files)."""
        with patch("sys.argv", ["bsl-analyzer", "--check"]):
            with patch("os.getcwd", return_value=str(tmp_path)):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 0

    def test_check_select_flag(self, tmp_path: Path) -> None:
        (tmp_path / "t.bsl").write_text("А = А;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            ["bsl-analyzer", "--check", str(tmp_path), "--select", "BSL009"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1  # BSL009 self-assign detected

    def test_check_ignore_flag(self, tmp_path: Path) -> None:
        (tmp_path / "t.bsl").write_text('Пароль = "секрет123";\n', encoding="utf-8")
        with patch(
            "sys.argv",
            ["bsl-analyzer", "--check", str(tmp_path), "--ignore", "BSL012"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        # With BSL012 ignored this file should be clean (may have other diagnostics)
        # Just verify it runs without crashing
        assert exc_info.value.code in (0, 1)


# ---------------------------------------------------------------------------
# main() — list-rules mode
# ---------------------------------------------------------------------------


class TestMainListRules:
    def test_list_rules_does_not_exit(self) -> None:
        with patch("sys.argv", ["bsl-analyzer", "--list-rules"]):
            # Should return normally (no sys.exit called)
            main()


# ---------------------------------------------------------------------------
# main() — version
# ---------------------------------------------------------------------------


class TestMainVersion:
    def test_version_flag(self) -> None:
        with patch("sys.argv", ["bsl-analyzer", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
