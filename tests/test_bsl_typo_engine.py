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
