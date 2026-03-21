"""Tests for onec_hbk_bsl.cli.config."""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.cli.config import _EMPTY, BslConfig, load_config

# ---------------------------------------------------------------------------
# BslConfig — rule selection
# ---------------------------------------------------------------------------


class TestBslConfigSelect:
    def test_select_none_when_empty(self) -> None:
        cfg = BslConfig({})
        assert cfg.select is None

    def test_select_parsed(self) -> None:
        cfg = BslConfig({"select": ["BSL001", " bsl002 ", "BSL003"]})
        assert cfg.select == {"BSL001", "BSL002", "BSL003"}

    def test_select_empty_list_returns_none(self) -> None:
        cfg = BslConfig({"select": []})
        assert cfg.select is None


class TestBslConfigIgnore:
    def test_ignore_none_when_empty(self) -> None:
        cfg = BslConfig({})
        assert cfg.ignore is None

    def test_ignore_parsed(self) -> None:
        cfg = BslConfig({"ignore": ["BSL001", "BSL002"]})
        assert cfg.ignore == {"BSL001", "BSL002"}


class TestBslConfigExclude:
    def test_exclude_empty(self) -> None:
        cfg = BslConfig({})
        assert cfg.exclude == []

    def test_exclude_list(self) -> None:
        cfg = BslConfig({"exclude": ["vendor/**", "*.gen.bsl"]})
        assert cfg.exclude == ["vendor/**", "*.gen.bsl"]

    def test_is_excluded_full_path(self) -> None:
        cfg = BslConfig({"exclude": ["/project/vendor/**"]})
        assert cfg.is_excluded("/project/vendor/foo.bsl") is True
        assert cfg.is_excluded("/project/src/foo.bsl") is False

    def test_is_excluded_basename(self) -> None:
        cfg = BslConfig({"exclude": ["*_test.bsl"]})
        assert cfg.is_excluded("/project/src/foo_test.bsl") is True

    def test_is_excluded_path_component(self) -> None:
        cfg = BslConfig({"exclude": ["generated"]})
        assert cfg.is_excluded("/project/generated/out.bsl") is True


class TestBslConfigPerFileIgnores:
    def test_per_file_ignores_empty(self) -> None:
        cfg = BslConfig({})
        assert cfg.per_file_ignores == {}

    def test_get_file_ignores(self) -> None:
        cfg = BslConfig(
            {
                "per-file-ignores": {
                    "**/legacy/**": ["BSL001", "BSL002"],
                    "special.bsl": ["BSL003"],
                }
            }
        )
        assert cfg.get_file_ignores("/src/legacy/old.bsl") == {"BSL001", "BSL002"}
        assert cfg.get_file_ignores("/src/special.bsl") == {"BSL003"}
        assert cfg.get_file_ignores("/src/normal.bsl") == set()


class TestBslConfigFormat:
    def test_format_none(self) -> None:
        cfg = BslConfig({})
        assert cfg.format is None

    def test_format_value(self) -> None:
        cfg = BslConfig({"format": "json"})
        assert cfg.format == "json"


class TestBslConfigJobs:
    def test_jobs_none(self) -> None:
        cfg = BslConfig({})
        assert cfg.jobs is None

    def test_jobs_int(self) -> None:
        cfg = BslConfig({"jobs": 4})
        assert cfg.jobs == 4


class TestBslConfigExitZero:
    def test_exit_zero_default_false(self) -> None:
        cfg = BslConfig({})
        assert cfg.exit_zero is False

    def test_exit_zero_true(self) -> None:
        cfg = BslConfig({"exit-zero": True})
        assert cfg.exit_zero is True


class TestBslConfigBaseline:
    def test_baseline_none(self) -> None:
        cfg = BslConfig({})
        assert cfg.baseline is None

    def test_baseline_path(self) -> None:
        cfg = BslConfig({"baseline": "baseline.json"})
        assert cfg.baseline == "baseline.json"


class TestBslConfigThresholds:
    def test_thresholds_none(self) -> None:
        cfg = BslConfig({})
        assert cfg.max_line_length is None
        assert cfg.max_proc_lines is None

    def test_thresholds_set(self) -> None:
        cfg = BslConfig(
            {
                "max-line-length": 120,
                "max-proc-lines": 200,
                "max-cognitive-complexity": 15,
            }
        )
        assert cfg.max_line_length == 120
        assert cfg.max_proc_lines == 200
        assert cfg.max_cognitive_complexity == 15

    def test_engine_kwargs_filters_none(self) -> None:
        cfg = BslConfig({"max-line-length": 100})
        kwargs = cfg.engine_kwargs()
        assert kwargs == {"max_line_length": 100}


# ---------------------------------------------------------------------------
# load_config — file discovery
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        cfg = load_config(str(tmp_path))
        assert cfg.select is None
        assert cfg.ignore is None

    def test_reads_onec_hbk_bsl_toml(self, tmp_path: Path) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            '[onec-hbk-bsl]\nignore = ["BSL001"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.ignore == {"BSL001"}

    def test_reads_onec_hbk_bsl_toml_root_level(self, tmp_path: Path) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            'ignore = ["BSL002"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.ignore == {"BSL002"}

    def test_reads_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool."onec-hbk-bsl"]\nselect = ["BSL012"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select == {"BSL012"}

    def test_onec_hbk_bsl_toml_preferred_over_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool."onec-hbk-bsl"]\nselect = ["BSL001"]\n', encoding="utf-8"
        )
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            'select = ["BSL009"]\n', encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select == {"BSL009"}

    def test_walks_up_to_parent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool."onec-hbk-bsl"]\nignore = ["BSL014"]\n', encoding="utf-8"
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
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            "this is not valid toml [[[", encoding="utf-8"
        )
        cfg = load_config(str(tmp_path))
        assert cfg.select is None

    def test_config_thresholds(self, tmp_path: Path) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text(
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
