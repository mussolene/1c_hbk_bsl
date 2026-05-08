from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, ProcInfo


def extend_method_contract_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: object,
    path: str,
    content: str,
    lines: list[str],
    procs: list[ProcInfo],
    tree: object,
    calls: list[tuple[str, int, int]],
    proc_node_map: dict[str, object],
    snapshot: object,
) -> None:
    bsl192_193_194_228_266 = ("BSL192", "BSL193", "BSL194", "BSL228", "BSL266")
    if any(engine._rule_enabled(code) for code in bsl192_193_194_228_266):
        rule_tasks.append(
            (
                "BSL192_193_194_228_266",
                lambda: engine._rule_bsl192_193_194_228_266_method_contract_diagnostics(
                    path, lines, procs, bsl192_193_194_228_266
                ),
            )
        )

    if engine._rule_enabled("BSL212"):
        rule_tasks.append(
            (
                "BSL212",
                lambda: engine._rule_bsl212_missed_required_parameter(
                    path, content, lines, procs, calls
                ),
            )
        )

    if engine._rule_enabled("BSL215"):
        rule_tasks.append(
            (
                "BSL215",
                lambda: engine._rule_bsl215_missing_parameter_description(path, lines, procs),
            )
        )

    bsl221_222_239_271 = ("BSL221", "BSL222", "BSL239", "BSL271")
    if any(engine._rule_enabled(code) for code in bsl221_222_239_271):
        rule_tasks.append(
            (
                "BSL221_222_239_271",
                lambda: engine._rule_bsl221_222_239_271_light_pool(
                    path, lines, tree, procs, bsl221_222_239_271, snapshot
                ),
            )
        )

    if engine._rule_enabled("BSL224"):
        rule_tasks.append(
            (
                "BSL224",
                lambda: engine._rule_bsl224_nested_function_in_parameters(path, lines, tree),
            )
        )

    if engine._rule_enabled("BSL233"):
        rule_tasks.append(
            ("BSL233", lambda: engine._rule_bsl233_public_methods_description(path, lines, procs))
        )

    if engine._rule_enabled("BSL240"):
        rule_tasks.append(
            (
                "BSL240",
                lambda: engine._rule_bsl240_rewrite_method_parameter(
                    path, lines, procs, tree, proc_node_map
                ),
            )
        )

    if engine._rule_enabled("BSL254"):
        rule_tasks.append(
            ("BSL254", lambda: engine._rule_bsl254_transferring_parameters(path, lines, procs))
        )
