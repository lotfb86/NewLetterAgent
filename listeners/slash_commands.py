"""Slash command handlers for the newsletter agent."""

from __future__ import annotations

import logging
import threading
from typing import Any

from listeners.approval import ApprovalHandler
from services.command_controller import CommandController
from services.contact_importer import ContactImporter

logger = logging.getLogger(__name__)

_HELP_TEXT = """\
*The Ruh Digest — Newsletter Agent*

*How it works:*
:one: *Collect* — Post team updates as messages in this channel anytime during the week.
:two: *Research* — Every Thursday at 9am CT, the agent automatically collects team updates from the last 7 days, researches AI industry news, and generates a newsletter draft. (You can also trigger this manually with `/run`.)
:three: *Review* — The draft is posted here for review. Reply in the draft thread with feedback to request changes — the agent will revise automatically.
:four: *Send* — When the draft looks good, say "approved" in the thread or use `/approve`. The newsletter goes out to all subscribers immediately.

*Commands:*
• `/run` — Manually trigger a research + draft cycle
• `/reset` — Clear current draft and start a fresh cycle
• `/replay <run_id>` — Retry a previously failed run
• `/approve` — Approve the current draft and send it
• `/import-contacts <emails>` — Add subscribers (inline or CSV upload)
• `/help` — Show this message

*Importing contacts:*
Inline: `/import-contacts user@example.com, user2@example.com`
CSV: Upload a file with an "email" column, then run `/import-contacts`
"""


