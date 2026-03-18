"""
Tests for cli/config.py — TOML config loader and BslConfig.
"""

from __future__ import annotations

from pathlib import Path

from bsl_analyzer.cli.config import _EMPTY, BslConfig, load_config

# ---------------------------------------------------------------------------
# BslConfig properties
# ---------------------------------------------------------------------------


class TestBslConfigProperties:
    def test_empty_config_defaults(self) -> None:
        cfg = BslConfig({})
        assert cfg.select is None
        assert cfg.ignore is None
        assert cfg.exclude == []
        assert cfg.per_file_ignores == {}
        assert cfg.format is None
        assert cfg.jobs is None
        assert cfg.exit_zero is False
        assert cfg.baseline is None

    def test_select_uppercased(self) -> None:
        cfg = BslConfig({"select": ["bsl001", "BSL002"]})
        assert cfg.select == {"BSL001", "BSL002"}

    def test_ignore_uppercased(self) -> None:
        cfg = BslConfig({"ignore": ["bsl014"]})
        assert cfg.ignore == {"BSL014"}

    def test_select_empty_list_returns_none(self) -> None:
        cfg = BslConfig({"select": []})
        assert cfg.select is None

    def test_threshold_overrides(self) -> None:
        cfg = BslConfig(
            {
                "max-line-length": 120,
                "max-proc-lines": 60,
                "max-cognitive-complexity": 20,
                "max-mccabe-complexity": 12,
                "max-nesting-depth": 5,
                "max-params": 8,
                "max-returns": 4,
                "max-bool-ops": 4,
                "min-duplicate-uses": 2,
            }
        )
        assert cfg.max_line_length == 120
        assert cfg.max_proc_lines == 60
        assert cfg.max_cognitive_complexity == 20
        assert cfg.max_mccabe_complexity == 12
        assert cfg.max_nesting_depth == 5
        assert cfg.max_params == 8
        assert cfg.max_returns == 4
        assert cfg.max_bool_ops == 4
        assert cfg.min_duplicate_uses == 2

    def test_engine_kwargs_omits_none(self) -> None:
        cfg = BslConfig({"max-line-length": 80})
        kw = cfg.engine_kwargs()
        assert kw == {"max_line_length": 80}
        assert "max_proc_lines" not in kw

    def test_engine_kwargs_all(self) -> None:
        cfg = BslConfig({"max-params": 5, "max-returns": 3})
        kw = cfg.engine_kwargs()
        assert kw["max_params"] == 5
        assert kw["max_returns"] == 3

    def test_exit_zero_flag(self) -> None:
        cfg = BslConfig({"exit-zero": True})
        assert cfg.exit_zero is True

    def test_baseline_path(self) -> None:
        cfg = BslConfig({"baseline": "my-baseline.json"})
        assert cfg.baseline == "my-baseline.json"

    def test_format_property(self) -> None:
        cfg = BslConfig({"format": "json"})
        assert cfg.format == "json"

    def test_jobs_property(self) -> None:
        cfg = BslConfig({"jobs": 4})
        assert cfg.jobs == 4


# ---------------------------------------------------------------------------
# BslConfig.is_excluded
# ---------------------------------------------------------------------------


class TestIsExcluded:
    def test_no_excludes_never_excluded(self, tmp_path: Path) -> None:
        cfg = BslConfig({})
        assert not cfg.is_excluded(str(tmp_path / "a.bsl"))

    def test_exact_name_match(self, tmp_path: Path) -> None:
        cfg = BslConfig({"exclude": ["vendor"]})
        assert cfg.is_excluded(str(tmp_path / "vendor" / "module.bsl"))

    def test_glob_pattern_match(self, tmp_path: Path) -> None:
        cfg = BslConfig({"exclude": ["*.bsl"]})
        assert cfg.is_excluded(str(tmp_path / "file.bsl"))

    def test_non_matching_not_excluded(self, tmp_path: Path) -> None:
        cfg = BslConfig({"exclude": ["vendor"]})
        assert not cfg.is_excluded(str(tmp_path / "src" / "module.bsl"))

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        cfg = BslConfig({"exclude": ["vendor", "tests"]})
        assert cfg.is_excluded(str(tmp_path / "tests" / "a.bsl"))
        assert not cfg.is_excluded(str(tmp_path / "src" / "a.bsl"))


# ---------------------------------------------------------------------------
# BslConfig.get_file_ignores
# ---------------------------------------------------------------------------


class TestGetFileIgnores:
    def test_no_per_file_ignores(self, tmp_path: Path) -> None:
        cfg = BslConfig({})
        assert cfg.get_file_ignores(str(tmp_path / "a.bsl")) == set()

    def test_matching_pattern(self, tmp_path: Path) -> None:
        cfg = BslConfig({"per-file-ignores": {"*.bsl": ["BSL001", "bsl002"]}})
        result = cfg.get_file_ignores(str(tmp_path / "a.bsl"))
        assert result == {"BSL001", "BSL002"}

    def test_non_matching_pattern(self, tmp_path: Path) -> None:
        cfg = BslConfig({"per-file-ignores": {"test_*.bsl": ["BSL001"]}})
        result = cfg.get_file_ignores(str(tmp_path / "module.bsl"))
        assert result == set()


# ---------------------------------------------------------------------------
# load_config — file discovery
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        cfg = load_config(str(tmp_path))
        assert cfg.select is None
        assert cfg.ignore is None

    def test_reads_bsl_analyzer_toml(self, tmp_path: Path) -> None:
        (tmp_path / "bsl-analyzer.toml").write_text(
            '[bsl-analyzer]\nignore = ["BSL001"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.ignore == {"BSL001"}

    def test_reads_bsl_analyzer_toml_root_level(self, tmp_path: Path) -> None:
        (tmp_path / "bsl-analyzer.toml").write_text(
            'ignore = ["BSL002"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.ignore == {"BSL002"}

    def test_reads_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.bsl-analyzer]\nselect = ["BSL012"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select == {"BSL012"}

    def test_bsl_analyzer_toml_preferred_over_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.bsl-analyzer]\nselect = ["BSL001"]\n', encoding="utf-8"
        )
        (tmp_path / "bsl-analyzer.toml").write_text(
            'select = ["BSL009"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select == {"BSL009"}

    def test_walks_up_to_parent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.bsl-analyzer]\nignore = ["BSL014"]\n', encoding="utf-8"
        )
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)
        cfg = load_config(str(subdir))
        assert cfg.ignore == {"BSL014"}

    def test_pyproject_without_bsl_section_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest]\naddopts = []\n", encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select is None

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "bsl-analyzer.toml").write_text(
            "this is not valid toml [[[", encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select is None

    def test_config_thresholds(self, tmp_path: Path) -> None:
        (tmp_path / "bsl-analyzer.toml").write_text(
            'max-line-length = 120\nmax-proc-lines = 80\n',
            encoding="utf-8",
        )
        cfg = load_config(str(tmp_path))
        assert cfg.max_line_length == 120
        assert cfg.max_proc_lines == 80

    def test_empty_singleton(self) -> None:
        assert _EMPTY.select is None
        assert _EMPTY.ignore is None
        assert _EMPTY.exclude == []
