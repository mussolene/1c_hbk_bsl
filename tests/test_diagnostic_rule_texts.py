from __future__ import annotations

import importlib.util
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
from onec_hbk_bsl.analysis.diagnostics import (
    _BSLLS_NAME_TO_CODE,
    RULE_DESCRIPTIONS_RU,
    RULE_METADATA,
    Diagnostic,
    Severity,
    lsp_compat_severity,
)


def _load_rules_doc_builder():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_diagnostic_rules_doc.py"
    spec = importlib.util.spec_from_file_location("build_diagnostic_rules_doc", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        assert get_rule(code).description == title
        assert get_rule(code).message


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
        assert get_rule(code).description == title


def test_structured_diagnostics_include_catalog_message() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL159",
    )

    assert get_rule("BSL159").message == "Общий модуль недопустимого типа"
    assert diag.to_dict(include_rule_name=True)["rule_message"] == (
        "Общий модуль недопустимого типа"
    )


def test_rule_catalog_resolves_code_and_bslls_name_to_same_rule() -> None:
    by_code = get_rule("BSL236")
    by_name = get_rule("QueryToMissingMetadata")

    assert by_code == by_name
    assert by_code.code == "BSL236"
    assert by_code.name == "QueryToMissingMetadata"
    assert by_code.description == "Обращение к несуществующим метаданным в запросе"
    assert by_code.message == "Обращение к несуществующим метаданным в запросе"
    assert by_code.severity == "ERROR"
    assert by_code.tags == ("query", "correctness")
    assert by_code.implemented is True


def test_rule_catalog_can_return_english_rule_text() -> None:
    rule = get_rule("RefOveruse", locale="en")

    assert rule.code == "BSL238"
    assert rule.name == "RefOveruse"
    assert rule.description == 'Overuse "Reference" in a query'
    assert rule.message == 'Overuse "Reference" in a query'


def test_bsl241_rule_catalog_severity_matches_emitted_error() -> None:
    rule = get_rule("BSL241")

    assert rule.name == "SameMetadataObjectAndChildNames"
    assert rule.severity == "ERROR"


def test_diagnostic_uses_i18n_message_by_default() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL236",
    )

    assert diag.message == get_rule("BSL236").message


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
    assert get_rule("BSL999").description == "BSL999"


def test_diagnostic_rules_doc_is_generated_from_registry() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "diagnostic-rules.md"
    assert doc_path.read_text(encoding="utf-8") == _load_rules_doc_builder().build_markdown()
