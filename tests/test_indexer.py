"""
Tests for SymbolIndex and IncrementalIndexer.

Covers:
  - upsert_file stores and retrieves symbols
  - find_symbol exact and fuzzy search
  - find_callers returns call sites
  - remove_file removes all data for a file
  - get_stats returns accurate counts
  - save_commit / get_last_commit round-trip
"""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.indexer.metadata_parser import (
    MetaMember,
    MetaObject,
    build_metadata_configuration_snapshot,
    crawl_config,
)
from onec_hbk_bsl.indexer.symbol_index import INDEX_POLICY_VERSION, SymbolIndex

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_FILE = "/workspace/orders.bsl"
SAMPLE_SYMBOLS = [
    {
        "name": "ОбработатьЗаказ",
        "line": 10,
        "character": 0,
        "end_line": 40,
        "end_character": 0,
        "kind": "procedure",
        "is_export": True,
        "container": None,
        "signature": "Procedure ОбработатьЗаказ(Заказ) Export",
        "doc_comment": "Обрабатывает входящий заказ.",
    },
    {
        "name": "ВалидироватьСтроки",
        "line": 42,
        "character": 0,
        "end_line": 70,
        "end_character": 0,
        "kind": "function",
        "is_export": False,
        "container": None,
        "signature": "Function ВалидироватьСтроки(Строки)",
        "doc_comment": "",
    },
    {
        "name": "Статус",
        "line": 5,
        "character": 4,
        "end_line": 5,
        "end_character": 10,
        "kind": "variable",
        "is_export": False,
        "container": None,
        "signature": "Var Статус",
        "doc_comment": "",
    },
]

SAMPLE_CALLS = [
    {
        "caller_line": 25,
        "caller_character": 12,
        "caller_name": "ОбработатьЗаказ",
        "callee_name": "ВалидироватьСтроки",
        "callee_args_count": 1,
    },
    {
        "caller_line": 30,
        "caller_character": 8,
        "caller_name": "ОбработатьЗаказ",
        "callee_name": "ЗаписатьЛог",
        "callee_args_count": 2,
    },
]


# ---------------------------------------------------------------------------
# Upsert and retrieval
# ---------------------------------------------------------------------------


class TestBulkWrite:
    """bulk_write drops FTS triggers during load and rebuilds — fuzzy search must still work."""

    def test_bulk_write_then_fuzzy_find(self, tmp_path: Path) -> None:
        db = tmp_path / "bulk.sqlite"
        idx = SymbolIndex(str(db))
        with idx.bulk_write():
            idx.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)
        results = idx.find_symbol("Обраб", fuzzy=True, limit=10)
        assert len(results) >= 1
        names = {r["name"] for r in results}
        assert "ОбработатьЗаказ" in names


