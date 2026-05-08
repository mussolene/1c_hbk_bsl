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
    if engine._rule_enabled("BSL208") or engine._rule_enabled("BSL256"):

        def task_bsl208_bsl256() -> list[object]:
            out = engine._rule_bsl208_bsl256_latin_cyrillic_and_typo(path, lines, procs, snapshot)
            if engine._rule_enabled("BSL256"):
                out.extend(engine._rule_bsl256_bslls_typo_spellcheck(path, tree))
            return out

        rule_tasks.append(("BSL208_BSL256", task_bsl208_bsl256))

    if engine._rule_enabled("BSL258"):
        rule_tasks.append(("BSL258", lambda: engine._rule_bsl258_union_without_all(path, lines)))
    if engine._rule_enabled("BSL262"):
        rule_tasks.append(("BSL262", lambda: engine._rule_bsl262_usage_write_log_event(path, tree)))
