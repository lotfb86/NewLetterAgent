# Environment Configuration

Use `.env.example` as the source list for required variables.

## Staging
- `ENABLE_DRY_RUN=true`
- Use staging Slack channel and staging Resend audience.
- Keep `SIGNUP_ALLOWED_ORIGINS` restricted to staging domains.

## Production
- `ENABLE_DRY_RUN=false`
- Use production Slack channel and production Resend audience.
- Set production signup origins only.

## Validation Steps
1. Run `python -c "from config import get_config; get_config(load_dotenv_file=True); print('ok')"`.
2. Start worker (`python bot.py`) and confirm startup without config errors.
3. Confirm heartbeat message appears in configured heartbeat channel.
