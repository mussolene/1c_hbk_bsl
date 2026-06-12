"""
Tests for __main__ entry point — argument parsing and dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from onec_hbk_bsl.__main__ import _normalize_argv, _parse_codes, main

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

    def test_unknown_code_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown diagnostic rule token"):
            _parse_codes("BSL999")


# ---------------------------------------------------------------------------
# main() — check mode
# ---------------------------------------------------------------------------


def test_main_calls_multiprocessing_freeze_support_before_argparse() -> None:
    with (
        patch("multiprocessing.freeze_support") as freeze_support,
        patch("sys.argv", ["onec-hbk-bsl", "rules"]),
    ):
        main()

    freeze_support.assert_called_once_with()


class TestMainCheckNewFlags:
    def test_exit_zero_flag(self, tmp_path: Path) -> None:
        (tmp_path / "dirty.bsl").write_text('Пароль = "секрет123";\n', encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--select",
                "BSL012",
                "--exit-zero",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_sarif_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--format",
                "sarif",
                "--select",
                "BSL001",
            ],
        ):
            with pytest.raises(SystemExit):
                main()
        import json

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "runs" in data

    def test_update_baseline_flag(self, tmp_path: Path) -> None:
        (tmp_path / "f.bsl").write_text('Пароль = "с123";\n', encoding="utf-8")
        baseline = str(tmp_path / "b.json")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--select",
                "BSL012",
                "--update-baseline",
                baseline,
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert Path(baseline).exists()

    def test_baseline_flag(self, tmp_path: Path) -> None:
        (tmp_path / "f.bsl").write_text('Пароль = "с123";\n', encoding="utf-8")
        baseline = str(tmp_path / "b.json")
        # First, create baseline
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--select",
                "BSL012",
                "--update-baseline",
                baseline,
            ],
        ):
            with pytest.raises(SystemExit):
                main()
        # Then run with baseline — should exit 0
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--select",
                "BSL012",
                "--baseline",
                baseline,
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


class TestMainCheck:
    def test_check_mode_clean_exits_0(self, tmp_path: Path) -> None:
        (tmp_path / "ok.bsl").write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "check", str(tmp_path), "--select", "BSL001"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_check_mode_dirty_exits_1(self, tmp_path: Path) -> None:
        (tmp_path / "dirty.bsl").write_text('Пароль = "секрет123";\n', encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "check", str(tmp_path), "--select", "BSL012"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_check_with_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            ["onec-hbk-bsl", "check", str(tmp_path), "--format", "json", "--select", "BSL001"],
        ):
            with pytest.raises(SystemExit):
                main()
        # JSON written to stdout (not stderr)
        captured = capsys.readouterr()
        import json

        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_check_rejects_removed_sonarqube_format(self, tmp_path: Path) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--format",
                "sonarqube",
                "--select",
                "BSL001",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2

    def test_check_no_path_uses_cwd(self, tmp_path: Path) -> None:
        """check with no paths should use cwd (returns 0 if cwd has no BSL files)."""
        with patch("sys.argv", ["onec-hbk-bsl", "check"]):
            with patch("os.getcwd", return_value=str(tmp_path)):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 0

    def test_check_select_flag(self, tmp_path: Path) -> None:
        (tmp_path / "t.bsl").write_text("А = А;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            ["onec-hbk-bsl", "check", str(tmp_path), "--select", "BSL009"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1  # BSL009 self-assign detected

    def test_check_ignore_flag(self, tmp_path: Path) -> None:
        (tmp_path / "t.bsl").write_text('Пароль = "секрет123";\n', encoding="utf-8")
        with patch(
            "sys.argv",
            ["onec-hbk-bsl", "check", str(tmp_path), "--ignore", "BSL012"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        # With BSL012 ignored this file should be clean (may have other diagnostics)
        # Just verify it runs without crashing
        assert exc_info.value.code in (0, 1)

    def test_check_rejects_unknown_select_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "check", str(tmp_path), "--select", "BSL999"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 2
        assert "Unknown diagnostic rule token" in captured.err

    def test_check_rejects_unknown_config_rule(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text('select = ["BSL999"]\n', encoding="utf-8")
        (tmp_path / "ok.bsl").write_text("А = 1;\n", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "check", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 2
        assert "Unknown diagnostic rule token" in captured.err


# ---------------------------------------------------------------------------
# main() — format mode
# ---------------------------------------------------------------------------


class TestMainFormat:
    def test_format_subcommand_check_reports_dirty_without_writing(self, tmp_path: Path) -> None:
        path = tmp_path / "dirty.bsl"
        original = "Процедура Тест()\nА = 1;\nКонецПроцедуры\n"
        path.write_text(original, encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "format", str(tmp_path), "--check"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert path.read_text(encoding="utf-8") == original

    def test_format_subcommand_writes_default_tabs(self, tmp_path: Path) -> None:
        path = tmp_path / "dirty.bsl"
        path.write_text("Процедура Тест()\nА = 1;\nКонецПроцедуры\n", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "format", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert "\n\tА = 1;" in path.read_text(encoding="utf-8")

    def test_help_mentions_format_subcommand(self, capsys: pytest.CaptureFixture) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "COMMAND" in out
        assert "format" in out

    def test_format_subcommand_check_clean_exits_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "clean.bsl"
        path.write_text("Процедура Тест()\n\tА = 1;\nКонецПроцедуры", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "format", str(tmp_path), "--check"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# main() — list-rules mode
# ---------------------------------------------------------------------------


class TestMainListRules:
    def test_list_rules_does_not_exit(self) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "rules"]):
            # Should return normally (no sys.exit called)
            main()

    def test_list_rules_with_tag_filter(self) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "rules", "--tag", "security"]):
            # Should return normally and show only security rules
            main()


# ---------------------------------------------------------------------------
# main() — version
# ---------------------------------------------------------------------------


class TestMainVersion:
    def test_version_flag(self) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# main() — init mode
# ---------------------------------------------------------------------------


class TestMainInit:
    def test_init_creates_config_file(self, tmp_path: Path) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "init"]):
            with patch("os.getcwd", return_value=str(tmp_path)):
                main()
        assert (tmp_path / "onec-hbk-bsl.toml").exists()

    def test_init_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        existing = tmp_path / "onec-hbk-bsl.toml"
        existing.write_text("# custom\n")
        with patch("sys.argv", ["onec-hbk-bsl", "init"]):
            with patch("os.getcwd", return_value=str(tmp_path)):
                main()
        assert existing.read_text() == "# custom\n"


# ---------------------------------------------------------------------------
# main() — compatibility aliases and removed flags
# ---------------------------------------------------------------------------


class TestMainCompatibilityAliases:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["--check", "."], ["check", "."]),
            (["--lsp"], ["lsp"]),
            (["--mcp", "--stdio"], ["mcp", "--stdio"]),
            (["--index", ".", "--force"], ["index", ".", "--force"]),
            (["--list-rules"], ["rules"]),
            (["--init"], ["init"]),
            (
                ["--log-level", "debug", "--check", "."],
                ["check", "--log-level", "debug", "."],
            ),
            (["format", ".", "--check"], ["format", ".", "--check"]),
        ],
    )
    def test_legacy_mode_alias_normalization(
        self, argv: list[str], expected: list[str]
    ) -> None:
        assert _normalize_argv(argv) == expected

    def test_legacy_check_alias_still_runs(self, tmp_path: Path) -> None:
        (tmp_path / "ok.bsl").write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
        with patch("sys.argv", ["onec-hbk-bsl", "--check", str(tmp_path), "--select", "BSL001"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_legacy_rules_alias_still_runs(self) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "--list-rules", "--tag", "security"]):
            main()

    def test_legacy_init_alias_still_runs(self, tmp_path: Path) -> None:
        with patch("sys.argv", ["onec-hbk-bsl", "--init"]):
            with patch("os.getcwd", return_value=str(tmp_path)):
                main()
        assert (tmp_path / "onec-hbk-bsl.toml").exists()

    def test_global_log_level_before_legacy_alias_still_parses(self, tmp_path: Path) -> None:
        (tmp_path / "ok.bsl").write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
        with patch(
            "sys.argv",
            ["onec-hbk-bsl", "--log-level", "debug", "--check", str(tmp_path), "--select", "BSL001"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


class TestMainRemovedLegacyFlags:
    def test_compact_format_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "t.bsl").write_text("А = А;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--format",
                "compact",
                "--select",
                "BSL009",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2

    @pytest.mark.parametrize(
        "argv",
        [
            ["onec-hbk-bsl", "check", ".", "--stats"],
            ["onec-hbk-bsl", "check", ".", "--show-fix"],
            ["onec-hbk-bsl", "check", ".", "--check-profile", "full"],
            ["onec-hbk-bsl", "check", ".", "--paths-from0", "paths.txt"],
            ["onec-hbk-bsl", "check", ".", "--changed-lines-only"],
            ["onec-hbk-bsl", "check", ".", "--split-fragment", "*"],
            ["onec-hbk-bsl", "check", ".", "--sonar-root", "."],
        ],
    )
    def test_removed_flags_are_rejected(self, argv: list[str]) -> None:
        with patch("sys.argv", argv):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# main() -- fix mode
# ---------------------------------------------------------------------------


class TestMainFixFlag:
    def test_fix_flag_removes_self_assign(self, tmp_path: Path) -> None:
        p = tmp_path / "t.bsl"
        p.write_text("А = А;\n", encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "onec-hbk-bsl",
                "check",
                str(tmp_path),
                "--select",
                "BSL009",
                "--fix",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert "А = А" not in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# main() — diff mode
# ---------------------------------------------------------------------------


class TestMainDiffFlag:
    def test_diff_with_no_changes_exits_0(self, tmp_path: Path) -> None:
        """--diff with no changed BSL files should exit 0 cleanly."""
        with patch("sys.argv", ["onec-hbk-bsl", "check", str(tmp_path), "--diff"]):
            with patch("onec_hbk_bsl.cli.git_utils.git_changed_files", return_value=[]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 0
