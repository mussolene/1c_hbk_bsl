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
    if engine._rule_enabled("BSL005"):
        rule_tasks.append(
            ("BSL005", lambda: engine._rule_bsl005_hardcode_network_address(path, lines))
        )
    if engine._rule_enabled("BSL006"):
        rule_tasks.append(("BSL006", lambda: engine._rule_bsl006_hardcode_path(path, lines)))
    if engine._rule_enabled("BSL007"):
        rule_tasks.append(
            ("BSL007", lambda: engine._rule_bsl007_unused_local_variable(path, lines, procs))
        )
    if engine._rule_enabled("BSL008"):
        rule_tasks.append(
            ("BSL008", lambda: engine._rule_bsl008_too_many_returns(path, lines, procs))
        )
    if engine._rule_enabled("BSL009"):
        rule_tasks.append(("BSL009", lambda: engine._rule_bsl009_self_assign(path, lines, tree)))
    if engine._rule_enabled("BSL010"):
        rule_tasks.append(
            ("BSL010", lambda: engine._rule_bsl010_useless_return(path, lines, procs))
        )
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
    if engine._rule_enabled("BSL018"):
        rule_tasks.append(
            ("BSL018", lambda: engine._rule_bsl018_raise_with_literal(path, lines, tree))
        )
    if engine._rule_enabled("BSL019"):
        rule_tasks.append(
            ("BSL019", lambda: engine._rule_bsl019_cyclomatic_complexity(path, lines, procs))
        )
    if engine._rule_enabled("BSL020"):
        rule_tasks.append(
            ("BSL020", lambda: engine._rule_bsl020_excessive_nesting(path, lines, procs))
        )
    if engine._rule_enabled("BSL021"):
        rule_tasks.append(
            ("BSL021", lambda: engine._rule_bsl021_unused_val_parameter(path, lines, procs))
        )
    if engine._rule_enabled("BSL022"):
        rule_tasks.append(
            ("BSL022", lambda: engine._rule_bsl022_deprecated_message(path, lines, procs))
        )
    if engine._rule_enabled("BSL023"):
        rule_tasks.append(("BSL023", lambda: engine._rule_bsl023_service_tag(path, lines)))
    if engine._rule_enabled("BSL025"):
        rule_tasks.append(("BSL025", lambda: engine._rule_bsl025_empty_statement(path, lines)))
    if engine._rule_enabled("BSL026"):
        rule_tasks.append(
            ("BSL026", lambda: engine._rule_bsl026_empty_region(path, lines, regions))
        )
    if engine._rule_enabled("BSL027"):
        rule_tasks.append(("BSL027", lambda: engine._rule_bsl027_use_goto(path, lines)))
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
    if engine._rule_enabled("BSL034"):
        rule_tasks.append(
            ("BSL034", lambda: engine._rule_bsl034_unused_error_variable(path, lines, procs))
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
    if engine._rule_enabled("BSL037"):
        rule_tasks.append(
            ("BSL037", lambda: engine._rule_bsl037_override_builtin(path, lines, procs))
        )
    if engine._rule_enabled("BSL038"):
        rule_tasks.append(
            ("BSL038", lambda: engine._rule_bsl038_string_concat_in_loop(path, lines, procs, tree))
        )
    if engine._rule_enabled("BSL039"):
        rule_tasks.append(("BSL039", lambda: engine._rule_bsl039_nested_ternary(path, lines)))
    if engine._rule_enabled("BSL040"):
        rule_tasks.append(
            ("BSL040", lambda: engine._rule_bsl040_using_this_form(path, lines, procs))
        )
    if engine._rule_enabled("BSL041"):
        rule_tasks.append(("BSL041", lambda: engine._rule_bsl041_deprecated_message(path, lines)))
    if engine._rule_enabled("BSL042"):
        rule_tasks.append(
            ("BSL042", lambda: engine._rule_bsl042_empty_export_method(path, lines, procs))
        )
    if engine._rule_enabled("BSL043"):
        rule_tasks.append(
            ("BSL043", lambda: engine._rule_bsl043_too_many_variables(path, lines, procs))
        )
    if engine._rule_enabled("BSL044"):
        rule_tasks.append(
            ("BSL044", lambda: engine._rule_bsl044_function_no_return_value(path, lines, procs))
        )
    if engine._rule_enabled("BSL045"):
        rule_tasks.append(
            ("BSL045", lambda: engine._rule_bsl045_multiline_string_literal(path, lines))
        )
    if engine._rule_enabled("BSL046"):
        rule_tasks.append(
            ("BSL046", lambda: engine._rule_bsl046_missing_else_branch(path, lines, procs))
        )
    if engine._rule_enabled("BSL047"):
        rule_tasks.append(("BSL047", lambda: engine._rule_bsl047_current_date(path, lines)))
    if engine._rule_enabled("BSL048"):
        rule_tasks.append(("BSL048", lambda: engine._rule_bsl048_empty_file(path, lines)))
    if engine._rule_enabled("BSL049"):
        rule_tasks.append(
            ("BSL049", lambda: engine._rule_bsl049_unconditional_raise(path, lines, procs))
        )
    if engine._rule_enabled("BSL050"):
        rule_tasks.append(
            ("BSL050", lambda: engine._rule_bsl050_large_transaction(path, lines, procs))
        )
    if engine._rule_enabled("BSL051"):
        rule_tasks.append(
            ("BSL051", lambda: engine._rule_bsl051_unreachable_code(path, lines, procs, tree))
        )
    if engine._rule_enabled("BSL052"):
        rule_tasks.append(
            ("BSL052", lambda: engine._rule_bsl052_useless_condition(path, lines, tree))
        )
    if engine._rule_enabled("BSL053"):
        rule_tasks.append(("BSL053", lambda: engine._rule_bsl053_execute_dynamic(path, lines)))
    if engine._rule_enabled("BSL054"):
        rule_tasks.append(
            ("BSL054", lambda: engine._rule_bsl054_module_level_variable(path, lines, procs))
        )
    if engine._rule_enabled("BSL219"):
        rule_tasks.append(
            (
                "BSL219",
                lambda: engine._rule_bsl219_missing_variables_description(path, lines, procs),
            )
        )
    if engine._rule_enabled("BSL055"):
        rule_tasks.append(
            ("BSL055", lambda: engine._rule_bsl055_consecutive_blank_lines(path, lines, snapshot))
        )
    if engine._rule_enabled("BSL056"):
        rule_tasks.append(
            ("BSL056", lambda: engine._rule_bsl056_short_method_name(path, lines, procs))
        )
    if engine._rule_enabled("BSL057"):
        rule_tasks.append(
            ("BSL057", lambda: engine._rule_bsl057_deprecated_input_dialog(path, lines))
        )
    if engine._rule_enabled("BSL058"):
        rule_tasks.append(("BSL058", lambda: engine._rule_bsl058_query_without_where(path, lines)))
    if engine._rule_enabled("BSL059"):
        rule_tasks.append(
            ("BSL059", lambda: engine._rule_bsl059_bool_literal_comparison(path, lines, tree))
        )
    if engine._rule_enabled("BSL060"):
        rule_tasks.append(
            ("BSL060", lambda: engine._rule_bsl060_double_negation(path, lines, tree))
        )
    if engine._rule_enabled("BSL061"):
        rule_tasks.append(
            ("BSL061", lambda: engine._rule_bsl061_abrupt_loop_exit(path, lines, tree))
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
    if engine._rule_enabled("BSL063"):
        rule_tasks.append(("BSL063", lambda: engine._rule_bsl063_large_module(path, lines)))
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
    if engine._rule_enabled("BSL067"):
        rule_tasks.append(
            ("BSL067", lambda: engine._rule_bsl067_var_after_code(path, lines, procs))
        )
    if engine._rule_enabled("BSL068"):
        rule_tasks.append(("BSL068", lambda: engine._rule_bsl068_too_many_elseif(path, lines)))
    if engine._rule_enabled("BSL069"):
        rule_tasks.append(("BSL069", lambda: engine._rule_bsl069_infinite_loop(path, lines)))
    if engine._rule_enabled("BSL070"):
        rule_tasks.append(
            ("BSL070", lambda: engine._rule_bsl070_empty_loop_body(path, lines, tree))
        )
    if engine._rule_enabled("BSL071"):
        rule_tasks.append(("BSL071", lambda: engine._rule_bsl071_magic_number(path, lines, procs)))
    if engine._rule_enabled("BSL072"):
        rule_tasks.append(
            ("BSL072", lambda: engine._rule_bsl072_string_concat_in_loop(path, lines))
        )
    if engine._rule_enabled("BSL073"):
        rule_tasks.append(("BSL073", lambda: engine._rule_bsl073_missing_else_branch(path, lines)))
    if engine._rule_enabled("BSL074"):
        rule_tasks.append(("BSL074", lambda: engine._rule_bsl074_todo_comment(path, lines)))
    if engine._rule_enabled("BSL075"):
        rule_tasks.append(
            ("BSL075", lambda: engine._rule_bsl075_global_variable_modification(path, lines, procs))
        )
    if engine._rule_enabled("BSL076"):
        rule_tasks.append(
            ("BSL076", lambda: engine._rule_bsl076_negative_condition_first(path, lines))
        )
    if engine._rule_enabled("BSL078"):
        rule_tasks.append(
            ("BSL078", lambda: engine._rule_bsl078_raise_without_message(path, lines))
        )
    if engine._rule_enabled("BSL079"):
        rule_tasks.append(("BSL079", lambda: engine._rule_bsl079_using_goto(path, lines)))
    if engine._rule_enabled("BSL080"):
        rule_tasks.append(("BSL080", lambda: engine._rule_bsl080_silent_catch(path, lines)))
    if engine._rule_enabled("BSL081"):
        rule_tasks.append(("BSL081", lambda: engine._rule_bsl081_long_method_chain(path, lines)))
    if engine._rule_enabled("BSL082"):
        rule_tasks.append(
            ("BSL082", lambda: engine._rule_bsl082_missing_newline_at_eof(path, lines))
        )
    if engine._rule_enabled("BSL083"):
        rule_tasks.append(
            ("BSL083", lambda: engine._rule_bsl083_too_many_module_variables(path, lines, procs))
        )
    if engine._rule_enabled("BSL084"):
        rule_tasks.append(
            ("BSL084", lambda: engine._rule_bsl084_function_with_no_return(path, lines, procs))
        )
    if engine._rule_enabled("BSL085"):
        rule_tasks.append(
            ("BSL085", lambda: engine._rule_bsl085_literal_boolean_condition(path, lines, tree))
        )
    if engine._rule_enabled("BSL086"):
        rule_tasks.append(("BSL086", lambda: engine._rule_bsl086_http_request_in_loop(path, lines)))
    if engine._rule_enabled("BSL087"):
        rule_tasks.append(
            ("BSL087", lambda: engine._rule_bsl087_object_creation_in_loop(path, lines))
        )
    if engine._rule_enabled("BSL088"):
        rule_tasks.append(
            ("BSL088", lambda: engine._rule_bsl088_missing_parameter_comment(path, lines, procs))
        )
