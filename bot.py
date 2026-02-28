"""Newsletter agent entrypoint.

This module initializes Slack Bolt, pipeline orchestration, and scheduler runtime.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import AppConfig, get_config
from listeners.approval import ApprovalHandler
from listeners.feedback import FeedbackHandler
from listeners.intent import IntentClassifier
from listeners.router import MessageDispatcher, RoutingOutcome
from listeners.slash_commands import SlashCommandHandlers
from listeners.updates import TeamUpdateHandler
from scheduler import SchedulerRuntime
from services.command_controller import CommandController, CommandResult
from services.contact_importer import ContactImporter
from services.context_state import ConversationState
from services.draft_manager import DraftManager
from services.formatter import SlackPreviewFormatter
from services.hacker_news import HackerNewsReader
from services.llm import OpenRouterClient
from services.news_researcher import NewsResearcher
from services.observability import LogContext, get_logger
from services.orchestrator import NewsletterOrchestrator
from services.planner import NewsletterPlanner
from services.renderer import NewsletterRenderer
from services.research_pipeline import ResearchPipeline
from services.rss_reader import RSSReader
from services.run_state import RunStateStore
from services.runtime_paths import bootstrap_runtime_paths
from services.sender import ResendSender
from services.slack_reader import SlackReader
from services.writer import NewsletterWriter


@dataclass(frozen=True)
class BotRuntime:
    """Container for initialized bot runtime dependencies."""

    app: App
    dispatcher: MessageDispatcher
    orchestrator: NewsletterOrchestrator
    scheduler: SchedulerRuntime


def _to_command_result(outcome: Any) -> CommandResult:
    accepted = bool(getattr(outcome, "accepted", False))
    reason = str(getattr(outcome, "reason", "unknown"))
    return CommandResult(accepted=accepted, reason=reason)


def _build_runtime(config: AppConfig) -> BotRuntime:
    run_state = RunStateStore(config.run_state_db_path)
    run_state.initialize()

    logger = get_logger()
    draft_manager = DraftManager(config, run_state)
    llm_client = OpenRouterClient(config)
    context_state = ConversationState.from_store(run_state)

    slack_reader = SlackReader(config)
    rss_reader = RSSReader(config)
    hn_reader = HackerNewsReader(config)
    researcher = NewsResearcher(llm_client)

    grok_researcher = None
    if config.enable_grok_research:
        from services.grok_researcher import GrokResearcher

        grok_researcher = GrokResearcher(llm_client, enabled=True)

    research_pipeline = ResearchPipeline(
        config=config,
        slack_reader=slack_reader,
        rss_reader=rss_reader,
        hacker_news_reader=hn_reader,
        news_researcher=researcher,
        grok_researcher=grok_researcher,
    )

    planner = NewsletterPlanner(config, llm_client)
    writer = NewsletterWriter(config, llm_client)
    renderer = NewsletterRenderer(configure_template_path())
    formatter = SlackPreviewFormatter()
    sender = ResendSender(config)

    app = App(token=config.slack_bot_token)
    auth_payload: Any
    try:
        auth_payload = app.client.auth_test()
    except Exception:  # noqa: BLE001
        auth_payload = {}
    bot_user_id = _resolve_bot_user_id(auth_payload)

    orchestrator = NewsletterOrchestrator(
        config=config,
        run_state=run_state,
        draft_manager=draft_manager,
        context_state=context_state,
        research_pipeline=research_pipeline,
        planner=planner,
        writer=writer,
        renderer=renderer,
        formatter=formatter,
        sender=sender,
        slack_client=app.client,
        logger=logger,
    )

    def _revision_builder(feedback_text: str) -> tuple[dict[str, Any], str, str]:
        return orchestrator.build_feedback_revision(feedback_text=feedback_text)

    approval_handler = ApprovalHandler(draft_manager)
    feedback_handler = FeedbackHandler(draft_manager, _revision_builder)
    update_handler = TeamUpdateHandler(llm_client=llm_client, context_state=context_state)
    intent_classifier = IntentClassifier(llm_client)

    command_controller = CommandController(
        run_callback=lambda: _to_command_result(
            orchestrator.trigger_run(trigger="manual", requested_by="manual-command")
        ),
        reset_callback=lambda: _to_command_result(
            orchestrator.reset_and_trigger_run(requested_by="reset-command")
        ),
        include_late_update_callback=lambda thread_ts: _to_command_result(
            orchestrator.include_late_update(thread_ts=thread_ts)
        ),
        replay_callback=lambda run_id: _to_command_result(orchestrator.replay_run(run_id=run_id)),
    )

    contact_importer = ContactImporter(
        resend_api_key=config.resend_api_key,
        audience_id=config.resend_audience_id,
    )

    # --- Slash command handlers ---
    slash_handlers = SlashCommandHandlers(
        command_controller=command_controller,
        approval_handler=approval_handler,
        contact_importer=contact_importer,
        orchestrator=orchestrator,
        slack_client=app.client,
        channel_id=config.newsletter_channel_id,
    )

    @app.command("/run")
    def _cmd_run(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_run(ack, respond, command)

    @app.command("/reset")
    def _cmd_reset(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_reset(ack, respond, command)

    @app.command("/replay")
    def _cmd_replay(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_replay(ack, respond, command)

    @app.command("/approve")
    def _cmd_approve(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_approve(ack, respond, command)

    @app.command("/import-contacts")
    def _cmd_import_contacts(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_import_contacts(ack, respond, command)

    @app.command("/help")
    def _cmd_help(ack: Any, respond: Any, command: dict[str, Any]) -> None:
        slash_handlers.handle_help(ack, respond, command)

    # --- Message dispatcher (intent-based routing) ---
    dispatcher = MessageDispatcher(
        bot_user_id=bot_user_id,
        draft_manager=draft_manager,
        context_state=context_state,
        approval_handler=approval_handler,
        feedback_handler=feedback_handler,
        update_handler=update_handler,
        intent_classifier=intent_classifier,
        on_include_late_update=command_controller.include_late_update,
    )

    @app.event("message")
    def _on_message(event: dict[str, Any], say: Any) -> None:
        try:
            outcome = dispatcher.dispatch(event)
        except Exception as exc:  # noqa: BLE001
            thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
            say(
                text=(f"Message handling failed. Manual intervention may be needed: {exc}"),
                thread_ts=thread_ts or None,
            )
            return

        if outcome.action == "approval" and outcome.detail == "approved":
            run_id = str((outcome.payload or {}).get("run_id") or "")
            send_outcome = orchestrator.send_approved_run(run_id=run_id)
            outcome = RoutingOutcome(
                action="approval",
                detail="sent" if send_outcome.accepted else f"send_failed:{send_outcome.reason}",
                payload={"run_id": run_id},
            )

        _respond_to_outcome(outcome=outcome, event=event, say=say)

    scheduler_runtime = SchedulerRuntime(config=config, orchestrator=orchestrator)
    return BotRuntime(
        app=app,
        dispatcher=dispatcher,
        orchestrator=orchestrator,
        scheduler=scheduler_runtime,
    )


def configure_template_path() -> Any:
    from pathlib import Path

    return Path(__file__).parent / "templates/newsletter_base.html"


def _resolve_bot_user_id(auth_payload: Any) -> str:
    if isinstance(auth_payload, dict):
        return str(auth_payload.get("user_id", ""))
    if hasattr(auth_payload, "data") and isinstance(auth_payload.data, dict):
        return str(auth_payload.data.get("user_id", ""))
    return ""


def _respond_to_outcome(*, outcome: RoutingOutcome, event: dict[str, Any], say: Any) -> None:
    thread_ts = str(event.get("thread_ts") or event.get("ts") or "")

    if outcome.action == "ignore":
        return

    if outcome.action == "agent_response":
        response_text = (outcome.payload or {}).get("response", "")
        if response_text:
            say(text=response_text, thread_ts=thread_ts)
        return

    if outcome.action == "approval":
        messages = {
            "draft_stale": (
                "Draft is stale (>48h). Please trigger a fresh research run before approval."
            ),
            "not_latest_draft_thread": "Approval must be posted in the latest draft thread.",
            "no_active_draft": "No active draft found to approve.",
            "draft_not_pending": "Draft is not pending review.",
            "draft_missing_ts": "Draft metadata is incomplete. Please reset and rerun.",
            "sent": "Approval received. Newsletter send pipeline completed.",
        }
        if outcome.detail.startswith("send_failed:"):
            reason = outcome.detail.split(":", 1)[1]
            say(text=f"Approval accepted but send failed: {reason}", thread_ts=thread_ts)
            return
        say(
            text=messages.get(outcome.detail, f"Approval rejected: {outcome.detail}"),
            thread_ts=thread_ts,
        )
        return

    if outcome.action == "feedback":
        if outcome.detail == "revised":
            version = outcome.payload.get("draft_version") if outcome.payload else None
            say(text=f"Feedback applied. Draft updated to v{version}.", thread_ts=thread_ts)
            return
        if outcome.detail == "max_revisions_reached":
            say(
                text=(
                    "Maximum revisions reached. Use `/reset` to run a fresh cycle."
                ),
                thread_ts=thread_ts,
            )
            return
        say(text=f"Feedback ignored: {outcome.detail}", thread_ts=thread_ts)
        return

    if outcome.action == "late_update_prompt":
        say(
            text=(
                "This update arrived after this week's collection window. "
                "Reply 'include' to add it to the current draft, or it will be picked up next week."
            ),
            thread_ts=thread_ts,
        )
        return

    if outcome.action == "late_update_include":
        if outcome.detail == "included":
            say(
                text=("Late update included in the current draft and a redraft was posted."),
                thread_ts=thread_ts,
            )
            return
        say(text=f"Late update include failed: {outcome.detail}", thread_ts=thread_ts)
        return

    if outcome.action == "team_update" and outcome.detail == "needs_clarification":
        questions = []
        if outcome.payload:
            questions = [str(item) for item in outcome.payload.get("questions", [])]
        if not questions:
            say(text="Could you add more detail/context for this update?", thread_ts=thread_ts)
            return
        question_text = "\n".join(f"- {question}" for question in questions)
        say(text=f"Thanks. A few clarifications would help:\n{question_text}", thread_ts=thread_ts)
        return

    if outcome.action == "clarification_context":
        say(text="Thanks — context noted. ✅", thread_ts=thread_ts)
        return

    if outcome.action == "late_update_thread":
        # User replied in a late-update thread without saying "include" —
        # silently noted or ignore.
        return

    if outcome.action == "team_update" and outcome.detail == "clear":
        say(text="Update captured. ✅", thread_ts=thread_ts)
        return


def _install_signal_handlers(
    socket_handler: SocketModeHandler, scheduler: SchedulerRuntime
) -> None:
    def _shutdown(_signum: int, _frame: Any) -> None:
        scheduler.shutdown()
        try:
            socket_handler.close()
        except Exception:  # noqa: BLE001
            return

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def main() -> None:
    """Run the newsletter bot process."""
    config = get_config()
    bootstrap_runtime_paths(config)

    runtime = _build_runtime(config)
    runtime.scheduler.start()

    handler = SocketModeHandler(runtime.app, config.slack_app_token)
    _install_signal_handlers(handler, runtime.scheduler)

    logger = get_logger()
    logger.info(
        "bot_started",
        context=LogContext(),
        channel_id=config.newsletter_channel_id,
        dry_run=config.enable_dry_run,
    )
    handler.start()


if __name__ == "__main__":
    main()
