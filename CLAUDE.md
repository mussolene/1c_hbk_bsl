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
