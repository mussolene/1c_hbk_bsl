# Security audit report (secrets, paths, supply chain)

This document records automated checks run against this repository. Re-run after major changes.

## Git history — secret scanning (Gitleaks)

- **Tool:** [Gitleaks](https://github.com/gitleaks/gitleaks) `detect --source .` with config [`.gitleaks.toml`](../.gitleaks.toml) (allowlists known test fixtures).
- **Scope:** Full git history (all commits).

### Findings

| Result | Detail |
|--------|--------|
| **Real secrets** | None identified. |
| **False positive (before allowlist)** | `tests/test_diagnostics_extended.py` line ~327: a `token = "…"` assignment with a long alphanumeric placeholder triggered `generic-api-key`. This is **intentional** fake input for the `UsingHardcodeSecretInformation` diagnostic tests. |

### Manual history probes

Commands used (no matches in this repo):

- `git log --all -S 'ghp_'`
- `git log --all -S 'BEGIN OPENSSH PRIVATE KEY'`
- `git log --all -S '/Users/'`

## CI secrets

- **VS Marketplace:** `VSCE_PAT` is referenced only as `${{ secrets.VSCE_PAT }}` in [`.github/workflows/release.yml`](../.github/workflows/release.yml) — value is not in the tree.

## History rewrite / rotation (automated audit)

- **Credential rotation:** Not required — no live API keys, PATs, or private keys were found in history (only the test fixture above).
- **filter-repo / BFG:** Not required for the same reason.

## If a real leak is ever found

1. **Rotate** the exposed credential immediately (GitHub PAT, PyPI, VSCE, AWS, etc.), even if you rewrite git history.
2. **Rewrite history** only if needed for a public repo: `git filter-repo` or BFG, then coordinated `force-push` and fork notifications.

## Supply chain

- **GitHub release download (VS Code):** The extension resolves the release tag as `v` + `version` from the installed `package.json`, so the fallback download matches the published VSIX ([`vscode-extension/src/extension.ts`](../vscode-extension/src/extension.ts)).
- **Release asset integrity:** CI does not publish SHA256 sidecar files today. Optional hardening: attach `SHA256SUMS` (or GitHub’s built-in asset checksums) and verify in the client before executing a downloaded binary.
- **Branch protection:** Restrict who can push `v*.*.*` tags and approve `environment: release` deploys in GitHub **Settings → Environments / Rules** (not expressible in-repo).

## Related

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — dependency licenses.
- [DATA_SOURCES.md](DATA_SOURCES.md) — provenance checklist for `data/` (including 1C-related JSON).
