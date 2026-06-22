from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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

    keys = mod.bslls_keys(raw, source, source, frozenset({"BSL216"}))

    assert keys == {
        mod.DiagnosticKey(
            file_key="Module.bsl",
            line=2,
            character=5,
            end_line=2,
            end_character=6,
            code="BSL216",
        )
    }


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

    keys = mod.onec_keys(raw, source, frozenset({"BSL216"}))

    assert keys == {
        mod.DiagnosticKey(
            file_key="Module.bsl",
            line=2,
            character=5,
            end_line=2,
            end_character=6,
            code="BSL216",
        )
    }


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
