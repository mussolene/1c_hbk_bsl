#!/usr/bin/env bash
# Build Python release distributions with matching meta/core package metadata.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-./.venv/bin/python}"
VERSION="${1:-}"
OUT_DIR="${2:-dist}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 VERSION [OUT_DIR]" >&2
    exit 1
fi

VERSION="${VERSION#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Release version must be MAJOR.MINOR.PATCH, got: $VERSION" >&2
    exit 1
fi

if [[ "$PYTHON" != */* ]]; then
    PYTHON_FOUND="$(command -v "$PYTHON" 2>/dev/null || true)"
else
    PYTHON_FOUND="$PYTHON"
fi
if [[ -z "$PYTHON_FOUND" || ( "$PYTHON" == */* && ! -x "$PYTHON" ) ]]; then
    echo "Missing project Python runtime: $PYTHON" >&2
    echo "Create or repair .venv, or set PYTHON explicitly in a controlled build environment." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

META_PYPROJECT="packages/onec-hbk-bsl/pyproject.toml"
META_PYPROJECT_BACKUP="$(mktemp /tmp/onec-hbk-bsl-meta-pyproject.XXXXXX)"
cp "$META_PYPROJECT" "$META_PYPROJECT_BACKUP"
restore_meta_pyproject() {
    cp "$META_PYPROJECT_BACKUP" "$META_PYPROJECT"
    rm -f "$META_PYPROJECT_BACKUP"
}
trap restore_meta_pyproject EXIT

export SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION"
"$PYTHON" -m build --outdir "$OUT_DIR"

"$PYTHON" - "$VERSION" "$META_PYPROJECT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

version = sys.argv[1]
path = Path(sys.argv[2])
text = path.read_text(encoding="utf-8")
replacements = {
    '"onec-hbk-bsl-core[mcp]",': f'"onec-hbk-bsl-core[mcp]=={version}",',
    '"onec-hbk-bsl-core[all]",': f'"onec-hbk-bsl-core[all]=={version}",',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing meta dependency placeholder: {old}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
PY

"$PYTHON" -m build packages/onec-hbk-bsl --outdir "$OUT_DIR"
restore_meta_pyproject
trap - EXIT

"$PYTHON" - "$VERSION" "$OUT_DIR" <<'PY'
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

version = sys.argv[1]
out_dir = Path(sys.argv[2])
meta_wheels = sorted(out_dir.glob(f"onec_hbk_bsl-{version}-*.whl"))
if not meta_wheels:
    raise SystemExit(f"meta wheel not found for {version} in {out_dir}")
wheel = meta_wheels[-1]
with zipfile.ZipFile(wheel) as archive:
    metadata_name = next(
        name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
    )
    metadata = archive.read(metadata_name).decode("utf-8")
required = [
    f"Requires-Dist: onec-hbk-bsl-core[mcp]=={version}",
    f"Requires-Dist: onec-hbk-bsl-core[all]=={version}; extra ==",
]
missing = [line for line in required if line not in metadata]
if missing:
    raise SystemExit(
        "meta package does not pin matching core dependency: " + ", ".join(missing)
    )
PY

"$PYTHON" -m twine check "$OUT_DIR"/*
