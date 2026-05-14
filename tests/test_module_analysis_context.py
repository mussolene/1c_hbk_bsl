from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.domain import ModuleAnalysisContext, ModuleModel
from onec_hbk_bsl.analysis.diagnostic.domain.procedure_model import ProcedureModel
from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot


def test_module_analysis_context_exposes_snapshot_views(tmp_path: Path) -> None:
    content = """\
Процедура Тест(Парам = "x") Экспорт
    Запрос.Текст = "ВЫБРАТЬ
    |Поле // query comment
    |ИЗ Справочник.Номенклатура";
    Сообщить(Парам); // trailing
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)
    context = ModuleAnalysisContext.from_snapshot(snapshot)

    assert context.path == snapshot.path
    assert context.content == content
    assert context.lines is snapshot.lines
    assert isinstance(context.module, ModuleModel)
    assert context.module is context.module

    assert len(context.procedures) == 1
    procedure = context.procedures[0]
    assert isinstance(procedure, ProcedureModel)
    assert procedure.name == "Тест"
    assert procedure.is_export
    assert procedure.optional_params == frozenset({"Парам"})
    assert context.procedures is context.procedures

    assert context.comment_starts is snapshot.comment_starts
    assert context.line_string_states is snapshot.line_string_states
    assert context.masked_lines is snapshot.masked_lines
    assert context.code_lines_without_comments is snapshot.code_lines_without_comments
    assert context.query_text_blocks is snapshot.query_text_blocks

    facts = context.line_facts
    assert facts is context.line_facts
    assert facts[0].line_no == 1
    assert facts[0].has_code
    assert facts[4].comment_start is not None
    assert facts[4].code_text.rstrip() == "    Сообщить(Парам);"
    assert not facts[4].is_comment_only
    assert context.line_fact(4) == facts[4]

    query_blocks = context.query_text_blocks_containing_line(3)
    assert len(query_blocks) == 1
    assert query_blocks[0] is snapshot.query_text_blocks[0]
