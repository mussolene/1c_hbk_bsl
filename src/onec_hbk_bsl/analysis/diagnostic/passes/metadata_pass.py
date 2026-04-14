from __future__ import annotations

from collections.abc import Callable


def extend_metadata_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[object]]]],
    *,
    engine: object,
    path: str,
    content: str,
    lines: list[str],
    tree: object,
    procs: list[object],
    snapshot: object,
) -> None:
    bsl171_204_217_248_251_252_259_268 = (
        "BSL171",
        "BSL204",
        "BSL217",
        "BSL248",
        "BSL251",
        "BSL252",
        "BSL259",
        "BSL268",
    )
    if any(engine._rule_enabled(code) for code in bsl171_204_217_248_251_252_259_268):
        rule_tasks.append(
            (
                "BSL171_204_217_248_251_252_259_268",
                lambda: engine._rule_bsl171_204_217_248_251_252_259_268_light_pool(
                    path, content, lines, tree, procs, bsl171_204_217_248_251_252_259_268
                ),
            )
        )

    bsl229_275_278 = ("BSL229", "BSL275", "BSL278")
    if any(engine._rule_enabled(code) for code in bsl229_275_278):
        rule_tasks.append(
            (
                "BSL229_275_278",
                lambda: engine._rule_bsl229_275_278_local_xml_pool(
                    path, lines, procs, bsl229_275_278
                ),
            )
        )

    bsl169_170_181_182_196_260 = (
        "BSL169",
        "BSL170",
        "BSL181",
        "BSL182",
        "BSL196",
        "BSL260",
    )
    if any(engine._rule_enabled(code) for code in bsl169_170_181_182_196_260):
        rule_tasks.append(
            (
                "BSL169_170_181_182_196_260",
                lambda: engine._rule_bsl169_170_181_182_196_260_light_pool(
                    path, lines, procs, bsl169_170_181_182_196_260, snapshot
                ),
            )
        )

    bsl189_211_213_214_231_232_241_242_246_274 = (
        "BSL189",
        "BSL211",
        "BSL213",
        "BSL214",
        "BSL231",
        "BSL232",
        "BSL241",
        "BSL242",
        "BSL246",
        "BSL274",
    )
    if any(engine._rule_enabled(code) for code in bsl189_211_213_214_231_232_241_242_246_274):
        rule_tasks.append(
            (
                "BSL189_211_213_214_231_232_241_242_246_274",
                lambda: engine._rule_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
                    path,
                    lines,
                    procs,
                    bsl189_211_213_214_231_232_241_242_246_274,
                    snapshot,
                ),
            )
        )
