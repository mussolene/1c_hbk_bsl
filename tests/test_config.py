"""Tests for onec_hbk_bsl.cli.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.cli.config import (
    _EMPTY,
    BslConfig,
    ResolvedConfig,
    load_config,
    resolve_config,
)

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

    def test_select_rejects_unknown_rule_code(self) -> None:
        cfg = BslConfig({"select": ["BSL999"]})
        with pytest.raises(ValueError, match="Unknown diagnostic rule token"):
            _ = cfg.select


class TestBslConfigIgnore:
    def test_ignore_none_when_empty(self) -> None:
        cfg = BslConfig({})
        assert cfg.ignore is None

    def test_ignore_parsed(self) -> None:
        cfg = BslConfig({"ignore": ["BSL001", "BSL002"]})
        assert cfg.ignore == {"BSL001", "BSL002"}

    def test_ignore_rejects_unknown_rule_code(self) -> None:
        cfg = BslConfig({"ignore": ["BSL999"]})
        with pytest.raises(ValueError, match="Unknown diagnostic rule token"):
            _ = cfg.ignore


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

    def test_index_exclude_defaults_to_diagnostic_exclude(self) -> None:
        cfg = BslConfig({"exclude": ["vendor"]})
        assert cfg.is_index_excluded("/project/vendor/module.bsl") is True

    def test_empty_index_exclude_keeps_lint_excluded_files_navigable(self) -> None:
        cfg = BslConfig({"exclude": ["vendor"], "index-exclude": []})
        path = "/project/vendor/module.bsl"
        assert cfg.is_excluded(path) is True
        assert cfg.is_index_excluded(path) is False


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

    def test_get_file_ignores_rejects_unknown_rule_code(self) -> None:
        cfg = BslConfig({"per-file-ignores": {"**/legacy/**": ["BSL999"]}})
        with pytest.raises(ValueError, match="per-file-ignores"):
            cfg.get_file_ignores("/src/legacy/old.bsl")


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


class TestBslConfigFormatter:
    def test_formatter_defaults(self) -> None:
        cfg = BslConfig({})
        assert cfg.indent_size is None
        assert cfg.insert_spaces is None

    def test_formatter_options_from_config(self) -> None:
        cfg = BslConfig({"indent-size": 2, "insert-spaces": True})
        assert cfg.indent_size == 2
        assert cfg.insert_spaces is True


class TestBslConfigIndex:
    def test_index_defaults(self) -> None:
        cfg = BslConfig({})
        assert cfg.index_mode == "full"
        assert cfg.index_max_bytes == 0

    def test_index_options(self) -> None:
        cfg = BslConfig({"index-mode": "symbols", "index-max-bytes": 1234})
        assert cfg.index_mode == "symbols"
        assert cfg.index_max_bytes == 1234

    def test_invalid_index_options(self) -> None:
        with pytest.raises(ValueError, match="index-mode"):
            _ = BslConfig({"index-mode": "remote"}).index_mode
        with pytest.raises(ValueError, match="index-max-bytes"):
            _ = BslConfig({"index-max-bytes": -1}).index_max_bytes


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


class TestResolvedConfig:
    def test_precedence_matrix_covers_scalar_bool_and_collections(self) -> None:
        project = BslConfig(
            {
                "format": "sarif",
                "jobs": 8,
                "exit-zero": True,
                "select": ["BSL001"],
                "exclude": ["project/**"],
                "per-file-ignores": {"project.bsl": ["BSL001"]},
                "insert-spaces": True,
            }
        )
        resolved = resolve_config(
            project,
            environ={"BSL_SELECT": "BSL002"},
            format="text",
            jobs=0,
            exit_zero=False,
            exclude=[],
            per_file_ignores={"explicit.bsl": ["BSL003"]},
            insert_spaces=False,
        )

        assert resolved.format == "text"
        assert resolved.jobs == 0
        assert resolved.exit_zero is False
        assert resolved.select == {"BSL002"}
        assert resolved.exclude == []
        assert resolved.index_exclude == []
        assert resolved.per_file_ignores == {"explicit.bsl": ["BSL003"]}
        assert resolved.insert_spaces is False

    def test_environment_overrides_project_for_supported_values(self) -> None:
        resolved = resolve_config(
            BslConfig(
                {
                    "select": ["BSL001"],
                    "ignore": ["BSL002"],
                    "index-mode": "full",
                    "index-max-bytes": 100,
                }
            ),
            environ={
                "BSL_SELECT": "BSL003",
                "BSL_IGNORE": "BSL004",
                "BSL_INDEX_MODE": "symbols",
                "BSL_INDEX_MAX_BYTES": "200",
            },
        )

        assert resolved.select == {"BSL003"}
        assert resolved.ignore == {"BSL004"}
        assert resolved.index_mode == "symbols"
        assert resolved.index_max_bytes == 200

    def test_defaults_are_complete_and_snapshot_is_immutable(self) -> None:
        resolved = resolve_config(BslConfig({}), environ={})

        assert isinstance(resolved, ResolvedConfig)
        assert resolved.format == "text"
        assert resolved.jobs == 0
        assert resolved.exit_zero is False
        assert resolved.indent_size == 4
        assert resolved.insert_spaces is False
        with pytest.raises(AttributeError, match="immutable"):
            resolved._data = {}  # type: ignore[misc]

    def test_same_fixture_resolves_identically_through_public_adapters(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from onec_hbk_bsl.cli.check import resolve_check_config
        from onec_hbk_bsl.lsp.server import _resolve_workspace_config
        from onec_hbk_bsl.mcp_bridge import server as mcp_server

        (tmp_path / "onec-hbk-bsl.toml").write_text(
            "\n".join(
                (
                    'select = ["BSL001"]',
                    'ignore = ["BSL002"]',
                    'exclude = ["vendor/**"]',
                    'per-file-ignores = { "legacy.bsl" = ["BSL003"] }',
                    "insert-spaces = true",
                    "indent-size = 2",
                )
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("BSL_SELECT", raising=False)
        monkeypatch.delenv("BSL_IGNORE", raising=False)
        monkeypatch.delenv("BSL_INDEX_MODE", raising=False)
        monkeypatch.delenv("BSL_INDEX_MAX_BYTES", raising=False)
        monkeypatch.setattr(mcp_server, "_ALLOWED_WORKSPACE_ROOTS", (tmp_path.resolve(),))
        monkeypatch.setattr(mcp_server, "_WORKSPACE", str(tmp_path.resolve()))

        cli = resolve_check_config(load_config(str(tmp_path)))
        lsp = _resolve_workspace_config(str(tmp_path))
        mcp = mcp_server._resolve_mcp_config(str(tmp_path))

        def signature(cfg: ResolvedConfig) -> tuple[object, ...]:
            return (
                cfg.select,
                cfg.ignore,
                cfg.exclude,
                cfg.per_file_ignores,
                cfg.indent_size,
                cfg.insert_spaces,
            )

        assert signature(cli) == signature(lsp) == signature(mcp)


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
        (tmp_path / "onec-hbk-bsl.toml").write_text('ignore = ["BSL002"]\n', encoding="utf-8")
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
        (tmp_path / "onec-hbk-bsl.toml").write_text('select = ["BSL009"]\n', encoding="utf-8")
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
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\naddopts = []\n", encoding="utf-8")
        cfg = load_config(str(tmp_path))
        assert cfg.select is None

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text("this is not valid toml [[[", encoding="utf-8")
        cfg = load_config(str(tmp_path))
        assert cfg.select is None

    def test_config_thresholds(self, tmp_path: Path) -> None:
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            "max-line-length = 120\nmax-proc-lines = 80\n",
            encoding="utf-8",
        )
        cfg = load_config(str(tmp_path))
        assert cfg.max_line_length == 120
        assert cfg.max_proc_lines == 80

    def test_empty_singleton(self) -> None:
        assert _EMPTY.select is None
        assert _EMPTY.ignore is None
        assert _EMPTY.exclude == []
