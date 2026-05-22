from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any

_PROCESS_POOL_LOCK = threading.Lock()
_PROCESS_POOL: ProcessPoolExecutor | None = None
_PROCESS_POOL_WORKERS = 0


def _shutdown_process_pool() -> None:
    global _PROCESS_POOL, _PROCESS_POOL_WORKERS
    with _PROCESS_POOL_LOCK:
        if _PROCESS_POOL is not None:
            _PROCESS_POOL.shutdown(wait=False, cancel_futures=True)
        _PROCESS_POOL = None
        _PROCESS_POOL_WORKERS = 0


atexit.register(_shutdown_process_pool)


@dataclass(frozen=True, slots=True)
class DiagnosticRuleTask:
    code: str
    fn: Callable[[], list[Any]]
    process_safe: bool = False


RuleTask = DiagnosticRuleTask | tuple[str, Callable[[], list[Any]]]


def make_diagnostic_rule_task(
    code: str,
    fn: Callable[[], list[Any]],
    *,
    process_safe: bool = False,
) -> DiagnosticRuleTask:
    return DiagnosticRuleTask(code=code, fn=fn, process_safe=process_safe)


def _parallel_workers() -> int:
    raw = os.environ.get("BSL_DIAG_PARALLEL_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return 1
    return max(1, min(8, os.cpu_count() or 1))


def _parallel_enabled() -> bool:
    value = os.environ.get("BSL_DIAG_PARALLEL_RULES", "1").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _process_parallel_enabled() -> bool:
    value = os.environ.get("BSL_DIAG_PROCESS_RULES", "1").strip().casefold()
    return _parallel_enabled() and value not in {"0", "false", "no", "off"}


def _get_process_pool(workers: int) -> ProcessPoolExecutor:
    global _PROCESS_POOL, _PROCESS_POOL_WORKERS
    with _PROCESS_POOL_LOCK:
        if _PROCESS_POOL is None or _PROCESS_POOL_WORKERS != workers:
            if _PROCESS_POOL is not None:
                _PROCESS_POOL.shutdown(wait=False, cancel_futures=True)
            _PROCESS_POOL = ProcessPoolExecutor(max_workers=workers)
            _PROCESS_POOL_WORKERS = workers
        return _PROCESS_POOL


def _normalize_task(task: RuleTask) -> DiagnosticRuleTask:
    if isinstance(task, DiagnosticRuleTask):
        return task
    code, fn = task
    return DiagnosticRuleTask(code=code, fn=fn)


def _execute_sequential(tasks: list[DiagnosticRuleTask]) -> list[Any]:
    out: list[Any] = []
    for task in tasks:
        out.extend(task.fn())
    return out


def _run_process_tasks(
    tasks: list[tuple[int, DiagnosticRuleTask]],
    results_by_index: dict[int, list[Any]],
) -> None:
    workers = min(_parallel_workers(), len(tasks))
    if workers <= 1 or not _process_parallel_enabled():
        for index, task in tasks:
            results_by_index[index] = task.fn()
        return

    future_to_task: dict[Any, tuple[int, DiagnosticRuleTask]] = {}
    pool = _get_process_pool(workers)
    for index, task in tasks:
        future_to_task[pool.submit(task.fn)] = (index, task)

    for future, (index, task) in future_to_task.items():
        try:
            results_by_index[index] = future.result()
        except Exception:
            results_by_index[index] = task.fn()


def _submit_process_tasks(
    tasks: list[tuple[int, DiagnosticRuleTask]],
) -> dict[Any, tuple[int, DiagnosticRuleTask]] | None:
    workers = min(_parallel_workers(), len(tasks))
    if workers <= 1 or not _process_parallel_enabled():
        return None
    pool = _get_process_pool(workers)
    try:
        return {pool.submit(task.fn): (index, task) for index, task in tasks}
    except (BrokenProcessPool, RuntimeError, OSError):
        _shutdown_process_pool()
        return None


def _collect_process_tasks(
    future_to_task: dict[Any, tuple[int, DiagnosticRuleTask]],
    results_by_index: dict[int, list[Any]],
) -> None:
    for future, (index, task) in future_to_task.items():
        try:
            results_by_index[index] = future.result()
        except Exception:
            results_by_index[index] = task.fn()


def execute_diagnostic_rule_tasks(
    tasks: list[RuleTask],
) -> list[Any]:
    """
    Run enabled rule callables.

    Existing rule objects close over the prepared document context, so only
    tasks explicitly marked ``process_safe`` may run in the reusable process
    pool. Those tasks must receive serializable facts, not tree-sitter objects.
    """
    normalized = [_normalize_task(task) for task in tasks]
    if len(normalized) <= 1 or not _parallel_enabled():
        return _execute_sequential(normalized)

    process_tasks: list[tuple[int, DiagnosticRuleTask]] = []
    local_tasks: list[tuple[int, DiagnosticRuleTask]] = []
    for index, task in enumerate(normalized):
        if task.process_safe:
            process_tasks.append((index, task))
        else:
            local_tasks.append((index, task))

    results_by_index: dict[int, list[Any]] = {}
    future_to_task = _submit_process_tasks(process_tasks)
    if future_to_task is None:
        _run_process_tasks(process_tasks, results_by_index)
    for index, task in local_tasks:
        results_by_index[index] = task.fn()
    if future_to_task is not None:
        _collect_process_tasks(future_to_task, results_by_index)

    out: list[Any] = []
    for index in range(len(normalized)):
        out.extend(results_by_index.get(index, []))
    return out
