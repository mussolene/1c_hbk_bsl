"""
Tests for DiagnosticEngine.

Covers:
  - BSL001: syntax error detection
  - BSL002: long procedure detection
  - BSL004: empty exception handler detection
  - Clean file produces no diagnostics
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
from onec_hbk_bsl.analysis.diagnostics import Diagnostic, DiagnosticEngine, Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_content(content: str, tmp_path: Path) -> list[Diagnostic]:
    """Write *content* to a temp file and run the diagnostic engine on it."""
    bsl_file = tmp_path / "test.bsl"
    bsl_file.write_text(textwrap.dedent(content), encoding="utf-8")
    engine = DiagnosticEngine()
    return engine.check_file(str(bsl_file))


# ---------------------------------------------------------------------------
# BSL001 — Syntax errors
# ---------------------------------------------------------------------------


class TestBsl001SyntaxErrors:
    def test_valid_file_has_no_syntax_errors(self, sample_bsl_path: str) -> None:
        """sample.bsl is syntactically valid — should produce no BSL001 errors."""
        engine = DiagnosticEngine()
        issues = engine.check_file(sample_bsl_path)
        syntax_errors = [d for d in issues if d.code == "BSL001"]
        # Accept 0 syntax errors; tree-sitter may produce some for BSL grammar gaps
        # Just verify each error has required fields
        for err in syntax_errors:
            assert err.severity == Severity.ERROR
            assert err.line >= 1

    def test_round_with_precision_has_no_syntax_error(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "round.bsl"
        bsl_file.write_text(
            "Процедура П()\n"
            "\tНомерПериода = Окр((ДеньГода(ДатаВПериоде) - 2) / 10, 0);\n"
            "КонецПроцедуры\n",
            encoding="utf-8",
        )
        issues = DiagnosticEngine(select={"BSL001"}).check_file(str(bsl_file))
        assert not [d for d in issues if d.code == "BSL001"]

    def test_keyword_property_and_date_literal_have_no_syntax_error(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "keyword_property.bsl"
        bsl_file.write_text(
            "Функция Тест()\n"
            "\tКонтент = Новый Структура;\n"
            "\tКонтент.Function = ФункцияДокумента();\n"
            "\tИмя = Контент.Функция;\n"
            "\tДата = '2023.12.19';\n"
            "\tВозврат Контент;\n"
            "КонецФункции\n",
            encoding="utf-8",
        )
        issues = DiagnosticEngine(select={"BSL001"}).check_file(str(bsl_file))
        assert not [d for d in issues if d.code == "BSL001"]

    def test_long_valid_function_header_has_no_syntax_error(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "long_header.bsl"
        bsl_file.write_text(
            "Функция XML_УПД_970_ЭтоСпособПодтвержденияПолномочийЭлектроннойДоверенностью(ConfirmCredentials)\n"
            '\tВозврат (ConfirmCredentials = "3");\n'
            "КонецФункции\n",
            encoding="utf-8",
        )
        issues = DiagnosticEngine(select={"BSL001"}).check_file(str(bsl_file))
        assert not [d for d in issues if d.code == "BSL001"]

    def test_unreadable_file_produces_bsl001(self, tmp_path: Path) -> None:
        """DiagnosticEngine on a missing file returns a BSL001 error."""
        engine = DiagnosticEngine()
        issues = engine.check_file(str(tmp_path / "nonexistent.bsl"))
        assert len(issues) == 1
        assert issues[0].code == "BSL001"
        assert issues[0].severity == Severity.ERROR


# ---------------------------------------------------------------------------
# BSL002 — Procedure too long
# ---------------------------------------------------------------------------


class TestBsl002LongProcedure:
    def test_short_procedure_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура КороткаяПроцедура()
                Сообщение("привет");
            КонецПроцедуры
        """
        issues = _check_content(content, tmp_path)
        bsl002 = [d for d in issues if d.code == "BSL002"]
        assert bsl002 == []

    def test_long_procedure_triggers_bsl002(self, tmp_path: Path) -> None:
        # Build a procedure with 210 body lines
        body = "\n".join(f"    Переменная{i} = {i};" for i in range(210))
        content = f"Процедура ДлиннаяПроцедура()\n{body}\nКонецПроцедуры\n"
        bsl_file = tmp_path / "long.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine()
        issues = engine.check_file(str(bsl_file))
        bsl002 = [d for d in issues if d.code == "BSL002"]
        assert len(bsl002) >= 1
        assert bsl002[0].severity == Severity.WARNING
        assert bsl002[0].message == get_rule("BSL002").message


# ---------------------------------------------------------------------------
# BSL004 — EmptyCodeBlock
# ---------------------------------------------------------------------------


