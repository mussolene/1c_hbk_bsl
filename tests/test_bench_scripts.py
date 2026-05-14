from __future__ import annotations

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

    assert by_code == {"BSL265"}
    assert by_name == {"BSL265"}