class SlashCommandHandlers:
    """Container for all slash command handler methods."""

    def __init__(
        self,
        *,
        command_controller: CommandController,
        approval_handler: ApprovalHandler,
        contact_importer: ContactImporter,
        orchestrator: Any,
        slack_client: Any,
        channel_id: str,
    ) -> None:
        self._command_controller = command_controller
        self._approval_handler = approval_handler
        self._contact_importer = contact_importer
        self._orchestrator = orchestrator
        self._slack_client = slack_client
        self._channel_id = channel_id

    def handle_run(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /run — trigger a manual research + draft generation."""
        ack("Starting manual run... This may take a few minutes. :rocket:")

        def _run() -> None:
            try:
                result = self._command_controller.manual_run()
                if result.accepted:
                    respond("Manual run completed. Draft has been posted for review. :white_check_mark:")
                else:
                    respond(f"Manual run could not start: {result.reason}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Slash /run failed")
                respond(f"Run failed with error: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def handle_reset(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /reset — clear state and run a fresh cycle."""
        ack("Resetting and starting fresh cycle... :arrows_counterclockwise:")

        def _reset() -> None:
            try:
                result = self._command_controller.reset()
                if result.accepted:
                    respond("Reset completed. Fresh draft has been posted. :white_check_mark:")
                else:
                    respond(f"Reset could not start: {result.reason}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Slash /reset failed")
                respond(f"Reset failed with error: {exc}")

        threading.Thread(target=_reset, daemon=True).start()

    def handle_replay(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /replay <run_id> — replay a previously failed run."""
        run_id = (command.get("text") or "").strip()
        if not run_id:
            ack("Usage: `/replay <run_id>` — provide the run ID to replay.")
            return

        ack(f"Replaying run `{run_id}`... :repeat:")

        def _replay() -> None:
            try:
                result = self._command_controller.replay(run_id)
                if result.accepted:
                    respond(f"Replay of `{run_id}` completed. :white_check_mark:")
                else:
                    respond(f"Replay failed: {result.reason}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Slash /replay failed")
                respond(f"Replay failed with error: {exc}")

        threading.Thread(target=_replay, daemon=True).start()

    def handle_approve(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /approve — approve latest pending draft and send."""
        ack("Processing approval... :email:")

        def _approve() -> None:
            try:
                outcome = self._approval_handler.handle_slash()
                if outcome.accepted and outcome.run_id:
                    send_outcome = self._orchestrator.send_approved_run(run_id=outcome.run_id)
                    if send_outcome.accepted:
                        respond("Newsletter approved and sent! :tada:")
                    else:
                        respond(
                            f"Draft approved but send failed: {send_outcome.reason}. "
                            "Check logs for details."
                        )
                else:
                    messages = {
                        "no_active_draft": "No active draft found. Run `/run` first.",
                        "draft_not_pending": "Draft is not pending review.",
                        "draft_stale": (
                            "Draft is stale (>48h). "
                            "Use `/reset` for a fresh research run before approval."
                        ),
                        "draft_missing_ts": "Draft metadata is incomplete. Please `/reset` and rerun.",
                    }
                    respond(messages.get(outcome.reason, f"Approval rejected: {outcome.reason}"))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Slash /approve failed")
                respond(f"Approval failed with error: {exc}")

        threading.Thread(target=_approve, daemon=True).start()

    def handle_import_contacts(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /import-contacts — bulk import subscribers."""
        inline_text = (command.get("text") or "").strip()
        ack("Processing contact import... :busts_in_silhouette:")

        def _import() -> None:
            try:
                if inline_text:
                    valid, invalid = self._contact_importer.parse_inline(inline_text)
                else:
                    # Look for recent CSV file uploads in channel
                    csv_content = self._find_recent_csv()
                    if csv_content is None:
                        respond(
                            "No emails provided and no recent CSV found.\n\n"
                            "*Usage:*\n"
                            "• `/import-contacts user@example.com, user2@example.com`\n"
                            "• Upload a CSV file with an 'email' column, then run `/import-contacts`"
                        )
                        return
                    try:
                        valid, invalid = self._contact_importer.parse_csv(csv_content)
                    except ValueError as exc:
                        respond(f"CSV parsing error: {exc}")
                        return

                if not valid and invalid:
                    respond(
                        f"No valid emails found. Invalid entries: {', '.join(invalid[:10])}"
                    )
                    return

                if not valid:
                    respond("No emails found to import.")
                    return

                # Report invalid emails before importing valid ones
                parts: list[str] = []
                if invalid:
                    parts.append(
                        f":warning: {len(invalid)} invalid "
                        f"{'entry' if len(invalid) == 1 else 'entries'} "
                        f"skipped: {', '.join(invalid[:5])}"
                        + ("..." if len(invalid) > 5 else "")
                    )

                result = self._contact_importer.import_contacts(valid)

                parts.append(
                    f":white_check_mark: *{result.imported}* imported, "
                    f"*{result.duplicates}* already existed, "
                    f"*{result.failures}* failed"
                )

                if result.failed_emails:
                    parts.append(
                        f"Failed emails: {', '.join(result.failed_emails[:5])}"
                        + ("..." if len(result.failed_emails) > 5 else "")
                    )

                respond("\n".join(parts))

            except Exception as exc:  # noqa: BLE001
                logger.exception("Slash /import-contacts failed")
                respond(f"Import failed with error: {exc}")

        threading.Thread(target=_import, daemon=True).start()

    def handle_help(self, ack: Any, respond: Any, command: dict[str, Any]) -> None:
        """Handle /help — show available commands."""
        ack()
        respond(_HELP_TEXT)

    def _find_recent_csv(self) -> bytes | None:
        """Search last 10 channel messages for a CSV file upload."""
        try:
            result = self._slack_client.conversations_history(
                channel=self._channel_id,
                limit=10,
            )
            messages = result.get("messages") or result.data.get("messages", [])

            for msg in messages:
                files = msg.get("files") or []
                for f in files:
                    name = (f.get("name") or "").lower()
                    mimetype = (f.get("mimetype") or "").lower()
                    if name.endswith(".csv") or "csv" in mimetype:
                        url = f.get("url_private_download") or f.get("url_private")
                        if url:
                            return self._download_file(url)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to search for CSV files in channel", exc_info=True)

        return None

    def _download_file(self, url: str) -> bytes:
        """Download a file from Slack using bot token auth."""
        import requests

        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._slack_client.token}"},
            timeout=15,
        )
        response.raise_for_status()
        return response.content