class TestUpsertAndFind:
    def test_upsert_and_find_exact(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        results = symbol_index.find_symbol("ОбработатьЗаказ")
        assert len(results) == 1
        sym = results[0]
        assert sym["name"] == "ОбработатьЗаказ"
        assert sym["file_path"] == SAMPLE_FILE
        assert sym["line"] == 10
        assert bool(sym["is_export"]) is True

    def test_upsert_and_find_case_insensitive(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        # lower-cased query
        results = symbol_index.find_symbol("обработатьзаказ")
        assert len(results) == 1

    def test_find_symbol_with_file_filter(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)
        symbol_index.upsert_file(
            "/workspace/other.bsl",
            [
                {
                    "name": "ОбработатьЗаказ",
                    "line": 1,
                    "character": 0,
                    "end_line": 10,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "container": None,
                    "signature": "Procedure ОбработатьЗаказ()",
                    "doc_comment": "",
                }
            ],
            [],
        )

        # filter by filename
        results = symbol_index.find_symbol("ОбработатьЗаказ", file_filter="orders")
        assert all("orders" in r["file_path"] for r in results)

    def test_find_symbol_not_found(self, symbol_index: SymbolIndex) -> None:
        results = symbol_index.find_symbol("НесуществующийСимвол")
        assert results == []

    def test_find_symbol_candidates_are_stable_and_report_total(
        self, symbol_index: SymbolIndex
    ) -> None:
        for index in range(22):
            file_path = f"/workspace/module_{21 - index:02d}.bsl"
            symbol_index.upsert_file(
                file_path,
                [
                    {
                        "name": "ОдинаковыйОбработчик",
                        "line": index + 1,
                        "character": 0,
                        "end_line": index + 2,
                        "end_character": 0,
                        "kind": "procedure",
                        "is_export": False,
                        "container": None,
                        "signature": "Procedure ОдинаковыйОбработчик()",
                        "doc_comment": "",
                    }
                ],
                [],
            )

        candidates, total = symbol_index.find_symbol_candidates(
            "одинаковыйобработчик",
            limit=20,
        )

        assert total == 22
        assert len(candidates) == 20
        assert [row["file_path"] for row in candidates] == [
            f"/workspace/module_{index:02d}.bsl" for index in range(20)
        ]
        assert all("candidate_count" not in row for row in candidates)

    def test_get_file_symbols_returns_all(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        all_syms = symbol_index.get_file_symbols(SAMPLE_FILE)
        assert len(all_syms) == len(SAMPLE_SYMBOLS)
        # Should be sorted by line
        lines = [s["line"] for s in all_syms]
        assert lines == sorted(lines)


# ---------------------------------------------------------------------------
# Call graph queries
# ---------------------------------------------------------------------------


class TestFindCallers:
    def test_find_callers_returns_sites(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        callers = symbol_index.find_callers("ВалидироватьСтроки")
        assert len(callers) >= 1
        caller = callers[0]
        assert caller["callee_name"] == "ВалидироватьСтроки"
        assert caller["caller_name"] == "ОбработатьЗаказ"
        assert caller["caller_character"] == 12

    def test_find_callers_no_results(self, symbol_index: SymbolIndex) -> None:
        callers = symbol_index.find_callers("НесуществующаяФункция")
        assert callers == []

    def test_find_callees_by_file(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        callees = symbol_index.find_callees(SAMPLE_FILE)
        callee_names = {c["callee_name"] for c in callees}
        assert "ВалидироватьСтроки" in callee_names
        assert "ЗаписатьЛог" in callee_names


# ---------------------------------------------------------------------------
# Remove file
# ---------------------------------------------------------------------------


class TestRemoveFile:
    def test_remove_file_clears_symbols(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)
        assert len(symbol_index.get_file_symbols(SAMPLE_FILE)) > 0

        symbol_index.remove_file(SAMPLE_FILE)
        assert symbol_index.get_file_symbols(SAMPLE_FILE) == []
        assert symbol_index.find_callers("ВалидироватьСтроки") == []

    def test_remove_nonexistent_file_is_noop(self, symbol_index: SymbolIndex) -> None:
        """Removing a file that was never indexed should not raise."""
        symbol_index.remove_file("/no/such/file.bsl")  # Should not raise


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------


class TestGitState:
    def test_get_last_commit_none_initially(self, symbol_index: SymbolIndex) -> None:
        assert symbol_index.get_last_commit() is None

    def test_save_and_get_commit(self, symbol_index: SymbolIndex) -> None:
        commit_hash = "abc123def456"
        symbol_index.save_commit(commit_hash, workspace_root="/workspace")
        assert symbol_index.get_last_commit() == commit_hash
        assert symbol_index.get_last_index_policy_version() == INDEX_POLICY_VERSION

    def test_save_commit_updates_existing(self, symbol_index: SymbolIndex) -> None:
        symbol_index.save_commit("old_hash")
        symbol_index.save_commit("new_hash")
        assert symbol_index.get_last_commit() == "new_hash"

    def test_save_commit_preserves_explicit_legacy_policy(self, symbol_index: SymbolIndex) -> None:
        symbol_index.save_commit("old_hash", index_policy_version=1)
        assert symbol_index.get_last_index_policy_version() == 1


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_stats_after_upsert(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        stats = symbol_index.get_stats()
        assert stats["symbol_count"] == len(SAMPLE_SYMBOLS)
        assert stats["file_count"] == 1
        assert stats["call_count"] == len(SAMPLE_CALLS)

    def test_stats_include_index_size_bytes(self, tmp_path: Path) -> None:
        db = tmp_path / "stats.sqlite"
        idx = SymbolIndex(str(db))
        idx.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        stats = idx.get_stats()
        assert stats["index_size_bytes"] >= stats["db_size_bytes"] >= 0
        assert stats["index_size_bytes"] == (
            stats["db_size_bytes"] + stats["wal_size_bytes"] + stats["shm_size_bytes"]
        )
        assert stats["index_size_bytes"] > 0

    def test_stats_empty_index(self, symbol_index: SymbolIndex) -> None:
        stats = symbol_index.get_stats()
        assert stats["symbol_count"] == 0
        assert stats["file_count"] == 0
        assert stats["index_size_bytes"] == 0


class TestCorruptDatabaseRecovery:
    def test_constructor_recreates_invalid_database_file(self, tmp_path: Path) -> None:
        db = tmp_path / "invalid.sqlite"
        db.write_text("not a sqlite database", encoding="utf-8")

        idx = SymbolIndex(str(db))

        assert idx.find_symbol("ЛюбойСимвол") == []
        assert idx.has_metadata() is False
        stats = idx.get_stats()
        assert stats["symbol_count"] == 0
        assert stats["call_count"] == 0
        assert list(tmp_path.glob("*.corrupt.*")) == []

    def test_reads_recover_when_database_becomes_invalid(self, tmp_path: Path) -> None:
        db = tmp_path / "invalid-later.sqlite"
        idx = SymbolIndex(str(db))
        idx.close()
        db.write_text("not a sqlite database", encoding="utf-8")

        assert idx.find_symbol("ЛюбойСимвол") == []
        assert idx.has_metadata() is False
        stats = idx.get_stats()
        assert stats["symbol_count"] == 0
        assert stats["meta_object_count"] == 0
        assert list(tmp_path.glob("*.corrupt.*")) == []


class TestMetadataMembers:
    def test_get_meta_members_returns_more_than_legacy_page_limit(
        self, symbol_index: SymbolIndex
    ) -> None:
        members = [
            MetaMember(
                name=f"Реквизит{i:03d}",
                kind="attribute",
                parent_name="Контрагенты",
                parent_kind="Catalog",
            )
            for i in range(205)
        ]
        symbol_index.upsert_metadata(
            [MetaObject(name="Контрагенты", kind="Catalog", members=members)]
        )

        result = symbol_index.get_meta_members("Контрагенты")

        assert len(result) == 205
        assert result[0]["name"] == "Реквизит000"
        assert result[-1]["name"] == "Реквизит204"


class TestMetadataConfigurationSnapshot:
    def test_legacy_type_wrapper_remains_supported(self) -> None:
        import xml.etree.ElementTree as ET

        from onec_hbk_bsl.indexer.metadata_parser import _extract_type_info

        attribute = ET.fromstring(  # noqa: S314 - trusted synthetic fixture
            """\
<Attribute>
  <Properties>
    <Type>
      <TypeDescription><Types><Type>String</Type></Types></TypeDescription>
    </Type>
  </Properties>
</Attribute>
"""
        )

        assert _extract_type_info(attribute) == "String"

    def test_form_attribute_type_info_is_not_truncated(self) -> None:
        import xml.etree.ElementTree as ET

        from onec_hbk_bsl.indexer.metadata_parser import _extract_form_attribute_type_info

        expected = " ".join(f"cfg:CatalogRef.Объект{index:02d}" for index in range(8))
        values = "".join(f"<Type>cfg:CatalogRef.Объект{index:02d}</Type>" for index in range(8))
        attribute = ET.fromstring(  # noqa: S314 - trusted synthetic fixture
            f"<Attribute><Type>{values}</Type></Attribute>"
        )

        assert len(expected) > 120
        assert _extract_form_attribute_type_info(attribute) == expected

    def test_structured_snapshot_projects_to_legacy_metadata_members(self, tmp_path: Path) -> None:
        root = tmp_path
        (root / "Configuration.xml").write_text(
            """\
<MetaDataObject>
  <Configuration>
    <Properties>
      <Name>ТестоваяКонфигурация</Name>
      <UUID>cfg-uuid</UUID>
    </Properties>
  </Configuration>
</MetaDataObject>
""",
            encoding="utf-8",
        )
        catalogs = root / "Catalogs"
        catalogs.mkdir()
        # Composite type with enough reference targets to push the joined
        # type_info string past 120 chars, to prove long values aren't truncated.
        wide_composite_targets = [
            "Организации",
            "Контрагенты",
            "ДоговорыКонтрагентов",
            "ФизическиеЛица",
            "СтруктурныеПодразделения",
            "Пользователи",
        ]
        wide_composite_xml = "".join(
            f"<v8:Type>cfg:CatalogRef.{name}</v8:Type>" for name in wide_composite_targets
        )
        expected_wide_composite = " ".join(
            f"cfg:CatalogRef.{name}" for name in wide_composite_targets
        )
        assert len(expected_wide_composite) > 120

        (catalogs / "Контрагенты.xml").write_text(
            f"""\
<MetaDataObject xmlns:v8="http://v8.1c.ru/8.3/MDClasses">
  <Catalog uuid="catalog-uuid">
    <Properties>
      <Name>Контрагенты</Name>
      <Synonym><item><lang>ru</lang><content>Контрагенты</content></item></Synonym>
    </Properties>
    <ChildObjects>
      <Attribute>
        <Properties>
          <Name>ИНН</Name>
          <Type>
            <v8:Type>xs:string</v8:Type>
            <v8:StringQualifiers><v8:Length>12</v8:Length></v8:StringQualifiers>
          </Type>
        </Properties>
      </Attribute>
      <Attribute>
        <Properties>
          <Name>Ответственный</Name>
          <Type>{wide_composite_xml}</Type>
        </Properties>
      </Attribute>
      <TabularSection>
        <Properties><Name>Контакты</Name></Properties>
        <ChildObjects>
          <Attribute>
            <Properties>
              <Name>Телефон</Name>
              <Type>
                <v8:Type>cfg:CatalogRef.Контрагенты</v8:Type>
                <v8:Type>cfg:CatalogRef.Организации</v8:Type>
              </Type>
            </Properties>
          </Attribute>
        </ChildObjects>
      </TabularSection>
    </ChildObjects>
  </Catalog>
</MetaDataObject>
""",
            encoding="utf-8",
        )
        form_dir = catalogs / "Контрагенты" / "Forms" / "ФормаЭлемента" / "Ext"
        form_dir.mkdir(parents=True)
        (form_dir / "Form.xml").write_text(
            """\
<Form uuid="form-uuid" kind="ObjectForm">
  <Attributes>
    <Attribute name="Объект"><Type>CatalogObject.Контрагенты</Type></Attribute>
  </Attributes>
  <Commands>
    <Command name="Записать" handler="Записать"/>
  </Commands>
  <Events>
    <Event name="ПриОткрытии">ПриОткрытии</Event>
  </Events>
</Form>
""",
            encoding="utf-8",
        )

        snapshot = build_metadata_configuration_snapshot(root)

        assert snapshot.name == "ТестоваяКонфигурация"
        assert snapshot.uuid == "cfg-uuid"
        assert len(snapshot.objects) == 1
        catalog = snapshot.objects[0]
        assert catalog.name == "Контрагенты"
        assert catalog.type == "Catalog"
        assert catalog.uuid == "catalog-uuid"
        assert [attr.name for attr in catalog.attributes] == ["ИНН", "Ответственный"]
        assert catalog.attributes[0].type_info == "xs:string"
        # Wide composite type_info must not be cut mid-token at 120 chars.
        assert catalog.attributes[1].type_info == expected_wide_composite
        assert len(catalog.attributes[1].type_info) > 120
        assert [table.name for table in catalog.table_parts] == ["Контакты"]
        assert [attr.name for attr in catalog.table_parts[0].attributes] == ["Телефон"]
        assert (
            catalog.table_parts[0].attributes[0].type_info
            == "cfg:CatalogRef.Контрагенты cfg:CatalogRef.Организации"
        )
        assert [form.name for form in catalog.forms] == ["ФормаЭлемента"]
        assert [attr.name for attr in catalog.forms[0].attributes] == ["Объект"]
        assert [command.name for command in catalog.forms[0].commands] == ["Записать"]
        assert [event.name for event in catalog.forms[0].events] == ["ПриОткрытии"]

        legacy = crawl_config(root)
        assert [(member.name, member.kind) for member in legacy[0].members] == [
            ("ИНН", "attribute"),
            ("Ответственный", "attribute"),
            ("Контакты", "tabular_section"),
            ("Контакты.Телефон", "ts_attribute"),
            ("Объект", "form_attribute"),
            ("Записать", "form_command"),
        ]
        responsible = next(m for m in legacy[0].members if m.name == "Ответственный")
        assert responsible.type_info == expected_wide_composite
        assert len(responsible.type_info) > 120


class TestSqliteProfile:
    def test_symbol_index_uses_interactive_profile_by_default(self, tmp_path: Path) -> None:
        db = tmp_path / "interactive.sqlite"
        idx = SymbolIndex(str(db))
        profile = idx._sqlite_profile
        assert profile["mode"] == "interactive"
        assert profile["cache_size"] == -32768
        assert profile["mmap_size"] == 268435456
        assert profile["busy_timeout_ms"] == 10000
        assert profile["temp_store"] == "MEMORY"

    def test_symbol_index_uses_batch_profile_when_requested(self, tmp_path: Path) -> None:
        db = tmp_path / "batch.sqlite"
        idx = SymbolIndex(str(db), mode="batch")
        profile = idx._sqlite_profile
        assert profile["mode"] == "batch"
        assert profile["cache_size"] == -131072
        assert profile["mmap_size"] == 1073741824

    def test_symbol_index_profile_env_overrides(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("BSL_SQLITE_CACHE_SIZE", "-8192")
        monkeypatch.setenv("BSL_SQLITE_MMAP_SIZE", "134217728")
        monkeypatch.setenv("BSL_SQLITE_BUSY_TIMEOUT_MS", "3000")
        monkeypatch.setenv("BSL_SQLITE_TEMP_STORE", "FILE")
        db = tmp_path / "override.sqlite"
        idx = SymbolIndex(str(db), mode="interactive")
        profile = idx._sqlite_profile
        assert profile["cache_size"] == -8192
        assert profile["mmap_size"] == 134217728
        assert profile["busy_timeout_ms"] == 3000
        assert profile["temp_store"] == "FILE"


# ---------------------------------------------------------------------------
# IncrementalIndexer
# ---------------------------------------------------------------------------


class TestIncrementalIndexer:
    def test_index_file_populates_index(
        self, symbol_index: SymbolIndex, sample_bsl_path: str
    ) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file(sample_bsl_path)

        assert "error" not in result
        assert result["symbols"] > 0

        stats = symbol_index.get_stats()
        assert stats["symbol_count"] > 0

    def test_index_file_missing_path(self, symbol_index: SymbolIndex) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file("/no/such/file.bsl")

        assert "error" in result

    def test_index_snapshot_populates_index_without_reading_file(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        path = tmp_path / "open.bsl"
        content = "Процедура ИзПамяти() Экспорт\nКонецПроцедуры\n"
        snapshot = build_document_snapshot(path=str(path), content=content)
        indexer = IncrementalIndexer(index=symbol_index)

        result = indexer.index_snapshot(str(path), snapshot)

        assert "error" not in result
        assert result["symbols"] == 1
        symbols = symbol_index.get_file_symbols(str(path))
        assert [symbol["name"] for symbol in symbols] == ["ИзПамяти"]


# ---------------------------------------------------------------------------
# IncrementalIndexer extended tests
# ---------------------------------------------------------------------------


class TestIncrementalIndexerExtended:
    def test_find_all_bsl_files_finds_bsl(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        src = tmp_path / "src"
        src.mkdir()
        (src / "mod1.bsl").write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")
        (src / "mod2.bsl").write_text("Функция Ф()\nКонецФункции\n", encoding="utf-8")
        (src / "notes.txt").write_text("not bsl", encoding="utf-8")

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert any("mod1.bsl" in f for f in files)
        assert any("mod2.bsl" in f for f in files)
        assert not any("notes.txt" in f for f in files)

    def test_find_all_bsl_files_includes_os_extension(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        (tmp_path / "script.os").write_text("", encoding="utf-8")
        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))
        assert any("script.os" in f for f in files)

    def test_find_all_bsl_files_skips_tooling_dirs(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        src = tmp_path / "src"
        src.mkdir()
        (src / "real.bsl").write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        for dirname in (".agent", ".venv", "build", "dist", "node_modules"):
            ignored = tmp_path / dirname
            ignored.mkdir()
            (ignored / "ignored.bsl").write_text(
                "Процедура Служебная()\nКонецПроцедуры\n",
                encoding="utf-8",
            )

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert any("real.bsl" in f for f in files)
        assert not any("ignored.bsl" in f for f in files)

    def test_metadata_discovery_skips_tooling_dirs(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.metadata_parser import find_config_root

        ignored = tmp_path / ".agent" / "tmp" / "export"
        ignored.mkdir(parents=True)
        (ignored / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        real = tmp_path / "config"
        real.mkdir()
        (real / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        assert find_config_root(tmp_path) == real

    def test_metadata_input_xmls_include_objects_and_forms(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.metadata_parser import iter_metadata_input_xmls

        config = tmp_path / "config"
        catalog_dir = config / "Catalogs"
        form_ext = catalog_dir / "Контрагенты" / "Forms" / "ФормаЭлемента" / "Ext"
        form_ext.mkdir(parents=True)
        (config / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (catalog_dir / "Контрагенты.xml").write_text("<Catalog/>", encoding="utf-8")
        (form_ext / "Form.xml").write_text("<Form/>", encoding="utf-8")

        files = [path.relative_to(config).as_posix() for path in iter_metadata_input_xmls(config)]

        assert files == [
            "Configuration.xml",
            "Catalogs/Контрагенты.xml",
            "Catalogs/Контрагенты/Forms/ФормаЭлемента/Ext/Form.xml",
        ]

    def test_metadata_indexing_skips_unchanged_fingerprint(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.indexer import incremental
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
        from onec_hbk_bsl.indexer.metadata_parser import MetaMember, MetaObject

        config = tmp_path / "config"
        catalog_dir = config / "Catalogs"
        catalog_dir.mkdir(parents=True)
        (config / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (catalog_dir / "Контрагенты.xml").write_text("<Catalog/>", encoding="utf-8")

        calls = 0

        def fake_crawl_config(config_root: str) -> list[MetaObject]:
            nonlocal calls
            calls += 1
            return [
                MetaObject(
                    name="Контрагенты",
                    kind="Catalog",
                    file_path=str(Path(config_root) / "Catalogs" / "Контрагенты.xml"),
                    members=[
                        MetaMember(
                            name="ИНН",
                            kind="attribute",
                            parent_name="Контрагенты",
                            parent_kind="Catalog",
                        )
                    ],
                )
            ]

        monkeypatch.setattr(incremental, "crawl_config", fake_crawl_config)
        indexer = IncrementalIndexer(index=symbol_index, quiet=True)

        cold = indexer.index_metadata(str(tmp_path))
        warm = indexer.index_metadata(str(tmp_path))

        assert cold == {"objects": 1, "members": 1}
        assert warm == {
            "objects": 1,
            "members": 1,
            "skipped": True,
            "reason": "metadata_unchanged",
        }
        assert calls == 1

    def test_metadata_indexing_reindexes_when_fingerprint_changes(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.indexer import incremental
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
        from onec_hbk_bsl.indexer.metadata_parser import MetaObject

        config = tmp_path / "config"
        catalog_dir = config / "Catalogs"
        catalog_dir.mkdir(parents=True)
        (config / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_xml = catalog_dir / "Контрагенты.xml"
        obj_xml.write_text("<Catalog/>", encoding="utf-8")

        calls = 0

        def fake_crawl_config(_config_root: str) -> list[MetaObject]:
            nonlocal calls
            calls += 1
            return [MetaObject(name=f"Контрагенты{calls}", kind="Catalog")]

        monkeypatch.setattr(incremental, "crawl_config", fake_crawl_config)
        indexer = IncrementalIndexer(index=symbol_index, quiet=True)

        assert indexer.index_metadata(str(tmp_path))["objects"] == 1
        obj_xml.write_text('<Catalog changed="true"/>', encoding="utf-8")
        assert indexer.index_metadata(str(tmp_path))["objects"] == 1

        assert calls == 2

    def test_get_current_commit_non_git_dir(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        result = IncrementalIndexer._get_current_commit(str(tmp_path))
        # Non-git directory returns None
        assert result is None

    def test_get_current_commit_git_dir(self) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        # The project itself is a git repo
        project_root = str(Path(__file__).parent.parent)
        result = IncrementalIndexer._get_current_commit(project_root)
        # Should return a hex string or None (if not a git repo in CI)
        assert result is None or (isinstance(result, str) and len(result) >= 7)

    def test_get_changed_files_mocked_success(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "changed.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "changed.bsl\n"

        with patch("subprocess.run", return_value=mock_result):
            files = indexer.get_changed_files(since_commit="abc123", workspace=str(tmp_path))

        assert any("changed.bsl" in f for f in files)

    def test_get_changed_files_git_failure_fallback(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "fallback.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "not a git repository"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            files = indexer.get_changed_files(since_commit="abc123", workspace=str(tmp_path))

        # Falls back to full scan — should include our bsl file
        assert any("fallback.bsl" in f for f in files)

    def test_get_changed_files_git_not_found_fallback(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "nofallback.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            files = indexer.get_changed_files(since_commit="abc123", workspace=str(tmp_path))

        assert any("nofallback.bsl" in f for f in files)

    def test_index_workspace_force_true(
        self, symbol_index: SymbolIndex, temp_workspace: str
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "onec_hbk_bsl.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer.index_workspace(temp_workspace, force=True)

        assert result["indexed"] >= 1
        assert result["errors"] == 0

    def test_index_workspace_up_to_date_returns_early(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        fake_commit = "deadbeef1234567890"
        symbol_index.save_commit(fake_commit, workspace_root=str(tmp_path))

        indexer = IncrementalIndexer(index=symbol_index)

        with patch(
            "onec_hbk_bsl.indexer.incremental.IncrementalIndexer._get_current_commit",
            return_value=fake_commit,
        ):
            result = indexer.index_workspace(str(tmp_path), force=False)

        assert result == {"indexed": 0, "skipped": 0, "errors": 0}

    def test_index_workspace_reconciles_dirty_git_states_without_head_change(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import subprocess

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        def git(workspace: Path, *args: str) -> str:
            result = subprocess.run(
                ["git", *args],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

        def write_procedure(path: Path, name: str) -> None:
            path.write_text(
                f"Процедура {name}()\nКонецПроцедуры\n",
                encoding="utf-8",
            )

        for state in ("unstaged", "staged", "untracked", "deleted", "renamed"):
            workspace = tmp_path / state
            workspace.mkdir()
            git(workspace, "init", "-q")
            module = workspace / "module.bsl"
            write_procedure(module, "Исходная")
            git(workspace, "add", "module.bsl")
            git(
                workspace,
                "-c",
                "user.name=Indexer Test",
                "-c",
                "user.email=indexer@example.invalid",
                "commit",
                "-qm",
                "initial",
            )

            index = SymbolIndex(str(tmp_path / f"{state}.sqlite"))
            indexer = IncrementalIndexer(index=index, quiet=True)
            monkeypatch.setattr(indexer, "_start_metadata_indexing", lambda workspace: None)
            initial = indexer.index_workspace(str(workspace))
            assert initial["indexed"] == 1
            head = git(workspace, "rev-parse", "HEAD")

            if state == "unstaged":
                write_procedure(module, "ИзмененаБезStage")
            elif state == "staged":
                write_procedure(module, "ИзмененаВStage")
                git(workspace, "add", "module.bsl")
            elif state == "untracked":
                write_procedure(workspace / "untracked.bsl", "НоваяUntracked")
            elif state == "deleted":
                module.unlink()
            else:
                git(workspace, "mv", "module.bsl", "renamed.bsl")

            result = indexer.index_workspace(str(workspace))

            assert result["errors"] == 0
            assert git(workspace, "rev-parse", "HEAD") == head
            if state == "unstaged":
                assert index.find_symbol("Исходная") == []
                assert len(index.find_symbol("ИзмененаБезStage")) == 1
            elif state == "staged":
                assert index.find_symbol("Исходная") == []
                assert len(index.find_symbol("ИзмененаВStage")) == 1
            elif state == "untracked":
                assert len(index.find_symbol("Исходная")) == 1
                assert len(index.find_symbol("НоваяUntracked")) == 1
            elif state == "deleted":
                assert index.find_symbol("Исходная") == []
            else:
                renamed = workspace / "renamed.bsl"
                assert index.get_file_symbols(str(module.resolve())) == []
                assert len(index.get_file_symbols(str(renamed.resolve()))) == 1
            index.close()

    def test_clean_unchanged_worktree_does_zero_indexing_work(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import subprocess
        from unittest.mock import patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        module = workspace / "module.bsl"
        module.write_text("Процедура Исходная()\nКонецПроцедуры\n", encoding="utf-8")
        subprocess.run(["git", "add", "module.bsl"], cwd=workspace, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Indexer Test",
                "-c",
                "user.email=indexer@example.invalid",
                "commit",
                "-qm",
                "initial",
            ],
            cwd=workspace,
            check=True,
        )

        index = SymbolIndex(str(tmp_path / "clean.sqlite"))
        indexer = IncrementalIndexer(index=index, quiet=True)
        monkeypatch.setattr(indexer, "_start_metadata_indexing", lambda workspace: None)
        assert indexer.index_workspace(str(workspace))["indexed"] == 1

        with patch.object(indexer, "_index_files", wraps=indexer._index_files) as index_files:
            result = indexer.index_workspace(str(workspace))

        assert result == {"indexed": 0, "skipped": 0, "errors": 0}
        index_files.assert_not_called()
        index.close()

    def test_index_workspace_policy_change_forces_full_reconciliation(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        fake_commit = "deadbeef1234567890"
        symbol_index.save_commit(
            fake_commit,
            workspace_root=str(tmp_path),
            index_policy_version=INDEX_POLICY_VERSION - 1,
        )
        indexer = IncrementalIndexer(index=symbol_index)

        with (
            patch.object(indexer, "_get_current_commit", return_value=fake_commit),
            patch.object(indexer, "_find_all_bsl_files", return_value=[]) as find_all,
        ):
            result = indexer.index_workspace(str(tmp_path), force=False)

        find_all.assert_called_once_with(str(tmp_path.resolve()))
        assert result == {"indexed": 0, "skipped": 0, "errors": 0, "pruned": 0}
        assert symbol_index.get_last_index_policy_version() == INDEX_POLICY_VERSION

    def test_index_files_with_missing_file_increments_skipped(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        nonexistent = str(tmp_path / "gone.bsl")
        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "onec_hbk_bsl.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer._index_files([nonexistent], workspace=str(tmp_path))

        assert result["skipped"] == 1
        assert result["indexed"] == 0

    def test_index_file_with_calls_count(
        self, symbol_index: SymbolIndex, sample_bsl_path: str
    ) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file(sample_bsl_path)

        assert "error" not in result
        assert result["calls"] >= 0  # calls may be 0 for simple files

    def test_on_progress_callback_called(
        self, symbol_index: SymbolIndex, temp_workspace: str
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        progress_calls: list = []

        def on_progress(current: int, total: int, path: str) -> None:
            progress_calls.append((current, total, path))

        indexer = IncrementalIndexer(index=symbol_index, on_progress=on_progress)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "onec_hbk_bsl.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            indexer.index_workspace(temp_workspace, force=True)

        assert len(progress_calls) >= 1

    def test_index_workspace_many_files_stress(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        # Create many small modules to emulate a larger workspace.
        file_count = 120
        for i in range(file_count):
            p = tmp_path / f"mod_{i:03d}.bsl"
            p.write_text(
                f'Процедура Тест{i}()\n    Сообщить("{i}");\nКонецПроцедуры\n',
                encoding="utf-8",
            )

        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "onec_hbk_bsl.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer.index_workspace(str(tmp_path), force=True)

        assert result["errors"] == 0
        # At least all created files should be processed.
        assert result["indexed"] >= file_count
        # Spot-check that symbols are queryable after bulk indexing.
        sym = symbol_index.find_symbol("Тест42", limit=1)
        assert len(sym) == 1

    def test_metadata_indexing_single_flight_with_pending_workspace(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        import threading
        import time

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        ws1.mkdir()
        ws2.mkdir()
        indexer = IncrementalIndexer(index=symbol_index, quiet=True)

        started = threading.Event()
        release = threading.Event()
        calls: list[str] = []

        def fake_index_metadata(workspace: str) -> dict[str, int]:
            calls.append(workspace)
            if len(calls) == 1:
                started.set()
                release.wait(timeout=2.0)
            return {"objects": 0, "members": 0}

        monkeypatch.setattr(indexer, "index_metadata", fake_index_metadata)

        indexer._start_metadata_indexing(str(ws1))
        assert started.wait(timeout=2.0)
        indexer._start_metadata_indexing(str(ws2))
        with indexer._metadata_lock:
            assert indexer._metadata_running is True
            assert indexer._metadata_pending is True

        release.set()
        deadline = time.time() + 3.0
        while time.time() < deadline:
            with indexer._metadata_lock:
                if not indexer._metadata_running:
                    break
            time.sleep(0.01)

        assert calls == [str(ws1.resolve()), str(ws2.resolve())]

    def test_metadata_indexing_pending_requests_are_coalesced(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        import threading
        import time

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        ws3 = tmp_path / "ws3"
        ws1.mkdir()
        ws2.mkdir()
        ws3.mkdir()
        indexer = IncrementalIndexer(index=symbol_index, quiet=True)

        started = threading.Event()
        release = threading.Event()
        calls: list[str] = []

        def fake_index_metadata(workspace: str) -> dict[str, int]:
            calls.append(workspace)
            if len(calls) == 1:
                started.set()
                release.wait(timeout=2.0)
            return {"objects": 0, "members": 0}

        monkeypatch.setattr(indexer, "index_metadata", fake_index_metadata)

        indexer._start_metadata_indexing(str(ws1))
        assert started.wait(timeout=2.0)
        indexer._start_metadata_indexing(str(ws2))
        indexer._start_metadata_indexing(str(ws3))
        release.set()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            with indexer._metadata_lock:
                if not indexer._metadata_running:
                    break
            time.sleep(0.01)

        assert calls == [str(ws1.resolve()), str(ws3.resolve())]


class TestIndexScopeAndLifecycle:
    def test_git_discovery_includes_tracked_and_nonignored_only(self, tmp_path: Path) -> None:
        import subprocess

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        ignored = tmp_path / "ignored"
        ignored.mkdir()
        dropped = ignored / "drop.bsl"
        tracked = ignored / "tracked.bsl"
        visible = tmp_path / "visible.bsl"
        for path in (dropped, tracked, visible):
            path.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", str(tracked)], cwd=tmp_path, check=True)

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert str(visible.resolve()) in files
        assert str(tracked.resolve()) in files
        assert str(dropped.resolve()) not in files

    def test_discovery_applies_project_exclude(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        generated = tmp_path / "generated"
        generated.mkdir()
        excluded = generated / "part.bsl"
        included = tmp_path / "module.bsl"
        excluded.write_text("", encoding="utf-8")
        included.write_text("", encoding="utf-8")
        (tmp_path / "onec-hbk-bsl.toml").write_text('exclude = ["generated"]\n', encoding="utf-8")

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert str(included.resolve()) in files
        assert str(excluded.resolve()) not in files

    def test_discovery_can_index_diagnostic_excluded_files(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        library = tmp_path / "library"
        library.mkdir()
        dependency = library / "module.bsl"
        dependency.write_text("", encoding="utf-8")
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            'exclude = ["library"]\nindex-exclude = []\n', encoding="utf-8"
        )

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert str(dependency.resolve()) in files

    def test_symbols_mode_omits_call_graph(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        monkeypatch.setenv("BSL_INDEX_MODE", "symbols")
        path = tmp_path / "module.bsl"
        path.write_text("Процедура П()\n    Другая();\nКонецПроцедуры\n", encoding="utf-8")
        result = IncrementalIndexer(index=symbol_index).index_file(str(path))

        assert result["symbols"] >= 1
        assert result["calls"] == 0
        assert symbol_index.get_stats()["call_count"] == 0

    def test_off_mode_skips_persistent_writes(
        self, symbol_index: SymbolIndex, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        monkeypatch.setenv("BSL_INDEX_MODE", "off")
        path = tmp_path / "module.bsl"
        path.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        result = IncrementalIndexer(index=symbol_index).index_file(str(path))

        assert result["disabled"] is True
        assert symbol_index.get_stats()["symbol_count"] == 0

    def test_full_reindex_prunes_files_no_longer_in_scope(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        import subprocess

        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        stale = tmp_path / "ignored" / "old.bsl"
        stale.parent.mkdir()
        stale.write_text("Процедура Старая()\nКонецПроцедуры\n", encoding="utf-8")
        symbol_index.upsert_file(
            str(stale.resolve()),
            [{**SAMPLE_SYMBOLS[0], "name": "Старая"}],
            [],
        )

        result = IncrementalIndexer(index=symbol_index, quiet=True).index_workspace(
            str(tmp_path), force=True
        )

        assert result["pruned"] == 1
        assert symbol_index.find_symbol("Старая") == []

    def test_checkpoint_and_compact_reclaim_wal(self, tmp_path: Path) -> None:
        db = tmp_path / "compact.sqlite"
        idx = SymbolIndex(str(db))
        for i in range(50):
            idx.upsert_file(f"/workspace/{i}.bsl", SAMPLE_SYMBOLS, SAMPLE_CALLS)
        idx.remove_file("/workspace/1.bsl")

        checkpoint = idx.checkpoint(truncate=True)
        compact = idx.compact()

        assert checkpoint["busy"] == 0
        assert compact["after_bytes"] <= compact["before_bytes"]


# ---------------------------------------------------------------------------
# get_module_exports (Iteration 2)
# ---------------------------------------------------------------------------


class TestGetModuleExports:
    def test_get_module_exports_finds_exported(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/ОбщийМодуль.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "ЭкспортнаяФункция",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": True,
                    "signature": "ЭкспортнаяФункция()",
                    "doc_comment": None,
                },
                {
                    "name": "НеЭкспорт",
                    "line": 10,
                    "character": 0,
                    "end_line": 15,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "signature": "НеЭкспорт()",
                    "doc_comment": None,
                },
            ],
            [],
        )
        results = symbol_index.get_module_exports("ОбщийМодуль")
        names = [r["name"] for r in results]
        assert "ЭкспортнаяФункция" in names

    def test_get_module_exports_ignores_non_export(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/МодульБезЭкспорта.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "Внутренняя",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "signature": "Внутренняя()",
                    "doc_comment": None,
                }
            ],
            [],
        )
        results = symbol_index.get_module_exports("МодульБезЭкспорта")
        assert results == []

    def test_get_module_exports_case_insensitive(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/МойМодуль.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "Метод",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": True,
                    "signature": "Метод()",
                    "doc_comment": None,
                }
            ],
            [],
        )
        # lookup with different case
        results = symbol_index.get_module_exports("мойМОДУЛЬ")
        names = [r["name"] for r in results]
        assert "Метод" in names


# ---------------------------------------------------------------------------
# find_unused_symbols + find_callers_count_non_recursive (Unused detection)
# ---------------------------------------------------------------------------


class TestFindUnusedSymbols:
    _FILE = "/workspace/module.bsl"
    _CALLER_FILE = "/workspace/caller.bsl"

    def _sym(self, name: str, kind: str = "function", is_export: bool = False) -> dict:
        return {
            "name": name,
            "line": 1,
            "character": 0,
            "end_line": 5,
            "end_character": 0,
            "kind": kind,
            "is_export": is_export,
            "signature": f"{name}()",
            "doc_comment": None,
        }

    def test_unused_private_function_detected(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("НеВызывается")], [])
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert any(u["name"] == "НеВызывается" for u in unused)

    def test_used_function_not_in_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Вызывается")], [])
        symbol_index.upsert_file(
            self._CALLER_FILE,
            [self._sym("КаллерМетод")],
            [
                {
                    "caller_file": self._CALLER_FILE,
                    "caller_line": 10,
                    "caller_name": "КаллерМетод",
                    "callee_name": "Вызывается",
                    "callee_args_count": 0,
                }
            ],
        )
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert not any(u["name"] == "Вызывается" for u in unused)

    def test_export_function_not_in_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("ЭкспортМетод", is_export=True)], [])
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert not any(u["name"] == "ЭкспортМетод" for u in unused)

    def test_recursive_function_is_unused(self, symbol_index: SymbolIndex) -> None:
        """A function that only calls itself counts as unused."""
        symbol_index.upsert_file(self._FILE, [self._sym("Рекурсия")], [])
        symbol_index.upsert_file(
            self._FILE,
            [self._sym("Рекурсия")],
            [
                {
                    "caller_file": self._FILE,
                    "caller_line": 3,
                    "caller_name": "Рекурсия",
                    "callee_name": "Рекурсия",
                    "callee_args_count": 0,
                }
            ],
        )
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert any(u["name"] == "Рекурсия" for u in unused)

    def test_non_recursive_count_zero_for_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Функция1")], [])
        count = symbol_index.find_callers_count_non_recursive("Функция1")
        assert count == 0

    def test_non_recursive_count_positive_for_used(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Функция2")], [])
        symbol_index.upsert_file(
            self._CALLER_FILE,
            [self._sym("Другая")],
            [
                {
                    "caller_file": self._CALLER_FILE,
                    "caller_line": 5,
                    "caller_name": "Другая",
                    "callee_name": "Функция2",
                    "callee_args_count": 0,
                }
            ],
        )
        count = symbol_index.find_callers_count_non_recursive("Функция2")
        assert count == 1
