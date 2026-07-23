from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "compare_diag_bslls.py"
    spec = importlib.util.spec_from_file_location("compare_diag_bslls", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_rule_codes_accepts_internal_and_bslls_names() -> None:
    mod = _load_script_module()

    assert mod.normalize_rule_codes("BSL216,CommentedCode; UsingThisForm") == frozenset(
        {"BSL216", "BSL013", "BSL040"}
    )


def test_bslls_keys_filters_to_selected_rules_and_keeps_ranges(tmp_path: Path) -> None:
    mod = _load_script_module()
    source = tmp_path / "src"
    source.mkdir()
    file_path = source / "Module.bsl"
    file_path.write_text("", encoding="utf-8")
    raw = {
        "fileinfos": [
            {
                "mdoRef": file_path.as_uri(),
                "path": file_path.as_uri(),
                "diagnostics": [
                    {
                        "code": "MissingSpace",
                        "range": {
                            "start": {"line": 1, "character": 5},
                            "end": {"line": 1, "character": 6},
                        },
                    },
                    {
                        "code": "UnusedLocalVariable",
                        "range": {
                            "start": {"line": 1, "character": 4},
                            "end": {"line": 1, "character": 5},
                        },
                    },
                ],
            }
        ]
    }

    parsed = mod.bslls_keys(raw, source, source, frozenset({"BSL216"}))

    assert parsed.counts == Counter(
        {
            mod.DiagnosticKey(
                file_key="Module.bsl",
                line=2,
                character=5,
                end_line=2,
                end_character=6,
                code="BSL216",
            ): 1
        }
    )
    assert parsed.unmappable == ()


def test_onec_keys_filters_cli_json_to_selected_rules(tmp_path: Path) -> None:
    mod = _load_script_module()
    source = tmp_path / "src"
    source.mkdir()
    file_path = source / "Module.bsl"
    file_path.write_text("", encoding="utf-8")
    raw = [
        {
            "file": str(file_path),
            "line": 2,
            "character": 5,
            "end_line": 2,
            "end_character": 6,
            "code": "BSL216",
        },
        {
            "file": str(file_path),
            "line": 2,
            "character": 4,
            "end_line": 2,
            "end_character": 5,
            "code": "BSL007",
        },
    ]

    parsed = mod.onec_keys(raw, source, frozenset({"BSL216"}))

    assert parsed.counts == Counter(
        {
            mod.DiagnosticKey(
                file_key="Module.bsl",
                line=2,
                character=5,
                end_line=2,
                end_character=6,
                code="BSL216",
            ): 1
        }
    )
    assert parsed.unmappable == ()


def test_related_information_uri_wins_per_diagnostic_and_keeps_same_basenames(
    tmp_path: Path,
) -> None:
    mod = _load_script_module()
    source = tmp_path / "src"
    first = source / "Catalogs" / "A" / "Module.bsl"
    second = source / "Catalogs" / "B" / "Module.bsl"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    raw = {
        "fileinfos": [
            {
                "path": first.as_uri(),
                "diagnostics": [
                    {
                        "code": "MissingSpace",
                        "range": {
                            "start": {"line": 0, "character": 1},
                            "end": {"line": 0, "character": 2},
                        },
                        "relatedInformation": [{"location": {"uri": first.as_uri(), "range": {}}}],
                    },
                    {
                        "code": "MissingSpace",
                        "range": {
                            "start": {"line": 0, "character": 1},
                            "end": {"line": 0, "character": 2},
                        },
                        "relatedInformation": [{"location": {"uri": second.as_uri(), "range": {}}}],
                    },
                ],
            }
        ]
    }

    parsed = mod.bslls_keys(raw, source, source, frozenset({"BSL216"}))

    assert {key.file_key for key in parsed.counts} == {
        "Catalogs/A/Module.bsl",
        "Catalogs/B/Module.bsl",
    }
    assert parsed.counts.total() == 2


def test_unmappable_related_uri_does_not_fall_back_to_fileinfo_basename(
    tmp_path: Path,
) -> None:
    mod = _load_script_module()
    source = tmp_path / "src"
    source.mkdir()
    mapped = source / "Module.bsl"
    mapped.write_text("", encoding="utf-8")
    raw = {
        "fileinfos": [
            {
                "path": mapped.as_uri(),
                "diagnostics": [
                    {
                        "code": "MissingSpace",
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "relatedInformation": [
                            {
                                "location": {
                                    "uri": (tmp_path.parent / "outside" / "Module.bsl").as_uri()
                                }
                            }
                        ],
                    }
                ],
            }
        ]
    }

    parsed = mod.bslls_keys(raw, source, source, frozenset({"BSL216"}))

    assert parsed.counts == Counter()
    assert parsed.unmappable == (
        mod.UnmappableDiagnostic(
            "bslls",
            1,
            "BSL216",
            "relatedInformation URI is outside allowed roots",
        ),
    )


def test_multiset_comparison_classifies_exact_statement_line_and_duplicates() -> None:
    mod = _load_script_module()

    def key(line: int, character: int, end_character: int) -> object:
        return mod.DiagnosticKey("Module.bsl", line, character, line, end_character, "BSL216")

    ours = Counter({key(1, 0, 1): 2, key(2, 2, 5): 1, key(3, 1, 2): 1, key(8, 0, 1): 1})
    theirs = Counter({key(1, 0, 1): 1, key(2, 2, 8): 1, key(3, 4, 5): 1, key(9, 0, 1): 1})

    comparison = mod.compare_diagnostics(ours, theirs)

    assert comparison.exact == 1
    assert comparison.statement == 1
    assert comparison.line == 1
    assert comparison.range_only == 2
    assert comparison.duplicate_onec == 1
    assert comparison.duplicate_bslls == 0
    assert comparison.duplicate_common == 0
    assert comparison.duplicate_delta == 1
    assert comparison.only_onec.total() == 1
    assert comparison.only_bslls.total() == 1

    matching_duplicates = mod.compare_diagnostics(
        Counter({key(1, 0, 1): 2}),
        Counter({key(1, 0, 1): 2}),
    )
    assert matching_duplicates.exact == 1
    assert matching_duplicates.duplicate_common == 1
    assert matching_duplicates.duplicate_delta == 0
    assert not matching_duplicates.has_deltas


def test_bslls_file_key_uses_edt_suffix_for_cwd_prefixed_uri(tmp_path: Path) -> None:
    mod = _load_script_module()
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    path = (
        tmp_path
        / "repo"
        / "DataProcessors"
        / "Demo"
        / "Forms"
        / "Form"
        / "Ext"
        / "Form"
        / "Module.bsl"
    )
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    file_key = mod._bslls_file_key({"path": path.as_uri()}, source, workspace)

    assert file_key == "DataProcessors/Demo/Forms/Form/Ext/Form/Module.bsl"


def test_bslls_file_key_uses_root_ext_suffix_for_session_module(tmp_path: Path) -> None:
    mod = _load_script_module()
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    path = tmp_path / "repo" / "Ext" / "SessionModule.bsl"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    file_key = mod._bslls_file_key({"path": path.as_uri()}, source, workspace)

    assert file_key == "Ext/SessionModule.bsl"


def test_write_bslls_config_uses_only_mode_and_bslls_names(tmp_path: Path) -> None:
    mod = _load_script_module()
    config_path = tmp_path / "bslls.json"

    mod._write_bslls_config(config_path, frozenset({"BSL216", "BSL040"}))

    assert config_path.read_text(encoding="utf-8") == (
        "{\n"
        '  "language": "en",\n'
        '  "diagnostics": {\n'
        '    "mode": "ONLY",\n'
        '    "parameters": {\n'
        '      "UsingThisForm": true,\n'
        '      "MissingSpace": true\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


def test_find_bslls_jar_prefers_latest_autodiscovered_exec_jar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_script_module()
    repo_root = tmp_path / "repo"
    local_dir = repo_root / ".nosync" / "bsl-language-server"
    local_dir.mkdir(parents=True)
    old_jar = local_dir / "bsl-language-server-0.29.0-exec.jar"
    new_jar = local_dir / "bsl-language-server-1.0.0-exec.jar"
    old_jar.write_text("", encoding="utf-8")
    new_jar.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("BSLLS_JAR", raising=False)

    assert mod.find_bslls_jar(repo_root) == new_jar.resolve()


def test_find_bslls_jar_keeps_explicit_path_priority(tmp_path: Path) -> None:
    mod = _load_script_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    explicit = tmp_path / "custom.jar"
    explicit.write_text("", encoding="utf-8")

    assert mod.find_bslls_jar(repo_root, explicit) == explicit.resolve()


def test_copy_inputs_preserves_workspace_relative_paths(tmp_path: Path) -> None:
    mod = _load_script_module()
    workspace = tmp_path / "workspace"
    nested = workspace / "Catalogs" / "Demo" / "Forms" / "Form" / "Ext"
    nested.mkdir(parents=True)
    source_file = nested / "Module.bsl"
    source_file.write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
    temp_source = tmp_path / "source"
    temp_source.mkdir()

    copied = mod._copy_inputs([source_file], workspace, temp_source)

    assert copied == [temp_source / "Catalogs" / "Demo" / "Forms" / "Form" / "Ext" / "Module.bsl"]
    assert copied[0].read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8")


def test_main_captured_json_is_byte_stable_and_covers_exit_codes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _load_script_module()
    onec_path = tmp_path / "onec.json"
    bslls_path = tmp_path / "bslls.json"
    onec_payload = [
        {
            "file": "Catalogs/A/Module.bsl",
            "line": 2,
            "character": 5,
            "end_line": 2,
            "end_character": 6,
            "code": "BSL216",
        }
    ]
    bslls_payload = {
        "fileinfos": [
            {
                "path": "Catalogs/A/Module.bsl",
                "diagnostics": [
                    {
                        "code": "MissingSpace",
                        "range": {
                            "start": {"line": 1, "character": 5},
                            "end": {"line": 1, "character": 6},
                        },
                    }
                ],
            }
        ]
    }
    onec_path.write_text(json.dumps(onec_payload), encoding="utf-8")
    bslls_path.write_text(json.dumps(bslls_payload), encoding="utf-8")
    args = [
        "--workspace",
        str(tmp_path),
        "--select",
        "BSL216",
        "--format",
        "json",
        "--onec-json",
        str(onec_path),
        "--bslls-json",
        str(bslls_path),
    ]

    assert mod.main(args) == 0
    first = capsys.readouterr().out
    assert mod.main(args) == 0
    second = capsys.readouterr().out
    assert first == second
    assert json.loads(first)["counts"]["exact"] == 1

    bslls_payload["fileinfos"][0]["diagnostics"][0]["range"]["end"]["character"] = 9
    bslls_path.write_text(json.dumps(bslls_payload), encoding="utf-8")
    assert mod.main(args) == 1
    mismatch = json.loads(capsys.readouterr().out)
    assert mismatch["counts"]["statement"] == 1
    assert mismatch["counts"]["range_only"] == 1

    bslls_payload["fileinfos"][0]["diagnostics"][0]["relatedInformation"] = [
        {"location": {"uri": (tmp_path.parent / "outside" / "UnknownRoot" / "Module.bsl").as_uri()}}
    ]
    bslls_path.write_text(json.dumps(bslls_payload), encoding="utf-8")
    assert mod.main(args) == 2
    unmappable = json.loads(capsys.readouterr().out)
    assert unmappable["counts"]["unmappable"] == 1
    assert "UnknownRoot" not in json.dumps(unmappable)

    assert mod.main(args[:-2]) == 3
    assert "--onec-json and --bslls-json" in capsys.readouterr().err
