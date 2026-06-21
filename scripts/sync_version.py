#!/usr/bin/env python3
"""
Sync release metadata to the git tag version.

The Python package itself is versioned dynamically by setuptools-scm. This script
updates files that must contain literal versions in release artifacts:
``src/onec_hbk_bsl/_version.py`` and VS Code extension manifests.

The version source is intentionally stable: explicit release env first, then the
latest ``v*`` git tag. It does not use setuptools-scm's dirty/dev version because
that string is not what should be written into VSIX/runtime release metadata.

Usage::

    python3 scripts/sync_version.py
    python3 scripts/sync_version.py --runtime-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
PY_VERSION = ROOT / "src" / "onec_hbk_bsl" / "_version.py"
_VERSION_RE = re.compile(r"^v?(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$")


def _normalize_version(raw: str) -> str:
    value = raw.strip()
    if value.startswith("refs/tags/"):
        value = value.removeprefix("refs/tags/")
    match = _VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"unsupported release version: {raw!r}")
    return match.group("version")


def _version_from_env() -> str | None:
    for name in ("SETUPTOOLS_SCM_PRETEND_VERSION", "GITHUB_REF_NAME", "GITHUB_REF"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            return _normalize_version(raw)
        except ValueError:
            if name in {"GITHUB_REF_NAME", "GITHUB_REF"}:
                continue
            raise
    return None


def _version_from_latest_tag() -> str:
    out = subprocess.check_output(
        ["git", "describe", "--tags", "--match", "v*", "--abbrev=0"],
        cwd=str(ROOT),
        text=True,
    ).strip()
    return _normalize_version(out)


def _release_version() -> str:
    return _version_from_env() or _version_from_latest_tag()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="Only refresh src/onec_hbk_bsl/_version.py; do not touch VS Code manifests.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        ver = _release_version()
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        print("failed to resolve release version:", e, file=sys.stderr)
        return 1

    PY_VERSION.write_text(
        f'"""Generated version metadata for runtime use."""\n\n__version__ = "{ver}"\n',
        encoding="utf-8",
    )
    print(f"src/onec_hbk_bsl/_version.py: updated to {ver!r}")

    if args.runtime_only:
        return 0

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
