from __future__ import annotations

import os
import pickle
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from types import SimpleNamespace

import onec_hbk_bsl.analysis.diagnostic.execution as diagnostic_execution
from onec_hbk_bsl.analysis.diagnostic.cst import iter_ts_nodes
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.context import DiagnosticDocumentContext
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import (
    CoreDiagnosticsRule,
    FileSystemAccessRule,
)
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.runner import (
    append_diagnostic_runtime_rule_tasks,
)
from onec_hbk_bsl.analysis.diagnostic.execution import (
    execute_diagnostic_rule_tasks,
    make_diagnostic_rule_task,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
from onec_hbk_bsl.parser.bsl_parser import BslParser


def _worker_pid() -> list[int]:
    return [os.getpid()]


def _task_signature(value: str) -> list[str]:
    return [value]


def test_iter_ts_nodes_preserves_tree_sitter_preorder() -> None:
    tree = BslParser().parse_content("Процедура Тест()\nКонецПроцедуры\n", file_path="Module.bsl")

    actual = [(node.type, node.start_byte, node.end_byte) for node in iter_ts_nodes(tree.root_node)]

    def recursive(node):
        yield node
        for child in node.children:
            yield from recursive(child)

    expected = [(node.type, node.start_byte, node.end_byte) for node in recursive(tree.root_node)]
    assert actual == expected


def test_iter_ts_nodes_supports_nodes_without_tree_cursor() -> None:
    leaf_a = SimpleNamespace(name="a", children=[])
    leaf_b = SimpleNamespace(name="b", children=[])
    branch = SimpleNamespace(name="branch", children=[leaf_b])
    root = SimpleNamespace(name="root", children=[leaf_a, branch])

    assert [node.name for node in iter_ts_nodes(root)] == ["root", "a", "branch", "b"]


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


def test_large_documents_keep_only_serializable_process_tasks() -> None:
    content = "Процедура Тест()\nКонецПроцедуры\n"
    tree = BslParser().parse_content(content, file_path="Module.bsl")
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=DiagnosticEngine(select={"BSL186", "BSL279"}),
        path="Module.bsl",
        content=content,
        lines=content.splitlines(),
        tree=tree,
        snapshot=None,
    )

    assert [task[0] for task in tasks] == ["BSL186", "BSL279"]
    assert all(not task[0].startswith("fork") for task in tasks)
    assert execute_diagnostic_rule_tasks(tasks) == []


def test_process_safe_task_is_immutable_serializable_dto() -> None:
    task = make_diagnostic_rule_task(
        "BSL256:0",
        partial(_task_signature, "stable"),
        process_safe=True,
    )

    restored = pickle.loads(pickle.dumps(task))  # noqa: S301 - trusted test object

    assert restored.code == "BSL256:0"
    assert restored.process_safe is True
    assert restored.fn() == ["stable"]


def test_process_and_serial_paths_have_identical_signatures(monkeypatch) -> None:
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")
    tasks = [
        make_diagnostic_rule_task(
            "BSL256:0",
            partial(_task_signature, "first"),
            process_safe=True,
        ),
        ("LOCAL", partial(_task_signature, "middle")),
        make_diagnostic_rule_task(
            "BSL256:1",
            partial(_task_signature, "last"),
            process_safe=True,
        ),
    ]

    process_result = execute_diagnostic_rule_tasks(tasks)
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "0")
    serial_result = execute_diagnostic_rule_tasks(tasks)

    assert process_result == serial_result == ["first", "middle", "last"]


