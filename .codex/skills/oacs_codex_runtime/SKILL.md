---
name: codex-oacs-runtime
description: Use when Codex should work on a repository with OACS-backed development memory: build repo context, record command results as evidence, checkpoint iterations, capture D1 repo episodes, coordinate explicitly requested subagents through one shared OACS database, and close subagents when their goals are done.
---

# Codex OACS Runtime

This is a non-standard optional implementation/dogfood layer. It combines the
existing repo development memory adapter with an OACS-aware Codex runtime
workflow. It shows how repository development memory can live as a removable
skill layer without making Codex, Python, SQLite, or this workflow part of the
OACS portable standard.

Treat Codex chat history as a cache. Treat repository files, git state, OACS
evidence, OACS memory, OACS audit, and OACS checkpoints as the source of truth.
OACS is the standard/contract layer; Python `acs` CLI/API/SQLite behavior is a
reference implementation and must not be described as the standard itself.

## Script Actions

The `skill.json` entrypoint keeps the repo-local script adapter:

- `context`: build a repo-scoped Context Capsule.
- `capture`: commit a manual D1 repository episode.
- `auto_start`: build context and audit metadata without writing memory.
- `auto_finish`: commit a D1 repository episode for the completed iteration.
- `autorun`: build context, run a bounded local command, and commit a D1
  repository episode with command outcome metadata.

Policy:

- Auto mode commits only D1 `episode` memory.
- D2 facts, D2 procedures, rules, and D3-D5 patterns require explicit review
  through `memory propose`, `memory commit`, and `memory sharpen`.
- Standalone tool-result evidence does not enter context by itself; attach the
  evidence ref to reviewed memory if it should guide future context builds.
- Preserve attribution when distilling memory: user instructions, agent
  decisions, tool observations, project policies, and human approvals are
  different roles in the standard and should not be collapsed into plain text.
- In strict policy mode, the actor running this skill needs ordinary
  `context.build`, `context.explain`, memory, evidence, checkpoint, and audit
  grants; the skill must not rely on `system` bootstrap authority.

## Start or Resume

At the start of substantial work, choose or derive a stable task id. Reuse that
same task id after compaction or in a new chat. If the task id is unknown, list
recent checkpoints and ask the user or infer from current repo/user context
before resuming.

```bash
acs checkpoint list --limit 10 --json
acs context build --intent repo_development --scope project --json
acs checkpoint latest --task "<task-id>" --json
acs evidence list --kind tool_result --json
git status --short
```

Use the result to reconstruct a compact working state:

- task scope and acceptance criteria;
- latest checkpoint and next step;
- relevant memories and evidence refs;
- current repo state and touched files;
- forbidden assumptions and open risks.

Do not rely on prior chat summaries as proof. If a fact matters, prefer OACS
evidence, command output, git state, or repository files.

## Single-Agent Loop

For substantial features, fixes, refactors, release work, or investigations:

1. State explicit scope and `AC1`, `AC2`, ... before implementation.
2. Build fresh OACS context before changing files.
3. Run external tools normally; OACS records results, it does not orchestrate
   them.
4. Ingest canonical command results:

```bash
acs tool ingest-result \
  --tool-id local_verification \
  --tool-name local_verification \
  --tool-type external \
  --status completed \
  --input '{"commands":["ruff check .","mypy oacs","pytest -q"]}' \
  --output '{"status":"PASS","summary":"..."}' \
  --json
```

5. Inspect important evidence when debugging or proving completion:

```bash
acs evidence inspect ev_... --json
acs evidence list --kind tool_result --json
```

6. Record a checkpoint at each completed iteration:

```bash
acs checkpoint add \
  --task "<task-id>" \
  --summary "<what changed and why>" \
  --next "<next step or Release complete>" \
  --evidence ev_... \
  --json
```

7. Only sharpen durable memory from evidence-backed facts. Do not turn hunches,
   chat summaries, or unverified conclusions into D2+ memory.

## Context Assembly Rules

Build a new task capsule when intent changes materially. Keep the prompt-facing
state short; do not paste full histories unless the raw source itself must be
analyzed.

If `context build` emits unreadable-memory warnings, continue with the usable
result by default, but record the warning and run:

```bash
acs memory doctor --json
```

Use `--strict` only when the task is specifically verifying storage health or
release quality.

Context-build warnings are sidecar metadata from the reference implementation,
not fields in the portable `ContextCapsule` standard record.

## Multi-Agent Development

Use subagents only when the user explicitly asks for delegation, parallel agent
work, or subagents. When used, all agents coordinate through the same logical
repository and one parent-selected OACS database.

Codex subagents may run in forked workspaces. Do not assume a relative
`.oacs/oacs.db` path is shared. The parent must pass an absolute `OACS_DB` path
for the shared database in each subagent prompt. If a subagent cannot access the
shared DB, it must return command outputs/checkpoint details to the parent so
the parent can ingest them into the main DB.

Parent responsibilities:

- define the shared task scope and acceptance criteria;
- split work into disjoint ownership areas;
- assign each subagent a bounded task, expected output, and write scope;
- tell each subagent it is not alone in the codebase and must not revert others'
  work;
- require each subagent to record or return evidence refs for canonical command
  results it produced;
- verify returned evidence refs with `acs evidence inspect`; if refs are missing
  or not visible in the parent DB, ingest the subagent's returned command output
  in the parent DB;
- integrate results, run final verification, and write the final checkpoint;
- close each subagent once its bounded goal is done or no longer needed.

Subagent responsibilities:

- build or read OACS context before acting when repo memory matters;
- use the shared OACS DB, not private sidecar notes, for durable facts;
- ingest command results as OACS evidence when results matter;
- checkpoint completed work with evidence refs and next-step notes;
- report changed files, evidence refs, blockers, and residual risks;
- stop after the assigned goal instead of continuing into adjacent work.

Suggested subagent prompt shape:

```text
Task:
Acceptance criteria:
Owned files/modules:
Do not edit:
Required OACS DB/workspace:
If shared DB unavailable, return:
Required evidence to record:
Completion condition:
Close/stop when:
```

When a subagent finishes, the parent should review its changes, inspect returned
evidence refs, ingest any missing canonical results, and close that subagent. Do
not leave idle subagents running as ambient memory.

## Shared Database Protocol

The parent selects the shared OACS database. Prefer an absolute `OACS_DB` value
that all agents can access. Do not rely on relative discovery in forked
workspaces. Do not create per-agent databases for the same task unless
explicitly testing isolation.

Use OACS records for exchange:

- command result -> `acs tool ingest-result` -> `EvidenceRef`;
- iteration state -> `acs checkpoint add`;
- durable project fact -> `acs memory sharpen` with evidence ref;
- degraded storage state -> `acs memory doctor` evidence;
- final proof -> verification evidence + secret/leak scan evidence.

Standalone evidence does not become context by itself. If it should guide future
context builds, create or update reviewed memory with the evidence ref attached
using the available memory lifecycle commands (`memory propose`, `memory commit`,
and `memory sharpen`).

## Completion Bar

Do not claim completion unless:

- every acceptance criterion is satisfied;
- current verification is `PASS`;
- secret/leak review is `PASS` or explicitly reviewed as non-secret sentinel
  matches;
- OACS evidence exists for checks and important command outputs;
- an OACS checkpoint records outcome, evidence refs, and next step;
- all subagents spawned for the task are closed or explicitly handed off.
