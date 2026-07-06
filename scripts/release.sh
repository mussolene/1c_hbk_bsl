#!/usr/bin/env bash
# Create and publish a release tag after local verification.
#
# Usage:
#   ./scripts/release.sh 0.8.24 ["release: v0.8.24"]
#
# The tag is the release source of truth. CI derives Python, binary, and VSIX
# versions from that tag while building artifacts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-./.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    echo "Missing project Python runtime: $PYTHON" >&2
    echo "Create or repair .venv before releasing." >&2
    exit 1
fi

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 VERSION [RELEASE_MESSAGE]" >&2
    exit 1
fi

VERSION="${VERSION#v}"
TAG="v${VERSION}"
MESSAGE="${2:-release: ${TAG}}"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Release version must be MAJOR.MINOR.PATCH, got: $VERSION" >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree must be clean before creating a release tag." >&2
    git status --short >&2
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Tag already exists locally: $TAG" >&2
    exit 1
fi

echo "==> Verify Python"
"$PYTHON" -m ruff check src tests scripts
"$PYTHON" -m ruff format --check src tests scripts
"$PYTHON" -m pytest -q

echo "==> Verify VS Code extension"
(
    cd vscode-extension
    env -u npm_config_devdir -u NPM_CONFIG_DEVDIR npm ci
    env -u npm_config_devdir -u NPM_CONFIG_DEVDIR npm run typecheck
    env -u npm_config_devdir -u NPM_CONFIG_DEVDIR npm run compile
)

echo "==> Build Python distributions as ${VERSION}"
TMP_DIST="$(mktemp -d /tmp/onec-hbk-bsl-release.XXXXXX)"
export SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION"
"$PYTHON" -m build --outdir "$TMP_DIST"

META_PYPROJECT="packages/onec-hbk-bsl/pyproject.toml"
META_PYPROJECT_BACKUP="$(mktemp /tmp/onec-hbk-bsl-meta-pyproject.XXXXXX)"
cp "$META_PYPROJECT" "$META_PYPROJECT_BACKUP"
restore_meta_pyproject() {
    cp "$META_PYPROJECT_BACKUP" "$META_PYPROJECT"
    rm -f "$META_PYPROJECT_BACKUP"
}
trap restore_meta_pyproject EXIT
"$PYTHON" - "$VERSION" "$META_PYPROJECT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

version = sys.argv[1]
path = Path(sys.argv[2])
text = path.read_text(encoding="utf-8")
text = text.replace('"onec-hbk-bsl-core[mcp]",', f'"onec-hbk-bsl-core[mcp]=={version}",')
text = text.replace('"onec-hbk-bsl-core[all]",', f'"onec-hbk-bsl-core[all]=={version}",')
path.write_text(text, encoding="utf-8")
PY
"$PYTHON" -m build packages/onec-hbk-bsl --outdir "$TMP_DIST"
restore_meta_pyproject
trap - EXIT
"$PYTHON" -m twine check "$TMP_DIST"/*

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Verification changed tracked files; refusing to tag a dirty tree." >&2
    git status --short >&2
    exit 1
fi

echo "==> Create tag ${TAG}"
git tag -a "$TAG" -m "$MESSAGE"

echo "==> Push main and ${TAG}"
git push origin main "$TAG"

echo "Released ${TAG}. CI will build and publish artifacts from the tag."
