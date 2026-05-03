#!/usr/bin/env python3
"""Deterministic probe for LSP navigation hot paths (hover/references/call hierarchy)."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from onec_hbk_bsl.lsp.server import (
    BslLanguageServer,
    on_call_hierarchy_incoming,
    on_call_hierarchy_outgoing,
    on_hover,
    on_references,
)


def _make_params(uri: str, line: int, character: int) -> SimpleNamespace:
    return SimpleNamespace(
        text_document=SimpleNamespace(uri=uri),
        position=SimpleNamespace(line=line, character=character),
        context=SimpleNamespace(include_declaration=False),
    )


def _measure(fn, iterations: int = 200):  # type: ignore[no-untyped-def]
    durations = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        durations.append((time.perf_counter() - t0) * 1000.0)
    return {
        "iterations": iterations,
        "median_ms": round(statistics.median(durations), 4),
        "p95_ms": round(statistics.quantiles(durations, n=20)[18], 4),
        "max_ms": round(max(durations), 4),
    }


def run_probe() -> dict[str, object]:
    ls = BslLanguageServer()
    uri = "file:///probe.bsl"
    ls._docs[uri] = "МойВызов();\n"

    calls = {"find_symbol": 0, "find_callers": 0, "find_callees": 0}

    def _base_find_callers(name, limit=200):  # type: ignore[no-untyped-def]
        return [
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 3,
                "caller_character": 10,
                "caller_name": "ОбработатьЗаказ",
                "callee_name": "Цель",
            },
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 7,
                "caller_character": 12,
                "caller_name": "ОбработатьЗаказ",
                "callee_name": "Цель",
            },
        ]

    ls.symbol_index.find_callers = _base_find_callers  # type: ignore[method-assign]

    def _find_callers(name, limit=200):  # type: ignore[no-untyped-def]
        calls["find_callers"] += 1
        return _base_find_callers(name, limit=limit)

    ls.symbol_index.find_callers = _find_callers  # type: ignore[method-assign]

    def _base_find_callees(caller_file, caller_name=None, caller_line=None):  # type: ignore[no-untyped-def]
        return [
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 3,
                "caller_character": 10,
                "callee_name": "ЗаписатьЛог",
            },
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 7,
                "caller_character": 12,
                "callee_name": "ЗаписатьЛог",
            },
        ]

    ls.symbol_index.find_callees = _base_find_callees  # type: ignore[method-assign]

    def _find_callees(caller_file, caller_name=None, caller_line=None):  # type: ignore[no-untyped-def]
        calls["find_callees"] += 1
        return _base_find_callees(caller_file, caller_name=caller_name, caller_line=caller_line)

    ls.symbol_index.find_callees = _find_callees  # type: ignore[method-assign]

    def _find_symbol(name, limit=20, file_filter=None, fuzzy=False):  # type: ignore[no-untyped-def]
        calls["find_symbol"] += 1
        if name == "ОбработатьЗаказ":
            return [
                {
                    "name": "ОбработатьЗаказ",
                    "kind": "function",
                    "file_path": "/workspace/a.bsl",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "signature": "Function ОбработатьЗаказ()",
                }
            ]
        if name == "ЗаписатьЛог":
            return [
                {
                    "name": "ЗаписатьЛог",
                    "kind": "procedure",
                    "file_path": "/workspace/log.bsl",
                    "line": 10,
                    "character": 0,
                    "end_line": 12,
                    "end_character": 0,
                    "signature": "Procedure ЗаписатьЛог()",
                }
            ]
        return []

    ls.symbol_index.find_symbol = _find_symbol  # type: ignore[method-assign]

    hover_params = _make_params(uri, 0, 2)
    ref_params = _make_params(uri, 0, 2)
    incoming_params = SimpleNamespace(item=SimpleNamespace(name="Цель"))
    outgoing_params = SimpleNamespace(
        item=SimpleNamespace(name="ОбработатьЗаказ", uri="file:///workspace/a.bsl")
    )

    # Warm-up
    on_hover(ls, hover_params)
    on_references(ls, ref_params)
    on_call_hierarchy_incoming(ls, incoming_params)
    on_call_hierarchy_outgoing(ls, outgoing_params)

    before_hover = dict(calls)
    hover_stats = _measure(lambda: on_hover(ls, hover_params), iterations=200)
    after_hover = dict(calls)

    before_refs = dict(calls)
    refs_stats = _measure(lambda: on_references(ls, ref_params), iterations=200)
    after_refs = dict(calls)

    before_incoming = dict(calls)
    incoming_stats = _measure(
        lambda: on_call_hierarchy_incoming(ls, incoming_params), iterations=200
    )
    after_incoming = dict(calls)

    before_outgoing = dict(calls)
    outgoing_stats = _measure(
        lambda: on_call_hierarchy_outgoing(ls, outgoing_params), iterations=200
    )
    after_outgoing = dict(calls)

    def _delta(a, b):  # type: ignore[no-untyped-def]
        return {k: b[k] - a[k] for k in calls}

    hover_delta = _delta(before_hover, after_hover)
    refs_delta = _delta(before_refs, after_refs)
    incoming_delta = _delta(before_incoming, after_incoming)
    outgoing_delta = _delta(before_outgoing, after_outgoing)

    # For incoming/outgoing each request has duplicated caller/callee rows.
    # With lookup cache, each request should resolve symbol only once.
    expected_symbol_calls_per_hierarchy = 200

    return {
        "probe": "lsp_navigation_hot_paths",
        "hover": hover_stats,
        "references": refs_stats,
        "call_hierarchy_incoming": incoming_stats,
        "call_hierarchy_outgoing": outgoing_stats,
        "lookup_call_deltas": {
            "hover": hover_delta,
            "references": refs_delta,
            "incoming": incoming_delta,
            "outgoing": outgoing_delta,
        },
        "symbol_lookup_cache_assertion": {
            "expected_upper_bound_per_hierarchy_callset": expected_symbol_calls_per_hierarchy,
            "incoming_find_symbol_calls": incoming_delta["find_symbol"],
            "outgoing_find_symbol_calls": outgoing_delta["find_symbol"],
            "incoming_cache_effective": incoming_delta["find_symbol"]
            <= expected_symbol_calls_per_hierarchy,
            "outgoing_cache_effective": outgoing_delta["find_symbol"]
            <= expected_symbol_calls_per_hierarchy,
        },
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / ".agent" / "tasks" / "python-bslls-full-parity" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"lsp-nav-probe-{ts}.json"
    payload = run_probe()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"probe: {out_path}")
    print(f"hover_median_ms: {payload['hover']['median_ms']}")  # type: ignore[index]
    print(f"references_median_ms: {payload['references']['median_ms']}")  # type: ignore[index]
    print(f"incoming_median_ms: {payload['call_hierarchy_incoming']['median_ms']}")  # type: ignore[index]
    print(f"outgoing_median_ms: {payload['call_hierarchy_outgoing']['median_ms']}")  # type: ignore[index]
    print(
        "find_symbol_calls_incoming_delta: "
        f"{payload['lookup_call_deltas']['incoming']['find_symbol']}"  # type: ignore[index]
    )
    print(
        "find_symbol_calls_outgoing_delta: "
        f"{payload['lookup_call_deltas']['outgoing']['find_symbol']}"  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
