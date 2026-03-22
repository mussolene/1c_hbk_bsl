"""Committed baseline fixture: compare_diag_baseline.py must exit 0 (parity gate)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_committed_diag_baseline_matches() -> None:
    repo = Path(__file__).resolve().parents[1]
    fix = repo / "tests/fixtures/diag_baseline"
    script = repo / "scripts/compare_diag_baseline.py"
    env = dict(os.environ)
    env["BSL_SELECT"] = "BSL009,BSL059"
    env["PYTHONPATH"] = str(repo / "src")
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--baseline",
            str(fix / "baseline.json"),
            "--workspace",
            str(fix),
            "--files",
            "sample.bsl",
        ],
        cwd=str(fix),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
