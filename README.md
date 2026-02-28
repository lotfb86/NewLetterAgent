# Newsletter Agent

AI-powered weekly newsletter system that combines team Slack updates and external AI news, drafts content, runs a feedback loop in Slack, and sends approved issues via Resend.

## Start Here (Required)
1. Read [IMPLEMENTATION_PLAN.md](/Users/jesseanglen/NewLetterAgent/IMPLEMENTATION_PLAN.md).
2. Pick one unchecked task.
3. Claim it in the plan before writing code.
4. After finishing the task, mark it complete in the plan.

If you skip the plan update, the task is not considered done.

## Working Agreement For This Repo

### Task Tracking Is Mandatory
- Every code task must map to an `IMP-###` item in `IMPLEMENTATION_PLAN.md`.
- Before coding, change `Owner: unassigned` to your name/initials and start date.
- When finished, change `[ ]` to `[x]` and add a short completion note.
- If blocked, keep `[ ]` and add a blocker note under that task.

### Branch And Commit Conventions
- Branch format: `codex/<task-id>-<short-name>` (example: `codex/imp-052-schema-repair`).
- Commit prefix: `[IMP-###]` (example: `[IMP-052] Add JSON schema validation loop`).
- Keep pull requests scoped to claimed tasks.

### Definition Of Done
A task is complete only when all are true:
- Code implemented.
- Relevant tests added/updated and passing locally.
- Docs/config updated.
- `IMPLEMENTATION_PLAN.md` updated to `[x]` with note.

## Repository Documents
- Execution plan: [IMPLEMENTATION_PLAN.md](/Users/jesseanglen/NewLetterAgent/IMPLEMENTATION_PLAN.md)
- Product/architecture plan: [PLAN.md](/Users/jesseanglen/NewLetterAgent/PLAN.md)
- Dependency locking: [DEPENDENCY_LOCKING.md](/Users/jesseanglen/NewLetterAgent/DEPENDENCY_LOCKING.md)

## Local Setup (when codebase is scaffolded)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make check
```

## Core Runtime Expectations
- App runs as a long-lived worker (Slack Socket Mode + scheduler).
- Weekly pipeline is idempotent and restart-safe.
- Email HTML is deterministically rendered from validated JSON.
- Operational logs include run ID and draft version context.

## Multi-Developer Coordination
- Prefer one task owner at a time per `IMP-###` item.
- If two tasks conflict, list dependency/order in the plan before coding.
- Resolve plan conflicts in PR by preserving the latest completed checkboxes and notes.
