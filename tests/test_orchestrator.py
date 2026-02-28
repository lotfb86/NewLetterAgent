"""Tests for newsletter orchestration and send safety flow."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import AppConfig
from models import Confidence, DraftStatus, SourceTier, StoryCandidate
from services.context_state import ConversationState
from services.draft_manager import DraftManager
from services.formatter import SlackPreviewResult
from services.orchestrator import NewsletterOrchestrator
from services.research_pipeline import RankedStory, WeeklyResearchBundle
from services.run_state import RunStage, RunStateStore
from services.runtime_paths import bootstrap_runtime_paths


class _FakeSlackClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._counter = 0

    def chat_postMessage(self, **payload: Any) -> dict[str, Any]:
        self._counter += 1
        ts = f"{self._counter}.0"
        self.messages.append({"ts": ts, **payload})
        return {"ok": True, "ts": ts}


class _FakeResearchPipeline:
    def run_weekly(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        published_stories: list[Any],
    ) -> WeeklyResearchBundle:
        del published_stories
        story = StoryCandidate(
            title="Agent startup raises $25M",
            source_url="https://example.com/story",
            source_name="Example",
            published_at=end_at,
            confidence=Confidence.HIGH,
            source_tier=SourceTier.TIER_1,
            summary="Funding news",
        )
        planning_item: dict[str, str | int | None] = {
            "title": story.title,
            "source_url": story.source_url,
            "source_name": story.source_name,
            "published_at": story.published_at.isoformat() if story.published_at else None,
            "confidence": story.confidence.value,
            "source_tier": story.source_tier.value,
            "summary": story.summary,
        }
        return WeeklyResearchBundle(
            start_at=start_at,
            end_at=end_at,
            team_updates=(),
            source_stories=(story,),
            perplexity_results=(),
            candidate_stories=(story,),
            ranked_stories=(RankedStory(story=story, score=2.0, reasons=("funding",)),),
            planning_inputs=(planning_item,),
        )


class _FakePlanner:
    def create_plan(self, **_: Any) -> dict[str, Any]:
        return {
            "team_section": {"include": True, "items": []},
            "industry_section": {"items": []},
            "cta": {"text": "Contact us"},
        }


class _FakeWriter:
    def write_newsletter(self, **kwargs: Any) -> dict[str, Any]:
        issue_date = kwargs["issue_date"]
        return _sample_newsletter_payload(issue_date=issue_date)

    def revise_newsletter(self, *, current_draft: dict[str, Any], feedback_text: str) -> dict[str, Any]:
        revised = dict(current_draft)
        revised["intro"] = f"{current_draft.get('intro', '')} ({feedback_text})"
        return revised


class _FakeRenderer:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid

    def render(self, newsletter_payload: dict[str, Any]) -> str:
        if self.invalid:
            return "<html><body>missing required links</body></html>"

        first_story = newsletter_payload["industry_stories"][0]
        return (
            "<html><body>"
            "What We've Been Up To"
            "This Week in AI"
            f"<a href='{first_story['source_url']}'>story</a>"
            f"<a href='{newsletter_payload['cta']['url']}'>cta</a>"
            "<a href='{{{RESEND_UNSUBSCRIBE_URL}}}'>unsubscribe</a>"
            "</body></html>"
        )


class _FakeFormatter:
    def format_preview(self, newsletter_payload: dict[str, Any]) -> SlackPreviewResult:
        text = newsletter_payload.get("intro", "")
        return SlackPreviewResult(
            messages=(({"type": "section", "text": {"type": "mrkdwn", "text": text}},),),
            full_draft_snippet=text,
        )


class _FakeSender:
    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.created = 0
        self.sent = 0

    def create_broadcast(
        self,
        *,
        audience_id: str,
        from_email: str,
        subject: str,
        html: str,
    ) -> Any:
        del audience_id, from_email, subject, html
        self.created += 1
        return type(
            "BroadcastResult",
            (),
            {
                "broadcast_id": f"broadcast-{self.created}",
                "raw_response": {"id": f"broadcast-{self.created}"},
            },
        )()

    def send_broadcast(self, *, broadcast_id: str) -> dict[str, Any]:
        self.sent += 1
        status = "skipped_dry_run" if self.dry_run else "sent"
        return {"id": broadcast_id, "status": status}



def _build_config(tmp_path: Path, *, enable_dry_run: bool = True) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        openrouter_api_key="sk",
        slack_bot_token="xoxb",
        slack_app_token="xapp",
        newsletter_channel_id="C_NEWS",
        resend_api_key="re",
        resend_audience_id="aud",
        newsletter_from_email="newsletter@example.com",
        timezone="America/Chicago",
        research_day="thu",
        research_hour=9,
        brain_file_path=data_dir / "published_stories.md",
        dedup_lookback_weeks=12,
        run_state_db_path=data_dir / "run_state.db",
        failure_log_dir=data_dir / "failures",
        max_external_retries=3,
        max_draft_versions=5,
        enable_dry_run=enable_dry_run,
        heartbeat_channel_id="C_HEARTBEAT",
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )



def _build_orchestrator(
    tmp_path: Path,
    *,
    sender_dry_run: bool,
    invalid_renderer: bool = False,
) -> tuple[NewsletterOrchestrator, DraftManager, RunStateStore, _FakeSlackClient, _FakeSender, AppConfig]:
    config = _build_config(tmp_path, enable_dry_run=sender_dry_run)
    bootstrap_runtime_paths(config)

    run_state = RunStateStore(config.run_state_db_path)
    run_state.initialize()
    draft_manager = DraftManager(config, run_state)
    context_state = ConversationState()
    slack_client = _FakeSlackClient()
    sender = _FakeSender(dry_run=sender_dry_run)

    orchestrator = NewsletterOrchestrator(
        config=config,
        run_state=run_state,
        draft_manager=draft_manager,
        context_state=context_state,
        research_pipeline=_FakeResearchPipeline(),  # type: ignore[arg-type]
        planner=_FakePlanner(),  # type: ignore[arg-type]
        writer=_FakeWriter(),  # type: ignore[arg-type]
        renderer=_FakeRenderer(invalid=invalid_renderer),  # type: ignore[arg-type]
        formatter=_FakeFormatter(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        slack_client=slack_client,
    )
    return orchestrator, draft_manager, run_state, slack_client, sender, config



def _latest_run_id(run_state: RunStateStore) -> str:
    runs = run_state.list_runs()
    assert runs
    return runs[-1].run_id



def _sample_newsletter_payload(*, issue_date: str) -> dict[str, Any]:
    return {
        "newsletter_name": "AI Weekly",
        "issue_date": issue_date,
        "subject_line": "This Week in AI",
        "preheader": "Top AI stories",
        "intro": "Hello team",
        "team_updates": [{"title": "Launch", "summary": "Shipped a new workflow"}],
        "industry_stories": [
            {
                "headline": "Agent startup raises $25M",
                "hook": "Funding momentum continues",
                "why_it_matters": "Signals enterprise demand for agent tooling",
                "source_url": "https://example.com/story",
                "source_name": "Example",
                "published_at": "2026-02-27T00:00:00Z",
                "confidence": "high",
            }
        ],
        "cta": {"text": "Book a strategy call", "url": "https://example.com/contact"},
    }



def test_trigger_run_creates_draft_and_posts_preview(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, slack_client, sender, _ = _build_orchestrator(
        tmp_path,
        sender_dry_run=True,
    )

    outcome = orchestrator.trigger_run(trigger="manual")

    assert outcome.accepted
    assert outcome.reason == "run_completed"
    assert sender.created == 0
    assert slack_client.messages

    run = run_state.get_run(outcome.run_id or "")
    assert run is not None
    assert run.stage == RunStage.DRAFT_READY

    draft = draft_manager.get_current_draft()
    assert draft is not None
    assert draft.draft_version == 1
    assert draft.draft_status == DraftStatus.PENDING_REVIEW



def test_send_pipeline_completes_and_writes_backups(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, config = _build_orchestrator(
        tmp_path,
        sender_dry_run=False,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)

    draft_manager.mark_status(status=DraftStatus.APPROVED)
    send_outcome = orchestrator.send_approved_run(run_id=run_id)

    assert send_outcome.accepted
    assert sender.created == 1
    assert sender.sent == 1

    run = run_state.get_run(run_id)
    assert run is not None
    assert run.stage == RunStage.BRAIN_UPDATED

    current = draft_manager.get_current_draft()
    assert current is not None
    assert current.draft_status == DraftStatus.SENT

    assert config.run_state_db_path.with_suffix(".db.bak").exists()
    assert list((config.brain_file_path.parent / "archive").glob("published_stories_*.md"))



def test_full_dry_run_path_skips_live_send(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=True,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)
    draft_manager.mark_status(status=DraftStatus.APPROVED)

    send_outcome = orchestrator.send_approved_run(run_id=run_id)

    assert send_outcome.accepted
    assert sender.created == 1
    assert sender.sent == 1

    run = run_state.get_run(run_id)
    assert run is not None
    assert run.stage == RunStage.BRAIN_UPDATED


def test_send_validation_failure_stays_send_requested(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, _sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=True,
        invalid_renderer=True,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)

    draft_manager.mark_status(status=DraftStatus.APPROVED)
    send_outcome = orchestrator.send_approved_run(run_id=run_id)

    assert not send_outcome.accepted
    assert send_outcome.reason == "render_validation_failed"

    run = run_state.get_run(run_id)
    assert run is not None
    assert run.stage == RunStage.SEND_REQUESTED



def test_include_late_update_injects_into_draft_json(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, _sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=True,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)

    current = draft_manager.get_current_draft()
    assert current is not None

    # Seed late-update payload as if the update listener had already prompted include/skip.
    orchestrator._context_state.record_late_update("123.45", "Important late customer launch")  # noqa: SLF001

    include_outcome = orchestrator.include_late_update(thread_ts="123.45")

    assert include_outcome.accepted
    assert include_outcome.reason == "included"
    assert include_outcome.run_id == run_id
    assert include_outcome.draft_version == 2

    updated = draft_manager.get_current_draft()
    assert updated is not None
    payload = json.loads(updated.draft_json or "{}")
    titles = [item["title"] for item in payload["team_updates"]]
    assert "Late Team Update" in titles



def test_replay_resumes_send_from_send_requested(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=False,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)

    draft_manager.mark_status(status=DraftStatus.APPROVED)
    run_state.transition_run(run_id, RunStage.SEND_REQUESTED)

    replay = orchestrator.replay_run(run_id=run_id)

    assert replay.accepted
    assert replay.reason == "sent"
    assert sender.sent == 1

    run = run_state.get_run(run_id)
    assert run is not None
    assert run.stage == RunStage.BRAIN_UPDATED



def test_second_send_attempt_is_idempotently_rejected(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=False,
    )
    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)
    draft_manager.mark_status(status=DraftStatus.APPROVED)

    first = orchestrator.send_approved_run(run_id=run_id)
    second = orchestrator.send_approved_run(run_id=run_id)

    assert first.accepted
    assert not second.accepted
    assert second.reason == "already_sent"
    assert sender.sent == 1

    brain_entries = (tmp_path / "data" / "published_stories.md").read_text(encoding="utf-8")
    assert brain_entries.count("Agent startup raises $25M") == 1
