## OACS Repo Workflow

Use OACS/ACS as the durable project memory, context, and evidence surface for
substantial work in this repository.

Start long-running tasks by setting repo-local ACS state:

```bash
export OACS_DB="$PWD/.agent/oacs/oacs.db" OACS_PASSPHRASE="<local-passphrase>"
acs memory query --query "<task intent>" --scope project --json
acs context build --intent "<task intent>" --scope project --json
```

Record command outputs, Docker checks, BSLLS oracle runs, and verification
results as OACS evidence using `acs run` or `acs tool ingest-result`. Use
`acs checkpoint add` to record iteration state and `acs resume --scope project
--json` after context compaction or task resume.

Todo/task UI is session-only. The durable proof surface is ACS evidence,
checkpoints, and committed memories, not `repo-task-proof-loop` files.

Use floating context by default. Do not paste, forward, ingest, or replay the
full chat transcript. Keep a compact OACS capsule containing only the current
objective, constraints, decisions, touched files, evidence ids or artifact
paths, open risks, and next action. After compaction, interruption, resume, or
subagent handoff, rebuild context from ACS memory/context plus current
repository state; treat chat summaries as hints until confirmed.

Treat old `repo-task-proof-loop`, `.agent/tasks/<TASK_ID>`, `evidence.md`,
`evidence.json`, `verdict.json`, and `problems.md` workflow instructions as
stale compatibility artifacts unless a user explicitly asks to inspect old
history.

Hard rules:

- Do not claim completion unless every acceptance criterion is `PASS`.
- Current code and current command results are the source of truth.
- Verifiers judge current repository state and current command results, not
  prior chat claims.
- Fixes should be the smallest defensible diff.
- Keep secrets, credentials, license data, OACS DB files, and local-only
  sensitive paths out of memory, evidence, and committed files.

See `docs/oacs-development.md` for repository-specific command examples.
