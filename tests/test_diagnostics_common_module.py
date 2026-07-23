"""Common-module context diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    DiagnosticEngine,
)
from tests.diagnostic_test_support import _codes

pytestmark = pytest.mark.integration


# BSL172 — TestBsl172DataExchangeLoadingParity
class TestBsl172DataExchangeLoadingParity:
    def test_requires_exchange_check_with_return(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, Замещение)
                Если Отказ Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" in _codes(diags)

    def test_exchange_check_in_if_branch_satisfies_rule(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, Замещение)
                Если ОбменДанными.Загрузка Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" not in _codes(diags)

    def test_non_supported_module_type_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, СтандартнаяОбработка)
                Если Отказ Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" not in _codes(diags)
