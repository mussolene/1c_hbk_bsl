"""Smoke test for scripts/format_compare_bslls.py CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_format_compare_help_exits_zero() -> None:
    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, str(repo / "scripts/format_compare_bslls.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "--fixtures" in out
