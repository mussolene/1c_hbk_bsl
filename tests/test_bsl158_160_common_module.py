"""BSL158–BSL160 common-module rules (metadata + XML layout)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
    common_module_has_api_region,
    common_module_name_convention_issues,
    common_module_xml_flags_invalid,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


class _FakeIndex158:
    """Minimal stand-in for SymbolIndex metadata lookup."""

    def has_metadata(self) -> bool:
        return True

    def find_meta_object(self, name: str) -> dict[str, Any] | None:
        if name == "МойОбщийМодуль":
            return {"kind": "CommonModule", "name": "МойОбщийМодуль"}
        return None


def _write_module_xml(
    base: Path,
    *,
    folder_name: str = "ТестПакет",
    server: str = "false",
    servercall: str = "false",
    coa: str = "false",
    cma: str = "false",
    ext: str = "false",
    gcm: str = "false",
    global_: str = "false",
    privileged: str = "false",
    rvr: str = "DontUse",
) -> Path:
    # Имя без «Модуль» — иначе BSL168 (CommonModuleNameWords) на любой такой модуль.
    bsl = base / "CommonModules" / folder_name / "Ext" / "Module.bsl"
    bsl.parent.mkdir(parents=True)
    bsl.write_text("Процедура П() Экспорт\nКонецПроцедуры\n", encoding="utf-8")
    xml = base / "CommonModules" / folder_name / f"{folder_name}.xml"
    xml.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.20">
  <CommonModule uuid="00000000-0000-0000-0000-000000000001">
    <Properties>
      <Name>{folder_name}</Name>
      <Global>{global_}</Global>
      <Privileged>{privileged}</Privileged>
      <Server>{server}</Server>
      <ServerCall>{servercall}</ServerCall>
      <ClientOrdinaryApplication>{coa}</ClientOrdinaryApplication>
      <ClientManagedApplication>{cma}</ClientManagedApplication>
      <ExternalConnection>{ext}</ExternalConnection>
      <GlobalClientManagedApplication>{gcm}</GlobalClientManagedApplication>
      <ReturnValuesReuse>{rvr}</ReturnValuesReuse>
    </Properties>
  </CommonModule>
</MetaDataObject>
""",
        encoding="utf-8",
    )
    return bsl


