from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_typo import (
    contains_cyrillic_letter,
    contains_latin_letter,
    split_by_character_type_camel_case,
)
from onec_hbk_bsl.analysis.bsl_typo.candidates import collect_spell_candidates
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.parser.bsl_parser import BslParser


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

    diags = [
        diag
        for diag in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
        if diag.code == "BSL256"
    ]

    assert diags


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

    diags = [
        diag
        for diag in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
        if diag.code == "BSL256"
    ]

    assert diags


def test_typo_candidates_from_materialized_nodes_match_tree_walk() -> None:
    content = (
        "Процедура Тест()\n"
        "    ВаринатыОплаты = Объект.ВаринатыОплаты;\n"
        '    Сообщить("Варинаты оплаты");\n'
        "КонецПроцедуры\n"
    )
    tree = BslParser().parse_content(content, file_path="Module.bsl")
    root = tree.root_node
    nodes_by_type = {"identifier": [], "property": [], "string": []}
    stack = [root]
    while stack:
        node = stack.pop()
        node_type = getattr(node, "type", None)
        if node_type in nodes_by_type:
            nodes_by_type[node_type].append(node)
        stack.extend(reversed(getattr(node, "children", ()) or ()))

    walked = collect_spell_candidates(tree=tree)
    materialized = collect_spell_candidates(tree=tree, nodes_by_type=nodes_by_type)

    assert materialized == walked


def test_repeated_typo_fragment_emits_one_diagnostic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
        lambda word: word == "Атмена",
    )
    path = tmp_path / "Module.bsl"
    path.write_text(
        'Процедура Тест()\n    Сообщить("Атмена Атмена");\nКонецПроцедуры\n',
        encoding="utf-8",
    )

    diagnostics = DiagnosticEngine(select={"BSL256"}).check_file(str(path))

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "BSL256"


def test_distinct_typo_fragments_in_one_candidate_emit_one_diagnostic(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
        lambda word: word in {"Атмена", "Варинаты"},
    )
    path = tmp_path / "Module.bsl"
    path.write_text(
        'Процедура Тест()\n    Сообщить("Атмена Варинаты");\nКонецПроцедуры\n',
        encoding="utf-8",
    )

    diagnostics = DiagnosticEngine(select={"BSL256"}).check_file(str(path))

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "BSL256"
