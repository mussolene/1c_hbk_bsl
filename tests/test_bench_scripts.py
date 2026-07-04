from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path


def _load_script_module(name: str):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_bench_timing_path_for_run_cache_modes() -> None:
    bench_timing = _load_script_module("bench_timing")
    base = "/bench_100.bsl"
    assert bench_timing._path_for_run(base, 1, "hit") == base
    assert bench_timing._path_for_run(base, 1, "miss").startswith(base)
    assert bench_timing._path_for_run(base, 1, "miss") != base


def test_bench_profile_path_for_run_cache_modes() -> None:
    bench_profile = _load_script_module("bench_profile")
    base = "/bench_500.bsl"
    assert bench_profile._path_for_run(base, 2, "hit") == base
    assert bench_profile._path_for_run(base, 2, "miss").startswith(base)
    assert bench_profile._path_for_run(base, 2, "miss") != base


def test_bench_per_rule_external_paths_mode(tmp_path: Path) -> None:
    bench_per_rule = _load_script_module("bench_per_rule")
    module_path = tmp_path / "Module.bsl"
    module_path.write_text(
        "\n".join(
            [
                "Процедура Тест()",
                "    Сообщить(\"ok\");",
                "КонецПроцедуры",
            ]
        ),
        encoding="utf-8",
    )
    paths_file = tmp_path / "paths.txt"
    paths_file.write_text(str(module_path), encoding="utf-8")

    args = bench_per_rule._parse_args(
        [
            f"--paths-from={paths_file}",
            "--runs=1",
            "--top=3",
            "--ignore=BSL001, BSL260",
        ]
    )

    assert args.paths_from == str(paths_file)
    assert args.runs == 1
    assert args.top == 3
    assert bench_per_rule._parse_codes(args.ignore) == {"BSL001", "BSL260"}


def test_dev_corpus_bench_parse_trace_flags() -> None:
    dev_corpus_bench = _load_script_module("dev_corpus_bench")

    args = dev_corpus_bench.parse_args(
        [
            ".",
            "--largest=5",
            "--diagnostics-only",
            "--trace-analysis",
            "--trace-call-sites",
        ]
    )

    assert args.largest == 5
    assert args.diagnostics_only is True
    assert args.trace_analysis is True
    assert args.trace_call_sites is True


def test_dev_corpus_bench_trace_records_missing_types() -> None:
    dev_corpus_bench = _load_script_module("dev_corpus_bench")
    trace = dev_corpus_bench.AnalysisTrace()

    trace.add_walk("runtime", 10)
    trace.add_walk("runtime", 5)
    trace.add_missing_type("method_call")

    assert trace.root_walk_calls == {"runtime": 2}
    assert trace.root_walk_nodes == {"runtime": 15}
    assert trace.ts_nodes_missing_types == {"method_call": 1}


def test_bsl_diagnostic_messages_are_not_english_fallbacks() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "onec_hbk_bsl" / "analysis"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            code: str | None = None
            message: str | None = None
            message_line = getattr(node, "lineno", 0)
            for kw in node.keywords:
                if (
                    kw.arg == "code"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    code = kw.value.value
                elif kw.arg == "message":
                    message_line = getattr(kw.value, "lineno", message_line)
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        message = kw.value.value
                    elif isinstance(kw.value, ast.JoinedStr):
                        message = "".join(
                            part.value
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                            else "{}"
                            for part in kw.value.values
                        )
            if not code or not code.startswith("BSL") or not message:
                continue
            has_latin = any("a" <= char.lower() <= "z" for char in message)
            has_cyrillic = any("\u0400" <= char <= "\u04ff" for char in message)
            if has_latin and not has_cyrillic:
                offenders.append(f"{path.relative_to(root.parent.parent.parent)}:{message_line}")
    assert offenders == []
