from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def _load_script_module(name: str):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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


def test_bslls_oracle_parity_rule_filter_accepts_code_and_name() -> None:
    bslls_oracle_parity = _load_script_module("bslls_oracle_parity")

    by_code = bslls_oracle_parity._rule_filter_codes(["BSL265"])
    by_name = bslls_oracle_parity._rule_filter_codes(["UselessTernaryOperator"])
    unknown = bslls_oracle_parity._unknown_rule_filter_tokens(["BSL265,UselessTernaryOperator"])

    assert by_code == {"BSL265"}
    assert by_name == {"BSL265"}
    assert unknown == []


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
