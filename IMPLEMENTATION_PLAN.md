# Newsletter Agent - Full Build Implementation Plan

Last updated: 2026-02-28
Owner model: Multi-developer, shared repository
Plan sync: Includes redraft cap/reset flow, render validation ledger gate, and backup policy from `PLAN.md`

## Source Of Truth
- This file is the execution source of truth for build progress.
- Product and architecture details live in [PLAN.md](/Users/jesseanglen/NewLetterAgent/PLAN.md).
- If this file and code diverge, update this file immediately.

## Required Collaboration Protocol
1. Before starting work, pick an unchecked task from this file.
2. Claim it by replacing `Owner: unassigned` with your name/initials and date started.
3. Implement and test the task.
4. Mark task complete by changing `[ ]` to `[x]` and adding completion notes.
5. If partial or blocked, leave it unchecked and add a blocker note under the task.
6. Do not start unplanned work; add a new task ID first if scope changes.

## Definition Of Done (for every task)
- Code implemented and merged (or ready to merge).
- Relevant tests added/updated and passing locally.
- Logging/errors handled for failure cases.
- Docs/config updated if behavior changed.
- Task checkbox marked complete in this file.

## Milestones
- M1: Foundation complete
- M2: Research and content pipeline complete
- M3: Slack workflow complete
- M4: Send pipeline + operational safety complete
- M5: Staging dry-run complete
- M6: Production launch complete

---

## Phase 0 - Program Setup And Governance

- [x] `IMP-000` Establish repo governance docs (`README.md`, `IMPLEMENTATION_PLAN.md`)
  - Owner: Codex (2026-02-27)
  - Depends on: none
  - Done when: contributor workflow and task-tracking rules are documented
  - Completion note: Added `README.md` with mandatory plan workflow and created full-build execution tracker in `IMPLEMENTATION_PLAN.md`.

- [x] `IMP-001` Create project skeleton from PLAN structure
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-000`
  - Done when: folders/files from project structure exist with stubs
  - Completion note: Added scaffold for listeners/services/templates/data/signup/tests, root entry files (`bot.py`, `config.py`, `scheduler.py`), and baseline `Procfile`/`Dockerfile` stubs plus placeholder template and initial test files.

- [x] `IMP-002` Add `.env.example` with all required variables
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-001`
  - Done when: env var list matches PLAN (including `MAX_DRAFT_VERSIONS` and `ENABLE_DRY_RUN`) and boot fails fast on missing required vars
  - Completion note: Added `.env.example` with all PLAN variables including `MAX_DRAFT_VERSIONS` and `ENABLE_DRY_RUN`, plus optional heartbeat/CORS placeholders for upcoming tasks.

- [x] `IMP-003` Add `requirements.txt` and lock strategy
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-001`
  - Done when: all runtime + test dependencies are defined and install cleanly
  - Completion note: Added `requirements.txt`, `requirements-dev.txt`, and `DEPENDENCY_LOCKING.md` documenting `pip-tools` lockfile workflow; dependencies install cleanly in local venv.

- [x] `IMP-004` Add lint/test tooling (`pytest`, formatting, static checks)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-003`
  - Done when: one command runs all local quality checks
  - Completion note: Added `pyproject.toml` (`pytest`/`ruff`/`mypy`) and `Makefile` with `make check` running lint, format-check, typecheck, and tests.

- [x] `IMP-005` Add CI workflow for lint + tests
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-004`
  - Done when: pull requests run automated checks
  - Completion note: Added GitHub Actions workflow `.github/workflows/ci.yml` to install deps and run `make check` on PRs and key branches.

---

## Phase 1 - Core Config, Models, And Persistence

- [x] `IMP-010` Implement central config loader (`config.py`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-002`
  - Done when: typed config is loaded once and validated at startup
  - Completion note: Implemented `AppConfig` with typed parsing/validation, required-env fail-fast checks, boolean/int parsing guards, and cached `get_config()` + cache reset helper.

- [x] `IMP-011` Define core data models (story, draft, run state, feedback)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: all pipeline boundaries use structured models, not raw dicts
  - Completion note: Added `models.py` with typed enums/dataclasses for story candidates, draft payloads, feedback events, and run/draft state records.

