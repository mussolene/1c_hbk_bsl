from __future__ import annotations

from collections.abc import Callable


def extend_core_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[object]]]],
    *,
    engine: object,
    path: str,
    lines: list[str],
    procs: list[object],
    regions: list[tuple[int, int]],
    tree: object,
    proc_node_map: dict[tuple[str, int, str], object],
    snapshot: object,
) -> None:
    if engine._rule_enabled("BSL001"):
        rule_tasks.append(("BSL001", lambda: engine._rule_bsl001_syntax_errors(path, tree)))
    if engine._rule_enabled("BSL002"):
        rule_tasks.append(("BSL002", lambda: engine._rule_bsl002_method_size(path, lines, procs)))
    if engine._rule_enabled("BSL003"):
        rule_tasks.append(
            (
                "BSL003",
                lambda: engine._rule_bsl003_non_export_in_api_region(path, lines, procs, regions),
            )
        )
    if engine._rule_enabled("BSL004"):
        rule_tasks.append(("BSL004", lambda: engine._rule_bsl004_empty_except(path, lines, tree)))
    if engine._rule_enabled("BSL007"):
        rule_tasks.append(
            (
                "BSL007",
                lambda: engine._rule_bsl007_unused_local_variable(path, lines, procs, snapshot),
            )
        )
    if engine._rule_enabled("BSL008"):
        rule_tasks.append(
            ("BSL008", lambda: engine._rule_bsl008_too_many_returns(path, lines, procs))
        )
    if engine._rule_enabled("BSL009"):
        rule_tasks.append(("BSL009", lambda: engine._rule_bsl009_self_assign(path, lines, tree)))
    if engine._rule_enabled("BSL011"):
        rule_tasks.append(
            ("BSL011", lambda: engine._rule_bsl011_cognitive_complexity(path, lines, procs))
        )
    if engine._rule_enabled("BSL012"):
        rule_tasks.append(("BSL012", lambda: engine._rule_bsl012_hardcode_credentials(path, lines)))
    if engine._rule_enabled("BSL013"):
        rule_tasks.append(("BSL013", lambda: engine._rule_bsl013_commented_code(path, lines)))
    if engine._rule_enabled("BSL014"):
        rule_tasks.append(
            ("BSL014", lambda: engine._rule_bsl014_line_too_long(path, lines, snapshot))
        )
    if engine._rule_enabled("BSL015"):
        rule_tasks.append(
            ("BSL015", lambda: engine._rule_bsl015_optional_params_count(path, lines, procs))
        )
    if engine._rule_enabled("BSL016"):
        rule_tasks.append(
            ("BSL016", lambda: engine._rule_bsl016_non_standard_region(path, lines, regions))
        )
    if engine._rule_enabled("BSL017"):
        rule_tasks.append(
            ("BSL017", lambda: engine._rule_bsl017_export_in_command_module(path, lines, procs))
        )
    if engine._rule_enabled("BSL019"):
        rule_tasks.append(
            ("BSL019", lambda: engine._rule_bsl019_cyclomatic_complexity(path, lines, procs))
        )
    if engine._rule_enabled("BSL020"):
        rule_tasks.append(
            ("BSL020", lambda: engine._rule_bsl020_excessive_nesting(path, lines, procs))
        )
    if engine._rule_enabled("BSL022"):
        rule_tasks.append(
            ("BSL022", lambda: engine._rule_bsl022_deprecated_message(path, lines, procs))
        )
    if engine._rule_enabled("BSL025"):
        rule_tasks.append(("BSL025", lambda: engine._rule_bsl025_empty_statement(path, lines)))
    if engine._rule_enabled("BSL026"):
        rule_tasks.append(
            ("BSL026", lambda: engine._rule_bsl026_empty_region(path, lines, regions))
        )
    if engine._rule_enabled("BSL028"):
        rule_tasks.append(
            ("BSL028", lambda: engine._rule_bsl028_missing_try_catch(path, lines, procs))
        )
    if engine._rule_enabled("BSL029"):
        rule_tasks.append(
            ("BSL029", lambda: engine._rule_bsl029_magic_number(path, lines, procs, snapshot))
        )
    if engine._rule_enabled("BSL031"):
        rule_tasks.append(
            ("BSL031", lambda: engine._rule_bsl031_number_of_params(path, lines, procs))
        )
    if engine._rule_enabled("BSL032"):
        rule_tasks.append(
            ("BSL032", lambda: engine._rule_bsl032_function_return_value(path, lines, procs))
        )
    if engine._rule_enabled("BSL148"):
        rule_tasks.append(
            ("BSL148", lambda: engine._rule_bsl148_all_function_paths_return(path, tree))
        )
    if engine._rule_enabled("BSL033"):
        rule_tasks.append(
            ("BSL033", lambda: engine._rule_bsl033_query_in_loop(path, lines, procs, tree))
        )
    if engine._rule_enabled("BSL035"):
        rule_tasks.append(
            (
                "BSL035",
                lambda: engine._rule_bsl035_duplicate_string_literal(path, lines, procs, snapshot),
            )
        )
    if engine._rule_enabled("BSL036"):
        rule_tasks.append(("BSL036", lambda: engine._rule_bsl036_complex_condition(path, lines)))
    if engine._rule_enabled("BSL040"):
        rule_tasks.append(
            ("BSL040", lambda: engine._rule_bsl040_using_this_form(path, lines, procs))
        )
    if engine._rule_enabled("BSL042"):
        rule_tasks.append(
            ("BSL042", lambda: engine._rule_bsl042_empty_export_method(path, lines, procs))
        )
    if engine._rule_enabled("BSL051"):
        rule_tasks.append(
            ("BSL051", lambda: engine._rule_bsl051_unreachable_code(path, lines, procs, tree))
        )
    if engine._rule_enabled("BSL052"):
        rule_tasks.append(
            ("BSL052", lambda: engine._rule_bsl052_useless_condition(path, lines, tree))
        )
    if engine._rule_enabled("BSL054"):
        rule_tasks.append(
            (
                "BSL054",
                lambda: engine._rule_bsl054_module_level_variable(path, lines, procs, snapshot),
            )
        )
    if engine._rule_enabled("BSL219"):
        rule_tasks.append(
            (
                "BSL219",
                lambda: engine._rule_bsl219_missing_variables_description(
                    path, lines, procs, snapshot
                ),
            )
        )
    if engine._rule_enabled("BSL060"):
        rule_tasks.append(
            ("BSL060", lambda: engine._rule_bsl060_double_negation(path, lines, tree))
        )
    if engine._rule_enabled("BSL062"):
        rule_tasks.append(
            (
                "BSL062",
                lambda: engine._rule_bsl062_unused_parameter(
                    path, lines, procs, tree, proc_node_map
                ),
            )
        )
    if engine._rule_enabled("BSL064"):
        rule_tasks.append(
            ("BSL064", lambda: engine._rule_bsl064_procedure_returns_value(path, lines, procs))
        )
    if engine._rule_enabled("BSL065"):
        rule_tasks.append(
            ("BSL065", lambda: engine._rule_bsl065_missing_export_comment(path, lines, procs))
        )
    if engine._rule_enabled("BSL066"):
        rule_tasks.append(
            ("BSL066", lambda: engine._rule_bsl066_deprecated_platform_method(path, lines, procs))
        )
