#!/usr/bin/env bash
# scripts/release.sh VERSION [MESSAGE]
# Example: ./scripts/release.sh 0.7.12 "BSL149 fix, adaptive debounce"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── args ──────────────────────────────────────────────────────────────────────
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 VERSION [RELEASE_MESSAGE]" >&2
    exit 1
fi
# Strip leading 'v' for package.json; keep bare version
VERSION="${VERSION#v}"
TAG="v${VERSION}"
MESSAGE="${2:-release: ${TAG}}"

echo "==> Release ${TAG}: ${MESSAGE}"

# ── 1. tests ──────────────────────────────────────────────────────────────────
echo "==> Tests"
python -m pytest tests/ -q --no-cov --tb=short 2>&1 | tail -6
# Fail if any test failed (pytest exits non-zero on failure; set -e catches it)

# ── 2. lint ───────────────────────────────────────────────────────────────────
echo "==> Lint"
python -m ruff check src/ tests/ 2>&1 | tail -5

# ── 3. bump vscode-extension/package.json ────────────────────────────────────
echo "==> Bump vscode-extension to ${VERSION}"
PKG="vscode-extension/package.json"
# Use python for portable in-place JSON edit (no jq dependency)
python - "$PKG" "$VERSION" <<'PY'
import json, sys
path, ver = sys.argv[1], sys.argv[2]
pkg = json.loads(open(path).read())
print(f"  {pkg['version']} -> {ver}")
pkg["version"] = ver
open(path, "w").write(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n")
PY

# ── 4. build VSIX ─────────────────────────────────────────────────────────────
echo "==> npm package:vsix"
cd vscode-extension
npm run package:vsix 2>&1 | tail -3
cd "$ROOT"

VSIX="$ROOT/vscode-extension/1c-hbk-bsl-${VERSION}.vsix"
if [[ ! -f "$VSIX" ]]; then
    echo "ERROR: VSIX not found at $VSIX" >&2
    exit 1
fi

# ── 5. install in VSCode ──────────────────────────────────────────────────────
echo "==> Install VSIX"
code --install-extension "$VSIX" --force 2>&1 | tail -2

# ── 6. commit ─────────────────────────────────────────────────────────────────
echo "==> Commit"
git add "$PKG"
# Commit message via ollama if available, else use MESSAGE
if command -v ot &>/dev/null; then
    COMMIT_MSG="$(git diff --cached --stat | ot "write concise commit message for: ${MESSAGE}")"
else
    COMMIT_MSG="chore(release): bump vscode-extension to ${TAG}"
fi
git commit -m "${COMMIT_MSG}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# ── 7. tag ────────────────────────────────────────────────────────────────────
echo "==> Tag ${TAG}"
git tag -a "${TAG}" -m "${MESSAGE}"

# ── 8. push ───────────────────────────────────────────────────────────────────
echo "==> Push"
git push origin main
git push origin "${TAG}"

echo ""
echo "Released ${TAG} successfully."