def test_bsl158_assign_to_indexed_common_module(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text("МойОбщийМодуль = 1;\n", encoding="utf-8")
    engine = DiagnosticEngine(select={"BSL158"}, symbol_index=_FakeIndex158())
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL158"]
    assert len(diags) == 1
    assert "МойОбщийМодуль" in diags[0].message


def test_bsl158_noop_without_metadata_index(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text("МойОбщийМодуль = 1;\n", encoding="utf-8")
    engine = DiagnosticEngine(select={"BSL158"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL158"]


def test_bsl159_invalid_all_flags_false(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path)
    assert common_module_xml_flags_invalid(str(bsl)) is True
    engine = DiagnosticEngine(select={"BSL159"})
    diags = [d for d in engine.check_file(str(bsl)) if d.code == "BSL159"]
    assert len(diags) == 1


def test_bsl159_valid_server(tmp_path: Path) -> None:
    # Server-side (BSLLS ``isServer``): Server + ExternalConnection + COA, no CMA
    bsl = _write_module_xml(tmp_path, server="true", ext="true", coa="true", cma="false")
    assert common_module_xml_flags_invalid(str(bsl)) is False
    engine = DiagnosticEngine(select={"BSL159"})
    assert not [d for d in engine.check_file(str(bsl)) if d.code == "BSL159"]


def test_bsl159_invalid_server_flag_only(tmp_path: Path) -> None:
    """``Server`` alone is not a valid BSLLS context (needs ExternalConnection + COA)."""
    bsl = _write_module_xml(tmp_path, server="true")
    assert common_module_xml_flags_invalid(str(bsl)) is True


def test_bsl159_valid_client(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, coa="true", cma="true")
    assert common_module_xml_flags_invalid(str(bsl)) is False


def test_bsl159_valid_server_call(tmp_path: Path) -> None:
    bsl = _write_module_xml(
        tmp_path, server="true", servercall="true", ext="false", coa="false", cma="false"
    )
    assert common_module_xml_flags_invalid(str(bsl)) is False


def test_bsl159_valid_client_server(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, server="true", ext="true", coa="true", cma="true")
    assert common_module_xml_flags_invalid(str(bsl)) is False


def test_bsl160_fires_without_api_region(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, server="true")
    bsl.write_text(
        "#Область Прочее\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL160"})
    diags = [d for d in engine.check_file(str(bsl)) if d.code == "BSL160"]
    assert len(diags) == 1


def test_bsl160_clean_with_public_and_export(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, server="true")
    bsl.write_text(
        "#Область ПрограммныйИнтерфейс\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL160"})
    assert not [d for d in engine.check_file(str(bsl)) if d.code == "BSL160"]


def test_common_module_has_api_region_names() -> None:
    assert common_module_has_api_region(["ПрограммныйИнтерфейс", "Левое"])
    assert common_module_has_api_region(["internal"])
    assert not common_module_has_api_region(["Служебные"])


@pytest.mark.parametrize(
    "body,expect",
    [
        ("Процедура П()\nКонецПроцедуры\n", True),
        (
            "#Область ПрограммныйИнтерфейс\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
            False,
        ),
    ],
)
def test_bsl160_no_export_triggers(tmp_path: Path, body: str, expect: bool) -> None:
    bsl = _write_module_xml(tmp_path, server="true")
    bsl.write_text(body, encoding="utf-8")
    engine = DiagnosticEngine(select={"BSL160"})
    diags = [d for d in engine.check_file(str(bsl)) if d.code == "BSL160"]
    assert (len(diags) >= 1) == expect


def test_bsl161_cached_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, rvr="DuringRequest")
    codes = {c for c, _ in common_module_name_convention_issues(str(bsl))}
    assert "BSL161" in codes
    engine = DiagnosticEngine(select={"BSL161"})
    assert [d for d in engine.check_file(str(bsl)) if d.code == "BSL161"]

    bsl_ok = _write_module_xml(tmp_path / "ok", folder_name="КэшПовтИсп", rvr="DuringRequest")
    assert "BSL161" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl162_client_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, coa="true", cma="true")
    assert "BSL162" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(tmp_path / "ok", folder_name="КлиентТест", coa="true", cma="true")
    assert "BSL162" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl163_client_server_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, server="true", ext="true", coa="true", cma="true")
    assert "BSL163" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(
        tmp_path / "ok",
        folder_name="КлиентСерверТест",
        server="true",
        ext="true",
        coa="true",
        cma="true",
    )
    assert "BSL163" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl164_privileged_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, privileged="true", server="true", ext="true", coa="true")
    assert "BSL164" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(
        tmp_path / "ok",
        folder_name="ПолныеПраваТест",
        privileged="true",
        server="true",
        ext="true",
        coa="true",
    )
    assert "BSL164" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl165_global_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(tmp_path, global_="true", coa="true", cma="true")
    assert "BSL165" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(
        tmp_path / "ok", folder_name="ГлобальныйТест", global_="true", coa="true", cma="true"
    )
    assert "BSL165" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl166_global_client_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(
        tmp_path, folder_name="ГлобальныйСервис", global_="true", coa="true", cma="true"
    )
    assert "BSL166" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(
        tmp_path / "ok",
        folder_name="ГлобальныйКлиентТест",
        global_="true",
        coa="true",
        cma="true",
    )
    assert "BSL166" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl167_server_call_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(
        tmp_path, server="true", servercall="true", ext="false", coa="false", cma="false"
    )
    assert "BSL167" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    bsl_ok = _write_module_xml(
        tmp_path / "ok",
        folder_name="ВызовСервераТест",
        server="true",
        servercall="true",
        ext="false",
        coa="false",
        cma="false",
    )
    assert "BSL167" not in {c for c, _ in common_module_name_convention_issues(str(bsl_ok))}


def test_bsl168_forbidden_word_in_name(tmp_path: Path) -> None:
    bsl = _write_module_xml(
        tmp_path, folder_name="ТестМодуль", server="true", ext="true", coa="true"
    )
    assert "BSL168" in {c for c, _ in common_module_name_convention_issues(str(bsl))}
    engine = DiagnosticEngine(select={"BSL168"})
    assert [d for d in engine.check_file(str(bsl)) if d.code == "BSL168"]
