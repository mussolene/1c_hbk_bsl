# OACS Development Workflow

This repository uses OACS/ACS for durable agent memory, context, and evidence.
OACS records what happened; it does not choose or schedule commands.

## Floating Context Standard

Use floating context for all substantial work. Chat history is not the durable
working set and must not be replayed into prompts, subagents, memory, or
evidence as a full transcript.

The active context is a compact OACS capsule assembled from:

- ACS memory query results relevant to the current task.
- ACS context build output for the current intent.
- Current repository state from focused commands such as `git status`, `rg`,
  `sed`, targeted tests, and optional external oracle runs.
- Compact evidence references: `ev_...` ids, report paths, command labels, and
  summaries, not raw logs unless needed for a specific failure.

The capsule should contain only:

- `objective`: current task in one or two sentences.
- `constraints`: user constraints, safety limits, and resource limits.
- `decisions`: durable choices already made and why they matter.
- `state`: touched files, current verification status, and known artifacts.
- `risks`: unresolved mismatches, failing checks, or assumptions.
- `next`: the next concrete action.

Do not include full chat history, large command outputs, full parity JSON,
complete source files, credentials, license data, platform archives, OACS DB
files, or unrelated local paths. Store large raw outputs as artifacts and refer
to their paths or ACS evidence ids.

After chat compaction, interruption, resume, or handoff:

```bash
acs memory query --query "<task intent>" --scope project --json
acs context build --intent "<task intent>" --scope project --json
acs resume --scope project --json
git status --short
```

Then verify the current repo/runtime state with focused commands before making
claims. Treat chat summaries as hints only.

Subagents receive bounded capsules, not the full conversation. A subagent
request should include objective, constraints, owned files or read scope,
evidence/artifact references, and expected compact output. Subagent responses
should be distilled into ACS evidence or memory when they affect future work.

## Setup

```bash
export OACS_DB="$PWD/.agent/oacs/oacs.db"
export OACS_PASSPHRASE="<local-passphrase>"
acs init --project --json
acs status --json
```

`acs status` discovers `OACS_DB`, then `.agent/oacs/oacs.db`, then
`.oacs/oacs.db`.

## Start A Task

```bash
acs memory query --query "<task intent>" --scope project --json
acs context build --intent "<task intent>" --scope project --json
```

Keep task acceptance criteria in the conversation or in normal project docs.
Do not create a parallel proof-loop task tree for new work.

## Record Evidence

Use `acs run` when ACS should execute and record a command:

```bash
acs run --label "ruff" -- ruff check src tests
acs run --label "pytest" -- env PYTHONPATH=src ./.venv/bin/python -m pytest -q
acs run --label "targeted diagnostics" -- env PYTHONPATH=src python -m onec_hbk_bsl check tests/fixtures --format json --exit-zero
```

Use `acs tool ingest-result` when a tool has already run and you need to record
its result. Inspect evidence with:

```bash
acs evidence list --kind tool_result --json
acs evidence inspect <ev_...> --json
```

## Checkpoints And Resume

```bash
acs checkpoint add --task "<task intent>" \
  --summary "Implemented formatter CLI and oracle parity smoke" \
  --next "Run full verification" \
  --evidence ev_... \
  --json

acs resume --scope project --json
```

Checkpoints are task traces, not reusable facts. Use memory only for durable
facts, procedures, rules, and reusable project patterns.

## Durable Memory

When evidence should become reusable project knowledge:

```bash
MEM_ID=$(acs memory propose --type procedure --depth 2 --scope project \
  --text "External oracle diagnostics are run outside the product package and recorded as OACS evidence with artifact paths and summaries." \
  --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
acs memory commit "$MEM_ID" --json
acs memory sharpen "$MEM_ID" <ev_...> --json
```

Do not store credentials, license data, OACS DB files, platform archives, full
help dumps, or unrelated local host paths in memory or evidence.

## Verification Closeout

Before claiming completion, record current verification:

```bash
acs run --label "lint" -- ruff check src tests
acs run --label "tests" -- env PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

If a check fails, apply the smallest safe fix and rerun the failing check.
Before commits, inspect staged changes and run a leak/secret review appropriate
for the changed files.
