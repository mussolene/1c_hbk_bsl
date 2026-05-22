from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_SEQUENTIAL_RULE_CODES: frozenset[str] = frozenset(
    {
        # Rules below can touch SymbolIndex / metadata backends or reuse shared
        # engine state that should stay on the calling thread until the backend
        # contracts are explicitly made worker-safe.
        "BSL152",
        "BSL154",
        "BSL156",
        "BSL158",
        "BSL159",
        "BSL160",
        "BSL161",
        "BSL162",
        "BSL163",
        "BSL164",
        "BSL165",
        "BSL166",
        "BSL167",
        "BSL168",
        "BSL172",
        "BSL174",
        "BSL187",
        "BSL189",
        "BSL211",
        "BSL212",
        "BSL213",
        "BSL214",
        "BSL231",
        "BSL232",
        "BSL236",
        "BSL238",
        "BSL241",
        "BSL242",
        "BSL244",
        "BSL246",
        "BSL253",
        "BSL261",
        "BSL274",
    }
)


def _parallel_workers() -> int:
    raw = os.environ.get("BSL_DIAG_PARALLEL_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return 1
    return max(1, min(8, os.cpu_count() or 1))


def _parallel_enabled() -> bool:
    value = os.environ.get("BSL_DIAG_PARALLEL_RULES", "0").strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _execute_sequential(tasks: list[tuple[str, Callable[[], list[Any]]]]) -> list[Any]:
    out: list[Any] = []
    for _code, fn in tasks:
        out.extend(fn())
    return out


def execute_diagnostic_rule_tasks(
    tasks: list[tuple[str, Callable[[], list[Any]]]],
) -> list[Any]:
    """
    Run enabled rule callables.

    Most rule objects are read-only over the prepared document context and can
    run concurrently. Rules that may touch SymbolIndex/metadata/shared backends
    stay sequential until those contracts are made explicitly worker-safe.
    """
    if len(tasks) <= 1 or not _parallel_enabled():
        return _execute_sequential(tasks)

    parallel_tasks: list[tuple[int, str, Callable[[], list[Any]]]] = []
    sequential_tasks: list[tuple[int, str, Callable[[], list[Any]]]] = []
    for index, (code, fn) in enumerate(tasks):
        target = sequential_tasks if code in _SEQUENTIAL_RULE_CODES else parallel_tasks
        target.append((index, code, fn))

    results_by_index: dict[int, list[Any]] = {}
    workers = min(_parallel_workers(), len(parallel_tasks))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bsl-diag-rule") as pool:
            future_to_index = {pool.submit(fn): index for index, _code, fn in parallel_tasks}
            for future, index in future_to_index.items():
                results_by_index[index] = future.result()
    else:
        for index, _code, fn in parallel_tasks:
            results_by_index[index] = fn()

    for index, _code, fn in sequential_tasks:
        results_by_index[index] = fn()

    out: list[Any] = []
    for index in range(len(tasks)):
        out.extend(results_by_index.get(index, []))
    return out
