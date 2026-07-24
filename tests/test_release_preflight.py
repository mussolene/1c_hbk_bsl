from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_release.py"
SPEC = importlib.util.spec_from_file_location("verify_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_release)


def _coverage(path: Path, parser_covered: int = 63) -> Path:
    data = {
        "totals": {"percent_covered": 80.5},
        "files": {
            "src/onec_hbk_bsl/parser/example.py": {
                "executed_lines": list(range(1, parser_covered + 1)),
                "missing_lines": list(range(parser_covered + 1, 101)),
                "summary": {
                    "covered_lines": parser_covered,
                    "num_statements": 100,
                },
            },
            "src/onec_hbk_bsl/lsp/example.py": {
                "executed_lines": list(range(1, 75)),
                "missing_lines": list(range(75, 101)),
                "summary": {"covered_lines": 74, "num_statements": 100},
            },
            "src/onec_hbk_bsl/mcp_bridge/example.py": {
                "executed_lines": list(range(1, 69)),
                "missing_lines": list(range(69, 101)),
                "summary": {"covered_lines": 68, "num_statements": 100},
            },
            "src/onec_hbk_bsl/indexer/example.py": {
                "executed_lines": list(range(1, 82)),
                "missing_lines": list(range(82, 101)),
                "summary": {"covered_lines": 81, "num_statements": 100},
            },
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_component_coverage_floor_rejects_controlled_regression(tmp_path: Path) -> None:
    path = _coverage(tmp_path / "coverage.json", parser_covered=62)
    with pytest.raises(ValueError, match="parser"):
        verify_release.verify_coverage(path)


def test_diff_coverage_uses_only_changed_executable_lines(tmp_path: Path) -> None:
    path = _coverage(tmp_path / "coverage.json")
    with pytest.raises(ValueError, match="diff 50.00%"):
        verify_release.verify_coverage(
            path,
            changed_lines={"src/onec_hbk_bsl/parser/example.py": {62, 64}},
        )


def test_release_publish_jobs_depend_on_full_preflight() -> None:
    verify_release.verify_release_dag()


def test_rule_contract_has_exact_runtime_parity() -> None:
    contract = verify_release.source_contract()
    assert len(contract["rules"]) == 180
    assert contract["rules"] == contract["runtime_rules"]
    assert len(contract["platform_api"]["types"]) > 50


def test_missing_artifact_blocks_preflight(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing release artifacts"):
        verify_release.verify_artifacts(tmp_path, "0.8.43", tmp_path / "out")


def test_checksum_manifest_is_independent_of_input_order(tmp_path: Path) -> None:
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    manifest = tmp_path / "SHA256SUMS"
    verify_release.write_checksum_manifest([second, first], manifest)
    forward = manifest.read_text(encoding="utf-8")
    verify_release.write_checksum_manifest([first, second], manifest)
    assert manifest.read_text(encoding="utf-8") == forward
    assert forward.splitlines()[0].endswith("  a.bin")


def test_pull_request_preflight_accepts_non_empty_unreleased_section(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Correct pull request preflight.\n",
        encoding="utf-8",
    )

    verify_release.verify_changelog(
        "0.8.44",
        allow_unreleased=True,
        changelog_path=changelog,
    )


def test_pull_request_preflight_rejects_empty_unreleased_section(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.8.43] - 2026-07-23\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no non-empty Unreleased section"):
        verify_release.verify_changelog(
            "0.8.44",
            allow_unreleased=True,
            changelog_path=changelog,
        )


def test_tag_preflight_still_requires_exact_dated_section(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Pending change.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no dated 0.8.44 section"):
        verify_release.verify_changelog("0.8.44", changelog_path=changelog)


def test_local_markdown_link_checker_validates_paths_and_anchors(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "README.md").write_text(
        "# Root\n\n[Details](docs/details.md#known-fact)\n",
        encoding="utf-8",
    )
    (docs / "details.md").write_text("# Details\n\n## Known fact\n", encoding="utf-8")

    verify_release.verify_local_markdown_links(tmp_path)

    (tmp_path / "README.md").write_text("[Missing](docs/details.md#absent)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing anchor"):
        verify_release.verify_local_markdown_links(tmp_path)


def test_public_documentation_requires_bilingual_product_pages(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    extension = tmp_path / "vscode-extension"
    extension.mkdir()
    (extension / "package.json").write_text(
        json.dumps({"contributes": {"configuration": {"properties": {"setting.one": {}}}}}),
        encoding="utf-8",
    )
    bilingual = '<div class="doc-lang-ru"></div><div class="doc-lang-en"></div>'
    for name in verify_release.REQUIRED_PUBLIC_DOCS:
        text = bilingual + ("`setting.one`" if name == "extension.md" else "")
        (docs / name).write_text(text, encoding="utf-8")
    verify_release.verify_public_documentation(tmp_path)

    (docs / "index.md").write_text('<div class="doc-lang-ru"></div>', encoding="utf-8")
    with pytest.raises(ValueError, match="not bilingual"):
        verify_release.verify_public_documentation(tmp_path)


def test_mkdocs_i18n_hook_removes_inactive_nested_blocks() -> None:
    hook_path = SCRIPT.parent / "mkdocs_i18n.py"
    hook_spec = importlib.util.spec_from_file_location("mkdocs_i18n", hook_path)
    assert hook_spec is not None and hook_spec.loader is not None
    hook = importlib.util.module_from_spec(hook_spec)
    hook_spec.loader.exec_module(hook)
    source = (
        '# <span class="doc-lang doc-lang-ru">RU</span>'
        '<span class="doc-lang doc-lang-en">EN</span>\n'
        '<div class="doc-lang doc-lang-ru" markdown="1">\n'
        'Русский\n<div class="grid cards">\nКарточка\n</div>\n</div>\n'
        '<div class="doc-lang doc-lang-en" markdown="1">\nEnglish\n</div>\n'
    )

    rendered = hook.on_page_markdown(
        source,
        page=None,
        config={"extra": {"doc_locale": "ru"}},
        files=None,
    )

    assert "Русский" in rendered
    assert "Карточка" in rendered
    assert "English" not in rendered
    assert ">EN<" not in rendered


def test_published_docs_reject_adjacent_analyzer_links(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "index.md"
    page.write_text("# Docs\n\nNo adjacent links.\n", encoding="utf-8")
    verify_release.verify_published_docs_independence(tmp_path)

    page.write_text(
        "# Docs\n\n[Adjacent](https://github.com/1c-syntax/bsl-language-server)\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="adjacent analyzer"):
        verify_release.verify_published_docs_independence(tmp_path)


def test_changelog_integrity_requires_repaired_history_and_latest_base(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n- Pending.\n\n"
        "## [0.8.44] - 2026-07-23\n\n- Current.\n\n"
        "## [0.8.42] - 2026-07-16\n\n- Performance.\n\n"
        "## [0.8.41] - 2026-07-13\n\n- Compatibility.\n\n"
        "[Unreleased]: https://example.test/compare/v0.8.44...HEAD\n"
        "[0.8.44]: https://example.test/compare/v0.8.43...v0.8.44\n"
        "[0.8.42]: https://example.test/compare/v0.8.41...v0.8.42\n"
        "[0.8.41]: https://example.test/compare/v0.8.40...v0.8.41\n",
        encoding="utf-8",
    )
    verify_release.verify_changelog_integrity(changelog)

    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace("v0.8.44...HEAD", "v0.8.43...HEAD"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="latest dated release"):
        verify_release.verify_changelog_integrity(changelog)


def test_core_and_meta_package_public_metadata_match() -> None:
    verify_release.verify_package_metadata()


def test_community_files_have_required_reporting_and_reproduction_fields() -> None:
    verify_release.verify_community_files()
