# Security audit report (secrets, paths, supply chain)

This document records automated checks run against this repository. Re-run after major changes.

## Git history — secret scanning (Gitleaks)

- **Tool:** [Gitleaks](https://github.com/gitleaks/gitleaks) `detect --source . --redact`
  with config
  [`.gitleaks.toml`](https://github.com/mussolene/1c_hbk_bsl/blob/main/.gitleaks.toml)
  (allowlists known test fixtures).
- **Scope:** Full git history (all commits).

For a tracked working-tree snapshot without local `.agent/`, build outputs, or caches:

```bash
tmp=$(mktemp -d)
git archive HEAD | tar -x -C "$tmp"
gitleaks detect --no-git --source "$tmp" --redact --verbose
rm -rf "$tmp"
```

### Findings

| Result | Detail |
|--------|--------|
| **Real secrets** | None identified. |
| **False positive (before allowlist)** | `tests/test_diagnostics_core_snapshot.py::TestBsl012HardcodeCredentials` contains a `token = "…"` assignment with a long alphanumeric placeholder that triggered `generic-api-key`. This is **intentional** fake input for the `UsingHardcodeSecretInformation` diagnostic tests. |

### Manual history probes

Commands used (no matches in this repo):

- `git log --all -S 'ghp_'`
- `git log --all -S 'BEGIN OPENSSH PRIVATE KEY'`
- `git log --all -S '<local path marker>'`

## CI secrets

- **VS Marketplace:** `VSCE_PAT` is referenced only as `${{ secrets.VSCE_PAT }}` in
  [`.github/workflows/release.yml`](https://github.com/mussolene/1c_hbk_bsl/blob/main/.github/workflows/release.yml)
  — value is not in the tree.
- **PyPI:** releases use GitHub OIDC Trusted Publishing from the `pypi` environment in
  [`.github/workflows/release.yml`](https://github.com/mussolene/1c_hbk_bsl/blob/main/.github/workflows/release.yml);
  no PyPI API token is expected in repository secrets.

## History rewrite / rotation

- **Credential rotation:** Not required for automated audit — no live API keys, PATs, or private keys were found in history (only the test fixture above).
- **Purging removed paths from all commits:** Optional. If files were published and later removed from the tree but must disappear from **entire** git history (e.g. internal documentation), use [git-filter-repo](https://github.com/newren/git-filter-repo) after backup:

```bash
# Example: drop specific paths from every commit (adjust paths; then force-push all branches/tags)
git filter-repo --path path/to/file.md --invert-paths
```

Coordinate `force-push`, notify fork owners, and re-clone local checkouts. Purging history **does not** replace rotating credentials if a real secret was exposed.

## If a real leak is ever found

1. **Rotate** the exposed credential immediately (GitHub PAT, PyPI, VSCE, AWS, etc.), even if you rewrite git history.
2. **Rewrite history** only if needed for a public repo: `git filter-repo` or BFG, then coordinated `force-push` and fork notifications.

## Supply chain

- **GitHub release download (VS Code):** The extension resolves the release tag as `v` +
  `version` from the installed `package.json`, so the fallback download matches the
  published VSIX
  ([`vscode-extension/src/extension.ts`](https://github.com/mussolene/1c_hbk_bsl/blob/main/vscode-extension/src/extension.ts)).
- **PyPI release:** The release workflow publishes the same checked wheel/sdist that it attaches to the GitHub Release. Configure PyPI Trusted Publishing for `mussolene/1c_hbk_bsl`, `.github/workflows/release.yml`, environment `pypi` before pushing a release tag.
- **Release asset integrity:** full artifact preflight emits a deterministic
  `SHA256SUMS` for the complete release set before publication. Download
  clients should verify the manifest before executing a binary.
- **Branch protection:** Restrict who can push `v*.*.*` tags and approve `environment: release` deploys in GitHub **Settings → Environments / Rules** (not expressible in-repo).

## Related

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — dependency licenses.
- [DATA_SOURCES.md](DATA_SOURCES.md) — provenance checklist for `data/` (including 1C-related JSON).