def test_background_documents_never_start_process_pool_or_mix_context(monkeypatch) -> None:
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")

    def unexpected_process_pool(workers: int):
        raise AssertionError(f"background thread requested {workers} process workers")

    monkeypatch.setattr(diagnostic_execution, "_get_process_pool", unexpected_process_pool)

    def document_tasks(path: str, long_line_index: int):
        lines = [""] * 5_000
        lines[long_line_index] = "А" * 121
        content = "\n".join(lines)
        snapshot = build_document_snapshot(path, content=content)
        tasks = []
        append_diagnostic_runtime_rule_tasks(
            tasks,
            engine=DiagnosticEngine(select={"BSL014"}),
            path=path,
            content=content,
            lines=lines,
            tree=snapshot.tree,
            snapshot=snapshot,
        )
        return tasks

    task_sets = [
        document_tasks("First.bsl", 0),
        document_tasks("Second.bsl", 4_999),
    ]
    barrier = threading.Barrier(2)

    def run_background(tasks):
        barrier.wait()
        return [
            (diagnostic.file, diagnostic.line, diagnostic.code)
            for diagnostic in execute_diagnostic_rule_tasks(tasks)
        ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_background, tasks) for tasks in task_sets]
        results = [future.result() for future in futures]

    assert results == [
        [("First.bsl", 1, "BSL014")],
        [("Second.bsl", 5_000, "BSL014")],
    ]


def test_worker_submission_failure_falls_back_once(monkeypatch) -> None:
    calls: list[str] = []

    class FailingPool:
        def submit(self, fn):
            raise RuntimeError("injected worker failure")

    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")
    monkeypatch.setattr(diagnostic_execution, "_get_process_pool", lambda workers: FailingPool())
    monkeypatch.setattr(diagnostic_execution, "_shutdown_process_pool", lambda: None)

    def record_fallback() -> list[str]:
        calls.append("fallback")
        return ["result"]

    result = execute_diagnostic_rule_tasks(
        [
            make_diagnostic_rule_task("PROCESS", record_fallback, process_safe=True),
            make_diagnostic_rule_task("PROCESS:2", lambda: [], process_safe=True),
        ]
    )

    assert result == ["result"]
    assert calls == ["fallback"]


def test_process_pool_creation_failure_falls_back_once(monkeypatch) -> None:
    calls: list[str] = []
    shutdown_calls: list[str] = []

    def unavailable_pool(workers: int):
        raise OSError(f"injected failure for {workers} workers")

    def record(value: str) -> list[str]:
        calls.append(value)
        return [value]

    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")
    monkeypatch.setattr(diagnostic_execution, "_get_process_pool", unavailable_pool)
    monkeypatch.setattr(
        diagnostic_execution,
        "_shutdown_process_pool",
        lambda: shutdown_calls.append("shutdown"),
    )
    tasks = [
        make_diagnostic_rule_task(
            value,
            partial(record, value),
            process_safe=True,
        )
        for value in ("first", "second")
    ]

    result = execute_diagnostic_rule_tasks(tasks)

    assert result == ["first", "second"]
    assert calls == ["first", "second"]
    assert shutdown_calls == ["shutdown"]


def test_worker_result_failure_falls_back_once(monkeypatch) -> None:
    calls: list[str] = []

    class ResultFailingPool:
        def __init__(self) -> None:
            self.submissions = 0

        def submit(self, fn):
            self.submissions += 1
            future: Future[list[str]] = Future()
            if self.submissions == 1:
                future.set_exception(RuntimeError("injected result failure"))
            else:
                future.set_result(fn())
            return future

    def record_fallback() -> list[str]:
        calls.append("fallback")
        return ["recovered"]

    pool = ResultFailingPool()
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "2")
    monkeypatch.setattr(diagnostic_execution, "_get_process_pool", lambda workers: pool)
    tasks = [
        make_diagnostic_rule_task("FAIL", record_fallback, process_safe=True),
        make_diagnostic_rule_task(
            "OK",
            partial(_task_signature, "stable"),
            process_safe=True,
        ),
    ]

    result = execute_diagnostic_rule_tasks(tasks)

    assert result == ["recovered", "stable"]
    assert calls == ["fallback"]


