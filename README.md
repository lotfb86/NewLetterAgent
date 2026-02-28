# Newsletter Agent

AI-powered weekly newsletter system that combines Slack team updates with external AI news, drafts content, runs a feedback loop in Slack, and sends approved issues through Resend.

## Start Here (Required)
1. Read [IMPLEMENTATION_PLAN.md](/Users/jesseanglen/NewLetterAgent/IMPLEMENTATION_PLAN.md).
2. Pick one unchecked task.
3. Claim it in the plan before writing code.
4. Implement + test.
5. Mark the task complete in the plan with a completion note.

If plan status is not updated, the work is not considered done.

## Working Agreement
- Every change must map to an `IMP-###` task.
- Keep PRs scoped to claimed tasks.
- Run `make check` before finishing.
- Do not skip plan updates.

## Local Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make check
```

## Runtime Commands
- Start bot + scheduler: `python bot.py`
- Run checks: `make check`
- Tests only: `make test`

## Slack Operator Commands
Post these in `#newsletter-updates`:
- `run` -> trigger manual research + draft cycle (run lock enforced)
- `reset` -> clear active draft state and start a fresh cycle
- `replay <run_id>` -> resume/replay an incomplete failed run
- `approved` (in latest draft thread) -> trigger send pipeline
- Reply in draft thread -> feedback redraft loop
- Reply `include` in late-update prompt thread -> inject late update + auto-redraft

## Reliability + Safety
- Run-level lock stored in SQLite (`run_lock` table)
- Send ledger stages:
  - `draft_ready -> send_requested -> render_validated -> broadcast_created -> broadcast_sent -> brain_updated`
- Idempotent send protection by `run_id`
- Dead-letter failures written to `data/failures/`
- Backups on `brain_updated`:
  - `data/run_state.db.bak`
  - `data/archive/published_stories_YYYY-MM-DD.md`
- Heartbeat job posts daily liveness + next scheduled run

## Deployment

### Railway
- Runtime command: `python bot.py`
- `Procfile` is configured for worker mode.
- `railway.toml` is included with restart policy.
- Mount persistent volume at `/app/data`.

### Docker
- Build: `docker build -t newsletter-agent .`
- Run (example):
```bash
docker run --rm \
  -e OPENROUTER_API_KEY=dummy \
  -e SLACK_BOT_TOKEN=dummy \
  -e SLACK_APP_TOKEN=dummy \
  -e NEWSLETTER_CHANNEL_ID=C123 \
  -e RESEND_API_KEY=dummy \
  -e RESEND_AUDIENCE_ID=aud_dummy \
  -e NEWSLETTER_FROM_EMAIL=newsletter@example.com \
  -e TIMEZONE=America/Chicago \
  -e RESEARCH_DAY=thu \
  -e RESEARCH_HOUR=9 \
  -e BRAIN_FILE_PATH=/app/data/published_stories.md \
  -e DEDUP_LOOKBACK_WEEKS=12 \
  -e RUN_STATE_DB_PATH=/app/data/run_state.db \
  -e FAILURE_LOG_DIR=/app/data/failures \
  -e MAX_EXTERNAL_RETRIES=3 \
  -e MAX_DRAFT_VERSIONS=5 \
  -e ENABLE_DRY_RUN=true \
  -v "$PWD/data:/app/data" \
  newsletter-agent
```

## Signup Flow (Webflow Integration)

### Option A (Recommended): Standalone signup page
- Deploy `signup/index.html` + `signup/api/subscribe.py` to Vercel.
- Configure env vars: `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`, `SIGNUP_ALLOWED_ORIGINS`.
- Share the signup URL directly (site button, social, signatures, etc).

### Option B: Webflow form + API
1. Build form in Webflow.
2. POST to `signup/api/subscribe.py` endpoint.
3. Ensure Webflow domain is in `SIGNUP_ALLOWED_ORIGINS`.
4. Keep server-side CORS allowlist strict.

## Signup API Behavior
- Validates and normalizes email.
- Handles CORS preflight (`OPTIONS`) and allowlist enforcement.
- Rejects disallowed origins.
- In-memory IP rate limiting.
- Honeypot anti-bot field (`company`).
- Duplicate contact attempts return success with `duplicate=true`.

## Observability
- Structured JSON logs include event, timestamps, and run context.
- Slack status messages emitted at major run/send stages.
- Daily heartbeat includes scheduler next-run timestamp.

## Recovery Playbook
1. Inspect latest dead-letter file in `data/failures/`.
2. Find run ID from error payload.
3. Use Slack command `replay <run_id>`.
4. If draft is stale or capped, issue `reset`.

## Repository Documents
- Execution tracker: [IMPLEMENTATION_PLAN.md](/Users/jesseanglen/NewLetterAgent/IMPLEMENTATION_PLAN.md)
- Product architecture: [PLAN.md](/Users/jesseanglen/NewLetterAgent/PLAN.md)
- Locking strategy: [DEPENDENCY_LOCKING.md](/Users/jesseanglen/NewLetterAgent/DEPENDENCY_LOCKING.md)
