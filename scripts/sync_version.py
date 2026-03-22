#!/usr/bin/env python3
"""
Sync ``vscode-extension/package.json`` (and lockfile) to the **git-based** version.

Uses setuptools-scm (same as the Python package) or ``git describe`` as fallback.
Run from the repo root after tagging, or in CI on a tag checkout.

Usage::

    python scripts/sync_version.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"


def _version_from_scm() -> str:
    try:
        from setuptools_scm import get_version

        return get_version(root=str(ROOT))
    except ImportError as e:
        raise RuntimeError("install setuptools-scm: uv pip install setuptools-scm") from e


def _version_from_git_describe() -> str:
    out = subprocess.check_output(
        ["git", "describe", "--tags", "--match", "v*", "--abbrev=0"],
        cwd=str(ROOT),
        text=True,
    ).strip()
    if out.startswith("v"):
        return out[1:]
    return out


def main() -> int:
    try:
        ver = _version_from_scm()
    except RuntimeError, LookupError:
        try:
            ver = _version_from_git_describe()
        except (OSError, subprocess.CalledProcessError) as e:
            print("setuptools-scm failed and git describe failed:", e, file=sys.stderr)
            return 1

    pkg_path = EXT / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    old = pkg.get("version")
    pkg["version"] = ver
    pkg_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"vscode-extension/package.json: {old!r} → {ver!r}")

    r = subprocess.run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts"],
        cwd=str(EXT),
        check=False,
    )
    if r.returncode != 0:
        print("npm install --package-lock-only failed", file=sys.stderr)
        return r.returncode
    print("vscode-extension/package-lock.json refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
