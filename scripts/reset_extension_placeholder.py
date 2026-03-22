#!/usr/bin/env python3
"""
Set ``vscode-extension/package.json`` ``version`` to the repo placeholder (0.0.0)
and refresh ``package-lock.json`` root.

Called automatically at the end of ``make vsix`` so local builds do not leave
real scm versions committed in package manifests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
PLACEHOLDER = "0.0.0"


def main() -> int:
    pkg_path = EXT / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    old = pkg.get("version")
    if old == PLACEHOLDER:
        return 0
    pkg["version"] = PLACEHOLDER
    pkg_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"vscode-extension/package.json: {old!r} → {PLACEHOLDER!r} (placeholder)")

    r = subprocess.run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts"],
        cwd=str(EXT),
        check=False,
    )
    if r.returncode != 0:
        print("npm install --package-lock-only failed", file=sys.stderr)
        return r.returncode
    print("vscode-extension/package-lock.json: root version reset to placeholder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
