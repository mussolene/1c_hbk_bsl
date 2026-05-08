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
    if engine._rule_enabled("BSL208") or engine._rule_enabled("BSL256"):

        def task_bsl208_bsl256() -> list[object]:
            out = engine._rule_bsl208_bsl256_latin_cyrillic_and_typo(path, lines, procs, snapshot)
            if engine._rule_enabled("BSL256"):
                out.extend(engine._rule_bsl256_bslls_typo_spellcheck(path, tree))
            return out

        rule_tasks.append(("BSL208_BSL256", task_bsl208_bsl256))
