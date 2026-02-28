# Launch Checklist

## Staging Dry Run (IMP-113)
- Configure staging env vars and staging Resend audience.
- Set `ENABLE_DRY_RUN=true`.
- Run one scheduled cycle.
- Run one manual `run` cycle.
- Verify Slack status posts and heartbeat.
- Verify rendered HTML in Gmail/Apple Mail/Outlook.

## Production Go-Live (IMP-114)
- Confirm staging checklist complete.
- Switch `ENABLE_DRY_RUN=false` in production only.
- Verify production audience and sender domain.
- Trigger first production send and verify `brain_updated` stage.

## Retrospective (IMP-115)
Document after first production send:
- Timeline of run + send.
- Incidents and mitigation.
- Operator pain points.
- Backlog follow-ups and owners.
