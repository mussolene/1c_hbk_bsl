"""BSL280 — unknown metadata object reference."""

from __future__ import annotations

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.analysis.metadata_refs import diagnostics_unknown_metadata_objects
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex


def test_bsl280_reports_missing_object() -> None:
    idx = SymbolIndex(db_path=":memory:")
    # minimal fake metadata row would need upsert_metadata — use diagnostics helper directly
    # with empty index: has_metadata false -> no issues
    content = "Справочники.НетТакогоОбъекта;"
    diags = diagnostics_unknown_metadata_objects("m.bsl", content, idx)
    assert diags == []

    from onec_hbk_bsl.indexer.metadata_parser import MetaObject

    idx.upsert_metadata(
        [
            MetaObject(name="ЕстьТакой", kind="Catalog", members=[]),
        ]
    )
    assert idx.has_metadata()
    good = "Справочники.ЕстьТакой;"
    assert diagnostics_unknown_metadata_objects("m.bsl", good, idx) == []
    bad = "Справочники.НетТакогоОбъекта;"
    diags2 = diagnostics_unknown_metadata_objects("m.bsl", bad, idx)
    assert len(diags2) == 1
    assert diags2[0].code == "BSL280"


def test_bsl280_engine_select() -> None:
    idx = SymbolIndex(db_path=":memory:")
    from onec_hbk_bsl.indexer.metadata_parser import MetaObject

    idx.upsert_metadata([MetaObject(name="A", kind="Catalog", members=[])])
    engine = DiagnosticEngine(select={"BSL280"}, symbol_index=idx)
    issues = engine.check_content("x.bsl", "Документы.Несуществует;")
    assert any(i.code == "BSL280" for i in issues)
