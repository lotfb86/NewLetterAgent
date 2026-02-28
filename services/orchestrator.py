"""End-to-end orchestration for run, draft, send, and recovery flows."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from config import AppConfig
from models import DraftStatus, RunStage
from services.backups import backup_brain_snapshot, backup_run_state_db
from services.brain import append_published_stories, read_published_stories
from services.context_state import ConversationState
from services.draft_manager import DraftManager
from services.failures import save_dead_letter
from services.formatter import SlackPreviewFormatter
from services.observability import LogContext, StructuredLogger, get_logger
from services.planner import NewsletterPlanner
from services.renderer import NewsletterRenderer
from services.research_pipeline import ResearchPipeline
from services.run_state import RunStateError, RunStateStore
from services.sender import ResendSender
from services.validator import validate_https_links, validate_rendered_html
from services.writer import NewsletterWriter


@dataclass(frozen=True)
class OrchestrationOutcome:
    """Result for manual/scheduled command handlers."""

    accepted: bool
    reason: str
    run_id: str | None = None
    draft_version: int | None = None


class NewsletterOrchestrator:
    """Coordinate weekly runs, redrafts, sends, and recovery."""

    def __init__(
        self,
        *,
        config: AppConfig,
        run_state: RunStateStore,
        draft_manager: DraftManager,
        context_state: ConversationState,
        research_pipeline: ResearchPipeline,
        planner: NewsletterPlanner,
        writer: NewsletterWriter,
        renderer: NewsletterRenderer,
        formatter: SlackPreviewFormatter,
        sender: ResendSender,
        slack_client: Any,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._config = config
        self._run_state = run_state
        self._draft_manager = draft_manager
        self._context_state = context_state
        self._research_pipeline = research_pipeline
        self._planner = planner
        self._writer = writer
        self._renderer = renderer
        self._formatter = formatter
        self._sender = sender
        self._slack_client = slack_client
        self._logger = logger or get_logger()

    def trigger_run(self, *, trigger: str, requested_by: str | None = None) -> OrchestrationOutcome:
        """Run research and draft generation if run lock is available."""
        run_id = self._generate_run_id(trigger)
        if not self._run_state.try_acquire_run_lock(run_id):
            locked = self._run_state.get_locked_run_id()
            return OrchestrationOutcome(
                accepted=False,
                reason=f"run_locked:{locked or 'unknown'}",
                run_id=locked,
            )

        context = LogContext(run_id=run_id)
        try:
            self._run_state.create_run(
                run_id,
                payload={
                    "trigger": trigger,
                    "requested_by": requested_by,
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )
            self._logger.info(
                "run_started",
                context=context,
                trigger=trigger,
                requested_by=requested_by,
            )
            return self._execute_draft_generation(run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            self._logger.error("run_failed", context=context, error=str(exc))
            self._record_failure(
                run_id=run_id,
                stage="run",
                error=str(exc),
                payload={"trigger": trigger},
            )
            self._post_status(
                f"Run `{run_id}` failed during draft generation: {exc}",
            )
            return OrchestrationOutcome(accepted=False, reason="run_failed", run_id=run_id)
        finally:
            self._run_state.release_run_lock(run_id)

    def reset_and_trigger_run(self, *, requested_by: str | None = None) -> OrchestrationOutcome:
        """Clear active draft state and trigger a fresh run."""
        self._draft_manager.clear_current_draft()
        self._context_state.mark_not_sent()
        return self.trigger_run(trigger="reset", requested_by=requested_by)

    def build_feedback_revision(self, *, feedback_text: str) -> tuple[dict[str, Any], str, str]:
        """Build revised draft payload and post a new draft version."""
        current = self._draft_manager.get_current_draft()
        if current is None or current.draft_json is None:
            raise ValueError("No current draft available")

        current_payload = _parse_json_dict(current.draft_json)
        revised_payload = self._writer.revise_newsletter(
            current_draft=current_payload,
            feedback_text=feedback_text,
        )
        revised_html = self._renderer.render(revised_payload)
        next_version = current.draft_version + 1
        draft_ts = self._post_draft_preview(
            newsletter_payload=revised_payload,
            header=(
                f"Newsletter Draft v{next_version} - "
                f"Week of {revised_payload.get('issue_date', 'unknown')}"
            ),
            footer=(
                "Revision based on feedback. Reply with more feedback or say *approved* to send."
            ),
        )
        self._patch_run_from_newsletter(current.run_id, revised_payload, draft_ts)
        return revised_payload, revised_html, draft_ts

    def include_late_update(self, *, thread_ts: str) -> OrchestrationOutcome:
        """Inject a late team update into active draft and redraft automatically."""
        # Check preconditions before consuming the late update so it can be
        # retried if any guard fails.
        current = self._draft_manager.get_current_draft()
        if current is None or current.draft_json is None:
            return OrchestrationOutcome(accepted=False, reason="no_active_draft")

        if current.draft_status != DraftStatus.PENDING_REVIEW:
            return OrchestrationOutcome(accepted=False, reason="draft_not_pending")

        if not self._draft_manager.has_revision_capacity():
            self._draft_manager.mark_max_revisions_reached()
            return OrchestrationOutcome(accepted=False, reason="max_revisions_reached")

        late_text = self._context_state.pop_late_update(thread_ts)
        if late_text is None:
            return OrchestrationOutcome(accepted=False, reason="no_late_update")

        payload = _parse_json_dict(current.draft_json)
        team_updates = payload.get("team_updates")
        if not isinstance(team_updates, list):
            team_updates = []

        summary = _squash_text(late_text, max_chars=280)
        team_updates.append(
            {
                "title": "Late Team Update",
                "summary": summary,
            }
        )
        payload["team_updates"] = team_updates

        html = self._renderer.render(payload)
        draft_ts = self._post_draft_preview(
            newsletter_payload=payload,
            header=(
                f"Newsletter Draft v{current.draft_version + 1} - "
                f"Week of {payload.get('issue_date', 'unknown')}"
            ),
            footer=("Late update included. Reply with more feedback or say *approved* to send."),
        )
        updated = self._draft_manager.create_revision(
            draft_json=payload,
            draft_html=html,
            draft_ts=draft_ts,
        )
        self._patch_run_from_newsletter(updated.run_id, payload, draft_ts)
        return OrchestrationOutcome(
            accepted=True,
            reason="included",
            run_id=updated.run_id,
            draft_version=updated.draft_version,
        )

    def send_approved_run(self, *, run_id: str) -> OrchestrationOutcome:
        """Execute send pipeline from current ledger stage for approved run."""
        return self._resume_send_pipeline(run_id)

    def replay_run(self, *, run_id: str) -> OrchestrationOutcome:
        """Manually replay failed run or resume send sequence."""
        run = self._run_state.get_run(run_id)
        if run is None:
            return OrchestrationOutcome(accepted=False, reason="run_not_found", run_id=run_id)

        if not self._run_state.try_acquire_run_lock(run_id):
            return OrchestrationOutcome(accepted=False, reason="run_locked", run_id=run_id)

        try:
            if run.stage == RunStage.DRAFT_READY:
                draft = self._run_state.get_draft_state(run_id)
                if draft is None:
                    return self._execute_draft_generation(run_id=run_id)
            return self._resume_send_pipeline(run_id)
        finally:
            self._run_state.release_run_lock(run_id)

    def resume_incomplete_runs(self) -> list[OrchestrationOutcome]:
        """Resume incomplete runs at startup where safe to do so."""
        outcomes: list[OrchestrationOutcome] = []
        for run in self._run_state.list_incomplete_runs():
            draft = self._run_state.get_draft_state(run.run_id)
            if run.stage == RunStage.DRAFT_READY:
                if draft is None:
                    continue
                if draft.draft_status != DraftStatus.APPROVED:
                    continue
            outcomes.append(self.replay_run(run_id=run.run_id))
        return outcomes

    def post_heartbeat(self, *, next_run_at: datetime | None) -> None:
        """Post heartbeat to configured channel with scheduler state details."""
        if not self._config.heartbeat_channel_id:
            return
        next_run_text = next_run_at.isoformat() if next_run_at else "unknown"
        self._send_message(
            channel=self._config.heartbeat_channel_id,
            text=(
                "Heartbeat: newsletter agent is alive and Socket Mode is connected. "
                f"Next scheduled run: {next_run_text}."
            ),
        )

    def _execute_draft_generation(self, *, run_id: str) -> OrchestrationOutcome:
        now = datetime.now(UTC)
        start_at = now - timedelta(days=7)
        self._context_state.mark_not_sent()
        self._context_state.set_collection_cutoff(now)
        self._post_status(f"Run `{run_id}`: research started.")

        published = read_published_stories(self._config.brain_file_path)
        bundle = self._research_pipeline.run_weekly(
            start_at=start_at,
            end_at=now,
            published_stories=published,
        )
        plan = self._planner.create_plan(
            team_updates=list(bundle.team_updates),
            industry_story_inputs=list(bundle.planning_inputs),
        )

        issue_date = now.astimezone(ZoneInfo(self._config.timezone)).date().isoformat()
        newsletter_payload = self._writer.write_newsletter(
            newsletter_plan=plan,
            issue_date=issue_date,
            newsletter_name="This Week in AI",
        )
        newsletter_html = self._renderer.render(newsletter_payload)

        draft_ts = self._post_draft_preview(
            newsletter_payload=newsletter_payload,
            header=f"Newsletter Draft - Week of {issue_date}",
            footer=(
                "Review this draft. Reply with feedback to request changes, "
                "or say *approved* to send."
            ),
        )

        draft = self._draft_manager.create_or_replace_draft(
            run_id=run_id,
            draft_ts=draft_ts,
            draft_json=newsletter_payload,
            draft_html=newsletter_html,
        )
        self._patch_run_from_newsletter(run_id, newsletter_payload, draft_ts)

        self._logger.info(
            "draft_ready",
            context=LogContext(run_id=run_id, draft_version=draft.draft_version),
            story_candidates=len(bundle.candidate_stories),
            ranked_stories=len(bundle.ranked_stories),
        )
        self._post_status(f"Run `{run_id}`: draft v{draft.draft_version} posted for review.")
        return OrchestrationOutcome(
            accepted=True,
            reason="run_completed",
            run_id=run_id,
            draft_version=draft.draft_version,
        )

    def _patch_run_from_newsletter(
        self,
        run_id: str,
        newsletter_payload: dict[str, Any],
        draft_ts: str,
    ) -> None:
        subject = str(newsletter_payload.get("subject_line", "This Week in AI")).strip()
        issue_date = str(newsletter_payload.get("issue_date", ""))
        self._run_state.patch_run_payload(
            run_id,
            {
                "subject_line": subject,
                "issue_date": issue_date,
                "draft_ts": draft_ts,
            },
        )

    def _resume_send_pipeline(self, run_id: str) -> OrchestrationOutcome:
        run = self._run_state.get_run(run_id)
        if run is None:
            return OrchestrationOutcome(accepted=False, reason="run_not_found", run_id=run_id)
        if run.stage == RunStage.BRAIN_UPDATED:
            return OrchestrationOutcome(accepted=False, reason="already_sent", run_id=run_id)

        context = LogContext(run_id=run_id)

        try:
            run = self._ensure_send_requested(run)
            if run is None:
                return OrchestrationOutcome(
                    accepted=False,
                    reason="send_not_allowed",
                    run_id=run_id,
                )

            if run.stage == RunStage.SEND_REQUESTED:
                validation_errors = self._validate_current_draft_for_send(run_id)
                if validation_errors:
                    message = "; ".join(validation_errors)
                    self._run_state.set_run_error(run_id, message)
                    self._record_failure(
                        run_id=run_id,
                        stage="render_validation",
                        error=message,
                        payload={"errors": validation_errors},
                    )
                    self._post_status(
                        f"Run `{run_id}` validation failed after approval: {message}",
                    )
                    return OrchestrationOutcome(
                        accepted=False,
                        reason="render_validation_failed",
                        run_id=run_id,
                    )

                run = self._run_state.transition_run(run_id, RunStage.RENDER_VALIDATED)
                self._post_status(f"Run `{run_id}`: render validated.")

            if run.stage == RunStage.RENDER_VALIDATED:
                payload = _parse_json_dict(run.payload_json)
                draft = self._run_state.get_draft_state(run_id)
                if draft is None or draft.draft_html is None:
                    raise RunStateError("Draft HTML missing for broadcast creation")

                created = self._sender.create_broadcast(
                    audience_id=self._config.resend_audience_id,
                    from_email=self._config.newsletter_from_email,
                    subject=str(payload.get("subject_line") or "This Week in AI"),
                    html=draft.draft_html,
                )
                run = self._run_state.transition_run(
                    run_id,
                    RunStage.BROADCAST_CREATED,
                    payload_patch={
                        "broadcast_id": created.broadcast_id,
                        "broadcast_created_response": created.raw_response,
                    },
                )
                self._post_status(f"Run `{run_id}`: broadcast created ({created.broadcast_id}).")

            if run.stage == RunStage.BROADCAST_CREATED:
                payload = _parse_json_dict(run.payload_json)
                broadcast_id = str(payload.get("broadcast_id", "")).strip()
                if not broadcast_id:
                    raise RunStateError("Missing broadcast_id in run payload")

                send_result = self._sender.send_broadcast(broadcast_id=broadcast_id)
                run = self._run_state.transition_run(
                    run_id,
                    RunStage.BROADCAST_SENT,
                    payload_patch={"broadcast_send_result": send_result},
                )
                self._post_status(f"Run `{run_id}`: broadcast sent.")

            if run.stage == RunStage.BROADCAST_SENT:
                self._append_brain_entries(run_id)
                run = self._run_state.transition_run(run_id, RunStage.BRAIN_UPDATED)

                self._draft_manager.mark_status(status=DraftStatus.SENT)
                self._context_state.mark_sent()

                payload = _parse_json_dict(run.payload_json)
                issue_date = str(payload.get("issue_date") or datetime.now(UTC).date().isoformat())
                db_backup = backup_run_state_db(self._config)
                brain_backup = backup_brain_snapshot(self._config, issue_date=issue_date)
                self._post_status(
                    f"Run `{run_id}` complete. Newsletter sent and brain updated.",
                )
                self._logger.info(
                    "run_completed",
                    context=context,
                    db_backup=str(db_backup) if db_backup else None,
                    brain_backup=str(brain_backup) if brain_backup else None,
                )

            return OrchestrationOutcome(accepted=True, reason="sent", run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            self._run_state.set_run_error(run_id, str(exc))
            self._record_failure(run_id=run_id, stage="send", error=str(exc), payload={})
            self._logger.error("send_failed", context=context, error=str(exc))
            self._post_status(f"Run `{run_id}` send failed: {exc}")
            return OrchestrationOutcome(accepted=False, reason="send_failed", run_id=run_id)

    def _ensure_send_requested(self, run: Any) -> Any | None:
        if run.stage != RunStage.DRAFT_READY:
            return run

        draft = self._run_state.get_draft_state(run.run_id)
        if draft is None:
            self._run_state.set_run_error(run.run_id, "No draft found for run")
            return None
        if draft.draft_status != DraftStatus.APPROVED:
            return None

        run = self._run_state.transition_run(run.run_id, RunStage.SEND_REQUESTED)
        self._post_status(f"Run `{run.run_id}`: send requested after approval.")
        return run

    def _validate_current_draft_for_send(self, run_id: str) -> list[str]:
        draft = self._run_state.get_draft_state(run_id)
        if draft is None:
            return ["Draft state missing"]

        errors: list[str] = []
        if not draft.draft_html:
            errors.append("Draft HTML missing")
        else:
            errors.extend(validate_rendered_html(draft.draft_html))

        if not draft.draft_json:
            errors.append("Draft JSON missing")
        else:
            payload = _parse_json_dict(draft.draft_json)
            errors.extend(validate_https_links(payload))

        return errors

    def _append_brain_entries(self, run_id: str) -> None:
        draft = self._run_state.get_draft_state(run_id)
        if draft is None or draft.draft_json is None:
            raise RunStateError("No draft JSON available for brain update")

        payload = _parse_json_dict(draft.draft_json)
        issue_date = str(payload.get("issue_date") or datetime.now(UTC).date().isoformat())
        stories = payload.get("industry_stories")
        entries: list[tuple[str, str]] = []
        if isinstance(stories, list):
            for story in stories:
                if not isinstance(story, dict):
                    continue
                title = str(story.get("headline", "")).strip()
                url = str(story.get("source_url", "")).strip()
                if title and url:
                    entries.append((title, url))

        append_published_stories(self._config.brain_file_path, issue_date, entries)

    def _post_draft_preview(
        self,
        *,
        newsletter_payload: dict[str, Any],
        header: str,
        footer: str,
    ) -> str:
        preview = self._formatter.format_preview(newsletter_payload)
        header_block = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{header}*"},
        }
        footer_block = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": footer},
        }

        first_ts = ""
        for index, message_blocks in enumerate(preview.messages):
            blocks = list(message_blocks)
            if index == 0:
                blocks = [
                    header_block,
                    {"type": "divider"},
                    *blocks,
                    {"type": "divider"},
                    footer_block,
                ]
            response = self._send_message(
                channel=self._config.newsletter_channel_id,
                text=header if index == 0 else f"{header} (continued)",
                blocks=blocks,
                thread_ts=first_ts or None,
            )
            if index == 0:
                first_ts = response.get("ts", "")

        if first_ts:
            self._post_full_draft_snippet(thread_ts=first_ts, markdown=preview.full_draft_snippet)
        return first_ts or str(time.time())

    def _post_full_draft_snippet(self, *, thread_ts: str, markdown: str) -> None:
        heading = "View full draft (canonical markdown preview):"
        chunks = _chunk_text(markdown, max_chars=2800)
        self._send_message(
            channel=self._config.newsletter_channel_id,
            thread_ts=thread_ts,
            text=heading,
        )
        for chunk in chunks:
            self._send_message(
                channel=self._config.newsletter_channel_id,
                thread_ts=thread_ts,
                text=f"```\n{chunk}\n```",
            )

    def _record_failure(
        self,
        *,
        run_id: str,
        stage: str,
        error: str,
        payload: dict[str, Any],
    ) -> None:
        save_dead_letter(
            failure_dir=self._config.failure_log_dir,
            stage=stage,
            run_id=run_id,
            error=error,
            payload=payload,
        )

    def _post_status(self, text: str) -> None:
        self._send_message(channel=self._config.newsletter_channel_id, text=text)

    def _send_message(
        self,
        *,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if blocks is not None:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        if self._slack_client is None:
            return {"ok": True, "ts": str(time.time())}

        response = self._slack_client.chat_postMessage(**payload)
        if isinstance(response, dict):
            return response
        if hasattr(response, "data") and isinstance(response.data, dict):
            return response.data
        return {"ok": True, "ts": str(time.time())}

    @staticmethod
    def _generate_run_id(trigger: str) -> str:
        now = datetime.now(UTC)
        safe_trigger = re.sub(r"[^a-z0-9_-]+", "-", trigger.lower()).strip("-") or "run"
        return f"{now.strftime('%Y-%m-%d')}-{safe_trigger}-{now.strftime('%H%M%S')}"


def _parse_json_dict(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object payload")
    return data


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n", 0, max_chars)
        if split_at < 0:
            split_at = max_chars
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _squash_text(value: str, *, max_chars: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
