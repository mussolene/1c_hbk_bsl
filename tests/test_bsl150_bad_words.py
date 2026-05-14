"""BSL150 BadWords — BSLLS default empty pattern; optional regex via engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def test_bsl150_default_pattern_emits_nothing() -> None:
    engine = DiagnosticEngine(select={"BSL150"})
    src = "// foo\nПроцедура Тест() КонецПроцедуры\n"
    diags = engine.check_content("m.bsl", src)
    assert [d.code for d in diags] == []


def test_bsl150_with_pattern_finds_word() -> None:
    engine = DiagnosticEngine(
        select={"BSL150"},
        bad_words_pattern=r"BADWORD",
    )
    src = "Процедура Тест() // BADWORD here\nКонецПроцедуры\n"
    diags = engine.check_content("m.bsl", src)
    assert len(diags) == 1
    assert diags[0].code == "BSL150"
    assert diags[0].line == 1
    assert diags[0].message == "В тексте модуля найдено запрещенное слово <BADWORD>."


def test_bsl150_matches_bslls_configured_fixture() -> None:
    fixture = Path(".agent/tmp/bslls-source/src/test/resources/diagnostics/BadWordsDiagnostic.bsl")
    if not fixture.exists():
        pytest.skip("BSLLS fixture is not available")

    diags = [
        diag
        for diag in DiagnosticEngine(
            select={"BSL150"}, bad_words_pattern="лотус|шмотус"
        ).check_file(str(fixture))
        if diag.code == "BSL150"
    ]

    assert [(d.message, d.line, d.character, d.end_line, d.end_character) for d in diags] == [
        ("В тексте модуля найдено запрещенное слово <лотус>.", 1, 42, 1, 47),
        ("В тексте модуля найдено запрещенное слово <шмотус>.", 1, 48, 1, 54),
        ("В тексте модуля найдено запрещенное слово <Лотус>.", 5, 4, 5, 9),
        ("В тексте модуля найдено запрещенное слово <Лотус>.", 7, 24, 7, 29),
        ("В тексте модуля найдено запрещенное слово <Лотус>.", 7, 34, 7, 39),
        ("В тексте модуля найдено запрещенное слово <Шмотус>.", 9, 4, 9, 10),
    ]
