from __future__ import annotations

import os

from onec_hbk_bsl.analysis.diagnostic.execution import (
    execute_diagnostic_rule_tasks,
    make_diagnostic_rule_task,
)


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
