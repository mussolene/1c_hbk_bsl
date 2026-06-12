"""
Tests for cli/git_utils.py — git diff helper for --diff mode.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from onec_hbk_bsl.cli.git_utils import (
    _parse_unified_diff_changed_ranges,
    git_changed_files,
    git_changed_line_ranges,
    git_root,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_result(stdout: str, returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    return r


# ---------------------------------------------------------------------------
# git_root
# ---------------------------------------------------------------------------


class TestGitRoot:
    def test_returns_root_when_in_repo(self, tmp_path: Path) -> None:
        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = _make_run_result("/some/root\n")
            result = git_root(str(tmp_path))
        assert result == "/some/root"

    def test_returns_none_outside_repo(self, tmp_path: Path) -> None:
        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = _make_run_result("", returncode=128)
            result = git_root(str(tmp_path))
        assert result is None

    def test_returns_none_when_git_not_found(self, tmp_path: Path) -> None:
        with patch(
            "onec_hbk_bsl.cli.git_utils.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = git_root(str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# git_changed_files
# ---------------------------------------------------------------------------


class TestGitChangedFiles:
    def test_returns_changed_bsl_files(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "module.bsl"
        bsl_file.write_text("А = 1;", encoding="utf-8")
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("docs")

        def _fake_run(args, **kwargs):
            if "rev-parse" in args:
                return _make_run_result(str(tmp_path) + "\n")
            if "diff" in args:
                return _make_run_result("module.bsl\nreadme.txt\n")
            if "ls-files" in args:
                return _make_run_result("")
            return _make_run_result("")

        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run", side_effect=_fake_run):
            result = git_changed_files(str(tmp_path))

        assert any("module.bsl" in f for f in result)
        assert not any("readme.txt" in f for f in result)

    def test_returns_empty_when_no_git(self, tmp_path: Path) -> None:
        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = _make_run_result("", returncode=128)
            result = git_changed_files(str(tmp_path))
        assert result == []

    def test_returns_empty_when_no_changed_bsl(self, tmp_path: Path) -> None:
        def _fake_run(args, **kwargs):
            if "rev-parse" in args:
                return _make_run_result(str(tmp_path) + "\n")
            return _make_run_result("readme.md\n")

        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run", side_effect=_fake_run):
            result = git_changed_files(str(tmp_path))
        assert result == []

    def test_since_parameter_passed_to_git(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "new.bsl"
        bsl_file.write_text("Б = 2;", encoding="utf-8")

        call_args_list = []

        def _fake_run(args, **kwargs):
            call_args_list.append(args)
            if "rev-parse" in args:
                return _make_run_result(str(tmp_path) + "\n")
            if "diff" in args:
                return _make_run_result("new.bsl\n")
            return _make_run_result("")

        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run", side_effect=_fake_run):
            git_changed_files(str(tmp_path), since="origin/main")

        diff_call = next(a for a in call_args_list if "diff" in a)
        assert "origin/main" in diff_call


class TestGitChangedLineRanges:
    def test_parse_unified_diff_changed_ranges_utf8_path(self, tmp_path: Path) -> None:
        diff = (
            "diff --git a/src/Модуль.bsl b/src/Модуль.bsl\n"
            "--- a/src/Модуль.bsl\n"
            "+++ b/src/Модуль.bsl\n"
            "@@ -1,0 +2,3 @@\n"
            "+А = 1;\n"
        )
        result = _parse_unified_diff_changed_ranges(diff, str(tmp_path))
        expected = str((tmp_path / "src" / "Модуль.bsl").resolve())
        assert result == {expected: [(2, 4)]}

    def test_git_changed_line_ranges_includes_untracked_full_file(self, tmp_path: Path) -> None:
        tracked = tmp_path / "tracked.bsl"
        tracked.write_text("А = 1;\n", encoding="utf-8")
        untracked = tmp_path / "Новый.os"
        untracked.write_text("А = 1;\nБ = 2;\n", encoding="utf-8")

        def _fake_run(args, **kwargs):
            if "rev-parse" in args:
                return _make_run_result(str(tmp_path) + "\n")
            if "diff" in args and "--unified=0" in args:
                return _make_run_result(
                    "diff --git a/tracked.bsl b/tracked.bsl\n"
                    "--- a/tracked.bsl\n"
                    "+++ b/tracked.bsl\n"
                    "@@ -1 +1 @@\n"
                    "+А = 1;\n"
                )
            if "diff" in args:
                return _make_run_result("tracked.bsl\n")
            if "ls-files" in args:
                return _make_run_result("Новый.os\n")
            return _make_run_result("")

        with patch("onec_hbk_bsl.cli.git_utils.subprocess.run", side_effect=_fake_run):
            result = git_changed_line_ranges(str(tmp_path))

        assert result[str(tracked.resolve())] == [(1, 1)]
        assert result[str(untracked.resolve())] == [(1, 2)]
