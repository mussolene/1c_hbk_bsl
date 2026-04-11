"""BSL152 CachedPublic — BSLLS-style common module + Public / ПрограммныйИнтерфейс region."""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
    common_module_bslls_cached_reuse,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def _write_cached_module(
    root: Path,
    *,
    reuse: str,
    region_name: str,
    include_proc: bool,
    use_russian_folders: bool = False,
) -> Path:
    cm = "ОбщиеМодули" if use_russian_folders else "CommonModules"
    base = root / cm / "ТестПовтИсп"
    ext = base / "Ext"
    ext.mkdir(parents=True)
    bsl = ext / "Module.bsl"
    proc_block = "\nПроцедура Публичная() Экспорт\nКонецПроцедуры\n" if include_proc else ""
    bsl.write_text(
        f"#Область {region_name}\n{proc_block}#КонецОбласти\n",
        encoding="utf-8",
    )
    xml = base / "ТестПовтИсп.xml"
    xml.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.20">
  <CommonModule uuid="00000000-0000-0000-0000-000000000001">
    <Properties>
      <Name>ТестПовтИсп</Name>
      <ReturnValuesReuse>{reuse}</ReturnValuesReuse>
    </Properties>
  </CommonModule>
</MetaDataObject>
""",
        encoding="utf-8",
    )
    return bsl


def test_bsl152_fires_on_public_region_with_duringsession(tmp_path: Path) -> None:
    bsl = _write_cached_module(
        tmp_path, reuse="DuringSession", region_name="ПрограммныйИнтерфейс", include_proc=True
    )
    assert common_module_bslls_cached_reuse(str(bsl)) is True
    engine = DiagnosticEngine(select={"BSL152"})
    diags = [d for d in engine.check_file(str(bsl)) if d.code == "BSL152"]
    assert len(diags) == 1
    assert diags[0].line == 1
    opener = bsl.read_text(encoding="utf-8").splitlines()[0]
    name_i = opener.index("ПрограммныйИнтерфейс")
    assert diags[0].character <= name_i < diags[0].end_character


def test_bsl152_fires_for_region_public_english(tmp_path: Path) -> None:
    bsl = _write_cached_module(
        tmp_path, reuse="DuringRequest", region_name="Public", include_proc=True
    )
    engine = DiagnosticEngine(select={"BSL152"})
    diags = [d for d in engine.check_file(str(bsl)) if d.code == "BSL152"]
    assert len(diags) == 1


def test_bsl152_noop_dontuse(tmp_path: Path) -> None:
    bsl = _write_cached_module(
        tmp_path, reuse="DontUse", region_name="ПрограммныйИнтерфейс", include_proc=True
    )
    assert common_module_bslls_cached_reuse(str(bsl)) is False
    engine = DiagnosticEngine(select={"BSL152"})
    assert not [d for d in engine.check_file(str(bsl)) if d.code == "BSL152"]


def test_bsl152_noop_empty_public_region(tmp_path: Path) -> None:
    bsl = _write_cached_module(
        tmp_path, reuse="DuringSession", region_name="Public", include_proc=False
    )
    engine = DiagnosticEngine(select={"BSL152"})
    assert not [d for d in engine.check_file(str(bsl)) if d.code == "BSL152"]


def test_bsl152_russian_commonmodules_folder(tmp_path: Path) -> None:
    bsl = _write_cached_module(
        tmp_path,
        reuse="DuringSession",
        region_name="ПрограммныйИнтерфейс",
        include_proc=True,
        use_russian_folders=True,
    )
    assert common_module_bslls_cached_reuse(str(bsl)) is True
    engine = DiagnosticEngine(select={"BSL152"})
    assert len([d for d in engine.check_file(str(bsl)) if d.code == "BSL152"]) == 1


def test_bsl152_noop_standalone_bsl(tmp_path: Path) -> None:
    p = tmp_path / "foo.bsl"
    p.write_text(
        "#Область ПрограммныйИнтерфейс\nПроцедура А() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL152"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL152"]
