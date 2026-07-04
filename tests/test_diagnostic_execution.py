from __future__ import annotations

import os
from types import SimpleNamespace

from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.context import DiagnosticDocumentContext
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import FileSystemAccessRule
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.runner import (
    append_diagnostic_runtime_rule_tasks,
)
from onec_hbk_bsl.analysis.diagnostic.execution import (
    execute_diagnostic_rule_tasks,
    make_diagnostic_rule_task,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.parser.bsl_parser import BslParser


def _worker_pid() -> list[int]:
    return [os.getpid()]


def test_process_safe_tasks_run_in_process_pool_and_preserve_order(monkeypatch) -> None:
    parent_pid = os.getpid()
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")

    result = execute_diagnostic_rule_tasks(
        [
            make_diagnostic_rule_task("BSL256:0", _worker_pid, process_safe=True),
            ("LOCAL", lambda: [parent_pid]),
            make_diagnostic_rule_task("BSL256:1", _worker_pid, process_safe=True),
        ]
    )

    assert result[1] == parent_pid
    assert result[0] != parent_pid
    assert result[2] != parent_pid


def test_light_pool_rules_are_scheduled_as_shared_fact_phases() -> None:
    selected = {
        "BSL169",
        "BSL170",
        "BSL171",
        "BSL181",
        "BSL196",
        "BSL202",
        "BSL221",
        "BSL222",
        "BSL223",
        "BSL239",
        "BSL243",
        "BSL248",
        "BSL249",
        "BSL251",
        "BSL252",
        "BSL259",
        "BSL260",
        "BSL268",
        "BSL271",
    }
    engine = DiagnosticEngine(select=selected)
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=engine,
        path="Module.bsl",
        content="",
        lines=[],
        tree=None,
        snapshot=None,
    )

    task_codes = [code for code, _ in tasks]
    assert "BSL169+BSL170+BSL181+BSL196+BSL260" in task_codes
    assert "BSL171+BSL248+BSL252+BSL259+BSL268" in task_codes
    assert "BSL202+BSL223+BSL243+BSL249" in task_codes
    assert "BSL221+BSL222+BSL239+BSL271" in task_codes
    assert "BSL251" in task_codes
    assert not (selected - {"BSL251"}) & set(task_codes)


def test_core_fact_phase_materializes_only_enabled_fact_family() -> None:
    class Snapshot:
        procedures = []

        def __init__(self) -> None:
            self.accessed: list[str] = []

        def line_too_long_facts(self, max_line_length: int) -> list[SimpleNamespace]:
            self.accessed.append(f"line_too_long:{max_line_length}")
            return [
                SimpleNamespace(
                    line_idx=0,
                    character=0,
                    end_line_idx=None,
                    end_character=max_line_length + 1,
                )
            ]

        def complexity_metrics_for_procs(self, procs) -> list[tuple[int, int]]:
            raise AssertionError("complexity metrics must not be built for BSL014")

        @property
        def hardcoded_credential_facts(self):
            raise AssertionError("BSL012 facts must not be built for BSL014")

        @property
        def commented_code_facts(self):
            raise AssertionError("BSL013 facts must not be built for BSL014")

        @property
        def missing_space_facts(self):
            raise AssertionError("BSL216 facts must not be built for BSL014")

    snapshot = Snapshot()
    engine = DiagnosticEngine(select={"BSL014"})
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=engine,
        path="Module.bsl",
        content="",
        lines=["A"],
        tree=None,
        snapshot=snapshot,
    )

    core_tasks = [task for task in tasks if getattr(task, "code", None) == "BSL014"]
    assert len(core_tasks) == 1
    assert snapshot.accessed == [f"line_too_long:{engine.max_line_length}"]

    result = execute_diagnostic_rule_tasks(core_tasks)
    assert [diagnostic.code for diagnostic in result] == ["BSL014"]


def test_runtime_cst_prewarm_uses_enabled_rule_contracts() -> None:
    engine = DiagnosticEngine(select={"BSL066", "BSL215"})
    requested: list[set[str]] = []

    def record_ts_nodes_for_types(tree, node_types: set[str]):
        requested.append(set(node_types))
        return {node_type: [] for node_type in node_types}

    engine._ts_nodes_for_types = record_ts_nodes_for_types
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=engine,
        path="Module.bsl",
        content="",
        lines=[],
        tree=object(),
        snapshot=None,
    )

    assert requested[0] == {"line_comment", "method_call"}


def test_access_rules_are_scheduled_as_shared_node_phase() -> None:
    selected = {"BSL188", "BSL203", "BSL264"}
    engine = DiagnosticEngine(select=selected)
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=engine,
        path="Module.bsl",
        content="",
        lines=[],
        tree=object(),
        snapshot=None,
    )

    task_codes = [code for code, _ in tasks]
    assert "BSL188+BSL203+BSL264" in task_codes
    assert not selected & set(task_codes)


def test_filesystem_access_rule_requires_runtime_cst_provider() -> None:
    content = """\
Процедура Метод()
    Ф = Новый Файл("a.txt");
КонецПроцедуры
"""
    tree = BslParser().parse_content(content, file_path="Module.bsl")
    context = DiagnosticDocumentContext(
        path="Module.bsl",
        content=content,
        lines=content.splitlines(),
        tree=tree,
        ts_nodes_for_types=None,
    )

    assert FileSystemAccessRule().run(context) == []