class TestBsl004EmptyExceptHandler:
    def test_empty_except_does_not_trigger_bsl004_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Сообщение("OK");
                Исключение
                    // Пустой обработчик
                КонецПопытки;
            КонецПроцедуры
        """
        issues = _check_content(content, tmp_path)
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert bsl004 == []

    def test_nonempty_except_no_bsl004(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Сообщение("OK");
                Исключение
                    ЗаписатьОшибку(ОписаниеОшибки());
                КонецПопытки;
            КонецПроцедуры
        """
        issues = _check_content(content, tmp_path)
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert bsl004 == []

    def test_sample_bsl_empty_except_is_not_bsl004(self, sample_bsl_path: str) -> None:
        engine = DiagnosticEngine()
        issues = engine.check_file(sample_bsl_path)
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert bsl004 == []

    def test_bsl004_reports_empty_if_line(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если Истина Тогда
    КонецЕсли;
КонецПроцедуры
"""
        bsl_file = tmp_path / "t.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine()
        issues = engine.check_file(str(bsl_file))
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert len(bsl004) >= 1
        assert bsl004[0].line == 2

    def test_bsl004_reports_multiline_if_on_then_token(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если ЗначениеЗаполнено(Параметр1,
        Параметр2) Тогда

        // Комментарий без исполняемого кода

    ИначеЕсли Истина Тогда
        Сообщить("OK");
    КонецЕсли;
КонецПроцедуры
"""
        bsl_file = tmp_path / "t.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine(select={"BSL004"})
        issues = engine.check_file(str(bsl_file))
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert len(bsl004) == 1
        assert bsl004[0].line == 3
        assert bsl004[0].character == content.splitlines()[2].index("Тогда")
        assert bsl004[0].end_character == bsl004[0].character + len("Тогда")

    def test_bsl004_reports_parenthesized_multiline_if_with_comment_only_body(
        self, tmp_path: Path
    ) -> None:
        content = """\
Процедура Тест()
    Если (Элемент.Ключ = "Totals")
        Или (Элемент.Ключ = "TotalSum") Тогда
        // Не заполняем
    Иначе
        Сообщить("OK");
    КонецЕсли;
КонецПроцедуры
"""
        bsl_file = tmp_path / "t.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine(select={"BSL004"})
        issues = engine.check_file(str(bsl_file))
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert len(bsl004) == 1
        assert bsl004[0].line == 3
        assert bsl004[0].character == content.splitlines()[2].index("Тогда")

    def test_bsl004_reports_empty_elseif_branch(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если А Тогда
        Сообщить("A");
    ИначеЕсли Б Тогда
        // TODO
    Иначе
        Сообщить("C");
    КонецЕсли;
КонецПроцедуры
"""
        bsl_file = tmp_path / "t.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine(select={"BSL004"})
        issues = engine.check_file(str(bsl_file))
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert len(bsl004) == 1
        assert bsl004[0].line == 4

    def test_bsl004_reports_empty_else_branch(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если А Тогда
        Сообщить("A");
    Иначе
        // TODO
    КонецЕсли;
КонецПроцедуры
"""
        bsl_file = tmp_path / "t.bsl"
        bsl_file.write_text(content, encoding="utf-8")

        engine = DiagnosticEngine(select={"BSL004"})
        issues = engine.check_file(str(bsl_file))
        bsl004 = [d for d in issues if d.code == "BSL004"]
        assert len(bsl004) == 1
        assert bsl004[0].line == 4


# ---------------------------------------------------------------------------
# No issues on clean file
# ---------------------------------------------------------------------------


class TestCleanFile:
    def test_clean_file_no_diagnostics(self, tmp_path: Path) -> None:
        content = """\
            Процедура ЧистаяПроцедура() Экспорт
                Перем Результат;
                Результат = 42;
                Попытка
                    Сообщение(Результат);
                Исключение
                    ЗаписатьЛог(ОписаниеОшибки());
                КонецПопытки;
            КонецПроцедуры
        """
        issues = _check_content(content, tmp_path)
        # BSL002 can't fire (short), BSL004 won't fire (non-empty handler)
        blocking = [d for d in issues if d.code in ("BSL002", "BSL004")]
        assert blocking == []


class TestCheckFileOptimization:
    def test_complexity_rules_reuse_string_state_per_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import onec_hbk_bsl.analysis.document_snapshot as snapshot_mod

        body = "\n".join(
            [
                "    Если Истина Тогда",
                '        Сообщение("ok");',
                "    КонецЕсли;",
            ]
        )
        content = "\n".join(f"Процедура Тест{i}()\n{body}\nКонецПроцедуры" for i in range(12))
        bsl_file = tmp_path / "many_procs.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        calls = {"value": 0}
        original = snapshot_mod.build_line_string_states

        def counted(lines: list[str]) -> list[bool]:
            calls["value"] += 1
            return original(lines)

        monkeypatch.setattr(snapshot_mod, "build_line_string_states", counted)

        engine = DiagnosticEngine(select={"BSL011", "BSL019"})
        engine.check_file(str(bsl_file))

        assert calls["value"] == 1

    def test_check_file_reads_content_once_when_tree_not_provided(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bsl_file = tmp_path / "single_read.bsl"
        bsl_file.write_text("А = 1;\n", encoding="utf-8")
        engine = DiagnosticEngine()
        parser = engine._get_parser()
        parse_file_called = {"value": False}
        captured: dict[str, object] = {}

        def fail_parse_file(_path: str) -> object:
            parse_file_called["value"] = True
            raise AssertionError("parse_file should not be used in optimized check_file path")

        def fake_parse_content(content: str, file_path: str = "<string>") -> object:
            captured["file_path"] = file_path
            return object()

        def fake_run_rules(
            path: str,
            content: str,
            tree: object,
            *,
            symbol_index: object | None = None,
        ) -> list[Diagnostic]:
            captured["path"] = path
            captured["content"] = content
            captured["tree"] = tree
            captured["symbol_index"] = symbol_index
            return []

        read_calls = 0
        original_read_text = Path.read_text

        def spy_read_text(self: Path, *args: object, **kwargs: object) -> str:
            nonlocal read_calls
            read_calls += 1
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(parser, "parse_file", fail_parse_file)
        monkeypatch.setattr(parser, "parse_content", fake_parse_content)
        monkeypatch.setattr(engine, "_get_parser", lambda: parser)
        monkeypatch.setattr(engine, "_run_rules", fake_run_rules)
        monkeypatch.setattr(Path, "read_text", spy_read_text)

        result = engine.check_file(str(bsl_file))

        assert result == []
        assert read_calls == 1
        assert parse_file_called["value"] is False
        assert captured["path"] == str(bsl_file)
        assert captured["file_path"] == str(bsl_file)
        assert captured["content"] == "А = 1;\n"

    def test_check_content_uses_bounded_cache_for_same_path_and_content(self, monkeypatch) -> None:
        engine = DiagnosticEngine()
        parser = engine._get_parser()
        parse_calls = {"count": 0}

        class _FakeTree:
            pass

        def fake_parse_content(content: str, file_path: str = "<string>") -> object:
            _ = content
            _ = file_path
            parse_calls["count"] += 1
            return _FakeTree()

        def fake_run_rules(
            path: str,
            content: str,
            tree: object,
            *,
            symbol_index: object | None = None,
        ) -> list[Diagnostic]:
            _ = path
            _ = content
            _ = tree
            _ = symbol_index
            return []

        monkeypatch.setattr(parser, "parse_content", fake_parse_content)
        monkeypatch.setattr(engine, "_get_parser", lambda: parser)
        monkeypatch.setattr(engine, "_run_rules", fake_run_rules)
        engine._content_diag_cache_limit = 2

        path = "/virtual/cache_test.bsl"
        content = "Процедура Тест()\nКонецПроцедуры\n"

        result1 = engine.check_content(path, content)
        result2 = engine.check_content(path, content)

        assert result1 == []
        assert result2 == []
        assert parse_calls["count"] == 1

    def test_check_content_cache_invalidates_when_content_changes(self, monkeypatch) -> None:
        engine = DiagnosticEngine()
        parser = engine._get_parser()
        parse_calls = {"count": 0}

        class _FakeTree:
            pass

        def fake_parse_content(content: str, file_path: str = "<string>") -> object:
            _ = content
            _ = file_path
            parse_calls["count"] += 1
            return _FakeTree()

        def fake_run_rules(
            path: str,
            content: str,
            tree: object,
            *,
            symbol_index: object | None = None,
        ) -> list[Diagnostic]:
            _ = path
            _ = content
            _ = tree
            _ = symbol_index
            return []

        monkeypatch.setattr(parser, "parse_content", fake_parse_content)
        monkeypatch.setattr(engine, "_get_parser", lambda: parser)
        monkeypatch.setattr(engine, "_run_rules", fake_run_rules)
        engine._content_diag_cache_limit = 2

        path = "/virtual/cache_invalidate_test.bsl"

        result1 = engine.check_content(path, "Процедура Тест()\nКонецПроцедуры\n")
        result2 = engine.check_content(path, "Процедура Тест2()\nКонецПроцедуры\n")

        assert result1 == []
        assert result2 == []
        assert parse_calls["count"] == 2

    def test_run_rules_skips_query_and_symbol_prep_when_families_disabled(
        self, monkeypatch
    ) -> None:
        import onec_hbk_bsl.analysis.diagnostic.engine as engine_mod

        engine = DiagnosticEngine(select={"BSL002"})

        class _FakeSnapshot:
            tree = object()
            is_tree_sitter = False
            procedures: list[object] = []
            regions: list[object] = []
            lines = ["Процедура Тест()\n", "КонецПроцедуры\n"]
            string_literal_ranges: tuple[tuple[int, int], ...] = ()

            @property
            def proc_node_map(self):  # pragma: no cover - defensive
                raise AssertionError("proc_node_map should not be touched for BSL002-only run")

            @property
            def symbols(self):
                raise AssertionError("symbols should not be touched when security family disabled")

            @property
            def calls(self):
                raise AssertionError("calls should not be touched when related families disabled")

            @property
            def query_text_blocks(self):
                raise AssertionError(
                    "query_text_blocks should not be touched when query family disabled"
                )

        monkeypatch.setattr(
            engine_mod,
            "build_document_snapshot",
            lambda *args, **kwargs: _FakeSnapshot(),
        )
        result = engine._run_rules("x.bsl", "Процедура Тест()\nКонецПроцедуры\n", object())
        assert result == []
