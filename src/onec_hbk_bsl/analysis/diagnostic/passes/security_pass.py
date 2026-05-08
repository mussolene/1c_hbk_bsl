from __future__ import annotations

from collections.abc import Callable


def extend_security_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[object]]]],
    *,
    engine: object,
    path: str,
    lines: list[str],
    tree: object,
    symbols: list[tuple[str, int, int]],
    calls: list[tuple[str, int, int]],
    procs: list[object],
    snapshot: object,
) -> None:
    bsl180_184_185_188_203_226_247_250_264_267_272 = (
        "BSL184",
        "BSL226",
        "BSL247",
        "BSL250",
        "BSL264",
        "BSL267",
        "BSL272",
    )
    if any(engine._rule_enabled(code) for code in bsl180_184_185_188_203_226_247_250_264_267_272):
        rule_tasks.append(
            (
                "BSL184_226_247_250_264_267_272",
                lambda: engine._rule_bsl180_184_185_188_203_226_247_250_264_267_272_api_pool(
                    path,
                    lines,
                    bsl180_184_185_188_203_226_247_250_264_267_272,
                    snapshot,
                ),
            )
        )

    bsl175_176 = ("BSL175", "BSL176")
    if any(engine._rule_enabled(code) for code in bsl175_176):
        rule_tasks.append(
            (
                "BSL175_176",
                lambda: engine._rule_bsl175_176_177_179_195_deprecated_api_diagnostics(
                    path, lines, symbols, calls, bsl175_176
                ),
            )
        )

    bsl202_205_223_243_249 = ("BSL202", "BSL205", "BSL223", "BSL243", "BSL249")
    if any(engine._rule_enabled(code) for code in bsl202_205_223_243_249):
        rule_tasks.append(
            (
                "BSL202_205_223_243_249",
                lambda: engine._rule_bsl202_205_223_243_249_light_call_pool(
                    path, lines, tree, bsl202_205_223_243_249, snapshot
                ),
            )
        )

    bsl244_253_261 = ("BSL244", "BSL253", "BSL261")
    if any(engine._rule_enabled(code) for code in bsl244_253_261):
        rule_tasks.append(
            (
                "BSL244_253_261",
                lambda: engine._rule_bsl244_253_261_runtime_pool(
                    path, lines, procs, bsl244_253_261, snapshot
                ),
            )
        )