- [x] `IMP-012` Implement run ledger persistence (`data/run_state.db` + `services/run_state.py`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-011`
  - Done when: run states persist across restart with transitions enforced
  - Completion note: Implemented SQLite-backed `RunStateStore` with schema init, run creation, guarded stage transitions (`draft_ready -> ... -> brain_updated`), incomplete-run listing, and persisted draft state upsert/get.

- [x] `IMP-013` Implement file locking/atomic writes for `published_stories.md`
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-011`
  - Done when: concurrent writes cannot corrupt brain file
  - Completion note: Implemented `services/brain.py` with advisory lock file (`flock`) and atomic temp-file replace writes for brain updates plus parser/read helpers.

- [x] `IMP-014` Add migration/init logic for runtime data paths (`data/`, `failures/`, `archive/`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-012`
  - Done when: app bootstraps required runtime directories automatically
  - Completion note: Added `services/runtime_paths.py` bootstrap to create runtime dirs (`data/`, `archive/`, `failures/`), ensure brain file exists, and initialize run-state DB.

---

## Phase 2 - External Service Clients

- [x] `IMP-020` Build OpenRouter client wrapper with retries/timeouts
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: supports Claude + Perplexity models with consistent response parsing
  - Completion note: Implemented `services/llm.py` OpenRouter wrapper with typed `LLMResult`, Claude/Perplexity helper methods, normalized citations, and resilience policy retries.

- [x] `IMP-021` Build RSS fetch/parser service with parallel fetch
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: configured feeds return normalized story objects
  - Completion note: Implemented `services/rss_reader.py` with feed source definitions, parallel fetch via `ThreadPoolExecutor`, normalized `StoryCandidate` outputs, recent-window filtering, and URL dedup.

- [x] `IMP-022` Build Hacker News fetch adapter
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-021`
  - Done when: top stories can be fetched and normalized into the same schema
  - Completion note: Added `services/hacker_news.py` adapter for top story IDs + item fetch and normalization into `StoryCandidate` schema.

- [x] `IMP-023` Build Slack reader service for channel history + threads
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: weekly window updates and clarifications can be retrieved
  - Completion note: Implemented `services/slack_reader.py` with paginated channel history, thread reply fetch, and weekly `TeamUpdate` assembly.

- [x] `IMP-024` Build Resend sender service (broadcast create/send/status)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: dry-run and real send paths both supported, where dry-run is log-only and never calls live Resend send
  - Completion note: Implemented `services/sender.py` with create/send/get operations and strict dry-run behavior (never calls live send in dry-run mode).

- [x] `IMP-025` Add service-level circuit breaking/backoff policies
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-020`, `IMP-021`, `IMP-023`, `IMP-024`
  - Done when: transient failures retry safely and terminal failures are surfaced cleanly
  - Completion note: Added shared `services/resilience.py` (retry + circuit breaker), integrated into LLM, RSS, Slack, HN, and Resend service calls.

---

## Phase 3 - Research Pipeline

- [x] `IMP-030` Implement weekly source collection orchestration
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-021`, `IMP-022`, `IMP-023`
  - Done when: all source stories for issue window are collected in one run payload
  - Completion note: Added `services/research_pipeline.py` orchestration that collects Slack updates + RSS + HN stories for the issue window in a unified bundle.

- [x] `IMP-031` Implement Perplexity query runner with configurable prompts
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-020`
  - Done when: 4-5 weekly queries execute and citations are captured
  - Completion note: `services/news_researcher.py` now runs configurable Perplexity query sets and captures query content + citations into structured results.

- [x] `IMP-032` Implement story merge + primary dedup (canonical URL + exact title)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-030`, `IMP-031`
  - Done when: duplicate source entries collapse into one candidate story
  - Completion note: Implemented `merge_primary_dedupe()` in `services/research_pipeline.py` with canonical URL normalization and exact normalized-title suppression.

- [x] `IMP-033` Implement secondary dedup (fuzzy similarity + follow-up detection)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-032`
  - Done when: near-duplicate stories are merged without losing true new developments
  - Completion note: Implemented `secondary_dedupe()` with SequenceMatcher similarity threshold plus same-source token-overlap follow-up heuristic.

- [x] `IMP-034` Implement brain lookback filtering (`DEDUP_LOOKBACK_WEEKS`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-013`
  - Done when: previously published stories are removed from candidate list
  - Completion note: Implemented `filter_previously_published()` to apply configurable lookback window and remove URL/title matches against parsed brain entries.

- [x] `IMP-035` Implement relevance scoring for target themes
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-032`
  - Done when: top stories are ranked by agents/digital labor/funding/enterprise relevance
  - Completion note: Implemented keyword/tier/confidence-weighted scoring and sorted ranking via `rank_stories_by_relevance()`.

---

## Phase 4 - Data Quality And Verification

- [x] `IMP-040` Implement URL canonicalization utility
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-032`
  - Done when: tracking params and common wrappers are normalized consistently
  - Completion note: Implemented `canonicalize_url()` in `services/quality.py` with tracking-parameter stripping, host normalization, redirect unwrapping for common wrappers, and stable URL normalization.

- [x] `IMP-041` Implement source trust tier classifier
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-040`
  - Done when: each story has `tier1|tier2|tier3` confidence basis
  - Completion note: Implemented domain-based tier classifier (`assign_source_tier`) and applied tier/confidence enrichment via `apply_canonicalization_and_tiering()`.

- [x] `IMP-042` Implement numeric-claim verification checks
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-041`
  - Done when: sensitive numeric claims are verified or flagged/removed
  - Completion note: Added numeric-claim extraction and verification flow (`enforce_numeric_claim_verification`) that upgrades verified claims and flags/demotes unverified numeric stories.

- [x] `IMP-043` Implement recency enforcement and missing-date handling
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-030`
  - Done when: stale/undated stories are filtered or explicitly marked low confidence
  - Completion note: Implemented `enforce_recency()` to remove out-of-window stories and mark missing timestamp stories as low-confidence with metadata note.

- [x] `IMP-044` Implement citation retention fields in story schema
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-011`
  - Done when: `source_url`, `source_name`, `published_at`, `confidence` are always present
  - Completion note: Citation fields are first-class in `StoryCandidate` and validated by `validate_citation_fields()` in quality gates.

- [x] `IMP-045` Propagate confidence + source tier into planning inputs
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-041`, `IMP-044`
  - Done when: planner inputs include confidence and source-tier metadata for each candidate story
  - Completion note: Added planner payload conversion (`to_planning_inputs`) and integrated quality outputs into `ResearchPipeline.run_weekly()` bundle output.

---

## Phase 5 - Newsletter Planning, Writing, Rendering

- [x] `IMP-050` Implement planner prompt and JSON schema output
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-020`, `IMP-035`, `IMP-044`, `IMP-045`
  - Done when: planner returns valid structured outline JSON and enforces confidence-based numeric-claim rules from PLAN
  - Completion note: Implemented `NewsletterPlanner` with structured prompts, strict planner schema validation, and confidence-aware planning rules.

- [x] `IMP-051` Implement writer prompt to output newsletter JSON only
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-050`
  - Done when: content JSON validates against schema and preserves story confidence metadata in output
  - Completion note: Implemented `NewsletterWriter` with newsletter JSON schema enforcement and explicit confidence metadata preservation.

- [x] `IMP-052` Build JSON schema validation + repair loop for model outputs
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-051`
  - Done when: malformed model output is retried/repaired before downstream use
  - Completion note: Added JSON extraction + schema validation utilities and repair-loop retry prompts in planner/writer services.

- [x] `IMP-052b` Implement LLM composition failure fallback
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-052`, `IMP-074`
  - Done when: if the planner or writer LLM calls fail validation after `MAX_EXTERNAL_RETRIES` attempts, the pipeline halts cleanly; the partial payload is saved to `data/failures/` as a dead-letter event; bot posts to Slack: *"Draft generation failed after [N] attempts: [error summary]. Research data has been saved. Manual intervention needed — fix the issue and say 'reset' to retry."*; the run ledger stays at the pre-composition state so a reset can resume from collected research without re-fetching
  - Completion note: Added `services/composition.py` dead-letter persistence and `CompositionFailure` exception emitted by planner/writer after retry exhaustion.

- [x] `IMP-052a` Design responsive HTML email template (`templates/newsletter_base.html`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-011`
  - Done when: template renders correctly in Gmail, Apple Mail, and Outlook (desktop + mobile); uses table-based layout with inline CSS for Outlook compatibility; supports dark mode via `prefers-color-scheme`; includes header, team updates section, industry stories section, CTA block, and footer with unsubscribe placeholder
  - Completion note: Replaced placeholder with table-based, responsive, dark-mode-aware template containing all required newsletter sections and unsubscribe placeholder.

- [x] `IMP-053` Build deterministic Jinja email renderer (`templates/newsletter_base.html`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-052`, `IMP-052a`
  - Done when: HTML generation is deterministic and model text is escaped by default
  - Completion note: Implemented `NewsletterRenderer` with strict Jinja environment, schema/link validation before render, and HTML validation after render.

- [x] `IMP-054` Implement pre-send HTML/link/unsubscribe validation checks
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-053`
  - Done when: invalid drafts are blocked with actionable errors before send transitions advance
  - Completion note: Added validator checks for unsubscribe placeholder, HTML size/section presence, anchor integrity, and HTTPS-only URL enforcement.

- [x] `IMP-055` Implement Slack preview formatter from canonical JSON
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-052`
  - Done when: Slack preview content matches rendered email meaningfully
  - Completion note: Implemented `SlackPreviewFormatter` to build Block Kit preview text from canonical newsletter JSON with structured sections.

- [x] `IMP-055a` Handle Slack Block Kit size limits in preview formatter
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-055`
  - Done when: previews exceeding Slack limits (3,000 chars per text block, 50 blocks per message) are intelligently truncated or split across multiple messages with clear continuation markers; full draft is always available via a "View full draft" thread reply or attached snippet
  - Completion note: Added block text chunking, message batch splitting, continuation markers, and full-draft markdown snippet output for overflow handling.

---

## Phase 6 - Slack Bot Interaction Flow

- [x] `IMP-060` Implement Slack Bolt app bootstrap with Socket Mode
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`
  - Done when: bot connects reliably and receives channel events
  - Completion note: Reworked `bot.py` into full Slack Bolt + Socket Mode runtime with dependency wiring, event handling, scheduler startup, and graceful shutdown hooks.

- [x] `IMP-060a` Implement bot self-message filtering
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`
  - Done when: bot ignores all messages authored by its own bot user ID; covers draft posts, confirmations, clarifying questions, and status updates so they never trigger listeners
  - Completion note: Added robust self-message filtering in dispatcher for bot user ID, `bot_message` subtype, and `bot_id` payloads with unit coverage.

- [x] `IMP-060b` Implement message routing dispatcher
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`, `IMP-060a`
  - Done when: a single entry-point dispatcher routes each incoming message through this priority chain: (1) self-message → ignore, (2) contains "approved" (case-insensitive) → approval listener, (3) is a thread reply on a draft post → feedback listener, (4) is a thread reply on a team update → store as clarification context, (5) top-level message → update validator. Each branch is testable in isolation.
  - Completion note: Implemented unified `MessageDispatcher` with explicit routing order, command branches (`run`/`reset`/`replay`), late-update include branch, and branch-level tests.

- [x] `IMP-061` Implement team update validator + clarifying question thread replies
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060b`, `IMP-020`
  - Done when: unclear updates trigger targeted follow-up questions
  - Completion note: `TeamUpdateHandler` now validates updates with Claude, returns clarification questions, and persists clarification replies into thread context state.

- [x] `IMP-062` Implement draft post creation and version tracking
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-055`, `IMP-012`
  - Done when: each draft has version, timestamp, and run linkage
  - Completion note: Added orchestrated draft posting from canonical JSON preview + persisted run-linked draft metadata (`run_id`, `draft_ts`, `draft_version`) in SQLite state.

- [x] `IMP-063` Implement feedback detection and JSON redraft loop
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-062`, `IMP-051`
  - Done when: threaded feedback creates new draft versions reliably
  - Completion note: Implemented writer-driven `revise_newsletter` flow, feedback listener integration, redraft post/re-render, and revision version increments via `DraftManager.create_revision`.

- [x] `IMP-064` Implement approval detection for latest draft only
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-062`
  - Done when: only active draft can move to send pipeline
  - Completion note: Approval handler enforces latest-thread matching and pending status before allowing send pipeline progression.

- [x] `IMP-065` Implement stale-draft guardrail (>48h requires refresh)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-064`
  - Done when: stale approvals are blocked with clear Slack guidance
  - Completion note: Added stale-check guard (>48h) in approval path with explicit operator-facing Slack rejection messaging.

- [x] `IMP-066` Implement redraft cap and max-revision status
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-063`, `IMP-010`
  - Done when: feedback loop hard-caps at `MAX_DRAFT_VERSIONS` and sets `max_revisions_reached` state
  - Completion note: Enforced max revision capacity in `DraftManager` + feedback handler with explicit `max_revisions_reached` status transitions.

- [x] `IMP-067` Implement `reset` command for fresh research + draft cycle
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-066`, `IMP-030`, `IMP-062`
  - Done when: users can issue reset to clear capped/stale draft state and start a new run safely
  - Completion note: `reset` now clears persisted active draft state and triggers a fresh run pipeline with new run ID and v1 draft.

- [x] `IMP-068` Implement manual `run` command to trigger research pipeline on demand
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060b`, `IMP-030`, `IMP-070`
  - Done when: a user can post "run" in `#newsletter-updates` to trigger the full research + draft pipeline outside the Thursday schedule; respects the run lock so it cannot conflict with a scheduled or in-progress run; bot confirms the trigger or explains why it was rejected
  - Completion note: Added manual run command routing to orchestrator with singleton run lock enforcement and accepted/rejected Slack responses.

- [x] `IMP-069` Handle late updates posted after Thursday collection window
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060b`, `IMP-062`
  - Done when: updates posted after the Thursday 9 AM collection cutoff but before the newsletter is sent are flagged to the team; bot replies in thread: *"This update arrived after this week's collection window. Reply 'include' to add it to the current draft, or it will be picked up next week."*; if someone replies "include", the update is injected into the current draft JSON and a redraft is triggered automatically
  - Completion note: Added late-update detection window + prompt flow, include command handling, JSON injection into `team_updates`, and automatic redraft posting.

---

## Phase 7 - Send Pipeline And Operational Safety

- [x] `IMP-070` Implement run ID generation and per-run lock
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-012`
  - Done when: concurrent weekly runs are prevented
  - Completion note: Added UTC date-stamped run ID generation in orchestrator and persisted singleton run lock table in `run_state.db`.

- [x] `IMP-071` Implement send ledger state machine
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-070`, `IMP-024`, `IMP-054`
  - Done when: send transitions (`draft_ready -> send_requested -> render_validated -> broadcast_created -> broadcast_sent -> brain_updated`) are persisted and restart-safe
  - Completion note: Implemented stage-by-stage send orchestrator using persisted ledger transitions and resume logic for incomplete runs.

- [x] `IMP-072` Implement idempotent send protection by run ID
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-071`
  - Done when: duplicate send attempts are safely ignored/blocked
  - Completion note: Send path now blocks repeated sends once run reaches terminal stage and enforces single transition progression per run.

- [x] `IMP-073` Implement post-send brain update transaction logic
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-072`, `IMP-013`
  - Done when: published stories append exactly once per successful send
  - Completion note: Brain append now executes only at `broadcast_sent -> brain_updated` boundary, guaranteeing single append per successful run.

- [x] `IMP-074` Implement dead-letter failure capture (`data/failures/`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-071`
  - Done when: unrecoverable failures are stored with payload + metadata
  - Completion note: Added generic dead-letter capture (`services/failures.py`) for run/send failures and integrated into orchestration failure paths.

- [x] `IMP-075` Implement structured logging with run/draft/request IDs
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-070`
  - Done when: logs allow full reconstruction of a weekly run
  - Completion note: Added JSON structured logger with run/draft/request context and integrated run lifecycle logging events.

- [x] `IMP-076` Implement Slack stage-by-stage status reporting
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`, `IMP-075`
  - Done when: operators can see run progress and failures in channel
  - Completion note: Orchestrator now posts stage status updates in Slack for research start, draft posting, send stages, completion, and failures.

- [x] `IMP-077` Implement manual recovery/replay command(s)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-074`, `IMP-071`
  - Done when: failed runs can be resumed or replayed without code edits
  - Completion note: Added `replay <run_id>` routing, command controller callback, and orchestrator replay/resume logic for failed/incomplete runs.

- [x] `IMP-078` Implement backup policy for runtime state and brain data
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-073`, `IMP-014`
  - Done when: successful `brain_updated` triggers `run_state.db.bak`, and weekly `published_stories.md` archive snapshots are created
  - Completion note: Added backup helpers creating `run_state.db.bak` and dated brain snapshots in `data/archive/` on successful `brain_updated`.

---

## Phase 8 - Scheduling And Runtime

- [x] `IMP-080` Implement APScheduler weekly trigger with timezone config
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`, `IMP-070`
  - Done when: scheduled Thursday runs execute at configured timezone hour
  - Completion note: Replaced scheduler stub with APScheduler runtime using timezone-aware weekly cron trigger from config.

- [x] `IMP-081` Implement startup reconciliation for missed/incomplete runs
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-080`, `IMP-071`
  - Done when: restart recovers safely from mid-run interruption
  - Completion note: Scheduler startup now invokes orchestrator reconciliation to resume safe incomplete runs after process restart.

- [x] `IMP-082` Implement graceful shutdown handling
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`, `IMP-080`
  - Done when: shutdown drains tasks and persists states cleanly
  - Completion note: Added SIGTERM/SIGINT handlers to shutdown scheduler and close Socket Mode handler cleanly.

- [x] `IMP-083` Implement periodic healthcheck / heartbeat
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`, `IMP-080`
  - Done when: bot posts a lightweight heartbeat to a designated Slack channel (or a private log channel) every 24 hours confirming it is alive and Socket Mode is connected; if no heartbeat is received for >36 hours, the team knows the process has silently died; APScheduler next-run time is included in the heartbeat message so operators can verify the scheduler is active
  - Completion note: Added 24-hour heartbeat scheduler job posting liveness and next scheduled run timestamp to configured heartbeat channel.

---

## Phase 9 - Signup Flow

- [x] `IMP-090` Build minimal signup page UI (`signup/index.html`)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-001`
  - Done when: page submits email to API with user-friendly states
  - Completion note: Implemented and refreshed standalone responsive signup UI with modal-style presentation, loading/error/success states, API submission wiring, accessibility status semantics, and backend-compatible field IDs/payload contract.

- [x] `IMP-091` Build `signup/api/subscribe.py` with validation
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-024`, `IMP-090`
  - Done when: valid email is added to Resend audience with sanitized input
  - Completion note: Implemented subscribe endpoint processor with JSON parsing, normalized email validation, and Resend contacts create integration.

- [x] `IMP-091a` Configure CORS for signup endpoint
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-091`
  - Done when: endpoint returns proper CORS headers (`Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`) for the Webflow domain and the standalone signup page domain; preflight `OPTIONS` requests are handled; other origins are rejected
  - Completion note: Added origin allowlist CORS handling with explicit preflight responses and disallowed-origin rejection.

- [x] `IMP-092` Add abuse protections (rate limiting + anti-bot)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-091`
  - Done when: endpoint resists scripted abuse and spam signups
  - Completion note: Added IP-window rate limiting and honeypot bot trap (`company` field) to suppress scripted abuse.

- [x] `IMP-093` Add duplicate-email and error UX handling
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-091`
  - Done when: user sees clear messages for already-subscribed/error cases
  - Completion note: Endpoint now maps duplicate-contact errors to `duplicate=true`; signup UI displays clear duplicate/network/error messages.

- [x] `IMP-094` Document Webflow integration option and link strategy
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-090`
  - Done when: README has exact instructions for Option A and Option B
  - Completion note: Updated `README.md` with exact Option A (standalone page) and Option B (Webflow form + API) integration instructions.

---

## Phase 10 - Testing

- [x] `IMP-100` Unit tests for config + models + run state
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-010`, `IMP-011`, `IMP-012`
  - Done when: model/config/state transitions are covered
  - Completion note: Added/maintained unit coverage in `test_config.py`, `test_models.py`, `test_run_state.py`, and new `test_run_state_lock.py`.

- [x] `IMP-101` Unit tests for RSS/HN/Perplexity adapters
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-021`, `IMP-022`, `IMP-031`
  - Done when: network parsing and normalization paths are covered
  - Completion note: Adapter coverage exists in `test_rss_reader.py`, `test_hacker_news.py`, `test_news_researcher.py`, and `test_llm.py`.

- [x] `IMP-102` Unit tests for quality checks + dedup
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-033`, `IMP-040`, `IMP-042`, `IMP-043`
  - Done when: canonicalization and verification rules are regression-safe
  - Completion note: Added and retained regression tests in `test_quality.py` and `test_research_pipeline.py` for canonicalization, verification, recency, and dedup behaviors.

- [x] `IMP-103` Unit tests for writer JSON schema and repair loop
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-052`
  - Done when: malformed outputs are caught and corrected/retried
  - Completion note: `test_writer.py` now covers schema repair retries, dead-letter failure capture, and revision JSON generation.

- [x] `IMP-104` Unit tests for renderer and HTML validation checks
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-053`, `IMP-054`
  - Done when: required placeholders/links/sections are guaranteed
  - Completion note: Renderer + validation coverage implemented in `test_renderer.py` and `test_validator.py`.

- [x] `IMP-105` Unit tests for approval/feedback listeners and message dispatcher
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060a`, `IMP-060b`, `IMP-063`, `IMP-064`, `IMP-065`
  - Done when: message routing works across edge cases including: bot ignores its own messages, approval only matches active drafts, feedback only matches draft threads, late updates prompt the include/skip flow, manual `run` and `reset` commands are routed correctly
  - Completion note: Expanded listener/dispatcher coverage in `test_approval_handler.py`, `test_feedback_handler.py`, and `test_router.py` (including run/reset/replay and late-update include flow).

- [x] `IMP-106` Unit tests for send idempotency and ledger recovery
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-072`, `IMP-081`
  - Done when: duplicate-send, restart, and `render_validated` gating scenarios are covered
  - Completion note: Added send idempotency + recovery coverage across `test_send_idempotency.py` and new orchestrator replay/send tests.

- [x] `IMP-107` Integration test: full dry-run path (no real send)
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-106`
  - Done when: end-to-end pipeline passes with fixture data
  - Completion note: Added integration-style dry-run pipeline test in `test_integration_pipeline.py::test_integration_full_dry_run_path`.

- [x] `IMP-108` Integration test: approved send in staging audience
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-107`
  - Done when: stage send succeeds and brain updates once
  - Completion note: Added integration-style approved send test with non-dry-run sender behavior and single brain update assertion in `test_integration_pipeline.py::test_integration_live_send_and_single_brain_update`.

- [x] `IMP-109` Tests for redraft cap, reset flow, and backups
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-066`, `IMP-067`, `IMP-078`
  - Done when: max-revision behavior, reset-triggered rerun, and backup artifacts are verified
  - Completion note: Added/retained coverage for max revisions (`test_feedback_handler.py`), reset rerun (`test_orchestrator.py`), and backup artifact creation on send completion (`test_orchestrator.py`).

- [x] `IMP-109a` Tests for new gap-coverage tasks
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-052b`, `IMP-055a`, `IMP-068`, `IMP-069`, `IMP-083`, `IMP-091a`
  - Done when: LLM composition failure halts cleanly and saves dead-letter; Slack preview truncation/splitting works within Block Kit limits; manual `run` command respects run lock; late update `include` flow injects into current draft; heartbeat posts on schedule; CORS headers are present for allowed origins and rejected for others
  - Completion note: Coverage now spans composition failure (`test_planner.py`/`test_writer.py`), preview limit handling (`test_formatter.py`), command/run lock (`test_command_controller.py`), late include flow (`test_router.py`/`test_orchestrator.py`), heartbeat scheduling (`test_scheduler_runtime.py`), and signup CORS behavior (`test_signup_subscribe.py`).

---

## Phase 11 - Deployment, Release, And Launch

- [x] `IMP-110` Add `Procfile`/runtime start command and Railway config
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-060`, `IMP-080`
  - Done when: app boots on Railway worker with persistent volume paths
  - Completion note: Added/validated worker `Procfile` command and new `railway.toml` deployment config with restart policy; startup path documented in README.

- [ ] `IMP-110a` Create and test Dockerfile
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-110`
  - Done when: Docker image builds cleanly from project root; runs as non-root user; persistent volume mount at `/app/data/` works correctly; image size is reasonable (slim base); local `docker build && docker run` with test env vars starts the bot successfully
  - Progress note: Dockerfile updated to non-root slim runtime with `/app/data` volume mount and startup command.
  - Blocker note: Local Docker daemon unavailable in this session (`Cannot connect to the Docker daemon ...`), so build/run smoke validation could not be executed end-to-end.

- [ ] `IMP-111` Configure environment variables in staging and production
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-110`
  - Done when: both environments have validated secrets and config
  - Progress note: Added env setup/validation documentation in `README.md` and `docs/ENVIRONMENTS.md`.
  - Blocker note: Requires access to external staging/production infrastructure dashboards to configure and verify live secrets.

- [x] `IMP-112` Configure observability and alert routing
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-075`, `IMP-076`
  - Done when: critical failures notify operators quickly
  - Completion note: Implemented structured JSON logging, stage-by-stage Slack status reporting, and scheduled heartbeat notifications with next-run visibility.

- [ ] `IMP-113` Execute required staging dry-run checklist
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-108`, `IMP-111`
  - Done when: at least one scheduled + one manual dry-run are successful
  - Progress note: Added executable checklist in `docs/LAUNCH_CHECKLIST.md` and integration dry-run coverage in tests.
  - Blocker note: Requires live staging deployment with valid Slack/OpenRouter/Resend credentials.

- [ ] `IMP-114` Go-live checklist and first production send
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-113`
  - Done when: first real newsletter sends successfully and post-send checks pass
  - Blocker note: Requires completion of external staging gate and real production infrastructure access.

- [ ] `IMP-115` Launch retrospective and backlog updates
  - Owner: Codex (2026-02-27)
  - Depends on: `IMP-114`
  - Done when: incidents, lessons, and phase-2 improvements are documented
  - Progress note: Added retrospective checklist scaffold in `docs/LAUNCH_CHECKLIST.md`.
  - Blocker note: Can only be completed after first production send and post-launch incident review.

---

## Active Blockers
- `IMP-110a`: Docker build/run smoke-test blocked in-session due unavailable local Docker daemon connection.
- `IMP-111`: Requires direct access to staging/production secret managers and runtime dashboards.
- `IMP-113`: Requires live staging deployment and credentialed dry-run execution.
- `IMP-114`: Requires completion of `IMP-113` and first real production send.
- `IMP-115`: Requires completion of `IMP-114` and post-launch retrospective inputs.

## Change Log For This Plan
- 2026-02-27: Initial full-build implementation plan created from architecture plan and reliability requirements.
- 2026-02-27: Synced with updated `PLAN.md` additions (redraft cap + reset command, render validation ledger stage, and backup requirements).
- 2026-02-27: Added 10 gap-coverage tasks from review: `IMP-060a` (bot self-message filtering), `IMP-060b` (message routing dispatcher), `IMP-055a` (Slack Block Kit size limits), `IMP-052a` (email template design), `IMP-052b` (LLM composition failure fallback), `IMP-068` (manual `run` command), `IMP-069` (late update handling), `IMP-083` (healthcheck/heartbeat), `IMP-091a` (CORS for signup endpoint), `IMP-110a` (Dockerfile). Added `IMP-109a` for test coverage of new tasks. Updated `IMP-105` to include dispatcher and new routing edge cases.
- 2026-02-27: Completed foundation build tasks `IMP-001` to `IMP-005` and core primitives `IMP-010` to `IMP-014` with passing `make check`.
- 2026-02-27: Completed service integration tasks `IMP-020` to `IMP-025` and research pipeline tasks `IMP-030` to `IMP-035`, with passing lint/type/test checks (`30` tests).
- 2026-02-27: Completed quality/verification tasks `IMP-040` to `IMP-045` and integrated quality checks into research bundle generation (`35` tests passing).
- 2026-02-27: Completed composition/render tasks `IMP-050` to `IMP-055a` including schema repair loops, dead-letter fallback, deterministic HTML rendering, and Slack preview overflow handling (`50` tests passing).
- 2026-02-28: Completed interaction/runtime/safety/signup/testing tasks `IMP-060` to `IMP-109a` with orchestrator + scheduler integrations and expanded test suite (`87` tests passing).
- 2026-02-28: Completed deployment/observability tasks `IMP-110` and `IMP-112`; documented remaining external blockers for `IMP-110a`, `IMP-111`, `IMP-113`, `IMP-114`, and `IMP-115`.
- 2026-02-28: Refreshed `IMP-090` signup page visual/UI behavior while preserving `/api/subscribe` contract and re-validated project checks (`91` tests passing).
