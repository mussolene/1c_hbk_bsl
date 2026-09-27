## OACS Project Policy

For substantial repository work, use the globally installed `oacs` Skill with
this repository's project memory. Keep current verification, OACS evidence, a
checkpoint, and a leak review as completion requirements. Never read, print,
or commit OACS keys, passphrases, databases, or private agent state. General
retrieval and lifecycle instructions belong to the global Skill; keep only
repository-specific examples in `docs/oacs-development.md`.

## Repository Python runtime

All Python commands in this repository must use the project virtual
environment: `./.venv/bin/python`. Do not use the system `python`, `python3`,
or ad-hoc aliases for tests, diagnostics, scripts, parser probes, packaging, or
release verification.

If `./.venv/bin/python` is missing or broken, stop and repair the project
environment before running Python-based checks. This matters for correctness:
the project `.venv` pins the `tree-sitter-bsl` build that exposes SDBL CST
support used by query diagnostics.
