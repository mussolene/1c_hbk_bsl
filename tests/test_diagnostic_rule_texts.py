from __future__ import annotations

from onec_hbk_bsl.analysis.diagnostics import (
    _BSLLS_NAME_TO_CODE,
    RULE_DESCRIPTIONS_RU,
    RULE_METADATA,
    Diagnostic,
    Severity,
    bslls_message_for_rule_code,
    lsp_compat_severity,
)
from onec_hbk_bsl.lsp.diagnostics_ru import (
    localize_rule_description,
    localize_rule_title,
    translate_message,
)


def test_all_bslls_rules_have_ru_titles() -> None:
    assert set(RULE_DESCRIPTIONS_RU) == set(_BSLLS_NAME_TO_CODE.values())


def test_problematic_ru_titles_match_bslls_meaning() -> None:
    expected = {
        "BSL022": "Использование модальных окон",
        "BSL025": "Пустой оператор",
        "BSL065": "Отсутствует описание возвращаемого значения функции",
        "BSL174": "Запрет незаполненных значений у измерений регистров",
    }
    for code, title in expected.items():
        assert RULE_DESCRIPTIONS_RU[code] == title
        assert localize_rule_title(code) == title
        assert translate_message(code, "legacy local wording") == title


def test_metadata_descriptions_use_bslls_english_titles() -> None:
    expected = {
        "BSL022": "Using modal windows",
        "BSL025": "Empty statement",
        "BSL065": "Function returned values description is missing",
        "BSL174": "Deny incomplete values for dimensions",
    }
    for code, title in expected.items():
        assert RULE_METADATA[code]["description"] == title


def test_public_rule_descriptions_are_localized_for_ui() -> None:
    expected = {
        "BSL022": "Использование модальных окон",
        "BSL025": "Пустой оператор",
        "BSL065": "Отсутствует описание возвращаемого значения функции",
        "BSL174": "Запрет незаполненных значений у измерений регистров",
    }
    for code, title in expected.items():
        assert localize_rule_description(code) == title


def test_structured_diagnostics_include_bslls_rule_message() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL159",
        message="local occurrence detail",
    )

    assert bslls_message_for_rule_code("BSL159") == "Общий модуль недопустимого типа"
    assert diag.to_dict(include_rule_name=True)["rule_message"] == (
        "Общий модуль недопустимого типа"
    )


def test_metadata_sonar_type_and_severity_follow_bslls() -> None:
    expected = {
        "BSL001": ("ERROR", "CRITICAL"),
        "BSL022": ("CODE_SMELL", "MAJOR"),
        "BSL164": ("SECURITY_HOTSPOT", "MAJOR"),
        "BSL174": ("CODE_SMELL", "MAJOR"),
    }
    for code, (sonar_type, sonar_severity) in expected.items():
        assert RULE_METADATA[code]["sonar_type"] == sonar_type
        assert RULE_METADATA[code]["sonar_severity"] == sonar_severity


def test_lsp_compat_severity_documents_bslls_facing_source_of_truth() -> None:
    expected = {
        "BSL156": Severity.HINT,  # CodeOutOfRegion
        "BSL256": Severity.HINT,  # Typo
        "BSL200": Severity.HINT,  # IncorrectLineBreak
        "BSL249": Severity.ERROR,  # StyleElementConstructors
    }
    for code, severity in expected.items():
        metadata_severity = Severity[RULE_METADATA[code]["severity"]]
        assert lsp_compat_severity(code, metadata_severity) is severity


def test_unknown_rule_title_does_not_use_generic_translation_fallback() -> None:
    assert localize_rule_title("BSL999") == "BSL999"
