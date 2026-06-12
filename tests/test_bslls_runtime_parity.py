from pathlib import Path

from onec_hbk_bsl.analysis import bslls_runtime_parity as parity
from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity


def test_parse_java_major_version() -> None:
    assert parity._parse_java_major_version('openjdk version "25.0.2" 2026-01-20') == 25
    assert parity._parse_java_major_version('java version "1.8.0_491"') == 8


def test_resolve_bslls_java_skips_java8(monkeypatch, tmp_path: Path) -> None:
    java8 = tmp_path / "java8"
    java8.write_text("", encoding="utf-8")
    home = tmp_path / "jdk25"
    java25 = home / "bin" / "java"
    java25.parent.mkdir(parents=True)
    java25.write_text("", encoding="utf-8")

    monkeypatch.setenv("BSLLS_JAVA", str(java8))
    monkeypatch.setenv("JAVA_HOME", str(home))
    monkeypatch.setattr(parity.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        parity,
        "_java_major_version",
        lambda path: 8 if path == java8 else 25,
    )

    assert parity.resolve_bslls_java() == java25.resolve()


def test_normalize_our_diagnostics_keeps_bsl_code_and_rule_name(tmp_path: Path) -> None:
    source = tmp_path / "module.bsl"
    diag = Diagnostic(
        file=str(source),
        line=1,
        character=0,
        end_line=1,
        end_character=5,
        severity=Severity.INFORMATION,
        code="BSL256",
        message="typo",
    )

    rows = parity.normalize_our_diagnostics([diag], workspace_root=tmp_path)

    assert rows[0].code == "BSL256"
    assert rows[0].code_source == "BSL256"
    assert rows[0].rule_name == "Typo"


def test_normalize_bslls_json_report_maps_rule_name_to_bsl_code(tmp_path: Path) -> None:
    source = tmp_path / "module.bsl"
    report = {
        "fileinfos": [
            {
                "path": str(source),
                "diagnostics": [
                    {
                        "code": "Typo",
                        "severity": "HINT",
                        "message": "typo",
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 5},
                        },
                    }
                ],
            }
        ]
    }

    rows = parity.normalize_bslls_json_report(report, workspace_root=tmp_path)

    assert rows[0].code == "BSL256"
    assert rows[0].code_source == "Typo"
    assert rows[0].rule_name == "Typo"


def test_diff_diagnostics_matches_by_bsl_code_not_rule_name() -> None:
    ours = parity.NormalizedDiagnostic(
        file="module.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=5,
        severity="HINT",
        code="BSL256",
        code_source="BSL256",
        rule_name="Typo",
        message="typo",
        message_norm="typo",
    )
    bslls = parity.NormalizedDiagnostic(
        file="module.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=5,
        severity="HINT",
        code="BSL256",
        code_source="Typo",
        rule_name="Typo",
        message="typo",
        message_norm="typo",
    )

    diff = parity.diff_diagnostics([ours], [bslls])

    assert diff["exact_match"] is True
    assert diff["only_ours"] == []
    assert diff["only_bslls"] == []
