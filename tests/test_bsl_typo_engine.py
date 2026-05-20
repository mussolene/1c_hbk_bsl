from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_typo import (
    contains_cyrillic_letter,
    contains_latin_letter,
    split_by_character_type_camel_case,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def test_cyrillic_pe_is_not_latin() -> None:
    assert contains_cyrillic_letter("П")
    assert not contains_latin_letter("П")
    assert contains_latin_letter("P")


def test_camel_case_split_keeps_cyrillic_parts() -> None:
    assert split_by_character_type_camel_case("ВаринатыОплаты") == ["Варинаты", "Оплаты"]


def test_domain_vzaimoraschet_tokens_are_not_typos(tmp_path) -> None:
    path = tmp_path / "Module.bsl"
    path.write_text(
        'Процедура Тест()\n    Сообщить("Взаиморасчетами");\nКонецПроцедуры\n',
        encoding="utf-8",
    )

    diags = DiagnosticEngine(select={"BSL256"}).check_file(str(path))

    assert not any("Взаиморасчет" in diag.message for diag in diags)


def test_bslls_typo_prefers_later_bad_part_when_code_prefix_is_accepted(tmp_path) -> None:
    path = tmp_path / "Module.bsl"
    path.write_text(
        (
            "Процедура Тест()\n"
            '    ПроизвРасхСО = ПолучитьПодчиненныйЭлемент("ПроизвРасхСО");\n'
            "КонецПроцедуры\n"
        ),
        encoding="utf-8",
    )

    messages = [diag.message for diag in DiagnosticEngine(select={"BSL256"}).check_file(str(path))]

    assert any('"Расх"' in message for message in messages)
    assert not any('"Произв"' in message for message in messages)


def test_bslls_typo_reports_string_abbreviations_after_ignored_latin_homoglyph(
    tmp_path,
) -> None:
    path = tmp_path / "Module.bsl"
    path.write_text(
        (
            "Процедура Тест()\n"
            '    Сообщить("Уточните cумму страховых взносов в стр.080 подр.1");\n'
            "КонецПроцедуры\n"
        ),
        encoding="utf-8",
    )

    messages = [diag.message for diag in DiagnosticEngine(select={"BSL256"}).check_file(str(path))]

    assert any('"подр"' in message for message in messages)
    assert not any('"cумму"' in message for message in messages)
