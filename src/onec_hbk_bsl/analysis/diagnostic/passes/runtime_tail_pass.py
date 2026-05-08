from __future__ import annotations

from collections.abc import Callable


def extend_runtime_tail_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[object]]]],
    *,
    engine: object,
    path: str,
    lines: list[str],
    procs: list[object],
    tree: object,
    snapshot: object,
) -> None:
    if engine._rule_enabled("BSL149"):
        rule_tasks.append(
            (
                "BSL149",
                lambda: engine._rule_bsl149_assign_alias_fields_in_query(path, lines, snapshot),
            )
        )
    if engine._rule_enabled("BSL150"):
        rule_tasks.append(("BSL150", lambda: engine._rule_bsl150_bad_words(path, lines)))
    if engine._rule_enabled("BSL197"):
        rule_tasks.append(
            ("BSL197", lambda: engine._rule_bsl197_if_else_duplicated_code_block(path, lines))
        )
    if engine._rule_enabled("BSL198"):
        rule_tasks.append(
            ("BSL198", lambda: engine._rule_bsl198_if_else_duplicated_condition(path, lines))
        )
    if engine._rule_enabled("BSL199"):
        rule_tasks.append(
            ("BSL199", lambda: engine._rule_bsl199_if_else_if_ends_with_else(path, lines))
        )
    if engine._rule_enabled("BSL208") or engine._rule_enabled("BSL256"):

        def task_bsl208_bsl256() -> list[object]:
            out = engine._rule_bsl208_bsl256_latin_cyrillic_and_typo(path, lines, procs, snapshot)
            if engine._rule_enabled("BSL256"):
                out.extend(engine._rule_bsl256_bslls_typo_spellcheck(path, tree))
            return out

        rule_tasks.append(("BSL208_BSL256", task_bsl208_bsl256))

    if engine._rule_enabled("BSL218"):
        rule_tasks.append(
            (
                "BSL218",
                lambda: engine._rule_bsl218_missing_temporary_file_deletion(path, lines, tree),
            )
        )
    if engine._rule_enabled("BSL225"):
        rule_tasks.append(
            (
                "BSL225",
                lambda: engine._rule_bsl225_number_of_values_in_structure_constructor(
                    path, lines, tree
                ),
            )
        )
    if engine._rule_enabled("BSL230"):
        rule_tasks.append(
            ("BSL230", lambda: engine._rule_bsl230_pairing_broken_transaction(path, tree))
        )
    if engine._rule_enabled("BSL258"):
        rule_tasks.append(("BSL258", lambda: engine._rule_bsl258_union_without_all(path, lines)))
    if engine._rule_enabled("BSL262"):
        rule_tasks.append(("BSL262", lambda: engine._rule_bsl262_usage_write_log_event(path, tree)))
    if engine._rule_enabled("BSL263"):
        rule_tasks.append(
            ("BSL263", lambda: engine._rule_bsl263_useless_for_each(path, lines, procs))
        )
