#!/usr/bin/env python3
"""Ensure a local cached BSLLS exec.jar exists and print its path."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

CACHE_DIR = Path.home() / ".cache/onec-hbk-bsl/bslls"
LATEST_RELEASE_URL = "https://api.github.com/repos/1c-syntax/bsl-language-server/releases/latest"


def _run(*args: str) -> str:
    proc = subprocess.run(args, check=True, capture_output=True, text=True)
    return proc.stdout


def _latest_release() -> tuple[str, str]:
    raw = _run("curl", "-fsSL", LATEST_RELEASE_URL)
    data = json.loads(raw)
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        if name.endswith("-exec.jar"):
            return name, str(asset["browser_download_url"])
    raise SystemExit("No BSLLS exec.jar asset found in latest release")


def _ensure_cached_jar() -> Path:
    env_path = (os.environ.get("BSLLS_JAR") or "").strip()
    if env_path:
        jar = Path(env_path).expanduser().resolve()
        if jar.is_file():
            return jar
        raise SystemExit(f"BSLLS_JAR does not exist: {jar}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = sorted(CACHE_DIR.glob("*-exec.jar"))
    if cached:
        return cached[-1]

    name, url = _latest_release()
    target = CACHE_DIR / name
    subprocess.run(("curl", "-fL", url, "-o", str(target)), check=True)
    return target.resolve()


def main() -> int:
    jar = _ensure_cached_jar()
    print(jar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
