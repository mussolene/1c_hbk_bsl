## OACS / ACS Repository Workflow

Use OACS/ACS for substantial repository work as the governed local context,
evidence, and checkpoint layer. OACS records facts and proof; it does not choose
or run tools for the assistant.

Required loop:

1. State scope and acceptance criteria before implementation.
2. Build context through OACS:
   `acs context build --intent repo_development --scope project --json`.
3. Record canonical command results as evidence with
   `acs tool ingest-result ...`.
4. Inspect evidence with `acs evidence inspect <ev_...> --json` when debugging
   or proving completion.
5. Distill only reviewed evidence-backed facts/procedures into durable memory.
6. Add an OACS checkpoint with evidence refs and next step after each iteration.
7. Run fresh verification and leak/secret checks before finalizing.

Completion bar:

- All acceptance criteria are satisfied.
- Verification is current and passing.
- OACS evidence exists for important command outputs.
- A checkpoint records the outcome and next step.
- OACS context build was run for the iteration.
- No `.agent/oacs/key.json`, `.agent/oacs/unlocked.key`, `.agent/oacs`,
  `.oacs`, keys, passphrases, local databases, or private agent state are read,
  printed, or committed.

See `docs/oacs-development.md` for repository-specific command examples.

## Maintainer-facing explainer docs (`docs/contrib_tmp/`)

When a fix is non-trivial and the maintainer/upstream author needs a
write-up to review it (not project documentation, not a `tmp/` working
note), put it in `docs/contrib_tmp/`. That directory is gitignored — it
exists so these files can be drafted, read, and copy-pasted into a PR
description or message, but can never end up committed or merged by
accident. Every file placed there must open with a short blockquote
noting it explains a change to the maintainer and is not part of the
project docs (see any existing file in `docs/contrib_tmp/` for the exact
wording). Do not remove `docs/contrib_tmp/` from `.gitignore`.
