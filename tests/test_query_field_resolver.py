"""Tests for SDBL query field chain resolution (query_field_resolver)."""

from __future__ import annotations

import pytest

from onec_hbk_bsl.analysis.document_snapshot import _SDBL_LANGUAGE, _parse_sdbl_query_text
from onec_hbk_bsl.analysis.query_field_resolver import (
    QueryTypeRef,
    SymbolIndexFieldLookup,
    _split_top_level,
    normalize_type_info,
    prepare_query_text,
    resolve_query_field_uses,
    resolve_query_text_uses,
)

pytestmark = [
    pytest.mark.platform,
    pytest.mark.skipif(_SDBL_LANGUAGE is None, reason="SDBL tree-sitter unavailable"),
]


class FakeLookup:
    """In-memory MetaFieldLookup: {(kind, name casefold): {field: type_info}}."""

    def __init__(self, objects: dict[tuple[str, str], dict[str, str]]) -> None:
        self._objects = {
            (kind, name.casefold()): fields for (kind, name), fields in objects.items()
        }

    def object_fields(self, kind: str, object_name: str) -> dict[str, tuple[str, str]] | None:
        fields = self._objects.get((kind, object_name.casefold()))
        if fields is None:
            return None
        return {name.casefold(): (name, raw) for name, raw in fields.items()}


LOOKUP = FakeLookup(
    {
        ("Catalog", "Организации"): {
            "ГоловнаяОрганизация": "cfg:CatalogRef.Организации",
            "ИНН": "xs:string",
        },
        ("Catalog", "Сотрудники"): {
            "ГоловнаяОрганизация": "cfg:CatalogRef.Организации",
        },
        ("Catalog", "Контрагенты"): {
            "ИНН": "xs:string",
        },
        ("Catalog", "ДоговорыКонтрагентов"): {
            "Владелец": "cfg:CatalogRef.Организации cfg:CatalogRef.Контрагенты",
        },
        ("AccumulationRegister", "УплаченныйНДФЛ"): {
            "Организация": "cfg:CatalogRef.Организации",
        },
        ("InformationRegister", "СведенияОбЭЛН"): {
            "Организация": "cfg:CatalogRef.Организации",
        },
    }
)


def _uses(query_text: str):
    tree, _has_errors = _parse_sdbl_query_text(query_text)
    assert tree is not None
    return resolve_query_field_uses(tree.root_node, LOOKUP)


def _by_text(uses, text: str):
    for use in uses:
        if ".".join(use.parts) == text:
            return use
    raise AssertionError(f"no use {text!r} among {['.'.join(u.parts) for u in uses]}")


class TestPrepareQueryText:
    def test_unescapes_bsl_doubled_quotes(self) -> None:
        assert prepare_query_text('ГДЕ Поле = ""СПВ-1""') == 'ГДЕ Поле = "СПВ-1"'
        assert prepare_query_text('ГДЕ Поле = """"') == 'ГДЕ Поле = ""'

    def test_blanks_builder_sections_preserving_lines(self) -> None:
        text = "ВЫБРАТЬ Т.Поле\nИЗ Таблица КАК Т\n{ГДЕ\nТ.Поле = 1}"
        prepared = prepare_query_text(text)
        assert prepared.splitlines()[0] == "ВЫБРАТЬ Т.Поле"
        assert prepared.count("\n") == text.count("\n")
        assert "{" not in prepared and "ГДЕ\n" not in prepared.replace("ВЫБРАТЬ", "")
        assert set(prepared.splitlines()[2]) <= {" "}

    def test_braces_inside_string_literal_are_kept(self) -> None:
        text = 'ГДЕ Поле = ""а{б}в""'
        assert prepare_query_text(text) == 'ГДЕ Поле = "а{б}в"'

    def test_prepared_builder_query_parses_clean(self) -> None:
        text = (
            "ВЫБРАТЬ\n"
            "    Орг.ГоловнаяОрганизация\n"
            "ИЗ\n"
            "    Справочник.Организации КАК Орг\n"
            "{ГДЕ\n"
            "    Орг.ГоловнаяОрганизация = &Головная}"
        )
        tree, has_errors = _parse_sdbl_query_text(prepare_query_text(text))
        assert tree is not None
        assert not has_errors
        uses = resolve_query_field_uses(tree.root_node, LOOKUP)
        use = _by_text(uses, "Орг.ГоловнаяОрганизация")
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)


