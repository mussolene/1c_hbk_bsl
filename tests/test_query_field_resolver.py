"""Tests for SDBL query field chain resolution (query_field_resolver)."""

from __future__ import annotations

import pytest

from onec_hbk_bsl.analysis.document_snapshot import _SDBL_LANGUAGE, _parse_sdbl_query_text
from onec_hbk_bsl.analysis.query_field_resolver import (
    QueryTypeRef,
    SymbolIndexFieldLookup,
    normalize_type_info,
    resolve_query_field_uses,
)

pytestmark = pytest.mark.skipif(_SDBL_LANGUAGE is None, reason="SDBL tree-sitter unavailable")


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
        assert set(use.resolution.candidates) == {
            "Справочник.Организации.ИНН",
            "Справочник.Контрагенты.ИНН",
        }

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


class TestSymbolIndexAdapter:
    class _FakeIndex:
        def __init__(self, members: list[dict[str, str]]) -> None:
            self._members = members

        def get_meta_members(self, object_name: str) -> list[dict[str, str]]:
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
