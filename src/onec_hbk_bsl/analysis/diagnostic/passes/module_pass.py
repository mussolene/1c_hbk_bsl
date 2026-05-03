from __future__ import annotations

from collections.abc import Callable


def extend_module_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[object]]]],
    *,
    engine: object,
    path: str,
    content: str,
    lines: list[str],
    procs: list[object],
    regions: list[tuple[int, int]],
    tree: object,
    idx: object,
) -> None:
    if engine._rule_enabled("BSL158") and idx is not None:
        rule_tasks.append(
            ("BSL158", lambda: engine._rule_bsl158_common_module_assign(path, lines, idx))
        )
    if engine._rule_enabled("BSL159"):
        rule_tasks.append(
            ("BSL159", lambda: engine._rule_bsl159_common_module_invalid_type(path, lines))
        )
    if engine._rule_enabled("BSL160"):
        rule_tasks.append(
            (
                "BSL160",
                lambda: engine._rule_bsl160_common_module_missing_api(path, lines, regions, procs),
            )
        )

    bsl161_168 = (
        "BSL161",
        "BSL162",
        "BSL163",
        "BSL164",
        "BSL165",
        "BSL166",
        "BSL167",
        "BSL168",
    )
    if any(engine._rule_enabled(code) for code in bsl161_168):
        rule_tasks.append(
            (
                "BSL161-168",
                lambda: engine._rule_bsl161_168_common_module_names(path, lines, bsl161_168),
            )
        )

    if engine._rule_enabled("BSL172"):
        rule_tasks.append(
            ("BSL172", lambda: engine._rule_bsl172_data_exchange_loading(path, lines, procs))
        )
    if engine._rule_enabled("BSL173"):
        rule_tasks.append(
            ("BSL173", lambda: engine._rule_bsl173_deleting_collection_item(path, lines, procs))
        )

    if engine._rule_enabled("BSL190"):
        rule_tasks.append(("BSL190", lambda: engine._rule_bsl190_form_data_to_value(path, lines)))
    if engine._rule_enabled("BSL245"):
        rule_tasks.append(
            (
                "BSL245",
                lambda: engine._rule_bsl245_server_side_export_form_method(path, lines, procs),
            )
        )
    if engine._rule_enabled("BSL237"):
        rule_tasks.append(
            ("BSL237", lambda: engine._rule_bsl237_redundant_access_to_object(path, lines))
        )