class TestNormalizeTypeInfo:
    def test_catalog_ref_token(self) -> None:
        assert normalize_type_info("cfg:CatalogRef.Организации") == (
            QueryTypeRef(display="Справочник.Организации", kind="Catalog", name="Организации"),
        )

    def test_composite_with_primitives(self) -> None:
        refs = normalize_type_info("cfg:CatalogRef.Организации xs:string xs:boolean")
        assert [r.display for r in refs] == ["Справочник.Организации", "Строка", "Булево"]
        assert [r.is_ref for r in refs] == [True, False, False]

    def test_unknown_token_kept_raw(self) -> None:
        (ref,) = normalize_type_info("v8ui:Color")
        assert ref.display == "v8ui:Color"
        assert not ref.is_ref


class TestDirectAndJoinAliases:
    QUERY = """
    ВЫБРАТЬ
        Орг.ГоловнаяОрганизация,
        Орг.Наименование,
        Орг.Ссылка,
        Сотр.ГоловнаяОрганизация
    ИЗ
        Справочник.Организации КАК Орг
            ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Сотрудники КАК Сотр
            ПО Сотр.ГоловнаяОрганизация = Орг.Ссылка
    """

    def test_alias_field_resolves_to_specific_identity(self) -> None:
        use = _by_text(_uses(self.QUERY), "Орг.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)

    def test_join_alias_same_named_attribute_is_not_confused(self) -> None:
        use = _by_text(_uses(self.QUERY), "Сотр.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Сотрудники.ГоловнаяОрганизация",)

    def test_standard_field_link_is_self_ref(self) -> None:
        use = _by_text(_uses(self.QUERY), "Орг.Ссылка")
        assert use.resolution.status == "resolved"
        (hop,) = use.resolution.hops
        assert hop.types == (
            QueryTypeRef(display="Справочник.Организации", kind="Catalog", name="Организации"),
        )

    def test_standard_field_name_is_string(self) -> None:
        use = _by_text(_uses(self.QUERY), "Орг.Наименование")
        assert use.resolution.status == "resolved"
        (hop,) = use.resolution.hops
        assert hop.types == (QueryTypeRef(display="Строка"),)

    def test_table_source_names_are_not_field_uses(self) -> None:
        texts = {".".join(u.parts) for u in _uses(self.QUERY)}
        assert "Справочник.Организации" not in texts
        assert "Справочник.Сотрудники" not in texts


class TestDereferenceChain:
    QUERY = """
    ВЫБРАТЬ
        НДФЛ.Организация.ГоловнаяОрганизация КАК Голова
    ИЗ
        РегистрНакопления.УплаченныйНДФЛ КАК НДФЛ
    """

    def test_chain_records_every_hop(self) -> None:
        use = _by_text(_uses(self.QUERY), "НДФЛ.Организация.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == (
            "РегистрНакопления.УплаченныйНДФЛ.Организация",
            "Справочник.Организации.ГоловнаяОрганизация",
        )


class TestNoAliasDefault:
    QUERY = """
    ВЫБРАТЬ
        Организации.ГоловнаяОрганизация
    ИЗ
        Справочник.Организации
    """

    def test_last_name_part_is_default_alias(self) -> None:
        use = _by_text(_uses(self.QUERY), "Организации.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)


class TestVirtualTable:
    QUERY = """
    ВЫБРАТЬ
        Срез.Организация.ГоловнаяОрганизация
    ИЗ
        РегистрСведений.СведенияОбЭЛН.СрезПоследних(&Дата, Организация = &Орг) КАК Срез
    """

    def test_slice_resolves_via_base_register(self) -> None:
        use = _by_text(_uses(self.QUERY), "Срез.Организация.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == (
            "РегистрСведений.СведенияОбЭЛН.Организация",
            "Справочник.Организации.ГоловнаяОрганизация",
        )

    def test_virtual_table_suffix_field_is_conservatively_unknown(self) -> None:
        query = """
        ВЫБРАТЬ
            Остатки.КоличествоОстаток
        ИЗ
            РегистрНакопления.УплаченныйНДФЛ.Остатки() КАК Остатки
        """
        use = _by_text(_uses(query), "Остатки.КоличествоОстаток")
        assert use.resolution.status == "unknown"


class TestTempTables:
    QUERY = """
    ВЫБРАТЬ
        Орг.Ссылка КАК Организация,
        Орг.ГоловнаяОрганизация КАК Голова,
        Орг.ИНН
    ПОМЕСТИТЬ ВТОрганизации
    ИЗ
        Справочник.Организации КАК Орг
    ;
    ВЫБРАТЬ
        ВТ.Голова.ИНН,
        ВТ.ИНН
    ИЗ
        ВТОрганизации КАК ВТ
    """

    def test_chain_through_temp_table_field(self) -> None:
        use = _by_text(_uses(self.QUERY), "ВТ.Голова.ИНН")
        assert use.resolution.status == "resolved"
        # ВТ hop carries no metadata identity; the dereference does.
        assert use.resolution.identities == ("Справочник.Организации.ИНН",)

    def test_unaliased_field_keeps_source_name(self) -> None:
        use = _by_text(_uses(self.QUERY), "ВТ.ИНН")
        assert use.resolution.status == "resolved"
        (hop,) = use.resolution.hops
        assert hop.types == (QueryTypeRef(display="Строка"),)


class TestCompositeTypes:
    def test_field_on_both_targets_is_ambiguous(self) -> None:
        query = """
        ВЫБРАТЬ
            Договор.Владелец.ИНН
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(_uses(query), "Договор.Владелец.ИНН")
        assert use.resolution.status == "ambiguous"
        assert use.resolution.candidates == (
            "Справочник.Контрагенты.ИНН",
            "Справочник.Организации.ИНН",
        )

    def test_field_on_single_target_disambiguates(self) -> None:
        query = """
        ВЫБРАТЬ
            Договор.Владелец.ГоловнаяОрганизация
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(_uses(query), "Договор.Владелец.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities[-1] == "Справочник.Организации.ГоловнаяОрганизация"


class TestNestedQuerySource:
    QUERY = """
    ВЫБРАТЬ
        Вложенный.Голова.ИНН
    ИЗ
        (ВЫБРАТЬ Орг.ГоловнаяОрганизация КАК Голова
         ИЗ Справочник.Организации КАК Орг) КАК Вложенный
    """

    def test_nested_query_fields_carry_types(self) -> None:
        use = _by_text(_uses(self.QUERY), "Вложенный.Голова.ИНН")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Организации.ИНН",)


class TestCastFieldAccess:
    def test_single_field_after_cast_resolves(self) -> None:
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Владелец КАК Справочник.Организации).ГоловнаяОрганизация
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(_uses(query), "Справочник.Организации.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)

    def test_chain_after_cast_resolves_every_hop(self) -> None:
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Владелец КАК Справочник.Организации).ГоловнаяОрганизация.ИНН
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(_uses(query), "Справочник.Организации.ГоловнаяОрганизация.ИНН")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == (
            "Справочник.Организации.ГоловнаяОрганизация",
            "Справочник.Организации.ИНН",
        )

    def test_cast_narrows_composite_type_before_dereference(self) -> None:
        # Владелец сам составного типа (Организации|Контрагенты) — без ВЫРАЗИТЬ
        # разыменование "ГоловнаяОрганизация" было бы ambiguous/unknown, но
        # явный КАК снимает неоднозначность до дальнейшего обращения к полю.
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Владелец КАК Справочник.Организации).ГоловнаяОрганизация
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        uses = _uses(query)
        cast_use = _by_text(uses, "Справочник.Организации.ГоловнаяОрганизация")
        assert cast_use.resolution.status == "resolved"
        # исходное поле Владелец при этом тоже отдельно учтено как use, и
        # само по себе несёт составной тип (без сужения ВЫРАЗИТЬ дальнейшее
        # обращение к его полю дало бы ambiguous)
        raw_use = _by_text(uses, "Договор.Владелец")
        assert raw_use.resolution.status == "resolved"
        (raw_hop,) = raw_use.resolution.hops
        assert {ref.name for ref in raw_hop.types} == {"Организации", "Контрагенты"}

    def test_unresolvable_field_after_cast_is_unknown(self) -> None:
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Владелец КАК Справочник.Организации).НетТакогоПоля
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(uses := _uses(query), "Справочник.Организации.НетТакогоПоля")
        assert use.resolution.status == "unknown"
        assert use is not None and uses

    def test_cast_to_primitive_type_does_not_resolve(self) -> None:
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Номер КАК СТРОКА(20)).Поле
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        """
        use = _by_text(_uses(query), "СТРОКА(20).Поле")
        assert use.resolution.status == "unknown"

    def test_temp_table_field_type_propagates_through_cast_dereference(self) -> None:
        query = """
        ВЫБРАТЬ
            ВЫРАЗИТЬ(Договор.Владелец КАК Справочник.Организации).ГоловнаяОрганизация КАК Голова
        ПОМЕСТИТЬ ВТ
        ИЗ
            Справочник.ДоговорыКонтрагентов КАК Договор
        ;
        ВЫБРАТЬ
            ВТ.Голова.ИНН
        ИЗ
            ВТ КАК ВТ
        """
        use = _by_text(_uses(query), "ВТ.Голова.ИНН")
        assert use.resolution.status == "resolved"
        assert use.resolution.identities == ("Справочник.Организации.ИНН",)


class TestParser011Integration:
    def test_tuple_membership_fields_resolve(self) -> None:
        query = """
        ВЫБРАТЬ
            Орг.ИНН
        ИЗ
            Справочник.Организации КАК Орг
        ГДЕ
            (Орг.ИНН, Орг.ГоловнаяОрганизация) В
            (ВЫБРАТЬ Контр.ИНН, Контр.ИНН
             ИЗ Справочник.Контрагенты КАК Контр)
        """
        uses = _uses(query)
        assert _by_text(uses, "Орг.ГоловнаяОрганизация").resolution.status == "resolved"
        assert _by_text(uses, "Контр.ИНН").resolution.status == "resolved"

    def test_destroy_statement_keeps_package_field_uses(self) -> None:
        query = """
        ВЫБРАТЬ
            Орг.ИНН
        ПОМЕСТИТЬ ВТ
        ИЗ
            Справочник.Организации КАК Орг
        ;
        УНИЧТОЖИТЬ ВТ
        """
        use = _by_text(resolve_query_text_uses(query, LOOKUP), "Орг.ИНН")
        assert use.resolution.status == "resolved"

    def test_nested_joins_keep_each_alias_binding(self) -> None:
        query = """
        ВЫБРАТЬ
            Орг.ГоловнаяОрганизация
        ИЗ
            Справочник.Организации КАК Орг
                ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Сотрудники КАК Сотр
                ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Контрагенты КАК Контр
                ПО Сотр.ГоловнаяОрганизация = Контр.ИНН
                ПО Орг.ГоловнаяОрганизация = Сотр.ГоловнаяОрганизация
        """
        uses = _uses(query)
        assert _by_text(uses, "Орг.ГоловнаяОрганизация").resolution.identities == (
            "Справочник.Организации.ГоловнаяОрганизация",
        )
        assert _by_text(uses, "Сотр.ГоловнаяОрганизация").resolution.identities == (
            "Справочник.Сотрудники.ГоловнаяОрганизация",
        )
        assert _by_text(uses, "Контр.ИНН").resolution.identities == ("Справочник.Контрагенты.ИНН",)


class TestUnknowns:
    def test_unknown_alias(self) -> None:
        query = """
        ВЫБРАТЬ
            Чужой.Поле
        ИЗ
            Справочник.Организации КАК Орг
        """
        use = _by_text(_uses(query), "Чужой.Поле")
        assert use.resolution.status == "unknown"

    def test_unknown_field_keeps_resolved_prefix_hops(self) -> None:
        query = """
        ВЫБРАТЬ
            Орг.ГоловнаяОрганизация.НетТакогоПоля
        ИЗ
            Справочник.Организации КАК Орг
        """
        use = _by_text(_uses(query), "Орг.ГоловнаяОрганизация.НетТакогоПоля")
        assert use.resolution.status == "unknown"
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)

    def test_unknown_object_in_lookup(self) -> None:
        query = """
        ВЫБРАТЬ
            Т.Поле
        ИЗ
            Справочник.НеизвестныйСправочник КАК Т
        """
        use = _by_text(_uses(query), "Т.Поле")
        assert use.resolution.status == "unknown"


class TestResolveQueryTextUses:
    def test_clean_text_resolves_without_fallback(self) -> None:
        text = """
        ВЫБРАТЬ
            Орг.ГоловнаяОрганизация
        ИЗ
            Справочник.Организации КАК Орг
        """
        uses = resolve_query_text_uses(text, LOOKUP)
        use = _by_text(uses, "Орг.ГоловнаяОрганизация")
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)
        assert use.row_offset == 0

    def test_broken_package_part_does_not_block_others(self) -> None:
        # Вторая часть пакета намеренно не разбирается текущей грамматикой
        # (ВЫРАЗИТЬ с разыменованием); первая и третья должны разрешиться,
        # включая протяжку ВТ из первой в третью.
        text = (
            "ВЫБРАТЬ\n"
            "    Орг.ГоловнаяОрганизация КАК Голова\n"
            "ПОМЕСТИТЬ ВТОрг\n"
            "ИЗ\n"
            "    Справочник.Организации КАК Орг\n"
            ";\n"
            "ВЫБРАТЬ\n"
            "    ВЫРАЗИТЬ(Т.Поле КАК Справочник.Организации).ИНН\n"
            "ИЗ\n"
            "    Справочник.Организации КАК Т\n"
            ";\n"
            "ВЫБРАТЬ\n"
            "    ВТ.Голова.ИНН\n"
            "ИЗ\n"
            "    ВТОрг КАК ВТ\n"
        )
        uses = resolve_query_text_uses(text, LOOKUP)
        first = _by_text(uses, "Орг.ГоловнаяОрганизация")
        assert first.row_offset == 0
        third = _by_text(uses, "ВТ.Голова.ИНН")
        assert third.resolution.status == "resolved"
        assert third.resolution.identities == ("Справочник.Организации.ИНН",)
        # абсолютная строка ВТ.Голова.ИНН в исходном тексте — 12 (0-based)
        assert third.row_offset + third.node.start_point[0] == 12

    def test_union_sections_recovered_separately(self) -> None:
        text = (
            "ВЫБРАТЬ\n"
            "    ВЫРАЗИТЬ(А.Поле КАК Справочник.Организации).ИНН\n"
            "ИЗ\n"
            "    Справочник.Организации КАК А\n"
            "ОБЪЕДИНИТЬ ВСЕ\n"
            "ВЫБРАТЬ\n"
            "    Орг.ГоловнаяОрганизация\n"
            "ИЗ\n"
            "    Справочник.Организации КАК Орг\n"
        )
        uses = resolve_query_text_uses(text, LOOKUP)
        use = _by_text(uses, "Орг.ГоловнаяОрганизация")
        assert use.resolution.identities == ("Справочник.Организации.ГоловнаяОрганизация",)
        assert use.row_offset + use.node.start_point[0] == 6

    def test_semicolon_inside_string_literal_is_not_a_separator(self) -> None:
        text = (
            'ВЫБРАТЬ\n    ""а;б"" КАК Константа,\n    Орг.ГоловнаяОрганизация\n'
            "ИЗ\n    Справочник.Организации КАК Орг"
        )
        uses = resolve_query_text_uses(text, LOOKUP)
        use = _by_text(uses, "Орг.ГоловнаяОрганизация")
        assert use.resolution.status == "resolved"


class TestSymbolIndexAdapter:
    class _FakeIndex:
        def __init__(self, members: list[dict[str, str]]) -> None:
            self._members = members
            self.requested_kind: str | None = None

        def get_meta_members(
            self, object_name: str, *, object_kind: str | None = None
        ) -> list[dict[str, str]]:
            self.requested_kind = object_kind
            return self._members

    def test_kind_mismatch_is_unknown(self) -> None:
        index = self._FakeIndex(
            [
                {
                    "name": "ГоловнаяОрганизация",
                    "kind": "attribute",
                    "type_info": "cfg:CatalogRef.Организации",
                    "object_kind": "Document",
                }
            ]
        )
        assert SymbolIndexFieldLookup(index).object_fields("Catalog", "Организации") is None
        assert index.requested_kind == "Catalog"

    def test_only_attributes_become_fields(self) -> None:
        index = self._FakeIndex(
            [
                {
                    "name": "ГоловнаяОрганизация",
                    "kind": "attribute",
                    "type_info": "cfg:CatalogRef.Организации",
                    "object_kind": "Catalog",
                },
                {
                    "name": "КонтактнаяИнформация",
                    "kind": "tabular_section",
                    "type_info": "",
                    "object_kind": "Catalog",
                },
            ]
        )
        fields = SymbolIndexFieldLookup(index).object_fields("Catalog", "Организации")
        assert fields is not None
        assert set(fields) == {"головнаяорганизация"}


class TestTopLevelSplit:
    def test_semicolons_inside_strings_and_parentheses_are_not_separators(self) -> None:
        text = 'ВЫБРАТЬ "а;""б", Функция(1; 2);\nВЫБРАТЬ 2'

        assert _split_top_level(text, by_union=False) == [
            (0, 'ВЫБРАТЬ "а;""б", Функция(1; 2)'),
            (0, "\nВЫБРАТЬ 2"),
        ]

    def test_union_split_preserves_row_offsets_and_ignores_nested_union(self) -> None:
        text = "ВЫБРАТЬ Функция(UNION)\nОБЪЕДИНИТЬ ВСЕ\nВЫБРАТЬ 2\nUNION\nSELECT 3"

        assert _split_top_level(text, by_union=True) == [
            (0, "ВЫБРАТЬ Функция(UNION)\n"),
            (1, "\nВЫБРАТЬ 2\n"),
            (3, "\nSELECT 3"),
        ]
