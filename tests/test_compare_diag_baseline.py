"""Tests for scripts/compare_diag_baseline.py key normalization."""
from __future__ import annotations

import json
from pathlib import Path


def test_compare_script_matching(tmp_path: Path) -> None:
    """Baseline and onec agree on a simple BSL012 case."""
    ws = tmp_path / "ws"
    ws.mkdir()
    bsl = ws / "t.bsl"
    bsl.write_text('Пароль = "секрет123";\n', encoding="utf-8")

    baseline = {
        "version": 1,
        "diagnostics": [{"file": "t.bsl", "line": 1, "code": "UsingHardcodeSecretInformation"}],
    }
    base_path = ws / "baseline.json"
    base_path.write_text(json.dumps(baseline), encoding="utf-8")

    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "compare_diag_baseline.py"
    env = dict(**__import__("os").environ)
    env["BSL_SELECT"] = "BSL012"
    env["PYTHONPATH"] = str(repo_root / "src")
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--baseline",
            str(base_path),
            "--workspace",
            str(ws),
            "--files",
            str(bsl),
        ],
        cwd=str(ws),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_compare_script_mismatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    bsl = ws / "t.bsl"
    bsl.write_text("А = 1;\n", encoding="utf-8")

    baseline = {
        "version": 1,
        "diagnostics": [{"file": "t.bsl", "line": 99, "code": "BSL001"}],
    }
    base_path = ws / "baseline.json"
    base_path.write_text(json.dumps(baseline), encoding="utf-8")

    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "compare_diag_baseline.py"
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--baseline",
            str(base_path),
            "--workspace",
            str(ws),
            "--files",
            str(bsl),
        ],
        cwd=str(ws),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