def test_process_submission_count_is_bounded(monkeypatch) -> None:
    class ImmediatePool:
        def __init__(self) -> None:
            self.submissions = 0

        def submit(self, fn):
            self.submissions += 1
            future: Future[list[str]] = Future()
            future.set_result(fn())
            return future

    pool = ImmediatePool()
    monkeypatch.setenv("BSL_DIAG_PROCESS_RULES", "1")
    monkeypatch.setenv("BSL_DIAG_PARALLEL_WORKERS", "8")
    monkeypatch.setattr(diagnostic_execution, "_get_process_pool", lambda workers: pool)
    tasks = [
        make_diagnostic_rule_task(
            f"TASK:{index}",
            partial(_task_signature, str(index)),
            process_safe=True,
        )
        for index in range(diagnostic_execution._MAX_PROCESS_TASKS + 5)
    ]

    result = execute_diagnostic_rule_tasks(tasks)

    assert pool.submissions == diagnostic_execution._MAX_PROCESS_TASKS
    assert result == [str(index) for index in range(len(tasks))]


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


def test_core_complexity_fallback_reads_metrics_from_request_snapshot() -> None:
    content = """\
Процедура Сложная()
    Если Истина Тогда
        Возврат;
    КонецЕсли;
КонецПроцедуры
"""
    snapshot = build_document_snapshot("Module.bsl", content=content)
    engine = DiagnosticEngine(
        select={"BSL011", "BSL019"},
        max_cognitive_complexity=0,
        max_mccabe_complexity=0,
    )
    context = DiagnosticDocumentContext(
        path=snapshot.path,
        content=snapshot.content,
        lines=snapshot.lines,
        tree=snapshot.tree,
        snapshot=snapshot,
        diagnostics_engine=engine,
    )

    assert [diag.code for diag in CoreDiagnosticsRule("BSL011").run(context)] == ["BSL011"]
    assert [diag.code for diag in CoreDiagnosticsRule("BSL019").run(context)] == ["BSL019"]


def test_runtime_cst_prewarm_uses_enabled_rule_contracts() -> None:
    engine = DiagnosticEngine(select={"BSL022", "BSL066", "BSL215"})
    requested: list[set[str]] = []

    def record_ts_nodes_for_types(tree, node_types: set[str], *, snapshot=None):
        _ = snapshot
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

    assert requested[0] == {"line_comment", "method_call", "string"}


def test_runtime_cst_prewarm_covers_late_runtime_consumers() -> None:
    selected = {
        "BSL025",
        "BSL027",
        "BSL028",
        "BSL029",
        "BSL030",
        "BSL052",
        "BSL060",
        "BSL064",
        "BSL151",
        "BSL217",
        "BSL230",
        "BSL256",
        "BSL271",
        "BSL276",
        "BSL277",
    }
    engine = DiagnosticEngine(select=selected)
    requested: list[set[str]] = []

    def record_ts_nodes_for_types(tree, node_types: set[str], *, snapshot=None):
        _ = snapshot
        requested.append(set(node_types))
        return {node_type: [] for node_type in node_types}

    engine._ts_nodes_for_types = record_ts_nodes_for_types
    content = """\
Процедура Метод()
    НачатьТранзакцию();
    ОтменитьТранзакцию();
    Значение = 2;
    Если Не Не Флаг Тогда
    КонецЕсли;
    Адрес = ПолучитьИзВременногоХранилища("x");
    ПродолжитьВызов();
КонецПроцедуры
"""
    lines = content.splitlines()
    tree = BslParser().parse_content(content, file_path="Module.bsl")
    tasks = []

    append_diagnostic_runtime_rule_tasks(
        tasks,
        engine=engine,
        path="Module.bsl",
        content=content,
        lines=lines,
        tree=tree,
        snapshot=None,
    )
    execute_diagnostic_rule_tasks(tasks)

    assert requested[0] == {
        ";",
        "assignment_statement",
        "binary_expression",
        "break_statement",
        "call_statement",
        "continue_statement",
        "for_each_statement",
        "for_statement",
        "function_definition",
        "goto_statement",
        "if_statement",
        "identifier",
        "method_call",
        "new_expression",
        "number",
        "procedure_definition",
        "property",
        "return_statement",
        "rise_error_statement",
        "string",
        "try_statement",
        "unary_expression",
        "var_statement",
        "while_statement",
    }
    assert all(call <= requested[0] for call in requested[1:])


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
