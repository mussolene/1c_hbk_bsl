## OACS Repo Workflow

For substantial features, refactors, bug fixes, release work, and documentation
changes in this repository, use OACS/ACS as the durable project memory,
context, and evidence surface.

Required sequence:

1. State the task scope and explicit acceptance criteria (`AC1`, `AC2`, ...)
   before implementation.
2. Export repo-local ACS state before using ACS:
   `export OACS_DB="$PWD/.agent/oacs/oacs.db" OACS_PASSPHRASE="<local-passphrase>"`.
3. Query durable memory first, then build fresh context:
   `acs memory query --query "<task intent>" --scope project --json` and
   `acs context build --intent "<task intent>" --scope project --json`.
4. Treat command outputs, Docker checks, BSLLS oracle results, and runtime
   checks as evidence with `acs run` or `acs tool ingest-result`.
5. If evidence should become durable project knowledge, distill it into memory
   with `acs memory propose`, `acs memory commit`, and `acs memory sharpen`.
6. Run a fresh check against the current repository state and rerun relevant
   checks after fixes.
7. Before every commit, check staged changes and unpushed history for
   non-project information and sensitive data: no local host paths, `.env`,
   OACS DB files, credentials, tokens, license data, platform archives, local
   volumes, or unrelated artifacts.
8. If checks do not pass, explain the problem, apply the smallest safe fix, and
   rerun the checks.

Hard rules:

- Do not claim completion unless every acceptance criterion is `PASS`.
- Current code and current command results are the source of truth, not prior
  chat claims.
- Use floating context by default. Do not replay, paste, ingest, or forward the
  full chat transcript as task context. Keep only a compact OACS capsule:
  current objective, constraints, decisions, touched files, evidence ids or
  artifact paths, open risks, and next action.
- After chat compaction, interruption, resume, or subagent handoff, rebuild
  context from ACS memory/context plus current repository state. Treat chat
  summaries as hints only until confirmed by ACS or fresh repo/runtime checks.
- Subagents receive bounded OACS capsules, not raw conversation history. They
  should return compact findings/evidence suitable for ACS ingestion.
- Fixes should be the smallest defensible diff.
- For long iterative work, do not rely only on chat context or compaction
  summaries. Query ACS at task start, record compact ACS evidence and memory
  after significant repo/runtime decisions, and query ACS plus current
  repo/runtime state after any context compaction or resume before continuing.
- OACS is not the runtime orchestrator. It records memory, context, and
  evidence around commands executed by the agent through normal shell, Docker,
  git, and test tools.
- Treat old `repo-task-proof-loop`, vendored proof-loop skill, and
  `.agent/tasks/<TASK_ID>` workflow instructions as stale compatibility
  artifacts, not active policy.
- Keep secrets out of OACS: no credentials, license data, platform archives,
  full help dumps, or local-only sensitive paths.
- Keep this root `AGENTS.md` lean. Put expanded guidance in docs instead of
  recreating a parallel task-artifact system.

See `docs/oacs-development.md` for repository-specific command examples.
