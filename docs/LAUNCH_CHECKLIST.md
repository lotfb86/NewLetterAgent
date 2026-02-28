# Launch Checklist — The Ruh Digest

Last updated: 2026-02-28

## Pre-Deployment Verification

- [x] All 111 tests passing (`make check`)
- [x] Phase 12 production readiness bugs fixed (IMP-120 through IMP-132)
- [x] Ruh.ai branding applied across all prompts, template, and CTA (IMP-133)
- [x] Newsletter name changed to "The Ruh Digest" everywhere
- [x] Template updated: purple brand color (#7c3aed), Ruh.ai footer, CTA
- [x] Stale run lock cleanup at startup (IMP-124)
- [x] SQLite WAL mode + foreign keys enabled (IMP-126)
- [x] Conversational state persistence to SQLite (IMP-122)
- [x] Grok research source added (optional, IMP-123)
- [ ] Verify `ruhdigest.com` DKIM/SPF records still valid in Resend

## Railway Configuration

- [x] Railway project: gracious-surprise
- [ ] Persistent volume mounted at `/app/data/` for SQLite + brain file
- [ ] Verify `restartPolicyType=ON_FAILURE` with maxRetries=5
- [x] `railway.toml` has correct `startCommand = "python bot.py"`

### Required Environment Variables
```
OPENROUTER_API_KEY=sk-or-v1-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
NEWSLETTER_CHANNEL_ID=C0AHTR8GK0C
RESEND_API_KEY=re_...
RESEND_AUDIENCE_ID=c6c7e9ee-0961-4891-9b98-0d719198c5ab
NEWSLETTER_FROM_EMAIL=newsletter@ruhdigest.com
NEWSLETTER_REPLY_TO_EMAIL=jesse@ruh.ai
TIMEZONE=America/Chicago
RESEARCH_DAY=thu
RESEARCH_HOUR=9
BRAIN_FILE_PATH=data/published_stories.md
DEDUP_LOOKBACK_WEEKS=12
RUN_STATE_DB_PATH=data/run_state.db
FAILURE_LOG_DIR=data/failures
MAX_EXTERNAL_RETRIES=4
MAX_DRAFT_VERSIONS=5
ENABLE_DRY_RUN=false
HEARTBEAT_CHANNEL_ID=C0AHTR8GK0C
HEARTBEAT_HOUR_UTC=15
SIGNUP_ALLOWED_ORIGINS=https://ruh.ai,https://www.ruh.ai
ENABLE_GROK_RESEARCH=false
```

## Production Go-Live (First Send)

### Step 1: Push and Deploy
- [ ] Commit all changes to `main`
- [ ] Push to GitHub (triggers Railway auto-deploy)
- [ ] Wait ~90s for deploy to complete
- [ ] Verify bot comes online in #newsletter-agent (look for heartbeat or test message)

### Step 2: Verify Bot Responsiveness
- [ ] Post a test team update in #newsletter-agent
- [ ] Verify bot responds without `*Sent using*` attribution leaking
- [ ] Verify late-update detection works (if after collection cutoff)
- [ ] Verify clarification questions work (if update is unclear)

### Step 3: Initial Newsletter Run
- [ ] Post `run` in #newsletter-agent
- [ ] Wait for research phase to complete (~2-5 min)
- [ ] Review draft posted by bot in channel
- [ ] Verify "The Ruh Digest" branding in draft preview
- [ ] Verify stories are relevant to AI agents/digital labor/enterprise
- [ ] Provide feedback if needed, verify redraft works
- [ ] Post `approved` in draft thread when satisfied

### Step 4: Post-Send Verification
- [ ] Verify email arrives at `jesse@rapidinnovation.io`
- [ ] Check email renders correctly (Gmail, mobile)
- [ ] Verify "The Ruh Digest" header and branding
- [ ] Verify CTA links to https://ruh.ai
- [ ] Verify unsubscribe link works
- [ ] Check Slack for `brain_updated` stage confirmation
- [ ] Verify `data/published_stories.md` was updated

## Domain Warm-Up Plan (Weeks 1-3)

### Week 1
- Send to 5-10 friendly/internal addresses only
- Monitor Resend deliverability dashboard
- Check no spam folder placement
- Verify open rates and click rates

### Week 2
- Gradually add more addresses (up to 50)
- Continue monitoring deliverability
- Watch for bounce rates (should be <2%)

### Week 3
- Scale to broader audience if deliverability is good
- Add remaining ~3,000 contacts via signup form or Resend import
- Monitor complaints and unsubscribes

## Rollback Procedure

If the first production send fails:
1. Check Slack error message for stage and error details
2. Check Railway logs (`railway logs`)
3. If stuck at run lock: restart service (lock auto-clears after 30min)
4. If draft generation failed: post `reset` to retry with fresh run
5. If send failed after approval: post `replay <run_id>` to resume
6. If critical issue: set `ENABLE_DRY_RUN=true` to prevent real sends

## Monitoring

- **Heartbeat**: Bot posts every 24h to #newsletter-agent (silence >36h = bot down)
- **Railway dashboard**: Check for crash loops (max 5 restarts)
- **Resend dashboard**: Monitor delivery rates, bounces, complaints
- **Brain file**: Verify grows by one section per successful send

## Known Limitations (Acceptable for Launch)

1. No database migration strategy — schema changes require manual intervention
2. Circuit breaker resets on deploy (in-memory only)
3. Brain file grows unboundedly (fine for months/years of weekly sends)
4. Approval keyword matching is eager ("approved" anywhere triggers it)
5. No persistent volume backup strategy beyond in-app snapshots
