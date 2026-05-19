from pathlib import Path

from onec_hbk_bsl.analysis import bslls_runtime_parity as parity


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
