# Newsletter Agent — Full Implementation Plan

## Overview

An AI-powered newsletter agent that automatically researches AI industry news, combines it with team updates from Slack, and sends a polished weekly newsletter. The agent runs as an always-on Slack bot with an interactive feedback loop and approval workflow.

**Company context:** The team builds human emulators / AI agents for clients. The newsletter should position the team as experts and get potential clients and investors excited about working with them.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Tech Stack](#tech-stack)
3. [Weekly Workflow](#weekly-workflow)
4. [Slack Bot — Interactive Features](#slack-bot--interactive-features)
5. [News Research Pipeline](#news-research-pipeline)
6. [The Brain — Deduplication System](#the-brain--deduplication-system)
7. [Newsletter Composition](#newsletter-composition)
8. [Feedback & Redraft Loop](#feedback--redraft-loop)
9. [Approval & Send Flow](#approval--send-flow)
10. [Operational Safety & Recovery](#operational-safety--recovery)
11. [Email Sending — Resend](#email-sending--resend)
12. [Newsletter Signup — Webflow Integration](#newsletter-signup--webflow-integration)
13. [Hosting — Railway](#hosting--railway)
14. [Project Structure](#project-structure)
15. [Environment Variables](#environment-variables)
16. [Dependencies](#dependencies)
17. [Setup Checklist](#setup-checklist)
18. [Testing & Launch Readiness](#testing--launch-readiness)
19. [Estimated Costs](#estimated-costs)
20. [Future Enhancements](#future-enhancements)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                Single Python Process (Railway)                │
│                                                               │
│  ┌──────────────────┐       ┌──────────────────────────────┐ │
│  │   APScheduler     │       │   Slack Bolt (Socket Mode)   │ │
│  │                   │       │                              │ │
│  │  Thu 9am CT:      │       │  ALWAYS LISTENING:           │ │
│  │   1. Collect      │       │                              │ │
│  │      Slack msgs   │       │  • Team posts update →       │ │
│  │   2. Research     │       │    Bot validates, asks       │ │
│  │      news via     │       │    clarifying Qs in thread   │ │
│  │      Perplexity   │       │                              │ │
│  │   3. Parse RSS    │       │  • After draft posted →      │ │
│  │      feeds        │       │    User gives feedback →     │ │
│  │   4. Dedup via    │       │    Bot redrafts & reposts    │ │
│  │      brain file   │       │                              │ │
│  │   5. Plan with    │       │  • User says "approved" →    │ │
│  │      Claude       │       │    Bot formats & sends       │ │
│  │   6. Write draft  │       │    newsletter via Resend     │ │
│  │   7. Post to      │       │                              │ │
│  │      Slack        │       │  • Updates brain file        │ │
│  └──────────────────┘       └──────────────────────────────┘ │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    OpenRouter Client                      │ │
│  │  (Single API key for all LLM calls)                      │ │
│  │                                                           │ │
│  │  perplexity/sonar      → News research (web search)      │ │
│  │  anthropic/claude-*    → Writing, planning, validation   │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Tool | Why |
|---|---|---|
| **LLM Router** | OpenRouter | Single API key for Perplexity + Claude |
| **News Research** | Perplexity Sonar via OpenRouter | Built-in web search, returns citations |
| **Newsletter Writing** | Claude Sonnet via OpenRouter | Best writing quality per dollar |
| **Content Validation** | Claude Haiku via OpenRouter | Fast, cheap for quick checks |
| **RSS Parsing** | `feedparser` (Python) | Free, reliable, standard library |
| **Email Sending** | Resend (Broadcast API) | Developer-first, free tier (3K/mo) |
| **Slack Integration** | Slack Bolt for Python (Socket Mode) | Official SDK, no public URL needed |
| **Scheduling** | APScheduler (in-process) | Runs inside the bot, timezone-aware |
| **Hosting** | Railway | Cheap ($5/mo), easy deploy, worker process |
| **Signup Page** | Resend hosted link (or simple Webflow form → serverless) | Shareable link for subscribers |

---

## Weekly Workflow

### Timeline (Central Time)

| Day | Time | What Happens |
|---|---|---|
| **Mon–Wed** | Anytime | Team drops updates in `#newsletter-updates`. Bot validates each message and asks clarifying questions in threads if anything is vague or incomplete. |
| **Thursday** | 9:00 AM CT | APScheduler triggers the research pipeline. Bot collects Slack messages (prev Thursday → this Thursday), runs Perplexity searches, parses RSS feeds, deduplicates against brain file, has Claude plan and write the draft. |
| **Thursday** | ~9:15 AM CT | Bot posts the formatted newsletter draft to `#newsletter-updates` with instructions: *"Review this draft. Reply with feedback to request changes, or say 'approved' to send."* |
| **Thu–Fri** | Anytime | Team reviews. Anyone can reply with feedback → bot redrafts and reposts. This loop continues until someone says "approved." |
| **After approval** | Immediately | Bot formats the final HTML email, sends via Resend Broadcast API, and updates the brain file with the stories that were published. |

### If No Team Updates

If no messages are found in `#newsletter-updates` for the week, the bot still runs the research pipeline and creates a newsletter with only industry news. The newsletter always ends with a CTA encouraging readers to reach out about AI agent projects or investment opportunities.

---

## Slack Bot — Interactive Features

### Technology: Slack Bolt for Python + Socket Mode

Socket Mode uses a WebSocket connection to Slack — no public URL, no ngrok, no reverse proxy. The bot is a long-running Python process that maintains a persistent connection.

### Required Slack App Configuration

**Bot Token Scopes:**
- `channels:history` — read messages in public channels
- `channels:read` — list channels, get channel info
- `chat:write` — post messages and replies
- `users:read` — resolve user IDs to display names
- `reactions:read` — (optional) detect emoji-based approval
- `reactions:write` — add ✅ acknowledgment reactions

**Event Subscriptions:**
- `message.channels` — fires on every message in public channels the bot belongs to

**App-Level Token:**
- Scope: `connections:write` (required for Socket Mode)

### Message Handlers

The bot registers three listeners in priority order:

1. **Approval listener** — detects "approved" (case-insensitive), triggers send pipeline
2. **Feedback listener** — detects messages that are replies to a draft post, triggers redraft
3. **General listener** — catches all other messages in `#newsletter-updates`, validates content, and asks clarifying questions in threads if needed

### Clarifying Questions Flow

When someone posts a team update:

1. Bot receives the message via Socket Mode
2. Sends the message to Claude (Haiku, via OpenRouter) with prompt:
   > "You are a newsletter editor. A team member posted this update for inclusion in our weekly AI newsletter. Does this make sense as a newsletter item? Is anything unclear, missing context, or potentially confusing to readers? If so, list specific clarifying questions. If the update is clear and complete, respond with 'CLEAR'."
3. If Claude returns questions → bot replies **in a thread** under the original message
4. If Claude says "CLEAR" → bot reacts with a checkmark emoji (✅) to acknowledge receipt
5. Thread replies from the team member are stored as additional context for Thursday's assembly

---

## News Research Pipeline

### Step 1: RSS Feed Collection

Parse these 10 feeds using `feedparser`:

| # | Feed | URL | Covers |
|---|---|---|---|
| 1 | TechCrunch AI | `https://techcrunch.com/category/artificial-intelligence/feed/` | Funding, launches |
| 2 | VentureBeat AI | `https://venturebeat.com/category/ai/feed/` | Enterprise adoption |
| 3 | Crunchbase News | `https://news.crunchbase.com/feed/` | Investment data |
| 4 | Wes Roth (NATURAL 20) | `https://rss.beehiiv.com/feeds/uCpOrhb7xR.xml` | AI agents, disruption |
| 5 | Matthew Berman (Forward Future) | Beehiiv RSS (discover from `forwardfuture.ai`) | Broad AI news |
| 6 | The Rundown AI | Beehiiv RSS (discover from `therundown.ai`) | Comprehensive coverage |
| 7 | Hacker News (API) | `https://hacker-news.firebaseio.com/v0/topstories.json` | Community buzz |
| 8 | Google News RSS | `https://news.google.com/rss/search?q=AI+agents+digital+labor+funding` | Gap-filling |
| 9 | OpenAI Blog | `https://openai.com/blog/rss.xml` | Model releases |
| 10 | Anthropic Blog | `https://www.anthropic.com/research/rss.xml` | Model releases |

**Implementation:**
- Fetch all feeds in parallel using `asyncio` or `concurrent.futures`
- Filter to articles published in the last 7 days
- Extract: title, URL, published date, summary/description
- Normalize and deduplicate by URL

### Step 2: Perplexity Deep Search via OpenRouter

Run 4-5 targeted queries through `perplexity/sonar`:

```python
research_queries = [
    "What are the biggest AI agent and digital labor announcements this week?",
    "What major AI startup funding rounds were announced this week?",
    "What new enterprise AI adoption news happened this week?",
    "What are the most hyped AI product launches or model releases this week?",
    "What AI industry trends or research breakthroughs are people talking about this week?",
]
```

For each query:
- Call `perplexity/sonar` via OpenRouter
- Extract the response content AND the `citations` array (real URLs, not hallucinated)
- Parse citations into the same format as RSS results

### Step 3: Merge & Deduplicate

- Combine RSS results + Perplexity results
- Deduplicate by URL (exact match) and title similarity (fuzzy match using simple string comparison)
- Check against brain file (see next section) to remove previously published stories
- Score remaining stories by relevance to target topics (AI agents, digital labor, funding, enterprise adoption)

### Step 4: Data Quality & Verification

Before any story can be included in planning:

1. **Canonicalize URLs first**
   - Strip common tracking params (`utm_*`, `ref`, `fbclid`, etc.)
   - Normalize scheme + hostname casing
   - Resolve obvious redirect wrappers where possible
2. **Assign source trust tier**
   - Tier 1: primary sources (company blogs, filings, official announcements)
   - Tier 2: established publications
   - Tier 3: social/aggregators
3. **Claim verification rule**
   - Numeric claims (funding amount, valuation, user counts, percentages) require either:
     - one Tier 1 source, or
     - two independent non-identical sources
   - If not verified, the draft must label the claim as unverified or omit it
4. **Recency rule**
   - Every included story must have a publish timestamp within the current issue window
   - If timestamp is missing, mark as low-confidence and require explicit inclusion decision in planning
5. **Citation retention**
   - Keep `source_url`, `source_name`, `published_at`, and `confidence` for each story item

---

## The Brain — Deduplication System

### File: `data/published_stories.md`

A condensed markdown file that serves as the agent's memory of everything it has ever published.

### Format

```markdown
# Published Newsletter Stories

## 2026-02-27
- OpenAI releases GPT-5 with native agent capabilities | https://techcrunch.com/2026/02/25/openai-gpt5
- Anthropic raises $5B Series D at $60B valuation | https://crunchbase.com/funding/anthropic-series-d
- Salesforce deploys 10,000 AI agents internally, reports 40% efficiency gain | https://venturebeat.com/2026/02/24/salesforce-ai-agents

## 2026-02-20
- Google Gemini 3.0 launches with real-time web browsing | https://blog.google/gemini-3
- Cognition raises $200M Series B for Devin AI coding agent | https://techcrunch.com/2026/02/18/cognition-devin-funding
- Microsoft reports 60% of Fortune 500 using Copilot agents | https://venturebeat.com/2026/02/17/microsoft-copilot-adoption

## 2026-02-13
...
```

### How Dedup Works

1. **Before research:** Load `published_stories.md` and extract all titles + URLs
2. **After gathering news:** For each candidate story, check:
   - **URL match:** Is the exact URL already in the brain? → Skip
   - **Title similarity:** Is there a title in the brain that is >80% similar? → Skip (catches same story from different sources)
   - **Follow-up detection:** Send ambiguous cases to Claude (Haiku) with prompt: *"Is this a genuinely new development, or a follow-up/rehash of the previously published story?"*
3. **After sending:** Append new stories to the brain file in condensed one-line format

### Brain File Maintenance

- The file grows by ~5-10 lines per week (50-500 lines per year)
- Once a year, archive entries older than 6 months to `data/archive/` to keep the active file small
- The agent only loads the last 3 months of entries for dedup checks (configurable)

---

## Newsletter Composition

### Step 1: Planning (Claude via OpenRouter)

After collecting Slack updates + research, send everything to Claude with a planning prompt:

```
You are a newsletter editor for a company that builds AI agents (human emulators)
for enterprise clients. Plan this week's newsletter.

TEAM UPDATES FROM SLACK:
{slack_messages}

INDUSTRY NEWS (already deduplicated, with source metadata):
{research_results}

Each news item includes: title, source_url, source_name, published_at, confidence
(high/medium/low), and source_tier (1=primary, 2=publication, 3=social/aggregator).

RULES:
- Numeric claims (funding amounts, valuations, user counts, percentages) require
  confidence "high" (backed by a Tier 1 source or two independent sources).
  If a story has confidence "medium" or "low", either omit the specific numbers
  or label them as "reportedly" / "according to unconfirmed reports."
- Only include stories with a published_at timestamp within the current issue window.
  Stories marked low-confidence due to missing timestamps should only be included
  if they are highly relevant and no better-sourced alternative exists.

Create a newsletter outline with:
1. SECTION 1 — "What We've Been Up To" (team updates, if any)
   - Summarize each update into a compelling narrative
   - If no updates, skip this section entirely
2. SECTION 2 — "This Week in AI" (top 3-5 industry stories)
   - Pick the stories most relevant to our audience (potential clients and investors
     interested in AI agents, digital labor, enterprise automation)
   - For each story: one-line hook, why it matters, link, confidence level
3. CTA — Always end with an invitation to get in touch about AI agent projects
   or investment opportunities

Output the plan as structured JSON.
```

### Step 2: Draft Content (Claude via OpenRouter)

Take the plan and have Claude generate structured content JSON (not HTML):

```
You are writing a weekly newsletter for a company that builds AI agents (human
emulators) for enterprise clients. The audience is potential clients, investors,
and AI enthusiasts.

Write in a tone that is:
- Professional but not stuffy
- Excited about AI but not breathlessly hypey
- Authoritative — we build this stuff, we know what we're talking about
- Brief — respect the reader's time

NEWSLETTER PLAN:
{plan_json}

Output valid JSON only with this schema:
{
  "newsletter_name": "string",
  "issue_date": "YYYY-MM-DD",
  "subject_line": "string",
  "preheader": "string",
  "intro": "string",
  "team_updates": [{"title":"string","summary":"string"}],
  "industry_stories": [{
    "headline":"string",
    "hook":"string",
    "why_it_matters":"string",
    "source_url":"https://...",
    "source_name":"string",
    "published_at":"ISO-8601",
    "confidence":"high|medium|low"
  }],
  "cta": {"text":"string","url":"https://..."}
}
```

### Step 3: Deterministic HTML Rendering

Render the final email with `templates/newsletter_base.html` (Jinja2) using only the JSON fields:

- Escape all LLM-provided text by default
- Do not allow raw HTML from the model
- Enforce deterministic section order and formatting
- Require `{{{RESEND_UNSUBSCRIBE_URL}}}` in footer

Pre-send validation checks:
- HTML size and section presence checks pass
- Every link is absolute `https://`
- Every industry story includes `source_url`, `source_name`, `published_at`, `confidence`
- No missing unsubscribe placeholder

### Step 4: Post Draft to Slack

Format the draft for Slack display using Block Kit (simplified version of the HTML) and post it to `#newsletter-updates` with:

> **Newsletter Draft — Week of [date]**
> [Formatted preview of the newsletter content]
> ---
> *Review this draft. Reply with feedback to request changes, or say **"approved"** to send it out.*

---

## Feedback & Redraft Loop

### How It Works

After the draft is posted to Slack:

1. **User replies with feedback** (e.g., "Change the section about Anthropic funding — the amount is wrong, it was $4B not $5B" or "Add a mention of our new healthcare client")
2. **Bot detects the reply** is in the thread of a draft post
3. **Bot sends the current draft JSON + feedback to Claude** with prompt:
   > "Here is the current newsletter draft JSON and feedback from the team. Revise the JSON to incorporate the feedback. Keep everything else the same unless the feedback specifically asks for changes. Return valid JSON only."
4. **Bot posts the revised draft** as a new message in the channel (not in the thread) with:
   > **Newsletter Draft v2 — Week of [date]**
   > [Updated content]
   > ---
   > *Revision based on feedback from @user. Reply with more feedback or say **"approved"** to send.*
5. **Loop continues** — more feedback → more revisions → until "approved"
6. **Redraft cap** — Maximum of **5 revision cycles** (`MAX_DRAFT_VERSIONS=5`). After v5, the bot posts: *"Maximum revisions reached. Please edit the newsletter manually or say 'reset' to trigger a fresh research + draft cycle."* This prevents runaway Claude API costs from contradictory or endless feedback.

### Tracking Draft State

The bot maintains run state (in-memory cache backed by persisted run ledger):
- `current_draft_ts` — Slack timestamp of the most recent draft message
- `current_draft_json` — Structured newsletter content
- `current_draft_html` — The full HTML content of the current draft
- `current_draft_version` — Version counter (v1, v2, v3... up to MAX_DRAFT_VERSIONS)
- `draft_status` — `"pending_review"` | `"approved"` | `"sent"` | `"max_revisions_reached"`

When a new draft is posted, the previous draft's tracking is replaced. Only the latest draft can be approved.

---

## Approval & Send Flow

### Trigger

Any user in `#newsletter-updates` replies with "approved" (case-insensitive, can be part of a longer message like "Looks good, approved!").

### Validation

Before sending, the bot checks:
- Is there an active draft in `pending_review` status?
- Is the draft less than 48 hours old? (Stale drafts require re-research)

### Send Sequence

1. Bot acknowledges: *"Approval received from @user. Preparing to send..."*
2. Format the final HTML email (already generated during writing step)
3. Call Resend Broadcast API:
   - Create a broadcast with the HTML content
   - Target the newsletter audience/segment
   - Trigger the send
4. Update brain file (`data/published_stories.md`) with the stories included
5. Post confirmation: *"Newsletter sent successfully to [X] subscribers."*
6. Set `draft_status = "sent"`

### If Send Fails

- Bot posts error to Slack: *"Failed to send newsletter: [error]. Please try again or contact admin."*
- Draft remains in `pending_review` so someone can say "approved" again after the issue is fixed

---

## Operational Safety & Recovery

### Reliability Rules

1. **Run-level idempotency**
   - Every Thursday run gets a `newsletter_run_id` (e.g., `2026-02-26-weekly`)
   - Any send attempt must reference this run ID
   - Duplicate send attempts for the same run ID are blocked once marked sent
2. **Send ledger**
   - Persist states: `draft_ready` -> `send_requested` -> `render_validated` -> `broadcast_created` -> `broadcast_sent` -> `brain_updated`
   - `render_validated` confirms the Jinja2 render and pre-send validation (links, unsubscribe placeholder, schema) passed before calling Resend
   - If render/validation fails after approval, the ledger stays at `send_requested` and the bot posts the validation errors to Slack so the team can fix and re-approve
   - On restart, resume from the last incomplete state instead of re-running everything
3. **Retry policy**
   - Retry external calls (OpenRouter, RSS fetch, Resend) with exponential backoff + jitter
   - Cap retries and surface final failure to Slack
4. **Dead-letter capture**
   - Store unrecoverable failures in `data/failures/` with payload + error metadata + timestamp
   - Include a replay command path for manual recovery
5. **Data backup**
   - On each successful `brain_updated` state, copy `run_state.db` to `run_state.db.bak`
   - Weekly backup of `published_stories.md` to `data/archive/published_stories_YYYY-MM-DD.md`
   - If the persistent volume is ever lost, the archive copies allow recovery
6. **Run lock**
   - Only one weekly pipeline run can execute at a time
   - If another trigger happens during an active run, reject it with a clear Slack status message

### Observability

- Post a short status update to Slack at each major stage: research started, draft posted, send started, send completed/failed
- Log structured events with `newsletter_run_id`, `draft_version`, and external request IDs
- Emit a single summary log line at end of run with total stories considered, selected, sent, and skipped

---

## Email Sending — Resend

### Why Resend

- Modern Broadcast API designed for programmatic newsletter sends
- Full custom HTML support (no template restrictions)
- Free tier: 3,000 emails/month, 1,000 contacts
- Automatic unsubscribe handling via `{{{RESEND_UNSUBSCRIBE_URL}}}`
- Python SDK available

### API Flow

```python
from resend import Resend

resend = Resend(api_key=os.environ["RESEND_API_KEY"])

# 1. Create the broadcast
broadcast = resend.broadcasts.create({
    "audience_id": os.environ["RESEND_AUDIENCE_ID"],
    "from": "newsletter@yourdomain.com",
    "subject": f"This Week in AI — {date_string}",
    "html": final_html_content,
})

# 2. Send it
resend.broadcasts.send(broadcast["id"])
```

### Resend Setup Steps

1. Create a Resend account at resend.com
2. Verify your sending domain (add DNS records)
3. Create an Audience (subscriber segment) in the dashboard
4. Generate an API key
5. Note the Audience ID for the environment variable

---

## Newsletter Signup — Webflow Integration

### Approach: Shareable Signup Link

Since the website is on Webflow and you just need a link to share, there are two clean options:

### Option A: Resend-Powered Signup Page (Recommended)

Build a minimal standalone signup page hosted on Vercel (free) that:
1. Shows a simple form: email input + "Subscribe" button
2. On submit, calls a serverless function that hits the Resend Contacts API
3. Confirms subscription

**Serverless function (Vercel, `api/subscribe.py`):**
```python
from http.server import BaseHTTPRequestHandler
import json, os
from resend import Resend

resend = Resend(api_key=os.environ["RESEND_API_KEY"])

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        resend.contacts.create({
            "email": body["email"],
            "audience_id": os.environ["RESEND_AUDIENCE_ID"],
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"success": True}).encode())
```

You get a link like `https://newsletter.yourdomain.com` that you can share anywhere.

### Option B: Webflow Form + Webhook

1. Add a form in Webflow with an email field
2. Use Webflow's form submission webhook (or a Zapier/Make integration) to POST the email to a serverless function
3. Serverless function calls `resend.contacts.create()`

Option A is simpler and doesn't depend on the Webflow site being live.

### What You Share

Either way, you end up with a URL you can:
- Put on your website ("Join our newsletter" button links to it)
- Share on social media
- Include in email signatures
- Drop in Slack communities

---

## Hosting — Railway

### Why Railway

- Simple deployment from a GitHub repo
- Worker process support (no HTTP port needed for Socket Mode)
- $5/month Hobby plan with enough credits for an always-on lightweight bot
- Built-in environment variable management
- Logs and monitoring in the dashboard

### Setup Steps

1. Create a Railway account at railway.app
2. Connect your GitHub repo
3. Create a new project → "Deploy from GitHub repo"
4. Set the start command: `python bot.py`
5. Add all environment variables (see section below)
6. Railway detects it's a worker process (no PORT binding) and runs it accordingly

### Procfile

```
worker: python bot.py
```

### Dockerfile (alternative)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

### Persistent Storage for Brain File

Railway supports persistent volumes. Attach a volume to `/app/data/` so the `published_stories.md` file persists across deploys and restarts. Alternatively, store the brain file in a simple cloud storage (S3, or even commit it back to the git repo via a GitHub Action).

---

## Project Structure

```
newsletter-bot/
├── bot.py                      # Entry point: initializes Slack Bolt + APScheduler
├── config.py                   # All configuration: channel IDs, model IDs, env vars
├── scheduler.py                # APScheduler setup, Thursday research trigger
│
├── listeners/
│   ├── __init__.py
│   ├── approval.py             # Detects "approved", triggers send pipeline
│   ├── feedback.py             # Detects draft feedback, triggers redraft
│   └── updates.py              # Validates team updates, asks clarifying Qs
│
├── services/
│   ├── __init__.py
│   ├── llm.py                  # OpenRouter client wrapper (Perplexity + Claude)
│   ├── slack_reader.py         # Fetch channel messages for a date range
│   ├── rss_reader.py           # Parse RSS feeds, extract articles
│   ├── news_researcher.py      # Perplexity queries for industry news
│   ├── quality.py              # URL canonicalization + source confidence checks
│   ├── brain.py                # Read/write/query published_stories.md
│   ├── planner.py              # Claude plans newsletter structure
│   ├── writer.py               # Claude writes structured newsletter JSON
│   ├── renderer.py             # Jinja2 render: JSON -> deterministic HTML
│   ├── formatter.py            # Format newsletter for Slack Block Kit preview
│   ├── sender.py               # Resend Broadcast API integration
│   ├── run_state.py            # Run ledger + idempotency state persistence
│   └── validator.py            # Claude checks if Slack updates make sense
│
├── templates/
│   └── newsletter_base.html    # Base HTML email template (responsive)
│
├── data/
│   ├── published_stories.md    # The brain — all previously published stories
│   ├── run_state.db            # SQLite ledger for runs/drafts/sends
│   ├── failures/               # Dead-letter events for manual replay
│   └── archive/                # Archived old brain entries (6+ months)
│
├── signup/                     # Standalone signup page (deployed to Vercel)
│   ├── index.html              # Simple email signup form
│   └── api/
│       └── subscribe.py        # Serverless function → Resend Contacts API
│
├── tests/
│   ├── test_brain.py
│   ├── test_rss_reader.py
│   ├── test_news_researcher.py
│   ├── test_writer.py
│   ├── test_renderer.py
│   ├── test_quality.py
│   └── test_send_idempotency.py
│
├── requirements.txt
├── Dockerfile
├── Procfile
├── .env.example
├── .gitignore
└── README.md
```

---

## Environment Variables

```bash
# OpenRouter (single key for all LLM calls)
OPENROUTER_API_KEY=sk-or-v1-xxxxx

# Slack
SLACK_BOT_TOKEN=xoxb-xxxxx          # Bot user OAuth token
SLACK_APP_TOKEN=xapp-xxxxx          # App-level token (Socket Mode)
NEWSLETTER_CHANNEL_ID=C0123456789   # #newsletter-updates channel ID

# Resend
RESEND_API_KEY=re_xxxxx
RESEND_AUDIENCE_ID=aud_xxxxx
NEWSLETTER_FROM_EMAIL=newsletter@yourdomain.com

# Configuration
TIMEZONE=America/Chicago
RESEARCH_DAY=thu                    # Day of week to run research
RESEARCH_HOUR=9                     # Hour (in TIMEZONE) to run research
BRAIN_FILE_PATH=data/published_stories.md
DEDUP_LOOKBACK_WEEKS=12             # How many weeks of brain history to check
RUN_STATE_DB_PATH=data/run_state.db
FAILURE_LOG_DIR=data/failures
MAX_EXTERNAL_RETRIES=4
MAX_DRAFT_VERSIONS=5                # Cap redraft cycles to prevent runaway costs
ENABLE_DRY_RUN=true                 # Dry run mode: executes entire pipeline (research, write,
                                    # post draft to Slack, accept approval, render HTML) but
                                    # replaces the Resend broadcast send with a log-only action.
                                    # Set to true in staging, false in production.
```

---

## Dependencies

### `requirements.txt`

```
slack-bolt>=1.18.0
openai>=1.0.0              # OpenAI-compatible client for OpenRouter
feedparser>=6.0.0          # RSS feed parsing
resend>=0.7.0              # Email sending
APScheduler>=3.10.0        # In-process scheduling
python-dotenv>=1.0.0       # Environment variable loading
tenacity>=8.0.0            # Retry logic with exponential backoff
beautifulsoup4>=4.12.0     # HTML parsing for RSS content cleanup
markdownify>=0.11.0        # Convert HTML to markdown (for Slack preview)
jinja2>=3.1.0              # Deterministic HTML template rendering
jsonschema>=4.0.0          # Validate model JSON output shape
```

---

## Setup Checklist

### 1. Slack App Setup
- [ ] Go to api.slack.com/apps → Create New App → "From scratch"
- [ ] Name: "Newsletter Agent" (or whatever you prefer)
- [ ] Enable Socket Mode (Settings → Socket Mode → toggle on)
- [ ] Generate App-Level Token with `connections:write` scope → save as `SLACK_APP_TOKEN`
- [ ] Add Bot Token Scopes: `channels:history`, `channels:read`, `chat:write`, `users:read`, `reactions:read`, `reactions:write`
- [ ] Subscribe to bot events: `message.channels`
- [ ] Install app to workspace → save Bot Token as `SLACK_BOT_TOKEN`
- [ ] Create `#newsletter-updates` channel
- [ ] Invite the bot to the channel: `/invite @Newsletter Agent`
- [ ] Note the channel ID (right-click channel name → "Copy link" → ID is in the URL)

### 2. OpenRouter Setup
- [ ] Create account at openrouter.ai
- [ ] Add credits ($10 to start — will last months)
- [ ] Generate API key → save as `OPENROUTER_API_KEY`

### 3. Resend Setup
- [ ] Create account at resend.com
- [ ] Add and verify your sending domain (DNS records)
- [ ] Create an Audience in the dashboard → note the Audience ID
- [ ] Generate API key → save as `RESEND_API_KEY`
- [ ] Add yourself as a test contact

### 4. Railway Setup
- [ ] Create account at railway.app
- [ ] Connect GitHub account
- [ ] Create new project → Deploy from GitHub repo
- [ ] Add all environment variables in Railway dashboard
- [ ] Attach a persistent volume at `/app/data/` (for the brain file)
- [ ] Deploy and verify the bot comes online in Slack

### 5. Signup Page Setup
- [ ] Deploy the signup page to Vercel (or Netlify)
- [ ] Configure environment variables (RESEND_API_KEY, RESEND_AUDIENCE_ID)
- [ ] (Optional) Connect a custom domain like `newsletter.yourdomain.com`
- [ ] Test the signup flow end-to-end

---

## Testing & Launch Readiness

### Required Test Coverage

- [ ] Unit: RSS parser handles missing dates, malformed feeds, and duplicate URLs
- [ ] Unit: quality checks correctly canonicalize URLs and assign confidence tiers
- [ ] Unit: writer returns schema-valid JSON only
- [ ] Unit: renderer output always contains unsubscribe placeholder and valid links
- [ ] Unit: send idempotency blocks duplicate sends for same `newsletter_run_id`
- [ ] Integration: one full dry run from Slack updates -> draft -> approval -> simulated send

### Staging Dry-Run Gate (Before First Live Send)

- [ ] Create a staging Resend audience (internal emails only)
- [ ] Set `ENABLE_DRY_RUN=true` and run at least one scheduled Thursday dry run
- [ ] Manually trigger one additional dry run to verify retry + failure handling paths
- [ ] Review generated HTML in real inbox clients (Gmail + Apple Mail + Outlook at minimum)
- [ ] Confirm logs and Slack status messages are clear enough for operational debugging
- [ ] Only after passing all checks, switch `ENABLE_DRY_RUN=false` for first production send

---

## Estimated Costs

### Monthly Costs

| Item | Cost |
|---|---|
| Railway (Hobby plan) | $5/mo |
| OpenRouter credits (Perplexity + Claude, ~4 runs/mo) | $1-2/mo |
| Resend (free tier: 3K emails/mo, 1K contacts) | $0/mo |
| Vercel (signup page, free tier) | $0/mo |
| RSS feeds | $0 |
| **Total** | **~$6-7/mo** |

### When You Scale

| Milestone | Change | Additional Cost |
|---|---|---|
| >1,000 subscribers | Resend Pro plan | $20/mo |
| >3,000 emails/mo | Resend Pro plan covers 50K | (included in $20) |
| >50,000 emails/mo | Resend Scale plan | $90/mo |
| More Perplexity queries | Sonar Pro for deeper research | +$5-10/mo |
| More redraft cycles | More Claude calls | +$1-2/mo |

---

## Future Enhancements

These are NOT in the initial build but could be added later:

1. **A/B subject line testing** — Generate 2 subject lines with Claude, use Resend's A/B testing feature
2. **Analytics dashboard** — Track open rates, click rates via Resend webhooks, post weekly stats to Slack
3. **Multiple newsletter segments** — Different content for investors vs. potential clients vs. general audience
4. **Automated LinkedIn/Twitter posting** — Post a teaser of the newsletter to social media
5. **Archive page** — Public web page with past newsletters (SEO value)
6. **Reader feedback loop** — Include a "Was this useful?" link in the newsletter, feed responses back to the agent
7. **Multi-channel updates** — Accept updates from multiple Slack channels or other sources (email, forms)
8. **Image generation** — Generate custom header images for each newsletter using an image model
9. **Referral program** — Use Resend + custom logic to reward subscribers who refer others

---

## Implementation Order

Build in this sequence, testing each piece before moving to the next:

### Phase 1: Foundation (Day 1)
1. Project setup (repo, dependencies, config)
2. OpenRouter client wrapper (test Perplexity + Claude calls)
3. Brain file system (read/write/dedup logic)

### Phase 2: Research Pipeline (Day 2)
4. RSS feed reader (parse all 10 feeds)
5. Perplexity news researcher (5 queries)
6. Merge + dedup logic + data quality checks
7. Newsletter planner (Claude plans the structure)
8. Newsletter writer (Claude writes structured JSON)
9. Deterministic renderer (JSON -> HTML template)

### Phase 3: Slack Bot (Day 3)
10. Slack Bolt setup (Socket Mode, basic listeners)
11. Update validator (clarifying questions in threads)
12. Draft posting (Block Kit formatted preview)
13. Feedback/redraft loop
14. Approval detection

### Phase 4: Email Sending (Day 4)
15. Resend integration (create broadcast, send)
16. Run-state ledger + idempotent send protection
17. Brain file update after send
18. End-to-end test (Slack -> research -> write -> approve -> send)

### Phase 5: Deployment (Day 5)
19. Railway deployment
20. Signup page (Vercel)
21. Staging dry run against test audience
22. Production testing with real data
23. First live newsletter send
