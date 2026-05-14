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

# ── 3. bump project release metadata ─────────────────────────────────────────
echo "==> Bump release metadata to ${VERSION}"
python - "$VERSION" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
ver = sys.argv[1]

for rel in ("vscode-extension/package.json", "vscode-extension/package-lock.json"):
    path = root / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"  {rel}: {data['version']} -> {ver}")
    data["version"] = ver
    if rel.endswith("package-lock.json"):
        data["packages"][""]["version"] = ver
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

(root / "src/onec_hbk_bsl/_version.py").write_text(
    f'"""Generated version metadata for runtime use."""\n\n__version__ = "{ver}"\n',
    encoding="utf-8",
)

subprocess.run(
    ["npm", "install", "--package-lock-only", "--ignore-scripts"],
    cwd=root / "vscode-extension",
    check=True,
)
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
git add vscode-extension/package.json vscode-extension/package-lock.json src/onec_hbk_bsl/_version.py
# Commit message via ollama if available, else use MESSAGE
if command -v ot &>/dev/null; then
    COMMIT_MSG="$(git diff --cached --stat | ot "write concise commit message for: ${MESSAGE}")"
else
    COMMIT_MSG="chore(release): bump vscode-extension to ${TAG}"
fi
git commit -m "${COMMIT_MSG}"

# ── 7. tag ────────────────────────────────────────────────────────────────────
echo "==> Tag ${TAG}"
git tag -a "${TAG}" -m "${MESSAGE}"

# ── 8. push ───────────────────────────────────────────────────────────────────
echo "==> Push"
git push origin main
git push origin "${TAG}"

echo ""
echo "Released ${TAG} successfully."
